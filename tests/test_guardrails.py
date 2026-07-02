from __future__ import annotations

from tsumugin.backends.base import RefinementResult
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.refinement.guardrails import check_guards


def _result(
    chi2: float,
    *,
    a: float = 5.0,
    occ: dict | None = None,
    wt_frac: float | None = None,
) -> RefinementResult:
    phase = PhaseInstance(
        phase_ref="P",
        lattice=LatticeParams(a, 5.0, 5.0),
        scale=1.0,
        wt_frac=wt_frac,
        occupancies=occ or {},
    )
    return RefinementResult(
        phases=(phase,),
        chi2=chi2,
        rwp=1.0,
        n_obs=100,
        n_params=1,
        converged=True,
        n_cycles=1,
    )


def test_chi2_divergence():
    prev = _result(100.0)
    cur = _result(200.0)  # 2x > 1.5x threshold
    kinds = [v.kind for v in check_guards(prev, cur)]
    assert "chi2_divergence" in kinds


def test_near_zero_chi2_ratio_noise_is_not_divergence():
    # ノイズフリーデータで chi2 がほぼ 0 のとき、数値ゆらぎ (1e-8 -> 1e-6) は
    # 比率こそ 100 倍だが絶対増分が無視できるため発散扱いにしない
    prev = _result(1e-8)
    cur = _result(1e-6)
    assert check_guards(prev, cur) == ()


def test_negative_occupancy():
    cur = _result(100.0, occ={"Fe": -0.1})
    vios = check_guards(None, cur)
    neg = [v for v in vios if v.kind == "negative_occupancy"]
    assert neg and neg[0].param == "phase0.occ.Fe"


def test_lattice_runaway():
    prev = _result(100.0, a=5.0)
    cur = _result(90.0, a=6.25)  # +25% > 20% threshold
    vios = check_guards(prev, cur)
    run = [v for v in vios if v.kind == "lattice_runaway"]
    assert run and run[0].param == "phase0.lattice.a"


def test_phase_fraction_pinned():
    cur = _result(100.0, wt_frac=1e-6)  # below 1e-4
    kinds = [v.kind for v in check_guards(None, cur)]
    assert "phase_fraction_pinned" in kinds


def test_clean_improvement_has_no_violations():
    prev = _result(100.0, a=5.0)
    cur = _result(80.0, a=5.01, occ={"Fe": 0.9}, wt_frac=0.5)
    assert check_guards(prev, cur) == ()


def test_prev_none_skips_chi2_and_lattice_checks():
    # huge chi2 but no prev to compare -> no chi2_divergence, no lattice_runaway
    cur = _result(1e9, a=999.0)
    kinds = [v.kind for v in check_guards(None, cur)]
    assert "chi2_divergence" not in kinds
    assert "lattice_runaway" not in kinds


def test_multiple_violations_ordered_deterministically():
    prev = _result(100.0, a=5.0)
    cur = _result(300.0, a=7.0, occ={"Fe": -0.2}, wt_frac=1e-8)
    kinds = [v.kind for v in check_guards(prev, cur)]
    # kind 定義順: chi2 -> negative_occ -> lattice -> negative_adp -> pinned
    assert kinds == [
        "chi2_divergence",
        "negative_occupancy",
        "lattice_runaway",
        "phase_fraction_pinned",
    ]


def test_negative_adp_forward_compat():
    cur = _result(100.0, occ={"adp_Fe": -0.01})
    kinds = [v.kind for v in check_guards(None, cur)]
    assert "negative_adp" in kinds
