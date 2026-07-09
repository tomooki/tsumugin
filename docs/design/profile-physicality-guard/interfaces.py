"""プロファイル物理性ガード 型・シグネチャ設計 (実装の契約)。

信頼性: 🔵 GSAS-II プロファイル定義 + 既存 validity.py/engine.py 精読。
本ファイルは設計成果物であり実行対象ではない (docs 配下)。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from tsumugin.autorietveld.model import Radiation, ValidityReport

# =====================================================================
# 純関数コア (validity.py に追加, numpy-only, GSAS 非依存)
# =====================================================================

# per-hist のプロファイル値 + 解放フラグ。{key: (value, refined)}
ProfileMap = Mapping[str, "tuple[float, bool]"]

# per-hist の評価レンジ。CW は (2θ_min_deg, 2θ_max_deg)、TOF は (d_min, d_max)。
# 取得不能な hist は None (レンジ依存判定を skip)。
RangeSpec = "tuple[float, float] | None"


def check_profile_physicality(
    *,
    profiles: Sequence[ProfileMap],
    radiations: Sequence[Radiation],
    ranges: Sequence[RangeSpec],
    sign_tol: float = 1e-3,
    shl_soft_max: float = 0.1,
    width_floor: float = 0.0,
) -> ValidityReport:
    """精密化後プロファイルの物理的妥当性を判定する (revert 用 hard + 警告用 soft)。

    判定 (放射源で分岐):
    - CW (X 線/CW 中性子):
      * ガウス幅正値性: H_G² = U·tan²θ + V·tanθ + W をレンジ端点 + 頂点で評価し
        min > width_floor か (U,V,W のいずれかが refined のとき hard)。
      * ローレンツ非負: X ≥ -sign_tol, Y ≥ -sign_tol (各々 refined のとき hard)。
      * 非対称下限: SH/L ≥ -sign_tol (refined のとき hard)。
      * 非対称 soft 上限: SH/L > shl_soft_max なら warnings (revert しない)。
    - TOF:
      * ガウス分散非負: σ² = sig-0 + sig-1·d² + sig-2·d⁴ をレンジ端点 + 頂点で評価し
        min ≥ -sign_tol か (sig-* のいずれかが refined のとき hard)。
      * 立上り/減衰 strict-pos: alpha, beta-0, beta-1 > 0 (refined のとき hard)。

    :param profiles: 各 hist の {key: (value, refined)}
    :param radiations: 各 hist の放射源 (profiles と同順)
    :param ranges: 各 hist の評価レンジ (CW=2θ°, TOF=d)。None はレンジ依存判定を skip
    :param sign_tol: 符号/非負判定の数値ノイズ許容 (負側)
    :param shl_soft_max: SH/L の soft 上限 (超過は警告のみ)
    :param width_floor: 幅二乗の下限 (既定 0.0)
    :returns: ValidityReport
      - passed: 全 **hard** チェック通過 (= revert しなくてよい)
      - checks: (name, ok, detail) の列 (hard のみ ok=False を持ちうる)
      - warnings: soft 逸脱・未解放違反・skip 理由
    :raises: なし (欠落/数値発散は skip/警告へ縮退, EDGE-001/002/003)
    """
    ...


# =====================================================================
# GSAS アダプタ (engine.py に追加, GSAS 遅延 import)
# =====================================================================


def _extract_profile(g2hists) -> tuple[dict[str, tuple[float, bool]], ...]:
    """各 hist の Instrument Parameters から {key: (value, refined)} を抽出。

    GSAS 格納形 inst[0][key] = [default, value, refine_flag]。key 集合は CW/TOF 双方の
    プロファイル関連キーに限定 (U,V,W,X,Y,SH/L,Zero,sig-0/1/2,alpha,beta-0/1,difC,difA)。
    欠落・構造差は当該 hist を空 dict に縮退 (EDGE-001)。
    """
    ...


def _profile_ranges(g2hists, radiations, profiles) -> tuple[tuple[float, float] | None, ...]:
    """各 hist の評価レンジ (CW=2θ°, TOF=d)。

    CW: getdata("x") の min/max (2θ 度)。
    TOF: getdata("x") (TOF μs) を d≈(t-Zero)/difC で換算 (difC,Zero は profiles から)。
    取得不能・difC 欠落/0 は None (EDGE-003)。
    """
    ...


def _profiles_physical(g2hists, radiations) -> ValidityReport:
    """_extract_profile + _profile_ranges を束ね check_profile_physicality を呼ぶラッパ。

    engine 段階ループで `if not _cells_physical(...) or not _profiles_physical(...).passed`
    のように使う。抽出不能時は passed=True (skip) に縮退。
    """
    ...


# =====================================================================
# model.py (既存, 変更なし — 参考)
# =====================================================================
# AutoRietveldResult.hist_profile: tuple[Mapping[str, float], ...] = ()
#   → 本機能で engine が充填する (TASK-0001 で追加済・未配線だった内省フィールド)。
# ValidityReport(passed: bool, checks: tuple[...] , warnings: tuple[str, ...])
#   → check_profile_physicality の返り値型。既存を再利用 (新型を作らない)。
