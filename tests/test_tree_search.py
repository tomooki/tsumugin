"""TASK-0006 木探索コア (best-first 展開 / 探索モード精密化 / ledger) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/search/tree.py`` (**未実装**) の
``SearchConfig`` / ``SearchResult`` (骨格) / ``HypothesisTreeSearch.__init__ / search()``。
tree.py 未作成のため collection 時に import が失敗し、本ファイルの全テストがエラー(=失敗)になる想定。

方針:
- backend は原則 ``SimulatedBackend`` (GSAS-II 非依存)。境界値 (TC-B05) と失敗注入 (TC-E02/E03) は
  Rwp / chi2 を厳密制御するため ``FakeBackend`` (RefinementBackend Protocol 準拠スタブ) を使う。
- 探索モード精密化の呼び出し契約 (TC-N10) は ``RecordingSpyBackend`` で観測する。
- 決定論 (TC-B04) は ``==`` ビット同一、物理量近似は ``pytest.approx`` を使う。
- 観測グリッドは全ピークが収まる ``15–60°`` へ縮めて実行時間を抑える (step 0.02 は clustering 較正上必須)。

書式の範: ``tests/test_pipeline.py`` / ``tests/test_pruning.py`` / ``tests/test_clustering.py``。
テストケース定義 (20 件, TC-N01〜10 / TC-E01〜04 / TC-B01〜06) に 1:1 対応する。
"""

from __future__ import annotations

import dataclasses
import json
import math
import re

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.search.clustering import PhaseCandidate

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定。
from tsumugin.search.tree import HypothesisTreeSearch, SearchConfig, SearchResult

# ---------------------------------------------------------------------------
# 共通テストデータ・前提 (モジュールレベルで一度だけ構築し不変共有する)
# ---------------------------------------------------------------------------

# 【観測グリッド】: 全候補のピークが収まる 15–60° / step 0.02。step 0.02 は等構造縮約 (TC-N06)
#   の bin 一致 (bin_width 0.2 内) を較正済み。範囲を縮めて refine 回数あたりの実行時間を抑える。🔵/🟡
GRID = np.arange(15.0, 60.0, 0.02)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンスを作る (格子定数 a を変えるとピーク位置が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


# 【候補相 (a を変えるとピーク位置が変わる)】: A/B は真の相、C/D は無関係相 (較正済みで score≈0)。
PHASE_A = _phase(5.0, "A")  # 真の相 1 🔵
PHASE_B = _phase(6.0, "B")  # 真の相 2 (2 相合成は A+B を重ねる) 🔵
PHASE_C = _phase(4.5, "C")  # 無関係相 (A/B とピーク位置が合わない) 🔵
PHASE_D = _phase(7.0, "D")  # 無関係相 🔵
PHASE_A_PRIME = _phase(5.001, "Aprime")  # A と同一 bin に落ちる等構造候補 (縮約対象) 🔵
PHASE_G = _phase(6.5, "G")  # 第 3 の真の相 (3 相合成 TC-B01 用) 🟡

_EXPLORE_FREE_1PHASE = {
    "phase0.scale",
    "phase0.lattice.a",
    "phase0.lattice.b",
    "phase0.lattice.c",
}


def _refs(hypothesis) -> set[str]:
    """仮説の相集合 (phase_ref の集合) を返す。"""
    return {p.phase_ref for p in hypothesis.phases}


def _node_with_refs(result: SearchResult, refs: set[str]):
    """指定の相集合を持つ仮説ノードを返す (無ければ None)。"""
    target = frozenset(refs)
    for h in result.hypotheses.values():
        if frozenset(_refs(h)) == target:
            return h
    return None


# ---------------------------------------------------------------------------
# テストダブル (境界値・失敗注入・呼び出し観測)
# ---------------------------------------------------------------------------


class FakeBackend:
    """RefinementBackend Protocol 準拠の決定論スタブ。

    相組合せ (phase_ref の frozenset) をキーに固定の (rwp, chi2) を返し、境界値 (TC-B05) と
    chi2=inf 注入 (TC-E02/E03) を厳密制御する。候補ピーク生成 (simulate → find_peaks) 経路を
    成立させるため ``simulate`` / ``peak_positions`` は内蔵 SimulatedBackend へ委譲する。
    """

    name = "fake"

    def __init__(
        self,
        *,
        rwp_by_refs: dict[frozenset[str], float] | None = None,
        chi2_by_refs: dict[frozenset[str], float] | None = None,
        default_rwp: float = 50.0,
        default_chi2: float = 10.0,
    ) -> None:
        self._sim = SimulatedBackend(peak_fwhm=0.2)
        self._rwp = dict(rwp_by_refs or {})
        self._chi2 = dict(chi2_by_refs or {})
        self._default_rwp = float(default_rwp)
        self._default_chi2 = float(default_chi2)
        self.refine_calls: list[frozenset[str]] = []

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        refs = frozenset(p.phase_ref for p in model.phases)
        self.refine_calls.append(refs)
        rwp = self._rwp.get(refs, self._default_rwp)
        chi2 = self._chi2.get(refs, self._default_chi2)
        n_obs = int(np.asarray(model.intensity).size)
        return RefinementResult(
            phases=model.phases,
            chi2=chi2,
            rwp=rwp,
            n_obs=n_obs,
            n_params=len(model.free_params),
            converged=math.isfinite(chi2),
            n_cycles=1,
            free_params=frozenset(model.free_params),
        )


class RecordingSpyBackend:
    """SimulatedBackend へ委譲しつつ refine の (free_params, max_cycles) を記録するスパイ。"""

    name = "spy"

    def __init__(self) -> None:
        self._sim = SimulatedBackend(peak_fwhm=0.2)
        self.refine_calls: list[tuple[frozenset[str], int]] = []

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        self.refine_calls.append((frozenset(model.free_params), max_cycles))
        return self._sim.refine(model, max_cycles=max_cycles)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース
# ---------------------------------------------------------------------------


def test_two_phase_truth_ranks_ab_first():
    # 【テスト目的】: 2 相合成 (A+B)・4 候補で {A,B} 仮説が最上位ランクになることを確認 (TC-001-01)
    # 【テスト内容】: SimulatedBackend の合成パターンに対する search() のフルパイプライン統合
    # 【期待される動作】: ranked[0] の相集合 == {"A", "B"}
    # 🔵 信頼性レベル: 受け入れ基準 TC-001-01 / REQ-001 に直接依拠

    # 【テストデータ準備】: a=5.0 / 6.0 の 2 立方相を重ねた合成パターン
    # 【初期条件設定】: 候補は真の 2 相 + 無関係 2 相 (a=4.5 / 7.0) — 枝刈りが有効になる候補 4 件
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)

    # 【実際の処理実行】: find_peaks → match → cluster → prune → best-first 展開 → BIC → rank
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    # 【結果検証】: ランキング先頭が真の 2 相構成であること
    assert result.ranked  # 【確認内容】: ランキングが非空 🔵
    assert _refs(result.ranked[0].hypothesis) == {"A", "B"}  # 【確認内容】: {A,B} が 1 位 🔵
    top_id = result.ranked[0].hypothesis.id
    assert top_id in result.hypotheses  # 【確認内容】: 先頭 ID が hypotheses に存在 (ID 整合) 🔵


def test_redundant_phase_addition_pruned_with_ledger_record():
    # 【テスト目的】: 単相 A データで余剰相追加が R 改善 2pt 未満で打ち切られ ledger 記録が残る (TC-001-02)
    # 【テスト内容】: 1 相合成・3 候補 (A,B,C) で {A} が 1 位、余剰相追加が branch_prune される
    # 【期待される動作】: ranked[0] == {A} かつ ledger に "branch_prune" kind が存在
    # 🔵 信頼性レベル: 受け入れ基準 TC-001-02 / TC-003-01 / REQ-102/402 に直接依拠

    # 【テストデータ準備】: 単相 A で完全説明できる合成データ (余剰相追加の Rwp 改善はほぼ 0)
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)

    # 【実際の処理実行】: 3 候補 (min_candidates 未満で枝刈り無効 → 余剰相は改善打ち切りで処理)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C])

    # 【結果検証】: 単相 {A} が最上位、余剰相追加は削除でなく branch_prune 記録で表現される
    assert _refs(result.ranked[0].hypothesis) == {"A"}  # 【確認内容】: 単相 {A} が 1 位 🔵
    kinds = [e.kind for e in result.ledger.entries]
    assert "branch_prune" in kinds  # 【確認内容】: 改善不足の打ち切りが理由付き記録される 🔵
    assert result.ledger.verify()  # 【確認内容】: 監査ログの連鎖健全性 🔵


def test_all_refined_hypotheses_have_bic_evidence():
    # 【テスト目的】: 全 refined 仮説の metrics.evidence に "bic" キーが付与される (TC-001-03)
    # 【テスト内容】: search() 後の全ノードが refined かつ metrics 付き・BIC 値保持
    # 【期待される動作】: 全ノードで metrics is not None かつ "bic" in evidence、gof が変換式に一致
    # 🔵 信頼性レベル: 受け入れ基準 TC-001-03 / REQ-004 / staged.py `_gof` 同式に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    # 【結果検証】: 全評価ノードが BIC 値を保持し metrics 欠落が 1 つも無いこと
    for h in result.hypotheses.values():
        assert h.metrics is not None  # 【確認内容】: metrics 欠落ノードが無い (rank の前提) 🔵
        assert "bic" in h.metrics.evidence  # 【確認内容】: BIC 一次評価が格納される 🔵
        assert h.status == "refined"  # 【確認内容】: 評価済みノードは refined 状態 🔵

    # 【期待値確認】: 代表 1 ノードの gof が sqrt(chi2 / max(n_obs - n_params, 1)) と一致
    m = result.ranked[0].hypothesis.metrics
    expected_gof = math.sqrt(m.chi2 / max(m.n_obs - m.n_params, 1))
    assert m.gof == pytest.approx(expected_gof)  # 【確認内容】: RefinementResult→Metrics 変換式 🔵


def test_child_hypothesis_parent_id_links_lineage():
    # 【テスト目的】: 子仮説の parent_id が親 ID と一致し系譜が解決できる (TC-001-04)
    # 【テスト内容】: 深さ 2 の {A,B} 仮説の parent_id が {A} または {B} の ID を指す
    # 【期待される動作】: 全ノードで親子の相集合が真部分集合、ダングリング parent_id が無い
    # 🔵 信頼性レベル: 受け入れ基準 TC-001-04 / REQ-202 に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    # 【結果検証】: 全ノードで系譜整合 (親は存在し、親の相集合は子の真部分集合)
    for h in result.hypotheses.values():
        if h.parent_id is None:
            continue
        assert h.parent_id in result.hypotheses  # 【確認内容】: ダングリング parent_id が無い 🔵
        parent = result.hypotheses[h.parent_id]
        assert _refs(parent) < _refs(h)  # 【確認内容】: 親の相集合は子の真部分集合 🔵

    # 【期待値確認】: {A,B} の親が単相 {A} または {B} である
    ab = _node_with_refs(result, {"A", "B"})
    assert ab is not None and ab.parent_id is not None  # 【確認内容】: 深さ 2 ノードが生成される 🔵
    assert _refs(result.hypotheses[ab.parent_id]) in ({"A"}, {"B"})  # 【確認内容】: 親は単相部分集合 🔵


def test_below_threshold_candidates_not_expanded():
    # 【テスト目的】: 枝刈り閾値未満の候補 (無関係相) がノード展開されない (TC-002-02 統合視点)
    # 【テスト内容】: 候補 4 (C/D 低スコア) で C/D の単相ノードが hypotheses に現れない
    # 【期待される動作】: 全仮説の相集合に C/D が含まれず、"prune_threshold" が ledger に記録される
    # 🟡 信頼性レベル: TC-002-02 は 🔵 だが TASK-0006 での統合確認という位置づけは妥当な推測

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    # 【結果検証】: C/D は「削除」でなく「非展開 + 記録」で扱われる (REQ-405)
    for h in result.hypotheses.values():
        assert "C" not in _refs(h)  # 【確認内容】: 閾値未満の C がどのノードにも展開されない 🔵
        assert "D" not in _refs(h)  # 【確認内容】: 閾値未満の D がどのノードにも展開されない 🔵
    kinds = [e.kind for e in result.ledger.entries]
    assert "prune_threshold" in kinds  # 【確認内容】: 枝刈り閾値の算出が ledger 追跡可能 🔵


def test_jaccard_reduction_keeps_alternatives():
    # 【テスト目的】: 等構造 2 候補が縮約され代表のみ探索、alternatives に代替候補を保持 (FR-114)
    # 【テスト内容】: A と A'(a=5.001) が 1 クラスタに縮約され、片方のみ探索対象になる
    # 【期待される動作】: alternatives に {代表idx: (代替idx,)}、代替の単相ノードは hypotheses に無い
    # 🔵 信頼性レベル: interfaces.py L143-199 / FR-114 / REQ-103 に直接依拠

    # 【テストデータ準備】: 単相 A データ + 等構造候補 A' + 無関係 C (候補 3 で枝刈り無効)
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_A_PRIME, PHASE_C])

    # 【結果検証】: 代表 idx → 代替 idx の縮約が alternatives に保持される (非破壊性)
    assert result.alternatives  # 【確認内容】: 代替候補が消失せず保持される 🔵
    assert len(result.alternatives) == 1  # 【確認内容】: 縮約クラスタは 1 つ (A/A') 🔵
    rep = next(iter(result.alternatives))
    assert set((rep,) + tuple(result.alternatives[rep])) == {0, 1}  # 【確認内容】: A/A' が同クラスタ 🔵

    # 【期待値確認】: 等構造の片方 (非代表) の単相ノードは探索されない
    single_refs = {
        next(iter(_refs(h)))
        for h in result.hypotheses.values()
        if h.parent_id is None and len(h.phases) == 1
    }
    assert len({"A", "Aprime"} & single_refs) == 1  # 【確認内容】: 代表 1 相のみ探索される 🔵
    kinds = [e.kind for e in result.ledger.entries]
    assert "cluster" in kinds  # 【確認内容】: クラスタ縮約が ledger 記録される 🔵


def test_ledger_verify_true_after_search():
    # 【テスト目的】: 探索実行後 ledger.verify() が True (TC-008-01)
    # 【テスト内容】: 全 append が正しく連鎖し改竄検証が通る (かつ空 ledger の自明 True でない)
    # 【期待される動作】: ledger.verify() is True かつ entries 非空
    # 🔵 信頼性レベル: 受け入れ基準 TC-008-01 に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    assert result.ledger.verify() is True  # 【確認内容】: ハッシュ連鎖が無傷 🔵
    assert len(result.ledger.entries) > 0  # 【確認内容】: 空 ledger の自明 True でない 🔵


def test_ledger_records_all_operation_kinds():
    # 【テスト目的】: 主要 5 操作 + 採択が kind 別に ledger 記録される (TC-008-02)
    # 【テスト内容】: match_score/cluster/prune_threshold/node_refine/branch_prune/ranking を包含
    # 【期待される動作】: 各 kind が 1 件以上、payload が JSON シリアライズ可能な素の型
    # 🔵 信頼性レベル: 受け入れ基準 TC-008-02 / dataflow.md 設計名に直接依拠

    # 【テストデータ準備】: 単相 A + 等構造 A' (cluster 発生) + 真相 B (余剰相追加で branch_prune)
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_A_PRIME, PHASE_B])

    # 【結果検証】: 全操作が単一 kind に潰れず設計名で区別記録される
    kinds = {e.kind for e in result.ledger.entries}
    required = {
        "match_score",
        "cluster",
        "prune_threshold",
        "node_refine",
        "branch_prune",
        "ranking",
    }
    assert required <= kinds  # 【確認内容】: 監査の粒度 (kind 別) を満たす 🔵

    # 【期待値確認】: payload が canonical JSON 化可能な素の型に限定される
    for entry in result.ledger.entries:
        json.dumps(entry.payload)  # 【確認内容】: 素の型 (float/int/str/list) で直列化可能 🔵


def test_search_result_skeleton_contract():
    # 【テスト目的】: SearchResult 骨格契約 — ID 形式 / 入力正規化 / TASK-0007 ダミー (TC-N09)
    # 【テスト内容】: 素の PhaseInstance と PhaseCandidate 両形で探索でき、ダミーフィールドは空値
    # 【期待される動作】: ID が ^hyp-\\d{4}$ 一意連番、good_cluster_ids/final_reports/warnings が空
    # 🔵 信頼性レベル: interfaces.py L143-199 / requirements §2.2・§2.4 に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)

    # 【実際の処理実行】: 素の PhaseInstance と PhaseCandidate(delta_u=0.0) の両受け入れ形
    raw = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B])
    wrapped = HypothesisTreeSearch(backend).search(
        GRID, y, [PhaseCandidate(phase=PHASE_A), PhaseCandidate(phase=PHASE_B)]
    )

    # 【結果検証】: 両入力形で骨格契約 (ID 形式・スコープ境界ダミー) が満たされる
    for result in (raw, wrapped):
        assert result.hypotheses  # 【確認内容】: 両入力形で探索が成功 🔵
        for hid in result.hypotheses:
            assert re.match(r"^hyp-\d{4}$", hid)  # 【確認内容】: ID が hyp-XXXX 連番形式 🔵
        assert result.good_cluster_ids == ()  # 【確認内容】: TASK-0007 ダミー空 🔵
        assert result.final_reports == {}  # 【確認内容】: TASK-0007 ダミー空 Mapping 🔵
        assert result.warnings == ()  # 【確認内容】: TASK-0007 ダミー空 🔵
        assert result.unmatched.unmatched_observed == ()  # 【確認内容】: unmatched は空ダミー 🔵
        for rk in result.ranked:
            assert rk.hypothesis.id in result.hypotheses  # 【確認内容】: ランキング ID が整合 🔵


def test_explore_mode_refine_uses_scale_lattice_and_max_cycles():
    # 【テスト目的】: 探索モード精密化が scale+lattice free_params と explore_max_cycles で呼ばれる (D2)
    # 【テスト内容】: backend.refine 直呼びの free_params と max_cycles をスパイで観測
    # 【期待される動作】: free_params == {phase0.scale, phase0.lattice.a/b/c}、max_cycles == 5 (既定)
    # 🔵 信頼性レベル: architecture.md D2 / REQ-003 / FR-113 に直接依拠 (スパイ検証方式は 🟡)

    # 【既定サイクル数の確認】: SimulatedBackend をラップしたスパイで呼び出し契約を観測
    spy = RecordingSpyBackend()
    y = spy.simulate([PHASE_A], GRID)
    HypothesisTreeSearch(spy).search(GRID, y, [PHASE_A])

    assert spy.refine_calls  # 【確認内容】: ノード評価で refine が直接呼ばれる 🔵
    nonempty = [fp for fp, _ in spy.refine_calls if fp]
    assert nonempty  # 【確認内容】: 実体パラメータを解放した refine 呼び出しが存在 🔵
    for fp in nonempty:
        # 【確認内容】: 全相の 4 パラメータのみ (occupancy 等が free に入らない) 🔵
        assert fp == _EXPLORE_FREE_1PHASE
    for _, mc in spy.refine_calls:
        assert mc == 5  # 【確認内容】: 既定 explore_max_cycles=5 で呼ばれる 🔵

    # 【明示サイクル数の確認】: SearchConfig(explore_max_cycles=3) が refine へ伝播する
    spy3 = RecordingSpyBackend()
    HypothesisTreeSearch(spy3, config=SearchConfig(explore_max_cycles=3)).search(GRID, y, [PHASE_A])
    assert spy3.refine_calls  # 【確認内容】: 明示設定でも refine が呼ばれる 🔵
    assert all(mc == 3 for _, mc in spy3.refine_calls)  # 【確認内容】: 明示 max_cycles=3 が伝播 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (縮退・非例外化・非破壊契約)
# ---------------------------------------------------------------------------


def test_zero_candidates_returns_empty_result_without_error():
    # 【テスト目的】: 候補ゼロで空ランキング・例外なしに縮退する (TC-E01 / EDGE-001)
    # 【テスト内容】: candidates=[] で IndexError/ValueError を出さず空 SearchResult を返す
    # 【期待される動作】: ranked==() / hypotheses=={} / alternatives=={}、ledger/snapshots は実体
    # 🔵 信頼性レベル: 受け入れ基準 TC-E01 / EDGE-001 / note.md §6 に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)

    # 【実際の処理実行】: 探索空間が空でも例外化せず縮退する
    result = HypothesisTreeSearch(backend).search(GRID, y, [])

    assert result.ranked == ()  # 【確認内容】: 空ランキング 🔵
    assert dict(result.hypotheses) == {}  # 【確認内容】: 空 Mapping 🔵
    assert dict(result.alternatives) == {}  # 【確認内容】: 空 Mapping 🔵
    assert result.ledger.verify() is True  # 【確認内容】: 空でも ledger 実体を返し検証が通る 🔵
    assert result.snapshots is not None  # 【確認内容】: 空でも snapshots 実体を返す 🔵


def test_infinite_chi2_node_demoted_search_completes():
    # 【テスト目的】: ノード精密化が chi2=inf を返しても探索全体が完走する (TC-E03 / EDGE-004)
    # 【テスト内容】: 相 B を含むノードだけ chi2=inf を返す FakeBackend で降格ルートを確認
    # 【期待される動作】: 例外なし、有限 chi2 の {A} が上位、inf ノードも metrics 付きで残る
    # 🔵 信頼性レベル: 受け入れ基準 TC-E03 / EDGE-004 / architecture.md D2 に直接依拠

    inf = float("inf")
    fake = FakeBackend(
        rwp_by_refs={frozenset({"A"}): 5.0},
        chi2_by_refs={frozenset({"B"}): inf, frozenset({"A", "B"}): inf},
        default_chi2=10.0,
        default_rwp=50.0,
    )
    y = fake.simulate([PHASE_A, PHASE_B], GRID)

    # 【実際の処理実行】: 1 ノードの失敗で探索全体を落とさない (Dara 教訓)
    result = HypothesisTreeSearch(fake).search(GRID, y, [PHASE_A, PHASE_B])

    # 【結果検証】: 有限 chi2 の {A} 系が上位、inf ノードは降格され metrics 付きで残る
    assert result.ranked  # 【確認内容】: 例外なく SearchResult を返す 🔵
    assert "A" in _refs(result.ranked[0].hypothesis)  # 【確認内容】: 有限 chi2 の {A} 系が上位 🔵
    assert all(h.metrics is not None for h in result.hypotheses.values())  # 【確認内容】: metrics 必須 🔵
    inf_nodes = [
        h for h in result.hypotheses.values() if h.metrics is not None and math.isinf(h.metrics.chi2)
    ]
    assert inf_nodes  # 【確認内容】: inf ノードも hypotheses に残る (rank の ValueError 回避) 🔵
    kinds = [e.kind for e in result.ledger.entries]
    assert "branch_prune" in kinds  # 【確認内容】: 降格が理由付き ledger 記録される 🔵


def test_all_infinite_hypotheses_guarded_against_nan():
    # 【テスト目的】: 全仮説 chi2=inf でも NaN に縮退せず完走する (NaN ガード)
    # 【テスト内容】: 全組合せ chi2=inf の FakeBackend で softmax の 0/0 NaN 化を防ぐ
    # 【期待される動作】: 例外なし・NaN なしで SearchResult が返り、各 probability が非 NaN
    # 🟡 信頼性レベル: ガード必要性は note.md §6 に依拠 🔵 だが具体方針は実装時確定 🟡

    inf = float("inf")
    fake = FakeBackend(default_chi2=inf, default_rwp=80.0)
    y = fake.simulate([PHASE_A, PHASE_B], GRID)

    # 【実際の処理実行】: 全滅ケースで NaN が下流へ伝播しないことを確認
    result = HypothesisTreeSearch(fake).search(GRID, y, [PHASE_A, PHASE_B])

    assert result.ranked  # 【確認内容】: 全滅でもランキングを返す (下流の集計を壊さない) 🔵
    for rk in result.ranked:
        assert not math.isnan(rk.probability)  # 【確認内容】: 確率が NaN 化しない (数値健全性) 🟡


def test_no_destructive_api_on_engine_and_result():
    # 【テスト目的】: 探索エンジン・SearchResult に削除・上書き API が存在しない (TC-008-03)
    # 【テスト内容】: 公開名に破壊系プレフィックスが無く、SearchResult が frozen であることを静的検証
    # 【期待される動作】: delete/remove/clear/overwrite/pop/update 系の公開名なし、再代入で FrozenInstanceError
    # 🔵 信頼性レベル: 受け入れ基準 TC-008-03 / NFR-101 / REQ-405 に直接依拠 (dir() 検証は 🟡)

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    engine = HypothesisTreeSearch(backend)
    result = engine.search(GRID, y, [PHASE_A])

    # 【結果検証】: 公開名に破壊系の名称が 1 つも含まれない (誤 mutation API のリグレッション防止)
    banned = ("delete", "remove", "clear", "overwrite", "pop", "update")
    for obj in (engine, result):
        for name in dir(obj):
            if name.startswith("_"):
                continue
            low = name.lower()
            assert not any(b in low for b in banned), name  # 【確認内容】: 破壊系公開 API が無い 🔵

    # 【期待値確認】: SearchResult は frozen dataclass でフィールド再代入が禁止される
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.ranked = ()  # 【確認内容】: 事後改変不能 (型レベルの非破壊性担保) 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース (上限・最小・決定論・閾値境界)
# ---------------------------------------------------------------------------


def test_max_phases_two_blocks_three_phase_hypotheses():
    # 【テスト目的】: max_phases=2 で 3 相仮説が生成されない (TC-003-02 / EDGE-101)
    # 【テスト内容】: 3 相合成 (A+B+G) でも上限 2 が唯一の阻止要因になるよう設計
    # 【期待される動作】: 全仮説の相数 <= 2 かつ 2 相仮説は存在する (上限ちょうどは生成)
    # 🔵 信頼性レベル: 受け入れ基準 TC-003-02 / REQ-401 / EDGE-101 に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B, PHASE_G], GRID)
    result = HypothesisTreeSearch(backend, config=SearchConfig(max_phases=2)).search(
        GRID, y, [PHASE_A, PHASE_B, PHASE_G, PHASE_D]
    )

    # 【結果検証】: 「2 は許可 / 3 は不許可」の境界が正しい (上限超は生成前に打ち切り)
    for h in result.hypotheses.values():
        assert len(h.phases) <= 2  # 【確認内容】: 3 相仮説が 1 つも生成されない 🔵
    assert any(len(h.phases) == 2 for h in result.hypotheses.values())  # 【確認内容】: 2 相は生成される 🔵


def test_search_config_defaults():
    # 【テスト目的】: SearchConfig 既定値の確認 — max_phases=5 ほか全 11 フィールド (TC-003-03)
    # 【テスト内容】: 引数なし SearchConfig() が interfaces.py の全既定値と一致し frozen であること
    # 【期待される動作】: 全既定値が仕様どおり、フィールド再代入で FrozenInstanceError
    # 🔵 信頼性レベル: 受け入れ基準 TC-003-03 / interfaces.py 既定値表に直接依拠

    c = SearchConfig()
    assert c.max_phases == 5  # 【確認内容】: 1 仮説の最大相数 🔵
    assert c.r_improve_pct == 2.0  # 【確認内容】: Rwp 改善打ち切り閾値 (ポイント) 🔵
    assert c.match_tol_deg == 0.15  # 【確認内容】: マッチング許容 2θ 🔵
    assert c.min_peak_height_frac == 0.05  # 【確認内容】: ピーク高さ閾値 🔵
    assert c.prune_min_candidates == 4  # 【確認内容】: 枝刈り最小候補数 🔵
    assert c.jaccard_threshold == 0.85  # 【確認内容】: クラスタ類似閾値 🔵
    assert c.explore_max_cycles == 5  # 【確認内容】: 探索モード精密化サイクル 🔵
    assert c.final_full_refine is True  # 【確認内容】: TASK-0007 用フラグ既定 🔵
    assert c.max_final_refine == 3  # 【確認内容】: TASK-0007 用既定 🔵
    assert c.high_r_threshold == 30.0  # 【確認内容】: TASK-0007 用 (Rwp%) 既定 🔵
    assert c.close_threshold == 10.0  # 【確認内容】: ΔBIC 僅差競合閾値 🔵

    with pytest.raises(dataclasses.FrozenInstanceError):
        c.max_phases = 3  # 【確認内容】: frozen による不変性 🔵

    # 【一貫した動作】: 既定 evidence が BICBackend (name=="bic") である __init__ 既定も確認 (REQ-004)
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A])
    assert result.ranked[0].evidence.backend == "bic"  # 【確認内容】: 既定 evidence が BIC 🔵


def test_single_candidate_yields_depth_one_tree():
    # 【テスト目的】: 候補 1 相 → 深さ 1 の木・単一仮説 (TC-E04 / EDGE-102)
    # 【テスト内容】: 探索空間の最小非空ケース (N=1) で組合せ展開なしに単一仮説が評価・ランクされる
    # 【期待される動作】: hypotheses が 1 件・深さ 1、ranked 長 1、probability ≈ 1.0 (単独 softmax)
    # 🔵 信頼性レベル: 受け入れ基準 TC-E04 / EDGE-102 に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A])

    assert len(result.hypotheses) == 1  # 【確認内容】: 深さ 2 への展開が起きない 🔵
    h = next(iter(result.hypotheses.values()))
    assert len(h.phases) == 1  # 【確認内容】: 単一相仮説 🔵
    assert h.parent_id is None  # 【確認内容】: 深さ 1 (根の直下) 🔵
    assert len(result.ranked) == 1  # 【確認内容】: ランキング長 1 🔵
    assert result.ranked[0].probability == pytest.approx(1.0)  # 【確認内容】: 単独 softmax は確率 1.0 🔵


def test_deterministic_bit_identical_across_runs():
    # 【テスト目的】: 同一入力 2 回実行でランキング・確率がビット同一 (TC-001-05)
    # 【テスト内容】: エンジンも 2 個生成し独立に search() を実行、pytest.approx を使わず == で比較
    # 【期待される動作】: ranked の (id, probability, evidence.value) 列と hypotheses キー列がビット同一
    # 🔵 信頼性レベル: 受け入れ基準 TC-001-05 / REQ-403 / NFR-102 に直接依拠

    def once():
        backend = SimulatedBackend(peak_fwhm=0.2)
        y = backend.simulate([PHASE_A, PHASE_B], GRID)
        return HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    r1, r2 = once(), once()

    # 【結果検証】: float の == 一致 (丸め揺らぎゼロ) — set/dict 順序由来の非決定性が無い
    order1 = [(rk.hypothesis.id, rk.probability, rk.evidence.value) for rk in r1.ranked]
    order2 = [(rk.hypothesis.id, rk.probability, rk.evidence.value) for rk in r2.ranked]
    assert order1 == order2  # 【確認内容】: ランキング・確率・evidence がビット同一 🔵
    assert list(r1.hypotheses.keys()) == list(r2.hypotheses.keys())  # 【確認内容】: キー列が同順 🔵
    assert [e.kind for e in r1.ledger.entries] == [
        e.kind for e in r2.ledger.entries
    ]  # 【確認内容】: ledger の kind 列が同順 🔵


def test_r_improve_exactly_threshold_expands():
    # 【テスト目的】: R 改善がちょうど r_improve_pct なら展開側 (境界包含 >=) (TC-B05)
    # 【テスト内容】: 親 {A}=10.0、子 {A,B}=8.0 (改善 2.0)、子 {A,C}=8.01 (改善 1.99) を FakeBackend で注入
    # 【期待される動作】: {A,B} は展開 (子を持つ)、{A,C} は展開されず branch_prune が記録される
    # 🟡 信頼性レベル: 判定式・絶対点解釈は依拠するが「等号包含」自体は実装時確定 🟡

    fake = FakeBackend(
        rwp_by_refs={
            frozenset({"A"}): 10.0,
            frozenset({"B"}): 10.0,
            frozenset({"C"}): 10.0,
            frozenset({"A", "B"}): 8.0,  # 改善ちょうど 2.0 → 展開側
            frozenset({"A", "C"}): 8.01,  # 改善 1.99 → 打ち切り
        },
        default_chi2=10.0,
    )
    y = fake.simulate([PHASE_A, PHASE_B, PHASE_C], GRID)
    result = HypothesisTreeSearch(fake, config=SearchConfig(r_improve_pct=2.0)).search(
        GRID, y, [PHASE_A, PHASE_B, PHASE_C]
    )

    # 【結果検証】: 展開の有無を「子ノードの有無」で観測する (等号包含 >= の確認)
    ab = _node_with_refs(result, {"A", "B"})
    ac = _node_with_refs(result, {"A", "C"})
    assert ab is not None  # 【確認内容】: {A,B} は評価される 🔵
    assert any(h.parent_id == ab.id for h in result.hypotheses.values())  # 【確認内容】: {A,B} は展開 🔵
    if ac is not None:
        # 【確認内容】: 改善 1.99 の {A,C} は展開されない (子を持たない) 🔵
        assert not any(h.parent_id == ac.id for h in result.hypotheses.values())
    kinds = [e.kind for e in result.ledger.entries]
    assert "branch_prune" in kinds  # 【確認内容】: 改善不足の打ち切りが記録される 🔵


def test_fewer_than_min_candidates_disables_pruning():
    # 【テスト目的】: 候補 3 以下では枝刈り無効 (全展開へフォールバック) (TC-002-03 統合視点)
    # 【テスト内容】: 候補 3 (A + 低スコア C/D) で dynamic_threshold が -inf に縮退し全候補が展開される
    # 【期待される動作】: 深さ 1 の単相仮説が 3 候補すべてについて hypotheses に存在する
    # 🟡 信頼性レベル: 受け入れ基準 TC-002-03 が 🟡 (妥当な推測) であることに準ずる

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_C, PHASE_D])

    # 【結果検証】: 低スコア候補も含め全候補が深さ 1 ノードとして評価される (枝刈りで消えない)
    single_refs = {
        next(iter(_refs(h)))
        for h in result.hypotheses.values()
        if h.parent_id is None and len(h.phases) == 1
    }
    assert {"A", "C", "D"} <= single_refs  # 【確認内容】: 候補 3 では全展開 (刈られない) 🔵
    kinds = [e.kind for e in result.ledger.entries]
    assert "prune_threshold" in kinds  # 【確認内容】: -inf 閾値 (全展開) も記録される 🔵
