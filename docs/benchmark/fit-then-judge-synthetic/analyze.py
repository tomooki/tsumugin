"""S-dev の結果を manifest の「期待する検出器の結果」と突き合わせる (P1.5 の調整で読む)。

    uv run python docs/benchmark/fit-then-judge-synthetic/analyze.py

事例ごとに、テンプレート (`T-AB`) と基準 (`B-AB`) について:
- 対照: blocking な判断要求が出ないこと・出版できる値の割合
- 要求で検出する欠陥 (#1 席の取り違え・#2 原子の欠落・#5 欠落相・#8 副相の格子の凍結): 対応する要求が出たか
- 回復で見る欠陥 (#3 混合占有の比・#4 変位・#6 格子・#9 極性の並進): 真値に戻ったか (座標 0.02 Å・占有率 0.02・格子 1e-3)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cases import CASES  # noqa: E402

from tsumugin.autorietveld.cif_normalize import read_structure_cif  # noqa: E402
from tsumugin.prereg_eval.defects import lattice_matrix  # noqa: E402

_REQUEST_FOR = {1: "crystal_chemistry", 2: "phase_set_completeness", 5: "phase_set_completeness", 8: "frozen_cell"}


def _blocking(arm: dict) -> set[str]:
    c = arm.get("claims") or {}
    return {str(r["kind"]).split(":")[0] for r in c.get("requests", []) if r.get("blocking")}


def _recovered(kind: int, target: str, arm: dict, truth_dir: Path) -> str:
    compound, _, rest = target.split(" ")[0].partition(".")
    truth = read_structure_cif(truth_dir / f"truth_{compound}.cif")
    lat = lattice_matrix(truth)
    coords = (arm.get("atom_coords") or {}).get(compound, {})
    if kind in (4,):
        t = next(a for a in truth.atoms if a.label == rest)
        f = coords.get(rest)
        if f is None:
            return "no value"
        d = float(np.linalg.norm((np.array(f) - np.array([t.x, t.y, t.z])) @ lat))
        return f"{'recovered' if d <= 0.02 else 'NOT recovered'} (|dr|={d:.3f} A)"
    if kind == 3:
        occ = (arm.get("atom_occupancy") or {}).get(compound, {})
        n = rest[1:]
        t = next(a for a in truth.atoms if a.label == f"Mg{n}").occ
        f = occ.get(f"Mg{n}")
        if f is None:
            return "no value"
        return f"{'recovered' if abs(f - t) <= 0.02 else 'NOT recovered'} (occ {f:.3f} vs {t:.3f})"
    if kind == 6:
        cell = (arm.get("refined_cells") or {}).get(compound)
        if cell is None:
            return "no value"
        rel = max(abs(c / t - 1) for c, t in zip(cell[:3], (truth.a, truth.b, truth.c)))
        return f"{'recovered' if rel <= 1e-3 else 'NOT recovered'} (max rel {rel:.2e})"
    if kind == 9:
        dz = [coords[a.label][2] - a.z for a in truth.atoms if a.label in coords]
        dz = [(v + 0.5) % 1.0 - 0.5 for v in dz]
        spread = (max(dz) - min(dz)) * truth.c if dz else float("nan")
        return f"{'same modulo translation' if spread <= 0.02 else 'DIFFERENT'} (spread {spread:.3f} A)"
    return "-"


def main() -> int:
    for case in CASES:
        f = HERE / "results" / "arms" / f"{case.case_id}.json"
        if not f.exists():
            print(f"== {case.case_id}: (no result)")
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        print(f"== {case.case_id}  defects={[k for k, _ in case.defects]} mismatches={list(case.mismatches)}")
        for arm_name in ("B-AB", "T-AB", "B-single", "T-single"):
            arm = (d.get("arms") or {}).get(arm_name)
            if not arm:
                continue
            c = arm.get("claims") or {}
            line = (f"  {arm_name:9s} fail={arm['failed']!s:5s} rwp={arm.get('rwp') or 0:6.2f} "
                    f"pub {c.get('n_publishable')}/{c.get('n_values')} blocking={sorted(_blocking(arm))}")
            for kind, target in case.defects:
                if kind in _REQUEST_FOR:
                    hit = _REQUEST_FOR[kind] in _blocking(arm)
                    line += f" | #{kind} {'DETECTED' if hit else 'missed'}"
                elif kind in (3, 4, 6, 9):
                    line += f" | #{kind} {_recovered(kind, target, arm, HERE / 'results' / case.case_id)}"
                else:
                    line += f" | #{kind} (see requests)"
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
