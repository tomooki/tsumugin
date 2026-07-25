import { useI18n } from "../../i18n";
import { BlueprintCard } from "../common";

/** AUTO right-pane body — header only implemented per scaffold scope. See
 * handoff/README.md §Right pane "AUTO body" for the full spec: tokens/wall
 * time strip, transcript (user/agent/tool/judgement/approval/escalation
 * message kinds), composer with quick-prompt chips. */
export function AgentSession() {
  const { t } = useI18n();
  return (
    <div style={{ padding: 12 }}>
      <BlueprintCard heading={t("budget.tokens")}>TODO</BlueprintCard>
    </div>
  );
}
