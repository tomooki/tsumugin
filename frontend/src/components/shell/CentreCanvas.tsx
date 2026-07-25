import type { ReactElement } from "react";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import type { TabId } from "../../state/types";
import {
  FitTab,
  HypothesesTab,
  LedgerTab,
  ParametersTab,
  PhaseIdTab,
  SequenceTab,
  StructureTab,
} from "../tabs";
import "./shell.css";

const TAB_ORDER: { id: TabId; key: "tab.fit" | "tab.param" | "tab.hyp" | "tab.pid" | "tab.seq" | "tab.struct" | "tab.ledger" }[] = [
  { id: "fit", key: "tab.fit" },
  { id: "param", key: "tab.param" },
  { id: "hyp", key: "tab.hyp" },
  { id: "pid", key: "tab.pid" },
  { id: "seq", key: "tab.seq" },
  { id: "struct", key: "tab.struct" },
  { id: "ledger", key: "tab.ledger" },
];

const TAB_COMPONENTS: Record<TabId, () => ReactElement> = {
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
  const { t } = useI18n();
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
            {t(tab.key)}
          </button>
        ))}
      </div>
      <div className="centre-canvas__body tg-scroll">
        <Active />
      </div>
    </div>
  );
}
