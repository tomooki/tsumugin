"""m5-nested-mem-oed 型定義 (設計文書)

作成日: 2026-07-04 / 関連設計: architecture.md / dataflow.md / design-interview.md
言語: Python 3.12 (frozen dataclass + Protocol — CLAUDE.md 規約)
信頼性レベル: 🔵 要件・仕様・M0〜M4 実装に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測
このファイルは設計時の契約書。実装は src/tsumugin/ 配下。想像でなく既存シグネチャに整合させる。
実装本体は ``...`` スタブ。型注釈・Protocol・dataclass は python として構文が通ること。

M5 は 3 系統の新レイヤを非破壊で載せる:
  (A) nested/laplace evidence + 階層的裁定 + 確率較正 → ``tsumugin/nested/``
  (B) MEMBackend + Dysnomia 連携 → ``tsumugin/mem/``
  (C) OED / 測定フィードバック提案 → ``tsumugin/oed/``
既存 ``EvidenceBackend`` Protocol (score(metrics) の狭いシグネチャ) は不変に保ち、nested/laplace が
必要とする追加入力 (尤度評価関数・パラメータ空間・restraint) は **補助 dataclass ``EvidenceProblem``
+ 別メソッド ``score_problem`` を持つ拡張 Protocol ``ProblemAwareEvidenceBackend``** で受け渡す (D1)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

# M0〜M4 実装済み型 (再利用・拡張の宿主) 🔵
from tsumugin.backends.base import RefinementBackend, RefinementResult
from tsumugin.errors import TsumuginError
from tsumugin.evidence.base import EvidenceBackend, EvidenceResult
from tsumugin.evidence.ranking import RankedHypothesis, rank
from tsumugin.joint.model import JointRefinementResult
from tsumugin.joint.verification import JointVerificationResult
from tsumugin.model import Hypothesis, PhaseInstance, RefinementMetrics
from tsumugin.model.project import Probe
from tsumugin.sequential.series import FrameSeries
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

# 型エイリアス — 実装では該当モジュールに定義
LogLikelihood = Callable[[np.ndarray], float]  # θ ベクトル → 対数尤度 (nested/laplace が評価)


# ========================================================================
# errors.py 拡張 (非破壊・末尾追加) — REQ-005/036/EDGE-001/011
# ========================================================================
# TsumuginError を基底に MEMUnavailableError (M4 定義済) と対称の 2 例外を errors.py 末尾へ追加。
# 「available + 専用例外」パターン (GSASUnavailableError/WebUIUnavailableError/MCPUnavailableError と対称)。


class NestedUnavailableError(TsumuginError):
    """optional extra ``nested`` (dynesty / ultranest) 未導入で nested 実行 API を要求したとき。🔵 REQ-005/EDGE-001

    ``MCPUnavailableError`` 系と対称。``import tsumugin.nested`` / ``import tsumugin.nested.sampler`` 自体は
    成功し、``NestedBackend.score_problem`` (実サンプラを起動する経路) 呼び出し時にのみ本例外を送出して
    extra 導入を案内する。laplace evidence・階層的裁定・較正はコア (numpy) のみで動作する。
    """


class OEDUnavailableError(TsumuginError):
    """optional extra ``oed`` (pyboed) 未導入で獲得関数接続 API を要求したとき。🔵 REQ-036/EDGE-011

    v1 の提案生成 (``propose_measurements``) は外部依存なしで動作する。PyBOED 獲得関数を用いた高度な
    情報利得評価 (``acquire`` 接続境界) の呼び出し時にのみ本例外を送出する。
    """


# ========================================================================
# nested/laplace.py — REQ-001/002/003/EDGE-005
# ========================================================================


@dataclass(frozen=True)
class LaplaceBackend:
    """Hessian 由来の Laplace 近似 evidence バックエンド。🔵 REQ-001/002/003/FR-121

    【EvidenceBackend 準拠】: ``name`` + ``score(metrics)`` を持ち、既存 rank/evidence 経路に混在可能
      (符号規約: value 小さいほど良い, REQ-003)。metrics のみで呼ばれた場合は BIC 近似へフォールバックする。
    【Laplace 近似】: EvidenceProblem (尤度関数 + MAP 点 + Hessian) が渡せる場合は
      value = -log Z_laplace ≈ -( logL_map + (k/2)ln(2π) - (1/2)ln|H| ) を返す (符号統一で -logZ)。
    【縮退フォールバック (EDGE-005)】: Hessian が特異/取得不能なら BIC 近似 (chi2 + k ln n) へ縮退し
      ``EvidenceResult`` に警告を残す (例外化しない, REQ-002)。nested 打ち切り時の代替先でもある (REQ-101)。
    """

    name: str = "laplace"

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        """metrics のみの狭い経路。Hessian が無いため BIC 近似で縮退する。🔵 REQ-002/003"""
        ...

    def score_problem(self, problem: "EvidenceProblem") -> EvidenceResult:
        """尤度 + Hessian を用いた Laplace evidence。特異時は score(metrics) へフォールバック。🔵 REQ-002/EDGE-005"""
        ...


# ========================================================================
# nested/base.py 相当 (拡張 Protocol + 補助 dataclass) — REQ-008/D1
# ========================================================================
# EvidenceBackend Protocol は不変。nested/laplace が必要とする追加入力を EvidenceProblem に束ね、
# 別メソッド score_problem を持つ ProblemAwareEvidenceBackend で受け渡す (既存 score(metrics) を壊さない)。


@dataclass(frozen=True)
class PriorSpec:
    """1 パラメータの事前分布 (単位超立方体 → 物理量の逆 CDF 変換で表現)。🔵 REQ-008/FR-125

    nested サンプラは単位超立方体上の点を各次元の ``transform`` で物理量へ写す。restraint 由来の
    区間 (格子シフト上限・占有率 [0,1] 拘束等) から自動構成し、手動上書きも受理する (REQ-301)。
    """

    param_name: str  # 【パラメータ名】: "phase0.lattice.a" / "global.occ.site" 等 🔵
    kind: Literal["uniform", "normal", "truncated_normal"] = "uniform"  # 🔵
    low: float = 0.0  # 【下限 (uniform / truncated)】 🔵
    high: float = 1.0  # 【上限 (uniform / truncated)】 🔵
    loc: float = 0.0  # 【中心 (normal 系)】 🔵
    scale: float = 1.0  # 【幅 (normal 系)】 🔵

    def transform(self, u: float) -> float:
        """単位区間 [0,1] の u を物理量へ写す逆 CDF 変換 (prior transform)。🔵 REQ-008"""
        ...


@dataclass(frozen=True)
class EvidenceProblem:
    """nested/laplace が evidence を評価するのに必要な追加入力の束。🔵 REQ-008/D1

    【D1 の核】: EvidenceBackend.score(metrics) の狭いシグネチャでは尤度関数/事前分布/サンプルを渡せない。
      これらを本 dataclass に束ね ``score_problem(problem)`` で受け渡す。metrics も同梱し、縮退時に
      BIC/Laplace フォールバックへ渡せるようにする。
    【決定論】: priors はパラメータ名昇順で保持し nested の次元順を固定する (NFR-102)。
    """

    metrics: RefinementMetrics  # 【フォールバック用 metrics (chi2/n_params/n_obs)】 🔵 REQ-002/101
    log_likelihood: LogLikelihood  # 【θ ベクトル → 対数尤度】 🔵 REQ-006
    priors: tuple[PriorSpec, ...]  # 【事前分布 (param_name 昇順)】 🔵 REQ-008/402
    map_point: np.ndarray | None = None  # 【MAP 推定点 (Laplace の展開中心)】 🔵 REQ-002
    hessian: np.ndarray | None = None  # 【負対数尤度の Hessian (Laplace)】 🔵 REQ-002/EDGE-005
    label: str = ""  # 【問題識別 (ledger 記録用)】 🟡


@runtime_checkable
class ProblemAwareEvidenceBackend(Protocol):
    """尤度関数を要する evidence バックエンドの拡張境界。🔵 REQ-004/D1

    既存 ``EvidenceBackend`` (score(metrics)) を **構造的に包含** し、追加で ``score_problem`` を要求する。
    bic/aic は本 Protocol を実装しない (既存のまま)。laplace/nested のみ実装し、階層的裁定はこの型で受ける。
    """

    name: str

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        ...

    def score_problem(self, problem: EvidenceProblem) -> EvidenceResult:
        ...


# ========================================================================
# nested/prior.py — REQ-008/301/FR-125
# ========================================================================


@dataclass(frozen=True)
class RestraintSpec:
    """精密化 restraint (格子シフト上限・占有率拘束等) の宣言。🔵 REQ-008/FR-125

    nested の事前分布自動構成 (``build_prior_from_restraints``) の入力。既存 free_params 命名
    ("phase{i}.{key}" / "global.{key}") と整合させる。
    """

    param_name: str  # 【対象パラメータ名】 🔵
    lower: float | None = None  # 【下限 (None は既定推定)】 🔵
    upper: float | None = None  # 【上限 (None は既定推定)】 🔵
    center: float | None = None  # 【中心値 (normal restraint 用)】 🔵
    sigma: float | None = None  # 【拘束幅 (normal restraint 用)】 🔵


def build_prior_from_restraints(
    free_params: frozenset[str],
    restraints: Sequence[RestraintSpec] = (),
    *,
    overrides: Mapping[str, PriorSpec] | None = None,
) -> tuple[PriorSpec, ...]:
    """精密化 restraint から nested 事前分布を自動構成する (手動上書き可)。🔵 REQ-008/301/FR-125

    【自動構成】: 各 free_param に対し restraints から区間/中心を引き uniform/truncated_normal を構成。
      restraint 未指定のパラメータは種別ごとの既定区間 (格子=±数%, 占有率=[0,1] 等) を割り当てる。
    【手動上書き (REQ-301)】: overrides に param_name→PriorSpec があれば自動構成を置換する。
    【決定論】: 返す tuple は param_name 昇順で固定し nested の次元順を決定論化する (NFR-102/REQ-402)。
    """
    ...


# ========================================================================
# nested/sampler.py — REQ-004〜009/101/301/EDGE-001/002/004/014
# ========================================================================


@dataclass(frozen=True)
class NestedConfig:
    """nested sampling 実行設定。🔵 REQ-009/012/101/303

    【再現性】: ``seed`` 固定でサンプラ種を固定し、logZ を誤差併記で再現可能にする (NFR-102 の nested 例外)。
    【時間上限】: ``time_limit_sec`` 超過で打ち切り + Laplace 代替 (REQ-101/NFR-103, 既定 30 分)。
    【実装選択】: ``sampler`` で dynesty / ultranest を選択 (REQ-303, いずれも optional extra ``nested``)。
    """

    sampler: Literal["dynesty", "ultranest"] = "dynesty"  # 🔵 REQ-303
    seed: int = 0  # 【サンプラ乱数種 (固定・再現性)】 🔵 REQ-009/NFR-102
    n_live: int = 400  # 【live point 数】 🟡
    time_limit_sec: float = 1800.0  # 【時間上限 (既定 30 分)】 🔵 REQ-101/NFR-103
    max_calls: int | None = None  # 【尤度評価回数上限 (任意の追加安全弁)】 🟡


@dataclass(frozen=True)
class NestedOutcome:
    """nested 実行の詳細 (evidence + 打ち切り/フォールバック情報)。🔵 REQ-006/007/101

    ``EvidenceResult`` (value=-logZ, logz_err) に加え、打ち切り・Laplace 代替の有無を型付き保持する。
    ``truncated=True`` のとき ``result`` は Laplace 代替の値 (符号統一), ``logz`` は None。
    """

    result: EvidenceResult  # 【evidence (value=-logZ 相当, logz_err 併記)】 🔵 REQ-006/007
    logz: float | None  # 【logZ 生値 (付随情報・打ち切り時 None)】 🔵 REQ-007
    truncated: bool = False  # 【時間上限打ち切り (Laplace 代替へ縮退)】 🔵 REQ-101/EDGE-002
    warnings: tuple[str, ...] = ()  # 【打ち切り/フォールバック警告】 🔵 REQ-101


@dataclass(frozen=True)
class NestedBackend:
    """nested sampling evidence バックエンド (dynesty / ultranest 遅延 import)。🔵 REQ-004〜009/101

    【ProblemAwareEvidenceBackend 準拠】: ``name`` + ``score(metrics)`` + ``score_problem(problem)``。
      ``score(metrics)`` は尤度関数を持たないため NestedUnavailableError ではなく **設計上呼べない経路**
      (nested は EvidenceProblem 必須) — metrics のみの場合は Laplace 代替へ委譲する (縮退)。
    【遅延 import (REQ-004/403)】: dynesty/ultranest は score_problem 実行時にのみ import。未導入なら
      ``NestedUnavailableError`` を送出し「extra 導入手順」を案内する。``import tsumugin.nested`` はコア
      (numpy) のみで成功する (TC-502-02)。
    【logZ±誤差 (REQ-006/009/EDGE-014)】: EvidenceResult.value=-logZ, logz_err に誤差を格納。seed 固定で
      2 回実行し logZ が logz_err の範囲内で一致する (ビット同一でなく誤差範囲一致, NFR-102 の nested 例外)。
    【時間上限 (REQ-101/EDGE-002)】: run_with_fallback が time_limit 超過を検知したら打ち切り、
      ``laplace`` を代替に用いた NestedOutcome (truncated=True, 警告付き) を返す (例外化しない)。
    """

    config: NestedConfig = field(default_factory=NestedConfig)
    laplace: LaplaceBackend = field(default_factory=LaplaceBackend)  # 【打ち切り代替先】 🔵 REQ-101
    name: str = "nested"

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        """metrics のみの縮退経路。尤度関数を欠くため Laplace 代替へ委譲する。🔵 REQ-007/101"""
        ...

    def score_problem(self, problem: EvidenceProblem) -> EvidenceResult:
        """nested を起動し value=-logZ + logz_err を返す。未導入は NestedUnavailableError。🔵 REQ-004〜009

        【打ち切り】: 時間上限は run_with_fallback 経由で扱う。本メソッドは実サンプラの評価窓 (@nested)。
        """
        ...

    def run_with_fallback(
        self, problem: EvidenceProblem, *, ledger: Ledger | None = None
    ) -> NestedOutcome:
        """nested 実行を時間上限付きで回し、超過なら Laplace 代替へ縮退した NestedOutcome を返す。🔵 REQ-101/EDGE-002

        【縮退】: time_limit_sec 超過や NestedUnavailableError は例外を上げず truncated=True + Laplace value
          + 警告として返す (解析全体を止めない, REQ-101/405)。ledger 非 None のとき打ち切りを記録する (REQ-013)。
        """
        ...


# ========================================================================
# nested/arbitration.py — REQ-010〜013/102/201/EDGE-003
# ========================================================================


@dataclass(frozen=True)
class ArbitrationConfig:
    """階層的裁定の設定 (2 段構え / フル nested)。🔵 REQ-011/012

    既定は 2 段構え (bic 一次 + close_competitor 群のみ nested 再裁定)。full_nested=True で全生存仮説を
    nested 裁定する (REQ-012/EDGE-004)。close_threshold は既存 rank と同一既定 (ΔBIC < 10)。
    """

    full_nested: bool = False  # 【全生存仮説を nested 裁定 (既定は 2 段構え)】 🔵 REQ-012
    close_threshold: float = 10.0  # 【僅差競合閾値 ΔBIC (rank と共有)】 🔵 REQ-011
    temperature: float = 1.0  # 【softmax 温度較正 (rank と共有)】 🔵 REQ-014


@dataclass(frozen=True)
class ArbitratedHypothesis:
    """階層的裁定後の 1 仮説 (裁定に用いた evidence backend を明示)。🔵 REQ-013/015

    ``RankedHypothesis`` を包み、bic 一次確定か nested 再裁定かを ``adjudicated_by`` で示す (レポート明示)。
    """

    ranked: RankedHypothesis  # 【裁定後の順位・確率・evidence】 🔵
    adjudicated_by: Literal["bic", "nested", "laplace"]  # 【裁定に用いた backend (REQ-015)】 🔵
    logz_err: float | None = None  # 【nested の logZ 誤差 (bic 一次は None)】 🔵 REQ-006


@dataclass(frozen=True)
class ArbitrationResult:
    """階層的裁定の統合結果。🔵 REQ-010〜013

    bic 一次で確定した仮説と nested 再裁定した競合群を統合した最終ランキング。どの仮説をどの backend で
    裁定したかを型付きで保持し、確率較正・レポート・OED 発動へ渡す。
    """

    arbitrated: tuple[ArbitratedHypothesis, ...]  # 【統合ランキング (evidence 昇順)】 🔵
    nested_ids: tuple[str, ...]  # 【nested 再裁定した仮説 ID (決定論・昇順)】 🔵 REQ-013/402
    primary_backend: str = "bic"  # 【一次探索/裁定の backend 名 (REQ-015)】 🔵
    warnings: tuple[str, ...] = ()  # 【打ち切り等の警告伝播】 🔵 REQ-101


def arbitrate(
    hypotheses: Sequence[Hypothesis],
    *,
    problems: Mapping[str, EvidenceProblem] | None = None,
    nested: NestedBackend | None = None,
    config: ArbitrationConfig = ArbitrationConfig(),
    ledger: Ledger | None = None,
) -> ArbitrationResult:
    """木探索を bic のまま維持し、僅差競合のみ nested で再裁定する 2 段構え裁定。🔵 REQ-010〜013/102/201

    【一次 (REQ-010/201)】: まず ``evidence.ranking.rank`` (BICBackend) で順位・確率・close_competitor を得る。
      木探索/枝刈りは bic のまま・nested で書き換えない (探索段は不変, REQ-010/201)。
    【再裁定対象抽出 (REQ-011)】: close_competitor=True (ΔBIC<10) の群のみを nested 再裁定対象とする。
      full_nested=True なら全生存仮説を対象にする (REQ-012/EDGE-004)。
    【nested 再裁定】: 対象仮説 ID の EvidenceProblem を problems から引き、nested.run_with_fallback で
      value=-logZ を得て evidence を差し替え、統合ランキングを再構成 (確率再計算) する。
    【僅差なし (REQ-102/EDGE-003)】: close_competitor が無い/problems・nested 未供給なら nested を発動せず
      bic 一次を最終結果とする (2 段構えの下段スキップ)。
    【記録 (REQ-013)】: どの仮説を bic 一次で確定し、どの競合を nested で再裁定したかを理由付きで
      ledger.append("arbitration", {...}) に記録する (NFR-105)。決定論: 仮説 ID 昇順で処理 (REQ-402)。
    """
    ...


# ========================================================================
# nested/calibration.py — REQ-014〜017/106/EDGE-012
# ========================================================================


@dataclass(frozen=True)
class CalibrationSample:
    """較正ベンチの 1 サンプル (予測確率 + 真偽ラベル + 由来 backend)。🔵 REQ-017/106

    backend フィールドで bic / nested の系列分離を行う (REQ-016/106/EDGE-012)。
    """

    predicted_probability: float  # 【予測確率 p∈[0,1]】 🔵 REQ-017
    correct: bool  # 【真偽 (正解ラベル)】 🔵 REQ-017
    backend: str = "bic"  # 【確率を出した evidence backend (系列分離キー)】 🔵 REQ-016/106


@dataclass(frozen=True)
class ReliabilityBin:
    """reliability diagram の 1 ビン。🔵 REQ-016/017"""

    lower: float  # 【ビン下端 (確率)】 🔵
    upper: float  # 【ビン上端 (確率)】 🔵
    mean_predicted: float  # 【ビン内平均予測確率】 🔵
    observed_frequency: float  # 【ビン内観測正解率】 🔵
    count: int  # 【ビン内サンプル数】 🔵


@dataclass(frozen=True)
class CalibrationReport:
    """1 backend 系列の較正評価 (reliability 曲線 + ECE)。🔵 REQ-016/017/NFR-004

    backend 名と確率の意味 (BIC 近似 vs logZ) をレポートに明記する (REQ-015/NFR-004)。
    """

    backend: str  # 【評価対象 backend (bic / nested)】 🔵 REQ-015/106
    bins: tuple[ReliabilityBin, ...]  # 【ビン分割済み reliability 曲線 (下端昇順)】 🔵 REQ-017/402
    ece: float  # 【Expected Calibration Error スカラ】 🔵 REQ-016
    n_samples: int  # 【評価サンプル数】 🔵
    probability_semantics: str = ""  # 【確率の意味の説明文 (BIC 近似 / logZ)】 🔵 REQ-015/NFR-004


def reliability_diagram(
    samples: Sequence[CalibrationSample], *, n_bins: int = 10
) -> tuple[ReliabilityBin, ...]:
    """予測確率を等幅ビンに分割し reliability 曲線を決定論的に構成する。🔵 REQ-016/017/EDGE-012

    【決定論】: ビンは [0,1] を n_bins 等分し下端昇順で返す。空ビンは count=0 で保持 (ビン順固定, REQ-402)。
    """
    ...


def expected_calibration_error(
    samples: Sequence[CalibrationSample], *, n_bins: int = 10
) -> float:
    """ECE = Σ (count_b / N) · |acc_b − conf_b| を決定論的に計算する。🔵 REQ-016/017"""
    ...


def calibrate_by_backend(
    samples: Sequence[CalibrationSample], *, n_bins: int = 10
) -> tuple[CalibrationReport, ...]:
    """samples を backend 別に分離し bic / nested を別系列で較正評価する。🔵 REQ-016/106/EDGE-012

    【系列分離】: samples を backend でグルーピングし各系列に CalibrationReport を生成する。返す tuple は
      backend 名昇順で決定論化する (REQ-402)。nested 系列があれば別 report として分離出力する (EDGE-012)。
    """
    ...


# ========================================================================
# mem/base.py — REQ-018 (MEMBackend Protocol + MEMResult)
# ========================================================================


@dataclass(frozen=True)
class MEMDensityMap:
    """MEM 密度マップ (VESTA 互換 .grd 等) への参照 + メタ。🔵 REQ-027

    実密度グリッドはファイル (path) に保持し、メモリには要約統計のみ持つ (重データを引き回さない)。
    """

    path: str  # 【密度マップファイルパス (.grd 等)】 🔵 REQ-027
    density_kind: Literal["electron", "nuclear"]  # 【電子密度 / 核密度】 🔵 REQ-022
    grid_shape: tuple[int, int, int]  # 【グリッド次元 (nx, ny, nz)】 🔵
    min_density: float  # 【最小密度値】 🔵
    max_density: float  # 【最大密度値】 🔵


@dataclass(frozen=True)
class DensityCrossSection:
    """指定サイト/結合経路に沿った 1D/2D 断面。🔵 REQ-028"""

    label: str  # 【断面識別 (サイト対 / 経路名)】 🔵
    dimension: Literal[1, 2]  # 【1D / 2D】 🔵
    coordinates: np.ndarray  # 【断面座標 (経路長 or 面グリッド)】 🔵
    values: np.ndarray  # 【断面上の密度値】 🔵


@dataclass(frozen=True)
class BondPathDensity:
    """ボンド経路の最小密度 (伝導パス評価)。🔵 REQ-029

    Na/K 伝導パス可視化を想定し、経路上の最小密度を伝導ボトルネックとして抽出する。
    """

    start_site: str  # 【始点サイト】 🔵
    end_site: str  # 【終点サイト】 🔵
    min_density: float  # 【経路上の最小密度 (ボトルネック)】 🔵 REQ-029
    path_length: float  # 【経路長】 🔵


@dataclass(frozen=True)
class MEMResult:
    """MEM 実行結果 (密度マップ・断面・ボンド経路最小密度・警告)。🔵 REQ-018/027〜031

    【非破壊】: 密度は path で参照し親仮説/joint 結果を書き換えない。適用ガード警告は ``warnings`` に
      積むが仮説除外はしない (Dara 教訓, REQ-031)。
    """

    density_map: MEMDensityMap  # 【密度マップ (.grd 参照 + 統計)】 🔵 REQ-027
    cross_sections: tuple[DensityCrossSection, ...] = ()  # 【1D/2D 断面】 🔵 REQ-028
    bond_paths: tuple[BondPathDensity, ...] = ()  # 【ボンド経路最小密度】 🔵 REQ-029
    r_factor: float | None = None  # 【MEM フィット R (収束判定用)】 🔵 REQ-026
    converged: bool = True  # 【MEM ソルバ収束】 🔵
    warnings: tuple[str, ...] = ()  # 【適用ガード等の信頼性警告 (除外はしない)】 🔵 REQ-030/031


@runtime_checkable
class MEMBackend(Protocol):
    """MEM ソルバの交換可能境界。🔵 REQ-018/FR-602

    ``RefinementBackend`` / ``EvidenceBackend`` / ``ChemPlausibility`` と同型の Protocol。v1 実装は
    ``DysnomiaBackend`` (外部バイナリラッパ)。将来の内製/他ソルバも本 IF で交換可能。
    """

    name: str

    def run(self, mem_input: "MEMInput") -> MEMResult:
        """MEM 入力から密度マップ等を計算する。未導入バックエンドは MEMUnavailableError を送出。🔵 REQ-018/020"""
        ...


# ========================================================================
# mem/inputgen.py — REQ-021/022/023 (F_obs 抽出 + MEM 入力生成)
# ========================================================================


@dataclass(frozen=True)
class StructureFactor:
    """1 反射の観測構造因子 (位相はモデル由来)。🔵 REQ-021

    決定論のため反射は (h,k,l) 昇順で保持する (REQ-023/NFR-102)。
    """

    hkl: tuple[int, int, int]  # 【ミラー指数】 🔵
    f_obs: float  # 【観測構造因子の大きさ |F_obs|】 🔵 REQ-021
    phase: float  # 【位相 (モデル由来, ラジアン)】 🔵 REQ-021
    d_spacing: float  # 【面間隔 d】 🔵


@dataclass(frozen=True)
class MEMInput:
    """MEM ソルバへの入力 (F_obs + セル + 密度種別 + グリッド設定)。🔵 REQ-021/022/023

    【密度種別 (REQ-022)】: probe に応じ X線→電子密度 / 中性子→核密度を選択する。
    【決定論 (REQ-023)】: structure_factors は (h,k,l) 昇順で固定し、同一仮説からビット同一の入力を生成する。
    """

    structure_factors: tuple[StructureFactor, ...]  # 【F_obs 群 ((h,k,l) 昇順)】 🔵 REQ-021/023
    density_kind: Literal["electron", "nuclear"]  # 【probe 由来の密度種別】 🔵 REQ-022
    lattice: tuple[float, float, float, float, float, float]  # 【格子 a,b,c,α,β,γ】 🔵
    space_group: str  # 【空間群記号】 🔵
    grid_shape: tuple[int, int, int]  # 【MEM グリッド次元】 🔵
    lambda_start: float = 1.0  # 【MEM の Lagrange 乗数初期値】 🟡


def extract_structure_factors(
    joint_result: JointRefinementResult, *, hist_index: int = 0
) -> tuple[StructureFactor, ...]:
    """精密化済み joint 結果から観測構造因子 F_obs (位相=モデル由来) を抽出する。🔵 REQ-021/023

    【抽出】: joint 集約 (RefinementResult) の精密化済み構造から F_calc の位相を借り、観測強度由来の
      |F_obs| と組んで StructureFactor を構成する (位相はモデル由来, REQ-021)。
    【決定論 (REQ-023)】: 反射は (h,k,l) 昇順で返す。同一仮説から 2 回抽出でビット同一 (NFR-102/REQ-402)。
    """
    ...


def build_mem_input(
    joint_result: JointRefinementResult,
    probe: Probe,
    *,
    hist_index: int = 0,
    grid_shape: tuple[int, int, int] = (64, 64, 64),
) -> MEMInput:
    """精密化済み仮説 (joint 結果) から MEM 入力ファイル内容を自動生成する。🔵 REQ-021/022/023

    【密度種別 (REQ-022)】: probe が xray なら電子密度、neutron_cw/neutron_tof なら核密度を選ぶ。
    【決定論 (REQ-023)】: extract_structure_factors の (h,k,l) 昇順を継ぎ、同一入力でビット同一 MEMInput。
    """
    ...


# ========================================================================
# mem/dysnomia.py — REQ-019/020/406 (外部バイナリラッパ・遅延 import)
# ========================================================================


@dataclass(frozen=True)
class DysnomiaBackend:
    """Dysnomia 外部バイナリの MEMBackend ラッパ (遅延起動)。🔵 REQ-019/020/406/FR-602

    【入出力ファイル契約固定 (REQ-406/NFR-106)】: 一時領域に MEM 入力ファイルを決定論的に生成し、
      Dysnomia バイナリを実行し、密度マップ (.grd) 等を回収する。生データ改変はしない (P2)。
    【未導入 (REQ-020/EDGE-006)】: バイナリ未検出時は run() が ``MEMUnavailableError`` へ縮退する
      (M4 で errors.py 定義済)。``import tsumugin.mem.dysnomia`` はコア (numpy) のみで成功する。
    """

    binary_path: str | None = None  # 【Dysnomia 実行ファイルパス (None は PATH 探索)】 🔵
    work_dir: str | None = None  # 【入出力一時領域 (None は tempdir)】 🔵
    name: str = "dysnomia"

    def run(self, mem_input: MEMInput) -> MEMResult:
        """入力ファイル生成→バイナリ実行→密度回収。未導入は MEMUnavailableError。🔵 REQ-019/020/EDGE-006"""
        ...


# ========================================================================
# mem/guard.py — REQ-030/031/103/EDGE-007 (適用ガード・警告のみ)
# ========================================================================


@dataclass(frozen=True)
class MEMApplicabilityReport:
    """MEM 適用推奨条件の判定結果 (警告のみ・除外しない)。🔵 REQ-030/031

    【最重要不変条件 (REQ-031/Dara 教訓)】: recommended=False でも MEM 実行を止めず、警告を返すのみ。
      仮説の除外・rejected 化は一切行わない。
    """

    recommended: bool  # 【推奨条件 (joint 済み単相/主相支配) を満たすか】 🔵 REQ-030
    is_single_phase: bool  # 【単相か】 🔵
    is_dominant_phase: bool  # 【主相支配的か】 🔵
    warnings: tuple[str, ...] = ()  # 【多相/低統計の信頼性警告 (除外はしない)】 🔵 REQ-031/103


def check_mem_applicability(
    verification: JointVerificationResult, hypothesis_id: str
) -> MEMApplicabilityReport:
    """MEM 適用の推奨条件を判定し、非充足でも警告のみ返す (除外しない)。🔵 REQ-030/031/103/EDGE-007

    【判定 (REQ-030)】: joint 検証済みかつ単相 or 主相支配的なら recommended=True。
    【警告のみ (REQ-031/103/EDGE-007)】: 多相/低統計は warnings に信頼性警告を積むが recommended=False を
      返すのみで MEM 実行を中止しない (Dara 教訓)。仮説除外もしない。
    """
    ...


# ========================================================================
# mem/iterate.py — REQ-024/025/026/107/202/EDGE-008/009 (MEM-Rietveld 反復)
# ========================================================================


@dataclass(frozen=True)
class MEMRietveldConfig:
    """MEM-Rietveld (MPF) 反復設定。既定オフ。🔵 REQ-024/302

    【既定オフ (REQ-024)】: ``enabled=False`` が既定。明示有効化なしでは反復しない。
    【停止 (REQ-026)】: max_iter または密度/R 変化 < tol で停止する。
    """

    enabled: bool = False  # 【MEM-Rietveld 反復の有効化 (既定オフ)】 🔵 REQ-024
    max_iter: int = 5  # 【最大反復数】 🔵 REQ-026
    r_tol: float = 1e-3  # 【R 値変化の収束閾値】 🔵 REQ-026
    density_tol: float = 1e-3  # 【密度変化の収束閾値】 🔵 REQ-026


@dataclass(frozen=True)
class MEMRietveldCycle:
    """MEM-Rietveld 反復 1 サイクルの記録 (子スナップショット参照付き)。🔵 REQ-025

    各サイクルは SnapshotStore の子スナップショットとして追記され、その ID を保持する (P2)。
    """

    iteration: int  # 【反復番号 (0 始まり)】 🔵
    snapshot_id: str  # 【子スナップショット ID (追記型)】 🔵 REQ-025
    r_factor: float  # 【当該サイクルの R 値】 🔵 REQ-026
    mem_result: MEMResult  # 【当該サイクルの MEM 結果】 🔵


@dataclass(frozen=True)
class MEMRietveldResult:
    """MEM-Rietveld 反復の全体結果 (停止理由 + サイクル列)。🔵 REQ-024/026/107

    【非破壊 (REQ-202/NFR-005)】: 親仮説・joint 結果は不変。各サイクルは子スナップショット追記。
    """

    cycles: tuple[MEMRietveldCycle, ...]  # 【反復サイクル列 (追記順)】 🔵 REQ-025
    stop_reason: Literal["converged", "max_iter", "diverged", "disabled"]  # 🔵 REQ-026/107/EDGE-008/009
    warnings: tuple[str, ...] = ()  # 【発散等の警告】 🔵 REQ-107


def run_mem_rietveld(
    backend: RefinementBackend,
    mem_backend: MEMBackend,
    joint_result: JointRefinementResult,
    parent_phases: tuple[PhaseInstance, ...],
    probe: Probe,
    *,
    config: MEMRietveldConfig = MEMRietveldConfig(),
    snapshots: SnapshotStore,
    ledger: Ledger | None = None,
) -> MEMRietveldResult:
    """MEM-Rietveld (MPF) 反復を回す。既定オフ・各サイクルは子スナップショット追記。🔵 REQ-024/025/026/107/202

    【既定オフ (REQ-024)】: config.enabled=False なら反復せず stop_reason="disabled" を即返す。
    【MPF サイクル】: MEM 密度 → F_calc 更新 → 再精密化 を回す。各サイクルの phases を
      ``snapshots.save(..., label="mem_rietveld_iter{n}")`` で子スナップショットとして **追記** する
      (親不変, REQ-025/202/NFR-005)。削除・上書きはしない (P2)。
    【停止 (REQ-026/EDGE-009)】: 収束 (R/密度変化 < tol) or max_iter 到達で停止し停止理由を ledger 記録。
    【発散 (REQ-107/EDGE-008)】: 密度負値/R 悪化を検知したら当該サイクルを子スナップショットに残しつつ停止し
      stop_reason="diverged"、理由を ledger 記録する (ロールバックは revert 経由・破壊しない)。
    """
    ...


# ========================================================================
# mem/output.py — REQ-027/028/029 (密度マップ・断面・ボンド経路)
# ========================================================================


def write_density_map(mem_result: MEMResult, path: str) -> str:
    """MEM 密度を VESTA 互換 .grd 等へ書き出しパスを返す。🔵 REQ-027"""
    ...


def extract_cross_section(
    density_map: MEMDensityMap,
    *,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    dimension: Literal[1, 2] = 1,
    label: str = "",
) -> DensityCrossSection:
    """指定サイト/経路に沿った 1D/2D 断面を密度マップから抽出する。🔵 REQ-028"""
    ...


def bond_path_min_density(
    density_map: MEMDensityMap,
    *,
    start_site: str,
    end_site: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> BondPathDensity:
    """ボンド経路上の最小密度 (伝導ボトルネック) を抽出する。🔵 REQ-029"""
    ...


# ========================================================================
# mem/spot.py — REQ-032/FR-606 (フレームスポット解析)
# ========================================================================


def run_mem_spot(
    backend: RefinementBackend,
    mem_backend: MEMBackend,
    series: FrameSeries,
    verification: JointVerificationResult,
    hypothesis_id: str,
    frame_index: int,
    probe: Probe,
    *,
    grid_shape: tuple[int, int, int] = (64, 64, 64),
    ledger: Ledger | None = None,
) -> MEMResult:
    """シーケンシャルの指定フレーム (充電端/放電端/転移前後) に MEM をスポット実行する。🔵 REQ-032/FR-606

    【スポット (REQ-032/405)】: frame_index で指定した単一フレームの joint 検証済み仮説に対して MEM を
      実行する。全フレーム自動反復はしない (spot 単位で完結, REQ-405)。
    【適用ガード】: check_mem_applicability の警告を MEMResult.warnings に伝播する (除外しない, REQ-031)。
    """
    ...


# ========================================================================
# mcp/mem.py 実体化 — REQ-033/034/104/EDGE-006/013 (run_mem MEMBackend 委譲)
# ========================================================================
# M4 の run_mem_boundary(session, *, placeholder=False, **params) 契約を維持しつつ、MEMBackend が
# 供給された場合に実処理へ委譲する。placeholder=True の M4 dict スキーマは後方互換維持 (REQ-033)。


def run_mem_boundary(
    session: object,  # 実装では tsumugin.mcp.tools.AnalysisSession (循環回避で TYPE_CHECKING)
    *,
    placeholder: bool = False,
    mem_backend: MEMBackend | None = None,
    hypothesis_id: str | None = None,
    frame_index: int | None = None,
    **params: object,
) -> dict:
    """M4 プレースホルダ境界を MEMBackend 委譲へ実体化する (後方互換維持)。🔵 REQ-033/034/104/EDGE-006/013

    【後方互換 (REQ-033)】: placeholder=True は M4 の
      {"status":"not_implemented","milestone":"M5","tool":"run_mem"} を返す (契約不変)。
    【MEMBackend 委譲 (REQ-034/EDGE-013)】: mem_backend 供給時は build_mem_input→mem_backend.run で
      密度マップパス・断面・最小密度・警告を **素の型 dict** で返す。子スナップショット追記のみで破壊操作なし
      (P2/NFR-101)。非有限値は finite_or_none で純化し json.dumps(allow_nan=False) 安全にする (TC-511-04)。
    【未導入 (REQ-104/EDGE-006)】: MEMUnavailableError を捕捉し {"status":"error","error":"mem_unavailable"}
      へ変換する (クラッシュ・破壊操作なし)。
    """
    ...


# ========================================================================
# oed/proposal.py — REQ-035/037/038/304/EDGE-010 (測定フィードバック提案)
# ========================================================================

MeasurementKind = Literal[
    "high_statistics_remeasure",  # 高統計再測定 🔵
    "additional_temperature_point",  # 追加温度点 🔵
    "neutron_for_joint",  # joint 用中性子測定 🔵
    "composition_analysis",  # 組成分析 🔵
]


@dataclass(frozen=True)
class OEDProposal:
    """僅差競合を判別する 1 測定提案 (情報利得付き)。🔵 REQ-035/304

    【情報利得順 (REQ-035)】: propose_measurements が estimated_information_gain 降順で並べる。
    """

    kind: MeasurementKind  # 【提案測定種別】 🔵 REQ-035
    target_hypothesis_ids: tuple[str, ...]  # 【判別対象の僅差競合仮説群 (昇順)】 🔵 REQ-038/402
    rationale: str  # 【なぜこの測定が判別に効くか (ledger 記録用)】 🔵 REQ-035
    estimated_information_gain: float  # 【推定情報利得スカラ (v1 簡易近似)】 🔵 REQ-304
    parameters: Mapping[str, object] = field(default_factory=dict)  # 【提案パラメータ (温度点 等)】 🟡


def propose_measurements(
    ranked: Sequence[RankedHypothesis],
    *,
    close_threshold: float = 10.0,
    ledger: Ledger | None = None,
) -> tuple[OEDProposal, ...]:
    """僅差競合時の判別測定提案を情報利得順に生成する (非破壊・提案のみ)。🔵 REQ-035/037/038/EDGE-010

    【発動条件 (REQ-038/EDGE-010)】: rank の close_competitor (ΔBIC/ΔlogZ < close_threshold) が存在する
      ときのみ提案する。僅差競合が無ければ空 tuple を返す (状態変更なし, EDGE-010)。
    【提案 (REQ-035)】: 高統計再測定 / 追加温度点 / joint 用中性子測定 / 組成分析を情報利得順で並べる。
    【非破壊 (REQ-037)】: 仮説の accepted/rejected 化・データ改変を一切伴わない。ledger 非 None のとき
      ledger.append("oed_proposal", {...}) で追記記録のみ (P2/NFR-101)。
    【決定論 (REQ-402)】: 対象仮説 ID 昇順・提案は (利得降順, kind 昇順) の安定順で固定する (NFR-102)。
    """
    ...


def proposals_to_json(proposals: Sequence[OEDProposal]) -> list[dict]:
    """OEDProposal 群を JSON ネイティブ list[dict] へ (情報利得順・決定論)。🔵 REQ-035/402

    非有限な情報利得は finite_or_none で純化し json.dumps(allow_nan=False) 安全にする。
    """
    ...


# ========================================================================
# oed/pyboed.py — REQ-036/105/EDGE-011 (PyBOED 獲得関数接続境界)
# ========================================================================


def acquire(
    proposals: Sequence[OEDProposal], *, config: Mapping[str, object] | None = None
) -> tuple[OEDProposal, ...]:
    """PyBOED 獲得関数で提案を再評価する接続境界 (v1 は提案生成のみ)。🔵 REQ-036/105/EDGE-011

    【遅延 import (REQ-036/403)】: pyboed は本関数実行時にのみ import。未導入なら
      ``OEDUnavailableError`` を送出する。propose_measurements (v1 スコープ) は本境界に依存せず動作する
      (提案生成は外部依存なし, REQ-105)。
    """
    ...


# ========================================================================
# 公開 API (__init__.py) への追記 — REQ-404/TC-514-05
# ========================================================================
# __all__ へ末尾追加 + 昇順維持 (test_m5_symbols_sorted で固定):
#   ArbitrationConfig, ArbitrationResult, ArbitratedHypothesis, BondPathDensity, CalibrationReport,
#   CalibrationSample, DensityCrossSection, DysnomiaBackend, EvidenceProblem, LaplaceBackend,
#   MEMApplicabilityReport, MEMBackend, MEMDensityMap, MEMInput, MEMResult, MEMRietveldConfig,
#   MEMRietveldResult, NestedBackend, NestedConfig, NestedOutcome, NestedUnavailableError,
#   OEDProposal, OEDUnavailableError, PriorSpec, ProblemAwareEvidenceBackend, ReliabilityBin,
#   RestraintSpec, StructureFactor, acquire, arbitrate, build_mem_input, build_prior_from_restraints,
#   calibrate_by_backend, check_mem_applicability, expected_calibration_error,
#   extract_structure_factors, propose_measurements, reliability_diagram, run_mem_rietveld,
#   run_mem_spot
#   (NestedUnavailableError / OEDUnavailableError は errors.py。実サンプラ/バイナリ非依存分をコア公開)


# ========================================================================
# 信頼性レベルサマリー
# ========================================================================
# 🔵: 主要シグネチャ・REQ 紐付けは要件/既存実装に依拠 / 🟡: n_live・lambda_start・parameters 等の
#     内部既定値と補助フィールドに集中 (実装時に合成ベンチ/契約 test で凍結) / 🔴: 0
