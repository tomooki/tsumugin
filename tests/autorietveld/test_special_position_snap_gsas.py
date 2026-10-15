"""特殊位置の吸着 — **実 GSAS-II** で多重度を測る (@pytest.mark.gsas, 合成 CIF のみ)。

- カナリア: 4 桁の 1/3 を GSAS-II がそのまま読むと一般位置 (多重度 6) になる。GSAS-II の
  更新で直ったらこのテストが落ちる — そのときは吸着が要るかを再検討する。
- 吸着後の CIF を読ませると 3m サイト (多重度 2)、自由軸 z は CIF の値のまま。
- 空間群記号からの対称操作の補完 (`_gsas_space_group_symops`) が GSAS の群と一致する。
"""

from __future__ import annotations

import pytest

from .test_special_position_snap import _zno_cif

pytestmark = pytest.mark.gsas

G2sc = pytest.importorskip("GSASII.GSASIIscriptable")


def _site_multiplicities(cif_path, tmp_path) -> dict[str, tuple[str, int, float]]:
    """GSAS-II が CIF から読んだ (サイト対称, 多重度, z)。"""
    G2sc.SetPrintLevel("none")
    gpx = G2sc.G2Project(newgpx=str(tmp_path / "probe.gpx"))
    phase = gpx.add_phase(str(cif_path), phasename="ZnO", fmthint="CIF")
    cx, ct, cs, _ = phase.data["General"]["AtomPtrs"]
    return {
        row[ct - 1]: (row[cs], int(row[cs + 1]), float(row[cx + 2]))
        for row in phase.data["Atoms"]
    }


def test_gsas_reads_four_decimal_thirds_as_general_positions(tmp_path):
    """カナリア: 吸着しない CIF を GSAS-II は多重度 6 で読む (= 吸着が要る理由)。"""
    sites = _site_multiplicities(_zno_cif(tmp_path), tmp_path)
    assert sites["Zn1"][1] == 6, sites


@pytest.mark.parametrize("with_symops", [True, False], ids=["cif-symops", "space-group"])
def test_snapped_cif_gives_multiplicity_two(tmp_path, with_symops):
    """★吸着後は 3m サイト (多重度 2)。自由軸 z は動かない。"""
    from tsumugin.autorietveld.engine import _gsas_space_group_symops
    from tsumugin.autorietveld.special_positions import snap_cif_special_positions

    report = snap_cif_special_positions(
        _zno_cif(tmp_path, with_symops=with_symops), tmp_path / "out", phase_name="ZnO",
        space_group_symops=_gsas_space_group_symops,
    )
    assert report.status == "snapped"
    assert report.symop_source == ("cif" if with_symops else "space_group")
    sites = _site_multiplicities(report.path, tmp_path)
    assert sites["Zn1"][:2] == ("3m(100)", 2), sites
    assert sites["O1"][:2] == ("3m(100)", 2), sites
    assert sites["O1"][2] == 0.3817
