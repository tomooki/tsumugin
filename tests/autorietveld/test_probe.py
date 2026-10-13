"""fit-then-judge P1-1B タスク 9: 初期値プローブ (REQ-FTJ-1B-601〜603)。

判定 (`claims.build.with_probe`) と進行 (`autorietveld.probe`) を GSAS 非依存で、engine の
`probe_from_gpx` を合成データの gated テストで検査する。
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace

import pytest

from tsumugin.autorietveld.claim_variables import (
    HistogramVariables,
    PhaseVariables,
    claim_variable_names,
)
from tsumugin.autorietveld.diagnostics import CovarianceRecord
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.autorietveld.probe import ProbeConfig, ProbeOutcome, run_initial_value_probe
from tsumugin.claims.build import base_claims, with_probe
from tsumugin.claims.model import Determinacy

_VARS = claim_variable_names(
    [PhaseVariables(name="P", pid=0, labels=("Pb", "O1"))],
    [HistogramVariables(index=0, hid=0, profile_keys=("U",))],
)


def _result(o1=(0.25, 0.1, 0.3), a=5.0, axes=2, moved=("P.O1.x", "P.O1.y"), **kw) -> AutoRietveldResult:
    base = dict(
        stage_results=(StageResult("S0", 10.0, 1.2, 5, True),),
        final_rwp=10.0, final_gof=1.2,
        refined_cells={"P": (a, a, a, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        cell_esd={"P": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)},
        atom_coords={"P": {"Pb": (0.0, 0.0, 0.0), "O1": o1}},
        atom_coord_esd={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.001, 0.002, None)}},
        atom_coord_free_index={"P": {"Pb": (0, 0, 0), "O1": (1, 2, 3)}},
        atom_uiso={"P": {"Pb": 0.01, "O1": 0.02}},
        atom_uiso_esd={"P": {"Pb": 0.001, "O1": 0.03}},
        atom_occupancy={"P": {"Pb": 1.0, "O1": 1.0}},
        atom_occupancy_esd={"P": {"Pb": None, "O1": None}},
        phase_weight_fractions={"P": 1.0},
        phase_weight_fraction_esd={"P": 0.0},
        hist_profile=({"U": 2.0},),
        hist_profile_esd=({"U": 0.1},),
        final_covariance=CovarianceRecord(
            vary_list=("0::A0", "0::dAx:1", "0::dAy:1", "0::AUiso:0", "0::AUiso:1",
                       "0:0:Scale", ":0:U"),
            dependent=(), correlations=(),
        ),
        claim_variables=_VARS,
        coord_jitter_axes_moved=axes,
        coord_jitter_moved=moved,
    )
    base.update(kw)
    return AutoRietveldResult(**base)


def _outcome(*probes, cfg=ProbeConfig()) -> ProbeOutcome:
    return ProbeOutcome(cfg, tuple(probes))


def test_values_that_came_back_in_both_probes_are_locally_stable():
    base = _result()
    claims = with_probe(base_claims(base), base, _outcome(_result(), _result()))
    for key in ("cell:P.a", "coord:P.O1.x"):
        assert claims[key].determinacy is Determinacy.LOCALLY_STABLE, key
        assert claims[key].witnesses[-1].kind == "initial_value_probe"


def test_classes_the_probe_did_not_perturb_get_no_witness():
    """Uiso・占有率・プロファイル等は振っていない — 戻ったのは当然 (レビュー H1)。"""
    base = _result()
    claims = with_probe(base_claims(base), base, _outcome(_result(), _result()))
    assert claims["uiso:P.Pb"].determinacy is Determinacy.ESD_ONLY


def test_a_coordinate_that_was_not_moved_in_both_probes_gets_no_witness():
    base = _result()
    claims = with_probe(
        base_claims(base), base, _outcome(_result(), _result(moved=("P.O1.y",)))
    )
    assert claims["coord:P.O1.x"].determinacy is Determinacy.ESD_ONLY
    assert claims["coord:P.O1.y"].determinacy is Determinacy.LOCALLY_STABLE


def test_a_displacement_within_the_agreement_floor_is_no_witness():
    """許容幅 (0.02 Å) 以下しか振らないで「戻った」は空虚 (レビュー H1)。"""
    base = _result()
    cfg = ProbeConfig(cell_frac=0.0, coord_jitter_ang=0.02)
    claims = with_probe(base_claims(base), base, _outcome(_result(), _result(), cfg=cfg))
    assert claims["coord:P.O1.x"].determinacy is Determinacy.ESD_ONLY


def test_an_unconverged_probe_is_no_witness():
    base = _result()
    bad = _result(stage_results=(StageResult("probe", 10.0, 1.2, 5, False),))
    claims = with_probe(base_claims(base), base, _outcome(_result(), bad))
    assert not any(c.determinacy is Determinacy.LOCALLY_STABLE for c in claims.values())
    json.dumps({k: c.to_dict() for k, c in claims.items()}, allow_nan=False)


def test_a_value_that_did_not_come_back_is_initial_value_dependent():
    base = _result()
    moved = _result(o1=(0.30, 0.1, 0.3))  # x が 50σ 離れた
    claims = with_probe(base_claims(base), base, _outcome(_result(), moved))
    c = claims["coord:P.O1.x"]
    assert c.determinacy is Determinacy.INITIAL_VALUE_DEPENDENT
    assert c.witnesses[-1].kind == "initial_value_probe_split"
    assert c.witnesses[-1].detail["probe"] == 1
    assert claims["coord:P.O1.y"].determinacy is Determinacy.LOCALLY_STABLE


def test_an_incomplete_probe_leaves_the_base_state():
    """回らなかった・省いたプローブは強いラベルを残さない (基底状態のまま)。"""
    base = _result()
    before = base_claims(base)
    for outcome in (None, _outcome(_result(), None), _outcome(_result()),
                    ProbeOutcome(ProbeConfig(), reason="gpx なし")):
        assert with_probe(before, base, outcome) == before


def test_coordinates_get_no_witness_when_no_axis_moved():
    base = _result()
    claims = with_probe(base_claims(base), base, _outcome(_result(axes=0, moved=()), _result(axes=0, moved=())))
    assert claims["coord:P.O1.x"].determinacy is Determinacy.ESD_ONLY
    assert claims["cell:P.a"].determinacy is Determinacy.LOCALLY_STABLE


def test_lattices_get_no_witness_when_the_cell_was_not_perturbed():
    base = _result()
    cfg = ProbeConfig(cell_frac=0.0, coord_jitter_ang=0.05)
    claims = with_probe(base_claims(base), base, _outcome(_result(), _result(), cfg=cfg))
    assert claims["cell:P.a"].determinacy is Determinacy.ESD_ONLY
    assert claims["coord:P.O1.x"].determinacy is Determinacy.LOCALLY_STABLE


def test_a_probe_that_perturbed_nothing_is_no_witness():
    base = _result()
    cfg = ProbeConfig(cell_frac=0.0, coord_jitter_ang=0.0)
    claims = with_probe(base_claims(base), base, _outcome(_result(), _result(), cfg=cfg))
    assert claims == base_claims(base)


def test_stronger_labels_are_not_downgraded_by_a_returning_probe():
    from tsumugin.claims.model import Witness

    base = _result()
    claims = base_claims(base)
    claims["cell:P.a"] = claims["cell:P.a"].strengthened_to(
        Determinacy.DETERMINED, Witness("multistart_agreement", {})
    )
    out = with_probe(claims, base, _outcome(_result(), _result()))
    assert out["cell:P.a"].determinacy is Determinacy.DETERMINED


def test_input_and_symmetry_values_are_not_promoted():
    base = _result()
    claims = with_probe(base_claims(base), base, _outcome(_result(), _result()))
    assert claims["coord:P.O1.z"].determinacy is Determinacy.ESD_ONLY  # 入力値は戻って当然
    assert claims["cell:P.alpha"].determinacy is Determinacy.EXACT


# --- 進行 (run_initial_value_probe) ---------------------------------------------


def test_the_probe_runs_plus_and_minus_from_the_saved_gpx(tmp_path):
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    calls = []

    def prober(path, **kw):
        calls.append((path, kw))
        return _result()

    out = run_initial_value_probe(str(gpx), ProbeConfig(cell_frac=0.01, seed=5), prober=prober)
    assert out.complete and out.reason == ""
    assert [c[1]["sign"] for c in calls] == [1, -1]
    assert [c[1]["seed"] for c in calls] == [5, 5]
    assert all(c[1]["blas_threads"] == 1 and c[1]["cell_frac"] == 0.01 for c in calls)
    json.dumps(out.to_dict(), allow_nan=False)


def test_without_a_saved_gpx_the_probe_does_not_run():
    out = run_initial_value_probe("", prober=lambda *a, **k: pytest.fail("走った"))
    assert not out.complete and "gpx" in out.reason


def test_a_failed_start_is_recorded_not_counted_as_returned(tmp_path):
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")

    def prober(path, *, sign, **kw):
        if sign < 0:
            raise RuntimeError("GSAS failed")
        return _result()

    out = run_initial_value_probe(str(gpx), prober=prober)
    assert not out.complete and out.probes[1] is None and "GSAS failed" in out.errors[0]


@pytest.mark.parametrize(
    "bad",
    [{"cell_frac": -0.1}, {"cell_frc": 0.1}, {"cell_frac": 0.0, "coord_jitter_ang": 0.0},
     {"max_cyc": 0}, {"seed": 1.5}],
)
def test_malformed_probe_specs_are_refused(bad):
    with pytest.raises(ValueError):
        ProbeConfig.from_dict(bad)


def test_probe_spec_defaults_and_round_trip():
    assert ProbeConfig.from_dict(None) == ProbeConfig()
    cfg = ProbeConfig.from_dict({"cell_frac": 0.01, "coord_jitter_ang": 0.0})
    assert ProbeConfig.from_dict(cfg.to_dict()) == cfg
    assert replace(cfg, seed=1).seed == 1


# --- gated: 合成 ZnO (hold-out と別の構造から GSAS で作ったパターン) -----------------


@pytest.mark.gsas
def test_probes_from_a_saved_fit_come_back_and_leave_the_gpx_untouched(tmp_path, monkeypatch):
    import hashlib

    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld

    from .test_engine_polar_origin import _synthetic_zno

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    import numpy as np

    xye, instprm, start = _synthetic_zno(tmp_path)
    # 計数雑音を足す (雑音なしだと最終段が「未収束」になり、そもそも証人の対象にならない)
    x, y, _ = np.loadtxt(xye, unpack=True)
    noisy = np.random.default_rng(0).poisson(y).astype(float)
    np.savetxt(xye, np.column_stack([x, noisy, np.sqrt(np.maximum(noisy, 1.0))]), fmt="%.6f")
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(instprm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    base = run_auto_rietveld([hist], [PhaseSpec(str(start), "ZnO", fix_polar_origin=True)])
    digest = hashlib.sha256(open(base.gpx_path, "rb").read()).hexdigest()

    # 座標だけを振る (格子の摂動は下の別テスト)。
    outcome = run_initial_value_probe(
        base.gpx_path, ProbeConfig(cell_frac=0.0, coord_jitter_ang=0.05)
    )
    assert outcome.complete, outcome.errors
    assert hashlib.sha256(open(base.gpx_path, "rb").read()).hexdigest() == digest
    # プローブの fit も成果物として残る (規定 2026-08-20。/code-review #243)
    saved = outcome.to_dict()["gpx_paths"]
    assert [Path(s).name.split(".probe-")[1] for s in saved] == ["plus.gpx", "minus.gpx"]
    assert all(Path(s).is_file() and Path(s).parent == Path(base.gpx_path).parent for s in saved)
    for probe in outcome.probes:
        # O1 の z だけ — Zn の z は座標フラグが立っているが極性原点の hold に入っている
        assert probe.coord_jitter_axes_moved == 1
        assert probe.coord_jitter_moved == ("ZnO.O1.z",)
        assert abs(probe.final_rwp - base.final_rwp) < 0.01 * base.final_rwp

    claims = with_probe(base_claims(base), base, outcome)
    assert claims["coord:ZnO.O1.z"].determinacy is Determinacy.LOCALLY_STABLE
    # 格子は振っていない — 「戻った」と数えない
    assert claims["cell:ZnO.a"].determinacy is Determinacy.ESD_ONLY


def test_a_poorly_determined_coordinate_gets_no_witness():
    """σ が大きく kσ 帯が変位を超える座標は「戻った」と区別できない (セルフレビュー N3)。"""
    base = _result(atom_coord_esd={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.001, 0.004, None)}})
    claims = with_probe(base_claims(base), base, _outcome(base, base))
    assert claims["coord:P.O1.x"].determinacy is Determinacy.LOCALLY_STABLE  # 3√2·0.001 < 0.01
    assert claims["coord:P.O1.y"].determinacy is Determinacy.ESD_ONLY  # 3√2·0.004 > 0.01


def test_a_converged_probe_that_split_still_downgrades_when_the_other_did_not_converge():
    """収束した開始点がはっきり割れたことは情報 — 片方が収束しなくても落とす。昇格はしない (N7)。"""
    base = _result()
    moved = _result(o1=(0.30, 0.1, 0.3))
    bad = _result(stage_results=(StageResult("probe", 10.0, 1.2, 5, False),))
    claims = with_probe(base_claims(base), base, _outcome(moved, bad))
    assert claims["coord:P.O1.x"].determinacy is Determinacy.INITIAL_VALUE_DEPENDENT
    assert claims["coord:P.O1.y"].determinacy is Determinacy.ESD_ONLY


def test_both_probes_use_the_same_directions_with_opposite_signs(tmp_path):
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    calls = []
    run_initial_value_probe(str(gpx), ProbeConfig(seed=7), prober=lambda p, **kw: calls.append(kw) or _result())
    assert [(c["sign"], c["seed"]) for c in calls] == [(1, 7), (-1, 7)]


@pytest.mark.parametrize("jitter", [0.01, 0.02])
def test_a_coordinate_displacement_within_the_floor_is_refused(jitter):
    with pytest.raises(ValueError, match="許容幅"):
        ProbeConfig.from_dict({"coord_jitter_ang": jitter})


def test_the_split_witness_names_the_original_probe():
    """収束しなかった開始点を飛ばしても、割れた開始点の元の添字を記録する (L-a)。"""
    base = _result()
    bad = _result(stage_results=(StageResult("probe", 10.0, 1.2, 5, False),))
    moved = _result(o1=(0.30, 0.1, 0.3))
    claims = with_probe(base_claims(base), base, _outcome(bad, moved))
    assert claims["coord:P.O1.x"].witnesses[-1].detail["probe"] == 1
