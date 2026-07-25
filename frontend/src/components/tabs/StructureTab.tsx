import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** Stub — see handoff README §Centre pane item 6 (STRUCTURE): editable
 * SITES table (99-element dropdown, per-parameter release checkboxes),
 * CONSTRAINTS card, MEM DENSITY card. Grid 1.35fr / 1fr. */
export function StructureTab() {
  const { t } = useI18n();
  return <BlueprintCard heading={t("tab.struct")}>TODO</BlueprintCard>;
}
