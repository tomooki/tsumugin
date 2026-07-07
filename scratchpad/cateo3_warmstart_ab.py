"""CaTeO3 実データ warm-start A/B 検証 (Issue #28 T6-B, MP/GSAS 非依存)。

同梱 2 フレーム (frame030 alpha 単相 / frame180 alpha+delta 共存) の実 XRDML に対し、
identify_pattern を (A) 静的 known_phases=() と (B) warm-start known_phases=[alpha] で走らせ、
delta 検出・残差 S/N を比較する。参照供給元は同梱 delta/alpha CIF (UserCIFProvider) で MP を回避。

pymatgen のみ (CIF→ピーク)。GSAS 不要 (numpy 同定コア)。
"""
from __future__ import annotations

import numpy as np

from tsumugin.insitu.phaseid import phasespec_to_reference
from tsumugin.autorietveld.model import PhaseSpec
from tsumugin.reference.io import load_xrdml
from tsumugin.reference.iterative import IdentifyConfig, identify_pattern
from tsumugin.reference.providers import UserCIFProvider
from tsumugin.reference.significance import residual_significance

BASE = "docs/benchmark/testdata/m9/cateo3"
ALPHA_CIF = f"{BASE}/alpha_CaTeO3_H2O.cif"
DELTA_CIF = f"{BASE}/delta_CaTeO3.cif"
F030 = f"{BASE}/NB-LM01MO_030.XRDML"  # alpha 単相域
F180 = f"{BASE}/NB-LM01MO_180.XRDML"  # alpha+delta 共存域
WAVELENGTH = 1.5406  # Cu Kα1 単色 (instprm)
ELEMENTS = ["Ca", "Te", "O"]

# 実データ用 cfg: SNIP 背景減算 + auto_fwhm。装置ピーク幅 ~0.056° と narrow なので fwhm 初期値も下げる。
CFG = IdentifyConfig(
    snr_stop=8.0, subtract_bg=True, auto_fwhm=True, fwhm=0.08,
    refine_lattice=True, max_strain=0.02, try_k=3,
)


def _delta_provider() -> UserCIFProvider:
    # alpha + delta 両方を候補に供給 (静的パスが両相を同定できるように)。
    return UserCIFProvider.from_files([ALPHA_CIF, DELTA_CIF], wavelength_angstrom=WAVELENGTH,
                                      two_theta_range=(5.0, 90.0))


def _alpha_ref():
    spec = PhaseSpec(structure_path=ALPHA_CIF, phase_name="alpha", format_hint="CIF")
    return phasespec_to_reference(spec, wavelength=WAVELENGTH, two_theta_range=(5.0, 90.0))


def _run(label: str, path: str, known):
    tt, inten = load_xrdml(path)
    prov = _delta_provider()
    res = identify_pattern(tt, inten, prov, elements=ELEMENTS, known_phases=known, cfg=CFG)
    ids = [a.phase_id for a in res.accepted]
    formulas = [a.formula for a in res.accepted]
    print(f"\n=== {label} | {path.split('/')[-1]} | known={[k.phase_id for k in known]} ===")
    print(f"  2θ range: {tt.min():.2f}–{tt.max():.2f}, n={tt.size}, max counts={inten.max():.0f}")
    print(f"  accepted: {list(zip(ids, formulas))}")
    print(f"  scales  : {[round(a.scale, 4) for a in res.accepted]}")
    print(f"  final residual max S/N: {res.final_max_snr:.1f}")
    delta_found = any('CaTeO3' == f for f in formulas)
    # delta = 無水 CaTeO3 (Ca8Te8O24); alpha は CaTeO4 相当 (含水, O 過剰)
    print(f"  >>> delta (CaTeO3) 検出: {delta_found}")
    return res


def main():
    alpha_ref = _alpha_ref()
    print(f"alpha_ref peaks: {len(alpha_ref.peaks) if alpha_ref else 'None'}, "
          f"formula={alpha_ref.formula if alpha_ref else None}")

    # --- 負のコントロール: frame030 (alpha 単相) ---
    _run("A 静的  ", F030, known=())
    _run("B warm  ", F030, known=[alpha_ref])

    # --- 正のコントロール: frame180 (alpha+delta 共存) ---
    _run("A 静的  ", F180, known=())
    _run("B warm  ", F180, known=[alpha_ref])


if __name__ == "__main__":
    main()
