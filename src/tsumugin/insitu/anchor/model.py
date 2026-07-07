"""M10 アンカー基準双方向 operando 解析のデータモデル (frozen dataclass, numpy-only)。

信頼できるフレーム (アンカー) を起点に両隣アンカーへ双方向で精密化し、区間ごとに IC (bic) で
最良経路を選ぶための不変値オブジェクト群。GSAS-II / pymatgen / MP に非依存の純データ層
(`extract`/`segment`/`select`/`engine` がこれを組み立てる)。

信頼性: 🔵 `docs/design/m10-anchored-operando/architecture.md` §2 / FR-330。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ...autorietveld.model import PhaseSpec
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
    """

    crossover_frame: int | None
    total_bic: float
    onset_frame: int | None = None
    monotonic: bool = True
    reason: str = ""
