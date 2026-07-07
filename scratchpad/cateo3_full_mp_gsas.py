"""CaTeO3 フル refinement — MP (delta 自動同定) + GSAS + warm-start B (Issue #28 T6-B)。

同梱 2 フレーム (frame030 alpha 単相 / frame180 alpha+delta 共存) を M9 逐次エンジンで実 GSAS 精密化し、
転移域で **Materials Project から delta 無水 CaTeO3 を自動同定・物質化・追加**する。warm-start B
(PhaseIdConfig.warm_start_known_phases=True) で現行相 alpha を精密化格子付きで先に残差減算してから
新相を探す。MP キーは .env から読み込む。GSAS 実行 (数分)。
"""
from __future__ import annotations

import os
from pathlib import Path


def _load_env():
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

from tsumugin.autorietveld.model import Geometry, PhaseSpec, Radiation  # noqa: E402
from tsumugin.insitu import (  # noqa: E402
    FrameSpec,
    PhaseIdConfig,
    SequentialConfig,
    make_gsas_runner,
    run_sequential_rietveld,
)

_CATEO3 = Path("docs/benchmark/testdata/m9/cateo3")
_INSTR = _CATEO3 / "cateo3_CuKa.instprm"


def main(warm_start: bool):
    frames = [
        FrameSpec(str(_CATEO3 / "NB-LM01MO_030.XRDML"), axis_value=30.0,
                  data_format="XRDML", two_theta_limits=(12.0, 70.0)),
        FrameSpec(str(_CATEO3 / "NB-LM01MO_180.XRDML"), axis_value=180.0,
                  data_format="XRDML", two_theta_limits=(12.0, 70.0)),
    ]
    alpha = PhaseSpec(str(_CATEO3 / "alpha_CaTeO3_H2O.cif"), "alpha", format_hint="CIF")
    runner = make_gsas_runner(
        instrument_path=str(_INSTR), radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO, max_cyc=20, background_coeffs=24,
    )
    pid = PhaseIdConfig(
        elements=("Ca", "Te", "O"),
        top_k=3,                      # MP に CaTeO3 は複数多形 → 全試行し最良 Rietveld を採る
        frac_min=0.02,
        min_rwp_gain=0.01,
        refine_new_phase_cell=True,   # Issue #20: DFT 異方格子誤差を Pawley プリアラインで補正
        require_full_element_system=True,
        snr_trigger=20.0,
        warm_start_known_phases=warm_start,  # ← B 検証スイッチ
    )
    tag = "B(warm-start)" if warm_start else "A(static)"
    print(f"\n########## CaTeO3 full MP+GSAS refinement — {tag} ##########", flush=True)
    res = run_sequential_rietveld(
        frames, [alpha], runner=runner,
        config=SequentialConfig(warm_start=True, phase_id=pid),
    )
    print(f"\n===== 結果 ({tag}) =====", flush=True)
    for f in res.frames:
        print(f"  frame {f.frame_index} (axis={f.axis_value}): Rwp={f.rwp:.2f}% GOF={f.gof:.2f} "
              f"phases={list(f.phase_names)} fracs={ {k: round(v,3) for k,v in f.phase_fractions.items()} } "
              f"validity={f.validity_passed} changepoint={f.changepoint}", flush=True)
    print(f"  appearances (自動採用新相): {[(a.phase_name, a.frame_index, a.source, a.evidence.get('phase_id'), a.evidence.get('formula')) for a in res.appearances]}", flush=True)
    print(f"  warnings: {list(res.warnings)}", flush=True)
    print(f"  ledger.verify(): {res.ledger.verify()}", flush=True)
    return res


if __name__ == "__main__":
    import sys

    warm = "--static" not in sys.argv
    main(warm)
