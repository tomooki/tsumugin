import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** Stub — see docs/design/gui-workbench/handoff/README.md §Centre pane, item
 * 1 (FIT) for the full spec: six metric cards, histogram chips, main
 * fit/residual plot, refinement history + physical validity gate. Replaced
 * file-by-file by later work; this scaffold only wires the tab shell. */
export function FitTab() {
  const { t } = useI18n();
  return <BlueprintCard heading={t("tab.fit")}>TODO</BlueprintCard>;
}
