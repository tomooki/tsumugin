import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import "./shell.css";
import { st } from "./shell.strings";

/** 38px context bar: project/dataset/frame/echem readout on the left,
 * final_selection_mode chip on the right (FR-402). */
export function ContextBar() {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  const project = state.shell?.project;
  const fsm = state.shell?.final_selection_mode ?? "human";
  const isHuman = fsm === "human";
  const echem = project?.echem;

  // V2b B2/B3: once frames are configured (viewModel.project.frames), swap
  // the static single frame chip for a "fr k / N" prev/next navigator over a
  // client-only cursor (state.frameIndex) — SequenceTab's per-frame table
  // highlights the matching row. Falls back to the pre-V2b static chip when
  // there is no frame column yet (demo/pre-project-mode fixtures).
  const frames = state.viewModel?.project?.frames ?? [];
  const frameCount = frames.length;
  const frameIdx = frameCount > 0 ? Math.min(state.frameIndex, frameCount - 1) : 0;

  function goPrevFrame() {
    if (frameIdx <= 0) return;
    dispatch({ type: "SET_FRAME_INDEX", index: frameIdx - 1 });
  }
  function goNextFrame() {
    if (frameIdx >= frameCount - 1) return;
    dispatch({ type: "SET_FRAME_INDEX", index: frameIdx + 1 });
  }

  return (
    <div className="context-bar">
      <div className="context-bar__left">
        <span className="context-bar__label">{t("context.project")}</span>
        <span className="context-bar__project">{project?.name ?? t("context.projectName")}</span>
        <span className="context-bar__sep">/</span>
        <span className="context-bar__dataset">{project?.dataset ?? t("context.datasetLine")}</span>
        <span className="context-bar__sep">/</span>
        {frameCount > 0 ? (
          <span className="context-bar__frame-nav">
            <button
              type="button"
              className="context-bar__frame-nav-btn"
              aria-label={st(lang, "frame.nav.prev")}
              disabled={frameIdx <= 0}
              onClick={goPrevFrame}
            >
              ‹
            </button>
            <span className="context-bar__frame-chip">
              {st(lang, "frame.nav.label", { k: frameIdx + 1, n: frameCount })}
            </span>
            <button
              type="button"
              className="context-bar__frame-nav-btn"
              aria-label={st(lang, "frame.nav.next")}
              disabled={frameIdx >= frameCount - 1}
              onClick={goNextFrame}
            >
              ›
            </button>
          </span>
        ) : (
          <span className="context-bar__frame-chip">{project?.frame ?? t("context.frameChip")}</span>
        )}
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
