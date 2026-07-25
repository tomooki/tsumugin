import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** Stub — see handoff README §Centre pane item 7 (LEDGER): append-only
 * entries (time | actor | text | hash | REVERT TO), 3px left rule coloured
 * by actor. No delete UI anywhere (P2 non-destructive). */
export function LedgerTab() {
  const { t } = useI18n();
  return <BlueprintCard heading={t("tab.ledger")}>TODO</BlueprintCard>;
}
