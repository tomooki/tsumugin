import { useEffect, useState } from "react";
import { getLedger } from "../../api/client";
import { formatNumber } from "../../api/format";
import type { Actor, LedgerEntry } from "../../api/types";
import { useI18n } from "../../i18n";
import { Btn } from "../common";
import { LEDGER_STRINGS, type LedgerStringKey } from "./LedgerTab.strings";
import "./LedgerTab.css";

// actor → { css modifier, label }. AGENT ③ / HUMAN / MCP ② / CORE ① labels
// live in central i18n (extracted from the handoff mockup); GUARD is added
// locally (see LedgerTab.strings.ts) since the mockup never rendered one.
const ACTOR_META: Record<Actor, { modifier: string; centralKey?: "ledger.actor.agent3" | "ledger.actor.mcp2" | "ledger.actor.core1" | "ledger.actor.human"; localKey?: LedgerStringKey }> = {
  "AGENT ③": { modifier: "agent", centralKey: "ledger.actor.agent3" },
  "MCP ②": { modifier: "core", centralKey: "ledger.actor.mcp2" },
  "CORE ①": { modifier: "core", centralKey: "ledger.actor.core1" },
  HUMAN: { modifier: "human", centralKey: "ledger.actor.human" },
  GUARD: { modifier: "guard", localKey: "ledger.actor.guard" },
};

/** LEDGER tab — see handoff README §Centre pane item 7: append-only entries
 * (time | actor | text | hash | REVERT TO), 3px left rule coloured by actor
 * (AGENT ③ = accent, MCP ②/CORE ① = neutral-400, HUMAN = accent-700, GUARD
 * = neutral-900). Fetched on mount via GET /api/ledger — this tab owns its
 * own load (unlike the other tabs, which read the App-level viewModel).
 *
 * P2 non-destructive: this component renders no delete/remove/edit control
 * anywhere. REVERT TO is the only per-row action — a revert is itself an
 * append (a new ledger entry + a snapshot restore), never a deletion. */
export function LedgerTab() {
  const { lang, t } = useI18n();
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function tl(key: LedgerStringKey): string {
    return LEDGER_STRINGS[key][lang];
  }

  useEffect(() => {
    let cancelled = false;
    getLedger()
      .then((res) => {
        if (cancelled) return;
        setEntries(res.entries);
        setError(null);
      })
      .catch(() => {
        if (cancelled) return;
        setError(tl("ledger.error"));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function actorLabel(actor: Actor): string {
    const meta = ACTOR_META[actor];
    if (meta?.centralKey) return t(meta.centralKey);
    if (meta?.localKey) return tl(meta.localKey);
    return actor;
  }

  return (
    <div className="ledger-tab">
      <div className="ledger-tab__head">
        <span className="ledger-tab__title">{t("ledger.title")}</span>
        <span className="ledger-tab__note">{t("ledger.note")}</span>
      </div>

      {entries === null && !error && <div className="ledger-tab__status">{tl("ledger.loading")}</div>}
      {error && <div className="ledger-tab__status ledger-tab__status--error">{error}</div>}
      {entries !== null && entries.length === 0 && (
        <div className="ledger-tab__status">{tl("ledger.empty")}</div>
      )}

      <div className="ledger-tab__rows">
        {(entries ?? []).map((entry) => {
          // out-of-vocabulary actor → neutral "core" rule colour, never a crash (§語彙)
          const modifier = ACTOR_META[entry.actor]?.modifier ?? "core";
          // finite_or_none 規約 + 旧サーバ (フィールドごと欠落) の両方を同じ「値なし」に潰す。
          const rwp = Number.isFinite(entry.rwp as number) ? (entry.rwp as number) : null;
          const bic = Number.isFinite(entry.bic as number) ? (entry.bic as number) : null;
          return (
            <div key={entry.index} className={`ledger-row ledger-row--${modifier}`}>
              <span className="ledger-row__time">{entry.time}</span>
              <span className="ledger-row__actor">{actorLabel(entry.actor)}</span>
              <span className="ledger-row__text">{entry.text}</span>
              {/* 適合度 (api-contract.md GET /api/ledger): 精密化由来のエントリだけが値を持つ。
                  null は **空欄** — `―` は「あるはずの値が欠けている」に予約しており、
                  モード切替に Rwp が無いのは欠測ではない。 */}
              <span className="ledger-row__rwp" title={rwp === null ? undefined : "Rwp / %"}>
                {rwp === null ? "" : formatNumber(rwp, 2)}
              </span>
              <span className="ledger-row__bic" title={bic === null ? undefined : "BIC"}>
                {bic === null ? "" : formatNumber(bic, 0)}
              </span>
              <span className="ledger-row__hash">{entry.hash}</span>
              <Btn variant="outline" className="ledger-row__revert">
                {t("ledger.revertTo")}
              </Btn>
            </div>
          );
        })}
      </div>
    </div>
  );
}
