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
