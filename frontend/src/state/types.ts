// State shape from docs/design/gui-workbench/handoff/README.md §State,
// extended with the server-supplied shell/viewmodel payloads that App.tsx
// fetches on mount (see docs/design/gui-workbench/api-contract.md).
import type { GuiMode, RefineStatus, ShellState, Site, ViewModel } from "../api/types";
import type { Lang } from "../i18n";

export type TabId = "fit" | "param" | "hyp" | "pid" | "seq" | "struct" | "ledger";
// Histogram ids are server data (demo: sxrd/nd1/nd2, project mode: h0, h1, …),
// not a closed vocabulary — a union type here silently strands `hist` on a
// nonexistent id when the data source changes (regression: project mode's
// "h0" plot never rendered because hist stayed "sxrd").
export type HistId = string;
export type ApprovalState = "pending" | "approved" | "rejected";
export type ReviewDecision = "accepted" | "sent_back";

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
  // key = TranscriptMessage.action_id — one decision per approval card, so two
  // pending ModelAction cards never leak state into each other (a single
  // ApprovalState here previously meant deciding card A also disabled/labelled
  // card B, since both read the same value).
  approval: Record<string, ApprovalState>;
  review: Record<string, ReviewDecision>;
  draft: string;

  // server-fetched data (App.tsx loads these via getState/getViewModel)
  shell: ShellState | null;
  viewModel: ViewModel | null;
  loading: boolean;
  error: string | null;

  // Local, poll-driven refinement job status (RUN REFINEMENT flow). Seeded
  // from shell.refine on every SET_SHELL (so a reload while a job is running
  // server-side still shows it), then kept live by OperatorConsole's
  // getRefineStatus() polling loop — see api-contract.md GET /api/refine/status.
  refine: RefineStatus | null;
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
  approval: {},
  review: {},
  draft: "",

  shell: null,
  viewModel: null,
  loading: false,
  error: null,
  refine: null,
};
