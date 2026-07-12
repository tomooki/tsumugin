"""_cells_physical の決定論テスト (Issue #49: 格子発散/無効計量テンソルガード)。

多相 Rietveld で少数相の相分率が 0 に近づくと格子が悪条件化し発散し得る
(a/b/c が 1e9 規模に爆発、あるいは角度が幾何学的に不可能な値になり計量テンソルが
非正定値になる)。既存ガードは崩壊 (近ゼロ) のみを検出していたため、爆発・無効
計量テンソルのケースを追加する。GSAS 非依存のスタブで検証する。numpy-only。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _cells_physical


class _StubPhase:
    """get_cell() が dict を返す最小スタブ (GSAS G2Phase の代替)。"""

    def __init__(self, cell: dict[str, float]) -> None:
        self._c = cell

    def get_cell(self):
        return self._c


def _cell(a=10.09, b=7.32, c=6.96, alpha=90.0, beta=90.4, gamma=90.0) -> dict[str, float]:
    return {
        "length_a": a,
        "length_b": b,
        "length_c": c,
        "angle_alpha": alpha,
        "angle_beta": beta,
        "angle_gamma": gamma,
    }


def test_normal_physical_cell_passes():
    assert _cells_physical([_StubPhase(_cell())]) is True


def test_near_zero_collapse_fails():
    """既存挙動: a が min_length 未満に崩壊したら False。"""
    assert _cells_physical([_StubPhase(_cell(a=0.1))]) is False


def test_explosion_fails():
    """Issue #49 の核心ケース: 少数相セルが発散し a が桁違いに巨大化。"""
    assert _cells_physical([_StubPhase(_cell(a=1e9))]) is False


def test_invalid_metric_tensor_all_obtuse_fails():
    """角度が全て 150°: cos²の和が体積項を非正にする幾何学的に不可能な格子。"""
    assert _cells_physical([_StubPhase(_cell(alpha=150.0, beta=150.0, gamma=150.0))]) is False


def test_invalid_metric_tensor_skewed_angles_fails():
    assert _cells_physical([_StubPhase(_cell(alpha=170.0, beta=10.0, gamma=10.0))]) is False


def test_non_finite_length_fails():
    assert _cells_physical([_StubPhase(_cell(a=float("inf")))]) is False
    assert _cells_physical([_StubPhase(_cell(a=float("nan")))]) is False


def test_non_finite_angle_fails():
    assert _cells_physical([_StubPhase(_cell(alpha=float("nan")))]) is False


def test_multi_phase_one_diverged_fails():
    """多相のうち 1 相でも発散していれば全体 False (少数相発散を見逃さない)。"""
    good = _StubPhase(_cell())
    diverged = _StubPhase(_cell(a=1e9))
    assert _cells_physical([good, diverged]) is False


def test_max_length_boundary_respects_custom_param():
    assert _cells_physical([_StubPhase(_cell(a=50.0))], max_length=100.0) is True
    assert _cells_physical([_StubPhase(_cell(a=150.0))], max_length=100.0) is False
