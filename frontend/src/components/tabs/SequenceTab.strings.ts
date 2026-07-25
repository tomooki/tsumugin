// Colocated strings for SequenceTab — keys that are not already covered by
// src/i18n/strings.ts (read-only; owned by another agent's parallel work).
// Central STRINGS already carries every static SEQUENCE chart/segment
// heading (seq.*, col.*) extracted from the handoff .dc.html; this file only
// adds the small amount of UI chrome the static mockup hard-coded per
// specific id/anchor ("fr091 ✳ crossover") that must instead be generic here
// because real anchor ids come from the API (viewModel.sequence.anchors).
//
// Numbers, tool names and parameter symbols ("Rwp") are not translated and
// therefore have no entry here — see SequenceTab.tsx.
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const SEQUENCE_STRINGS = {
  // Appended after an arbitrary anchor id to mark the bic-crossover anchor
  // (design: "fr091 ✳ crossover" / "fr091 ✳ 転移" — generalised here since
  // the id itself is server data, not a fixed string).
  "anchor.crossoverSuffix": { en: "✳ crossover", ja: "✳ 転移" },

  // Fallback chart chrome for any chart id the local RWP/lattice/fraction
  // map does not recognise (defensive — the API is expected to always send
  // exactly those three, per handoff/README.md §Centre pane item 5).
  "chart.fallback.placeholder": { en: "SERIES PLACEHOLDER", ja: "系列プロット枠" },

  // — RUN SEQUENTIAL (V2b B2/B3, api-contract.md §逐次 / operando) — this
  // real network flow post-dates the static handoff mockup (which only drew
  // the three chart cards / anchor chips / segment table as fixed demo
  // data), so none of it exists in src/i18n/strings.ts (mirrors PhaseIdTab/
  // HypothesesTab's PID_LOCAL_STRINGS/HYP_LOCAL_STRINGS precedent).
  "seq.run.heading": { en: "RUN SEQUENTIAL", ja: "逐次実行" },
  "seq.run.modeLabel": { en: "mode", ja: "モード" },
  "seq.run.modeForward": { en: "forward", ja: "前方" },
  "seq.run.modeAnchored": { en: "anchored (recommended)", ja: "anchored（推奨）" },
  "seq.run.button": { en: "RUN SEQUENTIAL", ja: "逐次実行" },
  "seq.run.running": { en: "RUNNING …", ja: "実行中 …" },
  "seq.run.busy": {
    en: "a job is already running (job slot busy) — try again once it finishes",
    ja: "他のジョブが実行中です（ジョブ枠が使用中）— 完了後に再試行してください",
  },
  "seq.run.error": {
    en: "failed to start sequential run: {message}",
    ja: "逐次実行の開始に失敗: {message}",
  },
  "seq.run.failed": { en: "sequential run failed: {message}", ja: "逐次実行に失敗: {message}" },
  "seq.run.pollError": {
    en: "failed to fetch sequential status: {message}",
    ja: "逐次実行の状態取得に失敗: {message}",
  },
  "seq.run.chargeConstraint": { en: "use charge constraint", ja: "電気化学制約を使用" },
  "seq.run.chargeConstraintHint": {
    en: "sync ECHEM on the PROJECT tab first",
    ja: "先に PROJECT タブで ECHEM を同期してください",
  },
  // Tooltip for RUN SEQUENTIAL while status.gsas_available is false (V2c レビュー指摘 #4) —
  // mirrors right.strings.ts's "recipe.gsasUnavailable" (RUN REFINEMENT) and
  // HypothesesTab.strings.ts's "hyp.local.gsasUnavailable" (MULTISTART).
  "seq.run.gsasUnavailable": {
    en: "GSAS-II is not available in this backend — sequential runs cannot start",
    ja: "このバックエンドでは GSAS-II が利用できません — 逐次実行は開始できません",
  },

  "seq.anchorTable.heading": { en: "ANCHOR TABLE", ja: "アンカー表" },
  "seq.anchorTable.note": {
    en: "check the phases present at each anchor frame (frame index → phases)",
    ja: "各アンカーフレームに存在する相をチェック（フレーム index → 相）",
  },
  "seq.anchorTable.empty": {
    en: "no frames configured — add frames on the PROJECT tab",
    ja: "フレーム未設定 — PROJECT タブでフレームを追加してください",
  },

  "seq.framesTable.heading": { en: "FRAMES", ja: "フレーム" },
  "col.frame": { en: "FRAME", ja: "フレーム" },
  "col.axisValue": { en: "AXIS VALUE", ja: "軸値" },
  "col.cells": { en: "CELLS", ja: "格子" },
  "col.fractions": { en: "FRACTIONS", ja: "分率" },
  "col.changepoint": { en: "CHANGEPOINT", ja: "変化点" },
} as const satisfies Record<string, StringPair>;

export type SequenceStringKey = keyof typeof SEQUENCE_STRINGS;

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), template);
}

/** Standalone translator for SEQUENCE_STRINGS with `{var}` interpolation
 * (mirrors right.strings.ts's `rt()` / ProjectTab.strings.ts's `pt()`). The
 * static-chrome-only lookup this file used to export (`SEQUENCE_STRINGS[key]
 * [lang]` inline in SequenceTab.tsx) had no interpolation need until the
 * V2b run-job error/status strings above. */
export function sqt(lang: Lang, key: SequenceStringKey, vars?: Record<string, string | number>): string {
  const pair: StringPair | undefined = SEQUENCE_STRINGS[key];
  if (!pair) return key;
  return interpolate(lang === "ja" ? pair.ja : pair.en, vars);
}
