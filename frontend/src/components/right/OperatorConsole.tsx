import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** MANUAL right-pane body — header only implemented per scaffold scope. See
 * handoff/README.md §Right pane "MANUAL body" for the full spec: STAGED
 * RELEASE RECIPE + precedence banner, eight stage rows, RUN
 * REFINEMENT/SNAPSHOT, REVIEW QUEUE. */
export function OperatorConsole() {
  const { t } = useI18n();
  return (
    <div style={{ padding: 12 }}>
      <BlueprintCard heading={t("recipe.title")}>TODO</BlueprintCard>
    </div>
  );
}
