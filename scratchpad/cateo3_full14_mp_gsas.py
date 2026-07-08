"""CaTeO3 全 14 フレーム フル refinement — MP (delta 自動同定) + GSAS + warm-start B (Issue #28 ①)。

Jana2020 Cookbook Example 02.6 "CaTeO3 cyclic" の全 14 フレーム (NB-LM01MO_030〜_420, 昇温→降温)
を M9 逐次エンジンで実 GSAS 精密化。alpha (含水) が昇温で脱水し転移域 (frame150–300) で **MP から
delta 無水 CaTeO3 を自動同定・物質化・追加**。warm-start B (現行相を精密化格子付きで先に残差減算)
の弱 minority 域での検出感度を測る。

XRDML は scratchpad/cateo3_frames14/ に Data.zip から展開済 (gitignore)。CIF/instprm はリポジトリ同梱。
MP キーは .env。GSAS 実行 (数十分)。usage: python cateo3_full14_mp_gsas.py [--static] [--maxframes N]
"""
from __future__ import annotations

import os
import sys
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

_CATEO3 = Path("docs/benchmark/testdata/m9/cateo3")     # CIF + instprm (同梱)
_FRAMES = Path("scratchpad/cateo3_frames14")            # 14 XRDML (Data.zip 展開)
_INSTR = _CATEO3 / "cateo3_CuKa.instprm"
_AXES = list(range(30, 421, 30))  # 30,60,...,420 (14 フレーム)


def main(warm_start: bool, max_frames: int | None, consolidate: bool = True,
         max_cyc: int = 20, top_k: int = 3, phaseid: bool = True):
    frame_paths = sorted(_FRAMES.glob("NB-LM01MO_*.XRDML"))
    assert len(frame_paths) == 14, f"14 フレーム必要, got {len(frame_paths)}"
    frames = [
        FrameSpec(str(p), axis_value=float(ax), data_format="XRDML",
                  two_theta_limits=(12.0, 70.0))
        for p, ax in zip(frame_paths, _AXES)
    ]
    if max_frames:
        frames = frames[:max_frames]
    alpha = PhaseSpec(str(_CATEO3 / "alpha_CaTeO3_H2O.cif"), "alpha", format_hint="CIF")
    runner = make_gsas_runner(
        instrument_path=str(_INSTR), radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO, max_cyc=max_cyc, background_coeffs=24,
    )
    pid = PhaseIdConfig(
        elements=("Ca", "Te", "O"), top_k=top_k, frac_min=0.02, min_rwp_gain=0.01,
        refine_new_phase_cell=True, require_full_element_system=True, snr_trigger=20.0,
        warm_start_known_phases=warm_start,
    )
    tag = ("B(warm-start)" if warm_start else "A(static)") + ("" if phaseid else " [no-phaseid]")
    print(f"\n########## CaTeO3 full-14 MP+GSAS — {tag} (n={len(frames)}) ##########", flush=True)
    res = run_sequential_rietveld(
        frames, [alpha], runner=runner,
        config=SequentialConfig(warm_start=True, phase_id=pid if phaseid else None,
                                backward_propagation=consolidate),
    )
    print(f"\n===== 結果 ({tag}) =====", flush=True)
    for f in res.frames:
        fr = {k: round(v, 3) for k, v in f.phase_fractions.items()}
        print(f"  f{f.frame_index:02d} ax={f.axis_value:.0f}: Rwp={f.rwp:6.2f}% GOF={f.gof:5.2f} "
              f"phases={list(f.phase_names)} fr={fr} valid={f.validity_passed} "
              f"cp={f.changepoint} failed={f.refine_failed}", flush=True)
    print("\n  --- appearances (自動採用新相) ---", flush=True)
    for a in res.appearances:
        print(f"    {a.phase_name} @f{a.frame_index}(ax={a.axis_value:.0f}) src={a.source} "
              f"id={a.evidence.get('phase_id')} formula={a.evidence.get('formula')} "
              f"Rwp {a.rwp_before:.1f}->{a.rwp_after:.1f}", flush=True)
    print(f"  warnings: {list(res.warnings)}", flush=True)
    print(f"  ledger.verify(): {res.ledger.verify()}", flush=True)
    # delta 転移サマリ
    delta_frames = [f.axis_value for f in res.frames if "new_CaTeO3" in f.phase_names]
    print(f"  >>> delta 存在フレーム軸: {delta_frames}", flush=True)
    return res


if __name__ == "__main__":
    warm = "--static" not in sys.argv
    consolidate = "--no-consolidate" not in sys.argv
    mf = None
    if "--maxframes" in sys.argv:
        mf = int(sys.argv[sys.argv.index("--maxframes") + 1])
    mc = int(sys.argv[sys.argv.index("--maxcyc") + 1]) if "--maxcyc" in sys.argv else 20
    tk = int(sys.argv[sys.argv.index("--topk") + 1]) if "--topk" in sys.argv else 3
    pi = "--no-phaseid" not in sys.argv
    main(warm, mf, consolidate, max_cyc=mc, top_k=tk, phaseid=pi)
