"""合成 `S-dev` を生成する (fit-then-judge P0 §6)。

    uv run python docs/benchmark/fit-then-judge-synthetic/generate.py [--out <dir>] [--only <case_id>]

- 構造は COD のミラーから ID で取得し、`cases.SOURCES` の sha256 と照合する (違えば止める)。
- 事例ごとに**真値の構造** (混合占有・選択配向・欠落相を含む) からパターンを計算し、**出発の構造** (欠陥を入れたもの) を書く。
- manifest (P0 §6.4) は**パターンを作る前に**組み (期待する検出器の結果を含む)、パターンの sha256 を足して
  `manifests/<case_id>.json` に書く (追跡する)。パターンと CIF は ``--out`` (既定 `results/`、gitignore) に置く。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from dataclasses import replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cases import CASES, SOURCES, CaseDef, PhaseDef  # noqa: E402

from tsumugin.autorietveld.cif_normalize import Atom, Structure, read_structure_cif, write_gsas_cif  # noqa: E402
from tsumugin.prereg_eval.defects import (  # noqa: E402
    displace_atom,
    drop_atom,
    scale_cell,
    shift_mixed_ratio,
    swap_site_elements,
    translate_along,
)
from tsumugin.prereg_eval.synth import (  # noqa: E402
    DEFECTS,
    DELTA_ZERO_DEG,
    CaseManifest,
    DefectSpec,
    PhaseSource,
    sample_defect,
)

_MIRROR = "https://qiserver.ugr.es/cod/{id}.cif"
CONTROL_EXPECTATION = "control: no defect-specific detector should fire"


def fetch_cif(compound: str, cache: Path) -> Path:
    src = SOURCES[compound]
    path = cache / f"{src.cod_id}.cif"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(_MIRROR.format(id=src.cod_id), timeout=60) as r:  # noqa: S310 — 固定の COD ミラー
            path.write_bytes(r.read())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != src.sha256:
        raise RuntimeError(f"{compound}: COD {src.cod_id} の sha256 が登録と違う ({digest})")
    return path


def _mix_fe(s: Structure, fraction: float) -> Structure:
    """Mg 席に Fe を ``fraction`` だけ混ぜる (ラベル Mg<n> → Fe<n>、同じ位置・同じ Uiso)。"""
    atoms: list[Atom] = []
    for at in s.atoms:
        if at.type_symbol.startswith("Mg"):
            atoms.append(replace(at, occ=1.0 - fraction))
            atoms.append(replace(at, label="Fe" + at.label[2:], type_symbol="Fe+2", occ=fraction))
        else:
            atoms.append(at)
    return replace(s, atoms=tuple(atoms))


def truth_structure(pd: PhaseDef, cif: Path) -> Structure:
    s = read_structure_cif(cif)
    return _mix_fe(s, pd.mixed_fe) if pd.mixed_fe else s


def _atom(s: Structure | None, label: str) -> str:
    if s is None:
        return "absent"
    for a in s.atoms:
        if a.label == label:
            return f"{a.label} {a.type_symbol} ({a.x:.5f}, {a.y:.5f}, {a.z:.5f}) occ={a.occ:.4f}"
    return f"{label} absent"


def _cell(s: Structure | None) -> str:
    return "absent" if s is None else f"a={s.a:.5f} b={s.b:.5f} c={s.c:.5f}"


def _describe(kind, compound, rest, truth, start, mag, zero_deg, case) -> tuple[str, str]:  # noqa: ANN001
    """P0 §6.4 の「真値・出発値」を文字列で残す (manifest は人が読んで照合する記録)。"""
    if kind == 1:
        a, b = rest.split("/")
        return f"{_atom(truth, a)}; {_atom(truth, b)}", f"{_atom(start, a)}; {_atom(start, b)}"
    if kind in (2, 4):
        return _atom(truth, rest), _atom(start, rest)
    if kind == 3:
        n = rest[1:]
        return (f"{_atom(truth, 'Mg' + n)}; {_atom(truth, 'Fe' + n)}",
                f"{_atom(start, 'Mg' + n)}; {_atom(start, 'Fe' + n)}")
    if kind in (6, 8):
        return _cell(truth), _cell(start) + (" (cell frozen)" if kind == 8 else "")
    if kind == 7:
        return f"zero={zero_deg:.4f} deg", "zero=0 (instrument file)"
    if kind == 9:
        return "origin as in COD", f"all atoms shifted along {rest} by {float(mag):.5f}"
    if kind == 5:
        wt = next(pd.wt for pd in case.phases if pd.compound == compound)
        return f"{compound} present at wt={wt}", f"{compound} absent from the model"
    if kind == 10:
        po = next(pd.preferred_orientation for pd in case.phases if pd.preferred_orientation)
        return f"March-Dollase r={po[0]} axis={po[1]}", "no preferred orientation in the model"
    return "truth", "start"


def build_case(case: CaseDef, cifs: dict[str, Path], out: Path) -> dict:
    """真値と出発の構造・パターンの入力・manifest (パターン前) を組む。GSAS は使わない。"""
    rng = np.random.default_rng(case.seed)
    truths = {pd.compound: truth_structure(pd, cifs[pd.compound]) for pd in case.phases}
    starts = dict(truths)
    zero_deg = 0.0
    specs: list[DefectSpec] = []
    for kind, target in case.defects:
        mag = sample_defect(kind, rng)
        compound, _, rest = target.partition(".")
        s = starts.get(compound)
        if kind == 1:
            a, b = rest.split("/")
            starts[compound] = swap_site_elements(s, a, b)
        elif kind == 2:
            starts[compound] = drop_atom(s, rest)
        elif kind == 3:
            n = rest[1:]  # "M2" → 2
            starts[compound] = shift_mixed_ratio(s, f"Mg{n}", f"Fe{n}", -float(mag))
        elif kind == 4:
            starts[compound] = displace_atom(s, rest, float(mag), rng)
        elif kind == 6:
            factors = tuple(1.0 + float(rng.choice([-1.0, 1.0])) * float(sample_defect(6, rng)) for _ in range(3))
            starts[compound] = scale_cell(s, factors)  # type: ignore[arg-type]
            mag = None
            target = f"{target} factors={tuple(round(f, 5) for f in factors)}"
        elif kind == 7:
            zero_deg = float(mag) * DELTA_ZERO_DEG
        elif kind == 8:
            starts[compound] = scale_cell(s, (1.0 + float(mag),) * 3)
        elif kind == 9:
            starts[compound] = translate_along(s, rest, float(mag))
        # #5 (欠落相) と #10 (選択配向) は真値の側だけ — 出発の構造は変えない
        truth_desc, start_desc = _describe(kind, compound, rest, truths.get(compound), starts.get(compound), mag, zero_deg, case)
        specs.append(DefectSpec(kind, target, None if mag is None else float(mag), truth_desc, start_desc))

    case_dir = out / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    truth_paths, start_phases = {}, []
    for pd in case.phases:
        tp = write_gsas_cif(truths[pd.compound], case_dir / f"truth_{pd.compound}.cif", phase_name=pd.compound)
        truth_paths[pd.compound] = str(tp)
        if pd.in_model:
            sp = write_gsas_cif(starts[pd.compound], case_dir / f"start_{pd.compound}.cif", phase_name=pd.compound)
            spec: dict = {"structure_path": str(sp), "phase_name": pd.compound, "refine_cell": pd.refine_cell}
            if pd.mixed_fe:
                labels = [a.label for a in starts[pd.compound].atoms]
                spec["mixed_occupancy_groups"] = [[m, "Fe" + m[2:]] for m in labels if m.startswith("Mg")]
            start_phases.append(spec)

    expected = tuple(DEFECTS[k].expected for k, _ in case.defects) or (CONTROL_EXPECTATION,)
    manifest = CaseManifest(
        case_id=case.case_id, case_set="S-dev",
        phases=tuple(
            PhaseSource(db="COD", entry_id=SOURCES[pd.compound].cod_id, revision=SOURCES[pd.compound].revision,
                        sha256=SOURCES[pd.compound].sha256, license="CC0", phase_name=pd.compound,
                        formula=SOURCES[pd.compound].formula, wt_fraction=pd.wt)
            for pd in case.phases
        ),
        instrument=case.instrument, max_counts=case.max_counts, seed=case.seed,
        defects=tuple(specs), mismatches=case.mismatches, expected=expected,
    )
    return {"manifest": manifest, "truth_paths": truth_paths, "start_phases": start_phases, "zero_deg": zero_deg,
            "case_dir": case_dir}


def _versions() -> dict[str, str]:
    import numpy

    out = {"numpy": numpy.__version__}
    try:
        from GSASII import GSASIIpath

        out["gsas2"] = str(GSASIIpath.GetVersionNumber())
    except Exception:  # noqa: BLE001
        out["gsas2"] = "unknown"
    return out


def generate(case: CaseDef, cache: Path, out: Path, manifests: Path) -> CaseManifest:
    from tsumugin.prereg_eval.synth_gsas import SimPhase, simulate_pattern

    cifs = {pd.compound: fetch_cif(pd.compound, cache) for pd in case.phases}
    built = build_case(case, cifs, out)
    manifest: CaseManifest = built["manifest"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=HERE).stdout.strip()
    manifest = replace(manifest, generator_commit=commit, versions=_versions())
    sim = simulate_pattern(
        [SimPhase(built["truth_paths"][pd.compound], pd.compound, pd.wt, pd.preferred_orientation)
         for pd in case.phases],
        instrument=case.instrument, out_dir=str(built["case_dir"]), stem=case.case_id,
        max_counts=case.max_counts, seed=case.seed, zero_deg=built["zero_deg"], mismatches=case.mismatches,
    )
    manifest = manifest.with_pattern(np.column_stack([sim.x, sim.y, sim.esd]))
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / f"{case.case_id}.json").write_text(
        json.dumps({**manifest.to_dict(), "start_phases_relative": [
            {**p, "structure_path": Path(p["structure_path"]).name} for p in built["start_phases"]
        ]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (built["case_dir"] / "phases.json").write_text(json.dumps(built["start_phases"], indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "results"))
    ap.add_argument("--cache", default=str(HERE / "results" / "cod_cache"))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    for case in CASES:
        if args.only and case.case_id != args.only:
            continue
        m = generate(case, Path(args.cache), Path(args.out), HERE / "manifests")
        print(case.case_id, m.pattern_sha256[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
