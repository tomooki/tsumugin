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
} as const satisfies Record<string, StringPair>;

export type SequenceStringKey = keyof typeof SEQUENCE_STRINGS;
