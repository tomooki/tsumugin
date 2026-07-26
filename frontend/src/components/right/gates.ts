// Pure, testable derivations used by the right pane. No fetch, no JSX — kept
// free of React so behaviour (gating, formatting) can be unit-tested without
// mounting components. See CLAUDE.md right-pane brief: "ゲート判定はビューで
// 再計算しない" — this is the one thin selector layer allowed, and it derives
// strictly from store state (stage.gate + paramRel / released sites), never
// from anything the server didn't already send.
import type { ReviewSeverity, StageGate, StageRow } from "../../api/types";
import type { ChipVariant } from "../common";
import { siteList } from "../../state/reducer";
import type { HistId, WorkbenchState } from "../../state/types";
import type { RightStringKey } from "./right.strings";

/** Is a staged-release recipe stage's gate satisfied?
 * - gate === null → ungated, always open (stages 02/03).
 * - gate === "occ" → STRUCTURE's per-atom occupancy release checkboxes
 *   (stage 07): open iff at least one site has occ released.
 * - otherwise → PARAMETERS' release checkboxes for the active histogram:
 *   open iff at least one `paramRel` key of the form `${hist}.${gate}.*` is
 *   true (key format per handoff/README.md §State; confirmed by
 *   state/reducer.test.ts's "sxrd.bkg.1" fixture). */
export function isStageGateOpen(gate: StageGate, hist: HistId, state: WorkbenchState): boolean {
  if (gate === null) return true;
  if (gate === "occ") {
    return siteList(state).some((site) => site.rel.occ === true);
  }
  const prefix = `${hist}.${gate}.`;
  return Object.entries(state.paramRel).some(([key, released]) => released && key.startsWith(prefix));
}

/** POST /api/refine `stages_on` payload (A1, api-contract.md §解析ループ):
 * the current stageOn toggle state, EXCEPT any stage whose PARAMETERS/
 * STRUCTURE gate is still closed is forced to false regardless of what
 * state.stageOn says — this is the only path by which the recipe UI's
 * gating actually reaches a real run ("UI のゲートを実 run に反映する唯一の
 *経路"). Without the override, a stage toggled on client-side before its
 * gate closed (or a stale fixture) would be sent as released and the
 * backend would silently release parameters PARAMETERS/STRUCTURE never
 * checked. Keys are the stage's own "01".."08" string id, matching the
 * contract's example. */
export function computeStagesOn(stages: StageRow[], state: WorkbenchState): Record<string, boolean> {
  const result: Record<string, boolean> = {};
  for (const stage of stages) {
    const gated = !isStageGateOpen(stage.gate, state.hist, state);
    result[stage.nn] = gated ? false : !!state.stageOn[Number(stage.nn)];
  }
  return result;
}

const SEVERITY_CHIP_VARIANT: Partial<Record<string, ChipVariant>> = {
  close: "inverted",
  unknown: "inverted",
  guard: "neutral",
  echem: "accent",
};

/** Industry's warning states carry no extra hue: close/unknown competitors
 * read as the inverted (neutral-900) attention treatment, guard events as
 * plain neutral, and echem items as the accent/positive treatment — mirrors
 * the handoff prototype's `sevStyle` table. Out-of-vocabulary severities
 * (the contract vocabulary can grow server-side first) degrade to the
 * neutral chip — the UI must never unmount on data (api-contract.md §語彙). */
export function reviewSeverityChipVariant(severity: ReviewSeverity | string): ChipVariant {
  return SEVERITY_CHIP_VARIANT[severity] ?? "neutral";
}

const SEVERITY_LABEL_KEY: Partial<Record<string, RightStringKey>> = {
  close: "review.severity.close",
  unknown: "review.severity.unknown",
  guard: "review.severity.guard",
  echem: "review.severity.echem",
};

/** Label key for a known severity; null for an out-of-vocabulary one, in
 * which case callers render the raw severity code uppercased. */
export function reviewSeverityLabelKey(
  severity: ReviewSeverity | string,
): RightStringKey | null {
  return SEVERITY_LABEL_KEY[severity] ?? null;
}

/** "1.24 M" / "18.4 k" / "512" — matches the handoff's `1.24 M tok` chip. */
export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(2)} M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)} k`;
  return String(Math.round(tokens));
}

/** "18 m 04 s" — matches the handoff's `18 m 04 s` wall-time chip
 * (1084 s → 18 m 04 s, verified against the seeded shell fixture). */
export function formatWallTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m} m ${String(s).padStart(2, "0")} s`;
}

/** "41 208" — space-grouped thousands for bic values in judgement rows. */
export function formatBic(n: number): string {
  return Math.round(n).toLocaleString("en-US").replace(/,/g, " ");
}

/** `propose_*` ModelAction kinds (api-contract.md §`propose_*` ツールと承認
 * カード): each shim tool mints its action_id with one of these prefixes —
 * `np-<frame>` (existing new-phase proposal, B5) / `sr-<n>`
 * (propose_structure_revision) / `rv-<n>` (propose_review_resolution) /
 * `pc-<n>` (propose_phase_change) / `st-<n>` (propose_settings_change). */
export type ApprovalKind = "np" | "sr" | "rv" | "pc" | "st";

const APPROVAL_KIND_PREFIX = /^(np|sr|rv|pc|st)-/;

/** Which ModelAction kind an approval card's action_id belongs to, for the
 * kind badge/state-line text. Returns null for anything that doesn't match a
 * known prefix — an unprefixed id (the pre-V3a "a1"-style fixtures still
 * used by earlier tests) or a future prefix this build doesn't recognise —
 * so callers degrade to the generic MODEL ACTION treatment instead of
 * crashing on unrecognised data (§語彙 の総関数フォールバック原則: 未知は
 * 無視して安全側に倒す、落ちない). */
export function approvalKind(actionId: string | undefined): ApprovalKind | null {
  if (!actionId) return null;
  const m = APPROVAL_KIND_PREFIX.exec(actionId);
  return (m?.[1] as ApprovalKind | undefined) ?? null;
}

/** Number of sites an `sr-` (propose_structure_revision) card's action_json
 * payload touches, for the "N site(s) changed" summary line above the raw
 * JSON. action_json is server-supplied free-form text, so this parses
 * defensively and returns null (→ no summary line, JSON pre still shows)
 * rather than throwing on anything that isn't `{"sites": [...]}`-shaped. */
export function structureRevisionSiteCount(actionJson: string | undefined): number | null {
  if (!actionJson) return null;
  try {
    const parsed: unknown = JSON.parse(actionJson);
    const sites = (parsed as { sites?: unknown } | null)?.sites;
    return Array.isArray(sites) ? sites.length : null;
  } catch {
    return null;
  }
}
