import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import "../shell/shell.css";
import { AgentSession } from "./AgentSession";
import { OperatorConsole } from "./OperatorConsole";

/** The only mode-dependent region: 30px header (OPERATOR CONSOLE in MANUAL /
 * AGENT SESSION in AUTO) + a mode-specific body. Mode toggle must swap only
 * this pane, the fsm chip and the status sentence — centre/left state stays
 * untouched (see handoff README "Interactions & behaviour" table). */
export function RightPane() {
  const { state } = useStore();
  const { t } = useI18n();
  const manual = state.mode === "manual";

  return (
    <div className="right-pane">
      <div className={`pane-head pane-head--${manual ? "manual" : "auto"}`}>
        <span>{manual ? t("pane.head.operator") : t("pane.head.agent")}</span>
        <span className="pane-head__note">
          {manual ? t("pane.headNote.manual") : t("pane.headNote.auto")}
        </span>
      </div>
      {manual ? <OperatorConsole /> : <AgentSession />}
    </div>
  );
}
