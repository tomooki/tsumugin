"""check_profile_physicality の CW 分岐 (GSAS getFWHM 準拠) の決定論テスト。

**設計注記**: GSAS はガウス分散を max(0.001,·) でクランプし、ローレンツ負値も反射位置以外では
総 FWHM に影響しないため、CW 係数の符号は revert 基準にならない (良好フィットでも U<0,Y<0 に収束)。
よって CW は soft 警告のみ・hard は値の NaN/inf (発散) のみ。numpy-only・GSAS 非依存。
"""

from __future__ import annotations

import math

from tsumugin.autorietveld.model import Radiation
from tsumugin.autorietveld.validity import check_profile_physicality

_CW_RANGE = (10.0, 120.0)  # 2θ deg


def _cw(**kw) -> dict[str, tuple[float, bool]]:
    """CW プロファイル。既定は物理値。kw で key -> (value, refined) を上書き。"""
    base = {
        "U": (2.0, False), "V": (-2.0, False), "W": (5.0, False),
        "X": (0.0, False), "Y": (0.0, False), "SH/L": (0.002, False),
    }
    base.update(kw)
    return base


def _check(prof, rad=Radiation.XRAY_SYNCHROTRON, rng=_CW_RANGE, **kw):
    return check_profile_physicality(
        profiles=[prof], radiations=[rad], ranges=[rng], **kw
    )


# --- CW は revert しない (GSAS クランプ準拠): 係数の符号は soft 警告 ---

def test_default_cw_profile_passes():
    assert _check(_cw()).passed is True


def test_gauss_negative_W_does_not_revert_but_warns():
    # GSAS はガウス分散を 0.001 にクランプ → W 大負でも passed=True、参考警告のみ
    r = _check(_cw(W=(-10.0, True)))
    assert r.passed is True
    assert any("H_G" in w for w in r.warnings)


def test_gauss_negative_U_does_not_revert():
    # 実 T1 は U=-1.96 に収束 (良好フィット) → passed=True
    assert _check(_cw(U=(-1.96, True), V=(-4.5, True), W=(6.4, True))).passed is True


def test_gauss_vertex_minimum_negative_warns_only():
    r = _check(_cw(U=(2.0, True), V=(-4.0, True), W=(1.9, True)))
    assert r.passed is True
    assert any("H_G" in w for w in r.warnings)


def test_gauss_linear_degenerate_U_zero_no_exception():
    assert _check(_cw(U=(0.0, True), V=(1.0, True), W=(0.5, True))).passed is True


# --- ローレンツ X,Y は soft (反射位置依存につき非 revert) ---

def test_lorentzian_positive_passes():
    assert _check(_cw(X=(1.0, True), Y=(0.5, True))).passed is True


def test_lorentzian_negative_Y_does_not_revert_but_warns():
    # 実 T1 は Y=-3.13 に収束 → passed=True + 参考警告
    r = _check(_cw(Y=(-3.13, True)))
    assert r.passed is True
    assert any(w.startswith("hist0 Y=") for w in r.warnings)


def test_lorentzian_tiny_negative_within_tol_no_warning():
    r = _check(_cw(X=(-1e-6, True)))
    assert r.passed is True
    assert not any("X=" in w for w in r.warnings)


# --- SH/L は soft ---

def test_shl_default_passes():
    assert _check(_cw(**{"SH/L": (0.002, True)})).passed is True


def test_shl_negative_warns_not_reverts():
    r = _check(_cw(**{"SH/L": (-0.01, True)}))
    assert r.passed is True
    assert any("SH/L" in w for w in r.warnings)


def test_shl_over_soft_max_warns_not_reverts():
    r = _check(_cw(**{"SH/L": (0.5, True)}))
    assert r.passed is True
    assert any("SH/L" in w and "soft" in w for w in r.warnings)


# --- 真の発散 (NaN/inf) は全放射源共通で hard ---

def test_nonfinite_refined_value_reverts():
    assert _check(_cw(U=(float("nan"), True))).passed is False
    assert _check(_cw(W=(float("inf"), True))).passed is False


def test_nonfinite_unrefined_value_does_not_revert():
    # 未解放の NaN は誤 revert しない (REQ-102)
    assert _check(_cw(U=(float("nan"), False))).passed is True


# --- 決定論 ---

def test_deterministic():
    a = _check(_cw(Y=(-3.13, True)))
    b = _check(_cw(Y=(-3.13, True)))
    assert (a.passed, a.checks, a.warnings) == (b.passed, b.checks, b.warnings)
    assert math.isfinite(0.0)  # sanity
