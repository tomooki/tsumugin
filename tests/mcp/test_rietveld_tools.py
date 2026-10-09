"""② `auto_rietveld` のバックエンド専用引数 (M12 W2)。

`seed_profile` は **TOPAS 経路だけ**の概念 (GSAS-II は装置ファイルの U,V,W をそのまま
読む)。③ は JSON しか送れないので、engine まで届くことと、誤用が黙って無視されずに
error dict になることの両方を固定する。
"""

from __future__ import annotations

import pytest

from tsumugin.refine_loop.action import AnalysisInput
from tsumugin.mcp.rietveld_tools import auto_rietveld




# ---------------- TOPAS のプロファイル種付け (#179) ----------------


def test_seed_profile_reaches_the_topas_engine_from_json():
    """③ は JSON しか送れない — `seed_profile` が engine まで届くこと。"""
    from tsumugin.refine_loop.orchestrator import _default_gsas_runner

    seen: dict[str, object] = {}

    def fake_engine(histograms, phases, **kw):
        seen.update(kw)
        raise RuntimeError("stop after capturing kwargs")

    import tsumugin.autorietveld.backends as backends_mod

    original = backends_mod.resolve_backend
    backends_mod.resolve_backend = lambda name: fake_engine  # type: ignore[assignment]
    try:
        runner = _default_gsas_runner(0, backend="topas", seed_profile=True)
        with pytest.raises(RuntimeError):
            runner(
                AnalysisInput(
                    histograms=(), phases=(), background_coeffs=6, extra_stages=()
                )
            )
    finally:
        backends_mod.resolve_backend = original  # type: ignore[assignment]
    assert seen.get("seed_profile") is True


def test_seed_profile_with_gsas_is_an_error_not_a_silent_ignore():
    """GSAS 経路は装置ファイルの U,V,W をそのまま読むので種付けの概念が無い。

    黙って無視すると「頼んだのに効いていない」が結果に現れない。
    """
    out = auto_rietveld([], [], seed_profile=True)
    assert "error" in out and "seed_profile" in out["error"]


def test_cell_strain_reaches_layer_two_output():
    """③ は結果 dict しか見ない — ε がそこに無ければ「無い」のと同じ。"""
    from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport
    from tsumugin.mcp.rietveld_tools import _result_to_dict

    result = AutoRietveldResult(
        stage_results=(), final_rwp=7.19, final_gof=1.44,
        refined_cells={"PbSO4": (8.48, 5.40, 6.96, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True, checks=(), warnings=()),
        cell_strain={"PbSO4": {"a_h1": 0.0031}},
    )
    payload = _result_to_dict(
        result, AnalysisInput(histograms=(), phases=(), background_coeffs=6, extra_stages=())
    )
    assert payload["cell_strain"] == {"PbSO4": {"a_h1": 0.0031}}


def test_seed_profile_with_search_is_refused_not_silently_dropped():
    """探索経路は候補ごとに runner を組むので種付けを運べない。

    単独経路では同じ引数が ValueError になるのに、探索経路だけ**沈黙して種付けなしで
    走る**のは最悪の非対称 (結果からは区別できない)。
    """
    out = auto_rietveld([], [], seed_profile=True, search=["polish"])
    assert "error" in out and out["error_type"] == "UnsupportedBackendCombination"
    assert "seed_profile" in out["error"]


def test_stage_revert_reason_and_noop_reach_layer_two_output():
    """fit-then-judge P1a タスク 1: 段の revert 理由と no-op は ③ が読める形で出す。

    note の文言に頼らせない (文言は変わってよい) — 理由は語彙の決まった独立キーにする。
    """
    from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
    from tsumugin.mcp.rietveld_tools import _result_to_dict

    result = AutoRietveldResult(
        stage_results=(
            StageResult("scale", 30.0, 3.0, 2, True),
            StageResult("cell", 30.0, 3.0, 2, False, reverted=True, revert_reason="gate:cell"),
            StageResult("profile", 30.0, 3.0, 2, True, is_noop=True),
        ),
        final_rwp=30.0, final_gof=3.0, refined_cells={},
        validity=ValidityReport(passed=True, checks=(), warnings=()),
    )
    payload = _result_to_dict(
        result, AnalysisInput(histograms=(), phases=(), background_coeffs=6, extra_stages=())
    )
    stages = payload["stages"]
    assert [s["revert_reason"] for s in stages] == [None, "gate:cell", None]
    assert [s["noop"] for s in stages] == [False, False, True]


def test_uiso_equiv_groups_reach_engine_from_layer_two_json():
    """fit-then-judge P1a タスク 2: ③ は JSON しか送れない — phases の dict で届くこと。"""
    from tsumugin.mcp.rietveld_tools import _build_input

    inp = _build_input(
        [], [{"structure_path": "x.cif", "phase_name": "x", "uiso_equiv_groups": [["O1", "O2"]]}],
        6, None,
    )
    assert inp.phases[0].uiso_equiv_groups == (("O1", "O2"),)


# ---------------- engine のドメインエラーを ② の境界で縮退する (fit-then-judge P1a) ----------------


def _raising_runner(exc):
    def run(inp):
        raise exc

    return run


@pytest.mark.parametrize("tool", ["auto_rietveld", "refine_with_revisions"])
def test_engine_domain_error_is_degraded_not_raised(tool):
    """`run(inp)` から出る Tsumugin のドメインエラー (相仕様の誤り・エンジン未導入等) は
    error dict にする。③ は LLM なので例外は回復不能なハード失敗になる (CLAUDE.md 不変条件)。

    P1a で engine に足した入力仕様の検査 (`uiso_equiv_groups` の未知ラベル・極性原点の
    site symmetry) は精密化の前に送出されるので、ここで縮退しないと境界を越える。
    """
    from tsumugin.errors import InvalidPhaseSpecError
    from tsumugin.mcp import rietveld_tools

    fn = getattr(rietveld_tools, tool)
    args = ([], []) if tool == "auto_rietveld" else ([], [], [])  # refine_with_revisions は actions 必須
    out = fn(*args, runner=_raising_runner(InvalidPhaseSpecError("相 x に原子 Ox がありません")))
    assert out == {"error": "相 x に原子 Ox がありません", "error_type": "InvalidPhaseSpecError"}


def test_logic_bugs_are_not_swallowed_at_the_boundary():
    """ドメインエラー以外 (論理バグ) は握り潰さない — 縮退対象を広げすぎない対照。"""
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    with pytest.raises(ZeroDivisionError):
        auto_rietveld([], [], runner=_raising_runner(ZeroDivisionError("bug")))


def test_phase_integrated_intensity_reaches_layer_two_output():
    """fit-then-judge P1a タスク 5: 相ごとの積分計算強度を ③ が読めること (欠測は null)。"""
    from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport
    from tsumugin.mcp.rietveld_tools import _result_to_dict

    result = AutoRietveldResult(
        stage_results=(), final_rwp=10.0, final_gof=1.0, refined_cells={},
        validity=ValidityReport(passed=True, checks=(), warnings=()),
        phase_integrated_intensity={"A": (7.0, None), "B": (3.0, float("nan"))},
    )
    payload = _result_to_dict(
        result, AnalysisInput(histograms=(), phases=(), background_coeffs=6, extra_stages=())
    )
    assert payload["phase_integrated_intensity"] == {"A": [7.0, None], "B": [3.0, None]}


def test_coordinate_freedom_mismatches_reach_layer_two_output():
    """fit-then-judge P1a タスク 6: 座標の自由度の食い違いを ③ が読めること。"""
    from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport
    from tsumugin.mcp.rietveld_tools import _result_to_dict

    result = AutoRietveldResult(
        stage_results=(), final_rwp=10.0, final_gof=1.0, refined_cells={},
        validity=ValidityReport(passed=True, checks=(), warnings=()),
        coordinate_freedom_mismatches={"p": (("O1", "??", "1"),)},
    )
    payload = _result_to_dict(
        result, AnalysisInput(histograms=(), phases=(), background_coeffs=6, extra_stages=())
    )
    assert payload["coordinate_freedom_mismatches"] == {"p": [["O1", "??", "1"]]}


def test_correlation_group_violation_is_degraded_at_the_boundary():
    """③ が相関群を割る段を `stages` で渡すと engine が `CorrelationGroupViolation` を送出する。
    これは入力の誤りなので ② の境界で error dict にする (以前は ValueError だけを継いでいて
    ドメインエラーとして扱われず、境界を越えていた)。"""
    from tsumugin.autorietveld.recipe import CorrelationGroupViolation
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    out = auto_rietveld([], [], runner=_raising_runner(CorrelationGroupViolation("群を分割")))
    assert out == {"error": "群を分割", "error_type": "CorrelationGroupViolation"}
