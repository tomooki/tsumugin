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
  // ContextBar frame nav (V2b B2/B3): shown instead of the static single
  // frame chip once viewModel.project.frames is non-empty — see
  // ContextBar.tsx.
  "frame.nav.label": { en: "fr {k} / {n}", ja: "fr {k} / {n}" },
  "frame.nav.prev": { en: "previous frame", ja: "前のフレーム" },
  "frame.nav.next": { en: "next frame", ja: "次のフレーム" },
  // GSAS-II unavailability chip (V2c レビュー指摘 #4): Tier1 desktop sidecar excludes GSAS-II
  // (desktop/README.md "Tier1 の GSAS 前提") — status.gsas_available is dynamic per GET
  // /api/state (api/types.ts BackendStatus doc comment), so this must render/unrender live, not
  // just once at load. Inverted chip variant matches Chip.tsx's "the only attention treatment".
  "status.gsasUnavailable": { en: "GSAS-II NOT FOUND", ja: "GSAS-II 未検出" },
  // Materials Project token unavailability chip (api-contract.md §アプリ設定
  // "GET /api/state の status.mp_available" — "…事前 disabled に使う。
  // gsas_available と同じ流儀"). Same dynamic-per-GET-/api/state /
  // inverted-chip treatment as status.gsasUnavailable above.
  "status.mpUnavailable": { en: "MP TOKEN NOT SET", ja: "MP トークン未設定" },
  // CLOSE PROJECT (api-contract.md §プロジェクトを閉じる導線): ContextBar's
  // right-end button, shown whenever state.shell.source !== "none" (project
  // or demo). A job running while it's clicked is a non-fatal 409, not a
  // fatal error — shown inline next to the button rather than via SET_ERROR.
  "close.button": { en: "CLOSE PROJECT", ja: "プロジェクトを閉じる" },
  "close.closing": { en: "CLOSING …", ja: "閉じています …" },
  "close.busy": {
    en: "a job is running — cannot close now",
    ja: "実行中は閉じられません",
  },
  "close.error": { en: "failed to close project", ja: "プロジェクトを閉じられませんでした" },
} as const satisfies Record<string, StringPair>;

export type ShellStringKey = keyof typeof SHELL_STRINGS;

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), template);
}

/** Standalone translator for SHELL_STRINGS, mirroring right.strings.ts's
 * `rt()` — useI18n().t only accepts the central StringKey union, so a
 * colocated dictionary needs its own lookup. */
export function st(lang: Lang, key: ShellStringKey, vars?: Record<string, string | number>): string {
  const pair: StringPair | undefined = SHELL_STRINGS[key];
  if (!pair) return key;
  return interpolate(lang === "ja" ? pair.ja : pair.en, vars);
}
