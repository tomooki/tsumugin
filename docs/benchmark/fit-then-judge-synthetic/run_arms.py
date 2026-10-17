"""合成 `S-dev` の全事例に P0 §1.1 の全アームを回し、結果を `results/arms/<case>.json` に書く (P1.5 の調整用)。

    uv run python docs/benchmark/fit-then-judge-synthetic/run_arms.py [--only <case_id>] [--n-starts 5]

`generate.py` が作ったパターン (`results/<case>/`) を使う。記録するもの: アームごとの失敗・χ²・観測集合のハッシュ・
事後の収束検査・背景項数・段の並び・f・b・テンプレートと基準経路の出版状態 (claims の要約と判断要求)。
P0 §3.1 により S-dev は開発用 (P1・P1.5 で自由に使ってよい)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cases import CASES  # noqa: E402

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation  # noqa: E402

_INSTR = {
    "lab_bb": (Radiation.XRAY_LAB, Geometry.BRAGG_BRENTANO),
    "sync_ds": (Radiation.XRAY_SYNCHROTRON, Geometry.DEBYE_SCHERRER),
}


def _case_inputs(case, results: Path):
    d = results / case.case_id
    rad, geo = _INSTR[case.instrument]
    hist = HistogramSpec(data_path=str(d / f"{case.case_id}.xye"), instrument_path=str(d / f"{case.case_id}.instprm"),
                         radiation=rad, geometry=geo, data_format="XYE")
    phases = []
    for p in json.loads((d / "phases.json").read_text(encoding="utf-8")):
        groups = tuple(tuple(g) for g in p.get("mixed_occupancy_groups", ()))
        phases.append(PhaseSpec(p["structure_path"], p["phase_name"], refine_cell=p["refine_cell"],
                                mixed_occupancy_groups=groups))
    return hist, phases


def _summary(run, outcome, claims_state):
    res = run.result
    return {
        "error": run.error, "same_as": run.same_as, "failed": outcome.failed, "failure_reason": outcome.failure_reason,
        "chi2": outcome.chi2, "obs_hash": outcome.obs_hash, "rwp": getattr(res, "final_rwp", None),
        "posthoc_shift_esd": run.posthoc_shift_esd, "background_coeffs": run.background_coeffs,
        "stages": list(run.stage_labels), "fail_count": outcome.fail_count, "short_bonds": outcome.short_bonds,
        "refined_cells": getattr(res, "refined_cells", None),
        "atom_coords": getattr(res, "atom_coords", None),
        "atom_occupancy": getattr(res, "atom_occupancy", None),
        "phase_weight_fractions": getattr(res, "phase_weight_fractions", None),
        "claims": claims_state,
    }


def _claims(run):
    from tsumugin.claims.publication import publication_state

    if run.result is None:
        return None
    st = publication_state(run.result, list(run.phases), multistart=run.multistart, derivation=run.derivation)
    claims = st.get("claims") or {}
    return {
        "error": st.get("error"),
        "n_values": len(claims), "n_publishable": sum(1 for c in claims.values() if c.get("publishable")),
        "requests": [{"id": r.get("id"), "kind": r.get("kind"), "blocking": r.get("blocking"),
                      "trigger": r.get("trigger")} for r in st.get("judgment_requests") or ()],
        "determinacy": {k: c.get("determinacy") for k, c in claims.items()},
    }


def run_case(case, results: Path, n_starts: int) -> dict:
    from tsumugin.prereg_eval.adapter import outcome_from_result, posthoc_converged
    from tsumugin.prereg_eval.arms import run_arms
    from tsumugin.template.declarations import TemplateDeclarations

    hist, phases = _case_inputs(case, results)
    main = max((pd for pd in case.phases if pd.in_model), key=lambda pd: pd.wt).compound
    decl = TemplateDeclarations.from_dict({"target_phase": main})
    t0 = time.time()
    arms = run_arms([hist], phases, decl, n_starts=n_starts, run_kwargs={"gpx_dir": str(results / "arms_gpx" / case.case_id)})
    out = {"case_id": case.case_id, "seconds": round(time.time() - t0, 1), "arms": {}}
    for name, run in arms.items():
        if run is None:
            out["arms"][name] = None
            continue
        oc = outcome_from_result(run.result, histograms=run.histograms, phases=run.phases, error=run.error,
                                 posthoc_converged=posthoc_converged(run.posthoc_shift_esd))
        out["arms"][name] = _summary(run, oc, _claims(run) if name in ("B-AB", "T-AB", "T-single", "B-single") else None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--n-starts", type=int, default=5)
    args = ap.parse_args()
    results = HERE / "results"
    (results / "arms").mkdir(parents=True, exist_ok=True)
    for case in CASES:
        if args.only and case.case_id != args.only:
            continue
        try:
            rec = run_case(case, results, args.n_starts)
        except Exception as exc:  # noqa: BLE001 — 1 事例の失敗で全体を止めない (記録して次へ)
            rec = {"case_id": case.case_id, "error": f"{type(exc).__name__}: {exc}"}
        (results / "arms" / f"{case.case_id}.json").write_text(
            json.dumps(rec, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        print(case.case_id, rec.get("seconds"), rec.get("error", ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
