// State shape from docs/design/gui-workbench/handoff/README.md §State,
// extended with the server-supplied shell/viewmodel payloads that App.tsx
// fetches on mount (see docs/design/gui-workbench/api-contract.md).
import type { GuiMode, JobKind, RefineStatus, ShellState, Site, ViewModel } from "../api/types";
import type { Lang } from "../i18n";

// "project" is first (V2a P4 — new PROJECT tab, see CentreCanvas.tsx TAB_ORDER
// and LeftRail's "+" shortcuts). Default state.tab below stays "fit" so
// existing default-tab expectations are unaffected.
export type TabId =
  | "project"
  | "phases"
  | "fit"
  | "param"
  | "hyp"
  | "pid"
  | "seq"
  | "struct"
  | "ledger";
// Histogram ids are server data (demo: sxrd/nd1/nd2, project mode: h0, h1, …),
// not a closed vocabulary — a union type here silently strands `hist` on a
// nonexistent id when the data source changes (regression: project mode's
// "h0" plot never rendered because hist stayed "sxrd").
export type HistId = string;
export type ApprovalState = "pending" | "approved" | "rejected";
export type ReviewDecision = "accepted" | "sent_back";
// Which background job currently owns the shared GSAS job slot (api-contract.md
// §解析ループ: "ジョブ枠は 1 つ (refine/phaseid/multistart は相互に 409)"). The
// three job kinds all report their running/done/failed status through the
// single `refine` slot below (so RUN REFINEMENT / IDENTIFY / MULTISTART can
// disable each other), but each kind is polled on its own endpoint — this
// field tells each job-owning component whether IT is the one that should be
// hitting its status endpoint right now (see hooks/usePollJob.ts `enabled`).
// `null` = no job owns the slot right now. Reuses api/types.ts's JobKind (the
// server-reported RefineStatus.kind) so the two stay structurally identical.
export type ActiveJob = JobKind | null;

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

  // Local, poll-driven job status — SHARED by RUN REFINEMENT (A1), IDENTIFY
  // (A4) and MULTISTART (A5): all three write/read this one slot, mirroring
  // the backend's single job slot (api-contract.md §解析ループ). Seeded from
  // shell.refine on every SET_SHELL (so a reload while a job is running
  // server-side still shows it — shell.refine only ever describes the RUN
  // REFINEMENT job, see ActiveJob doc comment above), then kept live by
  // whichever component's usePollJob is `enabled` per `activeJob` below.
  refine: RefineStatus | null;
  activeJob: ActiveJob;

  // Whether an agent turn (the V3a AUTO bridge, api-contract.md §AUTO 実
  // LLM ブリッジ) is currently running. AgentSession owns the detailed
  // AgentJobStatus (tokens/wall_time/error) as local component state (see
  // its file docstring — the bridge is its own independent job lane, not
  // the shared GSAS `refine`/`activeJob` slot above) and syncs just this
  // boolean here so sibling components in the same right-pane header —
  // AgentPolicySegment — can gate on "a turn is in flight" (api-contract.md
  // §エージェント権限モード: "エージェントのターン実行中は 409") without a
  // second independent poll loop.
  agentTurnRunning: boolean;

  // Client-only selected-frame cursor for the ContextBar's "fr k / N" nav
  // (V2b B2/B3) — not server state. Index into viewModel.project.frames
  // (input spec) / viewModel.sequence.frames (per-frame results), which are
  // expected to be positionally aligned once a sequential run has completed.
  // Consumers clamp against their own array length rather than trusting this
  // is always in range (e.g. after a frame column edit shrinks the count).
  frameIndex: number;
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
  activeJob: null,
  agentTurnRunning: false,
  frameIndex: 0,
};
