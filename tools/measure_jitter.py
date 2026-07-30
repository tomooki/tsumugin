"""座標摂動の既定量を**実測で**決めるための掃引 (Phase B §4-1)。

良い既定の条件は 2 つあり、両方を測らないと決められない:

1. **構造ベイスンを実際に探れている** — 小さすぎると全開始点が同じ点へ戻るだけで、
   「試験した」ことにならない (格子だけの試験と変わらない)。
2. **壊れない** — 大きすぎると発散・validity fail・別構造への落下が起き、
   「収束しなかった」のか「無茶な初期値を与えた」のか切り分けられなくなる。

各振幅について ``n_basins`` / 発散数 / validity fail 数 / Rwp のばらつき / どのクラスが
割れたかを出す。**判断材料を出すだけで既定値は決め打ちしない** (数字を見てから決める)。

    uv run python tools/measure_jitter.py --dataset T1 --recipe polish
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "tools"))

#: BLAS を 1 スレッドへ (子が継承する)。理由は `multistart._pinned_blas_threads` を参照。
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

from _bench_one import _build, _specs  # noqa: E402 — sys.path 調整後
from bench_specs import RECIPE_REGISTRY  # noqa: E402


def main(argv: "list[str] | None" = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default="T1")
    ap.add_argument("--recipe", default="A6-polish", choices=list(RECIPE_REGISTRY))
    ap.add_argument("--n-starts", type=int, default=5)
    ap.add_argument("--lattice-frac", type=float, default=0.007)
    ap.add_argument("--jitter", type=float, nargs="*",
                    default=[0.0, 0.02, 0.05, 0.10, 0.20])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    from tsumugin.autorietveld.model import StabilityOptions
    from tsumugin.autorietveld.multistart import run_multistart_rietveld
    from tsumugin.multistart.perturb import MultistartConfig, PerturbationSpec

    build = RECIPE_REGISTRY[args.recipe]
    hists, phases, bg, max_cyc = _specs(args.dataset)
    recipe, hists = _build(build, hists, phases, bg)
    stability = StabilityOptions(**build.stability) if build.stability else None
    cfg = MultistartConfig(
        n_starts=args.n_starts, spec=PerturbationSpec(lattice_frac=args.lattice_frac)
    )

    rows = []
    print(f"# {args.dataset} / {args.recipe} / n_starts={args.n_starts} "
          f"/ lattice ±{args.lattice_frac:.3%}", flush=True)
    for amp in args.jitter:
        t0 = time.time()
        kwargs: dict = {"max_cyc": max_cyc, "recipe": recipe}
        if stability is not None:
            kwargs["stability"] = stability
        res = run_multistart_rietveld(
            hists, phases, config=cfg, coord_jitter_ang=float(amp),
            jobs=args.n_starts, **kwargs,
        )
        valid = [s for s in res.starts if s.result is not None and s.result.validity.passed]
        classes = {}
        if res.agreement is not None and res.agreement.pairs:
            for c in res.agreement.pairs[0].classes:
                if c.n_compared:
                    classes[c.param_class] = c.verdict
        row = {
            "jitter_ang": float(amp),
            "seconds": round(time.time() - t0, 1),
            "n_axes_moved": res.n_axes_jittered,
            "n_basins": res.n_basins,
            "n_diverged": res.n_diverged,
            "n_invalid": len(res.starts) - len(valid) - res.n_diverged,
            "rwp_spread": round(res.rwp_spread, 4),
            "best_rwp": round(res.best.final_rwp, 5) if res.best else None,
            "corroborated": res.is_global_corroborated,
            "reason": res.corroboration_reason,
            "classes": classes,
        }
        rows.append(row)
        print(
            f"  jitter={amp:<5} axes={row['n_axes_moved']:<4} basins={row['n_basins']} "
            f"div={row['n_diverged']} invalid={row['n_invalid']} "
            f"spread={row['rwp_spread']:<8} best={row['best_rwp']} "
            f"{row['reason']:<28} {classes} ({row['seconds']}s)",
            flush=True,
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"dataset": args.dataset, "recipe": args.recipe, "rows": rows},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
