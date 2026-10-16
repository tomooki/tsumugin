"""座標ジッタ (`engine._apply_coord_jitter`) — マルチスタートの構造軸。GSAS 非依存。

Rietveld の局所解は主に**構造**にあるので、格子だけ振っても「格子のベイスンが 1 つ」しか
言えない。ここで固定するのは **対称性を壊さないこと**と、**摂動が効かなかったことを黙らない**
こと (高対称構造では全軸が固定され得るので、そのとき傍証を主張してはならない)。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.autorietveld.engine import _apply_coord_jitter

_PTRS = (3, 1, 7, 9)

#: `GSASIIspc.CSxinel` の実テーブル値 (`GSASIIspc.py:2528-2557`) を注入する
#: (実 `GetCSxinel` を使うと GSAS の有無でテスト結果が変わる)。
_CSXINEL = {
    "1": [[1, 2, 3], [1.0, 1.0, 1.0], [1, 2, 3]],        # X Y Z (一般位置)
    "0 0 z": [[0, 0, 1], [0.0, 0.0, 1.0], [0, 0, 3]],    # 0 0 Z
    "x -x 0": [[1, 1, 0], [1.0, -1.0, 0.0], [1, 1, 0]],  # X -X 0 (x,y 結束・z 固定)
    "x x x": [[1, 1, 1], [1.0, 1.0, 1.0], [1, 1, 1]],    # X X X (3 回軸上)
    "2x x z": [[1, 1, 2], [2.0, 1.0, 1.0], [1, 1, 3]],   # 2X X Z (係数 2 の結束)
    "x 2x z": [[1, 1, 2], [1.0, 2.0, 1.0], [1, 1, 3]],   # X 2X Z (従属軸の倍率 2)
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


def test_tied_axes_move_together_by_the_gsas_coefficients():
    """★結束軸 (``x -x 0`` の x,y) は**係数どおりに一緒に**動かす — 自由度は 1 つのまま。

    非トートロジー: GSAS は結束を**シフト**の等値 (``dAy = (cy/cx)·dAx``,
    `GSASIIstrIO.py:1760-1765`) として張るだけで、精密化の前に座標を揃え直さない (実測:
    `test_coord_jitter_tied_gsas.py`)。代表軸だけを書き換えると、結束関係を破った出発点の
    ずれが精密化後の座標にそのまま残り、開始点ごとに違う値になる (偽の割れ)。
    """
    atoms = [_atom("F1", (0.2, -0.2, 0.0), sytsym="x -x 0")]
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)

    assert n == 1, "自由度は 1 つ (x,y が結束・z は固定)"
    dx, dy = atoms[0][3] - 0.2, atoms[0][4] - (-0.2)
    assert dx != 0.0, "代表軸 x は動く"
    assert dy == pytest.approx(-dx, abs=1e-15), "従属軸 y は係数 -1 で追随する (y = -x のまま)"
    assert atoms[0][5] == 0.0, "z は対称固定"


def test_threefold_axis_site_stays_on_the_axis():
    atoms = [_atom("S1", (0.38, 0.38, 0.38), sytsym="x x x")]
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)
    assert n == 1
    assert atoms[0][3] != 0.38
    assert atoms[0][3] == atoms[0][4] == atoms[0][5], "(x,x,x) のまま"


def test_coefficient_is_relative_to_the_representative():
    """``2x x z``: 代表は x (係数 2)、y は ``dy = (1/2)·dx`` で追随する (GSAS の割り算と同じ)。"""
    atoms = [_atom("Ni1", (0.34, 0.17, 0.25), sytsym="2x x z")]
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)
    assert n == 2, "自由度は x (y 結束) と z の 2 つ"
    dx, dy = atoms[0][3] - 0.34, atoms[0][4] - 0.17
    assert dx != 0.0 and atoms[0][5] != 0.25
    assert dy == pytest.approx(dx * 0.5, abs=1e-15), "x = 2y のまま"


def test_follower_with_ratio_above_one_stays_within_the_angstrom_amplitude():
    """★``x 2x z``: y は ``dy = 2·dx`` で追随し、**どの軸の変位も amp Å 以下** に収まる。

    非トートロジー: 代表の軸長だけで分率へ直すと y は 2·amp Å 動く — 結束原子だけが
    指定より強く振られ、構造ごとに摂動の強さが変わる (`test_amplitude_is_in_angstrom_not_fractional`
    と同じ契約を結束原子にも課す)。
    """
    worst = 0.0
    for seed in range(20):
        atoms = [_atom("Ni1", (0.17, 0.34, 0.25), sytsym="x 2x z")]
        n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 1.0}, seed, _getcsxinel)
        assert n == 2
        dx, dy = atoms[0][3] - 0.17, atoms[0][4] - 0.34
        assert dy == pytest.approx(2.0 * dx, abs=1e-15), "y = 2x のまま"
        assert abs(dy) * 10.0 <= 1.0 + 1e-9, "従属軸 y も amp Å 以下"
        worst = max(worst, abs(dy) * 10.0)
    assert worst > 0.5, "上限で潰して動かなくしたのではない (y は amp の近くまで動く)"


def test_followers_do_not_consume_random_draws():
    """★乱数は**独立変数ごとに 1 回**だけ引く — 結束の追随で乱数列がずれない。

    非トートロジー: 追随軸ぶん余計に引くと、結束原子より後ろの一般位置原子の開始点が
    以前の版と変わる (一般位置しか無い構造の摂動は以前とビット同一であるべき)。
    """
    atoms = [_atom("S1", (0.38, 0.38, 0.38), sytsym="x x x"), _atom("O1", (0.25, 0.5, 0.125))]
    _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel)
    draws = np.random.default_rng(7).uniform(-1.0, 1.0, size=4) * 0.05 / 10.0
    assert atoms[0][3] == 0.38 + float(draws[0])
    assert (atoms[1][3], atoms[1][4], atoms[1][5]) == (
        0.25 + float(draws[1]), 0.5 + float(draws[2]), 0.125 + float(draws[3])
    )


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


# ---------------------------------------------------------------------------
# 精密化しない原子は摂動しない (frozen_coord_labels)
# ---------------------------------------------------------------------------


def test_frozen_coord_labels_are_never_jittered():
    """★`frozen_coord_labels` の原子は**動かさない** — coords 段が解放しないので戻る道が無い。

    非トートロジー: ジッタは「精密化が初期値から戻ってくるか」を試すための摂動である。
    凍結原子は coords 段で X フラグが立たない (`_phase_atom_info` が除外する) ので、
    摂動した値が**そのまま最終解**になる。開始点ごとに違う種で振るので、凍結原子の座標は
    開始点ごとに違う値で固定され、`agreement` はそれを**偽のベイスン分岐**
    (`undetermined_by_initial_values`) として報告する — 実際には何も精密化していないのに。
    """
    atoms = [_atom("O1", (0.25, 0.5, 0.125)), _atom("P1", (0.4, 0.1, 0.2))]
    n = _apply_coord_jitter(
        [_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel, frozen={"p": {"O1"}}
    )

    assert tuple(atoms[0][3:6]) == (0.25, 0.5, 0.125), "凍結原子は動かさない"
    assert tuple(atoms[1][3:6]) != (0.4, 0.1, 0.2), "凍結していない原子は従来どおり動く"
    assert n == 3, "動かした軸数に凍結原子を数えない (傍証判定の n_axes_jittered になる)"


def test_frozen_labels_are_scoped_to_their_own_phase():
    """【対照】凍結ラベルは**その相の**原子だけに効く (同名ラベルが別相にあり得る)。"""
    atoms = [_atom("O1", (0.25, 0.5, 0.125))]
    n = _apply_coord_jitter(
        [_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel, frozen={"other": {"O1"}}
    )
    assert n == 3
    assert tuple(atoms[0][3:6]) != (0.25, 0.5, 0.125)


# ---------------------------------------------------------------------------
# 結束の組と P1-1B の機能 (軸単位の固定・記録・プローブ) の組み合わせ
# ---------------------------------------------------------------------------


def test_moved_records_every_axis_of_a_tied_group():
    """結束の組は従属側も初期値を一緒に書き換えたので、記録 (claims の証人の範囲) に全軸を載せる。"""
    atoms = [_atom("S1", (0.38, 0.38, 0.38), sytsym="x x x"), _atom("Ca1", (0.0, 0.0, 0.3), "0 0 z")]
    moved: list[str] = []
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel, moved=moved)
    assert n == 2
    assert moved == ["p.S1.x", "p.S1.y", "p.S1.z", "p.Ca1.z"]


def test_a_held_axis_freezes_its_whole_tied_group():
    """★軸単位の固定 (極性原点の hold) が組の 1 軸に掛かっていれば組ごと動かさない。

    非トートロジー: 組は GSAS では 1 変数 — 固定されていない軸だけを動かすと結束が壊れ、
    固定された軸に追随しない従属側のずれが最終座標に残る。
    """
    atoms = [_atom("S1", (0.38, 0.38, 0.38), sytsym="x x x"), _atom("O1", (0.25, 0.5, 0.125))]
    moved: list[str] = []
    n = _apply_coord_jitter(
        [_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel,
        frozen_axes={"p": {"S1": [1]}}, moved=moved,
    )
    assert tuple(atoms[0][3:6]) == (0.38, 0.38, 0.38), "組の y が固定 → x,z も動かさない"
    assert n == 3 and moved == ["p.O1.x", "p.O1.y", "p.O1.z"]


def test_probe_moves_tied_groups_together_with_amp_on_the_widest_axis():
    """★プローブ (fixed_magnitude) も結束した組を組ごと振る。最も大きく動く軸がちょうど amp Å。

    ``x 2x z``: y が x の 2 倍動くので y が amp、x は amp/2。記録 (``shifts``) には軸ごとの
    **実際の**分率変位を載せる — claims は「振った量が許容幅を超えたか」を軸ごとに判定する
    (全軸が amp 動いた前提で数えると、amp/2 しか動いていない x に空虚な証人を付ける)。
    """
    atoms = [_atom("Ni1", (0.17, 0.34, 0.25), sytsym="x 2x z"), _atom("Ca1", (0.0, 0.0, 0.3), "0 0 z")]
    moved: list[str] = []
    shifts: dict[str, float] = {}
    n = _apply_coord_jitter(
        [_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel,
        fixed_magnitude=True, sign=-1, moved=moved, shifts=shifts,
    )
    assert n == 3
    assert moved == ["p.Ni1.x", "p.Ni1.y", "p.Ni1.z", "p.Ca1.z"]
    dx, dy = atoms[0][3] - 0.17, atoms[0][4] - 0.34
    assert dy == pytest.approx(2.0 * dx, abs=1e-15), "y = 2x のまま"
    assert abs(dy) * 10.0 == pytest.approx(0.05, abs=1e-12), "最も動く軸 (y) がちょうど amp Å"
    assert shifts == pytest.approx({
        "p.Ni1.x": 0.0025, "p.Ni1.y": 0.005, "p.Ni1.z": 0.005, "p.Ca1.z": 0.005,
    }, abs=1e-12)


def test_shifts_record_the_actual_displacement_in_phase_b_too():
    atoms = [_atom("S1", (0.38, 0.38, 0.38), sytsym="x x x")]
    shifts: dict[str, float] = {}
    _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel, shifts=shifts)
    d = abs(atoms[0][3] - 0.38)
    assert set(shifts) == {"p.S1.x", "p.S1.y", "p.S1.z"}
    assert all(v == pytest.approx(d, abs=1e-15) for v in shifts.values())


def test_colocated_atoms_receive_the_same_shift():
    """★共位置の組 (混合占有・``position_equiv_groups``) は**同じ変位**で動かす。

    非トートロジー: engine は共位置を座標**シフト**の等値 (`_equiv_positions`) で保つだけで、値を揃え
    直さない。原子ごとに別の乱数を掛けると、出発点で開いた共位置のずれが精密化後も残り、開始点ごとに
    違う値になる (P1.5 の S-dev: 混合占有の Fe2/Mg2 が T-AB でだけ x が 0.08 Å 割れ、偽の
    「初期値依存」で全値が止まった)。
    """
    atoms = [_atom("Fe2", (0.99, 0.28, 0.25)), _atom("Mg2", (0.99, 0.28, 0.25)), _atom("O1", (0.1, 0.2, 0.3))]
    moved: list[str] = []
    n = _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel,
                            colocated={"p": (("Fe2", "Mg2"),)}, moved=moved)

    assert atoms[0][3:6] == atoms[1][3:6], "共位置が開いた"
    assert atoms[0][3:6] != [0.99, 0.28, 0.25], "動いていない"
    assert n == 6, "独立変数は組の 3 + O1 の 3 (組の従属側は数えない)"
    assert {"p.Fe2.x", "p.Mg2.x"} <= set(moved)


def test_colocated_group_is_skipped_whole_when_one_member_is_frozen():
    atoms = [_atom("Fe2", (0.99, 0.28, 0.25)), _atom("Mg2", (0.99, 0.28, 0.25))]
    _apply_coord_jitter([_FakePhase("p", atoms)], {"p": 0.05}, 7, _getcsxinel,
                        frozen={"p": ("Fe2",)}, colocated={"p": (("Fe2", "Mg2"),)})
    assert atoms[0][3:6] == atoms[1][3:6] == [0.99, 0.28, 0.25]


def test_no_colocated_groups_is_bit_identical_to_before():
    a = [_atom("O1", (0.1, 0.2, 0.3)), _atom("O2", (0.4, 0.5, 0.6))]
    b = [list(r) for r in a]
    _apply_coord_jitter([_FakePhase("p", a)], {"p": 0.05}, 7, _getcsxinel)
    _apply_coord_jitter([_FakePhase("p", b)], {"p": 0.05}, 7, _getcsxinel, colocated={"p": ()})
    assert a == b


def test_colocated_groups_come_from_mixed_occupancy_and_position_equivalence():
    from tsumugin.autorietveld.engine import _colocated_groups
    from tsumugin.autorietveld.model import PhaseSpec

    spec = PhaseSpec(structure_path="x.cif", phase_name="p", mixed_occupancy_groups=(("Fe2", "Mg2"),), position_equiv_groups=(("H1", "D1"),))
    assert _colocated_groups([spec]) == {"p": (("Fe2", "Mg2"), ("H1", "D1"))}
