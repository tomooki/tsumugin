"""P1.5 段階 2: 開発に使ってよい公開チュートリアルで全アームを回す (P0 §3.1 の注・§8-6)。

**これを走らせた後に P0 の数・規則を変えると、結果は in-sample と表示される** (P0 §8-6)。使った化合物は「開発用の
化合物」として H-pub の候補から除く (`fit-then-judge-hpub/candidates.py` の ``DEV_COMPOUNDS`` に既にある)。

アームの実行と要約は合成 `S-dev` と同じ (`fit-then-judge-synthetic/run_arms.py` の `_summary`/`_claims`)。
入力は GSAS-II 公式チュートリアルのデータ (`docs/benchmark/testdata/`, 取得手順はそこの README)。

    python run_tutorial.py --testdata <docs/benchmark/testdata> [--only garnet] [--n-starts 5]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "fit-then-judge-synthetic"))

from run_arms import _claims, _summary  # noqa: E402

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation  # noqa: E402


def _garnet(td: Path):
    d = td / "m7" / "cwneutron"
    hist = HistogramSpec(data_path=str(d / "garnet.raw"), instrument_path=str(d / "inst_d1a.prm"),
                         radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER, data_format="GSAS")
    phase = PhaseSpec(str(d / "garnet_YFeAlO.cif"), "garnet", mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")))
    return [hist], [phase], "garnet"


CASES = {"garnet": _garnet}


def run_case(name: str, td: Path, results: Path, n_starts: int) -> dict:
    from tsumugin.prereg_eval.adapter import outcome_from_result, posthoc_converged
    from tsumugin.prereg_eval.arms import run_arms
    from tsumugin.template.declarations import TemplateDeclarations

    hists, phases, target = CASES[name](td)
    decl = TemplateDeclarations.from_dict({"target_phase": target})
    t0 = time.time()
    arms = run_arms(hists, phases, decl, n_starts=n_starts, run_kwargs={"gpx_dir": str(results / "arms_gpx" / name)})
    out = {"case_id": name, "seconds": round(time.time() - t0, 1), "arms": {}}
    for arm, run in arms.items():
        if run is None:
            out["arms"][arm] = None
            continue
        oc = outcome_from_result(run.result, histograms=run.histograms, phases=run.phases, error=run.error,
                                 posthoc_converged=posthoc_converged(run.posthoc_shift_esd))
        out["arms"][arm] = _summary(run, oc, _claims(run) if arm in ("B-AB", "T-AB", "T-single", "B-single") else None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testdata", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--n-starts", type=int, default=5)
    args = ap.parse_args()
    results = HERE / "results"
    (results / "arms").mkdir(parents=True, exist_ok=True)
    for name in CASES:
        if args.only and name != args.only:
            continue
        out = run_case(name, Path(args.testdata), results, args.n_starts)
        (results / "arms" / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                       encoding="utf-8")
        print(name, out["seconds"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
