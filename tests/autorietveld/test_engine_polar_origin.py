"""fit-then-judge P1a タスク 3: `PhaseSpec.fix_polar_origin` の engine 配線 (`_apply_polar_origin`)。

GSAS の G2Project/G2Phase と `GetCSxinel` を差し替えて、**どの変数にどの拘束を登録するか**を
決定論で検査する (原点の物理は `test_constraint_groups.py` の純関数テストが担う)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.engine import _apply_polar_origin
from tsumugin.autorietveld.model import PhaseSpec

_CS = {
    "3m(z)": ((0, 0, 1), (0.0, 0.0, 1.0)),
    "1": ((1, 2, 3), (1.0, 1.0, 1.0)),
    "3m(111)": ((1, 1, 1), (1.0, 1.0, 1.0)),
}


def _getcsxinel(sym):
    return _CS[str(sym).strip()]


class _Phase:
    # AtomPtrs = (cx, ct, cs, cia): ラベルは row[ct-1]、type は row[ct]、site sym は row[cs]
    def __init__(self, polax, rows, pid=0):
        self.id = pid
        self.data = {
            "General": {"SGData": {"SGPolax": polax}, "AtomPtrs": (2, 1, 5, 6)},
            "Atoms": [[lab, typ, 0, 0, 0, sym, 0] for lab, typ, sym in rows],
        }


class _Gpx:
    def __init__(self):
        self.calls = []

    def add_HoldConstr(self, names):
        self.calls.append(("hold", list(names)))

    def add_EqnConstr(self, total, names, mults):
        self.calls.append(("eqn", total, list(names), list(mults)))


def _spec(**kw):
    return PhaseSpec("x.cif", "w", **kw)


def test_holds_dz_of_the_heaviest_atom_for_a_z_polar_group():
    gpx = _Gpx()
    ph = _Phase("z", [("O1", "O", "3m(z)"), ("Zn1", "Zn", "3m(z)")])
    applied = _apply_polar_origin(gpx, [ph], [_spec(fix_polar_origin=True)], _getcsxinel)
    assert gpx.calls == [("hold", ["0::dAz:1"])]
    assert applied == [{"phase": "w", "polax": "z", "atom": "Zn1", "terms": [["z", 1.0]]}]


def test_nothing_is_registered_unless_the_phase_opts_in():
    gpx = _Gpx()
    ph = _Phase("z", [("Zn1", "Zn", "3m(z)")])
    assert _apply_polar_origin(gpx, [ph], [_spec()], _getcsxinel) == []
    assert gpx.calls == []


def test_frozen_atom_already_pins_the_origin():
    gpx = _Gpx()
    ph = _Phase("z", [("O1", "O", "3m(z)"), ("Zn1", "Zn", "3m(z)")])
    spec = _spec(fix_polar_origin=True, frozen_coord_labels=("O1",))
    assert _apply_polar_origin(gpx, [ph], [spec], _getcsxinel) == []
    assert gpx.calls == []


def test_111_general_atom_registers_a_sum_constraint():
    gpx = _Gpx()
    ph = _Phase("111", [("Bi1", "Bi", "1")], pid=2)
    _apply_polar_origin(gpx, [ph], [_spec(fix_polar_origin=True)], _getcsxinel)
    assert gpx.calls == [("eqn", 0.0, ["2::dAx:0", "2::dAy:0", "2::dAz:0"], [1.0, 1.0, 1.0])]


def test_111_atom_on_the_threefold_axis_holds_dax_only():
    gpx = _Gpx()
    ph = _Phase("111", [("Bi1", "Bi", "3m(111)"), ("O1", "O", "1")])
    _apply_polar_origin(gpx, [ph], [_spec(fix_polar_origin=True)], _getcsxinel)
    assert gpx.calls == [("hold", ["0::dAx:0"])]


def test_uninterpretable_site_symmetry_pins_the_origin_like_the_engine():
    """解釈できない原子は engine (`_phase_atom_info`) が座標を凍結する = 原点を決めている。

    固定を足すと実在の自由度を消すので何もしない (その原子は
    `coordinate_freedom_mismatches` に現れる)。以前は例外にしていたが engine の規則と食い違った。
    """

    def partly_broken(sym):
        if sym == "weird":
            raise KeyError(sym)
        return _getcsxinel(sym)

    gpx = _Gpx()
    ph = _Phase("z", [("O1", "O", "weird"), ("Zn1", "Zn", "3m(z)")])
    assert _apply_polar_origin(gpx, [ph], [_spec(fix_polar_origin=True)], partly_broken) == []
    assert gpx.calls == []


def test_phase_spec_fix_polar_origin_round_trip():
    spec = _spec(fix_polar_origin=True)
    assert PhaseSpec.from_dict(spec.to_dict()) == spec
    assert PhaseSpec("x.cif", "w").fix_polar_origin is False
    legacy = {k: v for k, v in spec.to_dict().items() if k != "fix_polar_origin"}
    assert PhaseSpec.from_dict(legacy).fix_polar_origin is False


# ---------------- gated: 合成データ (wurtzite ZnO, P6_3mc, c 軸極性) ----------------
#
# 極性構造の公開ベンチは hold-out (CaTeO3 delta) にしか無いので、GSAS-II で計算したパターンを
# 使う (ノイズなし・既知の真値)。真値 O z=0.382 から出発構造を 0.370 にずらして精密化する。

_ZNO_CIF = """data_ZnO
_cell_length_a 3.2500
_cell_length_b 3.2500
_cell_length_c 5.2070
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_symmetry_space_group_name_H-M 'P 63 m c'
_symmetry_Int_Tables_number 186
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Zn1 Zn 0.33333333 0.66666667 0.00000 1.0 0.008
O1  O  0.33333333 0.66666667 {oz:.5f} 1.0 0.010
"""


def _synthetic_zno(tmp_path):
    """真値 (O z=0.382) の ZnO パターンを GSAS で計算し、(xye, instprm, 出発 CIF) を返す。"""
    import numpy as np
    from GSASII import GSASIIscriptable as G2sc

    from tsumugin.autorietveld.model import Radiation
    from tsumugin.instprm import build_instprm_text

    instprm = tmp_path / "cuka1.instprm"
    instprm.write_text(
        build_instprm_text(radiation=Radiation.XRAY_LAB, wavelength=1.5405980), encoding="utf-8"
    )
    truth = tmp_path / "zno_truth.cif"
    truth.write_text(_ZNO_CIF.format(oz=0.382), encoding="utf-8")
    start = tmp_path / "zno_start.cif"
    start.write_text(_ZNO_CIF.format(oz=0.370), encoding="utf-8")

    sim = G2sc.G2Project(newgpx=str(tmp_path / "sim.gpx"))
    sim.add_phase(str(truth), phasename="ZnO", fmthint="CIF")
    hist = sim.add_simulated_powder_histogram(
        "sim", str(instprm), 20.0, 120.0, Tstep=0.02, phases=sim.phases()
    )
    sim.do_refinements([{}])
    x = np.asarray(hist.getdata("x"), dtype=float)
    ycalc = np.asarray(hist.getdata("ycalc"), dtype=float)
    y = 2.0e4 * ycalc / ycalc.max() + 100.0  # 計数統計の尺度 + 平坦な背景
    xye = tmp_path / "zno_sim.xye"
    np.savetxt(xye, np.column_stack([x, y, np.sqrt(y)]), fmt="%.6f")
    return xye, instprm, start


@pytest.mark.gsas
def test_polar_origin_is_held_on_a_real_gsas_refinement(tmp_path, monkeypatch):
    from GSASII import GSASIIscriptable as G2sc

    from tsumugin.autorietveld import Geometry, HistogramSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.store.ledger import Ledger

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _synthetic_zno(tmp_path)
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(instprm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    phase = PhaseSpec(str(start), "ZnO", fix_polar_origin=True)
    ledger = Ledger()
    result = run_auto_rietveld([hist], [phase], ledger=ledger)

    entries = [e.payload for e in ledger.entries if e.kind == "m7_polar_origin"]
    assert entries == [{"phase": "ZnO", "polax": "z", "atom": "Zn1", "terms": [["z", 1.0]]}]
    # 登録が gpx に実在すること (GSAS がたまたま特異方向を動かさなくても空振りしない)
    saved = G2sc.G2Project(gpxfile=result.gpx_path)
    assert "dAz" in str(saved.data["Constraints"]["data"]["Phase"])
    zn = result.atom_coords["ZnO"]["Zn1"]
    o = result.atom_coords["ZnO"]["O1"]
    assert zn[2] == 0.0, f"原点を固定した Zn の z が動いた: {zn}"
    assert abs(o[2] - 0.382) < 0.003, f"O の z が真値へ戻らない: {o}"


@pytest.mark.gsas
def test_jittered_starts_keep_the_origin_on_a_real_gsas_refinement(tmp_path, monkeypatch):
    """原点固定 + 座標の摂動 (収束確認の構造軸) が実 GSAS で正しく動く (P1-1B)。

    原点を決める Zn は摂動されず (z=0 のまま hold)、O だけが振られて真値へ戻る。
    """
    from tsumugin.autorietveld import Geometry, HistogramSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.store.ledger import Ledger

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _synthetic_zno(tmp_path)
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(instprm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    phase = PhaseSpec(str(start), "ZnO", fix_polar_origin=True)
    ledger = Ledger()
    result = run_auto_rietveld(
        [hist], [phase], ledger=ledger, initial_coord_jitter={"ZnO": 0.05}, jitter_seed=3
    )
    jit = next(e.payload for e in ledger.entries if e.kind == "m7_coord_jitter")
    assert jit["polar_origin_axes_not_jittered"] == {"ZnO": {"Zn1": ["z"]}}
    assert jit["n_axes_moved"] == 1  # O1 の z だけ
    zn = result.atom_coords["ZnO"]["Zn1"]
    o = result.atom_coords["ZnO"]["O1"]
    assert zn[2] == 0.0, f"原点を決める Zn が動いた: {zn}"
    assert abs(o[2] - 0.382) < 0.003, f"O の z が真値へ戻らない: {o}"
    assert result.coord_jitter_moved == ("ZnO.O1.z",)


def test_polar_origin_with_element_ranked_coords_stages_is_refused():
    """元素ランクの座標段では原点は既に決まっている — 静的な固定と組み合わせない (M6)。"""
    from tsumugin.autorietveld.constraint_groups import refuse_polar_origin_with_ranked_coords
    from tsumugin.autorietveld.model import RefinementStage
    from tsumugin.errors import InvalidPhaseSpecError

    ranked = [RefinementStage("z0", {"coords": 0}), RefinementStage("all", {"coords": True})]
    with pytest.raises(InvalidPhaseSpecError, match="元素ランク"):
        refuse_polar_origin_with_ranked_coords([_spec(fix_polar_origin=True)], ranked)
    # 全原子を解放する段だけなら可・相が opt-in していなければ検査しない
    refuse_polar_origin_with_ranked_coords(
        [_spec(fix_polar_origin=True)], [RefinementStage("all", {"coords": True})]
    )
    refuse_polar_origin_with_ranked_coords([_spec()], ranked)


def test_the_origin_fixing_atom_is_not_jittered():
    """原点を決める原子は座標の摂動から外す (P1-1B — 以前は組み合わせを拒否していた)。

    hold した座標を摂動すると開始点ごとに原点がずれ、極性方向の座標が「初期値依存」と誤判定される。
    """
    from tsumugin.autorietveld.engine import _coord_jitter_skips, polar_origin_atoms

    ph = _Phase("z", [("O1", "O", "3m(z)"), ("Zn1", "Zn", "3m(z)")])
    spec = _spec(fix_polar_origin=True, frozen_coord_labels=())
    assert polar_origin_atoms([ph], [spec], _getcsxinel) == {"w": {"Zn1"}}
    skip, origin = _coord_jitter_skips([ph], [spec], _getcsxinel)
    # 原子ごとではなく固定される軸 (z) だけを外す (レビュー M7)
    assert skip == {"w": ()} and origin == {"w": {"Zn1": {2}}}


def test_only_the_held_axis_of_the_origin_atom_is_skipped_and_moves_are_recorded():
    """一般位置の原点原子は z だけ hold — x,y は振って「試験した座標」として記録する。"""
    from tsumugin.autorietveld.engine import _apply_coord_jitter

    class _Ph(_Phase):
        name = "w"

        def get_cell(self):
            return {"length_a": 5.0, "length_b": 5.0, "length_c": 5.0}

    ph = _Ph("z", [("Bi1", "Bi", "1"), ("O1", "O", "3m(z)")])
    before = [list(r) for r in ph.data["Atoms"]]
    moved: list[str] = []
    n = _apply_coord_jitter(
        [ph], {"w": 0.05}, 0, _getcsxinel, frozen_axes={"w": {"Bi1": {2}}}, moved=moved,
        fixed_magnitude=True, sign=-1,
    )
    assert n == 3 and sorted(moved) == ["w.Bi1.x", "w.Bi1.y", "w.O1.z"]
    bi_after, bi_before = ph.data["Atoms"][0], before[0]
    assert bi_after[2 + 2] == bi_before[2 + 2]  # z は hold — 動かない
    for axis in (0, 1):  # 大きさは固定 (0.05 Å / 5 Å = 0.01)
        assert abs(abs(bi_after[2 + axis] - bi_before[2 + axis]) - 0.01) < 1e-12


def test_without_the_origin_flag_only_frozen_atoms_are_skipped():
    from tsumugin.autorietveld.engine import _coord_jitter_skips

    ph = _Phase("z", [("O1", "O", "3m(z)"), ("Zn1", "Zn", "3m(z)")])
    skip, origin = _coord_jitter_skips([ph], [_spec(frozen_coord_labels=("O1",))], _getcsxinel)
    assert skip == {"w": ("O1",)} and origin == {}


def test_the_standard_route_accepts_polar_origin_with_jitter():
    """原点固定と座標の摂動が組み合わせられる — Phase A が走る (以前は入口で拒否していた)。"""
    from tsumugin.autorietveld.confirm import optimize_then_confirm

    calls = []

    def search_runner(cand):
        calls.append(cand.name)
        raise RuntimeError("stop here")

    from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation

    h = HistogramSpec("d.xye", "i.instprm", Radiation.XRAY_LAB, Geometry.BRAGG_BRENTANO)
    optimize_then_confirm(
        [h], [_spec(fix_polar_origin=True)], candidates=["default"],
        search_runner=search_runner, save_gpx=False,
    )
    assert calls




def test_probe_and_phase_b_both_move_and_record_the_whole_tied_group():
    """結束軸 (x,x,x): プローブも収束確認も組ごと動かし、全軸を記録する。

    GSAS は精密化前に従属座標を揃え直さないので、代表軸だけを書き換えると結束が壊れたまま残る
    (`test_coord_jitter_tied_gsas.py`, PR #244)。従属側も初期値を一緒に動かしたので「試験した」に数える。
    """
    from tsumugin.autorietveld.engine import _apply_coord_jitter

    class _Ph(_Phase):
        name = "w"

        def get_cell(self):
            return {"length_a": 5.0, "length_b": 5.0, "length_c": 5.0}

    probe_moved: list[str] = []
    n = _apply_coord_jitter(
        [_Ph("111", [("Bi1", "Bi", "3m(111)")])], {"w": 0.05}, 0, _getcsxinel,
        fixed_magnitude=True, moved=probe_moved,
    )
    assert n == 1 and probe_moved == ["w.Bi1.x", "w.Bi1.y", "w.Bi1.z"]
    ph = _Ph("111", [("Bi1", "Bi", "3m(111)")])
    ms_moved: list[str] = []
    n = _apply_coord_jitter([ph], {"w": 0.05}, 0, _getcsxinel, moved=ms_moved)
    assert n == 1 and ms_moved == ["w.Bi1.x", "w.Bi1.y", "w.Bi1.z"]
    x, y, z = ph.data["Atoms"][0][2:5]
    assert x != 0 and x == y == z, "(x,x,x) のまま動く"
