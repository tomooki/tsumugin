# Handoff: Tsumugin Workbench — Manual / Auto mode GUI

## Overview

Tsumugin (multi-hypothesis, fully automatic Rietveld platform for powder diffraction, GSAS-II
backend) currently ships only a read-only FastAPI result viewer
(`src/tsumugin/webui/app.py` + `static/index.html`, 3 GET routes). This handoff covers the
operator-facing application: a desktop workbench (FastAPI × React + Tauri per ADR-0001) whose
**third layer switches between a human and an LLM**:

- **MANUAL** — layer ③ is the analyst working a conventional analysis GUI.
- **AUTO** — layer ③ is an LLM driving the same ② MCP tools through a chat loop.

Layer ① (deterministic core) and layer ② (MCP, 32 tools) are identical in both modes. The mode
toggle is bound to the project setting `final_selection_mode` (`human` | `agent`, FR-402), and
switching is itself a ledger entry.

The design's governing idea: **proposal ≠ application, and Rwp is not a completeness test.**
Every screen makes visible who holds the decision, what has actually been written, and what is
only proposed.

## About the design files

The files in this bundle are **design references authored as HTML** (streaming "Design
Component" format: one `.dc.html` file = template + a logic class). They are prototypes showing
intended look, structure and behaviour — **not production code to copy**.

The task is to **recreate these designs in Tsumugin's own target environment**: a React
front-end served by FastAPI and packaged with Tauri (ADR-0001; NiceGUI explicitly rejected).
Keep the repo's discipline from ADR-0001 §2: *no logic in the view layer* — all logic stays in
FastAPI/core, the GUI is a thin display/操作 layer. Read `_ds/.../styles.css` for the token
values and port them to whatever styling solution the front-end adopts (CSS variables map 1:1).

## Fidelity

**High-fidelity** for chrome, typography, spacing, colour and interaction states — recreate
pixel-for-pixel using the tokens listed below.

**Deliberately placeholder**: every plot/map region is a dashed frame with a label (the analyst
asked for structure only, no synthetic diffraction data). In implementation these become real
charts (fit/residual, frame series, MEM section, basin plot). Keep the frame geometry and axis
labelling; swap the dashed placeholder for the chart component.

## Application shell

Fixed 1920 × 1080 desktop window, CSS grid rows `56px / 38px / 1fr / 26px`:

1. **Title bar** (56px, `--color-neutral-100`, 1px bottom divider, 16px side padding)
   - Left (300px): `TSUMUGIN` — Barlow Condensed 700, 22px, letter-spacing .06em; then mono
     10px `v0.3 · M0–M11`; then a `GSAS-II` chip (accent-100 field, accent-300 hairline,
     accent-700 type, 1px 6px padding).
   - Centre: **mode toggle** — `.blueprint` frame (hairline + 4 corner `+` marks) around a
     `--color-neutral-200` tray, 3px padding, 3px gap. Two buttons, each `[8×8 dot][label +
     sublabel]`. Active: accent fill, `--color-bg` type, accent-coloured dot. Inactive:
     transparent, neutral-700 type, neutral-400 dot. Labels `MANUAL` / `AUTO` (Barlow Condensed
     600, 14px, .1em) over 10px sublabels *"layer ③ = you, in the analysis GUI"* / *"layer ③ =
     LLM, in a chat loop"*.
   - Right: EN / 日本語 segmented switch (active = neutral-900 field, neutral-100 type), then
     three mono 10.5px hairline chips: `● P2 NON-DESTRUCTIVE` (accent-700 6px dot),
     `ledger.verify() = TRUE`, and a token/wall-time chip (`agent idle` in MANUAL,
     `1.24 M tok · 18 m` in AUTO). **No cost/$ display** — tokens and wall time only.
2. **Context bar** (38px, `--color-neutral-200`): `PROJECT` · project name (Barlow Condensed
   600 15px) · dataset line · frame chip (mono 11.5px on accent-100/accent-300) · echem readout
   `V = 3.94 V · Q = 41.2 mAh g⁻¹ · x_echem = 0.71(2)`. Right side: `final_selection_mode` label
   + state chip (`HUMAN` neutral / `AGENT` accent) + `FR-402 · switch logged to ledger`.
3. **Body** (grid `258px / 1fr / 428px`), see below.
4. **Status bar** (26px, `--color-neutral-900` field, neutral-300 mono 10px): backend build,
   `seed = 0 · bit-identical (NFR-102)`, ledger entry count + chain state, `MCP tools 32 ·
   layer ② reachable`; right-aligned mode sentence (neutral-400 in MANUAL, accent-300 in AUTO).

### Left rail (258px, neutral-100, vertical scroll, sections split by 1px dividers)

Section headings are mono 9.5px, .14em, neutral-600. Sections:
`DATASETS` (name / meta / probe chip per row; active row accent-100 + accent-300 border) ·
`PHASES IN MODEL` (10×10 swatch, name, space group + MP id, weight fraction with esd) ·
`EXTERNAL CHANNELS` (echem V/I/Q, alkali budget x(t) → FR-318, CellConfig μt) ·
`SNAPSHOTS` (id + note, mono 10.5px).

### Centre pane — shared analysis canvas (identical in both modes)

34px tab strip (neutral-100, active tab: `--color-bg` field + 2px accent bottom rule; Barlow
Condensed 600 13px .07em), then a scrolling body (`overflow-x: hidden`, padding 14/16/20).
Each tab's root is `display:flex; flex-direction:column; gap:12px; min-height:100%` so content
fills the pane; the flexible element in each tab carries `flex:1; min-height:<floor>`.

All cards are Industry blueprint objects: `--color-neutral-100` field, hairline border, **four
corner `+` marks**, square corners, 10px 12px padding, heading Barlow Condensed 600 13.5px .06em
with a mono 10px note right-aligned on the same baseline.

1. **FIT** — six metric cards (`Rwp 6.71%`, `GOF 1.29`, `χ² 3 118`, `n_params 38`,
   `Δ vs manual −9.53`, `basins 1 / 3`; label mono 9.5px, value Barlow Condensed 600 24px, note
   10.5px). Histogram chips (`SR-XRD λ0.79958`, `ND TOF bank 1`, `ND TOF bank 3`) + right-aligned
   `two_theta_limits = [4.0, 38.0] · background 24 terms · Kα1 instprm`. Main plot card: rotated
   `Intensity` axis label, growing plot frame (min 220px), one tick-mark row per phase
   (132px label column + dashed strip), 74px residual frame, 2θ scale row 4.0 → 38.0.
   Bottom row: `REFINEMENT HISTORY · THIS FRAME` (stage / Rwp / ΔRwp / GUARD — ΔRwp negative in
   accent-800, the reverted `+0.42` row in neutral-900) and `PHYSICAL VALIDITY GATE` (occupancy
   bounds, Uiso, cell collapse, bond distance, coordination; PASS chips accent, WARN chip
   inverted neutral-900) with the note that Rwp cannot see a wrong phase set.
2. **PARAMETERS** — per-histogram refinement parameters. Histogram chips switch all cards;
   right-aligned live count `released in this histogram: N`. 2-column grid, `align-items:
   stretch`, cards are flex columns whose action row uses `margin-top:auto` so **cards in a row
   are equal height**. Order: `RADIATION / WAVELENGTH` · `SAMPLE & GEOMETRY` /
   `BACKGROUND` · `PROFILE` / `SIZE / MICROSTRAIN` (spans both columns).
   Card body = optional dropdown row, then a 3-column table `FIELD | VALUE | ±σ` where the
   VALUE cell is `[12px checkbox][right-aligned inline input]`, then `RELEASE ALL` / `FIX ALL`,
   then a footer sentence.
   - RADIATION: X-ray → `wavelength λ / Å 0.799580 ±0.000004`, `Kα2 / Kα1 ratio 0.000`,
     `polarization 0.980`; source dropdown (synchrotron X-ray / lab Cu Kα / lab Mo Kα /
     neutron CW / neutron TOF). TOF → λ band per bank, flight path 40.020 m, bank 2θ.
     Footers: λ/cell is near-singular so keep λ fixed (and the SR_CeO2 file's 0.5 is unused);
     for TOF there is no single λ — calibrate difC instead.
   - BACKGROUND: function + terms dropdowns, coefficients 1–8 with esd.
   - PROFILE: CW → U, V, W, X, Y, Z, SH/L, Zero. TOF → difC, difA, difB, Zero, alpha, beta-0,
     beta-1, sig-0, sig-1, sig-2.
   - SIZE / MICROSTRAIN: per phase size/mustrain/LGmix + model dropdowns; footer repeats the
     stage-08 revert and the low-resolution-CW exclusion.
   - SAMPLE & GEOMETRY: per-phase scale, sample displacement, absorption μt, preferred
     orientation.
3. **HYPOTHESES** — ranking table (`# / ID / PHASES / P / Rwp / GOF / BIC / CLOSE / STATUS`,
   header rule 1px `--color-text`, selected row accent-100, close-competitor dot accent-700,
   demoted row status `demoted · chem`). Bottom row (flex:1): `DIFF · <id> vs H-011` with the
   changed cells tinted accent-100, and `EVIDENCE & BASIN` (growing basin plot frame + four
   rows: evidence backend `bic → nested`, `ΔlogZ 1.2 < 2.5 threshold`, `n = 3 · basins = 1 ·
   corroborated`, `demote only · never exclude`).
4. **PHASE ID** — candidate table `# / FORMULA / SOURCE / SG / DARA / m/w/ms/x / STRAIN /
   CHEM GUARD / action`; top row accent-100; `ADD AS PHASE` outline buttons; guard column
   neutral-900 when it fails (`K missing`, `demoted`). Bottom row: `UNEXPLAINED FEATURES ·
   residual_report` (frame + mono list of 2θ / S/N / indexing) and `PHASE SET COMPLETENESS ·
   check_phase_set` (`is_complete FALSE` inverted chip, non-monotonic phase, flagged frames,
   and the note that acceptance criteria cannot see a *missing* phase).
5. **SEQUENCE** — three equally growing chart cards (Rwp vs frame, lattice a/c vs frame, phase
   fraction vs frame with x_echem overlay); anchor chip row (`fr012 … fr091 ✳ crossover` as the
   inverted chip … `fr228`) with `crossover fr091 · total_bic minimum · x_XRD follows x_echem
   within esd`; then `SEGMENT SELECTION · forward vs backward`
   (`SEGMENT / FORWARD SET / BACKWARD SET / Rwp / TOTAL BIC / SELECTED`).
6. **STRUCTURE** — editable model. Grid `1.35fr / 1fr`.
   - `SITES` card: the table is the growing, scrollable region; controls pinned to the card
     bottom. Columns `LABEL | ELEMENT (Z) | x | y | z | occ | Uiso | NOTE | ×`.
     Label and all five numbers are inline-editable (transparent border; neutral-400 on hover;
     accent border + `--color-bg` field on focus). **ELEMENT is a dropdown of GSAS-II's element
     table in atomic-number order** — 98 entries `1 H … 98 Cf` with `1 D` inserted immediately
     after H (99 options).
     **Per-parameter release checkboxes** sit left of each of x, y, z, occ, Uiso (12×12,
     `accent-color: var(--color-accent)`); a released cell tints accent-100. Coordinates fixed
     by symmetry are **disabled + neutral-200 field + neutral-500 type**, tooltip "fixed by
     symmetry (special position)" — mirror `GSASIIobj.GetCSxinel` for the real lock set.
     `NOTE` carries constraint context only (`free_occupancy`, `zeolitic water`,
     `equiv → Ow1`, `new · not refined`) — never release flags.
     Legend bar (accent-100) + live `released: N atomic parameters`.
     `+ ADD ATOM` (accent fill) appends a row flagged `new`; `×` per row deletes.
     Pending-edit counter, then `APPLY AS ReviseStructure` (accent-700) and `DISCARD`.
   - `CONSTRAINTS` card: `Σ occ(K1) · Z = x_total(t)` (EqnConstr · FR-318),
     `occ(D1) ≡ occ(Ow1)` / `Uiso(D1) ≡ Uiso(Ow1)` (EquivConstr), `0 ≤ occ ≤ 1`
     (parmMin/parmMax).
   - `MEM DENSITY · unmodelled` card: growing map frame + peak list with assignment.
7. **LEDGER** — append-only entries: `time | actor | text | hash | REVERT TO`, 3px left rule
   coloured by actor (`AGENT ③` accent, `MCP ②` / `CORE ①` neutral-400, `HUMAN` accent-700,
   guard events neutral-900). Header note: append-only · hash chain · every result traces back
   here (FR-424) · revert never deletes.

### Right pane (428px) — the only mode-dependent region

30px header: MANUAL → `OPERATOR CONSOLE` on `--color-neutral-300`, note *"layer ③ = human · you
release, you accept"*. AUTO → `AGENT SESSION` on `--color-accent-800` with neutral-100 type,
note *"layer ③ = LLM · ② MCP is the only actuator"*.

**MANUAL body** (scrolling, 12px padding, 14px section gap):

- `STAGED RELEASE RECIPE` + **precedence banner** (accent-100 field, accent-300 hairline,
  accent-700 3px left rule, mono kicker `gated by PARAMETERS / STRUCTURE`):
  *"PARAMETERS and STRUCTURE take precedence over this recipe. A stage only releases parameters
  that are checked there — anything left fixed stays fixed, and the stage reports it as
  skipped."*
- Eight stage rows `[nn][name + flags · ΔRwp][RELEASE|REVERT]`. Released rows: neutral-100
  field, accent-300 border, outline REVERT button. Unreleased: transparent, accent-filled
  RELEASE button. **Gating is live**: when a stage's owning group has nothing checked, its
  sub-line turns neutral-900 and reads `gated · nothing released in PARAMETERS` (stage 07 reads
  `gated · no atom occupancy checked in STRUCTURE`).
  Stage → gate mapping: 01 background → bkg · 04/05 profile → profile · 06 phase fractions →
  sample/scale · 07 occupancies → per-atom `occ` checkboxes · 08 size/mustrain → micro.
  Stages 02 (scale + cell) and 03 (zero) are ungated.
- `RUN REFINEMENT` (accent, flex:1) + `SNAPSHOT` (outline).
- `REVIEW QUEUE` (FR-421/423) — blueprint cards: severity chip, title, ref, detail, then
  `ACCEPT …` / `SEND BACK` / `ledger →`. Four seeded items: close competitor ΔlogZ 1.2,
  unindexed peaks 2θ 12.42 / 17.88, guard fired 3×, coulometric feasibility infeasible at
  fr092. Accepting/deferring swaps the primary button to `ACCEPTED ✓` / `SENT BACK` (outline).

**AUTO body** (grid `auto / 1fr / auto`):

- Two-cell strip: `TOKENS 1.24 M`, `WALL TIME 18 m 04 s`.
- Transcript, message kinds:
  - **user** — right-aligned accent-800 bubble, neutral-100 type, max-width 88%.
  - **agent** — `54px` mono gutter label `AGENT` + 12.5px prose.
  - **tool call** — hairline card with a 3px accent left rule; header row
    `[▸/▾] tool_name  MCP ②  1.8 s`; expanded body shows `ARGUMENTS` and `RETURN` as
    neutral-200 `<pre>` blocks (10.5px mono, pre-wrap) plus the reachability sentence *"Every
    argument traces to another tool's output — nothing here was invented by the model."*
    Seeded calls: `check_phase_set`, `residual_report`, `identify_phases`.
  - **judgement card** — blueprint card, kicker `JUDGEMENT · LAYER ③`, comparison rows
    (`cubic + tetragonal` Rwp 8.04 / bic 41 208 vs the 3-phase model 6.71 / 39 402, `Δbic
    −1 806 → 3 phases`), then the explanation that Rwp falls with every added phase so the
    criterion is segment total bic.
  - **approval card** (ModelAction) — accent-700 border; accent-700 header bar with
    `MODEL ACTION · NEEDS HUMAN` and right-aligned `proposal ≠ application`; title, rationale,
    a JSON `<pre>` of the action, then `APPROVE & APPLY` (accent-700) / `REJECT` (outline) /
    `inspect in Manual →` (jumps to MANUAL + PHASE ID). A state line reads
    `held · no state has changed yet` → `applied in snapshot S-0311 · ledger #1284 · revert
    available` or `rejected · proposal kept in ledger, nothing changed`.
  - **escalation** (FR-403) — neutral-900 hairline, 4px neutral-900 left rule, neutral-200
    field, inverted `ESCALATION · FR-403` chip.
- Composer: three quick-prompt chips, a 42px-min input field, `SEND` (accent), and the footer
  `skill: operando-diagnose · tools: 32 · safe actions auto-applied, model actions held for you`.

## Interactions & behaviour

| Trigger | Result |
| --- | --- |
| Mode toggle | Swaps only the right pane + `final_selection_mode` chip + status sentence; centre/left state untouched. Must append a ledger entry (`HUMAN · mode switch manual → auto`). |
| Tab click | Switches centre pane; no refinement is re-run. |
| Histogram chip | Re-points FIT and all four PARAMETERS cards. |
| Parameter checkbox | Toggles release for that parameter; updates the per-histogram count and any dependent stage's gated state. |
| RELEASE ALL / FIX ALL | Sets every row in that card. |
| Atom field edit / element change / ADD ATOM / × | Mutates the working model, increments the pending-edit counter, clears the "applied" state. |
| APPLY AS ReviseStructure | Stores the current model as the applied baseline, resets pending count, writes a child snapshot + ledger entry. |
| DISCARD | Drops **unapplied** edits only, restoring the last applied baseline — never rolls back a committed model (that is the ledger's revert). Disabled (45% opacity, `not-allowed`) when there are no pending edits. |
| Hypothesis row | Selects it and re-points the DIFF card. |
| Tool-call header | Expand/collapse arguments + return. |
| APPROVE & APPLY / REJECT | Applies or records the ModelAction; both paths keep the proposal in the ledger. |
| `inspect in Manual →` | Switches to MANUAL and opens PHASE ID. |
| Review queue ACCEPT / SEND BACK | Marks the item, swapping the primary button to a state label. |
| EN / 日本語 | Switches every label, heading, table header, note, review item, chat message and ledger line. Numbers, tool names, JSON payloads and parameter symbols stay untranslated (they are API surface). |

Non-negotiable invariants inherited from the spec: no destructive control anywhere (P2); every
state change is append + snapshot; SafeActions may auto-apply in AUTO, ModelActions never do;
escalations never block the loop (provisional ranking + needs-review flag).

## State

```
lang: "en" | "ja"                     // also settable as an external prop
mode: "manual" | "auto"               // bound to final_selection_mode
tab: fit | param | hyp | pid | seq | struct | ledger
hist: sxrd | nd | nd2                 // active histogram
hyp: string                           // selected hypothesis id
sites: Site[] | null                  // working model, null = show applied baseline
appliedSites: Site[] | null           // last applied model
edits: number                         // pending ReviseStructure edits
applied: boolean
paramRel: Record<`${hist}.${group}.${name}`, boolean>   // release overrides
paramValue: Record<same key, string>                    // edited values
open: Record<toolCallId, boolean>
stageOn: Record<1..8, boolean>
approval: "pending" | "approved" | "rejected"
review: Record<itemId, "accepted" | "sent">
draft: string
```

`Site = { id, label, el, x, y, z, occ, uiso, note, lock: {x?,y?,z?}, rel: {x?,y?,z?,occ?,uiso?} }`

Data to wire in real endpoints: project/dataset tree, frame + echem sync, per-frame metrics and
fit arrays, hypothesis ranking (`list_hypotheses` / `compare_hypotheses`), phase-ID candidates
(`identify_phases`), sequence series (`sequential_rietveld` / `anchored_sequential`), structure
model + constraints, MEM density (`mem_density`), ledger (append-only), review queue
(`list_review_queue` / `resolve_review_item`), and the agent transcript with its MCP tool calls.

## Design tokens

All colour/type/spacing values come from the bound **Industry** design system — the exact sheet
is bundled at `_ds/industry-3248150c-6a0b-4764-97d2-9f54a45f459a/styles.css` (with its
`readme.md`). Do not invent values; the prototype contains **zero raw hex codes**.

- Ground `--color-bg #f2f2f3` · surface `#e9e9ea` · text `--color-text #1d1f20` ·
  accent `--color-accent #5980a6` (mono scheme — accent-2 reads the same) ·
  `--color-divider = color-mix(in srgb, #1d1f20 16%, transparent)`.
- Ramps 100→900 for neutral and accent (OKLCH, shared lightness scale). Used here:
  neutral 100/200/300/400/500/600/700/800/900, accent 100/200/300/400/500/600/700/800/900.
- Type: `--font-heading "Barlow Condensed"` 600, `--font-body "Barlow"`; **Noto Sans JP is
  appended as a fallback to both** for Japanese. All numeric/technical text is
  `ui-monospace, Menlo, monospace` at 9–11.5px.
- Spacing scale `--space-1 3.4px … --space-8 27.2px` (0.85× density). Layout in this design uses
  8/10/12/14/16px gaps and paddings; radius is **0 everywhere** (Industry is square-cornered).
- Elevation `--shadow-sm/md/lg` (used only by the options file).
- Focus: `:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px }` —
  never the browser default.

**Attention/warning states carry no extra hue.** Industry is mono steel, so warnings read by
value inversion: `--color-neutral-900` field + `--color-neutral-100` type for chips (WARN,
CLOSE, UNKNOWN, `is_complete FALSE`, crossover anchor, escalation label), and
`--color-neutral-900` type against the neutral-600 norm for attention text (reverted ΔRwp,
gated stage lines, pending-edit counter, failed chem guard). Positive/informational states use
accent-100 field + accent-800 type.

## Assets

None. No icons are used; where the real product wants icons, ADR-level guidance is **Lucide at
stroke-width 1.5** (Industry's icon set). Blueprint corner marks are drawn by the design
system's `.blueprint > .corner` CSS, not images. All plots/maps are placeholders.

## Files

- `Tsumugin Workbench.dc.html` — the workbench prototype (all seven tabs, both modes, EN/JA).
  Template first, then a `class Component extends DCLogic` block holding state, the element
  table, the parameter tables, and the full EN/JA string map (`L(en, ja)` pairs).
- `Tsumugin Layout Options.dc.html` — five explored alternatives for the mode-switch shell:
  `1a` three-pane console (the one built), `1b` workspace tabs, `1c` weighted split,
  `1d` evidence board, `1e` three switch treatments (segmented / lever / custody line).
  Useful if the implementation wants to revisit the shell.
- `_ds/industry-3248150c-6a0b-4764-97d2-9f54a45f459a/styles.css`, `readme.md` — the design
  system: token sheet + component layer, and its written rules.

Source repo context for the implementer: spec `docs/tsumugin_spec_v0.3.md` (FR-402/403/404,
FR-420–424), GUI decision `docs/design/adr/0001-gui-frontend-stack.md`, three-layer split
`docs/design/m8-agentic-loop/architecture.md`, reachability rule
`docs/design/operando-diagnosis/architecture.md` §4.5, current viewer
`src/tsumugin/webui/app.py`, MCP tool surface `src/tsumugin/mcp/*_tools.py` (32 tools).
