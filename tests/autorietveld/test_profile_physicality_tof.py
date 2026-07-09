"""check_profile_physicality の TOF 分岐 + skip 縮退 (EDGE-001/003) の決定論テスト。

TOF ガウス分散 σ²=sig0+sig1·d²+sig2·d⁴ の d レンジ正値性・alpha/beta-0 strict-pos。numpy-only。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import Radiation
from tsumugin.autorietveld.validity import check_profile_physicality

_TOF = Radiation.NEUTRON_TOF
_D_RANGE = (0.5, 4.0)  # d (Å)


def _tof(**kw) -> dict[str, tuple[float, bool]]:
    base = {
        "sig-0": (100.0, False), "sig-1": (5.0, False), "sig-2": (0.0, False),
        "alpha": (0.5, False), "beta-0": (0.02, False),
    }
    base.update(kw)
    return base


def _check(prof, rng=_D_RANGE, **kw):
    return check_profile_physicality(
        profiles=[prof], radiations=[_TOF], ranges=[rng], **kw
    )


# --- ガウス分散 σ²≥0 (REQ-005) ---

def test_tof_default_variance_ok():
    # TC-005-01
    assert _check(_tof()).passed is True


def test_tof_negative_sig2_high_d_fails():
    # TC-005-E01: sig-2 大負 → 高 d で σ²<0 (sig 解放で hard)
    r = _check(_tof(**{"sig-2": (-50.0, True)}))
    assert r.passed is False


def test_tof_variance_boundary_near_zero_ok():
    # TC-005-B01: 端点 σ²≈0 (tol 内) → OK
    # d_lo=0.5 → x=0.25。σ²=sig0 + sig1*0.25。sig0=-1.2, sig1=5 → -1.2+1.25=0.05>=-tol
    r = _check(_tof(**{"sig-0": (-1.2, True), "sig-1": (5.0, True), "sig-2": (0.0, True)}))
    assert r.passed is True


# --- alpha/beta strict-pos (REQ-006) ---

def test_tof_alpha_beta_positive_ok():
    # TC-006-01
    assert _check(_tof(alpha=(0.5, True), **{"beta-0": (0.02, True)})).passed is True


def test_tof_alpha_zero_fails():
    # TC-006-E01: alpha=0 → 1/alpha 発散
    assert _check(_tof(alpha=(0.0, True))).passed is False


def test_tof_beta0_negative_fails():
    # TC-006-E02
    assert _check(_tof(**{"beta-0": (-0.01, True)})).passed is False


def test_tof_alpha_negative_unrefined_warns_only():
    # REQ-102: alpha<=0 でも未解放なら hard にしない
    r = _check(_tof(alpha=(0.0, False)))
    assert r.passed is True


# --- skip 縮退 (EDGE-001/003) ---

def test_empty_profile_skips_without_exception():
    # TC-001-E01: 空 dict → skip、例外なし、passed=True
    r = check_profile_physicality(
        profiles=[{}], radiations=[_TOF], ranges=[_D_RANGE]
    )
    assert r.passed is True
    assert any("skip" in w for w in r.warnings)


def test_none_range_skips_variance_but_keeps_sign():
    # EDGE-003: range None → σ² 判定 skip、alpha/beta 符号判定は継続
    r = _check(_tof(alpha=(-1.0, True)), rng=None)
    assert r.passed is False  # alpha 符号は効く
    # σ² の check は入っていない (レンジ skip)
    assert not any("σ²" in name for name, _, _ in r.checks)


def test_none_range_variance_only_skips():
    # range None + alpha/beta 物理 → σ² skip で passed=True
    r = _check(_tof(**{"sig-2": (-999.0, True)}), rng=None)
    assert r.passed is True


# --- 決定論 ---

def test_tof_deterministic():
    a = _check(_tof(**{"sig-1": (7.0, True)}))
    b = _check(_tof(**{"sig-1": (7.0, True)}))
    assert (a.passed, a.checks, a.warnings) == (b.passed, b.checks, b.warnings)
