// Typed fetch wrapper for the Workbench API (v1). Same-origin base URL — the
// dev server proxies /api to the FastAPI backend (see vite.config.ts); in
// Tauri the frontend and the sidecar share an origin too.
import type {
  AcceptRequest,
  AcceptResponse,
  ApiErrorBody,
  ApprovalDecision,
  ApprovalResponse,
  LedgerResponse,
  ModeRequest,
  RefineResponse,
  RefineStatus,
  ReviewQueueResponse,
  ReviewResolveRequest,
  ReviewResolveResponse,
  RevertRequest,
  RevertResponse,
  ShellState,
  StageAction,
  StageActionResponse,
  StructureApplyRequest,
  StructureApplyResponse,
  TranscriptMessageResponse,
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
  const res = await fetch(path, {
    ...init,
    headers: {
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

export function postRefine(): Promise<RefineResponse> {
  return post<RefineResponse>("/api/refine", {});
}

export function getRefineStatus(): Promise<RefineStatus> {
  return get<RefineStatus>("/api/refine/status");
}

export function postTranscriptMessage(text: string): Promise<TranscriptMessageResponse> {
  return post<TranscriptMessageResponse>("/api/transcript/message", { text });
}
