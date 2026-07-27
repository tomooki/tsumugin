// Colocated strings for PathPicker (api-contract.md §ファイル選択 — Welcome
// のファイル選択ウィンドウ). This component post-dates the handoff prototype
// (there is no OS file dialog reference to extract text from) so, mirroring
// the established colocated-strings pattern (shell.strings.ts `st()`,
// WelcomeScreen.strings.ts `wt()`, SettingsModal.strings.ts `sm()`), all of
// its text lives here rather than in the central src/i18n/strings.ts.
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const PATH_PICKER_STRINGS = {
  "picker.roots.heading": { en: "ROOTS", ja: "ルート" },
  "picker.up.label": { en: "up to parent directory", ja: "親ディレクトリへ" },
  "picker.entries.empty": { en: "empty", ja: "空です" },
  "picker.entries.projectChip": { en: "PROJECT", ja: "プロジェクト" },
  "picker.currentPath.label": { en: "current path", ja: "現在のパス" },
  "picker.select": { en: "SELECT", ja: "選択" },
  "picker.cancel": { en: "CANCEL", ja: "キャンセル" },
  // Shown next to a disabled SELECT in mode="project" — the currently
  // browsed directory/file is neither a project directory nor a .json file.
  "picker.reason.project": {
    en: "choose a folder marked PROJECT, or a .json file",
    ja: "PROJECT の付いたフォルダ、または .json ファイルを選んでください",
  },
  "picker.error.generic": { en: "failed to list directory", ja: "ディレクトリの取得に失敗しました" },
  "picker.loading": { en: "loading …", ja: "読み込み中 …" },
} as const satisfies Record<string, StringPair>;

export type PathPickerStringKey = keyof typeof PATH_PICKER_STRINGS;

/** Standalone translator for PATH_PICKER_STRINGS, mirroring shell.strings.ts's
 * `st()` / SettingsModal.strings.ts's `sm()` — useI18n().t only accepts the
 * central StringKey union, so a colocated dictionary needs its own lookup. */
export function pp(lang: Lang, key: PathPickerStringKey): string {
  const pair: StringPair | undefined = PATH_PICKER_STRINGS[key];
  if (!pair) return key;
  return lang === "ja" ? pair.ja : pair.en;
}
