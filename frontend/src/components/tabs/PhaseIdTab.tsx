import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** Stub — see handoff README §Centre pane item 4 (PHASE ID): candidate
 * table, UNEXPLAINED FEATURES · residual_report card, PHASE SET
 * COMPLETENESS · check_phase_set card. */
export function PhaseIdTab() {
  const { t } = useI18n();
  return <BlueprintCard heading={t("tab.pid")}>TODO</BlueprintCard>;
}
