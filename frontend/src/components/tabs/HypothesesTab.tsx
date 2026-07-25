import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** Stub — see handoff README §Centre pane item 3 (HYPOTHESES): ranking
 * table, DIFF card, EVIDENCE & BASIN card. */
export function HypothesesTab() {
  const { t } = useI18n();
  return <BlueprintCard heading={t("tab.hyp")}>TODO</BlueprintCard>;
}
