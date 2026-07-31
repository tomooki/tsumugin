# Tsumugin

**Multi-hypothesis, automated Rietveld refinement for powder diffraction.**

Tsumugin automates phase identification, multi-phase Rietveld refinement, and time-resolved
(*operando* / *in situ*) analysis of X-ray and neutron powder diffraction data — with the points
where an AI agent may act, and where a human must decide, designed in explicitly rather than left
implicit.

It drives real refinement engines (GSAS-II and Bruker TOPAS) on real data. It is not a simulator.

> **Status: v0.1 — research software.** The core is validated against published tutorial datasets
> and several real experiments (see [Validation](#validation)), but this is a research codebase,
> not a turnkey product. Expect to read the docs and to check the physics yourself. APIs may change.

---

## Why this exists

Rietveld refinement is easy to get *numerically* right and *physically* wrong. A lower R-factor can
mean a better model — or a wrong model with more parameters, a lattice quietly absorbing a
misaligned zero point, an occupancy above 1, or a phase that is not in the sample at all.

Tsumugin is built around that problem:

- **Evidence, not R-factors, decides between models.** Phase count is selected by BIC, because
  R<sub>wp</sub> decreases monotonically as you add phases and will always prefer the larger model.
- **Physical validity is a gate, not a footnote.** Every refinement passes a validity check
  (occupancies, ADPs, lattice collapse, bond distances) that can fail a fit with a good R<sub>wp</sub>.
- **Nothing is destroyed.** All state changes go to an append-only, hash-chained ledger; "undo" is
  a forward-appended revert, never a deletion.
- **Proposals are separated from application.** The system proposes structure revisions, extra
  measurements, and new phases; accepting them is a separate, recorded decision.
- **Silent no-ops are treated as defects.** A refinement stage that runs but releases nothing, or a
  backend that fails without saying so, is a bug class this codebase actively hunts — several such
  defects are documented in the commit history and pinned by regression tests.

The design specification (Japanese) is [`docs/tsumugin_spec_v0.3.md`](docs/tsumugin_spec_v0.3.md).

---

## The three layers

A design constraint runs through the whole codebase: **an implementation the operator cannot reach
does not exist.**

| Layer | What it is | Contract |
|---|---|---|
| ① Core | Deterministic Python (`tsumugin.*`), NumPy-only imports | Physics and bookkeeping |
| ② MCP tools | 38 [Model Context Protocol](https://modelcontextprotocol.io) tools | JSON in, JSON out — **never raises**; degrades to `{"error", "error_type"}` |
| ③ Skills | Claude Code plugin (`plugins/tsumugin/`) | Procedures telling an LLM *when* to use each tool |

Every ① feature must be reachable from ② as JSON and described in ③ — or its non-exposure must be
declared with a reason. This is enforced mechanically by `tests/test_layer_coverage.py`, which fails
if a capability is added without wiring or a declaration.

Layer ① works standalone; ② and ③ are optional.

---

## Validation

All numbers below were measured with the automated pipeline (no manual parameter tuning) against the
referenced datasets. Tutorial values are the published targets.

### Automated Rietveld vs. published tutorial results (GSAS-II backend)

| Dataset | Radiation | Tutorial R<sub>wp</sub> | Tsumugin |
|---|---|---|---|
| Fluoroapatite | Lab X-ray | 10.38 % | **9.83 %** |
| Y–Fe garnet (Fe/Al mixed occupancy) | CW neutron | 5.18 % | **4.33 %** |
| PbSO₄ | X-ray + CW neutron joint | 6.71 % | **6.66 %** |
| NAC + CaF₂ (2 phases) | TOF neutron ×2 + synchrotron | 6.83 % | ~12.8 % |

### Cross-engine agreement (TOPAS backend)

The strongest available check is whether two independent implementations land on the same
*structure*, not merely the same R-factor:

| Dataset | GSAS-II | TOPAS | Pass criterion |
|---|---|---|---|
| Fluoroapatite | 9.83 % | **10.45 %** | ≤ 12 % ✅ |
| Y–Fe garnet | 4.33 % | **5.54 %** | ≤ 6.5 % ✅ |
| PbSO₄ (X-ray only) | 11.0 % | **8.11 %** | — ✅ |
| PbSO₄ joint | 6.66 % | 8.29 % | ≤ 8 % ⚠️ |
| NAC + CaF₂ | ~12.8 % | 30.9 % | ≤ 15 % ❌ |

For the garnet, both engines independently refine the octahedral site to Fe ≈ 0.58 / Al ≈ 0.42; both
give the same PbSO₄ cell to four decimals. Details — including the seven TOPAS-side defects this
comparison exposed — are in [`docs/benchmark/m12-topas/`](docs/benchmark/m12-topas/).

### Real experiments

- **CaTeO₃ *in situ* dehydration** (14 frames, lab X-ray): sequential refinement with warm start,
  automatic identification of the δ phase from Materials Project at the transition, and acceptance
  gated on phase-fraction significance + R<sub>wp</sub> improvement + validity.
- **K₂Mn[Fe(CN)₆] *operando* electrochemistry** (synchrotron, 63 frames analysed at stride 4):
  R<sub>wp</sub> 6–9 % against 16.2 % for the manual reference analysis.
- **NaCuHCF·nD₂O** (deuterated Prussian-blue analogue): simultaneous synchrotron X-ray + J-PARC TOF
  neutron refinement; model selection by ΔBIC established that the zeolitic water site is required.

Benchmark data is not vendored (size and licensing). See
[`docs/benchmark/README.md`](docs/benchmark/README.md) for fetch instructions; the corresponding
tests skip automatically when the data is absent.

---

## Installation

Requires **Python ≥ 3.12**. The project uses [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/tomooki/tsumugin.git
cd tsumugin
uv sync --all-extras
uv run pytest -m "not gsas and not topas and not agent"
```

> **Use `--all-extras`.** `uv sync` removes extras that are not named, so a plain `uv sync` — or a
> single `--extra gsas` — will silently uninstall the others.

The core imports only NumPy. Every heavy or non-PyPI dependency (GSAS-II, pymatgen, dynesty,
Dysnomia, the MCP SDK, …) sits behind a lazy import and degrades to a named error when absent.

### Refinement backends

Both are optional. Without either, the simulated backend still exercises the full hypothesis-search
and bookkeeping stack.

<details>
<summary><b>GSAS-II</b> (primary backend)</summary>

GSAS-II is not on PyPI, and pip-building it on Windows needs a Fortran toolchain, so it is installed
as a source tree plus prebuilt binaries:

```bash
# 1. Source
git clone --depth 1 https://github.com/AdvancedPhotonSource/GSAS-II.git ~/G2

# 2. Make the source tree importable from the venv:
#    write the absolute path of ~/G2 into <venv>/Lib/site-packages/gsas2-source.pth

# 3. Prebuilt binaries
uv run python -c "import os; from GSASII import GSASIIpath as p; p.InstallGitBinary(p.getGitBinaryLoc(), os.path.expanduser('~/.GSASII/GSASII-bin'), nameByVersion=True)"

# 4. Verify
uv run pytest -m gsas
```
</details>

<details>
<summary><b>Bruker TOPAS</b> (second backend, commercial)</summary>

Only the console executable `tc.exe` is used — there is no COM/OLE or Python API. Point Tsumugin at
it and verify:

```bash
export TSUMUGIN_TOPAS_PATH=/path/to/TOPAS7/tc.exe   # or rely on autodetection
uv run pytest -m topas
```

Selection is per call: `auto_rietveld(..., backend="topas")`. Call `list_refinement_backends` first
to check availability. Do not switch backends between hypotheses or frames — R<sub>wp</sub> and BIC
stop being comparable.
</details>

### Optional extras

| Extra | Enables |
|---|---|
| `gsas` | GSAS-II runtime dependencies |
| `mp` | Materials Project phase library (`MATERIALS_PROJECT_API` env var) |
| `mcp` | MCP server (agent integration) |
| `web` | Read-only web UI and the GUI workbench backend |
| `nested` | Nested-sampling arbitration (dynesty) |
| `echem` | BioLogic `.mpr` electrochemistry import |
| `absorption` | Composition → μ for absorption correction |
| `agent` | Local Claude CLI bridge for the workbench |

---

## Quick start

### Hypothesis ranking without a refinement engine

```python
import numpy as np
from tsumugin import HypothesisTreeSearch, SimulatedBackend, PhaseInstance, LatticeParams
from tsumugin.search.clustering import PhaseCandidate

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 60.0, 0.02)

truth = [
    PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0)),
    PhaseInstance(phase_ref="B", lattice=LatticeParams(6.0, 6.0, 6.0)),
]
observed = backend.simulate(truth, two_theta)

result = HypothesisTreeSearch(backend).search(
    two_theta, observed, [PhaseCandidate(phase=p) for p in truth]
)
best = result.to_summary()["ranked"][0]
print(sorted(p["phase_ref"] for p in best["phases"]))  # ['A', 'B']
assert result.ledger.verify()   # append-only hash chain intact
```

### Automated Rietveld on a real structure

```python
from tsumugin.autorietveld import (
    Geometry, HistogramSpec, PhaseSpec, Radiation, run_auto_rietveld,
)

result = run_auto_rietveld(
    histograms=[HistogramSpec(
        data_path="PBSO4.XRA",
        instrument_path="INST_XRY.PRM",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )],
    phases=[PhaseSpec(structure_path="PbSO4-Wyckoff.cif", phase_name="PbSO4")],
)

print(f"Rwp = {result.final_rwp:.2f} %  GOF = {result.final_gof:.2f}")
print("physically valid:", result.validity.passed)
for stage in result.stage_results:
    print(f"  {stage.label:26s} Rwp={stage.rwp:7.3f} "
          f"n={stage.n_params:3d} {'REVERTED' if stage.reverted else ''}")
```

Parameters are released in stages; a stage that makes the fit worse is reverted and recorded rather
than kept. `result.validity` can fail even when `final_rwp` looks good — that is the point.

Further worked examples are in [`docs/`](docs/) and in the skill procedures under
[`plugins/tsumugin/skills/`](plugins/tsumugin/skills/).

---

## Architecture

| Module | Role |
|---|---|
| `model` | Immutable dataclasses (Project / Hypothesis / PhaseInstance …) |
| `backends` | `RefinementBackend` protocol + Simulated / GSAS-II / TOPAS |
| `refinement` | Staged parameter release + guardrails |
| `evidence` | BIC / AIC evidence and softmax probabilities |
| `store` | Append-only hash-chained ledger + non-destructive snapshots |
| `search` | Peak detection → matching → clustering → pruning → hypothesis tree |
| `reference` | Phase identification (Dara-style scoring, lattice pre-alignment, mixtures) |
| `mp` | Materials Project phase library (lazy pymatgen / mp-api) |
| `autorietveld` | Real-structure automated Rietveld: adaptive recipe, validity gate, anisotropic cell solver |
| `topas` | Bruker TOPAS backend (INP generation, `tc.exe` driver, output parsing) |
| `joint` | Multi-histogram (X-ray + neutron) joint refinement |
| `sequential`, `insitu` | Time-resolved refinement, change-point detection, phase-transition fitting |
| `insitu.anchor` | Anchor-based bidirectional *operando* analysis (BIC-selected transition path) |
| `operando` | Electrochemistry synchronisation, interval segmentation, solid-solution vs two-phase discrimination |
| `nested` | Nested-sampling re-arbitration of near-ties + probability calibration |
| `mem` | Maximum-entropy density analysis and MEM–Rietveld iteration |
| `oed` | Optimal experimental design: proposes discriminating measurements |
| `chem` | Chemical plausibility — **demotes only, never excludes** |
| `refine_loop` | Deterministic agentic loop (observe → judge → apply → re-run) |
| `interop` | RIETAN / Z-Code / GSAS-II format conversion |
| `mcp` | 38 MCP tools (SDK-independent implementation + lazy adapter) |
| `workbench` | GUI backend (FastAPI); frontend in `frontend/`, desktop shell in `desktop/` |

4484 tests, of which 4350 run without any external engine.

---

## Testing

```bash
uv run pytest -m "not gsas and not topas and not agent"   # fast tier, no external engines (~2.5 min)
uv run pytest -m gsas                                     # real GSAS-II refinements
uv run pytest -m topas                                    # real TOPAS refinements
uv run ruff check src tests
```

CI runs the fast tier, ruff, and the frontend build on Linux. **GSAS-II and TOPAS tests do not run in
CI** (neither is redistributable), so run `-m gsas` and `-m topas` locally before opening a PR.

---

## Known limitations

Stated plainly, because a benchmark table without them is misleading:

- **TOF multi-phase refinement is not competitive yet.** NAC + CaF₂ reaches ~12.8 % (GSAS-II) against
  a 6.83 % published value, and 30.9 % on the TOPAS backend. TOF peak-shape modelling is the limiting
  factor.
- **The TOPAS backend cannot use real CIFs in the hypothesis-search layer.** It refuses such input
  rather than silently substituting a simplified structure; real-structure work goes through
  `auto_rietveld(backend="topas")` instead.
- **Phase-set completeness is not guaranteed by the acceptance criteria.** They only ask whether an
  added phase explains residual intensity — a *missing* phase is outside their field of view. The
  `operando-diagnose` skill exists specifically to challenge a converged result.
- **Deuterium/hydrogen positions in hydrated frameworks are not determinable**, even from joint
  X-ray + neutron data; the framework and lattice are robust, the water hydrogens are not.
- **GSAS-II headless restraints do not work.** Measured across three independent code paths: the
  penalty is excluded from χ² by a dialog gate, so bond restraints are effectively non-functional in
  this mode. Canary tests will fail if this is ever fixed upstream.

Open issues are tracked on [GitHub](https://github.com/tomooki/tsumugin/issues).

---

## Documentation

| Path | Contents |
|---|---|
| [`docs/tsumugin_spec_v0.3.md`](docs/tsumugin_spec_v0.3.md) | Design specification (FR/NFR numbers used throughout the code) |
| [`docs/design/`](docs/design/) | Per-milestone architecture notes and ADRs |
| [`docs/benchmark/`](docs/benchmark/) | Measured results and data-fetch instructions |
| [`plugins/tsumugin/skills/`](plugins/tsumugin/skills/) | Operating procedures for agent-driven analysis |

Most documentation is in Japanese.

---

## Acknowledgements

Validation uses publicly available tutorial data from the
[GSAS-II project](https://github.com/AdvancedPhotonSource/GSAS-II) (Advanced Photon Source, Argonne
National Laboratory) and from [Jana2020](http://jana.fzu.cz/). Phase libraries are retrieved from
[Materials Project](https://next-gen.materialsproject.org/). Tsumugin is an independent project and
is not endorsed by any of them.

## License

[BSD 3-Clause](LICENSE) — Copyright © 2026 Tomooki Hosaka.

Note on optional dependencies: Tsumugin itself contains no copyleft code, and every optional backend
is a lazy import that you install separately. One of them, `galvani` (BioLogic `.mpr` reader, in the
`echem` extra), is **GPLv3**. Using it from your own installation is unaffected by this, but if you
redistribute a *bundle* that includes it — for example a packaged desktop build — that bundle is
subject to the GPL. The desktop sidecar therefore does not ship the `echem` extra.
