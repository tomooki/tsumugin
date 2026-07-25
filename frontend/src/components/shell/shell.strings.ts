// Colocated strings for the shell chrome (StatusBar/ContextBar) that are not
// already covered by src/i18n/strings.ts (read-only — a 1:1 extraction of
// the handoff prototype's hardcoded demo text, which predates the real
// RUN REFINEMENT polling flow and has no "a job is running" badge string).
// Mirrors components/right/right.strings.ts's `rt()` pattern.
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const SHELL_STRINGS = {
  "refine.running": { en: "REFINING …", ja: "精密化 実行中 …" },
} as const satisfies Record<string, StringPair>;

export type ShellStringKey = keyof typeof SHELL_STRINGS;

/** Standalone translator for SHELL_STRINGS, mirroring right.strings.ts's
 * `rt()` — useI18n().t only accepts the central StringKey union, so a
 * colocated dictionary needs its own lookup. */
export function st(lang: Lang, key: ShellStringKey): string {
  const pair: StringPair | undefined = SHELL_STRINGS[key];
  if (!pair) return key;
  return lang === "ja" ? pair.ja : pair.en;
}
