import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ShellState, ViewModel } from "../../api/types";
import App from "../../App";

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: {
      name: "K2Mn[Fe(CN)6] operando",
      dataset: "SR-XRD λ 0.79958 · 247 frames",
      frame: "fr091",
      echem: { v: 3.94, q_mah_g: 41.2, x_echem: "0.71(2)" },
    },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 1281, verified: true },
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36 },
    agent: { tokens: 1240000, wall_time_s: 1084, idle: true },
    ...overrides,
  };
}

function makeViewModel(): ViewModel {
  return {
    datasets: [{ id: "sxrd", name: "SR-XRD", meta: "λ 0.79958 · 247 fr", probe: "X", active: true }],
    phases: [],
    channels: [],
    snapshots: [],
    fit: {
      metrics: [],
      histograms: [],
      limits_note: "",
      phase_ticks: [],
      two_theta: { min: 4, max: 38 },
      history: [],
      validity: [],
    },
    parameters: {},
    hypotheses: { rows: [], diff: { vs: "", rows: [] }, evidence: [] },
    phase_id: { candidates: [], unexplained: [], completeness: { is_complete: true, notes: [], flagged_frames: "" } },
    sequence: { charts: [], anchors: [], note: "", segments: [] },
    structure: { sites: [], constraints: [], mem_peaks: [] },
    stages: [],
    review: [],
    transcript: [],
  };
}

function installFetchMock(initialMode: ShellState["mode"] = "manual") {
  let currentMode = initialMode;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/state") && method === "GET") {
      return jsonResponse(makeShell({ mode: currentMode, final_selection_mode: currentMode === "manual" ? "human" : "agent" }));
    }
    if (url.endsWith("/api/viewmodel") && method === "GET") {
      return jsonResponse(makeViewModel());
    }
    if (url.endsWith("/api/mode") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { mode: ShellState["mode"] };
      currentMode = body.mode;
      return jsonResponse(
        makeShell({ mode: currentMode, final_selection_mode: currentMode === "manual" ? "human" : "agent" }),
      );
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
  } as Response;
}

describe("mode toggle — right pane + fsm chip + status sentence swap only", () => {
  beforeEach(() => {
    installFetchMock("manual");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows OPERATOR CONSOLE in MANUAL and switches to AGENT SESSION in AUTO, keeping the centre tab selection", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByText("OPERATOR CONSOLE")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /FIT/ })).toBeInTheDocument();

    // move off the default FIT tab so we can prove it survives the mode switch
    await user.click(screen.getByRole("button", { name: /STRUCTURE/ }));

    await user.click(screen.getByRole("button", { name: /AUTO/ }));

    await waitFor(() => expect(screen.getByText("AGENT SESSION")).toBeInTheDocument());
    expect(screen.queryByText("OPERATOR CONSOLE")).not.toBeInTheDocument();

    // centre pane state (STRUCTURE tab) must still be selected after the swap
    const centreBody = document.querySelector(".centre-canvas__body");
    expect(centreBody).not.toBeNull();
    expect(within(centreBody as HTMLElement).getByText("STRUCTURE")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /STRUCTURE/ }).className,
    ).toContain("tab-strip__btn--active");
  });

  it("flips the final_selection_mode chip HUMAN → AGENT", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByText("HUMAN")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /AUTO/ }));

    await waitFor(() => expect(screen.getByText("AGENT")).toBeInTheDocument());
    expect(screen.queryByText("HUMAN")).not.toBeInTheDocument();
  });

  it("calls POST /api/mode with the new mode", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock("manual");
    render(<App />);

    await waitFor(() => expect(screen.getByText("OPERATOR CONSOLE")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /AUTO/ }));

    await waitFor(() => {
      const modeCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/mode"));
      expect(modeCall).toBeDefined();
    });
    const [, modeInit] = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/mode"))!;
    expect(JSON.parse(String((modeInit as RequestInit).body))).toEqual({ mode: "auto" });
  });
});
