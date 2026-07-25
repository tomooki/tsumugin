import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import "./shell.css";

/** 38px context bar: project/dataset/frame/echem readout on the left,
 * final_selection_mode chip on the right (FR-402). */
export function ContextBar() {
  const { state } = useStore();
  const { t } = useI18n();
  const project = state.shell?.project;
  const fsm = state.shell?.final_selection_mode ?? "human";
  const isHuman = fsm === "human";
  const echem = project?.echem;

  return (
    <div className="context-bar">
      <div className="context-bar__left">
        <span className="context-bar__label">{t("context.project")}</span>
        <span className="context-bar__project">{project?.name ?? t("context.projectName")}</span>
        <span className="context-bar__sep">/</span>
        <span className="context-bar__dataset">{project?.dataset ?? t("context.datasetLine")}</span>
        <span className="context-bar__sep">/</span>
        <span className="context-bar__frame-chip">{project?.frame ?? t("context.frameChip")}</span>
        {echem && (
          <span className="context-bar__echem">
            V = {echem.v.toFixed(2)} V · Q = {echem.q_mah_g.toFixed(1)} mAh g⁻¹ · x_echem ={" "}
            {echem.x_echem}
          </span>
        )}
      </div>
      <div className="context-bar__right">
        <span className="context-bar__fsm-label">final_selection_mode</span>
        <span
          className={`context-bar__fsm-chip context-bar__fsm-chip--${isHuman ? "human" : "agent"}`}
        >
          {isHuman ? t("context.fsm.human") : t("context.fsm.agent")}
        </span>
        <span className="context-bar__fsm-note">{t("context.fsmNote")}</span>
      </div>
    </div>
  );
}
