"""fit-then-judge P1a タスク 6: 座標の自由度の照合 (`coordinate_freedom_mismatches`)。

engine は原子行の site symmetry から `GetCSxinel` で「座標を解放してよい原子」を決めるが、
site symmetry を解釈できないと**黙って凍結する** (`_phase_atom_info`)。座標から `SytSym` で
再計算した site symmetry の自由度と食い違う原子を列挙して、その凍結を観測できるようにする
(期待値を同じ原子行から取ると恒等式になり、拾いたい失敗を拾えない)。観測のみ。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.engine import _coordinate_freedom_mismatches

_CS = {
    "1": ((1, 2, 3), (1.0, 1.0, 1.0)),
    "m(x0z)": ((1, 0, 2), (1.0, 0.0, 1.0)),
    "-1": ((0, 0, 0), (0.0, 0.0, 0.0)),
}


def _getcsxinel(sym):
    return _CS[str(sym).strip()]


class _Phase:
    def __init__(self, name, rows, recomputed):
        self.name = name
        self.data = {
            "General": {"SGData": {"SpGrp": "P 21/m"}, "AtomPtrs": (2, 1, 5, 6)},
            "Atoms": [[lab, "O", x, y, z, sym, 0] for lab, (x, y, z), sym in rows],
        }
        self._recomputed = recomputed

    def sytsym(self, xyz, sgdata):
        return (self._recomputed[tuple(xyz)], 1, 1, {})


def _check(phase):
    return _coordinate_freedom_mismatches([phase], _getcsxinel, phase.sytsym)


def test_consistent_rows_report_nothing():
    ph = _Phase("p", [("O1", (0.1, 0.25, 0.3), "m(x0z)")], {(0.1, 0.25, 0.3): "m(x0z)"})
    assert _check(ph) == {}


def test_different_freedom_is_reported():
    ph = _Phase("p", [("O1", (0.1, 0.2, 0.3), "m(x0z)")], {(0.1, 0.2, 0.3): "1"})
    assert _check(ph) == {"p": (("O1", "m(x0z)", "1"),)}


def test_uninterpretable_row_symmetry_is_reported_not_skipped():
    """engine が黙って凍結する当の病理 — 行の site symmetry を解釈できない原子。"""
    ph = _Phase("p", [("O1", (0.1, 0.2, 0.3), "??")], {(0.1, 0.2, 0.3): "1"})
    assert _check(ph) == {"p": (("O1", "??", "1"),)}


def test_same_freedom_with_different_labels_is_not_a_mismatch():
    """記号が違っても自由な軸の並びが同じなら食い違いではない (設定の違い等)。"""
    cs = dict(_CS)
    cs["m(x0z)'"] = cs["m(x0z)"]
    ph = _Phase("p", [("O1", (0.1, 0.25, 0.3), "m(x0z)'")], {(0.1, 0.25, 0.3): "m(x0z)"})
    assert _coordinate_freedom_mismatches([ph], lambda s: cs[str(s).strip()], ph.sytsym) == {}


def test_recompute_failure_is_reported_as_unknown():
    def broken(xyz, sgdata):
        raise RuntimeError("bad")

    ph = _Phase("p", [("O1", (0.1, 0.2, 0.3), "1")], {})
    assert _coordinate_freedom_mismatches([ph], _getcsxinel, broken) == {
        "p": (("O1", "1", "?"),)
    }


@pytest.mark.gsas
def test_real_gsas_phase_detects_a_corrupted_site_symmetry(tmp_path):
    """実 GSAS: 正しい相では空、原子行の site symmetry を壊すと拾う。"""
    from GSASII import GSASIIscriptable as G2sc

    from .test_engine_polar_origin import _ZNO_CIF

    cif = tmp_path / "zno.cif"
    cif.write_text(_ZNO_CIF.format(oz=0.382), encoding="utf-8")
    gpx = G2sc.G2Project(newgpx=str(tmp_path / "p.gpx"))
    ph = gpx.add_phase(str(cif), phasename="ZnO", fmthint="CIF")
    assert _coordinate_freedom_mismatches([ph]) == {}
    cs = ph.data["General"]["AtomPtrs"][2]
    ph.data["Atoms"][1][cs] = "bogus"
    found = _coordinate_freedom_mismatches([ph])
    assert list(found) == ["ZnO"] and found["ZnO"][0][:2] == ("O1", "bogus")
