import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { pt } from "../tabs/ProjectTab.strings";
import "./shell.css";

/** 258px left rail: DATASETS / PHASES IN MODEL / EXTERNAL CHANNELS /
 * SNAPSHOTS, each section split by a 1px divider. DATASETS/PHASES headings
 * carry a "+" shortcut to the PROJECT tab (V2a P4). */
export function LeftRail() {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  const vm = state.viewModel;
  const datasets = vm?.datasets ?? [];
  const phases = vm?.phases ?? [];
  const channels = vm?.channels ?? [];
  const snapshots = vm?.snapshots ?? [];

  return (
    <div className="left-rail tg-scroll">
      <div className="left-rail__section">
        <div className="left-rail__heading-row">
          <div className="left-rail__heading">{t("rail.datasets")}</div>
          <button
            type="button"
            className="left-rail__add-btn"
            title={pt(lang, "rail.addHistogram")}
            aria-label={pt(lang, "rail.addHistogram")}
            onClick={() => dispatch({ type: "SET_TAB", tab: "project" })}
          >
            +
          </button>
        </div>
        <div className="left-rail__datasets">
          {datasets.map((d) => (
            <div
              key={d.id}
              className={`left-rail__dataset-row${d.active ? " left-rail__dataset-row--active" : ""}`}
            >
              <span>
                <span className="left-rail__dataset-name">{d.name}</span>
                <span className="left-rail__dataset-meta">{d.meta}</span>
              </span>
              <span className="left-rail__probe-chip">{d.probe}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="left-rail__section">
        <div className="left-rail__heading-row">
          <div className="left-rail__heading">{t("rail.phasesInModel")}</div>
          <button
            type="button"
            className="left-rail__add-btn"
            title={pt(lang, "rail.addPhase")}
            aria-label={pt(lang, "rail.addPhase")}
            onClick={() => dispatch({ type: "SET_TAB", tab: "project" })}
          >
            +
          </button>
        </div>
        <div>
          {phases.map((p) => (
            <div key={p.id} className="left-rail__phase-row">
              <span className="left-rail__swatch" style={{ background: `var(--color-${p.swatch})` }} />
              <span>
                <span className="left-rail__phase-name">{p.name}</span>
                <span className="left-rail__phase-meta">
                  {p.space_group} · {p.mp_id}
                </span>
              </span>
              <span className="left-rail__phase-frac">{p.wt_frac}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="left-rail__section">
        <div className="left-rail__heading">{t("rail.externalChannels")}</div>
        <div>
          {channels.map((c) => (
            <div key={c.id} className="left-rail__channel-row">
              <span>{c.label}</span>
              <span className="left-rail__channel-state">{c.value}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="left-rail__section">
        <div className="left-rail__heading">{t("rail.snapshots")}</div>
        <div>
          {snapshots.map((s) => (
            <div key={s.id} className="left-rail__snapshot-row">
              <span>{s.id}</span>
              <span className="left-rail__snapshot-note">{s.note}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
