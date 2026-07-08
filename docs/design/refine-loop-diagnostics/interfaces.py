"""refine-loop-diagnostics 型定義 (設計スケッチ, docs 配下・非 import)。

作成日: 2026-07-09 / 関連設計: architecture.md
信頼性: 🔵 要件/既存実装参照 / 🟡 妥当な推測 / 🔴 未参照推測
実装時は既存モジュールへ統合する (本ファイルはインターフェース合意用)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

# 既存型 (再掲・参照用)
from tsumugin.autorietveld.model import AutoRietveldResult, HistogramSpec, PhaseSpec  # noqa
from tsumugin.refine_loop.action import AnalysisInput, SafeAction  # noqa
from tsumugin.refine_loop.diagnostics import ActionProposal, ResidualFeatures  # noqa


# ============================================================
# REQ-001: AutoRietveldResult 内省フィールド (非破壊・末尾追加・既定空) 🔵
# ============================================================
# model.py の AutoRietveldResult に以下を追加する (frozen, 既定値で後方互換):
#
#   atom_uiso: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
#       # phase_name → atom_label → Uiso。Uiso 発散/負値の検出源 (REQ-105) 🔵
#   atom_occupancy: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
#       # phase_name → atom_label → 占有率。[0,1] 逸脱の検出源 🔵
#   hist_absorption: tuple[float, ...] = ()
#       # per-hist の現吸収値。SetAbsorption 判断源 (REQ-106) 🔵
#   hist_profile: tuple[Mapping[str, float], ...] = ()
#       # per-hist の現プロファイル値 (Zero/alpha/X/Y/U/V/W 等) 🔵
#   peak_width_ratio: tuple[float, ...] = ()
#       # per-hist の obs/calc FWHM 比 (1.0 が理想)。幅ずれ検出 (REQ-103) 🔵
#   asymmetry_metric: tuple[float, ...] = ()
#       # per-hist の残差左右非対称度 (0=対称)。非対称検出 (REQ-101) 🔵
#   intensity_bias_metric: tuple[float, ...] = ()
#       # per-hist の系統 obs>calc 度 (選択配向徴候, REQ-102) 🔵
#   bg_extrema: tuple[int, ...] = ()
#       # per-hist の背景極値数 (過多=overfit, REQ-104) 🔵


# ============================================================
# REQ-002/101〜106: ResidualFeatures 拡張シグナル 🔵
# ============================================================
@dataclass(frozen=True)
class ResidualFeaturesExt:
    """diagnostics.ResidualFeatures に追加するフィールド (既存に統合)。🔵

    既存: hist_id / low_freq_bg_residual / fwhm_ratio / unindexed_peak_frac /
          edge_low_snr / n_background_coeffs
    追加 (すべて既定 0/空 = シグナルなし, EDGE-001 縮退):
    """

    asymmetry_residual: float = 0.0          # 非対称度 (>tol で Zero/非対称候補) REQ-101 🔵
    intensity_bias: float = 0.0              # 系統 obs>calc (>tol で PO 候補) REQ-102 🔵
    bg_extrema_count: int = 0                # 背景極値数 (過多で減項候補) REQ-104 🔵
    diverged_uiso_labels: tuple[str, ...] = ()   # 発散/負 Uiso 原子 → RestrictUiso REQ-105 🔵
    absorption_uncertain: bool = False       # 吸収不確実 → SetAbsorption 三択 REQ-106 🔵
    radiation_is_tof: bool = False           # TOF か (非対称候補 alpha/beta vs SH/L 分岐) 🔵


# ============================================================
# REQ-004: 新 SafeAction (action.py に追加) 🔵
# ============================================================
@dataclass(frozen=True)
class RestrictUiso(SafeAction):
    """Uiso 解放対象を限定する (発散防止)。free_uiso_labels を設定する純変換。🔵

    :param labels: Uiso を解放する原子ラベル (重原子/可動イオン/水など)
    :param phase: 対象相名 (None なら全相)
    """

    labels: tuple[str, ...]
    phase: str | None = None

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        """該当 PhaseSpec.free_uiso_labels を labels に設定した入力を返す。"""
        ...  # dataclasses.replace(phase, free_uiso_labels=self.labels)


@dataclass(frozen=True)
class SetAbsorption(SafeAction):
    """ヒストグラムの吸収を値固定 or 解放する (free/物理/0 の三択トライ)。🔵

    :param hist_id: 対象ヒストグラム索引
    :param value: 設定する吸収初期値 (物理値/0 等)
    :param refine: True なら "absorption" 解放段を extra_stages に追加、False なら固定
    """

    hist_id: int
    value: float = 0.0
    refine: bool = False

    def apply(self, inp: AnalysisInput) -> AnalysisInput:
        """HistogramSpec.absorption=value に設定 (+refine なら absorption 段追加)。"""
        ...  # 範囲外 hist_id は IndexError (TC-004-E01)


# ============================================================
# REQ-002: 残差解析の既定 diagnose (refine_loop/diagnose_residual.py, 新) 🔵
# ============================================================
def diagnose_residual(
    result: AutoRietveldResult,
    inp: AnalysisInput,
) -> Sequence[ResidualFeatures]:
    """残差配列 + 内省フィールドから ResidualFeatures 列を算出する既定 diagnose。🔵

    orchestrator の Diagnose 契約を満たし _default_diagnose を置換。numpy 決定論。
    内省フィールド欠落時は該当シグナルを立てない (EDGE-001 縮退)。残差空/全ノイズは
    シグナルを立てない (EDGE-102 FP 回避)。
    """
    ...


# ============================================================
# REQ-003/101〜106: propose_next_actions 規則追加 (diagnostics.py 拡張) 🔵
# ============================================================
# 既存 propose_next_actions に規則を追加 (候補は別々の提案):
#   - asymmetry_residual>tol → ReleaseParams("zero", {"profile_lorentzian":True}) と
#     ReleaseParams("asym", {"profile_asymmetry":True}) [TOF は {"tof_profile":["alpha","beta-1"]}]
#     を **2 提案** (別々, REQ-101/DD-2) 🔵
#   - intensity_bias>tol → ReleaseParams("po", {"preferred_orientation":4}) (REQ-102) 🔵
#   - fwhm_ratio ずれ → ReleaseParams(profile U,V,W) / (profile_lorentzian X,Y) / (size_strain)
#     を別々 (REQ-103) 🔵
#   - bg_extrema_count 過多 → AdjustBackground(減項) (REQ-104, 増項と両立) 🔵
#   - diverged_uiso_labels → RestrictUiso(重原子/水) (REQ-105) 🔵
#   - absorption_uncertain → SetAbsorption(free)/(物理)/(0) の 3 提案 (REQ-106) 🔵
# 順序: safe 優先→優先度降順→型名昇順 (REQ-402 決定論)。


# ============================================================
# REQ-005/202: モデル比較オーケストレータ (refine_loop/model_compare.py, 新) 🔵
# ============================================================
@dataclass(frozen=True)
class ModelCompareResult:
    """モデル比較の結果 (compare.ModelComparison + ledger)。🔵"""

    comparison: object            # compare.ModelComparison (scores/best/best_is_valid)
    best_phases: tuple[PhaseSpec, ...]   # best 変種の相 (継続精密化用)
    ledger: object | None = None


def run_model_comparison(
    histograms: Sequence[HistogramSpec],
    variants: Sequence[object],   # compare.ModelVariant 列
    *,
    runner: object = None,        # None なら run_auto_rietveld
    ledger: object | None = None,
    **run_kwargs: object,
) -> ModelCompareResult:
    """変種を精密化し compare_models で BIC+妥当性裁定 + ledger 追記する薄い上位。🔵

    単一モデル調律ループ (run_refinement_loop) の外側 (DD-6)。妥当なうち最小 BIC を best、
    妥当皆無なら全体最小へフォールバック (best_is_valid=False, EDGE-101)。ledger verify True。
    """
    ...


# ============================================================
# 信頼性レベルサマリー
# ============================================================
# 🔵 青信号: 全型定義 (要件 + 既存実装 + GAP_ANALYSIS に追跡可能)
# 🟡/🔴: 0
# 品質評価: 高品質
