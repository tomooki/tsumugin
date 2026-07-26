// Colocated strings for the SETTINGS modal (api-contract.md §アプリ設定
// (資格情報) — Materials Project トークン). This screen post-dates the
// handoff prototype (like WelcomeScreen.strings.ts / shell.strings.ts) so
// none of its text exists in the central extraction src/i18n/strings.ts —
// mirrors the established colocated-strings pattern (shell.strings.ts
// `st()`, right.strings.ts `rt()`, WelcomeScreen.strings.ts `wt()`). Also
// used by TitleBar.tsx for the gear-button trigger's label, since that
// button only exists to open this modal.
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const SETTINGS_STRINGS = {
  "settings.gear.label": { en: "settings", ja: "設定" },
  "settings.title": { en: "SETTINGS", ja: "設定" },
  "settings.mp.heading": {
    en: "MATERIALS PROJECT ACCESS TOKEN",
    ja: "MATERIALS PROJECT アクセストークン",
  },
  "settings.mp.inputLabel": { en: "API token", ja: "API トークン" },
  "settings.mp.placeholder": {
    en: "paste your Materials Project API key",
    ja: "Materials Project の API キーを貼り付け",
  },
  "settings.mp.save": { en: "SAVE", ja: "保存" },
  "settings.mp.saving": { en: "SAVING …", ja: "保存中 …" },
  "settings.mp.clear": { en: "CLEAR", ja: "削除" },
  "settings.mp.clearing": { en: "CLEARING …", ja: "削除中 …" },
  "settings.mp.close": { en: "CLOSE", ja: "閉じる" },
  // {hint} is the server-supplied masked tail (e.g. "ab12") — this component
  // never sees or constructs the real key (api-contract.md 絶対規則).
  "settings.status.setSettings": {
    en: "set · …{hint} (settings)",
    ja: "設定済み · …{hint} (settings)",
  },
  "settings.status.setEnv": {
    en: "detected from environment (env)",
    ja: "環境変数から検出 (env)",
  },
  "settings.status.unset": { en: "not set", ja: "未設定" },
  "settings.status.loading": { en: "…", ja: "…" },
  "settings.envNote": {
    en: ".env / an environment variable is already set. Saving here takes priority over it.",
    ja: ".env / 環境変数で設定されています。ここで保存すると設定ファイルが優先されます",
  },
  "settings.saveSuccess": { en: "token saved", ja: "トークンを保存しました" },
  "settings.clearSuccess": { en: "token cleared", ja: "トークンを削除しました" },
  "settings.saveError": {
    en: "failed to save token: {message}",
    ja: "トークンの保存に失敗: {message}",
  },
  "settings.clearError": {
    en: "failed to clear token: {message}",
    ja: "トークンの削除に失敗: {message}",
  },
  "settings.loadError": {
    en: "failed to load settings: {message}",
    ja: "設定の取得に失敗: {message}",
  },
} as const satisfies Record<string, StringPair>;

export type SettingsStringKey = keyof typeof SETTINGS_STRINGS;

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), template);
}

/** Standalone translator for SETTINGS_STRINGS, mirroring shell.strings.ts's
 * `st()` — useI18n().t only accepts the central StringKey union, so a
 * colocated dictionary needs its own lookup. */
export function sm(lang: Lang, key: SettingsStringKey, vars?: Record<string, string | number>): string {
  const pair: StringPair | undefined = SETTINGS_STRINGS[key];
  if (!pair) return key;
  return interpolate(lang === "ja" ? pair.ja : pair.en, vars);
}
