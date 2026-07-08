"""check_profile_physicality (プロファイル物理性判定, 純関数) の決定論テスト。

CW (X線/CW中性子) の幅関数正値性・ローレンツ非負・SH/L 下限+soft上限、hard/soft 切り分け (解放フラグ)。
TOF 分岐は test_profile_physicality_tof.py。numpy-only・GSAS 非依存。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import Radiation
from tsumugin.autorietveld.validity import check_profile_physicality

_CW_RANGE = (10.0, 120.0)  # 2θ deg


def _cw(**kw) -> dict[str, tuple[float, bool]]:
    """CW プロファイル。既定は物理値 (U=2,V=-2,W=5,X=0,Y=0,SH/L=0.002)。kw で上書き。

    値は (value, refined) タプル。kw は key -> (value, refined)。
    """
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


# --- ガウス幅正値性 (REQ-002) ---

def test_default_cw_profile_is_physical():
    # TC-002-01: 既定 U=2,V=-2,W=5 は [10°,120°] で H_G²>0 → OK
    assert _check(_cw()).passed is True


def test_gauss_negative_W_low_angle_fails():
    # TC-002-E01: W 大負 → 低角で H_G²<0。W refined で hard NG
    r = _check(_cw(W=(-10.0, True)))
    assert r.passed is False


def test_gauss_negative_U_high_angle_fails():
    # TC-002-E02: U 負 (concave-down) → 端点で負 → hard NG
    r = _check(_cw(U=(-5.0, True)))
    assert r.passed is False


def test_gauss_vertex_minimum_negative_fails():
    # TC-002-B01: 端点は正だが頂点 (t*=1.0, レンジ内) で負 → 頂点評価が効いて NG
    r = _check(_cw(U=(2.0, True), V=(-4.0, True), W=(1.9, True)))
    assert r.passed is False


def test_gauss_linear_degenerate_U_zero_ok_no_exception():
    # TC-002-B02 / EDGE-103: U=0 (頂点非存在) でも例外なく端点判定
    r = _check(_cw(U=(0.0, True), V=(1.0, True), W=(0.5, True)))
    assert r.passed is True


def test_gauss_violation_soft_when_not_refined():
    # REQ-202: U,V,W 未解放なら幅違反は hard にしない (warning のみ, passed=True)
    r = _check(_cw(W=(-10.0, False)))
    assert r.passed is True
    assert any("H_G" in w or "gauss" in w.lower() or "幅" in w for w in r.warnings)


# --- ローレンツ非負 (REQ-003) ---

def test_lorentzian_positive_ok():
    # TC-003-01
    assert _check(_cw(X=(1.0, True), Y=(0.5, True))).passed is True


def test_lorentzian_negative_X_fails():
    # TC-003-E01
    assert _check(_cw(X=(-0.5, True))).passed is False


def test_lorentzian_negative_Y_fails():
    # TC-003-E02
    assert _check(_cw(Y=(-0.3, True))).passed is False


def test_lorentzian_tiny_negative_within_tol_ok():
    # TC-003-B01: -1e-6 は sign_tol(1e-3) 内 → OK
    assert _check(_cw(X=(-1e-6, True))).passed is True


# --- SH/L 下限 + soft 上限 (REQ-004/103) ---

def test_shl_default_ok():
    assert _check(_cw(**{"SH/L": (0.002, True)})).passed is True


def test_shl_negative_fails():
    # TC-004-E01
    assert _check(_cw(**{"SH/L": (-0.01, True)})).passed is False


def test_shl_over_soft_max_warns_not_reverts():
    # TC-103-01/02: SH/L=0.5 は hard OK (>=-tol) だが soft 上限 0.1 超 → warnings, passed=True
    r = _check(_cw(**{"SH/L": (0.5, True)}))
    assert r.passed is True
    assert any("SH/L" in w for w in r.warnings)


# --- hard/soft 切り分け = 解放フラグ (REQ-102) ---

def test_unrefined_sign_violation_does_not_revert():
    # TC-102-01: X=-0.5 だが refined=False → hard にしない
    assert _check(_cw(X=(-0.5, False))).passed is True


def test_refined_sign_violation_reverts():
    # TC-102-02: 同じ X=-0.5 が refined=True → NG (対比)
    assert _check(_cw(X=(-0.5, True))).passed is False


# --- 決定論 ---

def test_deterministic():
    a = _check(_cw(X=(0.3, True)))
    b = _check(_cw(X=(0.3, True)))
    assert a.passed == b.passed
    assert a.checks == b.checks
    assert a.warnings == b.warnings
