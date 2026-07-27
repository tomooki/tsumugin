// Type shapes for the Workbench API (v1). Source of truth:
// docs/design/gui-workbench/api-contract.md — keep 1:1 with that document.
// Breaking changes must update the doc first.

export type GuiMode = "manual" | "auto";
export type FinalSelectionMode = "human" | "agent";

// api-contract.md §エージェント権限モード (`agent_policy`): "approve" (既定,
// propose_* は起票のみ・人間の承認で実行) | "auto" (propose_* が即時自動適用,
// カードは auto_applied) | "bypass" (即時自動適用 + project ライフサイクルも
// エージェントに開放). Changing it is human-only (shim has no tool for it —
// self-escalation is the one absolute boundary, mirrored by approval
// self-decision).
export type AgentPolicy = "approve" | "auto" | "bypass";

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
  // Dynamic (evaluated per GET /api/state, not seed) — whether GSAS-II
  // (GSASIIscriptable) is importable in this backend process. Tier1 desktop
  // sidecar bundles core + web extra only; GSAS-II is a local-install
  // prerequisite (desktop/README.md). When false, refine/multistart/sequential
  // job requests fail with 422 {"error_type": "GSASUnavailableError"}.
  gsas_available: boolean;
  // api-contract.md §アプリ設定 (資格情報): whether a Materials Project API
  // key is available (settings file or MATERIALS_PROJECT_API env var) —
  // used to pre-disable phase-identification controls (mirrors
  // gsas_available's precedent above) before a POST that needs it 422s.
  // Optional so pre-existing fixtures (which predate this field) keep
  // compiling; a missing value is treated as available (see
  // PhaseIdTab/StatusBar) so those controls are not spuriously disabled
  // against an older server.
  mp_available?: boolean;
}

export interface AgentStatus {
  tokens: number;
  wall_time_s: number;
  idle: boolean;
  // Added by api-contract.md §AUTO 実 LLM ブリッジ (V3a): whether the local
  // `claude` CLI / claude-agent-sdk bridge is importable in this backend
  // process (mirrors BackendStatus.gsas_available's precedent — a runtime
  // capability flag, not seed data). Optional so pre-V3a fixtures (which
  // predate this field) keep compiling; a missing value is treated as
  // available (see AgentSession.tsx) so the composer isn't spuriously
  // disabled against an older server.
  available?: boolean;
  // Added by api-contract.md §エージェント権限モード (V3a agent_policy):
  // "approve"|"auto"|"bypass", human-switchable via POST /api/agent/policy.
  // Optional for the same pre-V3a-fixture reason as `available` above — a
  // missing value is treated as "approve" (the documented default) by
  // AgentPolicySegment rather than crashing against an older server.
  policy?: AgentPolicy;
}

// GET /api/agent/status (api-contract.md §AUTO 実 LLM ブリッジ, V3a) — the
// dedicated poll endpoint AgentSession hits every 2s while an agent turn is
// in flight. Deliberately NOT reusing RefineStatus/JobKind's "idle" |
// "running" | "done" | "failed" vocabulary: there is no terminal "done" here
// (the bridge just returns to "idle" once the agent turn completes), and the
// shape carries `available`/`tokens`/`wall_time_s`/`error` inline rather than
// elapsed_s/last_event/kind — hence hooks/usePollJob.ts (typed to
// RefineStatus) is not reused for this poll loop (see AgentSession.tsx).
export type AgentJobState = "idle" | "running" | "failed";

export interface AgentJobStatus {
  status: AgentJobState;
  available: boolean;
  tokens: number;
  wall_time_s: number;
  error: string | null;
}

// "idle" | "running" | "done" | "failed" (api-contract.md GET /api/refine/status).
export type RefineJobStatus = "idle" | "running" | "done" | "failed";

// Which background job kind currently (or most recently) owns the shared
// GSAS job slot (api-contract.md §解析ループ: "ジョブ枠は 1 つ"). Mirrors
// state/types.ts ActiveJob minus the "no job has ever run yet" case, which
// RefineStatus.kind represents as `null` instead (see below).
// "sequential" added by api-contract.md §逐次 / operando (V2b): "ジョブ枠は
// 既存と同一 (kind に "sequential" が加わる)".
export type JobKind = "refine" | "phaseid" | "multistart" | "sequential" | "mem";

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

/** Refined lattice, already formatted server-side (esd in parentheses when
 * available). `null` on the row until a refinement has produced one — the UI
 * shows a dash rather than inventing numbers. */
export interface PhaseCell {
  a: string;
  b: string;
  c: string;
  alpha: string;
  beta: string;
  gamma: string;
}

export interface PhaseRow {
  id: string;
  name: string;
  swatch: string;
  space_group: string;
  mp_id: string;
  wt_frac: string;
  // PHASES tab fields (api-contract.md §PHASES タブ). Optional: demo/seed rows
  // and pre-existing fixtures omit them, in which case the tab renders the
  // row without phase-scoped controls rather than crashing.
  structure_path?: string;
  refine_cell?: boolean;
  temperature?: number | null;
  cell?: PhaseCell | null;
  /** Recipe stages that touch this phase — read-only (see the tab's note). */
  stages?: string[];
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
  // The element system phase identification actually runs with, derived from
  // the current phases' CIFs server-side (api-contract.md phase_id.elements) —
  // NOT a fixed list. `[]` = no phases / CIFs unreadable / pymatgen missing, in
  // which case the UI says nothing about elements rather than inventing them.
  // Optional for the same reason as `project` below: an older server omits it.
  elements?: string[];
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

/** Row shape for `sequence.frames[]` (V2b B2/B3, api-contract.md §逐次 /
 * operando: "per-frame 表 `sequence.frames[]` ({frame, label, axis_value,
 * rwp, cells, fractions, changepoint})"). `cells`/`fractions` are
 * server-formatted display strings (mirrors PhaseIdCandidate.mwmsx/strain
 * above — the exact per-phase breakdown is rendered verbatim, not parsed
 * client-side). */
export interface SequenceFrameRow {
  frame: string;
  label: string;
  axis_value: number;
  rwp: number;
  cells: string;
  fractions: string;
  changepoint: boolean;
}

export interface SequenceViewModel {
  charts: SequenceChart[];
  anchors: SequenceAnchor[];
  note: string;
  segments: SequenceSegment[];
  // V2b B2/B3: populated once POST /api/sequential completes. Optional —
  // pre-V2b fixtures predate this field (mirrors SequenceChart.series /
  // HypothesesViewModel.basin's precedent above).
  frames?: SequenceFrameRow[];
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

// api-contract.md §MEM 密度マップ (V3b — FR-601): c 軸に垂直な中央スライス, values は
// ≤128×128 に間引き済み (values[nx][ny], row-major on the "a" axis).
export interface MemMap {
  axis: "c";
  index: number;
  nx: number;
  ny: number;
  values: number[][];
  vmin: number;
  vmax: number;
  unit: string;
}

export interface MemViewModel {
  map: MemMap | null;
  peaks: MemPeak[];
  note: string;
}

export interface StructureViewModel {
  sites: Site[];
  constraints: ConstraintRow[];
  mem_peaks: MemPeak[];
  // null/absent = MEM not yet run (empty-state) — see api-contract.md §MEM 密度マップ. Optional
  // (rather than required-but-nullable) so existing fixtures/tests that predate V3b need not all
  // grow a `mem: null` line — call sites already read it via `structure?.mem?.map ?? null`.
  mem?: MemViewModel | null;
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

// "temperature" | "time" | "index" — project.json's optional frame_axis
// (api-contract.md §逐次 / operando, V2b B1).
export type FrameAxis = "temperature" | "time" | "index";

/** Row shape for the PROJECT tab's FRAMES table (V2b B1). Same judgment-call
 * status as ProjectHistogramRow above: api-contract.md documents the
 * project.json shape (`{"data_path", "axis_value", "label"?}`) and the
 * POST /api/project/frames mutator, but not an explicit read shape for
 * viewmodel.project — this mirrors the existing histograms/phases precedent
 * (an additive optional field). `id` is a display key (server-assigned,
 * analogous to ProjectHistogramRow.id); `label` falls back to the id
 * server-side when the spec's optional label was omitted. */
export interface ProjectFrameRow {
  id: string;
  label: string;
  axis_value: number;
  data_path: string;
}

export interface ProjectViewModel {
  histograms: ProjectHistogramRow[];
  phases: ProjectPhaseRow[];
  settings: ProjectSettingsData;
  // V2b B1 additions — optional for the same reason as the fields above
  // (pre-V2b fixtures/backends omit them; ProjectTab/ContextBar/SequenceTab
  // treat an absent value the same as an empty frame column).
  frames?: ProjectFrameRow[];
  frame_axis?: FrameAxis;
}

export type TranscriptKind = "user" | "agent" | "tool" | "judgement" | "approval" | "escalation";

export interface TranscriptJudgementRow {
  label: string;
  rwp: number;
  bic: number;
  chosen: boolean;
}

export type ApprovalState = "pending" | "approved" | "rejected";

// api-contract.md §エージェント権限モード: "承認カードの state に
// `auto_applied` が加わる (auto/bypass で即時自動適用されたもの)" — a
// server-driven ModelAction card state distinct from ApprovalState above
// (which is also POST /api/approval's response shape — that endpoint is
// human-only and never returns "auto_applied"; see §人間専用 in the
// contract). Kept as its own type rather than widening ApprovalState so
// ApprovalResponse.state stays exactly "approved" | "rejected".
export type ApprovalCardState = ApprovalState | "auto_applied";

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
  state?: ApprovalCardState;
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
  // Fit quality carried by entries that came from a refinement (m7_stage /
  // refine_finished); null on every other kind — a mode switch has no Rwp.
  // Rendered as a BLANK cell, not "—": see api-contract.md GET /api/ledger.
  // Optional so an older server (or a fixture) that omits them still type-checks.
  rwp?: number | null;
  bic?: number | null;
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

// "echem" added by api-contract.md §逐次 / operando (V2b B4): "mpr は upload
// (kind="echem") 経由も可".
export type UploadKind = "data" | "instrument" | "structure" | "echem";

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
  // Element system to identify with (api-contract.md §相同定の元素系). Omit to
  // let the server derive it from the current phases' CIFs — for an unknown
  // sample there are no phases yet, so this is the primary path.
  elements?: string[];
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

// api-contract.md §AUTO 実 LLM ブリッジ (V3a): POST /api/transcript/message's
// OTHER success shape — mode=auto AND the agent bridge is available routes
// the message to the local Claude Code agent session and starts it
// asynchronously (202) instead of recording it as a plain transcript entry
// (200 TranscriptMessageResponse, the demo/manual/agent-unavailable
// fallback — unchanged). 409 (a turn is already running) surfaces as an
// ApiError, not this shape.
export interface TranscriptMessageAgentStartedResponse {
  status: "agent_started";
}

export type TranscriptMessagePostResponse =
  | TranscriptMessageResponse
  | TranscriptMessageAgentStartedResponse;

export interface ModeRequest {
  mode: GuiMode;
}

// POST /api/agent/policy (api-contract.md §エージェント権限モード). 200 →
// the updated ShellState (mirrors ModeRequest/postMode's shape); a turn in
// flight is 409, an unrecognised policy string is 422 — both ApiError, not
// this shape.
export interface AgentPolicyRequest {
  policy: AgentPolicy;
}

// — 逐次 / operando (V2b — B1〜B5, api-contract.md §逐次 / operando) —

/** project.json's per-frame entry (`{"data_path", "axis_value", "label"?}`).
 * Frames share histograms[0]'s instrument condition (M9 single-instrument
 * series assumption) — no per-frame instrument fields here. */
export interface FrameSpec {
  data_path: string;
  axis_value: number;
  label?: string;
}

export interface ProjectFramesRequest {
  frames: FrameSpec[];
}

export type SequentialMode = "forward" | "anchored";

export interface SequentialRequest {
  mode: SequentialMode;
  // frame_index (string key, matching JSON object key constraints) → phase
  // names present at that anchor frame.
  anchor_table?: Record<string, string[]>;
  use_charge_constraint?: boolean;
}

export interface EchemRequest {
  mpr_path: string;
  offset_s: number;
  interval_s: number;
  sign: -1 | 1;
  x0?: number;
}

// ② align_echem+alkali_budget の出力 (`{"curve", "targets", ...}` —
// api-contract.md leaves the full shape open-ended with "..."). `curve`/
// `targets` are rendered as opaque success evidence (row/point counts) by
// the PROJECT tab's ECHEM card; the fields the rest of the UI actually reads
// (channels, project.echem, sequence fraction overlay) come from the
// session-held server state via the follow-up GET /api/state +
// /api/viewmodel refetch, not from this response body directly.
export interface EchemSyncResponse {
  curve: unknown[];
  targets: unknown[];
  [key: string]: unknown;
}

// — MEM 密度マップ (V3b — FR-601, api-contract.md §MEM 密度マップ) —

export type MemMapType = "Fobs" | "delt-F";

export interface MemRequest {
  phase?: string;
  hist?: string;
  map_type?: MemMapType;
  dmin?: number;
  grid_step?: number;
}

// — アプリ設定 (資格情報) — Materials Project トークン (api-contract.md §アプリ設定) —

// GET /api/settings — masked credential state. 絶対規則: the key itself is
// never returned; mp_api_key_hint is a short masked tail (server-formatted,
// e.g. "ab12") or null when unset.
export interface SettingsState {
  mp_api_key_set: boolean;
  mp_api_key_hint: string | null;
  mp_api_key_source: "settings" | "env" | null;
}

export interface SettingsSetRequest {
  mp_api_key: string;
}

export type SettingsKey = "mp_api_key";

export interface SettingsClearRequest {
  key: SettingsKey;
}

// — ファイル選択 (Welcome のファイル選択ウィンドウ, api-contract.md §ファイル選択) —
// Web pages cannot read a real filesystem path out of <input type=file>, so
// the backend enumerates directories server-side and the frontend draws its
// own in-app picker window (PathPicker.tsx) against these two read-only
// endpoints instead of an OS file dialog.

export interface FsRoot {
  path: string;
  label: string;
}

export interface FsRootsResponse {
  roots: FsRoot[];
}

/** GET /api/fs/list only ever returns directories and `.json` files — never
 * other file kinds (the contract: "ディレクトリと `.json` のみ返す"). */
export interface FsEntry {
  name: string;
  path: string;
  is_dir: boolean;
  // Whether this directory has a project.json directly inside it (the
  // "open a project" target marker) — see PathPicker's mode="project" SELECT
  // gating.
  is_project: boolean;
}

export interface FsListing {
  path: string;
  parent: string | null;
  // Whether the *currently browsed* directory itself is a project (contains
  // project.json). Without this, arriving via "up" or a root — which don't go
  // through an entry row — leaves the picker unable to tell, so a directory
  // you can legitimately open has its SELECT button disabled.
  is_project?: boolean;
  entries: FsEntry[];
}

// — errors —

export interface ApiErrorBody {
  error: string;
  error_type: string;
}
