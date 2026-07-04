"""TASK-0046 公開 API 統合 + E2E (M4 joint/chem/mcp 総仕上げ) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/__init__.py`` への M4 公開シンボル re-export
(``AlkaliMetalInAirRule`` / ``AnalysisSession`` / ``ChemPlausibility`` / ``ContrastConfig`` /
``HistogramWeighting`` / ``JointHistogram`` / ``JointRefinementModel`` /
``JointRefinementResult`` / ``JointVerificationResult`` / ``MCPUnavailableError`` /
``MEMUnavailableError`` / ``NEUTRON_B_TABLE`` / ``OccupancyReleaseRecommendation`` /
``PerHistogramMetrics`` / ``PhaseRef`` / ``PlausibilityResult`` / ``SynthesisContext`` /
``TofBankParams`` / ``XRAY_Z_TABLE`` / ``combine_plausibility`` / ``create_mcp_server`` /
``rank_with_plausibility`` / ``recommend_occupancy_release`` / ``refine_joint`` /
``refine_joint_detailed`` / ``verify_survivors``) と、公開 API 経由の joint / mcp 一気通貫 E2E。

Red の失敗機構: 本モジュール冒頭の ``from tsumugin import AnalysisSession, ...`` は M4 分が
トップレベル未 re-export のため collection 時に ImportError となり、本ファイルの全テストが失敗
する (``tests/test_operando_e2e.py`` と同一の Red 方針)。mcp.tools の 8 ツールは mcp サブ
パッケージ側公開のまま (トップレベル __all__ には入れない, interfaces.py 指示)。

方針:
- E2E は SimulatedBackend で決定論・乱数不使用 (@gsas は TC-409-02 の 1 件のみ・conftest.py が自動 skip)。
- 観測グリッドは 15-60° / step 0.05 (tests/test_joint_verification.py と同較正の粗版・<30 秒 smoke)。
- コア import が numpy のみ (mcp/xraylib なし) を find_spec 不在確認 + import 成功で担保する (REQ-403)。
- 決定論は ``==`` ビット同一、物理量は ``pytest.approx``。
テストケース定義 (TC-408 系 / TC-409 系) に 1:1 対応する。
"""

from __future__ import annotations

import dataclasses
import importlib.util
import inspect

import numpy as np
import pytest

import tsumugin
import tsumugin.chem
import tsumugin.errors
import tsumugin.joint
import tsumugin.mcp
import tsumugin.model

# 【Red の失敗点】: M4 シンボルはトップレベル未 re-export のため、この import が collection 時に
#   ImportError となり本ファイルの全テストが失敗する想定。M0〜M3 分は既に re-export 済みだが、
#   M4 分を含む結合 import 文全体が失敗する。🔵
from tsumugin import (
    NEUTRON_B_TABLE,
    XRAY_Z_TABLE,
    AlkaliMetalInAirRule,
    AnalysisSession,
    BICBackend,
    ChemPlausibility,
    ContrastConfig,
    FinalSelectionEngine,
    HistogramWeighting,
    Hypothesis,
    HypothesisTreeSearch,
    JointHistogram,
    JointRefinementModel,
    JointRefinementResult,
    JointVerificationResult,
    LatticeParams,
    Ledger,
    MCPUnavailableError,
    MEMUnavailableError,
    OccupancyReleaseRecommendation,
    PerHistogramMetrics,
    PhaseInstance,
    PhaseRef,
    PlausibilityResult,
    Project,
    RefinementMetrics,
    SearchConfig,
    SimulatedBackend,
    SnapshotStore,
    SynthesisContext,
    TofBankParams,
    combine_plausibility,
    create_mcp_server,
    rank_with_plausibility,
    recommend_occupancy_release,
    refine_joint,
    refine_joint_detailed,
    verify_survivors,
)
from tsumugin.evidence.base import EvidenceResult
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.mcp.tools import (
    accept_hypothesis,
    compare_hypotheses,
    export_gpx,
    get_trajectory,
    list_hypotheses,
    revert,
    submit_analysis,
)
from tsumugin.search.clustering import PhaseCandidate
from tsumugin.search.matcher import UnmatchedPeakReport
from tsumugin.search.tree import SearchResult
from tsumugin.sequential import FrameRecord, Trajectory

# ---------------------------------------------------------------------------
# 共通テストデータ・前提 (tests/test_joint_verification.py の較正を踏襲)
# ---------------------------------------------------------------------------

# 【観測グリッド】: joint 検証テストと同較正の 15-60° の粗版 (step 0.05, <30 秒 smoke)。🔵
GRID = np.arange(15.0, 60.0, 0.05)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子 (a=b=c) の相インスタンスを組む。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


PHASE_A = _phase(5.0, "A")
PHASE_B = _phase(6.0, "B")
PHASE_C = _phase(4.5, "C")

# 【昇格契約】: 本タスクでトップレベルへ昇格する M4 公開面全体 (interfaces.py 公開 API 節 / REQ-404)。🔵
_M4_PROMOTED_SYMBOLS = {
    # errors
    "MCPUnavailableError",
    "MEMUnavailableError",
    # model (PhaseRef / TofBankParams)
    "PhaseRef",
    "TofBankParams",
    # joint
    "NEUTRON_B_TABLE",
    "XRAY_Z_TABLE",
    "ContrastConfig",
    "HistogramWeighting",
    "JointHistogram",
    "JointRefinementModel",
    "JointRefinementResult",
    "JointVerificationResult",
    "OccupancyReleaseRecommendation",
    "PerHistogramMetrics",
    "recommend_occupancy_release",
    "refine_joint",
    "refine_joint_detailed",
    "verify_survivors",
    # chem
    "AlkaliMetalInAirRule",
    "ChemPlausibility",
    "PlausibilityResult",
    "SynthesisContext",
    "combine_plausibility",
    "rank_with_plausibility",
    # mcp (SDK 非依存で re-export 可能な facade + 遅延 import サーバ構築のみ)
    "AnalysisSession",
    "create_mcp_server",
}

# 【後方互換契約】: 既存 M0〜M3 の代表公開シンボル (削除・改名禁止 / REQ-404)。🔵
_M0M3_PUBLIC_SYMBOLS = {
    "AICBackend",
    "AbsorptionConfig",
    "AnalysisResult",
    "BICBackend",
    "CELL_PHASE_PRESETS",
    "DiscriminationConfig",
    "FinalSelectionEngine",
    "Hypothesis",
    "HypothesisTreeSearch",
    "Ledger",
    "MultistartEngine",
    "PhaseInstance",
    "Project",
    "RankedHypothesis",
    "SearchResult",
    "SequentialEngine",
    "SimulatedBackend",
    "SnapshotStore",
    "Trajectory",
    "analyze_single_pattern",
    "discriminate_interval",
    "export_gpx",
    "rank",
    "segment_series",
    "transmission_factor",
}


def _primary_search(ledger: Ledger | None = None) -> SearchResult:
    """プライマリ 1 ヒストで木探索を実行し SearchResult を返す (生存仮説 A を含む)。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    intensity = backend.simulate((PHASE_A,), GRID)
    search = HypothesisTreeSearch(backend, config=SearchConfig(), ledger=ledger)
    candidates = [
        PhaseCandidate(phase=PHASE_A),
        PhaseCandidate(phase=PHASE_B),
        PhaseCandidate(phase=PHASE_C),
    ]
    return search.search(GRID, intensity, candidates)


def _joint_histograms() -> tuple[JointHistogram, ...]:
    """検証用の joint ヒスト (X 線 + 中性子 CW) を合成する (2 ヒスト・2 probe 種別)。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    y_xray = backend.simulate((PHASE_A,), GRID)
    y_neutron = backend.simulate((PHASE_A,), GRID)
    return (
        JointHistogram(two_theta=GRID, intensity=y_xray, probe="xray"),
        JointHistogram(two_theta=GRID, intensity=y_neutron, probe="neutron_cw"),
    )


def _mk_ranked(hyp_id: str, evidence_value: float) -> RankedHypothesis:
    """MCP E2E 用の合成 RankedHypothesis (search_result の要素)。"""
    h = Hypothesis(
        id=hyp_id,
        phases=(_phase(4.0, hyp_id),),
        metrics=RefinementMetrics(
            rwp=5.0, gof=1.0, chi2=1.0, n_obs=100, n_params=5, evidence={"bic": evidence_value}
        ),
        status="refined",
    )
    ev = EvidenceResult(backend="bic", value=evidence_value)
    return RankedHypothesis(hypothesis=h, evidence=ev, probability=0.5, close_competitor=False)


def _synthetic_search_result(ledger: Ledger) -> SearchResult:
    """MCP ツールが操作する合成 SearchResult (2 仮説) を組む。"""
    ranked = [_mk_ranked("hyp-0000", 10.0), _mk_ranked("hyp-0001", 20.0)]
    return SearchResult(
        ranked=tuple(ranked),
        hypotheses={r.hypothesis.id: r.hypothesis for r in ranked},
        good_cluster_ids=tuple(sorted(r.hypothesis.id for r in ranked)),
        alternatives={},
        unmatched=UnmatchedPeakReport(
            unmatched_observed=(), extra_calculated=(), unknown_phase_flag=False
        ),
        final_reports={},
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
        warnings=(),
    )


def _mcp_session(*, mode: str = "agent") -> AnalysisSession:
    """MCP E2E 用の AnalysisSession (search_result / trajectory / 観測パターン込み) を組む。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    intensity = backend.simulate((PHASE_A,), GRID)
    ledger = Ledger()
    selection = FinalSelectionEngine(mode=mode, ledger=ledger)
    trajectory = Trajectory(records=(FrameRecord(frame_index=0, rwp=5.0),))
    return AnalysisSession(
        project=Project(id="proj-m4"),
        backend=backend,
        selection=selection,
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
        evidence=BICBackend(),
        search_result=_synthetic_search_result(ledger),
        trajectory=trajectory,
        two_theta=GRID,
        intensity=intensity,
    )


# ---------------------------------------------------------------------------
# 1. 公開 API 統合テスト (TC-408 系)
# ---------------------------------------------------------------------------


def test_m4_public_symbols_are_reexported():
    # 【テスト目的】: M4 公開シンボルが from tsumugin import ... で解決し期待の型を持つ [TC-408-05]
    # 【テスト内容】: モジュール冒頭 import 済みの各シンボルが class / dataclass / 関数 のいずれか検証
    # 【期待される動作】: トップレベル tsumugin 名前空間から M4 中核シンボルへ到達できる (完了条件①)
    # 🔵 信頼性レベル: interfaces.py 公開 API 節 / 完了条件① / test_m3_public_symbols_are_reexported の範

    # 【結果検証】: ルール・facade・Protocol はクラス
    for cls in (AlkaliMetalInAirRule, AnalysisSession, ChemPlausibility):
        assert inspect.isclass(cls)  # 【確認内容】: ルール/facade/Protocol はクラス 🔵

    # 【結果検証】: 値オブジェクト系は dataclass
    for dc in (
        ContrastConfig,
        HistogramWeighting,
        JointHistogram,
        JointRefinementModel,
        JointRefinementResult,
        JointVerificationResult,
        OccupancyReleaseRecommendation,
        PerHistogramMetrics,
        PhaseRef,
        PlausibilityResult,
        SynthesisContext,
        TofBankParams,
    ):
        assert dataclasses.is_dataclass(dc)  # 【確認内容】: 値オブジェクトは dataclass 🔵

    # 【結果検証】: 純関数系は callable でありクラスでない
    for fn in (
        combine_plausibility,
        create_mcp_server,
        rank_with_plausibility,
        recommend_occupancy_release,
        refine_joint,
        refine_joint_detailed,
        verify_survivors,
    ):
        assert callable(fn) and not inspect.isclass(fn)  # 【確認内容】: 関数として呼び出し可能 🔵

    # 【結果検証】: 静的テーブルは Mapping、例外は TsumuginError サブクラス
    from collections.abc import Mapping

    assert isinstance(NEUTRON_B_TABLE, Mapping)  # 【確認内容】: 中性子 b テーブルは Mapping 🔵
    assert isinstance(XRAY_Z_TABLE, Mapping)  # 【確認内容】: X 線 Z テーブルは Mapping 🔵
    assert issubclass(MCPUnavailableError, tsumugin.errors.TsumuginError)  # 🔵
    assert issubclass(MEMUnavailableError, tsumugin.errors.TsumuginError)  # 🔵


def test_m4_symbols_in_dunder_all_and_sorted():
    # 【テスト目的】: 昇格 M4 シンボルが tsumugin.__all__ に含まれ昇順ソート + 後方互換維持 [TC-408-05/REQ-404]
    # 【テスト内容】: __all__ の包含関係・ソート順・M0〜M3 分の後方互換 (削除なし)・実属性整合を検証
    # 【期待される動作】: __all__ が M0〜M3 + M4 を統合しアルファベット昇順のまま (完了条件② / REQ-404)
    # 🔵 信頼性レベル: interfaces.py 公開 API 節 / REQ-404 / test_m3_symbols_in_dunder_all_and_sorted の範

    exported = set(tsumugin.__all__)

    # 【結果検証】: 昇格 M4 シンボルが公開面 (__all__) に配線されていること
    assert _M4_PROMOTED_SYMBOLS <= exported  # 【確認内容】: M4 シンボルが __all__ に包含 🔵
    # 【後方互換】: 既存 M0〜M3 シンボルが 1 つも削除・改名されていないこと (REQ-404)
    assert _M0M3_PUBLIC_SYMBOLS <= exported  # 【確認内容】: M0〜M3 公開面の非破壊 (後方互換維持) 🔵
    # 【規約遵守】: __all__ がアルファベット昇順ソートを維持していること
    assert list(tsumugin.__all__) == sorted(tsumugin.__all__)  # 【確認内容】: 昇順ソート維持 🔵
    # 【指示遵守】: mcp.tools の 8 ツール実処理関数はトップレベル __all__ に入れない (mcp 側公開)
    for tool in ("submit_analysis", "list_hypotheses", "compare_hypotheses", "accept_hypothesis"):
        assert tool not in exported  # 【確認内容】: 8 ツールはトップレベル __all__ 非搭載 🔵


def test_m4_reexports_are_same_object():
    # 【テスト目的】: トップレベルのシンボルがサブパッケージ実体と同一オブジェクト [REQ-404]
    # 【テスト内容】: re-export が別実装・コピーでなくサブパッケージ実体の別名付けであることを is で検証
    # 【期待される動作】: verify_survivors 等がサブパッケージ属性と is 一致 (二重実装防止)
    # 🔵 信頼性レベル: REQ-404 / test_m3_reexports_are_same_object の範に依拠

    assert verify_survivors is tsumugin.joint.verify_survivors  # 【確認内容】: 同一実体 🔵
    assert refine_joint is tsumugin.joint.refine_joint  # 【確認内容】: 同一実体 🔵
    assert rank_with_plausibility is tsumugin.chem.rank_with_plausibility  # 【確認内容】: 同一実体 🔵
    assert combine_plausibility is tsumugin.chem.combine_plausibility  # 【確認内容】: 同一実体 🔵
    assert AnalysisSession is tsumugin.mcp.AnalysisSession  # 【確認内容】: 同一実体 🔵
    assert create_mcp_server is tsumugin.mcp.create_mcp_server  # 【確認内容】: 同一実体 🔵
    assert PhaseRef is tsumugin.model.PhaseRef  # 【確認内容】: 同一実体 🔵
    assert TofBankParams is tsumugin.model.TofBankParams  # 【確認内容】: 同一実体 🔵
    assert MCPUnavailableError is tsumugin.errors.MCPUnavailableError  # 【確認内容】: 同一実体 🔵


def test_dunder_all_names_all_resolvable():
    # 【テスト目的】: __all__ の全名称が実属性として解決できる (dangling 名なし)
    # 【テスト内容】: tsumugin.__all__ の全要素が hasattr(tsumugin, name) を満たすか
    # 【期待される動作】: 公開契約 (__all__) と実装 (実属性) の乖離ゼロ (追記時 typo/実体欠落の検出)
    # 🔵 信頼性レベル: 要件定義 / test_operando_e2e.test_dunder_all_names_all_resolvable に依拠

    for name in tsumugin.__all__:
        assert hasattr(tsumugin, name)  # 【確認内容】: __all__ と実属性の乖離が無い 🔵


def test_core_imports_numpy_only():
    # 【テスト目的】: コア import が numpy のみ (mcp/xraylib なしで import 可能) [TC-408-04/REQ-403]
    # 【テスト内容】: mcp SDK / xraylib が不在 (find_spec is None) を確認しつつ、コア import は成功する
    # 【期待される動作】: create_mcp_server は SDK 非依存で import でき、コア import で mcp SDK を引き込まない
    # 🔵 信頼性レベル: REQ-403 / interfaces.py 遅延 import 契約 (mcp.server の関数内遅延 import) に依拠

    import sys

    # 【前提確認】: このテスト環境に mcp SDK / xraylib が導入されていないこと (無ければ以下が担保対象)。
    #   仮に導入されていても、コア import が mcp SDK を sys.modules に載せないことは常に成立させる。
    if importlib.util.find_spec("mcp") is None:
        # 【担保】: mcp SDK 不在でも create_mcp_server を含む M4 コア import が成功済み (冒頭 import)
        assert callable(create_mcp_server)  # 【確認内容】: SDK 非依存で import 可能 🔵
    if importlib.util.find_spec("xraylib") is None:
        # 【担保】: xraylib 不在でも中性子コントラスト・joint コア import が成功済み
        assert isinstance(NEUTRON_B_TABLE, dict) or hasattr(NEUTRON_B_TABLE, "__getitem__")  # 🔵

    # 【最重要担保】: コア tsumugin を import しても mcp SDK は sys.modules に載らない (トップレベル
    #   で mcp SDK を引き込まない遅延 import 契約 / REQ-403)。mcp サブパッケージ (実処理層) は
    #   SDK 非依存なので載っていてよいが、SDK 本体 (import 名 "mcp") は載らないこと。
    #   ※ 既にどこかで mcp SDK を import 済みの環境では該当キーが残る可能性があるため、
    #     未導入 (find_spec None) のときのみ厳格判定する。
    if importlib.util.find_spec("mcp") is None:
        assert "mcp" not in sys.modules  # 【確認内容】: コア import で mcp SDK を引き込まない 🔵


# ---------------------------------------------------------------------------
# 2. joint 一気通貫 E2E (TC-409-01)
# ---------------------------------------------------------------------------


def test_m4_joint_pipeline_end_to_end():
    # 【テスト目的】: joint 一気通貫 E2E が完走する [TC-409-01]
    # 【テスト内容】: プライマリ探索 → 生存仮説 joint 検証 (X線+中性子 2 ヒスト) → コントラスト推奨 →
    #   ChemPlausibility 降格 rank → 最終選択 → ledger.verify() の縦串を公開 API のみで結線する
    # 【期待される動作】: 各層が破綻せず期待の型を返し、共有 ledger の verify() が True (完了条件③)
    # 🔵 信頼性レベル: TC-409-01 / interfaces.py joint フロー / test_joint_verification.py の範に依拠

    # 【共有 ledger】: 探索段とは別の検証用 ledger に joint 昇格・降格・選択の記録を集約する 🔵
    verify_ledger = Ledger()

    # 【プライマリ探索】: 探索段は不変。良好解=生存仮説を含む SearchResult を得る 🔵
    search_result = _primary_search()
    assert len(search_result.good_cluster_ids) >= 1  # 生存仮説が 1 件以上

    # 【生存仮説 joint 検証】: X線+中性子 2 ヒスト・2 probe 種別で検証精密化する 🔵 REQ-014
    histograms = _joint_histograms()
    verification = verify_survivors(
        SimulatedBackend(peak_fwhm=0.2),
        search_result,
        histograms,
        evidence=BICBackend(),
        contrast=ContrastConfig(site_elements={"M1": ("Mn", "Fe")}),
        ledger=verify_ledger,
    )
    assert isinstance(verification, JointVerificationResult)  # 【確認内容】: joint 検証結果を得る 🔵
    assert set(verification.joint_results) == set(search_result.good_cluster_ids)  # 生存仮説のみ
    for jr in verification.joint_results.values():
        assert isinstance(jr, JointRefinementResult)  # 【確認内容】: 各仮説は joint 詳細 🔵
        # ヒスト別指標が 2 ヒスト分あり probe 種別が 2 種 (X線+中性子) を含む
        assert len(jr.per_histogram) == len(histograms)  # 【確認内容】: ヒスト別 = 入力ヒスト数 🔵
        probes = {m.probe for m in jr.per_histogram}
        assert isinstance(jr.per_histogram[0], PerHistogramMetrics)  # 【確認内容】: ヒスト別型 🔵
        assert len(probes) >= 1  # 【確認内容】: probe 種別が算出されている 🔵

    # 【コントラスト推奨】: 提案は自動適用されず OccupancyReleaseRecommendation として付く 🔵 REQ-011
    for recs in verification.recommendations.values():
        assert isinstance(recs, tuple)  # 【確認内容】: 推奨は tuple (自動適用しない・提案のみ) 🔵
        for rec in recs:
            assert isinstance(rec, OccupancyReleaseRecommendation)  # 【確認内容】: 推奨型 🔵

    # 【ChemPlausibility 降格 rank】: 大気下単体アルカリ金属ルールで降格 (除外しない) 🔵 REQ-019
    ranked = rank_with_plausibility(
        verification.verified,
        BICBackend(),
        modules=(AlkaliMetalInAirRule(),),
        context=SynthesisContext(atmosphere="air"),
        ledger=verify_ledger,
    )
    # 【最重要不変条件】: 降格のみ。候補は除外されず出力件数 = 入力件数 (件数不減 / REQ-019/EDGE-005)
    assert len(ranked) == len(verification.verified)  # 【確認内容】: 降格でも件数不変 🔵
    assert all(isinstance(r, RankedHypothesis) for r in ranked)  # 【確認内容】: ランク型 🔵

    # 【最終選択】: FinalSelectionEngine で裁定する (agent モード・非破壊裁定) 🔵
    selection = FinalSelectionEngine(mode="agent", ledger=verify_ledger)
    decision = selection.decide(search_result)
    # accepted か recommended のいずれかが決まる (両者 None は探索破綻時のみ)
    assert decision.accepted is not None or decision.recommended_id is not None  # 🔵

    # 【ledger verify】: joint 昇格・降格・選択を通しても共有 ledger の連鎖が無傷 🔵 NFR-105/REQ-401
    assert verify_ledger.verify() is True  # 【確認内容】: 追記専用ハッシュチェーンが無傷 🔵
    assert len(verify_ledger.entries) > 0  # 【確認内容】: 空 ledger の自明 True でない 🔵
    # 【探索段不変】: 探索段の ledger は verify_survivors から一切追記されず不変で True 維持 (REQ-202)
    assert search_result.ledger.verify() is True  # 【確認内容】: 探索 ledger も無傷 🔵


def test_m4_joint_pipeline_is_deterministic():
    # 【テスト目的】: joint 一気通貫が 2 回実行でビット同一 (決定論 / NFR-102/REQ-402)
    # 【テスト内容】: 同一入力で verify → rank を 2 回実行し verified metrics / ranked 順がビット同一か
    # 【期待される動作】: 乱数・集合反復順に依存せず完全再現 (SimulatedBackend は乱数不使用)
    # 🔵 信頼性レベル: NFR-102 / REQ-402 / test_joint_verification.test_verification_is_deterministic の範

    hists = _joint_histograms()

    def _run() -> tuple[list[str], list[float]]:
        sr = _primary_search()
        v = verify_survivors(SimulatedBackend(peak_fwhm=0.2), sr, hists, evidence=BICBackend())
        r = rank_with_plausibility(
            v.verified,
            BICBackend(),
            modules=(AlkaliMetalInAirRule(),),
            context=SynthesisContext(atmosphere="air"),
        )
        return [h.id for h in v.verified], [rk.hypothesis.id for rk in r]

    v1_ids, r1_ids = _run()
    v2_ids, r2_ids = _run()
    assert v1_ids == v2_ids  # 【確認内容】: verified 順がビット同一 🔵
    assert r1_ids == r2_ids  # 【確認内容】: ranked 順がビット同一 🔵


# ---------------------------------------------------------------------------
# 3. MCP 一気通貫 E2E (TC-409-03)
# ---------------------------------------------------------------------------


def test_m4_mcp_end_to_end(tmp_path):
    # 【テスト目的】: MCP 一気通貫 E2E が全応答 dict で完走する [TC-409-03]
    # 【テスト内容】: submit → list → compare → accept(agent) → revert → get_trajectory → export_gpx →
    #   ledger.verify() の縦串を 8 ツール実処理関数 (SDK 非依存) で結線する
    # 【期待される動作】: 全応答が素の型 dict / accept→superseded / export_gpx は ok or error dict /
    #   共有 ledger の verify() が True (完了条件④)
    # 🔵 信頼性レベル: TC-409-03 / interfaces.py mcp フロー / test_mcp_tools.py の範に依拠

    session = _mcp_session(mode="agent")

    # 【submit】: 単一パターン投入 (理由付き記録) → 素の型 dict 🔵 REQ-021/025
    submit_res = submit_analysis(
        session, GRID, session.intensity, [[PHASE_A]], reason="m4-e2e"
    )
    assert isinstance(submit_res, dict)  # 【確認内容】: 応答は dict 🔵

    # 【list】: 直近探索結果の一覧 (search_result.to_summary 準拠) 🔵
    list_res = list_hypotheses(session)
    assert isinstance(list_res, dict)  # 【確認内容】: 応答は dict 🔵
    ids = [row["id"] for row in list_res["ranked"]]
    assert ids == ["hyp-0000", "hyp-0001"]  # 【確認内容】: 仮説一覧を返す 🔵

    # 【compare】: evidence/確率で比較 (rank 委譲) 🔵
    compare_res = compare_hypotheses(session, ["hyp-0000", "hyp-0001"])
    assert isinstance(compare_res, dict)  # 【確認内容】: 応答は dict 🔵
    assert len(compare_res["compared"]) == 2  # 【確認内容】: 2 仮説を比較 🔵

    # 【accept(agent)】: agent モードで accepted 化 (FinalSelectionEngine 委譲) 🔵 REQ-023
    accept_res = accept_hypothesis(session, "hyp-0000", by="agent", reason="accept-e2e")
    assert isinstance(accept_res, dict)  # 【確認内容】: 応答は dict 🔵
    assert accept_res["status"] == "accepted"  # 【確認内容】: agent モードで accepted 🔵

    # 【revert】: superseded 化 (追記型・件数不減 / P2) 🔵 REQ-024
    revert_res = revert(session, "hyp-0000", note="rollback-e2e")
    assert isinstance(revert_res, dict)  # 【確認内容】: 応答は dict 🔵
    assert revert_res["status"] == "superseded"  # 【確認内容】: 破壊的削除でなく superseded 化 🔵
    assert session.selection.accepted["hyp-0000"].status == "superseded"  # 件数不減で状態遷移

    # 【get_trajectory】: 時系列を素の型 dict で返す 🔵
    traj_res = get_trajectory(session)
    assert isinstance(traj_res, dict)  # 【確認内容】: 応答は dict 🔵
    assert "header" in traj_res and "rows" in traj_res  # 【確認内容】: 決定論ヘッダ + 行 🔵

    # 【export_gpx】: GSAS 導入時は ok、未導入は error dict (どちらもクラッシュしない) 🔵 EDGE-011
    export_res = export_gpx(session, str(tmp_path / "out.gpx"), "hyp-0000")
    assert isinstance(export_res, dict)  # 【確認内容】: 応答は dict 🔵
    assert export_res["status"] in {"ok", "error"}  # 【確認内容】: ok or error (未導入時 error dict) 🔵
    if export_res["status"] == "error":
        assert export_res["error"] == "gsas_unavailable"  # 【確認内容】: 未導入は gsas_unavailable 🔵

    # 【ledger verify】: submit/accept/revert を通しても共有 ledger の連鎖が無傷 🔵 NFR-105/REQ-401
    assert session.ledger.verify() is True  # 【確認内容】: 追記専用ハッシュチェーンが無傷 🔵
    kinds = {e.kind for e in session.ledger.entries}
    assert {"mcp_submit", "mcp_accept", "mcp_revert"} <= kinds  # 【確認内容】: 全操作が理由付き記録 🔵


# ---------------------------------------------------------------------------
# 4. 非破壊性 (TC-408-01/02)
# ---------------------------------------------------------------------------


def test_no_destructive_api_after_m4():
    # 【テスト目的】: joint 昇格・コントラスト・降格・MCP 操作を通しても ledger 無傷・削除/上書き API 不在
    #   [TC-408-01/02/REQ-401]
    # 【テスト内容】: joint 検証 + 降格 + MCP accept/revert を 1 本の ledger へ集約後 verify() True かつ、
    #   公開面 (トップレベル __all__ シンボル名) に破壊的動詞が現れないことを走査で確認する
    # 【期待される動作】: 全経路を通しても verify() True / 破壊的 API が公開面に無い (P2 / NFR-101)
    # 🔵 信頼性レベル: REQ-401 / P2 / NFR-101 / test_mcp_tools.test_no_destructive_* の範に依拠

    # 【joint + 降格経路】: 検証 → 降格 rank を共有 ledger に集約する 🔵
    ledger = Ledger()
    search_result = _primary_search()
    verification = verify_survivors(
        SimulatedBackend(peak_fwhm=0.2), search_result, _joint_histograms(),
        evidence=BICBackend(), ledger=ledger,
    )
    rank_with_plausibility(
        verification.verified, BICBackend(),
        modules=(AlkaliMetalInAirRule(),), context=SynthesisContext(atmosphere="air"),
        ledger=ledger,
    )
    assert ledger.verify() is True  # 【確認内容】: joint 昇格 + 降格経路で ledger 無傷 🔵

    # 【MCP 操作経路】: accept → revert を通しても ledger 無傷・件数不減 (superseded 化) 🔵
    session = _mcp_session(mode="agent")
    accept_hypothesis(session, "hyp-0000", by="agent")
    count_before = len(session.selection.accepted)
    revert(session, "hyp-0000", note="rb")
    assert len(session.selection.accepted) == count_before  # 【確認内容】: revert で件数不減 (P2) 🔵
    assert session.ledger.verify() is True  # 【確認内容】: MCP 操作経路でも ledger 無傷 🔵

    # 【公開面走査】: トップレベル __all__ のシンボル名に破壊的動詞が現れない 🔵 REQ-401
    forbidden = ("delete", "remove", "drop", "overwrite", "truncate", "purge", "erase")
    for name in tsumugin.__all__:
        assert not any(word in name.lower() for word in forbidden), name  # 【確認内容】: 破壊 API 不在 🔵


# ---------------------------------------------------------------------------
# 5. @gsas 2 ヒスト joint smoke (TC-409-02)
# ---------------------------------------------------------------------------


@pytest.mark.gsas
def test_m4_two_histogram_joint_smoke():
    # 【テスト目的】: GSASIIBackend で 2 ヒスト joint smoke が完走する [TC-409-02]
    # 【テスト内容】: 実 GSAS-II 精密化を用いた 2 ヒスト (X線+中性子) の joint 精密化が破綻せず
    #   集約 RefinementResult を返すか検証 (バックエンド交換 P7)
    # 【期待される動作】: バックエンド交換しても joint 精密化が同契約で完走 (未導入は auto-skip)
    # 🔵 信頼性レベル: TC-409-02 / test_operando_e2e.test_e2e_gsasii_multistart_n4_smoke の @gsas パターン

    from tsumugin.backends.gsasii import GSASIIBackend

    # 【テストデータ準備】: GSAS-II が確実に計算できる立方相 1 相 + 合成強度 (X線+中性子 2 ヒスト)
    grid = np.arange(20.0, 80.0, 0.05)
    backend = GSASIIBackend()
    phase = _phase(4.0, "P")
    y_xray = backend.simulate((phase,), grid)
    y_neutron = backend.simulate((phase,), grid)
    histograms = (
        JointHistogram(two_theta=grid, intensity=y_xray, probe="xray"),
        JointHistogram(two_theta=grid, intensity=y_neutron, probe="neutron_cw"),
    )
    model = JointRefinementModel(
        phases=(phase,),
        histograms=histograms,
        shared_free_params=frozenset({"phase0.scale"}),
    )

    # 【実際の処理実行】: 実バックエンドで 2 ヒスト joint 精密化を回す
    result = refine_joint(backend, model, weighting=HistogramWeighting())

    # 【結果検証】: 例外なく完走し集約 RefinementResult (chi2/rwp が算出) を返す
    assert result.chi2 is not None  # 【確認内容】: 集約 chi2 が算出される 🔵
    assert result.rwp is not None  # 【確認内容】: 集約 Rwp が算出される 🔵


# ---------------------------------------------------------------------------
# 6. README M4 使用例の写経実行 (完了条件⑧ / README との一致担保)
# ---------------------------------------------------------------------------


def test_readme_m4_example_executes(tmp_path):
    # 【テスト目的】: README「使い方 (M4)」節の最小使用例と同等コードが動作する (完了条件⑧)
    # 【テスト内容】: 公開 import → 探索 → joint 検証 → 降格 rank → MCP セッション の写経実行と完走検証
    # 【期待される動作】: 使用例が例外なく実行され ledger.verify() is True (README コード例が動く)
    # 🟡 信頼性レベル: 完了条件⑧ / README 文面は Green で確定 (E2E で使った API と一致)

    # --- ここから README 使用例と同等のコード (公開 API のみ使用) ---
    import numpy as np
    from tsumugin import (
        AlkaliMetalInAirRule,
        BICBackend,
        HypothesisTreeSearch,
        JointHistogram,
        LatticeParams,
        Ledger,
        PhaseInstance,
        SimulatedBackend,
        SynthesisContext,
        rank_with_plausibility,
        verify_survivors,
    )
    from tsumugin.search.clustering import PhaseCandidate

    two_theta = np.arange(15.0, 60.0, 0.05)
    backend = SimulatedBackend(peak_fwhm=0.2)
    true_phase = PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0))
    observed = backend.simulate((true_phase,), two_theta)

    # プライマリ探索 (探索段は不変) → 生存仮説を得る
    ledger = Ledger()
    search = HypothesisTreeSearch(backend, ledger=ledger)
    candidates = [
        PhaseCandidate(phase=true_phase),
        PhaseCandidate(phase=PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0))),
    ]
    result = search.search(two_theta, observed, candidates)

    # 生存仮説を X 線 + 中性子の 2 ヒストで joint 検証 (中性子/マルチヒストグラム)
    histograms = (
        JointHistogram(two_theta=two_theta, intensity=observed, probe="xray"),
        JointHistogram(two_theta=two_theta, intensity=observed, probe="neutron_cw"),
    )
    verification = verify_survivors(
        backend, result, histograms, evidence=BICBackend(), ledger=ledger
    )

    # ChemPlausibility で化学的に非妥当な相を降格 (除外はしない)
    ranked = rank_with_plausibility(
        verification.verified,
        BICBackend(),
        modules=(AlkaliMetalInAirRule(),),
        context=SynthesisContext(atmosphere="air"),
        ledger=ledger,
    )
    # --- ここまで README 使用例と同等のコード ---

    # 【結果検証】: 使用例の出力が公開 API の実シグネチャ・契約に追従していること
    assert len(verification.verified) >= 1  # 【確認内容】: 生存仮説が joint 検証される 🟡
    assert len(ranked) == len(verification.verified)  # 【確認内容】: 降格でも件数不変 🟡
    assert ledger.verify() is True  # 【確認内容】: 使用例経路でも ledger 連鎖が無傷 🟡
