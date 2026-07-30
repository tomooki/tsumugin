"""座標ジッタ (`engine._apply_coord_jitter`) — マルチスタートの構造軸。GSAS 非依存。

Rietveld の局所解は主に**構造**にあるので、格子だけ振っても「格子のベイスンが 1 つ」しか
言えない。ここで固定するのは **対称性を壊さないこと**と、**摂動が効かなかったことを黙らない**
こと (高対称構造では全軸が固定され得るので、そのとき傍証を主張してはならない)。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _apply_coord_jitter

_PTRS = (3, 1, 7, 9)

#: `GSASIIspc.CSxinel` の実テーブル値 (`GSASIIspc.py:2528-2557`) を注入する
#: (実 `GetCSxinel` を使うと GSAS の有無でテスト結果が変わる)。
_CSXINEL = {
    "1": [[1, 2, 3], [1.0, 1.0, 1.0], [1, 2, 3]],        # X Y Z (一般位置)
    "0 0 z": [[0, 0, 1], [0.0, 0.0, 1.0], [0, 0, 3]],    # 0 0 Z
    "x -x 0": [[1, 1, 0], [1.0, -1.0, 0.0], [1, 1, 0]],  # X -X 0 (x,y 結束・z 固定)
    "0 0 0": [[0, 0, 0], [0.0, 0.0, 0.0], [0, 0, 0]],    # 全固定
}


def _getcsxinel(sym):
    return _CSXINEL[sym]


def _atom(label, xyz, sytsym="1"):
    return [label, label[0], "", xyz[0], xyz[1], xyz[2], 1.0, sytsym, 4.0, "I", 0.01]


class _FakePhase:
    def __init__(self, name, atoms, cell=(10.0, 10.0, 10.0)):
        self.name = name
        self.data = {"Atoms": atoms, "General": {"AtomPtrs": list(_PTRS)}}
        self._cell = cell

    def get_cell(self):
        a, b, c = self._cell
        return {
            "length_a": a, "length_b": b, "length_c": c,
            "angle_alpha": 90.0, "angle_beta": 90.0, "angle_gamma": 90.0,
        }


def test_general_position_moves_all_three_axes():
    atoms = [_atom("O1", (0.25, 0.5, 0.125))]
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)
    assert n == 3
    assert (atoms[0][3], atoms[0][4], atoms[0][5]) != (0.25, 0.5, 0.125)


def test_symmetry_fixed_axes_are_never_touched():
    """★特殊位置の固定軸を動かすと空間群が壊れる。**触らない**。"""
    atoms = [_atom("Ca1", (0.0, 0.0, 0.3), sytsym="0 0 z")]
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)

    assert atoms[0][3] == 0.0 and atoms[0][4] == 0.0, "x,y は対称拘束で固定"
    assert atoms[0][5] != 0.3, "z だけが自由"
    assert n == 1


def test_tied_axes_move_only_their_representative():
    """★結束軸 (``x -x 0`` の x,y) は代表だけ動かす — 従属軸は GSAS の等値拘束が追随する。

    非トートロジー: 両方を独立に動かすと結束関係が壊れ、GSAS が拘束を張り直した瞬間に
    どちらか一方が捨てられる (= 摂動が意図と違う形で入る)。
    """
    atoms = [_atom("F1", (0.2, -0.2, 0.0), sytsym="x -x 0")]
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)

    assert n == 1, "自由度は 1 つ (x,y が結束・z は固定)"
    assert atoms[0][3] != 0.2, "代表軸 x は動く"
    assert atoms[0][4] == -0.2, "従属軸 y は触らない"
    assert atoms[0][5] == 0.0, "z は対称固定"


def test_a_fully_fixed_structure_reports_zero_moved_axes():
    """★全軸が対称固定なら**摂動は効かない** — それを黙って傍証にしてはならない。

    非トートロジー: 高対称相ではこれが普通に起きる。戻り値 0 は「この軸では試験していない」
    であって「摂動したが動かなかった」ではない (`min_procedures` と同じ空虚な True の防止)。
    """
    atoms = [_atom("X1", (0.0, 0.0, 0.0), sytsym="0 0 0")]
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)
    assert n == 0
    assert (atoms[0][3], atoms[0][4], atoms[0][5]) == (0.0, 0.0, 0.0)


def test_amplitude_is_in_angstrom_not_fractional():
    """★振幅は **Å** で、軸長で分率へ直す。

    非トートロジー: 分率のままだと a=5Å と c=20Å で実距離が 4 倍違い、「同じ大きさの摂動」に
    ならない (`agreement` の座標床を Å 距離にしたのと同じ理由)。
    """
    long_c = _FakePhase("p", [_atom("O1", (0.5, 0.5, 0.5))], cell=(5.0, 5.0, 20.0))
    _apply_coord_jitter([long_c], {"p": 1.0}, 3, _getcsxinel)
    row = long_c.data["Atoms"][0]
    dx_ang = abs(row[3] - 0.5) * 5.0
    dz_ang = abs(row[5] - 0.5) * 20.0
    assert dx_ang <= 1.0 + 1e-9 and dz_ang <= 1.0 + 1e-9, "どの軸も Å では同じ上限"


def test_same_seed_is_bit_identical():
    """★NFR-102: 種が同じならビット同一 (並列実行の結果を突き合わせる前提)。"""
    def run(seed):
        atoms = [_atom("O1", (0.25, 0.5, 0.125)), _atom("P1", (0.4, 0.1, 0.2))]
        _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, seed, _getcsxinel)
        return [tuple(a[3:6]) for a in atoms]

    assert run(11) == run(11)
    assert run(11) != run(12), "種が違えば別の開始点になること"


def test_no_jitter_spec_is_a_no_op():
    atoms = [_atom("O1", (0.25, 0.5, 0.125))]
    assert _apply_coord_jitter([_FakePhase("p", atoms)], {}, 7, _getcsxinel) == 0
    assert _apply_coord_jitter([_FakePhase("p", atoms)], {"other": 0.05}, 7, _getcsxinel) == 0
    assert _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.0}, 7, _getcsxinel) == 0
    assert (atoms[0][3], atoms[0][4], atoms[0][5]) == (0.25, 0.5, 0.125)
