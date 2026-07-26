import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import "../shell/shell.css";
import { AgentPolicySegment } from "./AgentPolicySegment";
import { AgentSession } from "./AgentSession";
import { OperatorConsole } from "./OperatorConsole";

/** The only mode-dependent region: 30px header (OPERATOR CONSOLE in MANUAL /
 * AGENT SESSION in AUTO) + a mode-specific body. Mode toggle must swap only
 * this pane, the fsm chip and the status sentence — centre/left state stays
 * untouched (see handoff README "Interactions & behaviour" table).
 *
 * AUTO's header also carries the agent permission-mode segment
 * (api-contract.md §エージェント権限モード, V3a) — it's not part of
 * AgentSession's body because it has to stay visible/actionable even while
 * the transcript scrolls, and MANUAL's OPERATOR CONSOLE has no equivalent
 * (the mode only governs the agent bridge). */
export function RightPane() {
  const { state } = useStore();
  const { t } = useI18n();
  const manual = state.mode === "manual";

  return (
    <div className="right-pane">
      <div className={`pane-head pane-head--${manual ? "manual" : "auto"}`}>
        <span>{manual ? t("pane.head.operator") : t("pane.head.agent")}</span>
        {!manual && <AgentPolicySegment />}
        <span className="pane-head__note">
          {manual ? t("pane.headNote.manual") : t("pane.headNote.auto")}
        </span>
      </div>
      {manual ? <OperatorConsole /> : <AgentSession />}
    </div>
  );
}
