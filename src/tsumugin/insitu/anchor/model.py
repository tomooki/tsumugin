"""M10 アンカー基準双方向 operando 解析のデータモデル (frozen dataclass, numpy-only)。

信頼できるフレーム (アンカー) を起点に両隣アンカーへ双方向で精密化し、区間ごとに IC (bic) で
最良経路を選ぶための不変値オブジェクト群。GSAS-II / pymatgen / MP に非依存の純データ層
(`extract`/`segment`/`select`/`engine` がこれを組み立てる)。

信頼性: 🔵 `docs/design/m10-anchored-operando/architecture.md` §2 / FR-330。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Mapping

from ...autorietveld.model import CellEsd, PhaseSpec
from ..model import Cell, FrameRietveldResult

__all__ = [
    "AnchorConfig",
    "Anchor",
    "Segment",
    "SegmentPass",
    "CrossoverChoice",
]


@dataclass(frozen=True)
class AnchorConfig:
    """アンカー抽出・双方向解析・crossover 選定の設定。

    :param anchor_confidence_min: アンカー候補に要する合成信頼度の下限 (段階 A スクリーニング)。
    :param anchor_rwp_max: 確定アンカーに要する Rietveld Rwp の上限 (段階 B 確認)。
    :param require_anchor_validity: 確定アンカーに `check_validity` pass を要求するか。**既定 False** —
        `check_validity` は室温 CIF セルとの乖離を fail 判定するため、高温/時間系列では正当に格子が伸びた
        フレームを軒並み fail させ (M9 H1 と同根)、アンカーが取れず単一アンカーに縮退する (実測)。よって
        アンカーは Rwp + 信頼度で確定し、validity は既定で課さない。良い参照セルがある系のみ True。
    :param w_score: 信頼度合成の Dara スコア重み。
    :param w_margin: 信頼度合成のスコアマージン (top1−top2) 重み。
    :param w_strain: 信頼度合成の strain ペナルティ重み (小 strain=良)。
    :param w_unknown: 信頼度合成の未知相フラグ ペナルティ重み。
    :param margin_cap: スコアマージンの飽和上限 (これ以上のマージンは頭打ち)。
    :param bic_tie: crossover 選定で総 bic 同点とみなす許容差 (これ以内は単調性で tie-break)。
    :param base_params: bic の n_params 推定のベース (背景/プロファイル/ゼロ等の非相パラメータ)。
    :param per_phase_params: bic の n_params 推定の 1 相あたりパラメータ数 (scale+格子+プロファイル概算)。
    :param require_bond_validity: crossover 選定に結合距離/配位数の妥当性を課すか (pymatgen 不在は自動 skip)。
    :param bond_tol_lo: 最近接結合距離の許容下限倍率 (共有結合半径和に対する)。
    :param bond_tol_hi: 最近接結合距離の許容上限倍率。
    :param hysteresis_frames: 相 death 判定のヒステリシス窓 (連続本数)。点滅抑制。
    """

    anchor_confidence_min: float = 0.5
    anchor_rwp_max: float = 20.0
    require_anchor_validity: bool = False
    w_score: float = 1.0
    w_margin: float = 1.0
    w_strain: float = 2.0
    w_unknown: float = 0.5
    margin_cap: float = 0.5
    bic_tie: float = 2.0
    base_params: int = 30
    per_phase_params: int = 12
    require_bond_validity: bool = False
    bond_tol_lo: float = 0.7
    bond_tol_hi: float = 1.3
    hysteresis_frames: int = 2

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnchorConfig":
        """JSON 由来 dict から `AnchorConfig` を構成する (② `anchored_sequential` の JSON 経路)。

        全フィールドが単純型 (bool/int/float) なので、既定インスタンスの各値の型に強制する。
        **未知キーは ValueError** — ③ (JSON しか送れない LLM) の typo を黙って無視すると、
        設定したつもりのツマミが効かず「呼べるが黙って間違う」を再導入するため (§4.5)。
        空 dict は全既定。② 側は ValueError を error dict へ縮退させる。

        :raises ValueError: `data` に AnchorConfig に無いキーが含まれるとき
        """
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(
                f"unknown AnchorConfig keys: {sorted(unknown)} (known: {sorted(known)})"
            )
        defaults = cls()
        kwargs: dict[str, object] = {}
        for name, value in data.items():
            current = getattr(defaults, name)
            # bool は int のサブクラスなので先に判定する
            if isinstance(current, bool):
                kwargs[name] = bool(value)
            elif isinstance(current, int):
                kwargs[name] = int(value)  # type: ignore[arg-type]
            else:
                kwargs[name] = float(value)  # type: ignore[arg-type]
        return cls(**kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Anchor:
    """確定アンカー — 双方向区間解析のウォームスタート種。

    :param frame_index: アンカーのフレーム番号 (0 始まり)
    :param axis_value: 軸値 (温度/時間, None 可)
    :param phase_specs: このアンカーで確定した相集合 (warm-start 用の構造仕様)
    :param refined_cells: 相名→精密化格子 (warm-start 初期値)
    :param rwp: 段階 B Rietveld の Rwp
    :param gof: 段階 B Rietveld の GOF
    :param phase_fractions: 相名→相分率 (段階 B 結果; 出力フレーム組立用)
    :param confidence: 段階 A 合成信頼度
    :param validity_passed: 物理妥当性ゲート合格か
    :param n_obs: 段階 B の観測点数 (bic 用)
    :param fallback: fallback アンカー (確定 0 個時の最小 Rwp フレーム) か
    :param phase_weight_fractions: 相名→重量分率 (段階 B `AutoRietveldResult.phase_weight_fractions`
        由来)。出力フレーム (`engine._anchor_frame_result`) に esd 付き出版値を運ぶための貫通フィールド。
        既定空 dict で後方互換。
    :param phase_weight_fraction_esd: 相名→重量分率 esd (段階 B 由来)。要素 ``None`` = 多相なのに
        この精密化から決まっていない (レビュー第6巡)・単相は ``0.0`` (自明)。既定空 dict。
    :param cell_esd: 相名→格子 esd (a,b,c,α,β,γ; 段階 B 由来)。要素 ``None`` = 格子を解放して
        いない (凍結セル/未精密化)。``0.0`` は対称拘束で厳密に固定。既定空 dict。
    :param alkali: FR-318 の alkali_* フィールド (`insitu.charge.alkali_fields` の出力を段階 B で
        事前計算した貫通 dict; `engine._anchor_frame_result` が FrameRietveldResult へ展開する)。
        既定空 dict (機能無効/後方互換)。
    :param ab_check: FR-318 アンカー A/B 検証 (REQ-318-006)。単相アンカーで
        制約なし (A=本アンカー) vs 占有率を echem 目標に凍結 (B) の 2 精密化を比較した
        ``{"rwp_free", "rwp_constrained", "delta_rwp", "x_refined"|"x_model", "x_echem"}``。
        **x のキーは由来で変わる**: ``x_refined`` = A の占有率が実際に精密化された (esd 付き) /
        ``x_model`` = 占有率固定 (既定) の CIF 由来モデル値 — **x₀ 校正の根拠にならない**
        (校正提案は x_refined のときのみ出る)。x_XRD が算出不能なフレームでは x キー自体が
        欠落する。None = 未実施 (機能無効/多相/echem 範囲外/B の fix 計画が組めない)。
        ΔRwp 大 = 不可逆容量の疑い (提案≠適用)。
    """

    frame_index: int
    axis_value: float | None
    phase_specs: tuple[PhaseSpec, ...]
    refined_cells: Mapping[str, Cell]
    rwp: float
    gof: float
    phase_fractions: Mapping[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    validity_passed: bool = True
    n_obs: int = 0
    fallback: bool = False
    phase_weight_fractions: Mapping[str, float] = field(default_factory=dict)
    phase_weight_fraction_esd: Mapping[str, float | None] = field(default_factory=dict)
    cell_esd: Mapping[str, CellEsd] = field(default_factory=dict)
    alkali: Mapping[str, object] = field(default_factory=dict)
    ab_check: Mapping[str, float] | None = None

    @property
    def phase_names(self) -> tuple[str, ...]:
        return tuple(p.phase_name for p in self.phase_specs)


@dataclass(frozen=True)
class Segment:
    """隣接アンカー対で挟まれた区間 (内側フレームを双方向解析する)。

    :param left: 左アンカー (先頭端点区間では None)
    :param right: 右アンカー (末尾端点区間では None)
    :param frame_indices: 内側フレーム番号 (アンカーフレームを除く, 昇順)
    :param one_sided: 片側のみ (端点区間) か。True なら bracket があるアンカー側のみで解析
    """

    left: Anchor | None
    right: Anchor | None
    frame_indices: tuple[int, ...]
    one_sided: bool = False


@dataclass(frozen=True)
class SegmentPass:
    """区間の 1 方向 (前方 or 後方) パスの結果。

    :param direction: "forward" (L→R) または "backward" (R→L)
    :param results: 内側フレーム番号→精密化結果 (この方向で解いたもの)
    """

    direction: str
    results: Mapping[int, FrameRietveldResult] = field(default_factory=dict)


@dataclass(frozen=True)
class CrossoverChoice:
    """区間の経路選定結果 (前方/後方のどこで切り替えるか)。

    :param crossover_frame: L..k を前方採用・k+1..R を後方採用の k (相集合同一の毎フレーム選定は None)
    :param total_bic: 採用経路の区間総 bic (相集合同一区間は Rwp 和を格納)
    :param onset_frame: 相集合変化を伴う場合の新相 onset フレーム (無ければ None)
    :param monotonic: 採用経路の新相分率が単調か
    :param reason: 選定方式 ("bic_crossover" / "rwp_per_frame" / "single_direction")
    :param bond_gate: FR-335 結合距離/配位数ゲートの適用結果。``""`` = 未適用
        (`require_bond_validity=False` / 異相集合 crossover 以外) / ``"kept"`` = bic 最良が
        既に結合妥当 / ``"moved"`` = 僅差帯で結合妥当な候補へ crossover を移した /
        ``"no_valid_candidate"`` = 僅差帯の全候補が結合不当だったため bic 最良を保持
        (**黙って不当経路を採らず ③ に疑う手掛かりを残す**)。
    """

    crossover_frame: int | None
    total_bic: float
    onset_frame: int | None = None
    monotonic: bool = True
    reason: str = ""
    bond_gate: str = ""
