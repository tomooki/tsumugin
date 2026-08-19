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
