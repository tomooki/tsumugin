"""GSAS 経路の特殊位置吸着 — CIF を GSAS が読む前に射影する (GSAS 非依存で測る)。

2026-10-15 実測: GSAS-II の ``SytSym`` は 4 桁の 1/3 (``0.3333, 0.6667``) を P6₃mc の 3m サイトと
認めず一般位置 (多重度 6 = 3 倍) として読む。精密化は Rwp 6.37% (合成 ZnO) で完走し、固定軸の
esd・GII・組成だけが壊れる。COD 1011258 (zincite) のように 1/3 を 4 桁で書く CIF は多い。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.cif_normalize import read_structure_cif
from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation

_P63MC_OPS = (
    "x,y,z", "-y,x-y,z", "-x+y,-x,z", "-x,-y,z+1/2", "y,-x+y,z+1/2", "x-y,x,z+1/2",
    "-y,-x,z", "-x+y,y,z", "x,x-y,z", "y,x,z+1/2", "x-y,-y,z+1/2", "-x,-x+y,z+1/2",
)


def _zno_cif(tmp_path: Path, *, with_symops: bool = True, zn=("0.3333", "0.6667", "0.0000"),
             o=("0.3333", "0.6667", "0.3817(3)")) -> Path:
    """COD 1011258 型の ZnO (P6₃mc)。1/3 を 4 桁で書く。"""
    lines = [
        "data_ZnO",
        "_cell_length_a 3.2495(2)",
        "_cell_length_b 3.2495(2)",
        "_cell_length_c 5.2069(3)",
        "_cell_angle_alpha 90",
        "_cell_angle_beta 90",
        "_cell_angle_gamma 120",
        "_symmetry_space_group_name_H-M 'P 63 m c'",
    ]
    if with_symops:
        lines += ["loop_", "_symmetry_equiv_pos_as_xyz"] + [f"'{op}'" for op in _P63MC_OPS]
    lines += [
        "loop_",
        "_atom_site_label",
        "_atom_site_type_symbol",
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_U_iso_or_equiv",
        f"Zn1 Zn {zn[0]} {zn[1]} {zn[2]} 0.0060",
        f"O1 O {o[0]} {o[1]} {o[2]} 0.0080",
    ]
    path = tmp_path / "ZnO.cif"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _no_space_group_lookup(hm: str):
    raise AssertionError(f"CIF に対称操作があるのに空間群記号から引いた: {hm!r}")


def test_four_decimal_thirds_are_snapped_before_gsas_reads_the_cif(tmp_path):
    """★GSAS に渡す CIF では 1/3・2/3 が機械精度 (GSAS の SytSym が 3m と判定する精度)。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    report = snap_cif_special_positions(
        _zno_cif(tmp_path), tmp_path / "out", phase_name="ZnO",
        space_group_symops=_no_space_group_lookup,
    )
    assert report.status == "snapped"
    atoms = {a.label: a for a in read_structure_cif(report.path).atoms}
    for label in ("Zn1", "O1"):
        assert atoms[label].x == pytest.approx(1 / 3, abs=1e-10), label
        assert atoms[label].y == pytest.approx(2 / 3, abs=1e-10), label


def test_free_axis_is_written_back_unchanged(tmp_path):
    """★射影は最小ノルム: 3m サイトの z (自由軸) は CIF の値のまま。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    report = snap_cif_special_positions(
        _zno_cif(tmp_path), tmp_path / "out", phase_name="ZnO",
        space_group_symops=_no_space_group_lookup,
    )
    atoms = {a.label: a for a in read_structure_cif(report.path).atoms}
    assert atoms["O1"].z == 0.3817
    assert atoms["Zn1"].z == 0.0
    # 動かない軸は元のトークン (esd 付き) のまま書き戻す — 書き直すのは動いた軸だけ。
    assert " 0.3817(3) " in Path(report.path).read_text(encoding="utf-8")


def test_three_decimal_thirds_are_snapped_from_the_written_precision(tmp_path):
    """★3 桁 (``0.333``) は既定の許容差 1e-4 では拾えない — 書かれた桁数から許容差を決める。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    src = _zno_cif(tmp_path, zn=("0.333", "0.667", "0.000"), o=("0.333", "0.667", "0.382"))
    report = snap_cif_special_positions(
        src, tmp_path / "out", phase_name="ZnO", space_group_symops=_no_space_group_lookup
    )
    atoms = {a.label: a for a in read_structure_cif(report.path).atoms}
    assert atoms["Zn1"].x == pytest.approx(1 / 3, abs=1e-10)
    assert atoms["O1"].z == 0.382


def test_ledger_payload_names_moved_atoms_and_distances(tmp_path):
    """記録: どの原子がどれだけ動いたか (分率と Å)、対称操作の出どころ。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    report = snap_cif_special_positions(
        _zno_cif(tmp_path), tmp_path / "out", phase_name="ZnO",
        space_group_symops=_no_space_group_lookup,
    ).to_dict()
    assert report["phase"] == "ZnO"
    assert report["symop_source"] == "cif"
    moved = {m["label"]: m for m in report["moved"]}
    assert set(moved) == {"Zn1", "O1"}
    zn = moved["Zn1"]
    assert zn["from"] == [0.3333, 0.6667, 0.0]
    assert zn["to"][0] == pytest.approx(1 / 3, abs=1e-12)
    # |Δ| = (1/3 − 0.3333, 2/3 − 0.6667) を a=3.2495 Å の六方格子で測った距離 (~1e-4 Å)
    assert 0 < zn["shift_angstrom"] < 1e-3


def test_untouched_cif_is_passed_through(tmp_path):
    """陽性対照: 動かす原子が無ければ元の CIF をそのまま渡す (書き直さない)。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    src = _zno_cif(
        tmp_path,
        zn=("0.333333333333", "0.666666666667", "0.0"),
        o=("0.333333333333", "0.666666666667", "0.3817"),
    )
    report = snap_cif_special_positions(
        src, tmp_path / "out", phase_name="ZnO", space_group_symops=_no_space_group_lookup
    )
    assert report.status == "unchanged"
    assert report.path == str(src)
    assert report.to_dict()["moved"] == []


def test_genuine_displacement_beyond_written_precision_is_kept(tmp_path):
    """陽性対照: 4 桁で 1/3 から 3e-4 ずれた座標は実在の変位 — 書かれた精度で区別できる。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    src = _zno_cif(tmp_path, zn=("0.3330", "0.6670", "0.0000"), o=("0.1234", "0.4321", "0.3817"))
    report = snap_cif_special_positions(
        src, tmp_path / "out", phase_name="ZnO", space_group_symops=_no_space_group_lookup
    )
    assert report.status == "unchanged", report.to_dict()


def test_missing_symops_fall_back_to_the_space_group(tmp_path):
    """CIF に対称操作が無ければ空間群記号から引く (GSAS が H-M 名から作るのと同じ群)。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    asked = []

    def lookup(hm):
        asked.append(hm)
        return _P63MC_OPS

    report = snap_cif_special_positions(
        _zno_cif(tmp_path, with_symops=False), tmp_path / "out", phase_name="ZnO",
        space_group_symops=lookup,
    )
    assert asked == ["P 63 m c"]
    assert report.status == "snapped"
    assert report.to_dict()["symop_source"] == "space_group"


def test_unobtainable_symops_are_recorded_not_silently_skipped(tmp_path):
    """★対称操作が手に入らなければ「吸着しなかった」と理由付きで記録する (黙って素通しにしない)。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    def lookup(hm):
        raise ValueError("unknown space group")

    src = _zno_cif(tmp_path, with_symops=False)
    report = snap_cif_special_positions(
        src, tmp_path / "out", phase_name="ZnO", space_group_symops=lookup
    ).to_dict()
    assert report["status"] == "skipped"
    assert "unknown space group" in report["reason"]
    assert report["path"] == str(src)


def test_unreadable_cif_is_recorded_and_passed_through(tmp_path):
    """読めない CIF は GSAS 自身の判断に任せる (ここで止めない) — ただし記録は残す。"""
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    report = snap_cif_special_positions(
        tmp_path / "missing.cif", tmp_path / "out", phase_name="X",
        space_group_symops=_no_space_group_lookup,
    ).to_dict()
    assert report["status"] == "skipped"
    assert report["reason"]


# ---------------------------------------------------------------- engine 配線 (偽 GSAS)


class _ReachedRefinementSetup(Exception):
    pass


class _FakePhase:
    def __init__(self, name):
        self.data = {"General": {"AtomPtrs": [3, 1, 7, 9]}, "Atoms": []}
        self.name = name

    def get_cell(self):
        raise _ReachedRefinementSetup


def _run_engine(monkeypatch, phase_specs):
    from tsumugin.autorietveld import engine as eng
    from tsumugin.store.ledger import Ledger

    seen: dict[str, str] = {}

    class _Project:
        def __init__(self, newgpx):
            pass

        def add_powder_histogram(self, *a, **k):
            class _H:
                data = {"Sample Parameters": {}}
            return _H()

        def add_phase(self, path, phasename, **k):
            seen[phasename] = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
            return _FakePhase(phasename)

    class _G2sc:
        G2Project = _Project

    monkeypatch.setattr(eng, "_g2sc", lambda: _G2sc)
    ledger = Ledger()
    hist = HistogramSpec(
        data_path="d.xra", instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )
    with pytest.raises(_ReachedRefinementSetup):
        eng.run_auto_rietveld([hist], phase_specs, save_gpx=False, ledger=ledger)
    return seen, [e.payload for e in ledger.entries if e.kind == "m7_special_position_snap"]


def test_engine_hands_gsas_the_snapped_cif_and_records_it(monkeypatch, tmp_path):
    """★配線: GSAS の add_phase が受け取る CIF は吸着済みで、ledger に移動が残る。"""
    src = _zno_cif(tmp_path)
    seen, entries = _run_engine(monkeypatch, [PhaseSpec(structure_path=str(src), phase_name="ZnO")])
    assert "0.3333 0.6667" not in seen["ZnO"], "GSAS に 4 桁の 1/3 が渡った"
    assert [e["phase"] for e in entries] == ["ZnO"]
    assert {m["label"] for m in entries[0]["moved"]} == {"Zn1", "O1"}
    assert src.read_text(encoding="utf-8").count("0.3333 0.6667") == 2, "入力 CIF を書き換えない"


def test_engine_records_non_cif_phases_as_skipped(monkeypatch, tmp_path):
    """CIF 以外 (GSAS .EXP) は射影しないが、しなかったことを記録する。"""
    seen, entries = _run_engine(
        monkeypatch, [PhaseSpec(structure_path=str(tmp_path / "x.EXP"), phase_name="X",
                                format_hint="EXP")]
    )
    assert entries == [
        {"phase": "X", "status": "skipped", "symop_source": None, "moved": [],
         "reason": "format_hint='EXP' (CIF 以外は射影しない)", "path": str(tmp_path / "x.EXP")}
    ]


def test_engine_adds_no_ledger_row_when_nothing_moved(monkeypatch, tmp_path):
    """既定経路の ledger は状態変化の記録だけ (`test_stability_gates_gsas`) — 動かす原子が
    無い相は行を足さず、元の CIF をそのまま GSAS に渡す。"""
    src = _zno_cif(
        tmp_path,
        zn=("0.333333333333", "0.666666666667", "0.0"),
        o=("0.333333333333", "0.666666666667", "0.3817"),
    )
    seen, entries = _run_engine(monkeypatch, [PhaseSpec(structure_path=str(src), phase_name="ZnO")])
    assert entries == []
    assert seen["ZnO"] == src.read_text(encoding="utf-8")
