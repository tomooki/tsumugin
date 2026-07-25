// Colocated strings for LedgerTab — keys not already covered by
// src/i18n/strings.ts (read-only; owned by another agent's parallel work).
// Central STRINGS already has ledger.title/note/revertTo and the actor
// labels for AGENT ③ / MCP ② / CORE ① / HUMAN (extracted from the handoff
// .dc.html), but the static mockup never rendered a "GUARD" row — the
// actor union in src/api/types.ts adds it for real guard-fired ledger
// entries (e.g. a reverted stage-08 size/mustrain release) — plus the
// fetch loading/error chrome the static mockup didn't need at all.

export interface StringPair {
  en: string;
  ja: string;
}

export const LEDGER_STRINGS = {
  "ledger.actor.guard": { en: "GUARD", ja: "ガード" },
  "ledger.loading": { en: "loading ledger…", ja: "ログを読み込み中…" },
  "ledger.error": { en: "failed to load ledger", ja: "ログの読み込みに失敗しました" },
  "ledger.empty": { en: "no entries yet", ja: "エントリはまだありません" },
} as const satisfies Record<string, StringPair>;

export type LedgerStringKey = keyof typeof LEDGER_STRINGS;
