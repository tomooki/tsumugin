"""autorietveld.mem (実 Dysnomia MEM 駆動) の TDD テスト (XND / MEM 実装)。

numpy-only の決定論コア (設定 dataclass / バイナリ解決 / ピーク→原子割当 / 密度種別 /
未導入縮退) を GSAS 非依存で検証し、実 Dysnomia MEM は @pytest.mark.gsas + バイナリ/
データ存在で gate する。
"""
from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from tsumugin.errors import MEMUnavailableError
from tsumugin.autorietveld.mem import (
    DensityPeak,
    MEMDensityResult,
    MEMRunConfig,
    _select_histogram,
    assign_peaks_to_atoms,
    density_kind_from_type,
    resolve_dysnomia_binary,
    run_dysnomia_mem,
)
from tsumugin.mem.base import MEMDensityMap


# ---------------------------------------------------------------------------
# (A) MEMRunConfig
# ---------------------------------------------------------------------------


def test_config_defaults():
    c = MEMRunConfig()
    assert c.dmin == pytest.approx(0.9)
    assert c.ncyc == 2000
    assert c.optimize == "ZSPA"
    assert c.grid_step == pytest.approx(0.25)
    assert c.density_kind is None
    assert c.binary_path is None
    assert c.extra_search_dirs == ()


def test_config_is_frozen():
    assert dataclasses.is_dataclass(MEMRunConfig)
    c = MEMRunConfig()
    with pytest.raises(FrozenInstanceError):
        c.dmin = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (B) density_kind_from_type (probe → 密度種別)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("t,expected", [
    ("PXC", "electron"), ("PXE", "electron"), ("X", "electron"),
    ("PNT", "nuclear"), ("PNC", "nuclear"), ("N", "nuclear"),
])
def test_density_kind_from_type(t, expected):
    assert density_kind_from_type(t) == expected


def test_density_kind_from_type_unknown_raises():
    with pytest.raises(ValueError):
        density_kind_from_type("ZZ")


# ---------------------------------------------------------------------------
# (C) resolve_dysnomia_binary (実在ファイルで解決 / 未検出 None)
# ---------------------------------------------------------------------------


def test_resolve_explicit_binary_path(tmp_path):
    exe = tmp_path / "Dysnomia64.exe"
    exe.write_text("stub")
    assert resolve_dysnomia_binary(binary_path=str(exe)) == str(exe)


def test_resolve_explicit_missing_returns_none(tmp_path):
    assert resolve_dysnomia_binary(binary_path=str(tmp_path / "nope.exe")) is None


def test_resolve_from_extra_dir_subfolder(tmp_path):
    """extra_search_dirs/<dir>/Dysnomia/<binimage> を探索する。"""
    dysdir = tmp_path / "Dysnomia"
    dysdir.mkdir()
    exe = dysdir / "Dysnomia64.exe"
    exe.write_text("stub")
    got = resolve_dysnomia_binary(
        extra_search_dirs=(str(tmp_path),), binimage="Dysnomia64.exe"
    )
    assert got == str(exe)


def test_resolve_from_extra_dir_direct(tmp_path):
    """extra_search_dirs の直下に置かれた実行ファイルも解決する。"""
    exe = tmp_path / "Dysnomia64.exe"
    exe.write_text("stub")
    got = resolve_dysnomia_binary(
        extra_search_dirs=(str(tmp_path),), binimage="Dysnomia64.exe"
    )
    assert got == str(exe)


def test_resolve_not_found(tmp_path):
    assert resolve_dysnomia_binary(
        extra_search_dirs=(str(tmp_path),), binimage="Nonexistent_zzz.exe"
    ) is None


# ---------------------------------------------------------------------------
# (D) assign_peaks_to_atoms (周期最小像で最近接原子割当・決定論)
# ---------------------------------------------------------------------------


def _cubic_amat(a: float) -> np.ndarray:
    return np.diag([a, a, a]).astype(float)


def test_assign_peaks_nearest_atom_cubic():
    amat = _cubic_amat(10.0)
    atoms = [("Na", 0.0, 0.0, 0.0), ("Cl", 0.5, 0.5, 0.5)]
    peaks = np.array([[0.1, 0.0, 0.0], [0.4, 0.5, 0.5]])
    mags = np.array([5.0, 3.0])
    out = assign_peaks_to_atoms(peaks, mags, atoms, amat)
    assert [p.nearest_atom for p in out] == ["Na", "Cl"]
    assert out[0].distance == pytest.approx(1.0, abs=1e-6)
    assert out[1].distance == pytest.approx(1.0, abs=1e-6)
    # |mag| 降順
    assert out[0].magnitude >= out[1].magnitude


def test_assign_peaks_periodic_min_image():
    """0.95 の peak は 0.0 の原子に (0.5Å) 割り当てられる (周期境界越え)。"""
    amat = _cubic_amat(10.0)
    atoms = [("O", 0.0, 0.0, 0.0)]
    peaks = np.array([[0.95, 0.0, 0.0]])
    mags = np.array([2.0])
    out = assign_peaks_to_atoms(peaks, mags, atoms, amat)
    assert out[0].nearest_atom == "O"
    assert out[0].distance == pytest.approx(0.5, abs=1e-6)


def test_assign_peaks_top_limit_and_sort():
    amat = _cubic_amat(8.0)
    atoms = [("A", 0.0, 0.0, 0.0)]
    peaks = np.array([[0.1, 0, 0], [0.2, 0, 0], [0.05, 0, 0]])
    mags = np.array([1.0, 9.0, -5.0])
    out = assign_peaks_to_atoms(peaks, mags, atoms, amat, top=2)
    assert len(out) == 2
    # |mag| 降順: 9, -5
    assert [round(p.magnitude, 3) for p in out] == [9.0, -5.0]


def test_assign_peaks_empty():
    amat = _cubic_amat(8.0)
    out = assign_peaks_to_atoms(np.empty((0, 3)), np.empty((0,)), [("A", 0, 0, 0)], amat)
    assert out == ()


def test_density_peak_is_frozen():
    p = DensityPeak(frac=(0.0, 0.0, 0.0), magnitude=1.0, nearest_atom="X", distance=0.5)
    with pytest.raises(FrozenInstanceError):
        p.magnitude = 2.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (E) run_dysnomia_mem: バイナリ未検出は MEMUnavailableError へ縮退
# ---------------------------------------------------------------------------


def test_run_raises_when_binary_unavailable(monkeypatch, tmp_path):
    import tsumugin.autorietveld.mem as memmod

    monkeypatch.setattr(memmod, "resolve_dysnomia_binary", lambda **kw: None)
    fake_gpx = tmp_path / "x.gpx"
    fake_gpx.write_text("stub")
    with pytest.raises(MEMUnavailableError):
        run_dysnomia_mem(str(fake_gpx))


def test_run_raises_when_gpx_missing():
    with pytest.raises((FileNotFoundError, MEMUnavailableError, ValueError)):
        run_dysnomia_mem("does_not_exist_zzz.gpx",
                         config=MEMRunConfig(binary_path="also_missing.exe"))


# ---------------------------------------------------------------------------
# (E2) _select_histogram: joint データで density_kind に応じて取り違えない
# ---------------------------------------------------------------------------


class _FakePhase:
    def __init__(self, name):
        self.data = {"General": {"Name": name}}


class _FakeHist:
    def __init__(self, name, pname, rtype, nref):
        self.name = name
        self.data = {"Reflection Lists": {pname: {
            "RefList": list(range(nref)), "Type": rtype}}}


class _FakeProject:
    def __init__(self, phase, hists):
        self._phase = phase
        self._hists = hists

    def phases(self):
        return [self._phase]

    def histograms(self):
        return self._hists


def _joint_project():
    ph = _FakePhase("NaCuHCF")
    xh = _FakeHist("PWDR xray.xye", "NaCuHCF", "PXC", 2000)
    nh = _FakeHist("PWDR nd Bank 1", "NaCuHCF", "PNT", 800)
    return _FakeProject(ph, [xh, nh]), xh, nh


def test_select_histogram_by_wanted_kind_neutron():
    proj, xh, nh = _joint_project()
    _, hist, refl, rtype = _select_histogram(proj, None, None, "nuclear")
    assert hist is nh and rtype == "PNT"


def test_select_histogram_by_wanted_kind_electron():
    proj, xh, nh = _joint_project()
    _, hist, refl, rtype = _select_histogram(proj, None, None, "electron")
    assert hist is xh and rtype == "PXC"


def test_select_histogram_explicit_name_wins():
    proj, xh, nh = _joint_project()
    _, hist, _, _ = _select_histogram(proj, None, "PWDR nd Bank 1", "electron")
    assert hist is nh  # 明示名が density_kind より優先


def test_select_histogram_default_first_with_reflections():
    proj, xh, nh = _joint_project()
    _, hist, _, _ = _select_histogram(proj, None, None, None)
    assert hist is xh


def test_select_histogram_missing_name_raises():
    proj, _, _ = _joint_project()
    with pytest.raises(MEMUnavailableError):
        _select_histogram(proj, None, "PWDR nonexistent", None)


def test_select_histogram_no_matching_kind_raises():
    ph = _FakePhase("X")
    only_xray = _FakeProject(ph, [_FakeHist("h", "X", "PXC", 100)])
    with pytest.raises(MEMUnavailableError):
        _select_histogram(only_xray, None, None, "nuclear")


# ---------------------------------------------------------------------------
# (F) MEMDensityResult 構造
# ---------------------------------------------------------------------------


def test_mem_density_result_frozen():
    dm = MEMDensityMap(path="p.grd", density_kind="nuclear", grid_shape=(4, 4, 4),
                       min_density=-1.0, max_density=5.0)
    r = MEMDensityResult(
        density_map=dm, pre_min=-0.9, pre_max=5.5, n_reflections=800,
        mem_r_factor=2.3, converged=True, density_kind="nuclear", peaks=(), warnings=())
    assert r.density_map.max_density == 5.0
    with pytest.raises(FrozenInstanceError):
        r.converged = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (G) @gsas: 実 Dysnomia MEM smoke (T1 実データで gpx を作り MEM を回す)
# ---------------------------------------------------------------------------

_T1 = Path("docs/benchmark/testdata/m7/labdata")


@pytest.mark.gsas
@pytest.mark.skipif(
    resolve_dysnomia_binary() is None, reason="Dysnomia バイナリ未検出"
)
@pytest.mark.skipif(
    not (_T1 / "FAP.XRA").exists(), reason="M7 T1 データ未取得"
)
def test_real_mem_smoke_electron(tmp_path):
    from tsumugin.autorietveld import (
        Geometry, HistogramSpec, PhaseSpec, Radiation,
    )
    from tsumugin.autorietveld.engine import run_auto_rietveld

    gpx = tmp_path / "t1.gpx"
    hist = HistogramSpec(
        data_path=str(_T1 / "FAP.XRA"),
        instrument_path=str(_T1 / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )
    phase = PhaseSpec(structure_path=str(_T1 / "FAP.EXP"), phase_name="fap",
                      format_hint="EXP")
    run_auto_rietveld([hist], [phase], keep_gpx=str(gpx))

    result = run_dysnomia_mem(str(gpx), config=MEMRunConfig(dmin=1.0, ncyc=500))
    assert isinstance(result, MEMDensityResult)
    assert result.density_kind == "electron"
    assert result.n_reflections > 0
    assert np.isfinite(result.density_map.min_density)
    assert np.isfinite(result.density_map.max_density)
    # 電子密度は正のピーク (原子) を持つ
    assert result.density_map.max_density > 0.0
    assert len(result.peaks) > 0
