"""レシピ探索 (Phase 2, REQ-SAR-500/501/502) の決定論テスト。

GSAS を一切使わない — `run_recipe_search` の runner を注入して候補ごとの結果を差し替える
(既存 `insitu` と同じ流儀)。**選択規則そのもの**を実データ無しで固定するのが目的。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.search import (
    CANDIDATE_NAMES,
    CandidateOutcome,
    RecipeCandidate,
    SearchConfig,
    build_candidates,
    candidate_bic,
    convergence_verdict,
    rank_outcomes,
    run_recipe_search,
    summarize_search,
)

# ---------------------------------------------------------------------------
# 素材
# ---------------------------------------------------------------------------

_H = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
    data_format="GSAS",
)
_P = PhaseSpec(structure_path="a.cif", phase_name="ph")


def _stage(label: str, *, rwp: float, n_params: int, converged: bool, reverted: bool = False,
           note: str = "") -> StageResult:
    return StageResult(label=label, rwp=rwp, gof=1.0, n_params=n_params,
                       converged=converged, reverted=reverted, note=note)


def _result(
    rwp: float,
    *,
    gof: float = 1.5,
    n_params: int = 30,
    converged: bool = True,
    valid: bool = True,
    n_obs: int = 4000,
    cells: dict[str, tuple[float, float, float, float, float, float]] | None = None,
    fractions: dict[str, float] | None = None,
    note: str = "",
) -> AutoRietveldResult:
    """最終段が受理された (reverted=False) 1 段の結果。"""
    return AutoRietveldResult(
        stage_results=(
            _stage("S0 scale", rwp=rwp * 2, n_params=5, converged=True),
            _stage("S1 cell", rwp=rwp, n_params=n_params, converged=converged, note=note),
        ),
        final_rwp=rwp,
        final_gof=gof,
        refined_cells=cells or {"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=valid),
        n_obs=n_obs,
        phase_fractions=fractions or {},
    )


def _candidate(name: str, origin: str = "fixed") -> RecipeCandidate:
    return RecipeCandidate(
        name=name,
        stages=(RefinementStage(label="S0 scale", flags={"scale": True}),),
        origin=origin,
        histograms=(_H,),
        background_coeffs=6,
    )


def _outcomes(*specs: tuple[str, AutoRietveldResult | None]) -> tuple[CandidateOutcome, ...]:
    return tuple(
        CandidateOutcome(index=i, candidate=_candidate(name), result=res)
        for i, (name, res) in enumerate(specs)
    )


# ---------------------------------------------------------------------------
# S1: 収束フィルタ → 妥当性降格 → 最良 → 同点は BIC
# ---------------------------------------------------------------------------


def test_best_rwp_wins_when_both_converged_and_valid():
    # 【目的】: 素直な場合は Rwp 最小が選ばれる (探索の一次規則)。
    outcomes = _outcomes(("default", _result(9.81)), ("serious", _result(10.45)))

    res = summarize_search(outcomes, SearchConfig())

    assert res.selected.candidate.name == "default"


def test_unconverged_candidate_loses_to_converged_one_even_with_better_rwp():
    # 【目的】: **収束していない best は最良ではない** (S1 の核心)。Rwp だけで選ぶと
    #   max shft/sig=258 を出した段の上に積んだ解が勝ってしまう。
    outcomes = _outcomes(
        ("default", _result(6.02, converged=False)),
        ("serious", _result(6.66, converged=True)),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.selected.candidate.name == "serious"
    assert res.convergence_fallback is False


def test_all_unconverged_falls_back_instead_of_selecting_nothing():
    # 【目的】: **収束フィルタを素朴に適用すると全候補が落ちる** (WS-1 実測: T1 の "成功して
    #   いる" 段も shift/esd 基準では未収束)。全滅時はフィルタを無効化し、警告を添えて
    #   最良を返す — 「答えが無い」より「信頼度の低い答え + 警告」の方が有用。
    outcomes = _outcomes(
        ("default", _result(9.81, converged=False)),
        ("serious", _result(10.45, converged=False)),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.selected.candidate.name == "default"
    assert res.convergence_fallback is True
    assert any("収束" in w for w in res.warnings)


def test_validity_failure_demotes_but_does_not_exclude():
    # 【目的】: 妥当性 fail は**降格**であって除外ではない (所見付きで残る)。
    outcomes = _outcomes(
        ("default", _result(9.0, valid=False)),
        ("serious", _result(12.0, valid=True)),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.selected.candidate.name == "serious"          # 降格した
    assert [o.candidate.name for o in res.ranked] == ["serious", "default"]
    assert res.outcomes[0].result is not None                # 除外はされていない


def test_validity_failure_of_all_candidates_still_selects_best():
    # 【目的】: CaTeO3 は既定/本気とも validity=fail (実測)。降格しかしないので選択は続く。
    outcomes = _outcomes(
        ("default", _result(12.20, valid=False)),
        ("serious", _result(12.19, valid=False)),
    )

    res = summarize_search(outcomes, SearchConfig(rwp_tie_eps=0.0))

    assert res.selected.candidate.name == "serious"
    assert any("妥当性" in w for w in res.warnings)


def test_near_tie_is_arbitrated_by_bic_not_by_rwp():
    # 【目的】: 候補間で母数が違うと Rwp 比較は不公平。0.1 ポイント以内は BIC で裁定する。
    #   ここでは Rwp が僅かに悪い方が母数が遥かに少なく BIC で勝つ。
    outcomes = _outcomes(
        ("default", _result(9.80, gof=1.5, n_params=200)),
        ("serious", _result(9.85, gof=1.5, n_params=30)),
    )

    res = summarize_search(outcomes, SearchConfig(rwp_tie_eps=0.1))

    assert res.selected.candidate.name == "serious"
    assert "bic" in res.selection_reason


def test_outside_the_tie_window_rwp_wins_even_if_bic_prefers_the_other():
    # 【目的】: BIC 裁定は**同点近傍だけ**。窓の外まで BIC で選ぶと「Rwp が明確に良い解」を
    #   母数の少なさだけで捨てることになる。
    outcomes = _outcomes(
        ("default", _result(6.02, gof=1.0, n_params=200)),
        ("serious", _result(6.66, gof=1.0, n_params=30)),
    )

    res = summarize_search(outcomes, SearchConfig(rwp_tie_eps=0.1))

    assert res.selected.candidate.name == "default"


def test_candidate_bic_matches_the_frame_bic_formula():
    # 【目的】: 相数抑制で使っている `insitu.anchor.select.frame_bic` と**同一式**であること。
    #   別式が 2 つあると「BIC で裁定した」という主張の意味が場所ごとに変わる。
    from tsumugin.insitu.anchor.model import AnchorConfig
    from tsumugin.insitu.anchor.select import frame_bic
    from tsumugin.insitu.model import FrameRietveldResult

    result = _result(9.0, gof=1.73, n_params=42, n_obs=5000)
    frame = FrameRietveldResult(
        frame_index=0, axis_value=None, data_path="d", rwp=9.0, gof=1.73,
        refined_cells={}, phase_fractions={}, phase_names=("ph",), n_obs=5000,
    )
    cfg = AnchorConfig(base_params=42, per_phase_params=0)

    assert candidate_bic(result) == pytest.approx(frame_bic(frame, cfg))


def test_failed_candidate_never_wins_and_is_reported():
    # 【目的】: 実行失敗 (例外/inf) は最下位に落ちるが、**候補としては残す** (何を試したかは
    #   結果の一部)。
    outcomes = (
        CandidateOutcome(index=0, candidate=_candidate("default"), result=None,
                         error="RuntimeError('boom')"),
        CandidateOutcome(index=1, candidate=_candidate("serious"), result=_result(12.0)),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.selected.candidate.name == "serious"
    assert any("boom" in w for w in res.warnings)
    assert len(res.outcomes) == 2


def test_all_candidates_failed_yields_no_selection_instead_of_a_fabricated_best():
    # 【目的】: 全滅を「最良」と答えない (② が空/不正入力を正常と答えない規律と同じ)。
    outcomes = (
        CandidateOutcome(index=0, candidate=_candidate("default"), error="boom"),
        CandidateOutcome(index=1, candidate=_candidate("serious"), error="boom"),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.selected is None
    assert res.best is None
    assert res.selected_index == -1


def test_convergence_verdict_uses_the_last_accepted_stage_not_the_last_stage():
    # 【目的】: revert された段は**巻き戻されている**ので、その未収束は最終状態の性質ではない。
    #   最終状態を作ったのは「最後に受理された段」である。
    result = AutoRietveldResult(
        stage_results=(
            _stage("S0", rwp=20.0, n_params=5, converged=True),
            _stage("S1", rwp=9.0, n_params=30, converged=True),
            _stage("S2", rwp=8.9, n_params=40, converged=False, reverted=True),
        ),
        final_rwp=9.0, final_gof=1.5, refined_cells={}, validity=ValidityReport(passed=True),
    )

    verdict, reason = convergence_verdict(result)

    assert verdict is True
    assert "S1" in reason


def test_convergence_verdict_reads_the_stability_gate_note():
    # 【目的】: `stability.require_convergence` を有効にすると engine が段の note へ
    #   ``unconverged`` を書く。GSAS 自身の converged フラグより厳しい判定なので拾う。
    result = _result(9.0, converged=True, note="unconverged")

    verdict, _ = convergence_verdict(result)

    assert verdict is False


def test_convergence_verdict_is_none_when_no_stage_was_accepted():
    # 【目的】: 判定材料が無いときに「収束した」と答えない (fail open で通すが理由は残す)。
    result = AutoRietveldResult(
        stage_results=(_stage("S0", rwp=20.0, n_params=5, converged=False, reverted=True),),
        final_rwp=float("inf"), final_gof=float("inf"), refined_cells={},
        validity=ValidityReport(passed=False),
    )

    verdict, reason = convergence_verdict(result)

    assert verdict is None
    assert reason


# ---------------------------------------------------------------------------
# S3: 不一致は警告 (REQ-SAR-501)
# ---------------------------------------------------------------------------


def test_close_rwp_with_different_lattice_raises_an_order_dependence_warning():
    # 【目的】: Rwp が僅差なのに格子が有意に違う = **順序依存**。答えより「答えの信頼度」を
    #   言えることが探索の最大の利得 (S3)。
    outcomes = _outcomes(
        ("default", _result(9.80, cells={"ph": (10.000, 10.0, 10.0, 90.0, 90.0, 90.0)})),
        ("serious", _result(9.90, cells={"ph": (10.100, 10.0, 10.0, 90.0, 90.0, 90.0)})),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert any("順序依存" in w for w in res.warnings)
    assert res.order_dependent is True


def test_close_rwp_with_matching_lattice_does_not_warn():
    # 【目的】: 偽陽性を作らない — 同じ答えに収束しているなら信頼度は高い。
    outcomes = _outcomes(("default", _result(9.80)), ("serious", _result(9.90)))

    res = summarize_search(outcomes, SearchConfig())

    assert res.order_dependent is False
    assert not any("順序依存" in w for w in res.warnings)


def test_far_apart_rwp_does_not_warn_even_with_different_lattice():
    # 【目的】: Rwp が明確に違うなら「どちらが良いか」はデータが答えている (順序依存ではない)。
    outcomes = _outcomes(
        ("default", _result(6.02, cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)})),
        ("serious", _result(12.0, cells={"ph": (10.5, 10.0, 10.0, 90.0, 90.0, 90.0)})),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.order_dependent is False


def test_close_rwp_with_different_phase_fractions_warns():
    # 【目的】: 多相では相分率の割れも順序依存の兆候 (格子は一致していても起こる)。
    outcomes = _outcomes(
        ("default", _result(9.80, fractions={"a": 0.70, "b": 0.30})),
        ("serious", _result(9.85, fractions={"a": 0.55, "b": 0.45})),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.order_dependent is True
    assert any("相分率" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# S5: 決定論
# ---------------------------------------------------------------------------


def test_exact_tie_is_broken_by_enumeration_order_not_by_completion_order():
    # 【目的】: 並列実行しても選択が完走順で変わらない (P-SAR-4)。
    outcomes = _outcomes(("default", _result(9.0)), ("serious", _result(9.0)))

    forward = summarize_search(outcomes, SearchConfig())
    backward = summarize_search(tuple(reversed(outcomes)), SearchConfig())

    assert forward.selected.candidate.name == "default"
    assert backward.selected.candidate.name == "default"  # index が同点解決の鍵


def test_repeated_summaries_are_bit_identical():
    outcomes = _outcomes(("default", _result(9.81)), ("serious", _result(10.45)))

    a = summarize_search(outcomes, SearchConfig()).to_dict()
    b = summarize_search(outcomes, SearchConfig()).to_dict()

    assert a == b


def test_candidate_names_are_an_explicit_tuple_not_a_sorted_set():
    # 【目的】: 列挙順が実装都合 (辞書順/集合順) で変わらないこと (S5)。
    assert CANDIDATE_NAMES == ("default", "serious", "adaptive")


# ---------------------------------------------------------------------------
# 候補生成 (S2: 固定 + 適応の 2 層)
# ---------------------------------------------------------------------------


def test_build_candidates_puts_the_fixed_layer_first():
    cands = build_candidates([_H], [_P], names=("default", "serious"))

    assert [c.name for c in cands] == ["default", "serious"]
    assert all(c.origin == "fixed" for c in cands)
    assert len(cands[0].stages) < len(cands[1].stages)  # 本気フィットは段数が多い


def test_build_candidates_rejects_unknown_names_loudly():
    # 【目的】: 綴り間違いを黙って無視すると「探索したつもり」で 1 候補しか回らない。
    with pytest.raises(ValueError, match="未知"):
        build_candidates([_H], [_P], names=("defualt",))


def test_adaptive_candidate_is_skipped_when_the_pattern_cannot_be_read():
    # 【目的】: 適応層が使えないデータでも**固定層が保険**として残ること (S2 の要点)。
    cands = build_candidates([_H], [_P], names=CANDIDATE_NAMES)

    assert [c.name for c in cands] == ["default", "serious"]  # adaptive は落ちる


def test_adaptive_candidate_does_not_overwrite_explicit_two_theta_limits(tmp_path):
    # 【目的】: 明示指定は人間の判断 (T4 のレンジ制限は非収束の主因を潰した実測値)。
    #   自動判定で黙って上書きしない (提案≠適用, P-SAR-3)。
    data = tmp_path / "p.xy"
    xs = [10.0 + 0.02 * i for i in range(2000)]
    ys = [100.0 + (900.0 if 500 <= i <= 510 else 0.0) for i in range(2000)]
    data.write_text("\n".join(f"{x} {y}" for x, y in zip(xs, ys)), encoding="utf-8")
    hist = HistogramSpec(
        data_path=str(data), instrument_path="i.prm", radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO, data_format="XY", two_theta_limits=(12.0, 40.0),
    )

    cands = build_candidates([hist], [_P], names=CANDIDATE_NAMES)
    adaptive = [c for c in cands if c.name == "adaptive"]

    if adaptive:  # 背景項数だけ変えた適応候補が立つことはある
        assert adaptive[0].histograms[0].two_theta_limits == (12.0, 40.0)


# ---------------------------------------------------------------------------
# run_recipe_search (runner 注入)
# ---------------------------------------------------------------------------


def test_run_recipe_search_runs_each_candidate_once_in_enumeration_order():
    seen: list[str] = []

    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        seen.append(candidate.name)
        return _result(10.0 if candidate.name == "serious" else 9.0)

    res = run_recipe_search([_H], [_P], runner=runner, names=("default", "serious"))

    assert seen == ["default", "serious"]
    assert res.selected.candidate.name == "default"


def test_run_recipe_search_converts_a_candidate_failure_into_a_result_not_an_exception():
    # 【不変条件】: バックエンドの失敗は例外でなく結果へ縮退させ、ガードレールに処理させる。
    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        if candidate.name == "default":
            raise RuntimeError("boom")
        return _result(12.0)

    res = run_recipe_search([_H], [_P], runner=runner, names=("default", "serious"))

    assert res.selected.candidate.name == "serious"
    assert res.outcomes[0].error


def test_run_recipe_search_records_every_candidate_in_the_ledger():
    from tsumugin.store import Ledger

    ledger = Ledger()
    run_recipe_search([_H], [_P], runner=lambda c: _result(9.0), ledger=ledger,
                      names=("default", "serious"))

    kinds = [e.kind for e in ledger.entries]
    assert kinds.count("m7_search_candidate") == 2
    assert kinds.count("m7_search_select") == 1
    assert ledger.verify()


def test_reported_tier_uses_the_same_rule_that_ranked_the_candidates():
    # 【目的】: **報告される tier は順位付けに使われた tier と一致すること** (レビュー MEDIUM-3)。
    #   `require_convergence` は ② の `search_config` から設定できる公開ノブなので、
    #   `to_dict` が True を決め打ちすると `false` を渡した呼び手には
    #   「未収束∧妥当」と報告されながら順位は「収束∧妥当」で付いた表が返る。
    #   ③ は「なぜその候補が勝ったか」を tier_label で読むので、これは誤った説明になる。
    outcomes = _outcomes(
        ("default", _result(6.02, converged=False)),
        ("serious", _result(6.66, converged=True)),
    )

    lenient = summarize_search(outcomes, SearchConfig(require_convergence=False))
    strict = summarize_search(outcomes, SearchConfig(require_convergence=True))

    # 前提: このノブは実際に選択を変える (変えないなら以下の照合は空虚に真になる)
    assert lenient.selected.candidate.name == "default"
    assert strict.selected.candidate.name == "serious"

    lenient_rows = lenient.to_dict()["candidates"]
    strict_rows = strict.to_dict()["candidates"]
    # 未収束候補の tier が規則ごとに変わる = 報告が config を見ている
    assert lenient_rows[0]["tier_label"] == "収束∧妥当"
    assert strict_rows[0]["tier_label"] == "未収束∧妥当"
    # そして tier 順は必ず順位表 (ranking) と整合する — 上位ほど tier が小さい
    for res, rows in ((lenient, lenient_rows), (strict, strict_rows)):
        tiers = [rows[i]["tier"] for i in res.ranking]
        assert tiers == sorted(tiers), f"報告 tier が順位と食い違う: {tiers}"
    # 収束判定そのもの (converged) は規則に依らず報告される (tier は降格規則・converged は事実)
    assert lenient_rows[0]["converged"] is False and strict_rows[0]["converged"] is False


def test_ledger_candidate_rows_use_the_configured_tier_rule():
    # 【目的】: ledger `m7_search_candidate` も同じ規則で書かれること (ledger と応答の食い違い禁止)。
    from tsumugin.store import Ledger

    ledger = Ledger()
    run_recipe_search(
        [_H], [_P],
        runner=lambda c: _result(9.0, converged=False),
        ledger=ledger,
        names=("default",),
        config=SearchConfig(require_convergence=False),
    )

    rows = [e.payload for e in ledger.entries if e.kind == "m7_search_candidate"]
    assert [r["tier_label"] for r in rows] == ["収束∧妥当"]


def test_result_dict_is_json_safe():
    import json

    outcomes = _outcomes(("default", _result(float("inf"), gof=float("inf"))),
                         ("serious", _result(9.0)))

    payload = summarize_search(outcomes, SearchConfig()).to_dict()

    json.dumps(payload, allow_nan=False)  # 非有限は None 化されていること


def test_rank_outcomes_is_a_total_ordering_over_all_candidates():
    # 【目的】: 落ちた候補も順位表に残る (何を試したかは結果の一部)。
    outcomes = (
        CandidateOutcome(index=0, candidate=_candidate("default"), error="boom"),
        CandidateOutcome(index=1, candidate=_candidate("serious"), result=_result(12.0)),
        CandidateOutcome(index=2, candidate=_candidate("adaptive"),
                         result=_result(11.0, converged=False)),
    )

    ranking, fallback = rank_outcomes(outcomes, SearchConfig())

    assert ranking == (1, 2, 0)
    assert fallback is False
    assert math.isinf(candidate_bic(outcomes[0].result)) if outcomes[0].result else True


# ---------------------------------------------------------------------------
# S6: operando (`tsumugin.insitu`) は探索しない (REQ-SAR-502)
# ---------------------------------------------------------------------------


def test_insitu_does_not_reference_the_recipe_search():
    # 【目的】: operando はフレーム数 × 候補数の積が現実的でないので**探索しない**。
    #   「時間予算があるのは operando だけ」という前提を、参照の不在で構造的に守る。
    #   ⚠ 変異実証: insitu の任意モジュールへ `from ..autorietveld.search import
    #   run_recipe_search` を 1 行足すと本テストが fail することを確認済み。
    import pathlib

    import tsumugin.insitu as insitu_pkg

    root = pathlib.Path(insitu_pkg.__file__).parent
    offenders = [
        str(p.relative_to(root))
        for p in sorted(root.rglob("*.py"))
        if any(
            token in p.read_text(encoding="utf-8")
            for token in ("autorietveld.search", "run_recipe_search", "RecipeSearchResult")
        )
    ]

    assert offenders == [], (
        f"operando 経路が探索を参照しています: {offenders}。"
        "REQ-SAR-502: insitu は軽量レシピ 1 本を既定に維持すること"
    )


def test_sequential_rietveld_runs_one_refinement_per_frame():
    # 【目的】: 参照の不在だけでなく**呼び出し回数**でも縛る (探索が入れば候補数倍になる)。
    from tsumugin.insitu.engine import run_sequential_rietveld
    from tsumugin.insitu.model import FrameSpec

    calls: list[int] = []

    def runner(frame, phases, initial_cells):
        calls.append(frame.frame_index if hasattr(frame, "frame_index") else len(calls))
        return AutoRietveldResult(
            stage_results=(), final_rwp=9.0, final_gof=1.0,
            refined_cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
            validity=ValidityReport(passed=True), phase_fractions={"ph": 1.0},
        )

    frames = [FrameSpec(data_path=f"f{i}.xrdml", axis_value=300.0 + i) for i in range(3)]
    run_sequential_rietveld(frames, [_P], runner=runner)

    assert len(calls) == 3


def test_a_candidate_that_dropped_data_cannot_win_on_bic():
    # 【目的】: **実測で発覚した構造的バイアス** (T1)。適応候補がレンジを切ると n_obs が
    #   5752→5535 に減り χ²=GOF²·(n_obs−n_params) が縮んで BIC が必ず下がる = 「データを
    #   捨てた候補が勝つ」。観測集合が違う候補は Rwp/BIC では上に来られないこと。
    outcomes = _outcomes(
        ("default", _result(9.8062, gof=1.7532, n_params=35, n_obs=5752)),
        ("adaptive", _result(9.8247, gof=1.7312, n_params=35, n_obs=5535)),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert candidate_bic(outcomes[1].result) < candidate_bic(outcomes[0].result)  # BIC は逆
    assert res.selected.candidate.name == "default"                               # それでも既知最良


def test_a_candidate_that_dropped_data_still_wins_when_it_is_the_only_converged_one():
    # 【目的】: レンジを切る動機 (T4 の非収束はレンジ未設定が主因) は殺さない。
    #   切った候補は「収束する」ことで勝つべきで、「点数が減った」ことで勝つべきではない。
    outcomes = _outcomes(
        ("default", _result(12.8, n_obs=5752, converged=False)),
        ("adaptive", _result(13.5, n_obs=3000, converged=True)),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert res.selected.candidate.name == "adaptive"


def test_different_observation_counts_are_flagged_because_rwp_is_not_comparable():
    # 【目的】: 適応層はデータレンジを変えうる = **観測集合が違う**。同じ観測集合の上でしか
    #   Rwp/BIC は比較できないので、黙って順位を出さず事実を添える (③ の受理基準と同じ規律)。
    outcomes = _outcomes(
        ("default", _result(9.80, n_obs=4000)),
        ("adaptive", _result(9.90, n_obs=3200)),
    )

    res = summarize_search(outcomes, SearchConfig())

    assert any("観測点数" in w for w in res.warnings)


def test_same_observation_count_does_not_flag():
    outcomes = _outcomes(("default", _result(9.80)), ("serious", _result(9.90)))

    res = summarize_search(outcomes, SearchConfig())

    assert not any("観測点数" in w for w in res.warnings)


def test_selection_reason_names_the_key_that_actually_decided():
    # 【目的】: 「Rwp が良かった」で一括りにすると、③ は「収束で勝った」「観測集合が違うので
    #   比較していない」を Rwp の勝利と誤読する。次点と**最初に食い違ったキー**を返すこと。
    by_tier = _outcomes(("default", _result(6.02, converged=False)),
                        ("serious", _result(6.66, converged=True)))
    by_obs = _outcomes(("default", _result(9.90, n_obs=5752)),
                       ("adaptive", _result(9.80, n_obs=5535)))
    by_rwp = _outcomes(("default", _result(9.80)), ("serious", _result(10.45)))
    by_bic = _outcomes(("default", _result(9.80, n_params=200)),
                       ("serious", _result(9.85, n_params=30)))

    assert summarize_search(by_tier, SearchConfig()).selection_reason == "tier"
    assert summarize_search(by_obs, SearchConfig()).selection_reason == "observation_set"
    assert summarize_search(by_rwp, SearchConfig()).selection_reason == "rwp"
    assert summarize_search(by_bic, SearchConfig()).selection_reason == "bic"
