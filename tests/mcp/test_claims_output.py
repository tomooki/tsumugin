"""fit-then-judge P1-1A タスク 8: ② の結果に出版状態が載ること (REQ-FTJ-1A-501/502)。

`auto_rietveld` (単発・探索・収束確認) と `refine_with_revisions` の結果に、既存キーを変えずに
``claims``・``judgment_requests``・``publishable_values``・``claims_version`` を足す。JSON 安全・例外に
しない・精密化済み gpx の隣に sidecar を書く。
"""

from __future__ import annotations

import dataclasses
import json
import os

import pytest

from tsumugin.autorietveld.claim_variables import (
    HistogramVariables,
    PhaseVariables,
    claim_variable_names,
)
from tsumugin.autorietveld.diagnostics import CovarianceRecord
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.claims import requests as rq
from tsumugin.claims.model import Check, Witness
from tsumugin.claims.sidecar import read_claims_sidecar
from tsumugin.gpxstore import ENV_VAR, active_context
from tsumugin.mcp.rietveld_tools import auto_rietveld, refine_with_revisions

_H = {
    "data_path": "d.xra", "instrument_path": "i.prm", "radiation": "xray_lab",
    "geometry": "bragg_brentano", "data_format": "GSAS",
}
_P = {"structure_path": "a.cif", "phase_name": "ph"}
_NEW_KEYS = ("claims_version", "claims", "judgment_requests", "publishable_values",
             "claims_sidecar", "claims_sidecar_reason", "claims_policy")


def _rich(gpx_path: str = "") -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("S0", 9.5, 1.5, 30, True),),
        final_rwp=9.5, final_gof=1.5, n_obs=4000,
        refined_cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        cell_esd={"ph": (0.001,) * 3 + (0.0,) * 3},
        validity=ValidityReport(passed=True),
        atom_coords={"ph": {"O1": (0.1, 0.2, 0.3)}},
        atom_coord_esd={"ph": {"O1": (0.001, 0.001, 0.001)}},
        atom_coord_free_index={"ph": {"O1": (1, 2, 3)}},
        phase_weight_fractions={"ph": 1.0},
        phase_weight_fraction_esd={"ph": 0.0},
        final_covariance=CovarianceRecord(
            vary_list=("0::A0", "0::dAx:0", "0::dAy:0", "0::dAz:0", "0:0:Scale"),
            dependent=(), correlations=(),
        ),
        claim_variables=claim_variable_names(
            [PhaseVariables("ph", 0, ("O1",))], [HistogramVariables(0, 0, ())],
        ),
        gpx_path=gpx_path,
    )


@pytest.fixture
def checks_pass(monkeypatch):
    monkeypatch.setattr(
        rq, "_phase_set_witness", lambda r: (Check.PASS, Witness("residual_window_snr", {})),
    )
    monkeypatch.setattr(rq, "crystal_chemistry", lambda phase, path, r: {
        "crystal_chemistry": (Check.PASS, Witness("crystal_chemistry", {})),
    })


def test_single_route_adds_the_publication_state_and_keeps_existing_keys():
    out = auto_rietveld([_H], [_P], runner=lambda inp: _rich())
    for key in _NEW_KEYS:
        assert key in out, key
    assert out["refined_cells"] == {"ph": [10.0, 10.0, 10.0, 90.0, 90.0, 90.0]}  # 既存キーは不変
    json.dumps(out, allow_nan=False)
    # 検査器が走れない (CIF も残差も無い) ので何も出版しない — 黙って出版可にしない
    assert out["publishable_values"] == {}
    kinds = {r["kind"] for r in out["judgment_requests"]}
    assert {"phase_set_completeness", "crystal_chemistry"} <= kinds
    assert all(r["default"]["answer"] == "hold" for r in out["judgment_requests"])
    # 収束確認が無い単発経路では determined は付かない
    assert not any(c["determinacy"] == "determined" for c in out["claims"].values())


def test_publishable_values_are_exactly_the_publishable_claims(checks_pass):
    out = auto_rietveld([_H], [_P], runner=lambda inp: _rich())
    want = {k for k, c in out["claims"].items() if c["publishable"]}
    assert want and set(out["publishable_values"]) == want
    assert out["publishable_values"]["cell:ph.a"] == {
        "value": 10.0, "esd": 0.001, "unit": "angstrom",
    }


def test_refine_with_revisions_carries_the_publication_state_too(checks_pass):
    out = refine_with_revisions([_H], [_P], [], runner=lambda inp: _rich())
    assert "error" not in out, out.get("error")
    assert out["publishable_values"]


def test_a_sidecar_is_written_next_to_the_gpx(tmp_path, checks_pass):
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    out = auto_rietveld([_H], [_P], runner=lambda inp: _rich(str(gpx)))
    assert out["claims_sidecar"] == str(tmp_path / "fit.claims.json")
    side = read_claims_sidecar(str(gpx))
    assert side is not None and side["claims"] == out["claims"]


def test_no_gpx_means_no_sidecar_and_a_reason():
    out = auto_rietveld([_H], [_P], runner=lambda inp: _rich("missing.gpx"))
    assert out["claims_sidecar"] == "" and out["claims_sidecar_reason"]


def test_a_failure_to_build_the_state_publishes_nothing_and_does_not_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(rq, "assess", boom)
    out = auto_rietveld([_H], [_P], runner=lambda inp: _rich())
    assert out["claims"] is None and out["publishable_values"] == {}
    assert any("出版状態" in w and "RuntimeError" in w for w in out["warnings"])
    assert out["final_rwp"] == 9.5  # フィット結果は落とさない


def test_convergence_route_gives_determined_values_a_witness(tmp_path, monkeypatch):
    """収束確認経路: 全開始点が同じ解へ戻った値に `determined` (証人付き) が付く。"""
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "gpx"))

    def fake_engine(histograms, phases, **kwargs):
        ctx = kwargs.get("gpx_context") or active_context()
        path = ""
        if ctx is not None and ctx.enabled and ctx.run_dir:
            path = os.path.join(ctx.run_dir, ctx.stem(data_stem="d") + ".gpx")
            with open(path, "wb") as fh:
                fh.write(path.encode())
        return dataclasses.replace(_rich(), gpx_path=path)

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_engine)
    data = tmp_path / "data" / "d.xra"
    data.parent.mkdir()
    out = auto_rietveld(
        [{**_H, "data_path": str(data)}], [_P],
        search=["default"], multistart={"n_starts": 3, "jobs": 1},
    )
    assert "error" not in out, out.get("error")
    cell = out["claims"]["cell:ph.a"]
    assert cell["determinacy"] == "determined"
    assert [w["kind"] for w in cell["witnesses"]] == ["multistart_agreement"]
    assert out["claims_sidecar"], out["claims_sidecar_reason"]


def test_search_route_carries_the_publication_state(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, "none")
    monkeypatch.setattr(
        "tsumugin.autorietveld.engine.run_auto_rietveld",
        lambda histograms, phases, **kw: _rich(),
    )
    out = auto_rietveld([_H], [_P], search=["default"])
    assert "error" not in out, out.get("error")
    assert out["claims"] and "cell:ph.a" in out["claims"]
