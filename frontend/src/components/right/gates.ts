// Pure, testable derivations used by the right pane. No fetch, no JSX — kept
// free of React so behaviour (gating, formatting) can be unit-tested without
// mounting components. See CLAUDE.md right-pane brief: "ゲート判定はビューで
// 再計算しない" — this is the one thin selector layer allowed, and it derives
// strictly from store state (stage.gate + paramRel / released sites), never
// from anything the server didn't already send.
import type { ReviewSeverity, StageGate } from "../../api/types";
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

const SEVERITY_CHIP_VARIANT: Record<ReviewSeverity, ChipVariant> = {
  close: "inverted",
  unknown: "inverted",
  guard: "neutral",
  echem: "accent",
};

/** Industry's warning states carry no extra hue: close/unknown competitors
 * read as the inverted (neutral-900) attention treatment, guard events as
 * plain neutral, and echem items as the accent/positive treatment — mirrors
 * the handoff prototype's `sevStyle` table. */
export function reviewSeverityChipVariant(severity: ReviewSeverity): ChipVariant {
  return SEVERITY_CHIP_VARIANT[severity];
}

const SEVERITY_LABEL_KEY: Record<ReviewSeverity, RightStringKey> = {
  close: "review.severity.close",
  unknown: "review.severity.unknown",
  guard: "review.severity.guard",
  echem: "review.severity.echem",
};

export function reviewSeverityLabelKey(severity: ReviewSeverity): RightStringKey {
  return SEVERITY_LABEL_KEY[severity];
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
