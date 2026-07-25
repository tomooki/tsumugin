// Local strings for the right pane (MANUAL/AUTO bodies) that are NOT part of
// the central extraction (src/i18n/strings.ts). src/i18n/strings.ts is
// read-only for this task and, being a 1:1 extraction of the handoff
// prototype's hardcoded demo text, has no generic entries for the things the
// real API-driven view needs: a review item's severity *code* (the demo
// hardcoded four fixed titles, we render arbitrary server items), a dynamic
// open-item count, and the escalation FR tag (the demo baked "FR-403" into
// the string itself). Everything else the right pane needs already exists
// centrally and is reused via the normal useI18n() `t()`.
import type { JobKind } from "../../api/types";
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const RIGHT_STRINGS = {
  "review.severity.close": { en: "CLOSE", ja: "僅差" },
  "review.severity.unknown": { en: "UNKNOWN", ja: "未知相" },
  "review.severity.guard": { en: "GUARD", ja: "ガード" },
  "review.severity.echem": { en: "ECHEM", ja: "電気化学" },
  "review.acceptPending": { en: "ACCEPT …", ja: "承認 …" },
  "review.openCountNote": { en: "FR-421 / 423 · {n} open", ja: "FR-421 / 423 · 未処理 {n} 件" },
  "escalationLabel": { en: "ESCALATION", ja: "エスカレーション" },
  // RUN REFINEMENT button label while a background job is polling (real
  // project mode only — demo mode's postRefine resolves "recorded" and never
  // reaches this state). Central STRINGS' "recipe.runRefinement" has no
  // in-progress variant since the handoff prototype never modelled a running
  // job (it was a static mockup).
  "recipe.running": { en: "RUNNING …", ja: "実行中 …" },
  // Fallback error text when a shared-job-slot poll (state.refine) reports
  // "failed" without a server-supplied `error` message. Keyed by the job's
  // real `kind` (セルフレビュー指摘 #1, api-contract.md RefineStatus.kind) so
  // OperatorConsole never mislabels a phaseid/multistart failure as
  // "refinement failed" — see jobFailedFallback below. PhaseIdTab/
  // HypothesesTab have their own kind-specific localized fallbacks already
  // (pid.local.identifyFailed / hyp.local.multistartFailed) and don't use this.
  "job.failed.refine": { en: "refinement failed", ja: "精密化に失敗" },
  "job.failed.phaseid": { en: "phase identification failed", ja: "相同定に失敗" },
  "job.failed.multistart": { en: "multistart failed", ja: "マルチスタートに失敗" },
} as const satisfies Record<string, StringPair>;

export type RightStringKey = keyof typeof RIGHT_STRINGS;

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), template);
}

/** Standalone translator for RIGHT_STRINGS, mirroring src/i18n/index.tsx's
 * `t()` — useI18n().t only accepts the central StringKey union, so a
 * colocated dictionary needs its own lookup. Callers pass `useI18n().lang`
 * directly rather than going through a second context provider. */
export function rt(lang: Lang, key: RightStringKey, vars?: Record<string, string | number>): string {
  const pair: StringPair | undefined = RIGHT_STRINGS[key];
  // Missing key → return the key itself (mirrors central t()'s total-function
  // contract): a label bug must degrade to visible text, never unmount the UI.
  if (!pair) return key;
  return interpolate(lang === "ja" ? pair.ja : pair.en, vars);
}

/** Kind-appropriate fallback text for a "failed" job status that carries no
 * server `error` message (セルフレビュー指摘 #1 (d)). `kind` defaults to
 * "refine" when the polled status predates the `kind` field (older server —
 * mirrors the same fallback used by SET_SHELL / resolveJobConflict). */
export function jobFailedFallback(lang: Lang, kind: JobKind | null | undefined): string {
  return rt(lang, `job.failed.${kind ?? "refine"}` as RightStringKey);
}
