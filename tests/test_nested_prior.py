"""TASK-0049 nested/prior の契約テスト (RestraintSpec / build_prior_from_restraints)。

検証:
- restraint から uniform / truncated_normal を構成 (REQ-008)
- overrides で手動上書き (REQ-301)
- 返り tuple が param_name 昇順で決定論 (NFR-102/REQ-402)
- 同一入力で 2 回ビット同一
- 種別既定 (lattice=±%, occ=[0,1], scale=[0,大])
- コア (numpy) のみで import できる
"""

from __future__ import annotations

import pytest


def test_import_core_only():
    import tsumugin.nested.prior as prior  # noqa: F401


def test_uniform_from_lower_upper_restraint():
    from tsumugin.nested.prior import RestraintSpec, build_prior_from_restraints

    priors = build_prior_from_restraints(
        frozenset({"phase0.lattice.a"}),
        [RestraintSpec(param_name="phase0.lattice.a", lower=4.9, upper=5.1)],
    )
    assert len(priors) == 1
    spec = priors[0]
    assert spec.param_name == "phase0.lattice.a"
    assert spec.kind == "uniform"
    assert spec.low == pytest.approx(4.9)
    assert spec.high == pytest.approx(5.1)


def test_truncated_normal_from_center_sigma_restraint():
    from tsumugin.nested.prior import RestraintSpec, build_prior_from_restraints

    priors = build_prior_from_restraints(
        frozenset({"global.occ.na"}),
        [RestraintSpec(param_name="global.occ.na", center=0.5, sigma=0.1)],
    )
    spec = priors[0]
    assert spec.kind == "truncated_normal"
    assert spec.loc == pytest.approx(0.5)
    assert spec.scale == pytest.approx(0.1)
    # 切断区間は占有率既定 [0,1]
    assert spec.low == pytest.approx(0.0)
    assert spec.high == pytest.approx(1.0)


def test_overrides_replace_auto_construction():
    from tsumugin.nested.base import PriorSpec
    from tsumugin.nested.prior import RestraintSpec, build_prior_from_restraints

    manual = PriorSpec(param_name="phase0.lattice.a", kind="normal", loc=5.0, scale=0.01)
    priors = build_prior_from_restraints(
        frozenset({"phase0.lattice.a"}),
        [RestraintSpec(param_name="phase0.lattice.a", lower=1.0, upper=9.0)],
        overrides={"phase0.lattice.a": manual},
    )
    assert priors == (manual,)


def test_result_sorted_by_param_name():
    from tsumugin.nested.prior import build_prior_from_restraints

    priors = build_prior_from_restraints(
        frozenset({"phase1.scale", "phase0.lattice.a", "global.occ.x"})
    )
    names = [p.param_name for p in priors]
    assert names == sorted(names)


def test_deterministic_bit_identical():
    from tsumugin.nested.prior import RestraintSpec, build_prior_from_restraints

    fp = frozenset({"phase0.lattice.a", "phase0.occ.na", "phase1.scale"})
    rs = [RestraintSpec(param_name="phase0.occ.na", center=0.3, sigma=0.05)]
    a = build_prior_from_restraints(fp, rs)
    b = build_prior_from_restraints(fp, rs)
    assert a == b


def test_default_lattice_interval_is_uniform_around_center():
    from tsumugin.nested.prior import build_prior_from_restraints

    # restraint 未指定の lattice は uniform (種別既定区間)
    priors = build_prior_from_restraints(frozenset({"phase0.lattice.a"}))
    spec = priors[0]
    assert spec.kind == "uniform"
    assert spec.low < spec.high


def test_default_occupancy_is_zero_one():
    from tsumugin.nested.prior import build_prior_from_restraints

    priors = build_prior_from_restraints(frozenset({"phase0.occ.na"}))
    spec = priors[0]
    assert spec.kind == "uniform"
    assert spec.low == pytest.approx(0.0)
    assert spec.high == pytest.approx(1.0)

    # "occupancy" 末尾キーも占有率扱い
    priors2 = build_prior_from_restraints(frozenset({"global.occupancy"}))
    s2 = priors2[0]
    assert s2.low == pytest.approx(0.0)
    assert s2.high == pytest.approx(1.0)


def test_default_scale_is_finite_nonnegative():
    from tsumugin.nested.prior import build_prior_from_restraints

    priors = build_prior_from_restraints(frozenset({"phase0.scale"}))
    spec = priors[0]
    assert spec.kind == "uniform"
    assert spec.low == pytest.approx(0.0)
    assert spec.high > 0.0
    import math

    assert math.isfinite(spec.high)


def test_global_param_name_parsed_for_kind():
    from tsumugin.nested.prior import build_prior_from_restraints

    # global.occ.x は末尾キー occ で占有率既定
    priors = build_prior_from_restraints(frozenset({"global.occ.x"}))
    spec = priors[0]
    assert spec.low == pytest.approx(0.0)
    assert spec.high == pytest.approx(1.0)


def test_lower_only_restraint_falls_back_to_default_when_incomplete():
    # lower のみ (upper 欠) は uniform を完成できないため種別既定へ縮退 (妥当な既定)
    from tsumugin.nested.prior import RestraintSpec, build_prior_from_restraints

    priors = build_prior_from_restraints(
        frozenset({"phase0.occ.na"}),
        [RestraintSpec(param_name="phase0.occ.na", lower=0.2)],
    )
    spec = priors[0]
    # 種別既定 (占有率 [0,1]) へ縮退しつつ lower を尊重
    assert spec.low == pytest.approx(0.2)
    assert spec.high == pytest.approx(1.0)


def test_sigma_zero_restraint_falls_back_to_uniform_no_zerodivision():
    # MEDIUM-4: sigma=0 は truncated_normal を作らず uniform 既定へ縮退 (ZeroDivisionError 回避)
    from tsumugin.nested.prior import RestraintSpec, build_prior_from_restraints

    priors = build_prior_from_restraints(
        frozenset({"global.occ.na"}),
        [RestraintSpec(param_name="global.occ.na", center=0.5, sigma=0.0)],
    )
    spec = priors[0]
    assert spec.kind == "uniform"
    # transform が例外を起こさず単調増加を保つ。
    import math

    for u in (0.0, 0.5, 1.0):
        assert math.isfinite(spec.transform(u))
    assert spec.transform(0.2) < spec.transform(0.8)


def test_sigma_negative_restraint_falls_back_to_uniform_monotonic():
    # MEDIUM-4: sigma<0 は逆 CDF 単調減少 (prior 不正) を避けて uniform 既定へ縮退
    from tsumugin.nested.prior import RestraintSpec, build_prior_from_restraints

    priors = build_prior_from_restraints(
        frozenset({"phase0.occ.na"}),
        [RestraintSpec(param_name="phase0.occ.na", center=0.5, sigma=-0.1)],
    )
    spec = priors[0]
    assert spec.kind == "uniform"
    assert spec.transform(0.2) < spec.transform(0.8)


def test_empty_free_params_returns_empty():
    from tsumugin.nested.prior import build_prior_from_restraints

    assert build_prior_from_restraints(frozenset()) == ()


def test_returns_tuple_of_priorspec():
    from tsumugin.nested.base import PriorSpec
    from tsumugin.nested.prior import build_prior_from_restraints

    priors = build_prior_from_restraints(frozenset({"phase0.lattice.a"}))
    assert isinstance(priors, tuple)
    assert all(isinstance(p, PriorSpec) for p in priors)
