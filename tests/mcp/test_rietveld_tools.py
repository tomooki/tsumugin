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


# ---------------- 相 spec の null / 型取り違え ----------------

_HIST = {
    "data_path": "d.xye",
    "instrument_path": "i.instprm",
    "radiation": "xray_lab",
    "geometry": "bragg_brentano",
}


def _capturing_runner(seen: list):
    from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport

    def run(inp):
        seen.append(inp)
        return AutoRietveldResult(
            stage_results=(), final_rwp=10.0, final_gof=1.0, refined_cells={},
            validity=ValidityReport(passed=True, checks=(), warnings=()),
        )

    return run


def _call(tool: str, phases, seen: list) -> dict:
    from tsumugin.mcp.rietveld_tools import refine_with_revisions

    runner = _capturing_runner(seen)
    if tool == "auto_rietveld":
        return auto_rietveld([_HIST], phases, runner=runner)
    return refine_with_revisions([_HIST], phases, [], runner=runner)


@pytest.mark.parametrize("tool", ["auto_rietveld", "refine_with_revisions"])
def test_refine_cell_null_reaches_the_engine_as_refined(tool):
    """③ が「未指定」の null を送っても、相の格子が黙って凍結されないこと。

    旧実装は ``bool(None) == False`` で engine に ``refine_cell=False`` を渡していた
    (GSAS は Cell 解放を飛ばす — 例外も警告も無く、格子は初期値のまま出版される)。
    """
    seen: list = []
    out = _call(
        tool, [{"structure_path": "a.cif", "phase_name": "A", "refine_cell": None}], seen
    )
    assert "error" not in out
    assert [p.refine_cell for p in seen[0].phases] == [True]


@pytest.mark.parametrize("tool", ["auto_rietveld", "refine_with_revisions"])
def test_refine_cell_string_is_an_error_dict_not_a_silent_flip(tool):
    seen: list = []
    out = _call(
        tool, [{"structure_path": "a.cif", "phase_name": "A", "refine_cell": "false"}], seen
    )
    assert out["error_type"] == "ValueError" and "refine_cell は真偽値" in out["error"]
    assert seen == []  # 精密化を回してから失敗しない
