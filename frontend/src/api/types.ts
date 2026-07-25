// Type shapes for the Workbench API (v1). Source of truth:
// docs/design/gui-workbench/api-contract.md — keep 1:1 with that document.
// Breaking changes must update the doc first.

export type GuiMode = "manual" | "auto";
export type FinalSelectionMode = "human" | "agent";

export interface EchemReadout {
  v: number;
  q_mah_g: number;
  x_echem: string;
}

export interface ProjectInfo {
  name: string;
  dataset: string;
  frame: string;
  echem: EchemReadout | null;
}

export interface LedgerStatus {
  count: number;
  verified: boolean;
}

export interface BackendStatus {
  backend_build: string;
  seed: number;
  mcp_tools: number;
}

export interface AgentStatus {
  tokens: number;
  wall_time_s: number;
  idle: boolean;
}

// "idle" | "running" | "done" | "failed" (api-contract.md GET /api/refine/status).
export type RefineJobStatus = "idle" | "running" | "done" | "failed";

export interface RefineStatus {
  status: RefineJobStatus;
  elapsed_s: number | null;
  last_event: string | null;
  error: string | null;
}

// "demo" | "project" — real project connection vs seeded demo data.
export type SourceMode = "demo" | "project";

export interface ShellState {
  project: ProjectInfo;
  mode: GuiMode;
  final_selection_mode: FinalSelectionMode;
  ledger: LedgerStatus;
  status: BackendStatus;
  agent: AgentStatus;
  // Added by the backend's api-contract.md revision. Optional here so the
  // existing seeded test fixtures (which predate these fields) keep compiling.
  source?: SourceMode;
  refine?: RefineStatus;
}

// — GET /api/viewmodel —

export interface DatasetRow {
  id: string;
  name: string;
  meta: string;
  probe: string;
  active: boolean;
}

export interface PhaseRow {
  id: string;
  name: string;
  swatch: string;
  space_group: string;
  mp_id: string;
  wt_frac: string;
}

export interface ChannelRow {
  id: string;
  label: string;
  value: string;
}

export interface SnapshotRow {
  id: string;
  note: string;
}

export interface FitMetric {
  key: string;
  label: string;
  value: string;
  note: string;
}

export interface FitHistogramChip {
  id: string;
  label: string;
  active: boolean;
}

export interface TwoThetaRange {
  min: number;
  max: number;
}

export interface FitHistoryRow {
  stage: string;
  rwp: number;
  /** null for the first stage of a real run — no predecessor to diff against. */
  delta_rwp: number | null;
  guard: string;
  reverted: boolean;
}

export interface FitValidityRow {
  check: string;
  status: "pass" | "warn" | "fail";
  detail: string;
}

// Real fit/residual curve for one histogram (hist id → FitPlotData | null).
// null = no curve yet (empty-state). Arrays are ≤2000 points, pre-decimated
// server-side (api-contract.md). yobs-only (ycalc/ybkg/residual/ticks null)
// means "loaded, not yet refined".
export interface FitPlotData {
  x: number[];
  yobs: number[];
  ycalc: number[] | null;
  ybkg: number[] | null;
  residual: number[] | null;
  ticks: Record<string, number[]>;
}

export type FitPlotMap = Record<string, FitPlotData | null>;

export interface FitViewModel {
  metrics: FitMetric[];
  histograms: FitHistogramChip[];
  limits_note: string;
  phase_ticks: string[];
  two_theta: TwoThetaRange;
  history: FitHistoryRow[];
  validity: FitValidityRow[];
  // Optional: added by the api-contract.md plot revision. Absent/undefined is
  // treated the same as an empty map (no curve for the active histogram) so
  // existing fixtures that predate this field keep compiling.
  plot?: FitPlotMap;
}

export interface ParamDropdown {
  label: string;
  value: string;
  options: string[];
}

export interface ParamRow {
  field: string;
  value: string;
  esd: string;
  released: boolean;
  locked: boolean;
}

export interface ParamCard {
  id: string;
  title: string;
  note: string;
  dropdown: ParamDropdown | null;
  rows: ParamRow[];
  footer: string;
}

export interface ParametersForHistogram {
  released_count: number;
  cards: ParamCard[];
}

export type ParametersViewModel = Record<string, ParametersForHistogram>;

export interface HypothesisRow {
  rank: number;
  id: string;
  phases: string;
  p: number;
  rwp: number;
  gof: number;
  bic: number;
  close: boolean;
  status: string;
  selected: boolean;
}

export interface HypothesisDiffRow {
  field: string;
  a: string;
  b: string;
  changed: boolean;
}

export interface HypothesisDiff {
  vs: string;
  rows: HypothesisDiffRow[];
}

export interface BasinPoint {
  x: number;
  y: number;
  label: string;
}

// Multistart lattice-basin scatter. null = no basin data (empty-state).
export interface BasinData {
  points: BasinPoint[];
}

export interface HypothesesViewModel {
  rows: HypothesisRow[];
  diff: HypothesisDiff;
  evidence: [string, string][];
  // Optional: added by the api-contract.md basin revision (see FitViewModel.plot note).
  basin?: BasinData | null;
}

export interface PhaseIdCandidate {
  rank: number;
  formula: string;
  source: string;
  sg: string;
  dara: number;
  mwmsx: string;
  strain: string;
  chem_guard: string;
  guard_fail: boolean;
}

export interface UnexplainedFeature {
  two_theta: number;
  sn: number;
  indexing: string;
}

export interface PhaseSetCompleteness {
  is_complete: boolean;
  notes: string[];
  flagged_frames: string;
}

export interface PhaseIdViewModel {
  candidates: PhaseIdCandidate[];
  unexplained: UnexplainedFeature[];
  completeness: PhaseSetCompleteness;
}

export interface ChartSeriesData {
  x: number[];
  ys: number[][];
  labels: string[];
}

export interface SequenceChart {
  id: string;
  title: string;
  // Optional: added by the api-contract.md series revision (see FitViewModel.plot note).
  // null = no series data yet (empty-state); undefined = fixture predates this field.
  series?: ChartSeriesData | null;
}

export interface SequenceAnchor {
  id: string;
  crossover: boolean;
}

export interface SequenceSegment {
  segment: string;
  forward: string;
  backward: string;
  rwp: string;
  total_bic: string;
  selected: string;
}

export interface SequenceViewModel {
  charts: SequenceChart[];
  anchors: SequenceAnchor[];
  note: string;
  segments: SequenceSegment[];
}

export interface SiteLock {
  x?: boolean;
  y?: boolean;
  z?: boolean;
}

export interface SiteRelease {
  x?: boolean;
  y?: boolean;
  z?: boolean;
  occ?: boolean;
  uiso?: boolean;
}

export interface Site {
  id: string;
  label: string;
  el: string;
  x: string;
  y: string;
  z: string;
  occ: string;
  uiso: string;
  note: string;
  lock: SiteLock;
  rel: SiteRelease;
}

export interface ConstraintRow {
  kind: string;
  text: string;
  ref: string;
}

export interface MemPeak {
  position: string;
  density: string;
  assign: string;
}

export interface StructureViewModel {
  sites: Site[];
  constraints: ConstraintRow[];
  mem_peaks: MemPeak[];
}

export type StageGate = "bkg" | "profile" | "sample" | "occ" | "micro" | null;

export interface StageRow {
  nn: string;
  name: string;
  flags: string;
  delta_rwp: string;
  released: boolean;
  gate: StageGate;
}

export type ReviewSeverity = "close" | "unknown" | "guard" | "echem";
export type ReviewState = "pending" | "accepted" | "sent_back";

export interface ReviewItem {
  id: string;
  severity: ReviewSeverity;
  title: string;
  ref: string;
  detail: string;
  state: ReviewState;
}

export type TranscriptKind = "user" | "agent" | "tool" | "judgement" | "approval" | "escalation";

export interface TranscriptJudgementRow {
  label: string;
  rwp: number;
  bic: number;
  chosen: boolean;
}

export type ApprovalState = "pending" | "approved" | "rejected";

export interface TranscriptMessage {
  id: string;
  kind: TranscriptKind;
  text?: string;
  tool?: string;
  layer?: string;
  secs?: number;
  args?: string;
  ret?: string;
  rows?: TranscriptJudgementRow[];
  action_id?: string;
  title?: string;
  rationale?: string;
  action_json?: string;
  state?: ApprovalState;
  fr?: string;
}

export interface ViewModel {
  datasets: DatasetRow[];
  phases: PhaseRow[];
  channels: ChannelRow[];
  snapshots: SnapshotRow[];
  fit: FitViewModel;
  parameters: ParametersViewModel;
  hypotheses: HypothesesViewModel;
  phase_id: PhaseIdViewModel;
  sequence: SequenceViewModel;
  structure: StructureViewModel;
  stages: StageRow[];
  review: ReviewItem[];
  transcript: TranscriptMessage[];
}

// — mutating endpoints —

export type Actor = "AGENT ③" | "MCP ②" | "CORE ①" | "HUMAN" | "GUARD";

export interface LedgerEntry {
  index: number;
  time: string;
  actor: Actor;
  text: string;
  hash: string;
  revert_to: string | null;
}

export interface LedgerResponse {
  entries: LedgerEntry[];
  verified: boolean;
}

export interface ReviewQueueResponse {
  items: ReviewItem[];
}

export interface AcceptRequest {
  by: "human" | "agent";
  reason: string;
}

export interface AcceptResponse {
  status: "accepted" | "recommend_only";
  [key: string]: unknown;
}

export interface RevertRequest {
  hypothesis_id: string;
  note: string;
}

export interface RevertResponse {
  status: "reverted";
}

export interface ReviewResolveRequest {
  action: "accept" | "send_back";
  note: string;
}

export interface ReviewResolveResponse {
  item: ReviewItem;
}

export interface StructureApplyRequest {
  sites: Site[];
  note: string;
}

export interface StructureApplyResponse {
  snapshot_id: string;
  ledger_index: number;
}

export type ApprovalDecision = "approve" | "reject";

export interface ApprovalRequest {
  decision: ApprovalDecision;
}

export interface ApprovalResponse {
  state: ApprovalState;
  snapshot_id: string | null;
  ledger_index: number;
}

export type StageAction = "release" | "revert";

export interface StageActionRequest {
  action: StageAction;
}

export interface StageActionResponse {
  stage: StageRow;
}

// 202 {"status": "started"} when a real refinement job is launched in the
// background, or {"status": "recorded"} in demo mode (project not connected,
// no background job — recorded to ledger only). 409 is a rejected request
// (job already running) and surfaces as an ApiError, not this shape.
export interface RefineResponse {
  status: "started" | "recorded";
}

export interface TranscriptMessageRequest {
  text: string;
}

export interface TranscriptMessageResponse {
  message: TranscriptMessage;
}

export interface ModeRequest {
  mode: GuiMode;
}

// — errors —

export interface ApiErrorBody {
  error: string;
  error_type: string;
}
