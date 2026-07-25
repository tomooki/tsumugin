// Typed fetch wrapper for the Workbench API (v1). Same-origin base URL — the
// dev server proxies /api to the FastAPI backend (see vite.config.ts); in
// Tauri the frontend and the sidecar share an origin too.
import type {
  AcceptRequest,
  AcceptResponse,
  AddHistogramRequest,
  AddPhaseRequest,
  AgentJobStatus,
  ApiErrorBody,
  ApprovalDecision,
  ApprovalResponse,
  EchemRequest,
  EchemSyncResponse,
  JobStartResponse,
  LedgerResponse,
  ModeRequest,
  MultistartRequest,
  PhaseIdAddRequest,
  PhaseIdRequest,
  ProjectCreateRequest,
  ProjectFramesRequest,
  ProjectOpenRequest,
  ProjectSettingsRequest,
  RecentProjectsResponse,
  RefineRequest,
  RefineResponse,
  RefineStatus,
  ReviewQueueResponse,
  ReviewResolveRequest,
  ReviewResolveResponse,
  RevertRequest,
  RevertResponse,
  SequentialRequest,
  ShellState,
  StageAction,
  StageActionResponse,
  StructureApplyRequest,
  StructureApplyResponse,
  TranscriptMessageAgentStartedResponse,
  TranscriptMessagePostResponse,
  UploadKind,
  UploadResponse,
  ViewModel,
} from "./types";

export class ApiError extends Error {
  readonly error_type: string;
  readonly status: number;

  constructor(body: ApiErrorBody, status: number) {
    super(body.error);
    this.name = "ApiError";
    this.error_type = body.error_type;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData bodies (uploadProjectFile) must NOT get a forced "Content-Type:
  // application/json" — the browser needs to set its own multipart boundary,
  // and a JSON header on a multipart body would make the server reject it.
  const isForm = init?.body instanceof FormData;
  const res = await fetch(path, {
    ...init,
    headers: isForm
      ? init?.headers
      : {
          "Content-Type": "application/json",
          ...(init?.headers ?? {}),
        },
  });

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = null;
  }

  if (!res.ok) {
    const errBody =
      body && typeof body === "object" && "error" in body && "error_type" in body
        ? (body as ApiErrorBody)
        : { error: res.statusText || "request failed", error_type: "http_error" };
    throw new ApiError(errBody, res.status);
  }

  return body as T;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

function post<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(payload) });
}

export function getState(): Promise<ShellState> {
  return get<ShellState>("/api/state");
}

export function postMode(mode: ModeRequest["mode"]): Promise<ShellState> {
  return post<ShellState>("/api/mode", { mode } satisfies ModeRequest);
}

export function getViewModel(): Promise<ViewModel> {
  return get<ViewModel>("/api/viewmodel");
}

export function getLedger(): Promise<LedgerResponse> {
  return get<LedgerResponse>("/api/ledger");
}

export function getReviewQueue(): Promise<ReviewQueueResponse> {
  return get<ReviewQueueResponse>("/api/review-queue");
}

export function getHypotheses(): Promise<ViewModel["hypotheses"]> {
  return get<ViewModel["hypotheses"]>("/api/hypotheses");
}

export function postHypothesisAccept(
  id: string,
  payload: AcceptRequest,
): Promise<AcceptResponse> {
  return post<AcceptResponse>(`/api/hypotheses/${encodeURIComponent(id)}/accept`, payload);
}

export function postRevert(payload: RevertRequest): Promise<RevertResponse> {
  return post<RevertResponse>("/api/revert", payload);
}

export function postReviewResolve(
  id: string,
  payload: ReviewResolveRequest,
): Promise<ReviewResolveResponse> {
  return post<ReviewResolveResponse>(`/api/review-queue/${encodeURIComponent(id)}/resolve`, payload);
}

export function postStructureApply(
  payload: StructureApplyRequest,
): Promise<StructureApplyResponse> {
  return post<StructureApplyResponse>("/api/structure/apply", payload);
}

export function postApproval(
  actionId: string,
  decision: ApprovalDecision,
): Promise<ApprovalResponse> {
  return post<ApprovalResponse>(`/api/approval/${encodeURIComponent(actionId)}`, { decision });
}

export function postStage(nn: string, action: StageAction): Promise<StageActionResponse> {
  return post<StageActionResponse>(`/api/stages/${encodeURIComponent(nn)}`, { action });
}

export function postRefine(payload: RefineRequest = {}): Promise<RefineResponse> {
  return post<RefineResponse>("/api/refine", payload);
}

export function getRefineStatus(): Promise<RefineStatus> {
  return get<RefineStatus>("/api/refine/status");
}

// — 解析ループ (V2a' A4/A5/A6, api-contract.md §解析ループ) —

export function postPhaseId(payload: PhaseIdRequest): Promise<JobStartResponse> {
  return post<JobStartResponse>("/api/phaseid", payload);
}

export function getPhaseIdStatus(): Promise<RefineStatus> {
  return get<RefineStatus>("/api/phaseid/status");
}

export function postPhaseIdAdd(payload: PhaseIdAddRequest): Promise<ShellState> {
  return post<ShellState>("/api/phaseid/add", payload);
}

export function postMultistart(payload: MultistartRequest = {}): Promise<JobStartResponse> {
  return post<JobStartResponse>("/api/multistart", payload);
}

export function getMultistartStatus(): Promise<RefineStatus> {
  return get<RefineStatus>("/api/multistart/status");
}

// GET /api/export/gpx (A6) — a plain download link, not a fetch() call (the
// browser needs to drive the Content-Disposition download itself), so this
// is just the single source of truth for the path rather than a request()
// wrapper function.
export const EXPORT_GPX_PATH = "/api/export/gpx";

// api-contract.md §AUTO 実 LLM ブリッジ (V3a): 200 {"message"} (demo/manual/
// agent-unavailable fallback, recorded to the transcript only) OR 202
// {"status": "agent_started"} (mode=auto + agent available: the message is
// handed to the local Claude Code agent session and runs asynchronously).
// 409 (a turn is already running) surfaces as an ApiError. Callers narrow the
// union with isAgentStartedResponse below.
export function postTranscriptMessage(text: string): Promise<TranscriptMessagePostResponse> {
  return post<TranscriptMessagePostResponse>("/api/transcript/message", { text });
}

/** Narrows postTranscriptMessage's response union to the agent-started
 * branch (202). */
export function isAgentStartedResponse(
  res: TranscriptMessagePostResponse,
): res is TranscriptMessageAgentStartedResponse {
  return "status" in res && res.status === "agent_started";
}

// GET /api/agent/status (api-contract.md §AUTO 実 LLM ブリッジ, V3a) — the
// dedicated poll endpoint for an in-flight agent turn (see api/types.ts
// AgentJobStatus for why this is not RefineStatus/usePollJob).
export function getAgentStatus(): Promise<AgentJobStatus> {
  return get<AgentJobStatus>("/api/agent/status");
}

// — PROJECT lifecycle (V2a P3/P4, api-contract.md §プロジェクトライフサイクル) —

export function postProjectCreate(payload: ProjectCreateRequest): Promise<ShellState> {
  return post<ShellState>("/api/project", payload);
}

export function postProjectOpen(payload: ProjectOpenRequest): Promise<ShellState> {
  return post<ShellState>("/api/project/open", payload);
}

export function postProjectClose(): Promise<ShellState> {
  return post<ShellState>("/api/project/close", {});
}

export function postProjectDemo(): Promise<ShellState> {
  return post<ShellState>("/api/project/demo", {});
}

export function getRecentProjects(): Promise<RecentProjectsResponse> {
  return get<RecentProjectsResponse>("/api/project/recent");
}

// multipart upload — file copied server-side into the project's data/
// directory (self-contained project). `request()` detects the FormData body
// and skips the default JSON Content-Type header (see above).
export function uploadProjectFile(file: File, kind: UploadKind): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  return request<UploadResponse>("/api/project/upload", { method: "POST", body: form });
}

// Response is ShellState ("state+viewmodel 反映" per api-contract.md) — the
// updated histogram/phase/settings rows land in the *viewmodel*, so callers
// must follow up with getViewModel() to see them (ProjectTab does this after
// every mutating call, mirroring OperatorConsole's post-action refetch).
export function postAddHistogram(payload: AddHistogramRequest): Promise<ShellState> {
  return post<ShellState>("/api/project/histograms", payload);
}

export function postRemoveHistogram(histId: string): Promise<ShellState> {
  return post<ShellState>(`/api/project/histograms/${encodeURIComponent(histId)}/remove`, {});
}

export function postAddPhase(payload: AddPhaseRequest): Promise<ShellState> {
  return post<ShellState>("/api/project/phases", payload);
}

export function postRemovePhase(phaseName: string): Promise<ShellState> {
  return post<ShellState>(`/api/project/phases/${encodeURIComponent(phaseName)}/remove`, {});
}

export function postProjectSettings(payload: ProjectSettingsRequest): Promise<ShellState> {
  return post<ShellState>("/api/project/settings", payload);
}

// — 逐次 / operando (V2b — B1〜B5, api-contract.md §逐次 / operando) —

// Full-replace (idempotent set), not append — see api/types.ts
// ProjectFramesRequest's doc comment and the contract's "フレーム列を全置換".
export function postProjectFrames(payload: ProjectFramesRequest): Promise<ShellState> {
  return post<ShellState>("/api/project/frames", payload);
}

export function postSequential(payload: SequentialRequest): Promise<JobStartResponse> {
  return post<JobStartResponse>("/api/sequential", payload);
}

export function getSequentialStatus(): Promise<RefineStatus> {
  return get<RefineStatus>("/api/sequential/status");
}

// Synchronous (not a background job) — no .../status polling counterpart.
export function postEchem(payload: EchemRequest): Promise<EchemSyncResponse> {
  return post<EchemSyncResponse>("/api/echem", payload);
}
