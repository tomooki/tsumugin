// Colocated strings for HypothesesTab's A5 MULTISTART job UI (api-contract.md
// §解析ループ: POST /api/multistart, GET /api/multistart/status). Same
// rationale as PhaseIdTab.strings.ts — src/i18n/strings.ts is a read-only
// extraction of the static handoff mockup and has no vocabulary for this
// real network flow.
export interface StringPair {
  en: string;
  ja: string;
}

export const HYP_LOCAL_STRINGS = {
  "hyp.local.nStartsLabel": { en: "n_starts", ja: "n_starts" },
  "hyp.local.multistart": { en: "MULTISTART", ja: "マルチスタート" },
  "hyp.local.multistarting": { en: "RUNNING …", ja: "実行中 …" },
  "hyp.local.multistartBusy": {
    en: "a job is already running (job slot busy) — try again once it finishes",
    ja: "ジョブが既に実行中です（ジョブ枠が使用中）— 完了後に再試行してください",
  },
  "hyp.local.multistartError": {
    en: "failed to start multistart: {message}",
    ja: "マルチスタートの開始に失敗: {message}",
  },
  "hyp.local.multistartFailed": {
    en: "multistart failed: {message}",
    ja: "マルチスタートに失敗: {message}",
  },
  "hyp.local.multistartPollError": {
    en: "failed to fetch multistart status: {message}",
    ja: "マルチスタートの状態取得に失敗: {message}",
  },
} as const satisfies Record<string, StringPair>;

export type HypLocalKey = keyof typeof HYP_LOCAL_STRINGS;

/** Same `{n}`-style interpolation as src/i18n/index.tsx, duplicated locally
 * (mirrors PhaseIdTab.strings.ts / StructureTab.strings.ts). */
export function interpolateLocal(
  template: string,
  vars?: Record<string, string | number>,
): string {
  if (!vars) return template;
  return Object.entries(vars).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    template,
  );
}
