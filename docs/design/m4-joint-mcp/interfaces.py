"""m4-joint-mcp 型定義 (設計文書)

作成日: 2026-07-04 / 関連設計: architecture.md
言語: Python 3.12 (frozen dataclass + Protocol — CLAUDE.md 規約)
信頼性レベル: 🔵 要件・仕様・M0〜M3 実装に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測
このファイルは設計時の契約書。実装は src/tsumugin/ 配下。想像でなく既存シグネチャに整合させる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

# M0〜M3 実装済み型 (再利用・拡張の宿主) 🔵
from tsumugin.backends.base import RefinementBackend, RefinementResult
from tsumugin.errors import TsumuginError
from tsumugin.evidence.base import EvidenceBackend
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.model import Hypothesis, PhaseInstance
from tsumugin.model.project import Probe, Project
from tsumugin.search.tree import SearchResult
from tsumugin.selection.engine import FinalSelectionEngine
from tsumugin.sequential.trajectory import Trajectory
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

# ========================================
# errors.py 拡張 (非破壊・末尾追加) — REQ-102/101
# ========================================
# TsumuginError を基底に WebUIUnavailableError と対称の 2 例外を errors.py 末尾へ追加する。


class MCPUnavailableError(TsumuginError):
    """optional extra ``mcp`` (mcp SDK) 未導入環境で MCP サーバ起動 API を要求したとき。🔵 REQ-102

    ``WebUIUnavailableError`` と対称。``import tsumugin.mcp.server`` 自体は成功し、
    ``create_mcp_server`` / ``serve_stdio`` 呼び出し時にのみ本例外を送出して extra 導入を案内する。
    ツール実処理関数 (``mcp.tools``) は SDK 非依存で本例外に依存せず動作する。
    """


class MEMUnavailableError(TsumuginError):
    """MEM バックエンド (M5 / FR-601〜606) 未実装のまま ``run_mem`` を要求したとき。🔵 REQ-101

    破壊的操作を伴わず「M5 で提供予定」を明示する。既定は本例外送出だが、呼び出し側スキーマ互換の
    プレースホルダ dict 応答へ切替可能 (D9)。
    """


# ========================================
# model/project.py 拡張 — REQ-001/002/003
# ========================================


@dataclass(frozen=True)
class TofBankParams:
    """TOF マルチバンクの DIFC/DIFA/ZERO 較正パラメータ (バンク単位)。🔵 REQ-002/FR-241

    【非破壊】: ``HistogramRef`` に ``bank_params: TofBankParams | None = None`` を末尾追加する器。
    既存の ``probe``/``data_ref``/``instprm_ref``/``bank_id`` は不変 (後方互換・TC-401-02)。
    """

    difc: float  # 【DIFC】: d 間隔→TOF 変換係数 🔵
    difa: float = 0.0  # 【DIFA】: 二次項 (既定 0) 🔵
    zero: float = 0.0  # 【ZERO】: TOF ゼロ点 (既定 0) 🔵


# HistogramRef 拡張 (project.py・末尾・既定 None で非破壊追加 🔵 REQ-002/404):
#   bank_params: TofBankParams | None = None
# Frame.histograms: tuple[HistogramRef, ...] は既存の器を利用 (X線+中性子+複数バンク混在, REQ-003)


# ========================================
# model/phase.py 拡張 — REQ-020
# ========================================


@dataclass(frozen=True)
class PhaseRef:
    """相 ID + 組成/元素系ヒント。ChemPlausibility.score の第 1 引数。🟡 REQ-020

    【橋渡し】: 既存 ``PhaseInstance.phase_ref: str`` は不変とし、本型は疎結合の別値オブジェクト。
    PhaseInstance へのフィールド追加は行わない (D6)。
    """

    id: str  # 【相 ID】: PhaseInstance.phase_ref と一致させる 🔵
    formula: str | None = None  # 【組成式】: 例 "LiFePO4"。不明は None 🟡
    element_system: tuple[str, ...] = ()  # 【元素系ヒント】: 例 ("Li","Fe","P","O") 🟡

    @staticmethod
    def from_phase_ref(
        phase_ref: str, *, formula: str | None = None, element_system: tuple[str, ...] = ()
    ) -> "PhaseRef":
        """既存 str ``phase_ref`` から PhaseRef を生成する橋渡し。🟡 REQ-020"""
        ...


# ========================================
# joint/model.py — REQ-004/006
# ========================================


@dataclass(frozen=True)
class JointHistogram:
    """joint 精密化 1 ヒスト分の入力 (2θ/I/w + probe + ヒスト重み)。🔵 REQ-004/FR-242"""

    two_theta: np.ndarray  # 【観測 2θ 軸】 🔵
    intensity: np.ndarray  # 【観測強度】 🔵
    probe: Probe = "xray"  # 【プローブ種別】: xray/neutron_cw/neutron_tof 🔵 REQ-001
    weights: np.ndarray | None = None  # 【観測重み】: None は統計重み 1/σ² 🔵 REQ-008
    hist_weight: float = 1.0  # 【ヒストグラム重み】: 経験重み上書き用スカラ (既定 統計 1.0) 🔵 REQ-008/301
    bank_id: int | None = None  # 【TOF バンク識別】: マルチバンク時 🟡 REQ-002


@dataclass(frozen=True)
class JointRefinementModel:
    """joint 精密化への入力。構造共有・ヒスト独立を分離保持する。🔵 REQ-004/FR-242

    【共有】: 構造パラメータ (格子/座標/占有率/ADP) は全ヒストで共有する ``phases`` +
      ``shared_free_params`` ("phase{i}.lattice.a" 等)。
    【独立】: scale/背景/プロファイルは ``per_histogram_free_params[k]`` でヒストごとに独立解放する。
    """

    phases: tuple[PhaseInstance, ...]  # 【共有構造相】 🔵
    histograms: tuple[JointHistogram, ...]  # 【ヒスト群・順序が決定論キー】 🔵 REQ-402
    shared_free_params: frozenset[str] = field(default_factory=frozenset)  # 【共有 free】 🔵
    # 【ヒスト独立 free】: index k -> 当該ヒストで解放する free_params (scale/bg/profile) 🔵
    per_histogram_free_params: Mapping[int, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PerHistogramMetrics:
    """joint 結果のヒスト別指標。🔵 REQ-006/009"""

    hist_index: int
    probe: Probe
    rwp: float  # 【ヒスト別 Rwp】 🔵
    chi2: float  # 【ヒスト別 χ² (失敗ヒストは inf)】 🔵 EDGE-001
    scale: float  # 【ヒスト独立 scale】 🔵
    sigma_source: Literal["covariance", "hist_weight"]  # 【σ 由来明示】 🔵 REQ-009/NFR-107


@dataclass(frozen=True)
class JointRefinementResult:
    """joint 精密化結果の型付き集約 (集約 RefinementResult + ヒスト別)。🔵 REQ-006

    【集約】: ``aggregate`` は共有構造 phases (±σ)・Σχ²・結合 Rwp を単一 RefinementResult に集約し、
      既存 rank/evidence 経路と互換にする (D1)。ヒスト別 Rwp/scale は ``per_histogram`` と
      ``aggregate.globals`` ("hist0.rwp" 等) の双方に持たせる。
    """

    aggregate: RefinementResult  # 【単一集約結果 (rank/evidence へ渡す)】 🔵 REQ-006
    per_histogram: tuple[PerHistogramMetrics, ...]  # 【ヒスト別指標 (順序=入力順)】 🔵 REQ-402
    warnings: tuple[str, ...] = ()  # 【σ 由来 / 失敗ヒスト明示】 🔵 REQ-009/EDGE-001


# ========================================
# joint/weights.py — REQ-008/009/301
# ========================================


@dataclass(frozen=True)
class HistogramWeighting:
    """ヒストグラム重み方式。既定は統計重み、経験重みはオプション。🔵 REQ-008/301"""

    mode: Literal["statistical", "empirical"] = "statistical"  # 🔵 REQ-008
    empirical_weights: Mapping[int, float] = field(default_factory=dict)  # 【index→信頼度】 🔵 REQ-301

    def resolve(self, model: JointRefinementModel) -> tuple[float, ...]:
        """各ヒストの実効重みを決定論順で返す。統計=1.0、経験=empirical_weights 上書き。🔵 REQ-008"""
        ...

    def sigma_source(self, hist_index: int) -> Literal["covariance", "hist_weight"]:
        """当該ヒストの σ 由来を返す (レポート明示用)。🔵 REQ-009/NFR-107"""
        ...


# ========================================
# joint/engine.py — REQ-005/007
# ========================================


def refine_joint(
    backend: RefinementBackend,
    model: JointRefinementModel,
    *,
    weighting: HistogramWeighting = HistogramWeighting(),
    max_cycles: int = 20,
    ledger: Ledger | None = None,
) -> RefinementResult:
    """joint 精密化を実行し集約 RefinementResult を返す。🔵 REQ-005/006/FR-242

    【GSASIIBackend】: GSAS-II ネイティブのマルチヒストグラム機能へ配線 (v1 は接続点, @gsas smoke)。
    【SimulatedBackend】: 各ヒストを ``backend.refine`` (ヒスト独立 free) → χ² 合算、共有構造は
      χ² 和で更新 (簡易ブロック座標降下, D2)。
    【失敗の非例外化】: 1 ヒスト精密化失敗 (chi2=inf) は例外化せず集約 chi2=inf へ伝播し
      warnings に失敗ヒスト index を明示する (REQ-007/EDGE-001)。集約 chi2=Σχ²、rwp=結合 Rwp。
    """
    ...


def refine_joint_detailed(
    backend: RefinementBackend,
    model: JointRefinementModel,
    *,
    weighting: HistogramWeighting = HistogramWeighting(),
    max_cycles: int = 20,
    ledger: Ledger | None = None,
) -> JointRefinementResult:
    """``refine_joint`` のヒスト別詳細付きラッパ。集約 + PerHistogramMetrics を返す。🔵 REQ-006/009"""
    ...


# ========================================
# joint/contrast.py — REQ-010/011/012/103/104
# ========================================

# 【静的テーブル (軽量同梱・重依存なし)】: 元素記号 → 中性子コヒーレント散乱長 b (fm) 🔵 REQ-010/403
NEUTRON_B_TABLE: Mapping[str, float]
# 【静的テーブル】: 元素記号 → X 線散乱因子近似 (原子番号 Z) 🔵 REQ-010
XRAY_Z_TABLE: Mapping[str, int]


@dataclass(frozen=True)
class OccupancyReleaseRecommendation:
    """コントラスト十分サイトの占有率解放推奨 (提案のみ・自動適用しない)。🔵 REQ-011/012"""

    phase_index: int  # 【相 index】 🔵
    site: str  # 【サイト識別 (占有率キー)】 🔵
    elements: tuple[str, str]  # 【占有元素対 (A,B)・記号昇順】 🔵 REQ-402
    contrast: float  # 【|f_norm − b_norm|】 🔵
    param_name: str  # 【解放候補パラメータ名 "global.occ.{site}" 等】 🟡
    rationale: str  # 【なぜ推奨したか (ledger 記録用)】 🔵 REQ-012


@dataclass(frozen=True)
class ContrastConfig:
    """コントラスト判定設定。🔵 REQ-010"""

    contrast_threshold: float = 0.15  # 【|f_norm − b_norm| 閾値】 🟡 D4


def recommend_occupancy_release(
    phases: tuple[PhaseInstance, ...],
    model: JointRefinementModel,
    *,
    config: ContrastConfig = ContrastConfig(),
    ledger: Ledger | None = None,
) -> tuple[OccupancyReleaseRecommendation, ...]:
    """コントラスト十分サイトの占有率解放を推奨する (自動適用しない)。🔵 REQ-010/011/FR-244

    【joint 条件】: joint データ (ヒスト数 ≥ 2 かつ probe 種別 ≥ 2) がある場合のみ発火。
      単一ヒストでは空を返す (REQ-104/EDGE-004)。
    【判定】: 各サイトの占有元素対 (A,B) で f_norm=f_A/(f_A+f_B)・b_norm=b_A/(|b_A|+|b_B|) を計算し
      |f_norm−b_norm| >= threshold のサイトを検出。全サイト閾値未満なら空・警告なし (REQ-103/EDGE-003)。
    【記録】: 各推奨を ledger.append("contrast_occupancy_recommend", {...}) で理由付き記録 (REQ-012)。
    【決定論】: 元素は記号昇順、サイトは占有率キー昇順で評価する (REQ-402)。
    """
    ...


# ========================================
# joint/verification.py — REQ-013/014/202
# ========================================


@dataclass(frozen=True)
class JointVerificationResult:
    """生存仮説の joint 検証精密化結果。🔵 REQ-014"""

    verified: tuple[Hypothesis, ...]  # 【joint 検証後の仮説 (metrics 更新)】 🔵
    joint_results: Mapping[str, JointRefinementResult]  # 【仮説 ID → joint 詳細】 🔵 REQ-006
    recommendations: Mapping[str, tuple[OccupancyReleaseRecommendation, ...]]  # 【仮説 ID → 提案】 🔵 REQ-011
    warnings: tuple[str, ...] = ()


def verify_survivors(
    backend: RefinementBackend,
    search_result: SearchResult,
    histograms: tuple[JointHistogram, ...],
    *,
    evidence: EvidenceBackend | None = None,
    weighting: HistogramWeighting = HistogramWeighting(),
    contrast: ContrastConfig = ContrastConfig(),
    ledger: Ledger | None = None,
) -> JointVerificationResult:
    """探索の生存仮説のみを joint 検証精密化する。探索段は書き換えない。🔵 REQ-013/014/202

    【FR-245】: プライマリ探索 (SearchResult) は不変。良好解=生存仮説を JointRefinementModel へ組み、
      refine_joint_detailed で検証精密化し、コントラスト推奨も付す。探索を joint 化しない (REQ-202)。
    """
    ...


# ========================================
# chem/base.py — REQ-015/016
# ========================================


@dataclass(frozen=True)
class SynthesisContext:
    """合成文脈: 元素系/前駆体/雰囲気/温度履歴/電気化学窓。🔵 REQ-016/FR-412"""

    element_system: tuple[str, ...] = ()  # 【元素系】 🔵
    precursors: tuple[str, ...] = ()  # 【前駆体】 🔵
    atmosphere: str | None = None  # 【雰囲気】: 例 "air"/"Ar"/"N2" 🔵
    temperature_history_c: tuple[float, ...] = ()  # 【温度履歴 (℃)】 🔵
    electrochemical_window_v: tuple[float, float] | None = None  # 【電気化学窓 (V)】 🔵


@dataclass(frozen=True)
class PlausibilityResult:
    """化学的妥当性の評価結果。🔵 REQ-015/FR-412"""

    score: float  # 【妥当性スコア [0,1]・小さいほど非妥当】 🔵 REQ-015
    rationale: str  # 【判断根拠】 🔵
    source: str  # 【評価モジュール識別 (module id)】 🔵 REQ-015/402


@runtime_checkable
class ChemPlausibility(Protocol):
    """化学的妥当性評価の Protocol 境界。🔵 REQ-015/FR-412

    外部モジュール (reaction network / 熱力学 / LLM 判断) は本 IF に準拠して将来接続する。
    """

    name: str  # 【module id (合成順の決定論キー)】 🔵 REQ-402

    def score(self, phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult:
        ...


# ========================================
# chem/rules.py — REQ-017 (v1 最小ルール)
# ========================================


class AlkaliMetalInAirRule:
    """v1 最小ルール: 大気下での単体アルカリ金属を降格する。🔵 REQ-017/FR-412

    context.atmosphere が酸化性 (air/O2) かつ phase が単体アルカリ金属 (Li/Na/K/Rb/Cs) のとき
    低スコアを返す。非該当は score=1.0 (降格なし)。name="alkali_metal_in_air"。
    """

    name: str

    def score(self, phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult:
        ...


# ========================================
# chem/compose.py — REQ-018/EDGE-007
# ========================================


def combine_plausibility(
    results: Sequence[PlausibilityResult], *, weights: Mapping[str, float] | None = None
) -> PlausibilityResult:
    """複数モジュールのスコアを重み付き幾何平均で合成する。🔵 REQ-018/EDGE-007

    【合成】: s = Π s_i^(w_i / Σw) (既定は等重み)。score=0 のモジュールがあれば合成 0 へ伝播し
      降格が伝播する (除外はしない, EDGE-007)。source は寄与 module id を昇順連結 (REQ-402)。
    【空入力】: results 空なら score=1.0 (降格なし) を返す (REQ-105 の素通し前提)。
    """
    ...


# ========================================
# chem/ranking.py — REQ-019/105 (降格のみ・除外しない)
# ========================================


def rank_with_plausibility(
    hypotheses: Sequence[Hypothesis],
    backend: EvidenceBackend,
    *,
    modules: Sequence[ChemPlausibility] = (),
    context: SynthesisContext = SynthesisContext(),
    phase_refs: Mapping[str, PhaseRef] | None = None,
    weights: Mapping[str, float] | None = None,
    temperature: float = 1.0,
    close_threshold: float = 10.0,
    ledger: Ledger | None = None,
) -> tuple[RankedHypothesis, ...]:
    """素の evidence rank に ChemPlausibility 降格を配線する (候補除外しない)。🔵 REQ-019/105/FR-412

    【最重要不変条件】: スコアは降格のみに使い、候補の除外・rejected 化は行わない。低スコア相も
      rank から消えない (REQ-019/EDGE-005)。
    【配線 (D5)】: まず evidence.ranking.rank で素の順位・確率 p を得る。modules 非空なら各仮説の
      各相を score → combine_plausibility で相スコア s∈[0,1] を合成し、p' = p·s で確率補正して
      再正規化・並べ替える。modules 空なら素の rank をそのまま返す (REQ-105/EDGE-006)。
    【決定論】: module id 昇順・相順は入力順 (REQ-402)。降格スコアと理由は ledger 記録。
    """
    ...


# ========================================
# mcp/tools.py — REQ-021/022/023/024/025 (SDK 非依存の実処理層)
# ========================================


@dataclass(frozen=True)
class AnalysisSession:
    """8 ツールが委譲先へアクセスするための facade (SDK 非依存)。🔵 REQ-022

    【束ね】: project/backend/evidence/ledger/snapshots/selection と最新 SearchResult・Trajectory を
      保持する不変 facade。MCP プロトコルを一切知らない (2 層分離の実処理側, D7)。
    """

    project: Project
    backend: RefinementBackend
    selection: FinalSelectionEngine  # 【final_selection_mode 適用の単一経路】 🔵 REQ-023
    ledger: Ledger
    snapshots: SnapshotStore
    evidence: EvidenceBackend | None = None
    search_result: SearchResult | None = None  # 【直近の探索/検証結果】 🔵
    trajectory: Trajectory | None = None  # 【get_trajectory 委譲用】 🔵


def submit_analysis(
    session: AnalysisSession,
    two_theta: np.ndarray,
    intensity: np.ndarray,
    candidate_phase_sets: Sequence[Sequence[PhaseInstance]],
    *,
    histograms: tuple[JointHistogram, ...] = (),
    reason: str = "",
) -> dict:
    """解析を投入する。pipeline / joint オーケストレーションへ委譲。🔵 REQ-021/022/025

    【委譲】: 単一パターンは analyze_single_pattern、joint 指定 (histograms 非空) は探索→verify_survivors。
    【記録】: ledger.append("mcp_submit", {..., "reason": reason}) (REQ-025)。応答は素の型 dict。
    """
    ...


def list_hypotheses(session: AnalysisSession) -> dict:
    """仮説一覧を返す。SearchResult.to_summary / rank へ委譲。🔵 REQ-021/022"""
    ...


def compare_hypotheses(session: AnalysisSession, hypothesis_ids: Sequence[str]) -> dict:
    """指定仮説を evidence/確率で比較する。rank へ委譲。🔵 REQ-021/022"""
    ...


def accept_hypothesis(
    session: AnalysisSession, hypothesis_id: str, *, by: Literal["agent", "human"], reason: str = ""
) -> dict:
    """仮説を accept する。FinalSelectionEngine.accept へ委譲し mode を同一適用。🔵 REQ-023/106/201

    【human モード拒否】: session.selection.mode == "human" かつ by == "agent" のとき accepted 化を
      拒否し {"status": "recommend_only", "recommended_id": ...} を返す (REQ-106/EDGE-010)。
    【記録】: accept 成立時のみ mcp_accept を ledger 記録 (accept 自体が selection 経由で記録)。
    """
    ...


def revert(session: AnalysisSession, hypothesis_id: str, *, note: str = "") -> dict:
    """accept を superseded 化する (追記型・破壊的削除でない)。🔵 REQ-024/TC-407-04

    【委譲】: FinalSelectionEngine.revert (superseded 化) のみ。破壊的操作は新設しない (REQ-024/NFR-101)。
    【記録】: mcp_revert を ledger 記録 (件数は減らない, TC-407-09)。
    """
    ...


def get_trajectory(session: AnalysisSession, *, path: str | None = None) -> dict:
    """時系列トラジェクトリを返す/CSV 書き出す。Trajectory へ委譲。🔵 REQ-021/022"""
    ...


def export_gpx(
    session: AnalysisSession, path: str, hypothesis_id: str, *, wavelength: float | None = None
) -> dict:
    """指定仮説の相を .gpx へ書き出す。export.gpx.export_gpx へ委譲。🔵 REQ-021/022/EDGE-011

    【GSAS 未導入】: GSASUnavailableError を捕捉し {"status": "error", "error": "gsas_unavailable"}
      へ変換する (クラッシュしない, TC-407-10)。
    """
    ...


def run_mem(session: AnalysisSession, **params) -> dict:
    """MEM 実行の M5 委譲境界。破壊的操作なし。🔵 REQ-101/EDGE-008

    【境界】: mcp.mem.run_mem へ委譲。既定は MEMUnavailableError 送出、または
      {"status": "not_implemented", "milestone": "M5"} プレースホルダ (呼び出し側スキーマ将来互換, D9)。
    """
    ...


# 【ツールレジストリ】: 8 ツール名 → 実処理関数。アダプタ層が配線に使う (SDK 非依存の単一情報源) 🔵 REQ-021
MCP_TOOLS: Mapping[str, object]


# ========================================
# mcp/mem.py — REQ-101 (run_mem 委譲境界)
# ========================================


def run_mem_boundary(session: AnalysisSession, *, placeholder: bool = False, **params) -> dict:
    """MEM バックエンド (M5) 未実装の委譲境界。🔵 REQ-101/EDGE-008

    placeholder=False (既定) は MEMUnavailableError を送出、True はプレースホルダ dict を返す。
    いずれも状態変更・破壊的 ledger 追記を伴わない。
    """
    ...


# ========================================
# mcp/server.py — REQ-021/102/303/405 (SDK 依存の薄いアダプタ層)
# ========================================
# import tsumugin.mcp.server 自体は mcp SDK 未導入でも成功する (遅延 import 契約, WebUIUnavailableError 対称)。


def create_mcp_server(session: AnalysisSession) -> object:
    """MCP Server を構築し 8 ツールを実処理関数へ配線する。🔵 REQ-021/102

    【SDK 遅延 import】: 本関数呼び出し時に mcp SDK を import。未導入なら MCPUnavailableError を送出
      (実処理関数 tools.py は SDK 非依存で動作, REQ-102/EDGE-009)。
    """
    ...


def serve_stdio(session: AnalysisSession) -> None:
    """stdio トランスポートでサーバを起動する (既定・ローカル)。🔵 REQ-405"""
    ...


def serve_local(session: AnalysisSession, *, host: str = "127.0.0.1", port: int = 0) -> None:
    """ローカルバインド (127.0.0.1) で起動する任意トランスポート。無認証ネットワーク公開しない。🟡 REQ-303/405"""
    ...


# ========================================
# store/serialization.py 拡張 — REQ-404/TC-401-04 (往復対称)
# ========================================


def bank_params_to_dict(params: TofBankParams) -> dict:
    """TofBankParams を JSON ネイティブ dict へ (phase_to_dict と同様の純化)。🟡 TC-401-04"""
    ...


def bank_params_from_dict(data: Mapping[str, object]) -> TofBankParams:
    """dict から TofBankParams を復元 (往復対称・欠損は既定値補完)。🟡 TC-401-04"""
    ...


# ========================================
# 公開 API (__init__.py) への追記 — REQ-404/TC-408-05
# ========================================
# __all__ へ末尾追加 + 昇順維持 (test_m4_symbols_sorted で固定):
#   AlkaliMetalInAirRule, AnalysisSession, ChemPlausibility, ContrastConfig, HistogramWeighting,
#   JointHistogram, JointRefinementModel, JointRefinementResult, JointVerificationResult,
#   MCPUnavailableError, MEMUnavailableError, NEUTRON_B_TABLE, OccupancyReleaseRecommendation,
#   PerHistogramMetrics, PhaseRef, PlausibilityResult, SynthesisContext, TofBankParams,
#   XRAY_Z_TABLE, combine_plausibility, create_mcp_server, rank_with_plausibility,
#   recommend_occupancy_release, refine_joint, refine_joint_detailed, verify_survivors
#   (+ mcp.tools の 8 ツールは mcp サブパッケージ側で公開。コア __all__ には SDK 非依存分のみ)


# ========================================
# 信頼性レベルサマリー
# ========================================
# 🔵: 48 / 🟡: 14 / 🔴: 0 — 品質評価: 高品質
# (🟡 は PhaseRef 橋渡し・コントラスト閾値/命名・b テーブル値・serialization 拡張に集中。要件へ遡及可能)
