// Colocated strings for the Welcome screen (source="none", REQ-GUI-017).
// This screen post-dates the handoff prototype (2026-07-25 "prototype is a
// design reference, not the spec" pivot — see V2_PLAN.md) so none of its text
// exists in the central extraction src/i18n/strings.ts; everything lives
// here, mirroring the established colocated-strings pattern (shell.strings.ts
// `st()`, right.strings.ts `rt()`).
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const WELCOME_STRINGS = {
  "welcome.title": { en: "TSUMUGIN WORKBENCH", ja: "TSUMUGIN ワークベンチ" },
  "welcome.subtitle": {
    en: "no project loaded — create one, open an existing one, or open the sample",
    ja: "プロジェクト未読込 — 新規作成、既存プロジェクトを開く、またはサンプルを開く",
  },

  "welcome.new.heading": { en: "NEW PROJECT", ja: "新規プロジェクト" },
  "welcome.new.nameLabel": { en: "name", ja: "名前" },
  "welcome.new.namePlaceholder": { en: "e.g. CaTeO3 cyclic", ja: "例: CaTeO3 cyclic" },
  "welcome.new.directoryLabel": { en: "directory", ja: "保存先" },
  "welcome.new.directoryPlaceholder": { en: "e.g. C:\\projects", ja: "例: C:\\projects" },
  "welcome.new.create": { en: "CREATE", ja: "作成" },
  "welcome.new.creating": { en: "CREATING …", ja: "作成中 …" },

  "welcome.open.heading": { en: "OPEN", ja: "開く" },
  "welcome.open.pathLabel": { en: "project path", ja: "プロジェクトパス" },
  "welcome.open.pathPlaceholder": {
    en: "e.g. C:\\projects\\CaTeO3 cyclic",
    ja: "例: C:\\projects\\CaTeO3 cyclic",
  },
  "welcome.open.open": { en: "OPEN", ja: "開く" },
  "welcome.open.opening": { en: "OPENING …", ja: "開いています …" },
  "welcome.open.recentHeading": { en: "RECENT", ja: "最近使ったプロジェクト" },
  "welcome.open.recentEmpty": { en: "no recent projects", ja: "最近使ったプロジェクトはありません" },

  "welcome.sample.heading": { en: "SAMPLE", ja: "サンプル" },
  "welcome.sample.note": {
    en: "browse a seeded demo session — read-only, nothing is written to disk",
    ja: "シードのデモセッションを閲覧 — 読み取り専用、ディスクへの書き込みなし",
  },
  "welcome.sample.open": { en: "OPEN SAMPLE", ja: "サンプルを開く" },
  "welcome.sample.opening": { en: "OPENING …", ja: "開いています …" },

  "welcome.error.generic": { en: "request failed", ja: "リクエストに失敗しました" },
} as const satisfies Record<string, StringPair>;

export type WelcomeStringKey = keyof typeof WELCOME_STRINGS;

/** Standalone translator for WELCOME_STRINGS, mirroring shell.strings.ts's
 * `st()` / right.strings.ts's `rt()` — useI18n().t only accepts the central
 * StringKey union, so a colocated dictionary needs its own lookup. */
export function wt(lang: Lang, key: WelcomeStringKey): string {
  const pair: StringPair | undefined = WELCOME_STRINGS[key];
  if (!pair) return key;
  return lang === "ja" ? pair.ja : pair.en;
}
