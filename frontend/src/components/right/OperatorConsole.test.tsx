import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReviewItem, StageRow, TranscriptMessage, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { initialWorkbenchState } from "../../state/reducer";
import { StoreProvider, useStore } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { OperatorConsole } from "./OperatorConsole";

// initialWorkbenchState.stageOn defaults stages 1-5 to "on" (matching the
// handoff demo, where the first five stages are already released). The
// gating tests below need stage 01 to start unreleased so the RELEASE
// button (not REVERT) is on screen — override just that key.
const STAGE_01_UNRELEASED = { ...initialWorkbenchState.stageOn, 1: false };

function makeViewModel(overrides: Partial<ViewModel> = {}): ViewModel {
  return {
    datasets: [],
    phases: [],
    channels: [],
    snapshots: [],
    fit: { metrics: [], histograms: [], limits_note: "", phase_ticks: [], two_theta: { min: 4, max: 38 }, history: [], validity: [] },
    parameters: {},
    hypotheses: { rows: [], diff: { vs: "", rows: [] }, evidence: [] },
    phase_id: { candidates: [], unexplained: [], completeness: { is_complete: true, notes: [], flagged_frames: "" } },
    sequence: { charts: [], anchors: [], note: "", segments: [] },
    structure: { sites: [], constraints: [], mem_peaks: [] },
    stages: [],
    review: [],
    transcript: [],
    ...overrides,
  };
}

function stage(overrides: Partial<StageRow> = {}): StageRow {
  return {
    nn: "01",
    name: "background",
    flags: "6→24 terms",
    delta_rwp: "−41.2",
    released: false,
    gate: "bkg",
    ...overrides,
  };
}

function reviewItem(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: "rv1",
    severity: "close",
    title: "ΔlogZ 1.2 below threshold",
    ref: "H-014 / H-011",
    detail: "detail text",
    state: "pending",
    ...overrides,
  };
}

function approvalMessage(overrides: Partial<TranscriptMessage> = {}): TranscriptMessage {
  return {
    id: "t5",
    kind: "approval",
    action_id: "a1",
    title: "identify new phase at frame 91",
    rationale: "Rwp jump + unexplained residual at fr091",
    action_json: '{"frame": 91}',
    state: "pending",
    ...overrides,
  };
}

function renderConsole(initialState: Partial<WorkbenchState>) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider lang="en">
        <StoreProvider initialState={initialState}>{children}</StoreProvider>
      </I18nProvider>
    );
  }
  return render(<OperatorConsole />, { wrapper: Wrapper });
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/stages/")) {
      const nn = url.split("/api/stages/")[1];
      return jsonResponse({ stage: stage({ nn }) });
    }
    if (url.endsWith("/api/refine")) {
      return jsonResponse({ status: "recorded" });
    }
    if (url.includes("/api/review-queue/")) {
      return jsonResponse({ item: reviewItem() });
    }
    if (url.includes("/api/approval/")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { decision: "approve" | "reject" };
      return jsonResponse({
        state: body.decision === "approve" ? "approved" : "rejected",
        snapshot_id: body.decision === "approve" ? "S-9999" : null,
        ledger_index: 42,
      });
    }
    throw new Error(`unhandled fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("OperatorConsole — staged release recipe gating", () => {
  let fetchMock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    fetchMock = installFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the gated sub-line and disables RELEASE when nothing is released in PARAMETERS", async () => {
    renderConsole({
      viewModel: makeViewModel({ stages: [stage({ nn: "01", gate: "bkg" })] }),
      paramRel: {},
      stageOn: STAGE_01_UNRELEASED,
    });

    expect(screen.getByText("gated · nothing released in PARAMETERS")).toBeInTheDocument();
    const releaseBtn = screen.getByRole("button", { name: "RELEASE" });
    expect(releaseBtn).toBeDisabled();
  });

  it("does not call postStage when clicking a disabled/gated RELEASE button", async () => {
    const user = userEvent.setup();
    renderConsole({
      viewModel: makeViewModel({ stages: [stage({ nn: "01", gate: "bkg" })] }),
      paramRel: {},
      stageOn: STAGE_01_UNRELEASED,
    });

    const releaseBtn = screen.getByRole("button", { name: "RELEASE" });
    await user.click(releaseBtn); // disabled — userEvent will not fire onClick
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("opens the gate and enables RELEASE once one PARAMETERS checkbox is on", async () => {
    const user = userEvent.setup();
    renderConsole({
      viewModel: makeViewModel({ stages: [stage({ nn: "01", gate: "bkg" })] }),
      paramRel: { "sxrd.bkg.1": true },
      stageOn: STAGE_01_UNRELEASED,
    });

    expect(screen.queryByText("gated · nothing released in PARAMETERS")).not.toBeInTheDocument();
    expect(screen.getByText("6→24 terms · −41.2")).toBeInTheDocument();

    const releaseBtn = screen.getByRole("button", { name: "RELEASE" });
    expect(releaseBtn).not.toBeDisabled();
    await user.click(releaseBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/stages/01"));
      expect(call).toBeDefined();
    });
    // after the TOGGLE_STAGE dispatch, the row flips to released (REVERT)
    await waitFor(() => expect(screen.getByRole("button", { name: "REVERT" })).toBeInTheDocument());
  });

  it("stage 07 gates on STRUCTURE per-atom occupancy release, not PARAMETERS", async () => {
    renderConsole({
      viewModel: makeViewModel({
        stages: [stage({ nn: "07", name: "occupancies", gate: "occ" })],
        structure: { sites: [], constraints: [], mem_peaks: [] },
      }),
      paramRel: { "sxrd.bkg.1": true }, // irrelevant to occ gating
    });

    expect(screen.getByText("gated · no atom occupancy checked in STRUCTURE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RELEASE" })).toBeDisabled();
  });

  it("stage 07 opens once a site has occ released", async () => {
    renderConsole({
      viewModel: makeViewModel({
        stages: [stage({ nn: "07", name: "occupancies", gate: "occ" })],
        structure: {
          sites: [
            {
              id: "s1",
              label: "K1",
              el: "K",
              x: "0.25",
              y: "0.25",
              z: "0.25",
              occ: "0.71",
              uiso: "0.04",
              note: "",
              lock: {},
              rel: { occ: true },
            },
          ],
          constraints: [],
          mem_peaks: [],
        },
      }),
      paramRel: {},
    });

    expect(screen.queryByText("gated · no atom occupancy checked in STRUCTURE")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RELEASE" })).not.toBeDisabled();
  });
});

describe("OperatorConsole — RUN REFINEMENT stages_on payload (A1)", () => {
  let fetchMock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    fetchMock = installFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends stages_on with a gated stage forced to false and an ungated stage as toggled", async () => {
    const user = userEvent.setup();
    renderConsole({
      viewModel: makeViewModel({
        stages: [
          stage({ nn: "01", gate: "bkg" }), // gated — nothing released in PARAMETERS below
          stage({ nn: "02", gate: null }),
        ],
      }),
      paramRel: {}, // stage 01's gate stays closed
      stageOn: { ...initialWorkbenchState.stageOn, 1: true, 2: true },
    });

    await user.click(screen.getByRole("button", { name: "RUN REFINEMENT" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, init]) => String(u).endsWith("/api/refine") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(call).toBeDefined();
      const [, init] = call!;
      const body = JSON.parse(String((init as RequestInit).body));
      expect(body).toEqual({ stages_on: { "01": false, "02": true } });
    });
  });

  it("sends a gated stage as true once its PARAMETERS gate opens", async () => {
    const user = userEvent.setup();
    renderConsole({
      viewModel: makeViewModel({ stages: [stage({ nn: "01", gate: "bkg" })] }),
      paramRel: { "sxrd.bkg.1": true },
      stageOn: { ...initialWorkbenchState.stageOn, 1: true },
    });

    await user.click(screen.getByRole("button", { name: "RUN REFINEMENT" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, init]) => String(u).endsWith("/api/refine") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(call).toBeDefined();
      const [, init] = call!;
      const body = JSON.parse(String((init as RequestInit).body));
      expect(body).toEqual({ stages_on: { "01": true } });
    });
  });
});

describe("OperatorConsole — PENDING MODEL ACTIONS (V2b B5)", () => {
  let fetchMock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    fetchMock = installFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a pending approval card (kind=approval, state=pending) even in MANUAL mode", () => {
    renderConsole({ viewModel: makeViewModel({ transcript: [approvalMessage()] }) });

    expect(screen.getByText("PENDING MODEL ACTIONS")).toBeInTheDocument();
    expect(screen.getByText("identify new phase at frame 91")).toBeInTheDocument();
    expect(screen.getByText("Rwp jump + unexplained residual at fr091")).toBeInTheDocument();
  });

  it("shows the empty-state note when there are no pending approvals", () => {
    renderConsole({ viewModel: makeViewModel({ transcript: [] }) });
    expect(screen.getByText("no pending model actions")).toBeInTheDocument();
  });

  it("APPROVE calls postApproval(action_id, 'approve') and the card leaves the pending queue", async () => {
    const user = userEvent.setup();
    renderConsole({ viewModel: makeViewModel({ transcript: [approvalMessage()] }) });

    await user.click(screen.getByRole("button", { name: "APPROVE & APPLY" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/approval/a1"));
      expect(call).toBeDefined();
    });
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/approval/a1"))!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ decision: "approve" });

    await waitFor(() => expect(screen.getByText("no pending model actions")).toBeInTheDocument());
  });

  it("REJECT calls postApproval(action_id, 'reject') and the card leaves the pending queue", async () => {
    const user = userEvent.setup();
    renderConsole({ viewModel: makeViewModel({ transcript: [approvalMessage()] }) });

    await user.click(screen.getByRole("button", { name: "REJECT" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/approval/a1"));
      expect(call).toBeDefined();
    });
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/approval/a1"))!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ decision: "reject" });

    await waitFor(() => expect(screen.getByText("no pending model actions")).toBeInTheDocument());
  });

  it("does not show an approval the server already reports as approved", () => {
    renderConsole({ viewModel: makeViewModel({ transcript: [approvalMessage({ state: "approved" })] }) });
    expect(screen.getByText("no pending model actions")).toBeInTheDocument();
    expect(screen.queryByText("identify new phase at frame 91")).not.toBeInTheDocument();
  });

  it("ignores non-approval transcript kinds", () => {
    renderConsole({
      viewModel: makeViewModel({
        transcript: [{ id: "t1", kind: "agent", text: "hello" } as TranscriptMessage],
      }),
    });
    expect(screen.getByText("no pending model actions")).toBeInTheDocument();
  });
});

describe("OperatorConsole — review queue", () => {
  let fetchMock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    fetchMock = installFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ACCEPT calls postReviewResolve and swaps the primary button to ACCEPTED ✓", async () => {
    const user = userEvent.setup();
    renderConsole({ viewModel: makeViewModel({ review: [reviewItem()] }) });

    const acceptBtn = screen.getByRole("button", { name: "ACCEPT …" });
    await user.click(acceptBtn);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/review-queue/rv1/resolve"));
      expect(call).toBeDefined();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "ACCEPTED ✓" })).toBeInTheDocument());
  });

  it("SEND BACK calls postReviewResolve and swaps the primary button to SENT BACK", async () => {
    const user = userEvent.setup();
    renderConsole({ viewModel: makeViewModel({ review: [reviewItem()] }) });

    await user.click(screen.getByRole("button", { name: "SEND BACK" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/review-queue/rv1/resolve"));
      expect(call).toBeDefined();
      const [, init] = call!;
      expect(JSON.parse(String((init as RequestInit).body))).toEqual({ action: "send_back", note: "" });
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "SENT BACK" })).toBeInTheDocument());
  });
});

describe("OperatorConsole — review state from the server survives a reload", () => {
  let fetchMock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    fetchMock = installFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows ACCEPTED ✓ (disabled) for an item the server already reports as accepted, with no local decision", () => {
    renderConsole({ viewModel: makeViewModel({ review: [reviewItem({ state: "accepted" })] }) });

    const acceptedBtn = screen.getByRole("button", { name: "ACCEPTED ✓" });
    expect(acceptedBtn).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows SENT BACK (disabled) for an item the server already reports as sent_back, with no local decision", () => {
    renderConsole({ viewModel: makeViewModel({ review: [reviewItem({ state: "sent_back" })] }) });

    const sentBackBtn = screen.getByRole("button", { name: "SENT BACK" });
    expect(sentBackBtn).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("out-of-vocabulary severity (regression — must not unmount)", () => {
  it("renders an unknown severity as its raw uppercased code on a neutral chip", () => {
    renderConsole({
      viewModel: makeViewModel({
        review: [reviewItem({ severity: "warn" as never, title: "odd item" })],
      }),
    });
    expect(screen.getByText("WARN")).toBeInTheDocument();
    expect(screen.getByText("odd item")).toBeInTheDocument();
  });
});

// — RUN REFINEMENT / GET /api/refine/status polling flow —

/** Exposes state.refine/state.error as text nodes so polling tests can
 * assert on store state that OperatorConsole itself doesn't fully render
 * (e.g. the exact RefineStatus object, or the error message text). */
function DebugState() {
  const { state } = useStore();
  return (
    <div data-testid="debug">
      <span data-testid="refine-status">{state.refine?.status ?? "none"}</span>
      <span data-testid="refine-error">{state.error ?? ""}</span>
    </div>
  );
}

function renderConsoleWithDebug(initialState: Partial<WorkbenchState>) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider lang="en">
        <StoreProvider initialState={initialState}>{children}</StoreProvider>
      </I18nProvider>
    );
  }
  return render(
    <>
      <OperatorConsole />
      <DebugState />
    </>,
    { wrapper: Wrapper },
  );
}

/** Fetch mock for the polling flow: POST /api/refine → refineResponse (once);
 * GET /api/refine/status → the next entry of `statuses` each call (repeats
 * the last entry once exhausted); GET /api/state / /api/viewmodel → minimal
 * valid payloads (for the post-"done" refetch). */
function installRefinePollFetchMock(opts: {
  refineResponse?: unknown;
  refineRejects?: { status: number; body: unknown };
  statuses: unknown[];
}) {
  let statusCallIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/refine") && method === "POST") {
      if (opts.refineRejects) {
        return {
          ok: false,
          status: opts.refineRejects.status,
          statusText: "Conflict",
          json: async () => opts.refineRejects!.body,
        } as Response;
      }
      return jsonResponse(opts.refineResponse ?? { status: "started" });
    }
    if (url.endsWith("/api/refine/status") && method === "GET") {
      const body = opts.statuses[Math.min(statusCallIndex, opts.statuses.length - 1)];
      statusCallIndex += 1;
      return jsonResponse(body);
    }
    if (url.endsWith("/api/state") && method === "GET") {
      return jsonResponse({
        project: { name: "p", dataset: "d", frame: "f", echem: null },
        mode: "manual",
        final_selection_mode: "human",
        ledger: { count: 1, verified: true },
        status: { backend_build: "b", seed: 0, mcp_tools: 36, gsas_available: true },
        agent: { tokens: 0, wall_time_s: 0, idle: true },
      });
    }
    if (url.endsWith("/api/viewmodel") && method === "GET") {
      return jsonResponse(makeViewModel());
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Flushes pending microtasks (promise .then chains) without advancing fake
 * timers — needed because the initial `postRefine().then(...)` chain isn't
 * scheduled via any timer, so `vi.advanceTimersByTimeAsync(0)` has nothing
 * to wait on. Wrapped in `act` so the resulting dispatch is batched like a
 * real event. */
async function flushMicrotasks(times = 6) {
  await act(async () => {
    for (let i = 0; i < times; i++) {
      await Promise.resolve();
    }
  });
}

/** Advances fake timers (running the setInterval poll tick + its promise
 * chain) inside `act` so the resulting store dispatch is flushed before the
 * next assertion. */
async function advanceTimers(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("OperatorConsole — RUN REFINEMENT polling flow", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("posts /api/refine, then polls /api/refine/status every 2s while running, disabling the button", async () => {
    vi.useFakeTimers();
    const fetchMock = installRefinePollFetchMock({
      refineResponse: { status: "started" },
      statuses: [{ status: "running", elapsed_s: 2, last_event: "stage 04", error: null }],
    });
    renderConsoleWithDebug({ viewModel: makeViewModel() });

    fireEvent.click(screen.getByRole("button", { name: "RUN REFINEMENT" }));
    await flushMicrotasks(); // flush the postRefine() promise chain

    expect(screen.getByTestId("refine-status").textContent).toBe("running");
    expect(screen.getByRole("button", { name: "RUNNING …" })).toBeDisabled();

    await advanceTimers(2000); // tick 1
    await advanceTimers(2000); // tick 2

    const statusCalls = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/refine/status"));
    expect(statusCalls.length).toBe(2);
  });

  it("on done, stops polling and refetches state + viewmodel", async () => {
    vi.useFakeTimers();
    const fetchMock = installRefinePollFetchMock({
      refineResponse: { status: "started" },
      statuses: [
        { status: "running", elapsed_s: 2, last_event: "stage 04", error: null },
        { status: "done", elapsed_s: 4, last_event: "complete", error: null },
      ],
    });
    renderConsoleWithDebug({ viewModel: makeViewModel() });

    fireEvent.click(screen.getByRole("button", { name: "RUN REFINEMENT" }));
    await flushMicrotasks();
    await advanceTimers(2000); // tick 1 → still running
    expect(screen.getByTestId("refine-status").textContent).toBe("running");

    await advanceTimers(2000); // tick 2 → done
    expect(screen.getByTestId("refine-status").textContent).toBe("done");

    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/state"))).toBe(true);
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/viewmodel"))).toBe(true);

    // polling must have stopped — no further /api/refine/status calls after "done"
    const statusCallsAtDone = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/refine/status")).length;
    await advanceTimers(4000);
    const statusCallsAfter = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/refine/status")).length;
    expect(statusCallsAfter).toBe(statusCallsAtDone);

    // the RUN REFINEMENT button is enabled again once the job is no longer running
    expect(screen.getByRole("button", { name: "RUN REFINEMENT" })).not.toBeDisabled();
  });

  it("on failed, surfaces the error and stops polling", async () => {
    vi.useFakeTimers();
    installRefinePollFetchMock({
      refineResponse: { status: "started" },
      statuses: [{ status: "failed", elapsed_s: 3, last_event: "stage 08", error: "cell collapsed" }],
    });
    renderConsoleWithDebug({ viewModel: makeViewModel() });

    fireEvent.click(screen.getByRole("button", { name: "RUN REFINEMENT" }));
    await flushMicrotasks();
    await advanceTimers(2000);

    expect(screen.getByTestId("refine-status").textContent).toBe("failed");
    expect(screen.getByTestId("refine-error").textContent).toBe("cell collapsed");
    expect(screen.getByRole("button", { name: "RUN REFINEMENT" })).not.toBeDisabled();
  });

  it("treats a 409 (already running) as non-fatal and reflects running state", async () => {
    vi.useFakeTimers();
    installRefinePollFetchMock({
      refineRejects: { status: 409, body: { error: "already running", error_type: "conflict" } },
      statuses: [{ status: "running", elapsed_s: 10, last_event: "stage 06", error: null }],
    });
    renderConsoleWithDebug({ viewModel: makeViewModel() });

    fireEvent.click(screen.getByRole("button", { name: "RUN REFINEMENT" }));
    await flushMicrotasks();

    expect(screen.getByTestId("refine-status").textContent).toBe("running");
    expect(screen.getByTestId("refine-error").textContent).toBe("");
  });

  it("does not double-post /api/refine when RUN REFINEMENT is clicked again while running (button is disabled)", async () => {
    vi.useFakeTimers();
    const fetchMock = installRefinePollFetchMock({
      refineResponse: { status: "started" },
      statuses: [{ status: "running", elapsed_s: 2, last_event: "stage 04", error: null }],
    });
    renderConsoleWithDebug({ viewModel: makeViewModel() });

    const btn = screen.getByRole("button", { name: "RUN REFINEMENT" });
    fireEvent.click(btn);
    await flushMicrotasks();
    expect(screen.getByRole("button", { name: "RUNNING …" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "RUNNING …" }));
    await flushMicrotasks();

    const refineCalls = fetchMock.mock.calls.filter(
      ([u, init]) => String(u).endsWith("/api/refine") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(refineCalls.length).toBe(1);
  });

  it("demo mode ('recorded') stays single-shot — no polling starts", async () => {
    vi.useFakeTimers();
    const fetchMock = installRefinePollFetchMock({
      refineResponse: { status: "recorded" },
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    renderConsoleWithDebug({ viewModel: makeViewModel() });

    fireEvent.click(screen.getByRole("button", { name: "RUN REFINEMENT" }));
    await flushMicrotasks();

    expect(screen.getByTestId("refine-status").textContent).toBe("none");
    expect(screen.getByRole("button", { name: "RUN REFINEMENT" })).not.toBeDisabled();

    await advanceTimers(4000);
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/refine/status"))).toBe(false);
  });
});
