import type { ReactElement } from "react";
import { useI18n } from "../../i18n";
import type { StringKey } from "../../i18n/strings";
import { useStore } from "../../state/store";
import type { TabId } from "../../state/types";
import {
  FitTab,
  HypothesesTab,
  LedgerTab,
  ParametersTab,
  PhaseIdTab,
  PhasesTab,
  ProjectTab,
  SequenceTab,
  StructureTab,
} from "../tabs";
import { ph } from "../tabs/PhasesTab.strings";
import { pt } from "../tabs/ProjectTab.strings";
import "./shell.css";

// "project" is first (V2a P4) and, being new, has no central StringKey — its
// label lives in ProjectTab.strings.ts's colocated dictionary (`pt`) instead,
// mirroring shell.strings.ts's `st()` pattern. See tabLabel() below.
const TAB_ORDER: { id: TabId; key: StringKey | null }[] = [
  { id: "project", key: null },
  { id: "phases", key: null },
  { id: "fit", key: "tab.fit" },
  { id: "param", key: "tab.param" },
  { id: "hyp", key: "tab.hyp" },
  { id: "pid", key: "tab.pid" },
  { id: "seq", key: "tab.seq" },
  { id: "struct", key: "tab.struct" },
  { id: "ledger", key: "tab.ledger" },
];

const TAB_COMPONENTS: Record<TabId, () => ReactElement> = {
  project: ProjectTab,
  phases: PhasesTab,
  fit: FitTab,
  param: ParametersTab,
  hyp: HypothesesTab,
  pid: PhaseIdTab,
  seq: SequenceTab,
  struct: StructureTab,
  ledger: LedgerTab,
};

/** Shared analysis canvas (identical in both modes): 34px tab strip + a
 * scrolling body. Each tab is its own file — see components/tabs. */
export function CentreCanvas() {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  const Active = TAB_COMPONENTS[state.tab];

  return (
    <div className="centre-canvas">
      <div className="tab-strip">
        {TAB_ORDER.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tab-strip__btn${state.tab === tab.id ? " tab-strip__btn--active" : ""}`}
            onClick={() => dispatch({ type: "SET_TAB", tab: tab.id })}
          >
            {tab.key ? t(tab.key) : tab.id === "phases" ? ph(lang, "tab.phases") : pt(lang, "tab.project")}
          </button>
        ))}
      </div>
      <div className="centre-canvas__body tg-scroll">
        <Active />
      </div>
    </div>
  );
}
