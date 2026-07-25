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

// Which background job kind currently (or most recently) owns the shared
// GSAS job slot (api-contract.md §解析ループ: "ジョブ枠は 1 つ"). Mirrors
// state/types.ts ActiveJob minus the "no job has ever run yet" case, which
// RefineStatus.kind represents as `null` instead (see below).
export type JobKind = "refine" | "phaseid" | "multistart";

export interface RefineStatus {
  status: RefineJobStatus;
  elapsed_s: number | null;
  last_event: string | null;
  error: string | null;
  // Added by api-contract.md's kind revision (セルフレビュー指摘 #1). Optional
  // for the same reason as ShellState.source/refine below — existing
  // fixtures predate this field and a missing key must not crash. `null`
  // means the shared job slot has never been started this session (server
  // reports it only while `status !== "idle"`); once started, it retains
  // the last-started kind even after "done"/"failed".
  kind?: JobKind | null;
}

// "none" | "demo" | "project" — no project loaded (Welcome screen) vs real
// project connection vs seeded demo data (api-contract.md §プロジェクトライフサイクル).
export type SourceMode = "none" | "demo" | "project";

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
  // project モード時は project.json の絶対パス。demo/none では null (api-contract.md
  // §プロジェクトライフサイクル). Optional for the same reason as `source` above.
  project_path?: string | null;
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
  // Optional (judgment call, mirrors the ProjectHistogramRow precedent
  // above): api-contract.md's candidates example doesn't show this field,
  // but POST /api/phaseid/add needs {formula, mp_id} to materialise a
  // specific candidate's CIF, and candidates originate from identify_phases
  // against Materials Project (the already-in-model PhaseRow above carries
  // the analogous mp_id). Optional so fixtures that predate it keep
  // compiling; ADD AS PHASE disables itself when a row has none.
  mp_id?: string;
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

// — PROJECT tab (V2a P3/P4, api-contract.md §プロジェクトライフサイクル) —

/** Row shape for the PROJECT tab's HISTOGRAMS table. NOTE (judgment call):
 * api-contract.md documents the add/remove/settings *mutating* endpoints for
 * histograms but does not yet document a read shape carrying data_path /
 * instrument_path / radiation / geometry / data_format / two_theta_limits /
 * bank together (viewmodel.datasets is a display summary — id/name/meta/probe
 * — not structured enough to drive per-field edit/remove controls). This
 * mirrors the existing precedent of FitViewModel.plot / SequenceChart.series /
 * HypothesesViewModel.basin: an additive, optional field anticipating a
 * doc revision. docs/ is read-only for this task (parallel backend work), so
 * the contract update is left for reconciliation — see the frontend agent's
 * final report. */
export interface ProjectHistogramRow {
  id: string;
  data_path: string;
  instrument_path: string;
  radiation: string;
  geometry: string;
  data_format: string;
  two_theta_limits: [number, number] | null;
  bank: number | null;
}

export interface ProjectPhaseRow {
  name: string;
  structure_path: string;
}

export interface ProjectSettingsData {
  two_theta_limits: [number, number] | null;
  background_coeffs: number | null;
  max_cyc: number | null;
}

export interface ProjectViewModel {
  histograms: ProjectHistogramRow[];
  phases: ProjectPhaseRow[];
  settings: ProjectSettingsData;
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
  // Optional: see ProjectViewModel's doc comment above (FitViewModel.plot
  // precedent). Absent/undefined ⇒ ProjectTab renders empty-state tables
  // (empty-state principle, V2_PLAN.md §横断の不変条件 — never fabricate rows).
  project?: ProjectViewModel;
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

// — PROJECT lifecycle mutating endpoints (api-contract.md §プロジェクトライフサイクル) —

export interface ProjectCreateRequest {
  name: string;
  directory: string;
}

export interface ProjectOpenRequest {
  path: string;
}

export interface RecentProject {
  name: string;
  path: string;
  last_opened: string;
}

export interface RecentProjectsResponse {
  projects: RecentProject[];
}

export type UploadKind = "data" | "instrument" | "structure";

export interface UploadResponse {
  stored_path: string;
}

export interface AddHistogramRequest {
  data_path: string;
  instrument_path: string;
  radiation: string;
  geometry: string;
  data_format: string;
  two_theta_limits?: [number, number] | null;
  bank?: number | null;
}

export interface AddPhaseRequest {
  structure_path: string;
  phase_name: string;
}

export interface ProjectSettingsRequest {
  two_theta_limits?: [number, number] | null;
  background_coeffs?: number | null;
  max_cyc?: number | null;
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

// api-contract.md `POST /api/refine`: staged-release recipe ON/OFF per
// stage number ("01".."08"). Omitted key = default; false = actually skipped
// by the real run, not just hidden client-side (A1 — see gates.ts
// computeStagesOn, the only path from the UI's gating to a real run).
export interface RefineRequest {
  stages_on?: Record<string, boolean>;
}

// — 解析ループ (V2a' A4/A5/A6, api-contract.md §解析ループ) —

export type PhaseIdMode = "pattern" | "residual";

export interface PhaseIdRequest {
  mode: PhaseIdMode;
  top_k?: number;
}

export interface PhaseIdAddRequest {
  formula: string;
  mp_id: string;
}

export interface MultistartRequest {
  n_starts?: number;
  scale?: number;
}

// 202 {"status": "started"} for POST /api/phaseid and /api/multistart — both
// only exist in project mode (no demo "recorded" branch like RefineResponse:
// every project-mode call launches a real background job). 409 (job slot
// busy) surfaces as an ApiError, not this shape.
export interface JobStartResponse {
  status: "started";
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
