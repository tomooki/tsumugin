// Pure reducer — kept free of React/DOM so it is unit-testable in isolation
// (see src/state/reducer.test.ts). Mirrors the mutator methods on
// `class Component` in the handoff prototype (editSite/toggleRelease/
// toggleParam/onAddAtom/onApplyEdits/onDiscardEdits/…).
import type { Site } from "../api/types";
import type { Action } from "./actions";
import { initialWorkbenchState, type WorkbenchState } from "./types";

export { initialWorkbenchState };

/** Working site list: unapplied edits > applied baseline > server seed. */
export function siteList(state: WorkbenchState): Site[] {
  return state.sites ?? state.appliedSites ?? state.viewModel?.structure.sites ?? [];
}

function nextSiteId(list: Site[]): string {
  const numericIds = list
    .map((s) => Number.parseInt(s.id.replace(/\D/g, ""), 10))
    .filter((n) => !Number.isNaN(n));
  const max = numericIds.length > 0 ? Math.max(...numericIds) : 0;
  return `s${max + 1}`;
}

export function reducer(state: WorkbenchState, action: Action): WorkbenchState {
  switch (action.type) {
    case "SET_LANG":
      return { ...state, lang: action.lang };

    case "SET_MODE":
      return { ...state, mode: action.mode };

    case "SET_TAB":
      return { ...state, tab: action.tab };

    case "SET_HIST":
      return { ...state, hist: action.hist };

    case "SET_HYP":
      return { ...state, hyp: action.hyp };

    case "TOGGLE_PARAM_REL": {
      const cur = action.key in state.paramRel ? state.paramRel[action.key] : action.fallback;
      return { ...state, paramRel: { ...state.paramRel, [action.key]: !cur } };
    }

    case "SET_PARAM_GROUP": {
      const next = { ...state.paramRel };
      for (const key of action.keys) next[key] = action.value;
      return { ...state, paramRel: next };
    }

    case "SET_PARAM_VALUE":
      return { ...state, paramValue: { ...state.paramValue, [action.key]: action.value } };

    case "EDIT_SITE": {
      const list = siteList(state);
      return {
        ...state,
        sites: list.map((r) => (r.id === action.id ? { ...r, [action.field]: action.value } : r)),
        edits: state.edits + 1,
        applied: false,
      };
    }

    case "TOGGLE_SITE_RELEASE": {
      const list = siteList(state);
      return {
        ...state,
        sites: list.map((r) =>
          r.id === action.id
            ? { ...r, rel: { ...r.rel, [action.field]: !r.rel[action.field] } }
            : r,
        ),
      };
    }

    case "ADD_ATOM": {
      const list = siteList(state);
      const id = nextSiteId(list);
      const newSite: Site = {
        id,
        label: id.toUpperCase(),
        el: "O",
        x: "0.0000",
        y: "0.0000",
        z: "0.0000",
        occ: "1.000",
        uiso: "0.025",
        note: "new",
        lock: {},
        rel: {},
      };
      return { ...state, sites: [...list, newSite], edits: state.edits + 1, applied: false };
    }

    case "DELETE_SITE": {
      const list = siteList(state);
      return {
        ...state,
        sites: list.filter((r) => r.id !== action.id),
        edits: state.edits + 1,
        applied: false,
      };
    }

    case "APPLY_EDITS":
      return {
        ...state,
        appliedSites: siteList(state),
        sites: null,
        edits: 0,
        applied: true,
      };

    case "DISCARD_EDITS":
      // Only unapplied edits are discarded; with zero pending edits this is a
      // no-op (the DISCARD control is disabled in that state, see UI).
      if (state.edits === 0) return state;
      return { ...state, sites: null, edits: 0 };

    case "TOGGLE_OPEN":
      return { ...state, open: { ...state.open, [action.id]: !state.open[action.id] } };

    case "TOGGLE_STAGE":
      return { ...state, stageOn: { ...state.stageOn, [action.nn]: !state.stageOn[action.nn] } };

    case "SET_APPROVAL":
      return { ...state, approval: { ...state.approval, [action.actionId]: action.approval } };

    case "SET_REVIEW":
      return { ...state, review: { ...state.review, [action.id]: action.decision } };

    case "SET_DRAFT":
      return { ...state, draft: action.draft };

    case "SET_SHELL":
      // Re-sync the local refine status from the server on every shell fetch
      // (initial load, mode switch, post-refine refetch) — this is what makes
      // a page reload mid-job still show the running badge/disabled button,
      // not just OperatorConsole's own poll loop. shell.refine is optional
      // (older fixtures), so a missing field leaves the local value as-is.
      return {
        ...state,
        shell: action.shell,
        mode: action.shell.mode,
        refine: action.shell.refine ?? state.refine,
      };

    case "SET_VIEW_MODEL": {
      // stageOn is client-local UI state that mirrors the server's stages[].released
      // truth (see docs/design/gui-workbench/api-contract.md). On every fresh
      // viewmodel fetch we resync it from the server so a page reload (or a
      // stage change made through another path) never leaves stageOn stale. An
      // empty stages array (e.g. some test fixtures) means "no data yet" — keep
      // whatever stageOn already holds rather than clobbering it with {}.
      const stages = action.viewModel.stages;
      const stageOn =
        stages.length > 0
          ? Object.fromEntries(stages.map((s) => [Number(s.nn), s.released]))
          : state.stageOn;
      // hist ids are server data (demo: sxrd/…, project: h0/…). If the current
      // selection does not exist in this viewmodel, re-point it to the active
      // (or first) histogram so FIT/PARAMETERS never dereference a stranded id.
      const hists = action.viewModel.fit?.histograms ?? [];
      let hist = state.hist;
      if (hists.length > 0 && !hists.some((h) => h.id === hist)) {
        hist = (hists.find((h) => h.active) ?? hists[0]).id;
      }
      return { ...state, viewModel: action.viewModel, stageOn, hist };
    }

    case "APPEND_TRANSCRIPT_MESSAGE": {
      // Local-only transcript append (composer echo). Deliberately does NOT go
      // through SET_VIEW_MODEL: that action treats its payload as server truth
      // and resyncs stageOn from stages[].released, which would silently undo
      // optimistic TOGGLE_STAGE updates when the reused viewModel is stale.
      if (!state.viewModel) return state;
      return {
        ...state,
        viewModel: {
          ...state.viewModel,
          transcript: [...state.viewModel.transcript, action.message],
        },
      };
    }

    case "SET_REFINE_STATUS":
      return { ...state, refine: action.refine };

    case "SET_LOADING":
      return { ...state, loading: action.loading };

    case "SET_ERROR":
      return { ...state, error: action.error };

    default:
      return state;
  }
}
