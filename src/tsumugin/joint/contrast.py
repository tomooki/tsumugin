"""コントラスト駆動の占有率解放推奨 (M4 / REQ-010/011/012/103/104 / FR-244)。

joint (X 線 + 中性子など probe 種の異なる複数ヒストグラム) が揃ったときにのみ、
サイトの占有元素対 (A,B) が「X 線と中性子でコントラストが十分異なる」かを判定し、
占有率パラメータの解放を *提案* する。**自動適用は一切しない** — 副作用は ledger
記録のみで、``phases`` も占有率も書き換えない (P2 非破壊 / REQ-011)。

散乱長 / 原子番号は軽量な静的テーブルとして同梱し、xraylib 等の重依存を持たない
(REQ-403)。numpy のみに依存する。

【設計判断: サイト→占有元素対 (A,B) の供給元】
``PhaseInstance.occupancies`` は ``Mapping[str, float]`` (site→占有率スカラ) であり、
混合サイトで競合する 2 元素 (A,B) を表現できない。既存モデルを破壊せず契約
(``OccupancyReleaseRecommendation.elements: tuple[str, str]``) を満たすため、
site→(elemA, elemB) は ``ContrastConfig.site_elements`` で供給する。相 (``model.phases``)
は phase_index 反復と joint 条件判定 (ヒスト数・probe 種別) に用いる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..model import PhaseInstance
from ..store.ledger import Ledger
from .model import JointRefinementModel

# ---------------------------------------------------------------------------
# 静的テーブル (軽量同梱・重依存なし / REQ-010/403)
# ---------------------------------------------------------------------------

# 元素記号 → 中性子コヒーレント散乱長 b [fm] (代表値)。
# 出典: NIST Neutron scattering lengths and cross sections
#   (V. F. Sears, Neutron News 3 (1992) 26) の bound coherent scattering length。
# 電池 / 酸化物系で使う主要元素を代表値でカバーする。
NEUTRON_B_TABLE: Mapping[str, float] = {
    "H": -3.739,
    "Li": -1.90,
    "B": 5.30,
    "C": 6.646,
    "N": 9.36,
    "O": 5.803,
    "F": 5.654,
    "Na": 3.63,
    "Mg": 5.375,
    "Al": 3.449,
    "Si": 4.1491,
    "P": 5.13,
    "S": 2.847,
    "Cl": 9.577,
    "K": 3.67,
    "Ca": 4.70,
    "Ti": -3.438,
    "V": -0.3824,
    "Cr": 3.635,
    "Mn": -3.73,
    "Fe": 9.45,
    "Co": 2.49,
    "Ni": 10.3,
    "Cu": 7.718,
    "Zn": 5.680,
    "Ga": 7.288,
    "Ge": 8.185,
    "Zr": 7.16,
    "Nb": 7.054,
    "Mo": 6.715,
    "Sn": 6.225,
    "La": 8.24,
    "W": 4.86,
}

# 元素記号 → 原子番号 Z。X 線散乱因子 f(0) の近似として Z を用いる (REQ-010)。
XRAY_Z_TABLE: Mapping[str, int] = {
    "H": 1,
    "Li": 3,
    "B": 5,
    "C": 6,
    "N": 7,
    "O": 8,
    "F": 9,
    "Na": 11,
    "Mg": 12,
    "Al": 13,
    "Si": 14,
    "P": 15,
    "S": 16,
    "Cl": 17,
    "K": 19,
    "Ca": 20,
    "Ti": 22,
    "V": 23,
    "Cr": 24,
    "Mn": 25,
    "Fe": 26,
    "Co": 27,
    "Ni": 28,
    "Cu": 29,
    "Zn": 30,
    "Ga": 31,
    "Ge": 32,
    "Zr": 40,
    "Nb": 41,
    "Mo": 42,
    "Sn": 50,
    "La": 57,
    "W": 74,
}


# ---------------------------------------------------------------------------
# 型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OccupancyReleaseRecommendation:
    """コントラスト十分サイトの占有率解放推奨 (提案のみ・自動適用しない)。🔵 REQ-011/012"""

    phase_index: int  # 【相 index】
    site: str  # 【サイト識別 (占有率キー)】
    elements: tuple[str, str]  # 【占有元素対 (A,B)・記号昇順】 (REQ-402)
    contrast: float  # 【|f_norm - b_norm|】
    param_name: str  # 【解放候補パラメータ名 "global.occ.{site}" 等】
    rationale: str  # 【なぜ推奨したか (ledger 記録用)】 (REQ-012)


@dataclass(frozen=True)
class ContrastConfig:
    """コントラスト判定設定。🔵 REQ-010

    【設計判断】: ``site_elements`` は site (占有率キー) → 占有元素対 (elemA, elemB) の
    マッピング。``PhaseInstance`` は混合サイトの 2 元素を表現できないため、契約
    ``OccupancyReleaseRecommendation.elements`` の供給元としてここで受ける。空なら
    判定対象サイトが無く、常に空推奨を返す。
    """

    # 【|f_norm - b_norm| 閾値】(D4): 正規化差 (f_norm, b_norm ともに [0,1] 近傍) の典型スケールに対し、
    #   コントラストが有意と言える経験的下限。0.15 は X線/中性子で片方のみ寄与が大きい元素対
    #   (例 Li/O のように中性子で b 符号差、X線で Z 差が小) を拾える保守値。ベンチで較正予定 (D4)。
    contrast_threshold: float = 0.15
    site_elements: Mapping[str, tuple[str, str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------


def _is_joint(model: JointRefinementModel) -> bool:
    """joint 条件: ヒスト数 ≥ 2 かつ distinct probe 種別 ≥ 2 (REQ-104/EDGE-004)。"""
    histograms = model.histograms
    if len(histograms) < 2:
        return False
    probes = {h.probe for h in histograms}
    return len(probes) >= 2


def _both_tables_have(element: str) -> bool:
    """element が Z / b 両テーブルに収録されているか (F8)。

    ``_contrast`` は ``XRAY_Z_TABLE`` と ``NEUTRON_B_TABLE`` の双方を参照するため、片方のみ
    収録の元素は判定不能であり、事前確認して KeyError を回避するための不変条件ヘルパ。
    """
    return element in XRAY_Z_TABLE and element in NEUTRON_B_TABLE


def _contrast(elem_a: str, elem_b: str) -> float:
    """(A,B) の f_norm / b_norm を計算し |f_norm - b_norm| を返す。

    f ≈ Z (X 線散乱因子近似)、b は中性子コヒーレント散乱長 [fm]。
    f_norm = f_A / (f_A + f_B)、b_norm = b_A / (|b_A| + |b_B|)。
    """
    f_a = float(XRAY_Z_TABLE[elem_a])
    f_b = float(XRAY_Z_TABLE[elem_b])
    b_a = NEUTRON_B_TABLE[elem_a]
    b_b = NEUTRON_B_TABLE[elem_b]
    f_norm = f_a / (f_a + f_b)
    b_norm = b_a / (abs(b_a) + abs(b_b))
    return abs(f_norm - b_norm)


def recommend_occupancy_release(
    phases: tuple[PhaseInstance, ...],
    model: JointRefinementModel,
    *,
    config: ContrastConfig = ContrastConfig(),
    ledger: Ledger | None = None,
) -> tuple[OccupancyReleaseRecommendation, ...]:
    """コントラスト十分サイトの占有率解放を推奨する (自動適用しない)。🔵 REQ-010/011/FR-244

    【joint 条件】: joint データ (ヒスト数 ≥ 2 かつ probe 種別 ≥ 2) がある場合のみ発火。
      単一ヒスト / 単一 probe 種は空を返す (REQ-104/EDGE-004)。
    【判定】: 各サイトの占有元素対 (A,B) で f_norm=f_A/(f_A+f_B)・b_norm=b_A/(|b_A|+|b_B|)
      を計算し |f_norm-b_norm| >= threshold のサイトを検出。全サイト閾値未満なら
      空・警告なし (REQ-103/EDGE-003)。
    【記録】: 各推奨を ledger.append("contrast_occupancy_recommend", {...}) で理由付き記録
      (REQ-012)。ledger=None なら記録スキップ (結果は ledger 有無で不変)。
    【非破壊】: 提案のみ。``phases`` / 占有率は一切書き換えない (REQ-011)。
    【決定論】: 元素は記号昇順で (A,B) を正規化、サイトは占有率キー昇順で評価 (REQ-402)。
    """
    # 【joint ゲート】: 単一ヒスト / 単一 probe 種は空 (REQ-104/EDGE-004) 🔵
    if not _is_joint(model):
        return ()

    recommendations: list[OccupancyReleaseRecommendation] = []
    threshold = config.contrast_threshold

    # 【相反復】: phase_index を保持しつつ各相の占有率サイトを昇順評価する 🔵
    for phase_index, phase in enumerate(phases):
        # 【サイトキー昇順】: 占有率キー昇順で決定論評価 (REQ-402) 🔵
        for site in sorted(phase.occupancies):
            pair = config.site_elements.get(site)
            if pair is None:
                continue  # 元素対未供給のサイトは判定対象外
            # 【元素記号昇順で正規化】: (A,B) を昇順へ (REQ-402) 🔵
            elem_a, elem_b = sorted(pair)
            # 【両テーブル収録確認 (F8)】: _contrast は Z / b 両テーブルを参照するため、どちらか
            #   一方でも未収録なら判定不能につきスキップし KeyError を回避する 🔵
            if not _both_tables_have(elem_a) or not _both_tables_have(elem_b):
                continue  # テーブル未収録元素は判定不能につきスキップ
            contrast = _contrast(elem_a, elem_b)
            # 【閾値判定】: 未満は提案せず・警告なし (REQ-103/EDGE-003) 🔵
            if contrast < threshold:
                continue
            param = f"global.occ.{site}"
            rationale = (
                f"phase{phase_index} site {site!r} 占有元素対 ({elem_a},{elem_b}) の "
                f"X線/中性子コントラスト |f_norm-b_norm|={contrast:.4f} が閾値 "
                f"{threshold:.4f} 以上のため、joint データで占有率 {param} の解放を推奨する。"
            )
            rec = OccupancyReleaseRecommendation(
                phase_index=phase_index,
                site=site,
                elements=(elem_a, elem_b),
                contrast=contrast,
                param_name=param,
                rationale=rationale,
            )
            recommendations.append(rec)
            # 【記録】: 理由付き append (ledger 提供時のみ / verify() 維持) 🔵 REQ-012
            if ledger is not None:
                ledger.append(
                    "contrast_occupancy_recommend",
                    {
                        "phase_index": phase_index,
                        "site": site,
                        "elements": [elem_a, elem_b],
                        "contrast": contrast,
                        "rationale": rationale,
                    },
                )

    return tuple(recommendations)
