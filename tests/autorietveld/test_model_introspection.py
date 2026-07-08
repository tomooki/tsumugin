"""AutoRietveldResult 内省フィールド (refine-loop-diagnostics REQ-001) の決定論テスト。"""

from __future__ import annotations

import dataclasses

from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport


def _base(**kw) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=10.0, gof=1.2, n_params=5, converged=True),),
        final_rwp=10.0,
        final_gof=1.2,
        refined_cells={},
        validity=ValidityReport(passed=True),
        **kw,
    )


def test_introspection_fields_hold_values():
    # TC-001-01: 新フィールドに与えた値を保持する。
    res = _base(
        atom_uiso={"P1": {"Cu": 0.01, "Ow": 0.05}},
        atom_occupancy={"P1": {"Ow": 0.34}},
        hist_absorption=(0.031, 0.35),
        hist_profile=({"Zero": -2.6, "alpha": 0.5}, {"X": 1.2, "Y": 39.0}),
        peak_width_ratio=(1.08, 0.97),
        asymmetry_metric=(0.12, 0.0),
        intensity_bias_metric=(0.03, 0.0),
        bg_extrema=(3, 9),
    )
    assert res.atom_uiso["P1"]["Ow"] == 0.05
    assert res.atom_occupancy["P1"]["Ow"] == 0.34
    assert res.hist_absorption == (0.031, 0.35)
    assert res.hist_profile[0]["alpha"] == 0.5
    assert res.peak_width_ratio == (1.08, 0.97)
    assert res.asymmetry_metric[0] == 0.12
    assert res.intensity_bias_metric[0] == 0.03
    assert res.bg_extrema == (3, 9)


def test_introspection_fields_default_empty_backward_compat():
    # TC-001-02: 省略時は既定空で後方互換 (旧構築・スタブが壊れない, EDGE-001)。
    res = _base()
    assert res.atom_uiso == {}
    assert res.atom_occupancy == {}
    assert res.hist_absorption == ()
    assert res.hist_profile == ()
    assert res.peak_width_ratio == ()
    assert res.asymmetry_metric == ()
    assert res.intensity_bias_metric == ()
    assert res.bg_extrema == ()


def test_introspection_fields_replace_non_destructive():
    # TC-001-B01: dataclasses.replace が新フィールドを非破壊更新する (frozen)。
    res = _base()
    res2 = dataclasses.replace(res, bg_extrema=(2, 4), asymmetry_metric=(0.2,))
    assert res.bg_extrema == ()  # 元は不変
    assert res2.bg_extrema == (2, 4)
    assert res2.asymmetry_metric == (0.2,)
    assert res2.final_rwp == res.final_rwp  # 他フィールドは保持
