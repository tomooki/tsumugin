import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentJobStatus, ShellState, TranscriptMessage, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider, useStore } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { AgentSession } from "./AgentSession";

function makeViewModel(transcript: TranscriptMessage[] = []): ViewModel {
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
    transcript,
  };
}

function makeShell(): ShellState {
  return {
    project: { name: "p", dataset: "d", frame: "fr001", echem: null },
    mode: "auto",
    final_selection_mode: "agent",
    ledger: { count: 1, verified: true },
    status: { backend_build: "x", seed: 0, mcp_tools: 36, gsas_available: true },
    agent: { tokens: 1_240_000, wall_time_s: 1084, idle: false },
  };
}

function renderSession(initialState: Partial<WorkbenchState>) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider lang="en">
        <StoreProvider initialState={{ shell: makeShell(), ...initialState }}>{children}</StoreProvider>
      </I18nProvider>
    );
  }
  return render(<AgentSession />, { wrapper: Wrapper });
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

describe("AgentSession — budget strip", () => {
  it("formats tokens and wall time from state.shell.agent", () => {
    renderSession({ viewModel: makeViewModel([]) });
    expect(screen.getByText("1.24 M")).toBeInTheDocument();
    expect(screen.getByText("18 m 04 s")).toBeInTheDocument();
  });
});

describe("AgentSession — tool call transcript item", () => {
  it("expands and collapses ARGUMENTS/RETURN on header click", async () => {
    const user = userEvent.setup();
    const msg: TranscriptMessage = {
      id: "t1",
      kind: "tool",
      tool: "check_phase_set",
      layer: "MCP ②",
      secs: 1.8,
      args: '{"frames":[84,96]}',
      ret: '{"is_complete":false}',
    };
    renderSession({ viewModel: makeViewModel([msg]) });

    expect(screen.queryByText('{"frames":[84,96]}')).not.toBeInTheDocument();

    await user.click(screen.getByText("check_phase_set"));
    expect(screen.getByText('{"frames":[84,96]}')).toBeInTheDocument();
    expect(screen.getByText('{"is_complete":false}')).toBeInTheDocument();

    await user.click(screen.getByText("check_phase_set"));
    expect(screen.queryByText('{"frames":[84,96]}')).not.toBeInTheDocument();
  });
});

describe("AgentSession — approval (ModelAction) transcript item", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/approval/")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as { decision: "approve" | "reject" };
        return jsonResponse({
          state: body.decision === "approve" ? "approved" : "rejected",
          snapshot_id: body.decision === "approve" ? "S-0311" : null,
          ledger_index: 1284,
        });
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const approvalMsg: TranscriptMessage = {
    id: "t5",
    kind: "approval",
    action_id: "a1",
    title: "AddPhase · monoclinic",
    rationale: "why",
    action_json: '{"action":"AddPhase"}',
    state: "pending",
  };

  it("APPROVE & APPLY calls postApproval and updates the state line", async () => {
    const user = userEvent.setup();
    renderSession({ viewModel: makeViewModel([approvalMsg]) });

    expect(screen.getByText("held · no state has changed yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "APPROVE & APPLY" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/approval/a1"));
      expect(call).toBeDefined();
    });
    await waitFor(() =>
      expect(
        screen.getByText("applied in snapshot S-0311 · ledger #1284 · revert available"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "APPLIED ✓" })).toBeDisabled();
  });

  it("REJECT calls postApproval with decision=reject and updates the state line", async () => {
    const user = userEvent.setup();
    renderSession({ viewModel: makeViewModel([approvalMsg]) });

    await user.click(screen.getByRole("button", { name: "REJECT" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/approval/a1"));
      expect(call).toBeDefined();
      const [, init] = call!;
      expect(JSON.parse(String((init as RequestInit).body))).toEqual({ decision: "reject" });
    });
    await waitFor(() =>
      expect(
        screen.getByText("rejected · proposal kept in ledger, nothing changed"),
      ).toBeInTheDocument(),
    );
  });

  it("deciding one approval card does not leak state into another pending card (per-action_id)", async () => {
    const user = userEvent.setup();
    const approvalMsgA: TranscriptMessage = { ...approvalMsg, id: "t5", action_id: "a1", title: "card A" };
    const approvalMsgB: TranscriptMessage = { ...approvalMsg, id: "t6", action_id: "a2", title: "card B" };
    renderSession({ viewModel: makeViewModel([approvalMsgA, approvalMsgB]) });

    const approveButtons = screen.getAllByRole("button", { name: "APPROVE & APPLY" });
    expect(approveButtons).toHaveLength(2);

    await user.click(approveButtons[0]);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/approval/a1"));
      expect(call).toBeDefined();
    });
    // card A resolved: its own APPROVE & APPLY button becomes APPLIED ✓ and disabled.
    await waitFor(() => expect(screen.getByRole("button", { name: "APPLIED ✓" })).toBeDisabled());
    // card B is untouched: still exactly one pending APPROVE & APPLY button, enabled.
    const remainingApprove = screen.getByRole("button", { name: "APPROVE & APPLY" });
    expect(remainingApprove).not.toBeDisabled();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/approval/a2"))).toBe(false);
  });

  it("rapid double-click on APPROVE & APPLY calls postApproval only once", async () => {
    // fireEvent (not userEvent) so both clicks land synchronously in the same
    // tick, before React has a chance to re-render the button as disabled —
    // this is what actually exercises the `inFlightRef` synchronous guard
    // rather than the (also-present, but slower) `busy` state disabling it.
    const approvalMsgC: TranscriptMessage = { ...approvalMsg, id: "t7", action_id: "a3" };
    renderSession({ viewModel: makeViewModel([approvalMsgC]) });

    const btn = screen.getByRole("button", { name: "APPROVE & APPLY" });
    fireEvent.click(btn);
    fireEvent.click(btn);

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/approval/a3"));
      expect(calls).toHaveLength(1);
    });
    // still exactly one after settling — the second click never reached fetch.
    const calls = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/approval/a3"));
    expect(calls).toHaveLength(1);
  });

  it("shows a mono 'resolving' state and disables both buttons while the request is in flight", async () => {
    let resolveFetch: (() => void) | null = null;
    const slowFetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/approval/a5")) {
        await new Promise<void>((resolve) => {
          resolveFetch = resolve;
        });
        return jsonResponse({ state: "approved", snapshot_id: "S-1", ledger_index: 1 });
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", slowFetchMock);

    const user = userEvent.setup();
    const approvalMsgE: TranscriptMessage = { ...approvalMsg, id: "t9", action_id: "a5" };
    renderSession({ viewModel: makeViewModel([approvalMsgE]) });

    await user.click(screen.getByRole("button", { name: "APPROVE & APPLY" }));

    await waitFor(() => expect(screen.getByText("resolving …")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "APPROVE & APPLY" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "REJECT" })).toBeDisabled();

    resolveFetch!();
    await waitFor(() => expect(screen.getByRole("button", { name: "APPLIED ✓" })).toBeDisabled());
  });

  it("409 on approve shows a non-fatal inline note instead of the fatal error path, and allows retry", async () => {
    const conflictFetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/approval/a4")) {
        return {
          ok: false,
          status: 409,
          statusText: "Conflict",
          json: async () => ({ error: "approval already resolved: a4", error_type: "ConflictError" }),
        } as Response;
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", conflictFetchMock);

    const user = userEvent.setup();
    const approvalMsgD: TranscriptMessage = { ...approvalMsg, id: "t8", action_id: "a4" };
    renderSession({ viewModel: makeViewModel([approvalMsgD]) });

    await user.click(screen.getByRole("button", { name: "APPROVE & APPLY" }));

    await waitFor(() =>
      expect(
        screen.getByText("already resolved elsewhere · refresh to see the result"),
      ).toBeInTheDocument(),
    );
    // non-fatal: the card returns to pending and lets the operator retry
    // (contrast with a hard failure, which the demo/mode-switch paths still
    // route through SET_ERROR).
    expect(screen.getByRole("button", { name: "APPROVE & APPLY" })).not.toBeDisabled();
  });
});

// — V3a agent bridge: propose_* ModelAction kinds (api-contract.md
// §`propose_*` ツールと承認カード) — action_id prefix → kind badge on the
// approval card. gates.test.ts covers the pure approvalKind/
// structureRevisionSiteCount mapping; these tests cover the rendering.
describe("AgentSession — approval card kind badges (propose_* V3a)", () => {
  function approvalOf(overrides: Partial<TranscriptMessage>): TranscriptMessage {
    return {
      id: "t10",
      kind: "approval",
      action_id: "np-91",
      title: "identify new phase at frame 91",
      rationale: "Rwp jump + unexplained residual at fr091",
      action_json: '{"frame": 91}',
      state: "pending",
      ...overrides,
    };
  }

  it.each([
    ["np-91", "NEW PHASE"],
    ["sr-4", "REVISE STRUCTURE"],
    ["rv-2", "REVIEW"],
    ["pc-1", "PHASE"],
    ["st-3", "SETTINGS"],
  ] as const)("shows the %s badge as %s", (actionId, label) => {
    renderSession({ viewModel: makeViewModel([approvalOf({ action_id: actionId })]) });
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("shows no kind badge for an unprefixed action_id (pre-V3a 'a1' fixture) and does not crash", () => {
    renderSession({ viewModel: makeViewModel([approvalOf({ action_id: "a1" })]) });
    for (const label of ["NEW PHASE", "REVISE STRUCTURE", "REVIEW", "PHASE", "SETTINGS"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    // the rest of the card still renders normally
    expect(screen.getByRole("button", { name: "APPROVE & APPLY" })).toBeInTheDocument();
  });

  it("shows no kind badge for an unrecognised prefix and does not crash (§語彙 総関数フォールバック)", () => {
    renderSession({ viewModel: makeViewModel([approvalOf({ action_id: "xx-1" })]) });
    for (const label of ["NEW PHASE", "REVISE STRUCTURE", "REVIEW", "PHASE", "SETTINGS"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "APPROVE & APPLY" })).toBeInTheDocument();
  });

  it("sr- card shows a 'N site(s) changed' summary line above the raw JSON, without hiding the JSON", () => {
    renderSession({
      viewModel: makeViewModel([
        approvalOf({
          action_id: "sr-4",
          action_json: '{"sites":[{"id":"s1"},{"id":"s2"},{"id":"s3"}]}',
        }),
      ]),
    });
    expect(screen.getByText("3 site(s) changed")).toBeInTheDocument();
    expect(screen.getByText('{"sites":[{"id":"s1"},{"id":"s2"},{"id":"s3"}]}')).toBeInTheDocument();
  });

  it("a non-sr- card shows no summary line even with a 'sites'-shaped payload", () => {
    renderSession({
      viewModel: makeViewModel([approvalOf({ action_id: "pc-1", action_json: '{"sites":[{"id":"s1"}]}' })]),
    });
    expect(screen.queryByText(/site\(s\) changed/)).not.toBeInTheDocument();
  });

  it("kind-specific state line after APPROVE (np-)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/approval/np-91")) {
        return jsonResponse({ state: "approved", snapshot_id: "S-1", ledger_index: 1 });
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSession({ viewModel: makeViewModel([approvalOf({ action_id: "np-91" })]) });
    await user.click(screen.getByRole("button", { name: "APPROVE & APPLY" }));

    await waitFor(() =>
      expect(screen.getByText("applied · new phase added to the phase set")).toBeInTheDocument(),
    );
    vi.unstubAllGlobals();
  });

  it("kind-specific state line after REJECT (rv-)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/approval/rv-2")) {
        return jsonResponse({ state: "rejected", snapshot_id: null, ledger_index: 2 });
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSession({ viewModel: makeViewModel([approvalOf({ action_id: "rv-2" })]) });
    await user.click(screen.getByRole("button", { name: "REJECT" }));

    await waitFor(() =>
      expect(screen.getByText("rejected · review item left pending")).toBeInTheDocument(),
    );
    vi.unstubAllGlobals();
  });

  it("unprefixed action_id keeps the pre-existing generic state line verbatim (backward compatibility)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/approval/a1")) {
        return jsonResponse({ state: "approved", snapshot_id: "S-0311", ledger_index: 1284 });
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSession({ viewModel: makeViewModel([approvalOf({ action_id: "a1" })]) });
    await user.click(screen.getByRole("button", { name: "APPROVE & APPLY" }));

    await waitFor(() =>
      expect(
        screen.getByText("applied in snapshot S-0311 · ledger #1284 · revert available"),
      ).toBeInTheDocument(),
    );
    vi.unstubAllGlobals();
  });
});

describe("AgentSession — composer", () => {
  it("SEND calls postTranscriptMessage and clears the draft", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/transcript/message")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as { text: string };
        return jsonResponse({ message: { id: "t99", kind: "user", text: body.text } });
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSession({ viewModel: makeViewModel([]), draft: "why was stage 08 reverted?" });

    const textarea = screen.getByPlaceholderText("Ask about this frame, or send an instruction…");
    expect(textarea).toHaveValue("why was stage 08 reverted?");

    await user.click(screen.getByRole("button", { name: "SEND" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/transcript/message"));
      expect(call).toBeDefined();
      const [, init] = call!;
      expect(JSON.parse(String((init as RequestInit).body))).toEqual({
        text: "why was stage 08 reverted?",
      });
    });
    await waitFor(() => expect(textarea).toHaveValue(""));

    vi.unstubAllGlobals();
  });

  it("a quick-prompt chip fills the draft without calling the API", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderSession({ viewModel: makeViewModel([]) });
    await user.click(screen.getByRole("button", { name: "Compare H-014 against H-011" }));

    const textarea = screen.getByPlaceholderText("Ask about this frame, or send an instruction…");
    expect(textarea).toHaveValue("Compare H-014 against H-011");
    expect(fetchMock).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});

// — V3a: AUTO 実 LLM ブリッジ (api-contract.md §AUTO 実 LLM ブリッジ) —

/** Exposes state.error as a text node so the polling tests below can assert
 * on the non-fatal-vs-fatal distinction (409 / failed) that AgentSession
 * itself doesn't fully render — mirrors OperatorConsole.test.tsx's
 * DebugState precedent. */
function DebugState() {
  const { state } = useStore();
  return <span data-testid="debug-error">{state.error ?? ""}</span>;
}

function renderSessionWithDebug(initialState: Partial<WorkbenchState>) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider lang="en">
        <StoreProvider initialState={{ shell: makeShell(), ...initialState }}>{children}</StoreProvider>
      </I18nProvider>
    );
  }
  return render(
    <>
      <AgentSession />
      <DebugState />
    </>,
    { wrapper: Wrapper },
  );
}

/** Fetch mock for the V3a bridge flow: POST /api/transcript/message →
 * `transcriptResponse` (or rejects with `transcriptRejects`, once); GET
 * /api/agent/status → the next entry of `statuses` each call (repeats the
 * last entry once exhausted); GET /api/viewmodel → the next entry of
 * `viewModels` each call (repeats the last entry once exhausted, defaults to
 * an empty-transcript viewmodel so tests that don't care can omit it). */
function installAgentBridgeFetchMock(opts: {
  transcriptResponse?: unknown;
  transcriptRejects?: { status: number; body: unknown };
  statuses?: AgentJobStatus[];
  viewModels?: ViewModel[];
}) {
  let statusCallIndex = 0;
  let vmCallIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/transcript/message") && method === "POST") {
      if (opts.transcriptRejects) {
        return {
          ok: false,
          status: opts.transcriptRejects.status,
          statusText: "Conflict",
          json: async () => opts.transcriptRejects!.body,
        } as Response;
      }
      return jsonResponse(opts.transcriptResponse ?? { status: "agent_started" });
    }
    if (url.endsWith("/api/agent/status") && method === "GET") {
      const statuses = opts.statuses ?? [];
      const body = statuses[Math.min(statusCallIndex, statuses.length - 1)];
      statusCallIndex += 1;
      return jsonResponse(body);
    }
    if (url.endsWith("/api/viewmodel") && method === "GET") {
      const viewModels = opts.viewModels ?? [makeViewModel([])];
      const body = viewModels[Math.min(vmCallIndex, viewModels.length - 1)];
      vmCallIndex += 1;
      return jsonResponse(body);
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Flushes pending microtasks (the postTranscriptMessage().then(...) chain)
 * without advancing fake timers, wrapped in `act` so the resulting dispatch
 * is batched like a real event (mirrors OperatorConsole.test.tsx's
 * precedent). */
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

describe("AgentSession — V3a agent bridge: SEND starts an agent turn (202)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("202 agent_started polls /api/agent/status every 2s, refetches the viewmodel while running (transcript grows), and stops polling at idle", async () => {
    vi.useFakeTimers();
    const runningStatus: AgentJobStatus = {
      status: "running",
      available: true,
      tokens: 500,
      wall_time_s: 4,
      error: null,
    };
    const idleStatus: AgentJobStatus = {
      status: "idle",
      available: true,
      tokens: 12_400,
      wall_time_s: 96,
      error: null,
    };
    const grownViewModel = makeViewModel([
      { id: "a1", kind: "agent", text: "checking phase set completeness first" },
    ]);
    const fetchMock = installAgentBridgeFetchMock({
      statuses: [runningStatus, idleStatus],
      viewModels: [grownViewModel],
    });

    renderSessionWithDebug({ viewModel: makeViewModel([]), draft: "check the phase set" });

    fireEvent.click(screen.getByRole("button", { name: "SEND" }));
    await flushMicrotasks();

    // draft cleared and SEND disabled immediately (optimistic — before the
    // first poll tick), same as the fallback path's draft-clear behaviour.
    expect(screen.getByPlaceholderText("Ask about this frame, or send an instruction…")).toHaveValue("");
    expect(screen.getByRole("button", { name: "SEND" })).toBeDisabled();

    await advanceTimers(2000); // tick 1 → running: status polled + viewmodel refetched
    expect(screen.getByText("checking phase set completeness first")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SEND" })).toBeDisabled();
    // budget strip reflects the LIVE polled values, not the shell-seeded ones
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("0 m 04 s")).toBeInTheDocument();

    await advanceTimers(2000); // tick 2 → idle: polling stops, SEND re-enabled
    expect(screen.getByRole("button", { name: "SEND" })).not.toBeDisabled();
    expect(screen.getByText("12.4 k")).toBeInTheDocument();

    const statusCallsAtIdle = fetchMock.mock.calls.filter((c) =>
      String(c[0]).endsWith("/api/agent/status"),
    ).length;
    await advanceTimers(4000);
    const statusCallsAfter = fetchMock.mock.calls.filter((c) =>
      String(c[0]).endsWith("/api/agent/status"),
    ).length;
    expect(statusCallsAfter).toBe(statusCallsAtIdle); // no further ticks once idle

    expect(screen.getByTestId("debug-error").textContent).toBe("");
  });

  it("a 409 (a turn is already running) is treated as non-fatal and starts polling instead of a fatal error", async () => {
    vi.useFakeTimers();
    installAgentBridgeFetchMock({
      transcriptRejects: { status: 409, body: { error: "agent turn already running", error_type: "ConflictError" } },
      statuses: [{ status: "running", available: true, tokens: 10, wall_time_s: 1, error: null }],
    });

    renderSessionWithDebug({ viewModel: makeViewModel([]), draft: "hello" });

    fireEvent.click(screen.getByRole("button", { name: "SEND" }));
    await flushMicrotasks();

    expect(screen.getByRole("button", { name: "SEND" })).toBeDisabled();
    expect(screen.getByTestId("debug-error").textContent).toBe("");
  });

  it("a failed agent turn shows the error inline (non-fatal path) and re-enables SEND", async () => {
    vi.useFakeTimers();
    installAgentBridgeFetchMock({
      statuses: [{ status: "failed", available: true, tokens: 20, wall_time_s: 3, error: "max_turns exceeded" }],
    });

    renderSessionWithDebug({ viewModel: makeViewModel([]), draft: "do something long-running" });

    fireEvent.click(screen.getByRole("button", { name: "SEND" }));
    await flushMicrotasks();
    await advanceTimers(2000);

    expect(screen.getByText("agent failed: max_turns exceeded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SEND" })).not.toBeDisabled();
    // a job failure is not routed through the global/fatal error path (mirrors
    // TranscriptItem's approval-409 precedent: inline text, not state.error).
    expect(screen.getByTestId("debug-error").textContent).toBe("");
  });
});

describe("AgentSession — V3a agent bridge: agent unavailable", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function unavailableShell(): ShellState {
    return {
      ...makeShell(),
      agent: { tokens: 0, wall_time_s: 0, idle: true, available: false },
    };
  }

  it("state.shell.agent.available === false disables SEND and shows the AGENT UNAVAILABLE chip", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderSession({ shell: unavailableShell(), viewModel: makeViewModel([]), draft: "anything" });

    expect(screen.getByText("AGENT UNAVAILABLE — claude CLI / agent extra required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SEND" })).toBeDisabled();

    // A disabled button never dispatches a click — this is the DOM-level
    // guard a mutation of the `disabled={... || !available}` wiring would
    // break (verified by hand: removing `!available` from that expression
    // makes this assertion fail — the button is enabled and the click below
    // reaches fetch).
    fireEvent.click(screen.getByRole("button", { name: "SEND" }));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("available === true (or omitted) leaves SEND enabled and shows no chip", () => {
    renderSession({ viewModel: makeViewModel([]) });
    expect(
      screen.queryByText("AGENT UNAVAILABLE — claude CLI / agent extra required"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SEND" })).not.toBeDisabled();
  });
});

describe("AgentSession — V3a composer footer", () => {
  it("shows the real-bridge footer note (not the demo skill/tool-count text) when idle", () => {
    renderSession({ viewModel: makeViewModel([]) });
    expect(screen.getByText("local Claude Code · custody: approvals stay human")).toBeInTheDocument();
  });
});
