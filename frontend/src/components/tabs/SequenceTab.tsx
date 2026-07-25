import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** Stub — see handoff README §Centre pane item 5 (SEQUENCE): three chart
 * cards (Rwp/lattice/phase fraction vs frame), anchor chip row, SEGMENT
 * SELECTION table. */
export function SequenceTab() {
  const { t } = useI18n();
  return <BlueprintCard heading={t("tab.seq")}>TODO</BlueprintCard>;
}
