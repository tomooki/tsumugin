import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** Stub — see handoff README §Centre pane item 2 (PARAMETERS): per-histogram
 * cards (RADIATION/WAVELENGTH, SAMPLE & GEOMETRY, BACKGROUND, PROFILE,
 * SIZE/MICROSTRAIN) with release checkboxes gating the staged recipe. */
export function ParametersTab() {
  const { t } = useI18n();
  return <BlueprintCard heading={t("tab.param")}>TODO</BlueprintCard>;
}
