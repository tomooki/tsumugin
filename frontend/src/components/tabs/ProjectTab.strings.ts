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

  // 装置パラメータファイルを持っていない利用者の導線 (FR-502)。
  "project.instrument.noFile": { en: "don't have one?", ja: "装置ファイルが無い" },
  "project.instrument.heading": { en: "MAKE AN INSTRUMENT FILE", ja: "装置ファイルを作る" },
  "project.instrument.preset": { en: "preset", ja: "プリセット" },
  "project.instrument.presetNone": { en: "(use wavelength below)", ja: "(下の波長を使う)" },
  "project.instrument.presetsUnavailable": {
    en: "presets need GSAS-II on the server — type a wavelength instead",
    ja: "プリセットはサーバ側の GSAS-II が要る — 代わりに波長を入力してください",
  },
  "project.instrument.wavelength": { en: "wavelength (Å)", ja: "波長 (Å)" },
  "project.instrument.wavelengthKa2": { en: "Kα2 wavelength (Å, optional)", ja: "Kα2 波長 (Å, 任意)" },
  "project.instrument.wavelengthHint": {
    en: "Leave Kα2 empty for Kα2-stripped data — a doublet model on stripped data is the largest systematic residual.",
    ja: "Kα2 除去済みデータでは Kα2 を空にする — 除去済みに二重線を当てるのが最大の系統残差になる。",
  },
  "project.instrument.create": { en: "CREATE INSTRUMENT FILE", ja: "装置ファイルを作る" },
  "project.instrument.creating": { en: "CREATING …", ja: "作成中 …" },
  "project.instrument.findings": { en: "instrument file notes", ja: "装置ファイルの指摘" },

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

  // — FRAMES (V2b B1, api-contract.md §逐次 / operando) —
  "project.frames.heading": { en: "FRAMES", ja: "フレーム" },
  "project.frames.note": {
    en: "sequence / operando frame column — shares histograms[0]'s instrument condition",
    ja: "逐次/operando のフレーム列 — histograms[0] の装置条件を共有",
  },
  "project.frames.empty": { en: "no frames configured", ja: "フレーム未設定" },
  "project.frames.col.label": { en: "LABEL", ja: "ラベル" },
  "project.frames.col.axisValue": { en: "AXIS VALUE", ja: "軸値" },
  "project.frames.col.dataFile": { en: "DATA FILE", ja: "データファイル" },
  "project.frames.axis.label": { en: "frame axis", ja: "フレーム軸" },
  "project.frames.axis.index": { en: "index", ja: "インデックス" },
  "project.frames.axis.time": { en: "time", ja: "時間" },
  "project.frames.axis.temperature": { en: "temperature", ja: "温度" },
  "project.frames.add.heading": { en: "ADD FRAMES", ja: "フレームを追加" },
  "project.frames.add.files": { en: "data files (multiple)", ja: "データファイル (複数選択可)" },
  "project.frames.add.axisValue": { en: "axis value", ja: "軸値" },
  "project.frames.add.remove": { en: "remove", ja: "除去" },
  "project.frames.add.uploading": { en: "uploading …", ja: "アップロード中 …" },
  "project.frames.add.submit": { en: "SAVE FRAMES", ja: "フレームを保存" },
  "project.frames.add.saving": { en: "SAVING …", ja: "保存中 …" },

  // — ECHEM (V2b B4, api-contract.md §逐次 / operando) —
  "project.echem.heading": { en: "ECHEM", ja: "電気化学" },
  "project.echem.note": {
    en: "align_echem + alkali_budget — synchronous, results held for this session",
    ja: "align_echem + alkali_budget — 同期実行、結果はセッションに保持",
  },
  "project.echem.mprFile": { en: "MPR file", ja: "MPR ファイル" },
  "project.echem.mprPath": { en: "MPR path", ja: "MPR パス" },
  "project.echem.offsetS": { en: "offset (s)", ja: "オフセット (s)" },
  "project.echem.intervalS": { en: "interval (s)", ja: "間隔 (s)" },
  "project.echem.sign": { en: "sign", ja: "符号" },
  "project.echem.x0": { en: "x0 (optional)", ja: "x0 (任意)" },
  "project.echem.submit": { en: "SYNC ECHEM", ja: "ECHEM を同期" },
  "project.echem.syncing": { en: "SYNCING …", ja: "同期中 …" },
  "project.echem.uploading": { en: "uploading …", ja: "アップロード中 …" },
  "project.echem.success": { en: "echem synced — channels/fraction overlay updated", ja: "echem 同期完了 — channels/分率重ね描きを更新しました" },

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
