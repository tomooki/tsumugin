// Colocated strings for FitTab's A6 EXPORT GPX link (api-contract.md
// §解析ループ: GET /api/export/gpx). src/i18n/strings.ts is read-only for
// this task (a parallel agent owns it) and has no vocabulary for this
// control — the static handoff mockup never modelled a download link.
export interface StringPair {
  en: string;
  ja: string;
}

export const FIT_LOCAL_STRINGS = {
  "fit.local.exportGpx": { en: "EXPORT GPX", ja: "GPX を書き出す" },
  "fit.local.exportDisabledTip": {
    en: "no refined result yet — run REFINEMENT first",
    ja: "まだ精密化結果がありません — 先に REFINEMENT を実行してください",
  },
} as const satisfies Record<string, StringPair>;

export type FitLocalKey = keyof typeof FIT_LOCAL_STRINGS;
