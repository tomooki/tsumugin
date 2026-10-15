"""`run_arms.py` の結果を事例 × アームの表にする (P1.5 の調整で読む)。

    uv run python docs/benchmark/fit-then-judge-synthetic/summarize.py [case_id ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    files = sorted((HERE / "results" / "arms").glob("*.json"))
    if argv:
        files = [f for f in files if f.stem in argv]
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        print(f"== {d['case_id']}  ({d.get('seconds')} s) {d.get('error', '')}")
        for name, v in (d.get("arms") or {}).items():
            if v is None:
                print(f"  {name:24s} (not run)")
                continue
            c = v.get("claims")
            pub = "" if not c else f" pub {c['n_publishable']}/{c['n_values']} req {sorted({r['kind'] for r in c['requests'] if r['blocking']})}"
            rwp = v.get("rwp")
            print(f"  {name:24s} fail={v['failed']!s:5s} rwp={'-' if rwp is None else f'{rwp:6.2f}'} "
                  f"posthoc={v.get('posthoc_shift_esd')} bkg={v.get('background_coeffs')} f={v.get('fail_count')} "
                  f"b={v.get('short_bonds')}{pub} {v.get('failure_reason', '')[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
