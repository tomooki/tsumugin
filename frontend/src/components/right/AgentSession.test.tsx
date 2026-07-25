import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ShellState, TranscriptMessage, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
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
    status: { backend_build: "x", seed: 0, mcp_tools: 36 },
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
