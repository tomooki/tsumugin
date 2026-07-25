// Colocated strings for the PROJECT tab (V2a P4, REQ-GUI-015/016). New tab,
// post-dates the handoff prototype extraction (src/i18n/strings.ts) — see
// WelcomeScreen.strings.ts's header comment for the same rationale. Also
// carries "tab.project", the tab-strip label, since CentreCanvas.tsx needs a
// label for this tab and it has no counterpart in the central STRINGS union.
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const PROJECT_STRINGS = {
  "tab.project": { en: "PROJECT", ja: "プロジェクト" },

  "project.title": { en: "PROJECT", ja: "プロジェクト" },
  "project.note": {
    en: "load data / instrument / structure files and refinement settings — every change is ledger-recorded",
    ja: "データ / 装置 / 構造ファイルと精密化設定を読み込む — 変更はすべて ledger に記録",
  },
  "project.demoReadOnly": {
    en: "SAMPLE session — read-only, create or open a project to edit",
    ja: "サンプルセッション — 読み取り専用。編集するにはプロジェクトを作成/開いてください",
  },
  "project.refineRunning": {
    en: "refinement is running — project edits are disabled until it finishes",
    ja: "精密化 実行中 — 完了するまでプロジェクトの編集はできません",
  },

  "project.histograms.heading": { en: "HISTOGRAMS", ja: "ヒストグラム" },
  "project.histograms.empty": { en: "no histograms loaded", ja: "ヒストグラム未読込" },
  "project.histograms.col.id": { en: "ID", ja: "ID" },
  "project.histograms.col.dataFile": { en: "DATA FILE", ja: "データファイル" },
  "project.histograms.col.format": { en: "FORMAT", ja: "形式" },
  "project.histograms.col.radiation": { en: "RADIATION", ja: "放射源" },
  "project.histograms.col.geometry": { en: "GEOMETRY", ja: "ジオメトリ" },
  "project.histograms.col.twoTheta": { en: "2θ RANGE", ja: "2θ 範囲" },
  "project.histograms.remove": { en: "remove", ja: "除去" },
  "project.histograms.remove.confirm": {
    en: "Remove histogram {id}? Its analysis history stays in the ledger.",
    ja: "ヒストグラム {id} を除去しますか? 解析履歴は ledger に残ります。",
  },
  "project.histograms.add.heading": { en: "ADD HISTOGRAM", ja: "ヒストグラムを追加" },
  "project.histograms.add.dataFile": { en: "data file", ja: "データファイル" },
  "project.histograms.add.instrumentFile": { en: "instrument params", ja: "装置パラメータ" },
  "project.histograms.add.radiation": { en: "radiation", ja: "放射源" },
  "project.histograms.add.geometry": { en: "geometry", ja: "ジオメトリ" },
  "project.histograms.add.format": { en: "data format", ja: "データ形式" },
  "project.histograms.add.twoThetaMin": { en: "2θ min", ja: "2θ 下限" },
  "project.histograms.add.twoThetaMax": { en: "2θ max", ja: "2θ 上限" },
  "project.histograms.add.bank": { en: "bank (TOF, optional)", ja: "バンク (TOF, 任意)" },
  "project.histograms.add.submit": { en: "ADD HISTOGRAM", ja: "ヒストグラムを追加" },
  "project.histograms.add.uploading": { en: "uploading …", ja: "アップロード中 …" },
  "project.histograms.add.adding": { en: "ADDING …", ja: "追加中 …" },

  "project.phases.heading": { en: "PHASES", ja: "相" },
  "project.phases.empty": { en: "no phases loaded", ja: "相未読込" },
  "project.phases.col.name": { en: "NAME", ja: "名前" },
  "project.phases.col.cif": { en: "CIF", ja: "CIF" },
  "project.phases.remove": { en: "remove", ja: "除去" },
  "project.phases.remove.confirm": {
    en: "Remove phase {name}? Its analysis history stays in the ledger.",
    ja: "相 {name} を除去しますか? 解析履歴は ledger に残ります。",
  },
  "project.phases.add.heading": { en: "ADD PHASE", ja: "相を追加" },
  "project.phases.add.cif": { en: "CIF file", ja: "CIF ファイル" },
  "project.phases.add.name": { en: "phase name", ja: "相の名前" },
  "project.phases.add.namePlaceholder": { en: "e.g. alpha CaTeO3", ja: "例: alpha CaTeO3" },
  "project.phases.add.submit": { en: "ADD PHASE", ja: "相を追加" },
  "project.phases.add.uploading": { en: "uploading …", ja: "アップロード中 …" },
  "project.phases.add.adding": { en: "ADDING …", ja: "追加中 …" },

  "project.settings.heading": { en: "SETTINGS", ja: "設定" },
  "project.settings.twoThetaMin": { en: "2θ min", ja: "2θ 下限" },
  "project.settings.twoThetaMax": { en: "2θ max", ja: "2θ 上限" },
  "project.settings.backgroundCoeffs": { en: "background terms", ja: "背景 項数" },
  "project.settings.maxCyc": { en: "max cycles", ja: "最大サイクル数" },
  "project.settings.save": { en: "SAVE SETTINGS", ja: "設定を保存" },
  "project.settings.saving": { en: "SAVING …", ja: "保存中 …" },

  "project.error.generic": { en: "request failed", ja: "リクエストに失敗しました" },

  "rail.addHistogram": { en: "add histogram", ja: "ヒストグラムを追加" },
  "rail.addPhase": { en: "add phase", ja: "相を追加" },
} as const satisfies Record<string, StringPair>;

export type ProjectStringKey = keyof typeof PROJECT_STRINGS;

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), template);
}

/** Standalone translator for PROJECT_STRINGS, mirroring right.strings.ts's
 * `rt()`. */
export function pt(lang: Lang, key: ProjectStringKey, vars?: Record<string, string | number>): string {
  const pair: StringPair | undefined = PROJECT_STRINGS[key];
  if (!pair) return key;
  return interpolate(lang === "ja" ? pair.ja : pair.en, vars);
}
