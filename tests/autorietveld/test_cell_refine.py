"""異方単位格子精密化 (autorietveld.cell_refine) のテスト (Issue #20)。

- import はコア (numpy) のみ (GSAS/pymatgen を引き込まない): 遅延 import 契約。
- `_first_hkl` の純ロジック (numpy 非依存)。
- `prealign_cell_from_structure` (pymatgen 必要, @pytest.mark.mp): 異方的に c を +3.4% ずらした
  参照構造から、真構造の観測ピークへ整合させて c を復元する (Issue #20 の核心を合成で検証)。
- `refine_structure_cell` の GSAS セル研磨経路は @pytest.mark.gsas (実データ検証は engine テスト側)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from tsumugin.autorietveld.cell_refine import (
    CellRefinementResult,
    _first_hkl,
    prealign_cell_from_structure,
    refine_structure_cell,
)

_DELTA_CIF = Path("docs/benchmark/testdata/m9/cateo3/delta_CaTeO3.cif")
_HAS_PYMATGEN = importlib.util.find_spec("pymatgen") is not None


def test_first_hkl_from_xrdcalculator_entry():
    # XRDCalculator の hkls エントリ形式: list[dict{'hkl':(h,k,l), 'multiplicity':m}]
    assert _first_hkl([{"hkl": (1, 0, 2), "multiplicity": 2}]) == (1, 0, 2)
    # 素の tuple 列でも先頭を取る
    assert _first_hkl([(2, 1, 1)]) == (2, 1, 1)


def test_first_hkl_rejects_empty():
    with pytest.raises(ValueError):
        _first_hkl([])


def test_cell_refinement_result_defaults():
    r = CellRefinementResult(
        cell=(1, 2, 3, 90, 90, 90), rwp=float("inf"), converged=False,
        method="none", n_matched=0,
    )
    assert r.prealign_cell is None


def _synthetic_observed(structure, *, wavelength=1.5406, rng=(10.0, 80.0), width=0.05):
    """真構造から合成観測パターン (真ピーク位置にガウシアン) を作る。"""
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    calc = XRDCalculator(wavelength=wavelength)
    pat = calc.get_pattern(structure, scaled=True, two_theta_range=rng)
    tt = np.linspace(rng[0], rng[1], 8000)
    inten = np.zeros_like(tt)
    for x, y in zip(pat.x, pat.y):
        inten += float(y) * np.exp(-0.5 * ((tt - float(x)) / width) ** 2)
    return tt, inten


@pytest.mark.mp
@pytest.mark.skipif(not _DELTA_CIF.exists(), reason="delta CIF 未配置")
def test_prealign_recovers_anisotropic_c_error():
    """c を +3.4% ずらした参照構造を、真構造の観測ピークへ整合させて c を復元する。"""
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    true = Structure.from_file(str(_DELTA_CIF))
    true_c = true.lattice.c

    tt, inten = _synthetic_observed(true)

    # c を +3.4% 過大にした DFT 相当構造を書き出す (分率座標は保持)
    lat = true.lattice
    pert = Structure(
        Lattice.from_parameters(lat.a, lat.b, lat.c * 1.034, lat.alpha, lat.beta, lat.gamma),
        true.species,
        true.frac_coords,
    )
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        pert_cif = str(Path(tmp) / "pert.cif")
        CifWriter(pert).write_file(pert_cif)

        sol = prealign_cell_from_structure(pert_cif, tt, inten, two_theta_range=(10.0, 80.0))

    assert sol is not None
    assert sol.crystal_system == "orthorhombic"
    # プリアラインの目標: c 誤差 3.4% を Rietveld/LeBail 収束半径 (~2%) 内へ落とし込む。
    # 摂動 13.77 → 真 13.32 (誤差 <2% = <0.27) かつ摂動値より確実に改善 (LeBail が残差を仕上げる)。
    assert abs(sol.cell[2] - true_c) < 0.27, f"c={sol.cell[2]} vs true {true_c}"
    assert sol.cell[2] < lat.c * 1.034 - 0.2  # 摂動値 (13.77) より明確に縮んでいる
    # a,b は元々ほぼ正しいので大きく動かさない
    assert abs(sol.cell[0] - lat.a) < 0.1
    assert abs(sol.cell[1] - lat.b) < 0.1


@pytest.mark.mp
@pytest.mark.skipif(not _DELTA_CIF.exists(), reason="delta CIF 未配置")
def test_prealign_deterministic():
    from pymatgen.core import Structure

    true = Structure.from_file(str(_DELTA_CIF))
    tt, inten = _synthetic_observed(true)
    s1 = prealign_cell_from_structure(str(_DELTA_CIF), tt, inten, two_theta_range=(10.0, 80.0))
    s2 = prealign_cell_from_structure(str(_DELTA_CIF), tt, inten, two_theta_range=(10.0, 80.0))
    assert s1 == s2


@pytest.mark.mp
@pytest.mark.skipif(not _DELTA_CIF.exists(), reason="delta CIF 未配置")
def test_prealign_returns_none_on_no_peaks():
    tt = np.linspace(10.0, 80.0, 2000)
    inten = np.zeros_like(tt)  # ピークなし
    sol = prealign_cell_from_structure(str(_DELTA_CIF), tt, inten)
    assert sol is None


def test_refine_structure_cell_is_callable():
    assert callable(refine_structure_cell)


_ALPHA_CIF = Path("docs/benchmark/testdata/m9/cateo3/alpha_CaTeO3_H2O.cif")
_FRAME = Path("docs/benchmark/testdata/m9/cateo3/NB-LM01MO_030.XRDML")
_INSTR = Path("docs/benchmark/testdata/m9/cateo3/cateo3_CuKa.instprm")


@pytest.mark.gsas
@pytest.mark.mp
@pytest.mark.skipif(
    not (_ALPHA_CIF.exists() and _FRAME.exists() and _INSTR.exists()),
    reason="CaTeO3 検証データ未配置",
)
def test_refine_structure_cell_recovers_mp_like_anisotropic_error_on_real_data():
    """MP-DFT 相当の異方誤差 (a+0.4%, b+0.8%, c+3.4%) を実測 frame030 で真セルへ回復する。

    Issue #20 の受理基準の忠実な代理: alpha を delta と同じ誤差プロファイルで摂動し、実データから
    numpy プリアライン + GSAS 平坦セル研磨で回復できることを検証する (LeBail 発散を回避した安定経路)。
    """
    import tempfile

    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    from tsumugin.reference.io import load_xrdml

    tt, inten = load_xrdml(str(_FRAME))
    true = Structure.from_file(str(_ALPHA_CIF))
    lat = true.lattice

    with tempfile.TemporaryDirectory() as d:
        pert = Structure(
            Lattice.from_parameters(
                lat.a * 1.004, lat.b * 1.008, lat.c * 1.034, lat.alpha, lat.beta, lat.gamma
            ),
            true.species,
            true.frac_coords,
        )
        pcif = str(Path(d) / "pert.cif")
        CifWriter(pert).write_file(pcif)
        xye = str(Path(d) / "f.xye")
        esd = np.sqrt(np.clip(inten, 1.0, None))
        with open(xye, "w") as fh:
            for x, y, e in zip(tt, inten, esd):
                fh.write(f"{x:.6f} {y:.4f} {e:.4f}\n")

        res = refine_structure_cell(
            pcif, xye, str(_INSTR), data_format="XYE", two_theta_limits=(12.0, 70.0),
            background_coeffs=24, max_cyc=15,
            prealign_two_theta=tt, prealign_intensity=inten,
        )

    # c 誤差 3.4% (0.50 Å) → <0.5% (0.07 Å) へ回復。格子は崩壊していない。
    assert abs(res.cell[2] - lat.c) < 0.07, f"c={res.cell[2]} vs true {lat.c}"
    assert abs(res.cell[0] - lat.a) < 0.05
    assert abs(res.cell[1] - lat.b) < 0.05
    assert res.prealign_cell is not None
    assert res.method in ("prealign+cell", "prealign")  # 発散して none に落ちていない
