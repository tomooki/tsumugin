"""木探索コア (best-first 展開 / 探索モード精密化 / ledger) — FR-110/113/115。

観測パターン ``(two_theta, intensity)`` と候補相集合から、相組合せ仮説の**探索木**を
best-first で構築し、探索モード精密化・BIC 一次評価・ランキングまで行って ``SearchResult``
を返す純粋なオーケストレーション層 (REQ-001)。M0 資産 (``RefinementBackend`` /
``EvidenceBackend`` / ``Ledger`` + ``SnapshotStore``) と Phase 2 部品 (``find_peaks`` /
``match_score`` / ``jaccard_clusters`` / ``dynamic_threshold``) の上に立つ。

データフロー (dataflow.md シーケンス L39-74 / ledger kind の設計名):
    find_peaks → 各候補 match_score (ledger ``match_score``) → jaccard_clusters
    (縮約・alternatives 保持, ledger ``cluster``) → dynamic_threshold 枝刈り
    (ledger ``prune_threshold``) → best-first 木探索 (``backend.refine`` 直呼び →
    BIC 評価, ledger ``node_refine`` / ``branch_prune``) → rank (ledger ``ranking``)。

決定論 (REQ-403 / NFR-102): 乱数不使用。全ソートはキー明示、best-first のキュー処理・
組合せキー (ソート済みインデックスタプル)・仮説 ID 採番 (評価順連番 ``hyp-XXXX``) を
入力順非依存の一意規則に固定し、同一入力の 2 回実行でビット同一の結果を返す。

非破壊性 (REQ-402/405 / NFR-101): 探索エンジン・``SearchResult`` は削除・上書き API を
持たない。枝刈り・降格は理由付き ledger 記録のみで表現し、候補は除外しない (Dara 教訓)。

失敗の非例外化 (EDGE-004): 精密化失敗は例外でなく chi2=inf の結果として扱い、当該ノードを
降格して探索を続行する。全ノードに ``RefinementMetrics`` を付与し、全仮説 inf 時の
softmax NaN 縮退を ``_FiniteGuardedEvidence`` でガードする。

探索後処理 (TASK-0007): 探索コアの後段で ``SearchResult`` の後処理フィールドを実体化する。
Jenks 良好解抽出 (``good_cluster_ids``)、良好解上位への ``StagedRefinementEngine`` フル精密化と
再ランク (``final_reports`` / ``ranked``)、最良仮説基準の未マッチ集約・未知相フラグ
(``unmatched``)、縮退警告 (``warnings``, EDGE-003)、``/api/result`` スキーマ準拠の純 dict 化
(``to_summary()``) を単一 ledger 共有・非破壊で行う (REQ-005/104/106 / D3/D6)。
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..backends.base import RefinementBackend, RefinementModel, param_name
from ..evidence.base import EvidenceBackend, EvidenceResult
from ..evidence.ic import BICBackend
from ..evidence.ranking import RankedHypothesis, rank
from ..model import Hypothesis, PhaseInstance, RefinementMetrics
from ..refinement.staged import RefinementReport, StagedRefinementEngine
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from .clustering import PhaseCandidate, jaccard_clusters, jenks_breaks
from .matcher import MatchResult, UnmatchedPeakReport, match_score, unmatched_peaks
from .peaks import Peak, find_peaks
from .pruning import dynamic_threshold

# 【定数定義】: 根 (空モデル) の基準 Rwp。SimulatedBackend の _rwp はゼロモデルで 100.0 を
#   返すため、深さ 1 の改善判定 (parent_rwp - child_rwp >= r_improve_pct) の基準とする 🟡 note.md §6
_BASELINE_RWP = 100.0

# 【定数定義】: 探索モード精密化で解放するパラメータ suffix (architecture.md D2 / REQ-003)。
#   全相について scale + 格子 a/b/c のみを解放し occupancy 等は固定する 🔵
_EXPLORE_KEYS = ("scale", "lattice.a", "lattice.b", "lattice.c")

# 【空 unmatched】: unmatched の実体化は TASK-0007 スコープ。それまでの共有プレースホルダを
#   1 箇所に定義する (frozen ゆえ共有安全、search() と _empty_result() の重複構築を排除) 🟡
_EMPTY_UNMATCHED = UnmatchedPeakReport(
    unmatched_observed=(), extra_calculated=(), unknown_phase_flag=False
)

# 【縮退警告 (EDGE-003)】: フラットパターン (観測ピーク 0) で後処理を安全側へ倒した理由文字列。
#   説明対象が無いため未知相フラグは立てず、良好解抽出・フル精密化はスキップする 🟡 EDGE-003
_FLAT_PATTERN_WARNING = (
    "観測ピークが検出されませんでした (フラットパターン)。"
    "良好解抽出・最終フル精密化・未マッチ集約をスキップしました。"
)


@dataclass(frozen=True)
class SearchConfig:
    """木探索設定 (frozen)。既定値は interfaces.py L143-158 の契約に一致させる。🔵/🟡"""

    max_phases: int = 5  # 1 仮説の最大相数 🔵 FR-115/REQ-401
    r_improve_pct: float = 2.0  # Rwp 改善打ち切り閾値 (ポイント) 🔵 FR-115 (絶対点解釈は 🟡)
    match_tol_deg: float = 0.15  # マッチング許容 2θ 🟡
    min_peak_height_frac: float = 0.05  # ピーク高さ閾値 🟡
    prune_min_candidates: int = 4  # 枝刈り最小候補数 🟡
    jaccard_threshold: float = 0.85  # クラスタ類似閾値 🟡
    explore_max_cycles: int = 5  # 探索モード精密化サイクル 🔵 FR-113 (値は 🟡)
    final_full_refine: bool = True  # (TASK-0007 用) 🟡 D3
    max_final_refine: int = 3  # (TASK-0007 用) 🟡
    high_r_threshold: float = 30.0  # (TASK-0007 用, Rwp%) 🟡 REQ-106
    close_threshold: float = 10.0  # ΔBIC 僅差競合 🔵 FR-122


@dataclass(frozen=True)
class SearchResult:
    """木探索の出力 (frozen・非破壊)。🔵 REQ-001/202/402

    TASK-0006 の探索コア (``ranked`` / ``hypotheses`` / ``alternatives`` / ``ledger`` /
    ``snapshots``) に加え、TASK-0007 の後処理フィールド (``good_cluster_ids`` / ``unmatched`` /
    ``final_reports`` / ``warnings`` / ``to_summary()``) を実体化して保持する。
    """

    ranked: tuple[RankedHypothesis, ...]  # refined 仮説を良い順で実体化 🔵 REQ-201
    hypotheses: Mapping[str, Hypothesis]  # 全評価ノード (parent_id で系譜) 🔵 REQ-202
    good_cluster_ids: tuple[str, ...]  # Jenks 低群 (良好解) の仮説 ID 🔵 REQ-104/FR-116
    alternatives: Mapping[int, tuple[int, ...]]  # 代表候補idx -> 代替候補idx 🔵 FR-114
    unmatched: UnmatchedPeakReport  # 最良仮説基準の未マッチ集約 🔵 REQ-005/106
    final_reports: Mapping[str, RefinementReport]  # フル精密化した仮説 ID -> report 🟡 D3
    ledger: Ledger  # 全操作を理由付き記録 🔵 REQ-402
    snapshots: SnapshotStore  # 実体を返す 🔵
    warnings: tuple[str, ...] = ()  # 縮退警告 (EDGE-003 等) 🟡

    def to_summary(self) -> dict:
        """``/api/result`` スキーマ準拠の JSON 化可能な純 dict を返す (D6 / api-endpoints.md)。🟡

        【機能概要】: ``ranked`` / ``unmatched`` / ``good_cluster_ids`` / ``warnings`` を
          Web UI へそのまま配信できる素の型 (str/int/float/bool/None/list/dict) へ写像する。
        【実装方針】: numpy スカラー・dataclass を一切露出させず、``float()`` / ``bool()`` /
          ``list`` で純 Python 型へ明示変換する (``json.dumps`` 成功を保証、TC-N17/TC-E07)。
        【テスト対応】: test_to_summary_matches_api_result_schema_and_is_json_serializable ほか。
        🟡 信頼性レベル: キー集合は api-endpoints.md 🔵 / D6 自体は設計由来 🟡。
        """
        # 【良好解判定集合】: in_good_cluster を O(1) 判定するため ID 集合化する 🔵
        good = set(self.good_cluster_ids)

        # 【ランキング行の純 dict 化】: 各 RankedHypothesis を素の型へ写像する 🔵 §4.4
        ranked_rows: list[dict] = []
        for i, rk in enumerate(self.ranked):
            hyp = rk.hypothesis
            metrics = hyp.metrics
            # 【相詳細】: phase_ref / wt_frac / 格子 a,b,c を素の型で並べる 🔵
            phase_rows = [
                {
                    "phase_ref": p.phase_ref,
                    "wt_frac": (float(p.wt_frac) if p.wt_frac is not None else None),
                    "lattice": {
                        "a": float(p.lattice.a),
                        "b": float(p.lattice.b),
                        "c": float(p.lattice.c),
                    },
                }
                for p in hyp.phases
            ]
            ranked_rows.append(
                {
                    "id": hyp.id,
                    "rank": i + 1,  # 【1 起番】: rank は 1 から連番 🔵
                    "probability": float(rk.probability),
                    "close_competitor": bool(rk.close_competitor),
                    "rwp": _finite_or_none(metrics.rwp) if metrics is not None else None,
                    "gof": _finite_or_none(metrics.gof) if metrics is not None else None,
                    "evidence": {
                        "backend": str(rk.evidence.backend),
                        # 非有限/センチネルは None (JSON に inf は無い。詳細 API と表現を統一)
                        "value": _finite_or_none(rk.evidence.value),
                    },
                    "phases": phase_rows,
                    "parent_id": hyp.parent_id,
                    "in_good_cluster": hyp.id in good,  # 【bool】: 良好解メンバか 🔵
                }
            )

        # 【トップレベル】: /api/result の必須キーを素の型で揃える 🔵 §4.4
        return {
            "ranked": ranked_rows,
            "unknown_phase_flag": bool(self.unmatched.unknown_phase_flag),
            "unmatched_observed": [
                {"position": float(pk.position), "height": float(pk.height)}
                for pk in self.unmatched.unmatched_observed
            ],
            "extra_calculated": [float(v) for v in self.unmatched.extra_calculated],
            "warnings": list(self.warnings),
            "n_hypotheses": len(self.hypotheses),
        }


# 有限 BIC (chi2 + k·ln n、実データでは高々 ~1e6) を確実に上回る大きな有限センチネル。
_EVIDENCE_SENTINEL = 1e18


def _finite_or_none(value: float) -> float | None:
    """JSON 配信用に数値を純化する。非有限 (inf/NaN) とセンチネル以上は None に落とす。

    chi2=inf は仕様上の正常経路 (EDGE-004) だが、JSON には inf が存在しないため配信層では
    None として表現する。``_FiniteGuardedEvidence`` のセンチネル (ランキング内部用) も
    観測者には無意味な値なので同様に None へ写像し、/api/result と /api/hypotheses/{id} の
    evidence 表現を一致させる。

    非有限判定は共有ユーティリティ ``_json.finite_or_none`` へ委譲し (単一情報源化, TASK-0023)、
    探索固有のセンチネル閾値判定 (``>= _EVIDENCE_SENTINEL``) のみ tree 側に残す (D-Q9)。
    """
    # 【委譲】: 非有限 (inf/-inf/NaN) → None の純化は共有関数へ集約する 🔵 TASK-0023
    v = finite_or_none(value)
    # 【センチネル局所判定】: 探索固有のセンチネル以上は観測者に無意味なため None 化する 🔵 D-Q9
    if v is None or v >= _EVIDENCE_SENTINEL:
        return None
    return v


class _FiniteGuardedEvidence:
    """全仮説 evidence が非有限のとき softmax が 0/0 → NaN 縮退するのを防ぐガード付き backend。

    【機能概要】: inner backend に委譲しつつ、非有限 (inf/NaN) の evidence 値のみ大きな有限
      センチネルへ丸める。有限値は不変のため通常ケースの evidence.value は真値のまま保たれ、
      決定論・ビット同一 (TC-001-05) を壊さない。全滅 (全 inf) 時は全値がセンチネルへ揃い
      softmax が均等確率へ縮退して NaN を回避する (TC 全 inf ガード)。
    【実装方針】: これは実処理を行う production ラッパー (テストダブルではない)。inner の
      ``name`` を踏襲するため RankedHypothesis.evidence.backend は "bic" のまま維持される。
    🟡 信頼性レベル: ガード必要性は note.md §6 に依拠 🔵、センチネル方式は実装時確定 🟡。
    """

    # 【センチネル】: モジュール定数を共有 (to_summary の None 写像と同一値であることが要件) 🟡
    _SENTINEL = _EVIDENCE_SENTINEL

    def __init__(self, inner: EvidenceBackend) -> None:
        # 【委譲先保持】: 実 evidence backend を保持し name を踏襲 (backend 名の一貫性) 🔵
        self._inner = inner
        self.name = inner.name

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        # 【委譲 + 有限ガード】: 実値が有限ならそのまま、非有限ならセンチネルへ丸める 🟡
        result = self._inner.score(metrics)
        if math.isfinite(result.value):
            return result
        return EvidenceResult(backend=self.name, value=self._SENTINEL, logz_err=result.logz_err)


class HypothesisTreeSearch:
    """多仮説木探索エンジン。🔵 FR-110

    候補正規化 → find_peaks → match_score → jaccard 縮約 (alternatives 保持) →
    dynamic_threshold 枝刈り → best-first 木探索 (backend.refine 直呼び, scale+lattice,
    max_cycles=explore_max_cycles) → BIC 評価 → rank を決定論的に実行する。
    """

    def __init__(
        self,
        backend: RefinementBackend,
        *,
        evidence: EvidenceBackend | None = None,
        config: SearchConfig = SearchConfig(),
        ledger: Ledger | None = None,
        snapshots: SnapshotStore | None = None,
    ) -> None:
        """探索エンジンを構築する。

        【機能概要】: backend / evidence / config と、任意の ledger・snapshots を束ねる。
        【テスト対応】: test_search_config_defaults (既定 evidence が BIC) 他。
        🔵 信頼性レベル: interfaces.py L179-190 / REQ-004 に直接依拠。

        Args:
            backend: 精密化バックエンド (``refine`` 直呼び、候補ピーク生成に ``simulate`` を利用)。
            evidence: evidence backend。None のとき既定 ``BICBackend`` (name="bic")。🔵 REQ-004
            config: 探索設定 (既定 ``SearchConfig()``)。
            ledger: 追記専用台帳。None のとき search() ごとに内部生成。
            snapshots: スナップショットストア。None のとき ledger 連携で内部生成。
        """
        # 【依存の束ね】: 探索の純関数構成 (REQ-404) を支える不変の依存を保持する 🔵
        self._backend = backend
        # 【既定 evidence】: 未指定なら BIC 一次評価を採用する (REQ-004 / FR-121) 🔵
        self._evidence: EvidenceBackend = evidence if evidence is not None else BICBackend()
        self._config = config
        self._ledger = ledger
        self._snapshots = snapshots

    # ---- 公開 API ------------------------------------------------------

    def search(
        self,
        two_theta: np.ndarray,
        intensity: np.ndarray,
        candidates: Sequence[PhaseCandidate | PhaseInstance],
        *,
        weights: np.ndarray | None = None,
    ) -> SearchResult:
        """観測パターンと候補集合から探索木を構築し ``SearchResult`` を返す。🔵 REQ-001

        【機能概要】: データフロー (モジュール docstring 参照) を決定論的に実行する。全操作を
          単一 ledger に理由付き記録し、非破壊で SearchResult を返す。
        【テスト対応】: tests/test_tree_search.py の 20 ケース (TC-N01〜10/TC-E01〜04/TC-B01〜06)。
        🔵 信頼性レベル: interfaces.py L192-199 / dataflow.md シーケンスに直接依拠。

        Args:
            two_theta: 観測 2θ 軸 (1D numpy)。
            intensity: 観測強度 (1D numpy、``two_theta`` と同長)。
            candidates: ``PhaseCandidate`` または ``PhaseInstance`` の並び。
            weights: 任意の観測重み (キーワード専用)。

        Returns:
            ``SearchResult``。候補ゼロでも例外化せず空値へ縮退して実体を返す (EDGE-001)。
        """
        config = self._config
        # 【単一インスタンス確保】: ledger / snapshots は search() ごとに単一利用・返却する 🔵
        ledger = self._ledger if self._ledger is not None else Ledger()
        snapshots = (
            self._snapshots if self._snapshots is not None else SnapshotStore(ledger=ledger)
        )

        # 【入力正規化 (数値)】: float 配列へ揃え、以降の refine を安定させる 🔵
        two_theta = np.asarray(two_theta, dtype=float)
        intensity = np.asarray(intensity, dtype=float)
        if weights is not None:
            weights = np.asarray(weights, dtype=float)

        # 【候補正規化】: PhaseInstance を PhaseCandidate(delta_u=0.0) へ揃える (M1 は delta_u=0) 🔵
        normalized = [
            c if isinstance(c, PhaseCandidate) else PhaseCandidate(phase=c) for c in candidates
        ]

        # 【候補ゼロの縮退】: 探索空間が空でも例外化せず空 SearchResult を返す (EDGE-001) 🔵
        if not normalized:
            return self._empty_result(ledger, snapshots)

        # 【観測ピーク検出】: 観測パターンから局所極大+高さ閾値でピークを抽出する 🔵 FR-111
        observed = find_peaks(
            two_theta, intensity, min_height_frac=config.min_peak_height_frac
        )

        # 【候補マッチング】: 各候補を simulate → find_peaks でピーク化し match_score を取る 🔵
        candidate_peaks, scores = self._match_candidates(
            normalized, two_theta, observed, ledger
        )

        # 【等構造縮約】: Jaccard クラスタで代表を選び、代替候補は alternatives に非破壊保持 🔵 FR-114
        representatives, alternatives = self._reduce_clusters(normalized, candidate_peaks, scores, ledger)

        # 【動的枝刈り】: 代表のマッチスコアから閾値を求め、閾値未満の候補を非展開にする 🔵 REQ-101
        eligible = self._prune_candidates(representatives, scores, ledger)

        # 【best-first 木探索】: 生存候補で組合せ仮説を評価・展開し全ノードを保持する 🔵 D1
        hypotheses = self._explore(eligible, scores, normalized, two_theta, intensity, weights, ledger)

        # 【ランキング (一次)】: 全 refined ノードを BIC 昇順+softmax でランクする 🔵 REQ-201
        ranked = self._rank(hypotheses, ledger)

        # 【探索後処理 (TASK-0007)】: 良好解抽出 → フル精密化 → 再ランク → 未マッチ集約を
        #   単一メソッドへ委譲し、後処理済みの SearchResult を返す 🔵 REQ-005/104/106
        return self._postprocess(
            ranked=ranked,
            hypotheses=hypotheses,
            alternatives=alternatives,
            observed=observed,
            two_theta=two_theta,
            intensity=intensity,
            weights=weights,
            ledger=ledger,
            snapshots=snapshots,
        )

    # ---- パイプライン各段 (純関数的ヘルパ) --------------------------------

    def _empty_result(self, ledger: Ledger, snapshots: SnapshotStore) -> SearchResult:
        """候補ゼロ時の空 SearchResult を返す (EDGE-001)。ledger/snapshots は実体を保つ。🔵"""
        # 【空縮退】: 全コレクションを空値にし、ledger/snapshots だけ実体を返す (検証可能に) 🔵
        return SearchResult(
            ranked=(),
            hypotheses={},
            good_cluster_ids=(),
            alternatives={},
            unmatched=_EMPTY_UNMATCHED,
            final_reports={},
            ledger=ledger,
            snapshots=snapshots,
            warnings=(),
        )

    def _match_candidates(
        self,
        normalized: list[PhaseCandidate],
        two_theta: np.ndarray,
        observed: Sequence[Peak],
        ledger: Ledger,
    ) -> tuple[list[tuple[Peak, ...]], list[float]]:
        """各候補相の計算ピークを生成し観測との match_score を取る (FR-111)。🔵

        候補ピーク生成方式 (設計未確定点の確定案): 候補 1 相を観測グリッド上で
        ``backend.simulate`` → ``find_peaks(min_height_frac)`` で Peak 化して ``match_score``
        に渡す (RefinementBackend Protocol に simulate は無いが SimulatedBackend/GSASIIBackend
        双方に実装があり、テストのバックエンドも委譲する)。🟡 note.md §注意事項。
        """
        config = self._config
        candidate_peaks: list[tuple[Peak, ...]] = []
        scores: list[float] = []
        for i, cand in enumerate(normalized):
            # 【候補ピーク生成】: 候補 1 相を観測グリッドで simulate してピーク化する 🟡
            calc = self._backend.simulate([cand.phase], two_theta)
            cpeaks = find_peaks(two_theta, calc, min_height_frac=config.min_peak_height_frac)
            candidate_peaks.append(cpeaks)
            # 【マッチング】: 候補ピーク列と観測ピーク列の一致率+被覆率でスコアを求める 🔵
            match = match_score(
                cpeaks, observed, tol_deg=config.match_tol_deg, candidate_index=i
            )
            scores.append(match.score)
            # 【監査記録】: 各候補のスコアを kind="match_score" で追跡可能にする 🔵 TC-008-02
            ledger.append("match_score", {"candidate_index": i, "score": float(match.score)})
        return candidate_peaks, scores

    def _reduce_clusters(
        self,
        normalized: list[PhaseCandidate],
        candidate_peaks: list[tuple[Peak, ...]],
        scores: list[float],
        ledger: Ledger,
    ) -> tuple[list[int], dict[int, tuple[int, ...]]]:
        """Jaccard クラスタで代表を選び代替候補を alternatives に保持する (FR-114)。🔵"""
        config = self._config
        # 【等構造クラスタ】: ピーク位置の Jaccard 類似で候補をクラスタし FoM で代表選出する 🔵
        clusters = jaccard_clusters(
            candidate_peaks,
            scores,
            [cand.delta_u for cand in normalized],  # M1 では delta_u は常に 0.0
            similarity_threshold=config.jaccard_threshold,
        )
        alternatives: dict[int, tuple[int, ...]] = {}
        representatives: list[int] = []
        for cluster in clusters:
            rep = int(cluster.representative)
            members = [int(m) for m in cluster.members]
            representatives.append(rep)
            # 【監査記録】: クラスタ縮約結果を kind="cluster" で記録する 🔵 TC-008-02
            ledger.append("cluster", {"representative": rep, "members": members})
            # 【非破壊保持】: 代表以外の代替候補を削除せず alternatives に保持する 🔵 REQ-103/405
            others = tuple(m for m in members if m != rep)
            if others:
                alternatives[rep] = others
        return representatives, alternatives

    def _prune_candidates(
        self, representatives: list[int], scores: list[float], ledger: Ledger
    ) -> list[int]:
        """動的閾値で代表候補を枝刈りし、生存候補をスコア降順で返す (REQ-101)。🔵"""
        config = self._config
        rep_scores = [scores[r] for r in representatives]
        # 【動的閾値】: スコア分布の変曲点を閾値とする (候補 < min_candidates 等は -inf=全展開) 🔵
        threshold = dynamic_threshold(rep_scores, min_candidates=config.prune_min_candidates)
        # 【境界包含】: 閾値ちょうどは展開側 (>=)、閾値未満のみ枝刈りする 🔵 REQ-101
        eligible = [r for r in representatives if scores[r] >= threshold]
        # 【監査記録】: 閾値と生存候補を kind="prune_threshold" で追跡可能にする 🔵 TC-008-02
        ledger.append(
            "prune_threshold",
            {
                "threshold": float(threshold),
                "n_candidates": len(representatives),
                "eligible": [int(r) for r in eligible],
            },
        )
        # 【非破壊記録】: 閾値未満の候補は削除でなく理由付き branch_prune 記録で表現する 🔵 REQ-405
        for r in representatives:
            if scores[r] < threshold:
                ledger.append(
                    "branch_prune",
                    {
                        "reason": "below_threshold",
                        "candidate": int(r),
                        "score": float(scores[r]),
                        "threshold": float(threshold),
                    },
                )
        # 【決定論順序】: スコア降順・同点は候補 index 昇順で best-first の試行順を固定する 🔵 NFR-102
        eligible.sort(key=lambda r: (-scores[r], r))
        return eligible

    def _explore(
        self,
        eligible: list[int],
        scores: list[float],
        normalized: list[PhaseCandidate],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        weights: np.ndarray | None,
        ledger: Ledger,
    ) -> dict[str, Hypothesis]:
        """best-first で相組合せ仮説の探索木を構築し全評価ノードを返す (D1)。🔵

        ノード = 候補 index の frozenset。根 = 空集合 (基準 Rwp=100.0)。深さ d の仮説に候補を
        1 相追加した子を評価し、Rwp 改善 >= r_improve_pct かつ chi2 有限かつ相数 < max_phases の
        子のみ展開キュー (rwp 最小優先の heap) へ積む。同一組合せはソート済みタプルキーで重複排除。
        """
        config = self._config
        hypotheses: dict[str, Hypothesis] = {}
        combo_to_id: dict[frozenset[int], str] = {}
        # 【best-first キュー】: (rwp, ソート済み index タプル) の heap で最有望ノードから展開する 🔵
        heap: list[tuple[float, tuple[int, ...]]] = []
        counter = 0

        def evaluate(combo: frozenset[int], parent_id: str | None, parent_rwp: float) -> None:
            """組合せを評価して hypotheses/combo_to_id へ登録し、展開可否を判定する。"""
            nonlocal counter
            node_id = f"hyp-{counter:04d}"  # 【ID 採番】: 評価順連番 (入力順非依存) 🔵 M0 規約
            counter += 1
            hyp = self._evaluate_node(
                combo, normalized, two_theta, intensity, weights, parent_id, node_id, ledger
            )
            hypotheses[node_id] = hyp
            combo_to_id[combo] = node_id
            self._consider_expand(combo, hyp, parent_rwp, heap, ledger)

        # 【深さ 1】: 生存候補の単相ノードを評価する (根の基準 Rwp=100.0 で改善判定) 🔵
        for r in eligible:
            evaluate(frozenset({r}), None, _BASELINE_RWP)

        # 【best-first 展開】: heap が空になるまで最有望ノードを 1 相ずつ広げる 🔵 D1
        while heap:
            _, parent_tuple = heapq.heappop(heap)
            parent_combo = frozenset(parent_tuple)
            parent_id = combo_to_id[parent_combo]
            parent_hyp = hypotheses[parent_id]
            # 【上限ガード】: max_phases 到達枝は展開停止する (EDGE-101) 🔵 REQ-401
            if len(parent_combo) >= config.max_phases:
                continue
            for r in eligible:
                if r in parent_combo:
                    continue  # 【重複相回避】: 既に含む候補は追加しない
                child_combo = parent_combo | {r}
                # 【重複排除】: 同一組合せの再評価をソート済みキーで排除する 🔵 D1
                if child_combo in combo_to_id:
                    continue
                # 【生成前打ち切り】: 上限超の仮説は Hypothesis 自体を作らない 🔵 TC-003-02
                if len(child_combo) > config.max_phases:
                    continue
                evaluate(child_combo, parent_id, parent_hyp.metrics.rwp)

        return hypotheses

    def _evaluate_node(
        self,
        combo: frozenset[int],
        normalized: list[PhaseCandidate],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        weights: np.ndarray | None,
        parent_id: str | None,
        node_id: str,
        ledger: Ledger,
    ) -> Hypothesis:
        """1 ノード (相組合せ) を探索モード精密化し refined Hypothesis を返す (D2/REQ-003)。🔵

        ``backend.refine`` を直接呼ぶ (StagedRefinementEngine 不使用)。free_params は全相の
        scale + 格子 a/b/c、max_cycles=explore_max_cycles。精密化失敗 (chi2=inf) も例外化せず
        metrics を付けて降格対象として返す (EDGE-004)。全ノードに BIC を格納する (REQ-004)。
        """
        config = self._config
        # 【相順の固定】: 候補 index 昇順で相を並べ、param_name の相 index を決定論化する 🔵
        indices = sorted(combo)
        phases = tuple(normalized[i].phase for i in indices)
        # 【探索モード free_params】: 全相の scale+格子 a/b/c のみ解放する 🔵 D2/REQ-003
        free = frozenset(
            param_name(pos, key) for pos in range(len(phases)) for key in _EXPLORE_KEYS
        )
        model = RefinementModel(
            phases=phases,
            free_params=free,
            two_theta=two_theta,
            intensity=intensity,
            weights=weights,
        )
        # 【探索モード精密化】: backend.refine を直呼びし max_cycles=explore_max_cycles を伝播 🔵
        result = self._backend.refine(model, max_cycles=config.explore_max_cycles)

        chi2 = float(result.chi2)
        n_obs = int(result.n_obs)
        n_params = int(result.n_params)
        # 【GoF 変換】: gof = sqrt(chi2 / max(n_obs - n_params, 1)) (staged.py _gof と同式) 🔵
        gof = math.sqrt(chi2 / max(n_obs - n_params, 1))
        base_metrics = RefinementMetrics(
            rwp=float(result.rwp),
            gof=gof,
            chi2=chi2,
            n_obs=n_obs,
            n_params=n_params,
            evidence={},
        )
        # 【BIC 一次評価】: 全評価ノードに evidence["bic"] を格納する (rank の前提) 🔵 REQ-004
        ev = self._evidence.score(base_metrics)
        metrics = replace(base_metrics, evidence={ev.backend: ev.value})
        hyp = Hypothesis(
            id=node_id,
            phases=result.phases,
            parent_id=parent_id,
            metrics=metrics,
            status="refined",  # 【状態】: 評価済みノードは refined (REQ-201 ランキング対象) 🔵
        )
        # 【監査記録】: ノード生成/精密化を kind="node_refine" で追跡可能にする 🔵 TC-008-02
        ledger.append(
            "node_refine",
            {
                "id": node_id,
                "parent_id": parent_id,
                "candidates": [int(i) for i in indices],
                "phases": [p.phase_ref for p in phases],
                "rwp": float(result.rwp),
                "chi2": chi2,
                "n_params": n_params,
            },
        )
        return hyp

    def _consider_expand(
        self,
        combo: frozenset[int],
        hyp: Hypothesis,
        parent_rwp: float,
        heap: list[tuple[float, tuple[int, ...]]],
        ledger: Ledger,
    ) -> None:
        """評価済みノードを展開キューへ積むか、理由付き branch_prune で降格する (D1/REQ-102)。🔵"""
        config = self._config
        metrics = hyp.metrics
        assert metrics is not None  # 全ノードに metrics を付与済み
        child_rwp = metrics.rwp
        indices = [int(i) for i in sorted(combo)]

        # 【失敗の降格】: chi2=inf のノードは展開せず降格として記録し探索を続行する 🔵 EDGE-004
        if not math.isfinite(metrics.chi2):
            ledger.append(
                "branch_prune",
                {"reason": "refine_failed", "id": hyp.id, "candidates": indices},
            )
            return

        # 【R 改善打ち切り】: parent_rwp - child_rwp < r_improve_pct の子は展開せず記録する 🔵 REQ-102
        improvement = parent_rwp - child_rwp
        if improvement < config.r_improve_pct:
            ledger.append(
                "branch_prune",
                {
                    "reason": "no_improvement",
                    "id": hyp.id,
                    "candidates": indices,
                    "rwp": float(child_rwp),
                    "parent_rwp": float(parent_rwp),
                    "improvement": float(improvement),
                },
            )
            return

        # 【上限到達】: max_phases に達した枝は自然停止 (これ以上追加しない) 🔵 REQ-401/EDGE-101
        if len(combo) >= config.max_phases:
            return

        # 【展開キュー投入】: 改善した有限ノードを rwp 最小優先で heap へ積む 🔵 D1
        heapq.heappush(heap, (float(child_rwp), tuple(indices)))

    def _rank(
        self, hypotheses: dict[str, Hypothesis], ledger: Ledger
    ) -> tuple[RankedHypothesis, ...]:
        """全 refined ノードを BIC 昇順+softmax でランクし採択を記録する (REQ-201/FR-122)。🔵"""
        config = self._config
        # 【NaN ガード】: 全仮説 inf の softmax 0/0 縮退を防ぐガード付き evidence で評価する 🟡
        guarded = _FiniteGuardedEvidence(self._evidence)
        # 【決定論入力順】: 評価順 (id 昇順) の仮説列を渡し rank の同点タイブレークを固定する 🔵
        ranked = rank(
            list(hypotheses.values()), guarded, close_threshold=config.close_threshold
        )
        # 【監査記録】: ランキング採択を kind="ranking" で記録する 🔵 TC-008-02 (pipeline 踏襲)
        ledger.append(
            "ranking",
            {
                "order": [rk.hypothesis.id for rk in ranked],
                "probabilities": [float(rk.probability) for rk in ranked],
            },
        )
        return ranked

    # ---- TASK-0007 探索後処理ヘルパ --------------------------------------

    def _postprocess(
        self,
        *,
        ranked: tuple[RankedHypothesis, ...],
        hypotheses: dict[str, Hypothesis],
        alternatives: Mapping[int, tuple[int, ...]],
        observed: tuple[Peak, ...],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        weights: np.ndarray | None,
        ledger: Ledger,
        snapshots: SnapshotStore,
    ) -> SearchResult:
        """探索コアの後段で SearchResult の後処理フィールドを実体化する (TASK-0007)。🔵

        【機能概要】: 良好解抽出 (Jenks) → 最終フル精密化 + 再ランク (D3) → 未マッチ集約
          (REQ-005/106) を単一 ledger 共有・非破壊で行い、完成した SearchResult を返す。
        【設計方針】: search() の一次ランキングまで (TASK-0006 コア) と後処理 (TASK-0007) を
          分離し、後処理群を 1 メソッドへ凝集させて search() の流れを二段構成に保つ。フラット/
          通常の両経路を末尾 1 箇所の SearchResult 構築へ集約し、フィールド列の重複を排する。
        【EDGE-003】: 観測ピーク 0 (フラットパターン) は説明対象が無いため良好解抽出・フル精密化・
          未マッチ集約をスキップし、警告のみ積んで空良好解・未知相フラグ False へ倒す 🟡。
        🔵 信頼性レベル: dataflow.md L39-74 / architecture.md D3 / note.md §4.5 に依拠。
        """
        # 【EDGE-003 フラット縮退】: 例外化せず後処理をスキップし警告のみ積む 🟡 EDGE-003
        if not observed:
            ledger.append("warning", {"reason": "flat_pattern_no_observed_peaks"})
            good_cluster_ids: tuple[str, ...] = ()
            final_reports: Mapping[str, RefinementReport] = {}
            unmatched = _EMPTY_UNMATCHED
            warnings: tuple[str, ...] = (_FLAT_PATTERN_WARNING,)
        else:
            # 【良好解抽出 (Jenks)】: 一次 evidence を 2 群化した低群を良好解 ID に確定 🔵 REQ-104
            good_cluster_ids = self._extract_good_cluster(ranked, ledger)
            # 【最終フル精密化 + 再ランク】: 良好解上位に staged 精密化を適用し metrics 更新 🟡 D3
            final_reports, ranked = self._final_refine(
                ranked,
                good_cluster_ids,
                hypotheses,
                two_theta,
                intensity,
                weights,
                ledger,
                snapshots,
            )
            # 【未マッチ集約 + 未知相フラグ】: 最良仮説を基準に未説明観測を集約 🔵 REQ-005/106
            unmatched = self._compute_unmatched(
                ranked, hypotheses, two_theta, observed, ledger
            )
            warnings = ()

        # 【単一構築】: フラット/通常の両経路を 1 箇所の SearchResult 構築へ集約する (DRY) 🔵
        return SearchResult(
            ranked=ranked,
            hypotheses=hypotheses,
            good_cluster_ids=good_cluster_ids,
            alternatives=alternatives,
            unmatched=unmatched,
            final_reports=final_reports,
            ledger=ledger,
            snapshots=snapshots,
            warnings=warnings,
        )

    def _extract_good_cluster(
        self, ranked: tuple[RankedHypothesis, ...], ledger: Ledger
    ) -> tuple[str, ...]:
        """一次 evidence を Jenks 2 群化し低 evidence 群 (良好解) の仮説 ID を返す (REQ-104/FR-116)。🔵

        【機能概要】: ``ranked`` の evidence 値 (低いほど良い) を ``jenks_breaks(n_classes=2)``
          で 2 群に分け、境界以下 (``value <= breaks[0]``) の仮説を良好解とする。
        【実装方針】: 非有限 evidence は ``_rank`` が有限センチネルへ丸め済みのため jenks が安定。
          境界不能 (仮説 1 件 → ``jenks_breaks`` が ``()``) は全 ranked を良好解とみなす
          フォールバック (§3.6)。全同値は境界=同値となり ``<=`` で全件が良好解になる。返す ID は
          決定論のため昇順に整列する。
        【テスト対応】: test_jenks_good_cluster_ids_* / _single_hypothesis_falls_back /
          _all_equal_evidence_makes_every_hypothesis_good。
        🔵 信頼性レベル: acceptance-criteria TC-004-03 / FR-116 / REQ-104 に依拠
          (縮退フォールバックは §3.6 の実装時確定事項 🟡)。
        """
        # 【空縮退】: ランキング空 (候補ゼロ経路) では良好解も空 🔵
        if not ranked:
            return ()
        # 【Jenks 2 群化】: 低群 (良好) と高群 (劣位) の境界値を DP で求める 🔵 REQ-104
        values = [rk.evidence.value for rk in ranked]
        breaks = jenks_breaks(values, n_classes=2)
        if breaks:
            # 【低群抽出】: 境界以下の evidence を持つ仮説を良好解とする (低いほど良い) 🔵
            threshold = breaks[0]
            good = [rk.hypothesis.id for rk in ranked if rk.evidence.value <= threshold]
        else:
            # 【縮退フォールバック】: 仮説 1 件で境界不能 → その 1 件をそのまま良好解にする 🟡 §3.6
            good = [rk.hypothesis.id for rk in ranked]
        # 【決定論整列】: 良好解 ID を昇順に固定する (入力順非依存) 🔵 NFR-102
        good_ids = tuple(sorted(good))
        ledger.append(
            "good_cluster", {"ids": list(good_ids), "n_ranked": len(ranked)}
        )
        return good_ids

    def _final_refine(
        self,
        ranked: tuple[RankedHypothesis, ...],
        good_cluster_ids: tuple[str, ...],
        hypotheses: dict[str, Hypothesis],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        weights: np.ndarray | None,
        ledger: Ledger,
        snapshots: SnapshotStore,
    ) -> tuple[dict[str, RefinementReport], tuple[RankedHypothesis, ...]]:
        """良好解上位 max_final_refine 件に staged フル精密化を適用し metrics 更新・再ランクする (D3)。🟡

        【機能概要】: ``final_full_refine=True`` のとき良好解のうち evidence 昇順上位
          ``max_final_refine`` 件へ ``StagedRefinementEngine.run`` を適用し、BIC を再計算して
          ``hypotheses`` の該当ノードを非破壊で差し替え、``rank`` を再実行する。
        【実装方針】: 探索と同一 ``ledger`` / ``snapshots`` を共有し追記のみで監査一貫性を保つ
          (§3.2)。metrics 反映は ``dataclasses.replace`` による新インスタンス生成で行い元
          ``Hypothesis`` を破壊しない。``final_full_refine=False`` / 良好解空では
          ``({}, 元の ranked)`` を返し metrics 不変。
        【テスト対応】: test_final_full_refine_records_reports_and_updates_metrics /
          _reranking_orders_ranked_ascending_after_full_refine / _disabled_keeps_reports_empty /
          _max_final_refine_clips_to_top_good_cluster / _postprocess_appends_to_single_ledger。
        🟡 信頼性レベル: architecture.md D3 / 要件定義 §3.6 からの妥当な導出。
        """
        config = self._config
        # 【無効化 / 空縮退】: フラグ False または良好解空なら何もせず不変で返す 🟡 §3.6
        if not config.final_full_refine or not good_cluster_ids:
            return {}, ranked

        # 【対象選出】: 良好解のうち evidence 昇順 (= ranked 順) 上位 max_final_refine 件 🟡 D3
        good_set = set(good_cluster_ids)
        targets = [rk.hypothesis.id for rk in ranked if rk.hypothesis.id in good_set]
        targets = targets[: config.max_final_refine]

        # 【共有エンジン】: 探索と同一 ledger/snapshots で staged 精密化を行う (監査一貫性) 🔵 §3.2
        engine = StagedRefinementEngine(self._backend, store=snapshots, ledger=ledger)
        final_reports: dict[str, RefinementReport] = {}
        for hid in targets:
            hyp = hypotheses[hid]
            # 【フル精密化】: 段階的パラメータ解放で最終評価精度を上げる 🟡 D3
            report = engine.run(hyp.phases, two_theta, intensity, weights=weights)
            # 【BIC 再計算】: フル精密化後 metrics から evidence を再評価する 🟡 REQ-004
            ev = self._evidence.score(report.metrics)
            new_metrics = replace(report.metrics, evidence={ev.backend: ev.value})
            # 【非破壊反映】: phases/metrics を差し替えた新 Hypothesis へ置換 (id/parent_id/status 保持) 🔵
            hypotheses[hid] = replace(
                hyp, phases=report.final_phases, metrics=new_metrics
            )
            final_reports[hid] = report
            # 【監査記録】: フル精密化の適用を kind="final_refine" で追跡可能にする 🔵 §3.2
            ledger.append(
                "final_refine",
                {
                    "id": hid,
                    "rwp": float(report.metrics.rwp),
                    "chi2": float(report.metrics.chi2),
                    "escalated": bool(report.escalated),
                },
            )

        # 【再ランク】: 更新後 metrics で BIC 昇順ランキングを確定する 🟡 D3
        ranked = self._rank(hypotheses, ledger)
        return final_reports, ranked

    def _compute_unmatched(
        self,
        ranked: tuple[RankedHypothesis, ...],
        hypotheses: Mapping[str, Hypothesis],
        two_theta: np.ndarray,
        observed: tuple[Peak, ...],
        ledger: Ledger,
    ) -> UnmatchedPeakReport:
        """最良仮説を基準に未マッチ観測ピークを集約し未知相フラグを判定する (REQ-005/106)。🔵

        【機能概要】: 最良仮説 (``ranked[0]``) の各相を ``simulate → find_peaks → match_score``
          で観測と突き合わせ、``unmatched_peaks`` でどの相でも説明できない観測ピークを Peak 実体
          (位置・強度付き) で集約する。未知相フラグは「未マッチ非空」または「全 refined 仮説の
          Rwp > high_r_threshold」で立てる。
        【実装方針】: 探索時の候補マッチ結果を再利用せず最良仮説の相で再計算することで、再ランク後の
          最良解に整合した決定論的な未マッチ集約を得る (§6 選択肢2)。``high_r_flag`` は厳密比較
          (``>``) で境界値を高 R に含めない (§3.6)。
        【テスト対応】: test_complete_explanation_has_no_unmatched_and_flag_false /
          _unknown_phase_reports_unmatched_peaks_with_flag / _all_high_r_forces_unknown_phase_flag /
          _high_r_threshold_uses_strict_greater_comparison。
        🔵 信頼性レベル: acceptance-criteria TC-005-01/02 / TC-E02 / REQ-005/106 に依拠。
        """
        config = self._config
        # 【空縮退】: ランキング空では未マッチ集約対象が無いため空へ倒す 🔵
        if not ranked:
            return _EMPTY_UNMATCHED

        # 【全高 R 判定】: 全 refined 仮説の Rwp が閾値を厳密超過するとき未知相フラグを強制する 🔵 REQ-106
        high_r_flag = all(
            h.metrics is not None and h.metrics.rwp > config.high_r_threshold
            for h in hypotheses.values()
        )

        # 【最良仮説の相ごとマッチ】: 各相を simulate してピーク化し観測と突き合わせる 🔵
        best = ranked[0].hypothesis
        match_results: list[MatchResult] = []
        for i, phase in enumerate(best.phases):
            calc = self._backend.simulate([phase], two_theta)
            cpeaks = find_peaks(
                two_theta, calc, min_height_frac=config.min_peak_height_frac
            )
            match_results.append(
                match_score(
                    cpeaks, observed, tol_deg=config.match_tol_deg, candidate_index=i
                )
            )

        # 【未マッチ集約】: 説明済み観測の補集合を Peak 実体で復元し未知相フラグを立てる 🔵 FR-117
        report = unmatched_peaks(match_results, observed, high_r_flag=high_r_flag)
        # 【監査記録】: 未マッチ集約結果を kind="unmatched" で追跡可能にする 🔵
        ledger.append(
            "unmatched",
            {
                "n_unmatched_observed": len(report.unmatched_observed),
                "n_extra_calculated": len(report.extra_calculated),
                "unknown_phase_flag": bool(report.unknown_phase_flag),
                "high_r_flag": bool(high_r_flag),
            },
        )
        return report
