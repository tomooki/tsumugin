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
        # 【TASK-0007 整合】: good_cluster_ids / final_reports は TASK-0007 で実体化された。
        #   旧スタブ (空値) 断言は TC-N11/TC-B07 (良好解・フル精密化の非空要件) と矛盾するため、
        #   最良解が良好解に含まれ・精密化対象が良好解の部分集合であることの契約検証へ最小修正する。
        assert isinstance(result.good_cluster_ids, tuple)  # 【確認内容】: 良好解 ID は tuple 🔵
        assert result.ranked[0].hypothesis.id in result.good_cluster_ids  # 最良解が良好解 🔵
        assert set(result.final_reports) <= set(result.good_cluster_ids)  # 精密化対象⊆良好解 🔵
        assert result.warnings == ()  # 【確認内容】: 非フラットなので警告なし 🔵
        assert result.unmatched.unmatched_observed == ()  # 【確認内容】: 完全説明で未マッチ空 🔵
        for rk in result.ranked:
            assert rk.hypothesis.id in result.hypotheses  # 【確認内容】: ランキング ID が整合 🔵


def test_explore_mode_refine_uses_scale_lattice_and_max_cycles():
    # 【テスト目的】: 探索モード精密化が scale+lattice free_params と explore_max_cycles で呼ばれる (D2)
    # 【テスト内容】: backend.refine 直呼びの free_params と max_cycles をスパイで観測
    # 【期待される動作】: free_params == {phase0.scale, phase0.lattice.a/b/c}、max_cycles == 5 (既定)
    # 🔵 信頼性レベル: architecture.md D2 / REQ-003 / FR-113 に直接依拠 (スパイ検証方式は 🟡)

    # 【既定サイクル数の確認】: SimulatedBackend をラップしたスパイで呼び出し契約を観測
    # 【TASK-0007 整合】: 本ケースは「探索モード」精密化の free_params/max_cycles 契約 (D2) の
    #   検証が目的。TASK-0007 で有効化された最終フル精密化 (StagedRefinementEngine, max_cycles=20 /
    #   段階別 free_params) はスパイに別契約の refine を混入させ本旨を覆すため、対照的に
    #   final_full_refine=False で切り離して探索モードのみを観測する (要件矛盾の最小修正)。
    spy = RecordingSpyBackend()
    y = spy.simulate([PHASE_A], GRID)
    HypothesisTreeSearch(spy, config=SearchConfig(final_full_refine=False)).search(
        GRID, y, [PHASE_A]
    )

    assert spy.refine_calls  # 【確認内容】: ノード評価で refine が直接呼ばれる 🔵
    nonempty = [fp for fp, _ in spy.refine_calls if fp]
    assert nonempty  # 【確認内容】: 実体パラメータを解放した refine 呼び出しが存在 🔵
    for fp in nonempty:
        # 【確認内容】: 全相の 4 パラメータのみ (occupancy 等が free に入らない) 🔵
        assert fp == _EXPLORE_FREE_1PHASE
    for _, mc in spy.refine_calls:
        assert mc == 5  # 【確認内容】: 既定 explore_max_cycles=5 で呼ばれる 🔵

    # 【明示サイクル数の確認】: SearchConfig(explore_max_cycles=3) が refine へ伝播する
    # 【TASK-0007 整合】: 上記同様、探索モード伝播のみを観測するためフル精密化を切り離す。
    spy3 = RecordingSpyBackend()
    HypothesisTreeSearch(
        spy3, config=SearchConfig(explore_max_cycles=3, final_full_refine=False)
    ).search(GRID, y, [PHASE_A])
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


# ===========================================================================
# TASK-0007 探索後処理 (good_cluster / final_reports / unmatched / warnings /
# to_summary) の失敗テスト (TDD Red)。既存 20 ケースはそのままに、TC-N11〜18 /
# TC-E05〜07 / TC-B07〜11 の 16 ケースを追加する。現状の tree.py はこれらを
# スタブ (空値/最小 summary) で返すため、下記アサーションは全て失敗する想定。
#
# 書式の範: 上記既存ケース / docs/implements/.../TASK-0007/search-postprocess-*。
# ===========================================================================

# 【スキーマ契約】: to_summary() トップレベルの必須キー集合 (api-endpoints.md /api/result)。🔵
_SUMMARY_TOP_KEYS = {
    "ranked",
    "unknown_phase_flag",
    "unmatched_observed",
    "extra_calculated",
    "warnings",
    "n_hypotheses",
}

# 【スキーマ契約】: to_summary()["ranked"][i] の必須キー集合 (note §4.4)。🔵
_SUMMARY_RANKED_KEYS = {
    "id",
    "rank",
    "probability",
    "close_competitor",
    "rwp",
    "gof",
    "evidence",
    "phases",
    "parent_id",
    "in_good_cluster",
}


def _run_ab_search(config: SearchConfig | None = None) -> SearchResult:
    """A+B 合成データ・候補 [A,B,C,D] の標準探索を実行する共通ヘルパ (後処理系で再利用)。

    C/D は無関係相で枝刈りされ hypotheses は {A}/{B}/{A,B} の 3 ノードに収束するため、
    良好解抽出・フル精密化・再ランクの後処理を最小コストで検証できる (実行時間抑制)。🔵
    """
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)
    engine = HypothesisTreeSearch(backend, config=config or SearchConfig())
    return engine.search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])


# ---------------------------------------------------------------------------
# 1. 正常系テストケース (TC-N11〜N18)
# ---------------------------------------------------------------------------


def test_jenks_good_cluster_ids_contains_top_and_excludes_worst():
    # 【テスト目的】: Jenks が低 evidence 群 (良好解) を分離し good_cluster_ids に ID が入る (TC-N11)
    # 【テスト内容】: A+B 合成・候補 [A,B,C,D] で search() を実行し good_cluster_ids を検証
    # 【期待される動作】: rank1 (最良) の ID が含まれ、最劣位 (evidence 最大) の ID は含まれない
    # 🔵 信頼性レベル: acceptance-criteria TC-004-03 / FR-116 / REQ-104 に直接依拠

    # 【テストデータ準備】: 真の相 A/B + 無関係相 C/D で evidence が良好/劣位の 2 群に分かれる
    # 【前提条件確認】: 既存 TC-N01 で {A,B} が rank1 になることは保証済み
    result = _run_ab_search()

    # 【結果検証】: good_cluster_ids は非空の ID タプルで rank1 を含み最劣位を含まない
    assert isinstance(result.good_cluster_ids, tuple)  # 【確認内容】: 戻り値は tuple 🔵
    assert result.good_cluster_ids  # 【確認内容】: 良好解が非空 (スタブ () では失敗) 🔵
    assert result.ranked[0].hypothesis.id in result.good_cluster_ids  # 【確認内容】: 最良解が含まれる 🔵
    for hid in result.good_cluster_ids:
        assert hid in result.hypotheses  # 【確認内容】: 中身は index でなく仮説 ID である 🔵
    worst_id = result.ranked[-1].hypothesis.id
    assert worst_id not in result.good_cluster_ids  # 【確認内容】: 最劣位仮説は良好解に入らない 🔵


def test_final_full_refine_records_reports_and_updates_metrics():
    # 【テスト目的】: 良好解上位にフル精密化が適用され final_reports 記録と metrics 更新が起きる (TC-N12)
    # 【テスト内容】: 既定 config (final_full_refine=True) で final_reports と hypotheses metrics を検証
    # 【期待される動作】: final_reports のキーが good_cluster_ids に含まれ、metrics が report と整合する
    # 🟡 信頼性レベル: architecture.md D3 / 要件定義 §3.6 からの妥当な導出

    result = _run_ab_search()

    # 【結果検証】: final_reports が非空で全キーが良好解、件数は max_final_refine 以内
    assert result.final_reports  # 【確認内容】: フル精密化記録が非空 (スタブ {} では失敗) 🟡
    assert len(result.final_reports) <= SearchConfig().max_final_refine  # 【確認内容】: 上位のみ精密化 🟡
    for key, report in result.final_reports.items():
        assert key in result.good_cluster_ids  # 【確認内容】: 精密化対象は良好解のみ 🟡
        # 【RefinementReport 形状】: D3 の値型は RefinementReport (5 フィールド) 🟡
        for attr in ("final_phases", "metrics", "stage_outcomes", "escalated", "free_params"):
            assert hasattr(report, attr)  # 【確認内容】: RefinementReport のフィールドを備える 🟡
        hyp = result.hypotheses[key]
        assert hyp.metrics is not None  # 【確認内容】: 精密化後ノードは metrics を持つ 🟡
        # 【非破壊反映】: hypotheses[key] の metrics が report.metrics と整合 (rwp/gof) 🟡
        assert hyp.metrics.rwp == report.metrics.rwp  # 【確認内容】: rwp がフル精密化値に更新 🟡
        assert hyp.metrics.gof == report.metrics.gof  # 【確認内容】: gof がフル精密化値に更新 🟡
        assert "bic" in hyp.metrics.evidence  # 【確認内容】: BIC が再計算され格納される 🟡


def test_reranking_orders_ranked_ascending_after_full_refine():
    # 【テスト目的】: フル精密化後に rank() が再実行され ranked が evidence 昇順で確定する (TC-N13)
    # 【テスト内容】: 再ランク後の evidence 値列の単調性と ranked/hypotheses の整合を検証
    # 【期待される動作】: evidence 値が昇順、rank1 が {A,B}、各 evidence が hypotheses の bic と一致
    # 🟡 信頼性レベル: architecture.md D3 + ranking 既存契約からの妥当な導出

    result = _run_ab_search()

    # 【結果検証】: 再ランク後の evidence 値が昇順 (良い順) で真の構成が 1 位を維持する
    values = [rk.evidence.value for rk in result.ranked]
    assert values == sorted(values)  # 【確認内容】: evidence 値列が非減少 (昇順) 🟡
    assert _refs(result.ranked[0].hypothesis) == {"A", "B"}  # 【確認内容】: rank1 が真の構成 {A,B} 🟡
    # 【整合性】: ranked の evidence が更新後 hypotheses の bic と一致 (同一 metrics で再計算) 🟡
    for rk in result.ranked:
        bic = result.hypotheses[rk.hypothesis.id].metrics.evidence["bic"]
        assert rk.evidence.value == bic  # 【確認内容】: 更新後の値で整列している 🟡
    # 【フル精密化の実行痕跡】: 再ランクはフル精密化後に走る (スタブ {} では失敗) 🟡
    assert result.ranked[0].hypothesis.id in result.final_reports  # 【確認内容】: rank1 が精密化済み 🟡


def test_final_full_refine_disabled_keeps_reports_empty():
    # 【テスト目的】: final_full_refine=False でフル精密化がスキップされる (TC-N14)
    # 【テスト内容】: 無効時 final_reports は空だが良好解抽出等その他後処理は成立することを検証
    # 【期待される動作】: final_reports=={} かつ good_cluster_ids は有効時と同一で非空
    # 🟡 信頼性レベル: 要件定義 §3.6 (D3 無効化仕様) に依拠した妥当な導出

    # 【対照実験】: 同一データで有効/無効の差分だけを観測する
    res_on = _run_ab_search(SearchConfig(final_full_refine=True))
    res_off = _run_ab_search(SearchConfig(final_full_refine=False))

    # 【結果検証】: 無効時はフル精密化記録が空、その他後処理は有効時と同一に成立
    assert dict(res_off.final_reports) == {}  # 【確認内容】: 無効時 final_reports は空 Mapping 🟡
    assert res_on.final_reports  # 【確認内容】: 有効時は非空 (スタブでは失敗する対照) 🟡
    assert res_off.good_cluster_ids  # 【確認内容】: 無効化しても良好解抽出は成立 (スタブ () で失敗) 🟡
    assert res_off.good_cluster_ids == res_on.good_cluster_ids  # 【確認内容】: 良好解は有効時と同一 🟡
    # 【後続後処理の健全性】: unmatched / to_summary が無効時も例外なく成立 🟡
    assert "unknown_phase_flag" in res_off.to_summary()  # 【確認内容】: summary スキーマが成立 🟡


def test_complete_explanation_has_no_unmatched_and_flag_false():
    # 【テスト目的】: 候補相で完全に説明できるデータで未マッチ空・未知相フラグ False (TC-N15)
    # 【テスト内容】: A+B 合成・候補 [A,B,C,D] (真の構成が候補に含まれる) の unmatched を検証
    # 【期待される動作】: unmatched_observed==() かつ unknown_phase_flag is False
    # 🔵 信頼性レベル: acceptance-criteria TC-005-02 / REQ-005/106 に直接依拠

    result = _run_ab_search()

    # 【結果検証】: 観測の全ピークが最良仮説で説明され、偽陽性の未知相フラグが立たない
    assert result.unmatched.unmatched_observed == ()  # 【確認内容】: 未マッチ観測が空 🔵
    assert result.unmatched.unknown_phase_flag is False  # 【確認内容】: bool 型で厳密に False 🔵
    # 【スキーマ経路】: to_summary 側にもフラグ False が現れる (スタブは当該キー無しで失敗) 🔵
    assert result.to_summary()["unknown_phase_flag"] is False  # 【確認内容】: summary もフラグ False 🔵


def test_unknown_phase_reports_unmatched_peaks_with_flag():
    # 【テスト目的】: 候補にない相の混入で未マッチ観測ピークが位置・強度付きで報告される (TC-N16)
    # 【テスト内容】: A+B+G の 3 相合成 (G は候補外)・候補 [A,B,C,D] で unmatched を検証
    # 【期待される動作】: 未説明ピークが Peak 実体・位置昇順で報告され unknown_phase_flag が True
    # 🔵 信頼性レベル: acceptance-criteria TC-005-01 / REQ-005/106 に直接依拠

    from tsumugin.search.peaks import find_peaks

    # 【テストデータ準備】: G(a=6.5) を候補に入れず混ぜ、どの候補でも説明できない未知相を模擬
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B, PHASE_G], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    unmatched = result.unmatched
    # 【結果検証】: 未マッチ観測が非空で各要素が位置・正の強度を持ち位置昇順に整列する
    assert unmatched.unmatched_observed  # 【確認内容】: 未マッチ観測が報告される (スタブは空で失敗) 🔵
    positions = [pk.position for pk in unmatched.unmatched_observed]
    assert all(isinstance(pk.position, float) for pk in unmatched.unmatched_observed)  # 位置は float 🔵
    assert all(pk.height > 0.0 for pk in unmatched.unmatched_observed)  # 【確認内容】: 強度は正値 🔵
    assert positions == sorted(positions)  # 【確認内容】: 位置昇順に整列 🔵
    assert unmatched.unknown_phase_flag is True  # 【確認内容】: 未マッチ非空でフラグ True 🔵
    # 【由来検証】: 未マッチ位置の少なくとも 1 つが G 由来ピーク近傍 (match_tol_deg 相当内) 🔵
    g_peaks = [p.position for p in find_peaks(GRID, backend.simulate([PHASE_G], GRID))]
    assert g_peaks  # 【確認内容】: G は範囲内に検出可能なピークを持つ 🔵
    assert any(any(abs(pos - gp) <= 0.25 for gp in g_peaks) for pos in positions)  # G 近傍 🔵


def test_to_summary_matches_api_result_schema_and_is_json_serializable():
    # 【テスト目的】: to_summary() が /api/result スキーマの全キーを持つ純 dict で JSON 化可能 (TC-N17)
    # 【テスト内容】: キー集合・値の素の型 (str/int/float/bool)・json.dumps 往復を検証
    # 【期待される動作】: numpy スカラー/dataclass を露出しない完全な純 dict を返す
    # 🔵🟡 信頼性レベル: キー集合は api-endpoints.md 🔵 / D6 自体は設計由来 🟡

    result = _run_ab_search()
    summary = result.to_summary()

    # 【結果検証】: トップレベルの必須キーが全て存在し、件数・フラグが実体と整合
    assert _SUMMARY_TOP_KEYS <= set(summary)  # 【確認内容】: 必須トップキーを全て備える 🔵
    assert summary["n_hypotheses"] == len(result.hypotheses)  # 【確認内容】: 仮説総数が一致 🔵
    assert summary["unknown_phase_flag"] is False  # 【確認内容】: 完全説明なのでフラグ False 🔵
    assert isinstance(summary["ranked"], list)  # 【確認内容】: ranked は list (スタブは id 列で失敗) 🔵

    # 【行スキーマ】: ranked[i] が全キーを持ち rank==i+1、値が素の型である
    for i, row in enumerate(summary["ranked"]):
        assert _SUMMARY_RANKED_KEYS <= set(row)  # 【確認内容】: 行の必須キーを全て備える 🔵
        assert row["rank"] == i + 1  # 【確認内容】: rank は 1 起番の連番 🔵
        assert type(row["id"]) is str  # 【確認内容】: id は素の str 🔵
        assert type(row["rank"]) is int  # 【確認内容】: rank は素の int 🔵
        assert type(row["rwp"]) is float  # 【確認内容】: rwp は素の float (np.float64 非露出) 🔵
        assert type(row["probability"]) is float  # 【確認内容】: probability は素の float 🔵
        assert type(row["in_good_cluster"]) is bool  # 【確認内容】: in_good_cluster は素の bool 🔵
        assert set(row["evidence"]) == {"backend", "value"}  # 【確認内容】: evidence キー集合 🔵
        assert type(row["evidence"]["value"]) is float  # 【確認内容】: evidence 値は素の float 🔵
        for p in row["phases"]:
            assert {"phase_ref", "wt_frac", "lattice"} <= set(p)  # 【確認内容】: 相の必須キー 🔵
            assert {"a", "b", "c"} <= set(p["lattice"])  # 【確認内容】: 格子 a/b/c を備える 🔵
        # 【整合性】: in_good_cluster の真偽が good_cluster_ids と一致 🔵
        assert row["in_good_cluster"] == (row["id"] in result.good_cluster_ids)

    assert summary["ranked"][0]["in_good_cluster"] is True  # 【確認内容】: rank1 は良好解 🔵
    # 【JSON 化】: json.dumps が例外なく成功し、往復で同値になる 🔵
    assert json.loads(json.dumps(summary)) == summary  # 【確認内容】: JSON 往復で同値 🔵


def test_postprocess_appends_to_single_ledger_and_verifies():
    # 【テスト目的】: フル精密化・再ランクを含む後処理後も ledger.verify() が True を維持する (TC-N18)
    # 【テスト内容】: 有効/無効でエントリ総数を比較し、単一 ledger への追記と監査健全性を検証
    # 【期待される動作】: verify() is True かつ 後処理有効時のエントリ数が無効時より多い
    # 🔵 信頼性レベル: 要件定義 §3.2 / REQ-402 (単一 ledger/snapshots 共有) に直接依拠

    res_on = _run_ab_search(SearchConfig(final_full_refine=True))
    res_off = _run_ab_search(SearchConfig(final_full_refine=False))

    # 【結果検証】: 後処理を含めても監査チェーンが 1 本で健全、記録は追記で増える
    assert res_on.ledger.verify() is True  # 【確認内容】: 後処理後も改竄検証が通る 🔵
    assert len(res_on.ledger.entries) > 0  # 【確認内容】: 空 ledger の自明 True でない 🔵
    # 【追記のみ】: フル精密化分だけエントリが上乗せされる (スタブは同数で失敗) 🔵
    assert len(res_on.ledger.entries) > len(res_off.ledger.entries)  # 【確認内容】: 後処理分の追記 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (TC-E05〜E07)
# ---------------------------------------------------------------------------


def test_all_high_r_forces_unknown_phase_flag():
    # 【テスト目的】: 全 refined 仮説の Rwp が閾値超のとき未知相フラグが強制的に立つ (TC-E05)
    # 【テスト内容】: 全組合せ Rwp=50 (>既定 30) の FakeBackend で縮退経路を検証
    # 【期待される動作】: 例外なく完走し unknown_phase_flag is True、最良仮説は結果に残る
    # 🔵 信頼性レベル: acceptance-criteria TC-E02 / EDGE-002 / REQ-106 に直接依拠

    # 【テストデータ準備】: どの候補も観測を説明できない (全 Rwp=50 > high_r_threshold=30) 全滅状況
    fake = FakeBackend(default_rwp=50.0, default_chi2=10.0)
    y = fake.simulate([PHASE_A, PHASE_B], GRID)

    # 【実際の処理実行】: 全高 R でも例外化せず結果構造を完全な形で返す
    result = HypothesisTreeSearch(fake).search(GRID, y, [PHASE_A, PHASE_B])

    # 【結果検証】: 未マッチの有無に依らずフラグが強制 True、最良仮説が要確認情報として返る
    assert result.ranked  # 【確認内容】: 全滅でも最良仮説を返す 🔵
    assert result.unmatched.unknown_phase_flag is True  # 【確認内容】: all(rwp>threshold) で強制 True 🔵
    assert result.to_summary()["unknown_phase_flag"] is True  # 【確認内容】: summary もフラグ True 🔵


def test_flat_pattern_degrades_with_warnings_and_no_flag():
    # 【テスト目的】: 観測ピーク 0 のフラットパターンで例外なく縮退し警告が積まれる (TC-E06)
    # 【テスト内容】: 完全フラット強度で good_cluster 空・warnings 非空・フラグ False を検証
    # 【期待される動作】: 例外なし、good_cluster_ids==()、warnings 非空、unknown_phase_flag is False
    # 🟡 信頼性レベル: acceptance-criteria TC-005-03 / EDGE-003 (フラグ False は note §6 設計) に依拠

    # 【テストデータ準備】: 強度一定 (find_peaks が () を返しマッチング対象が存在しない縮退入力)
    backend = SimulatedBackend(peak_fwhm=0.2)
    intensity = np.full_like(GRID, 100.0)

    # 【実際の処理実行】: 空測定でもパイプラインを止めず警告へ縮退する
    result = HypothesisTreeSearch(backend).search(GRID, intensity, [PHASE_A, PHASE_B])

    # 【結果検証】: 空良好解 + 警告蓄積。説明対象が無いので未知相フラグは立てない (EDGE-002 と区別)
    assert result.good_cluster_ids == ()  # 【確認内容】: 良好解は空 🟡
    assert len(result.warnings) >= 1  # 【確認内容】: 縮退理由の警告が積まれる (スタブ () で失敗) 🟡
    assert all(isinstance(w, str) for w in result.warnings)  # 【確認内容】: 警告は文字列 🟡
    assert result.unmatched.unknown_phase_flag is False  # 【確認内容】: フラット時はフラグ False 🟡
    summary = result.to_summary()
    assert summary["warnings"]  # 【確認内容】: summary にも警告が現れる 🟡
    json.dumps(summary)  # 【確認内容】: 空スキーマの summary が JSON 化可能 🟡


def test_zero_candidates_empty_result_has_empty_schema_summary():
    # 【テスト目的】: 候補ゼロで空 SearchResult が返り to_summary が空スキーマで成立する (TC-E07)
    # 【テスト内容】: candidates=[] で good_cluster/final_reports/unmatched が空、summary が同一スキーマ
    # 【期待される動作】: 空でも TC-N17 と同一トップキー集合・ranked==[]・n_hypotheses==0・JSON 化可能
    # 🔵 信頼性レベル: EDGE-001 + note §6 (候補ゼロ経路との整合) に直接依拠

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)

    # 【実際の処理実行】: 上流候補が全滅しても API 応答契約 (キー集合) を破らない
    result = HypothesisTreeSearch(backend).search(GRID, y, [])

    # 【結果検証】: 空でも各後処理フィールドが空値で成立し、summary が空スキーマになる
    assert result.good_cluster_ids == ()  # 【確認内容】: 良好解は空 🔵
    assert dict(result.final_reports) == {}  # 【確認内容】: フル精密化記録は空 Mapping 🔵
    assert result.unmatched.unmatched_observed == ()  # 【確認内容】: 未マッチ観測は空 🔵
    summary = result.to_summary()
    assert _SUMMARY_TOP_KEYS <= set(summary)  # 【確認内容】: 空でも同一トップキー集合 (スタブで失敗) 🔵
    assert summary["ranked"] == []  # 【確認内容】: ranked は空 list 🔵
    assert summary["n_hypotheses"] == 0  # 【確認内容】: 仮説総数 0 🔵
    json.dumps(summary)  # 【確認内容】: 空スキーマでも JSON 化可能 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース (TC-B07〜B11)
# ---------------------------------------------------------------------------


def test_single_hypothesis_falls_back_to_good_cluster():
    # 【テスト目的】: refined 仮説 1 件で Jenks 境界不能でも単一仮説が良好解になる (TC-B07)
    # 【テスト内容】: A 単相・候補 [A] で jenks_breaks 縮退時のフォールバックを検証
    # 【期待される動作】: good_cluster_ids==(ranked[0].id,)、final_reports にその 1 件、例外なし
    # 🟡 信頼性レベル: 縮退条件は clustering.py 契約 🔵、フォールバック規則は §3.6 実装時確定 🟡

    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A])

    # 【結果検証】: 単一仮説はそのまま良好解になり、フル精密化にも 1 件記録される
    only_id = result.ranked[0].hypothesis.id
    assert result.good_cluster_ids == (only_id,)  # 【確認内容】: 単一仮説がそのまま良好解 (スタブ () で失敗) 🟡
    assert len(result.final_reports) == 1  # 【確認内容】: フル精密化が 1 件記録される 🟡
    assert only_id in result.final_reports  # 【確認内容】: 記録キーが当該仮説 ID 🟡
    assert "unknown_phase_flag" in result.to_summary()  # 【確認内容】: to_summary が成立 🟡


def test_all_equal_evidence_makes_every_hypothesis_good():
    # 【テスト目的】: 全 refined 仮説の evidence が同値のとき全仮説が良好解になる (TC-B08)
    # 【テスト内容】: FakeBackend で全組合せ同一 (rwp=100=基準, chi2=10) を返し展開を止め同値化する
    # 【期待される動作】: good_cluster_ids が全仮説 ID、並びは ID 昇順で決定論的、例外なし
    # 🟡 信頼性レベル: 要件定義 §3.6 の推奨フォールバック (実装時確定事項) に基づく

    # 【テストデータ準備】: rwp=基準 100 で改善 0 → 展開されず {A}/{B} の 2 単相のみ (同一 BIC) になる
    fake = FakeBackend(default_rwp=100.0, default_chi2=10.0)
    y = fake.simulate([PHASE_A, PHASE_B], GRID)
    result = HypothesisTreeSearch(fake, config=SearchConfig(final_full_refine=False)).search(
        GRID, y, [PHASE_A, PHASE_B]
    )

    # 【結果検証】: 区別できない (evidence 同値) 場合は落とさず全て良好解に残す安全側縮退
    all_ids = set(result.hypotheses)
    assert set(result.good_cluster_ids) == all_ids  # 【確認内容】: 全仮説が良好解 (スタブ () で失敗) 🟡
    assert len(result.good_cluster_ids) == len(all_ids)  # 【確認内容】: 重複なく全件 🟡
    assert list(result.good_cluster_ids) == sorted(result.good_cluster_ids)  # 【確認内容】: ID 昇順で決定論 🟡


def test_high_r_threshold_uses_strict_greater_comparison():
    # 【テスト目的】: Rwp==high_r_threshold では高 R フラグが立たない (厳密比較 >) (TC-B09)
    # 【テスト内容】: 完全説明データ + FakeBackend の rwp を閾値ちょうど/超で振って境界の両側を検証
    # 【期待される動作】: rwp==30 → フラグ False、rwp==30.1 → フラグ True
    # 🟡 信頼性レベル: 条件式 (>) は §3.6 🔵、等値ケースの挙動指定はそこからの論理的導出 🟡

    # 【完全説明構成】: {A,B} の chi2 を最小化し最良仮説が観測を全説明 (未マッチ由来のフラグを排除)
    chi2_map = {frozenset({"A", "B"}): 5.0}
    cfg = SearchConfig(final_full_refine=False)

    def run(default_rwp: float) -> SearchResult:
        fake = FakeBackend(default_rwp=default_rwp, chi2_by_refs=chi2_map, default_chi2=100.0)
        y = fake.simulate([PHASE_A, PHASE_B], GRID)
        return HypothesisTreeSearch(fake, config=cfg).search(GRID, y, [PHASE_A, PHASE_B])

    res_eq = run(30.0)  # 閾値ちょうど
    res_gt = run(30.1)  # 閾値超

    # 【結果検証】: 閾値ちょうどは「高 R でない」側へ、閾値超で初めてフラグが立つ
    assert res_eq.unmatched.unknown_phase_flag is False  # 【確認内容】: rwp==threshold は False (>) 🟡
    assert res_gt.unmatched.unknown_phase_flag is True  # 【確認内容】: rwp>threshold で True (スタブで失敗) 🟡


def test_max_final_refine_clips_to_top_good_cluster():
    # 【テスト目的】: フル精密化対象が「良好解上位 min(max_final_refine, 良好解数) 件」になる (TC-B10)
    # 【テスト内容】: (a) 上限 1 で 1 件のみ (最良)、(b) 良好解 1 件で上限 3 でも 1 件 を検証
    # 【期待される動作】: (a) len==1 かつキーは evidence 最小 (最良) の ID、(b) len==1 (上限未達)
    # 🟡 信頼性レベル: 設計 D3「上位 max_final_refine 件」からの境界導出

    # (a) 上限クリップ: max_final_refine=1 で良好解のうち最良 1 件のみ精密化
    res_a = _run_ab_search(SearchConfig(max_final_refine=1))
    assert len(res_a.final_reports) == 1  # 【確認内容】: 上位 1 件へクリップ (スタブ 0 件で失敗) 🟡
    assert set(res_a.final_reports) == {res_a.ranked[0].hypothesis.id}  # 【確認内容】: 最良を選出 🟡
    assert res_a.ranked[0].hypothesis.id in res_a.good_cluster_ids  # 【確認内容】: 選出は良好解内 🟡

    # (b) 上限未達: 良好解 1 件 (単一候補) では上限 3 でも 1 件 (= 良好解数)
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)
    res_b = HypothesisTreeSearch(backend, config=SearchConfig(max_final_refine=3)).search(
        GRID, y, [PHASE_A]
    )
    assert len(res_b.final_reports) == 1  # 【確認内容】: 良好解数 (1) で頭打ち 🟡


def test_deterministic_bit_identical_including_postprocess():
    # 【テスト目的】: 再ランク・後処理を含めて 2 回実行で to_summary() までビット同一 (TC-B11)
    # 【テスト内容】: 同一入力で独立 2 回探索し good_cluster/final_reports/ranked/summary の一致を検証
    # 【期待される動作】: 4 系列すべてが == でビット同一 (pytest.approx を使わない)
    # 🔵 信頼性レベル: NFR-102 / REQ-403 / 要件定義 §3.1 に直接依拠

    r1 = _run_ab_search()
    r2 = _run_ab_search()

    # 【非空ガード】: 空同士の自明一致でなく後処理が実体化していることを担保 (スタブで失敗)
    assert r1.good_cluster_ids  # 【確認内容】: 良好解が非空 (実体化の担保) 🔵
    assert r1.final_reports  # 【確認内容】: フル精密化記録が非空 🔵
    assert "unknown_phase_flag" in r1.to_summary()  # 【確認内容】: summary スキーマが成立 🔵

    # 【結果検証】: 後処理フィールドまで含めて 2 回実行がビット同一 (再現性)
    assert r1.good_cluster_ids == r2.good_cluster_ids  # 【確認内容】: 良好解がビット同一 🔵
    assert tuple(r1.final_reports.keys()) == tuple(r2.final_reports.keys())  # 精密化キーが同順 🔵
    order1 = [(rk.hypothesis.id, rk.probability, rk.evidence.value) for rk in r1.ranked]
    order2 = [(rk.hypothesis.id, rk.probability, rk.evidence.value) for rk in r2.ranked]
    assert order1 == order2  # 【確認内容】: ランキング列がビット同一 🔵
    assert r1.to_summary() == r2.to_summary()  # 【確認内容】: summary が dict 完全一致 🔵
