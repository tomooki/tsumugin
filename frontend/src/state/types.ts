// State shape from docs/design/gui-workbench/handoff/README.md §State,
// extended with the server-supplied shell/viewmodel payloads that App.tsx
// fetches on mount (see docs/design/gui-workbench/api-contract.md).
import type { GuiMode, ShellState, Site, ViewModel } from "../api/types";
import type { Lang } from "../i18n";

export type TabId = "fit" | "param" | "hyp" | "pid" | "seq" | "struct" | "ledger";
export type HistId = "sxrd" | "nd" | "nd2";
export type ApprovalState = "pending" | "approved" | "rejected";
export type ReviewDecision = "accepted" | "sent";

export interface WorkbenchState {
  lang: Lang;
  mode: GuiMode;
  tab: TabId;
  hist: HistId;
  hyp: string;

  sites: Site[] | null;
  appliedSites: Site[] | null;
  edits: number;
  applied: boolean;

  // key = `${hist}.${group}.${name}`
  paramRel: Record<string, boolean>;
  paramValue: Record<string, string>;

  open: Record<string, boolean>;
  stageOn: Record<number, boolean>;
  approval: ApprovalState;
  review: Record<string, ReviewDecision>;
  draft: string;

  // server-fetched data (App.tsx loads these via getState/getViewModel)
  shell: ShellState | null;
  viewModel: ViewModel | null;
  loading: boolean;
  error: string | null;
}

export const initialWorkbenchState: WorkbenchState = {
  lang: "en",
  mode: "manual",
  tab: "fit",
  hist: "sxrd",
  hyp: "H-014",

  sites: null,
  appliedSites: null,
  edits: 0,
  applied: false,

  paramRel: {},
  paramValue: {},

  open: {},
  stageOn: { 1: true, 2: true, 3: true, 4: true, 5: true, 6: false, 7: false, 8: false },
  approval: "pending",
  review: {},
  draft: "",

  shell: null,
  viewModel: null,
  loading: false,
  error: null,
};
