// Colocated strings for the STRUCTURE tab that have no equivalent in the
// shared src/i18n/strings.ts dictionary (read-only for this tab — see
// CLAUDE.md editing rules). The shared file already carries the bulk of the
// STRUCTURE vocabulary extracted from the handoff prototype (struct.*,
// col.*, site.*, edit.*); what's missing here is purely client-side network
// lifecycle text (apply in flight / apply failure) that has no counterpart
// in the prototype's static demo data.
export interface StructLocalPair {
  en: string;
  ja: string;
}

export const STRUCT_LOCAL_STRINGS = {
  "struct.local.applying": { en: "applying…", ja: "適用中…" },
  "struct.local.applyError": {
    en: "failed to apply structure edits: {message}",
    ja: "構造編集の適用に失敗: {message}",
  },
  // A3 (api-contract.md §解析ループ): applied occupancy/Uiso edits only feed
  // initial_occupancies on the NEXT real refinement run, not immediately —
  // central STRINGS' "edit.applied" (read-only here) says the ReviseStructure
  // was logged, but not when it actually takes effect.
  "struct.local.appliedNextRun": {
    en: "applies on the next RUN REFINEMENT",
    ja: "次回の RUN REFINEMENT で反映されます",
  },
  // V3b (FR-601, api-contract.md §MEM 密度マップ): RUN MEM job lifecycle text
  // for the MEM DENSITY card — no counterpart in the static handoff prototype.
  "struct.local.runMem": { en: "RUN MEM", ja: "MEM 実行" },
  "struct.local.runningMem": { en: "running…", ja: "実行中…" },
  "struct.local.mapTypeLabel": { en: "map", ja: "map" },
  "struct.local.memBusyTip": {
    en: "another job is running (shared job slot)",
    ja: "他のジョブが実行中です (共有ジョブ枠)",
  },
  "struct.local.memUnrefinedTip": {
    en: "run REFINEMENT first",
    ja: "先に REFINEMENT を実行してください",
  },
  "struct.local.memBusy": { en: "a job is already running", ja: "他のジョブが実行中です" },
  "struct.local.memError": { en: "MEM failed: {message}", ja: "MEM 実行に失敗: {message}" },
  "struct.local.memPollError": {
    en: "MEM status poll failed: {message}",
    ja: "MEM 状態取得に失敗: {message}",
  },
} as const satisfies Record<string, StructLocalPair>;

export type StructLocalKey = keyof typeof STRUCT_LOCAL_STRINGS;

/** Same `{n}`-style interpolation as src/i18n/index.tsx, duplicated locally
 * since that helper isn't exported. */
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
