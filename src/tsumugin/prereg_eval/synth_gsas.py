"""P0 §6.2: 合成パターンの生成 (GSAS-II の calc-only。GSAS は遅延 import)。

- 装置は生成器の中の**合成の値** (`INSTRUMENT_DEFS`)。準 hold-out の装置ファイルを使わない。
- 相の重量分率は GSAS 自身の定義 (``WgtFrac = Mass·Scale / Σ``, `GSASIIstrMath.calcMassFracs`) に合わせ、
  ``Scale ∝ wt / Mass`` で置く。
- **真値の側**に入れるもの: ゼロ点 (#7)・選択配向 (#10)・モデルの不一致 (非対称・Kα2 比・不純物ピーク・非晶質のこぶ)。
  精密化に渡す装置ファイルは不一致の**無い**側 (= 精密化が知らないずれが真値に入っている)。
- Ycalc に Poisson 雑音を掛けるのは `synth.add_counting_noise` (最大計数の 2 水準)。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .synth import MISMATCHES, add_counting_noise

__all__ = ["INSTRUMENT_DEFS", "SimPhase", "SimResult", "simulate_pattern"]

INSTRUMENT_DEFS: dict[str, dict] = {
    "lab_bb": {
        "radiation": "xray_lab", "geometry": "bragg_brentano",
        "wavelength": 1.540593, "wavelength_ka2": 1.544414, "ka2_ratio": 0.5,
        "tth": (10.0, 120.0, 0.02), "sh_l": 0.002, "background": 200.0,
    },
    "sync_ds": {
        "radiation": "xray_synchrotron", "geometry": "debye_scherrer",
        "wavelength": 0.7, "wavelength_ka2": None, "ka2_ratio": 0.0,
        "tth": (3.0, 50.0, 0.01), "sh_l": 0.002, "background": 100.0,
    },
}

#: 不一致の大きさ (真値の側。生成器と一緒に凍結する)
_TRUE_SH_L = 0.02
_TRUE_KA2_RATIO = 0.45
_IMPURITY_HEIGHT = 0.01
_HUMP_HEIGHT = 0.05
_HUMP_FWHM_DEG = 8.0


@dataclass(frozen=True)
class SimPhase:
    cif_path: str
    phase_name: str
    wt_fraction: float
    preferred_orientation: tuple[float, tuple[int, int, int]] | None = None  # (March–Dollase r, 軸)


@dataclass(frozen=True)
class SimResult:
    xye_path: str
    instprm_path: str
    x: np.ndarray
    y: np.ndarray
    esd: np.ndarray
    ycalc: np.ndarray


def _instprm_text(spec: Mapping, *, sh_l: float, ka2_ratio: float, zero: float) -> str:
    from ..autorietveld.model import Radiation
    from ..instprm import build_instprm_text

    kw: dict = {"radiation": Radiation(spec["radiation"]), "wavelength": spec["wavelength"], "zero": zero,
                "profile": {"SH/L": sh_l}}
    if spec["wavelength_ka2"]:
        kw["wavelength_ka2"] = spec["wavelength_ka2"]
        kw["ka2_ratio"] = ka2_ratio
    return build_instprm_text(**kw)


def _gauss(x: np.ndarray, center: float, fwhm: float) -> np.ndarray:
    sigma = fwhm / 2.354820045
    return np.exp(-0.5 * ((x - center) / sigma) ** 2)


def simulate_pattern(
    phases: Sequence[SimPhase],
    *,
    instrument: str,
    out_dir: str,
    stem: str,
    max_counts: float,
    seed: int,
    zero_deg: float = 0.0,
    mismatches: Sequence[str] = (),
) -> SimResult:
    """真値の相から合成パターンを作り、``<stem>.xye`` と精密化用の ``<stem>.instprm`` を書く。"""
    from GSASII import GSASIIscriptable as G2sc

    spec = INSTRUMENT_DEFS[instrument]
    for m in mismatches:
        if m not in MISMATCHES:
            raise ValueError(f"未登録のモデルの不一致: {m!r}")
    if abs(sum(p.wt_fraction for p in phases) - 1.0) > 1e-6:
        raise ValueError("phase wt fractions must sum to 1")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    true_sh = _TRUE_SH_L if "asymmetry" in mismatches else spec["sh_l"]
    true_ka2 = _TRUE_KA2_RATIO if "kalpha2_ratio" in mismatches else spec["ka2_ratio"]
    truth_prm = out / f"{stem}.truth.instprm"
    truth_prm.write_text(_instprm_text(spec, sh_l=true_sh, ka2_ratio=true_ka2, zero=zero_deg), encoding="utf-8")
    refine_prm = out / f"{stem}.instprm"
    refine_prm.write_text(_instprm_text(spec, sh_l=spec["sh_l"], ka2_ratio=spec["ka2_ratio"], zero=0.0),
                          encoding="utf-8")

    gpx = G2sc.G2Project(newgpx=str(out / f"{stem}.sim.gpx"))
    g2phases = [gpx.add_phase(p.cif_path, phasename=p.phase_name, fmthint="CIF") for p in phases]
    start, stop, step = spec["tth"]
    hist = gpx.add_simulated_powder_histogram(f"{stem}-sim", str(truth_prm), start, stop, Tstep=step,
                                              phases=g2phases)
    masses = [float(ph.data["General"]["Mass"]) for ph in g2phases]
    scales = [p.wt_fraction / m for p, m in zip(phases, masses)]
    top = max(scales)
    for ph, p, s in zip(g2phases, phases, scales):
        hap = ph.data["Histograms"][hist.name]
        hap["Scale"][0] = s / top
        if p.preferred_orientation is not None:
            r, axis = p.preferred_orientation
            hap["Pref.Ori."][0] = "MD"
            hap["Pref.Ori."][1] = float(r)
            hap["Pref.Ori."][3] = list(axis)
    gpx.do_refinements([{}])
    x = np.asarray(hist.getdata("x"), dtype=float)
    ycalc = np.asarray(hist.getdata("ycalc"), dtype=float)

    if "impurity_peak" in mismatches:
        center = float(rng.uniform(x[0] + 0.2 * (x[-1] - x[0]), x[-1] - 0.2 * (x[-1] - x[0])))
        ycalc = ycalc + _IMPURITY_HEIGHT * ycalc.max() * _gauss(x, center, 0.1)
    if "amorphous_hump" in mismatches:
        center = float(x[0] + 0.15 * (x[-1] - x[0]))
        ycalc = ycalc + _HUMP_HEIGHT * ycalc.max() * _gauss(x, center, _HUMP_FWHM_DEG)

    noisy = add_counting_noise(ycalc, max_counts=max_counts, background=spec["background"], seed=seed)
    xye = out / f"{stem}.xye"
    np.savetxt(xye, np.column_stack([x, noisy.y, noisy.esd]), fmt="%.6f")
    return SimResult(str(xye), str(refine_prm), x, noisy.y, noisy.esd, ycalc)
