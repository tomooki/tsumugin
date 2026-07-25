import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ShellState, ViewModel } from "./api/types";
import App from "./App";

// REQ-GUI-017 integration: source="none" swaps the 3-pane workbench body for
// the Welcome screen (App.tsx's `isWelcome` branch), and a successful
// create/open/demo call flips source and brings the workbench back.

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: { name: "", dataset: "", frame: "", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 0, verified: true },
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36, gsas_available: true },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    source: "none",
    ...overrides,
  };
}

function makeViewModel(): ViewModel {
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
  };
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function installFetchMock() {
  let source: ShellState["source"] = "none";
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/state") && method === "GET") return jsonResponse(makeShell({ source }));
    if (url.endsWith("/api/viewmodel") && method === "GET") return jsonResponse(makeViewModel());
    if (url.endsWith("/api/project/recent") && method === "GET") return jsonResponse({ projects: [] });
    if (url.endsWith("/api/project") && method === "POST") {
      source = "project";
      return jsonResponse({ ok: true });
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App — source=none shows the Welcome screen, not the 3-pane workbench", () => {
  it("renders WelcomeScreen and none of the workbench body (LeftRail/tab strip/OperatorConsole)", async () => {
    installFetchMock();
    render(<App />);

    await waitFor(() => expect(screen.getByText("NEW PROJECT")).toBeInTheDocument());

    expect(screen.queryByText("DATASETS")).not.toBeInTheDocument();
    expect(screen.queryByText("OPERATOR CONSOLE")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /FIT/ })).not.toBeInTheDocument();
  });

  it("keeps the title bar and status bar visible, and disables the mode toggle", async () => {
    installFetchMock();
    render(<App />);

    await waitFor(() => expect(screen.getByText("NEW PROJECT")).toBeInTheDocument());

    expect(screen.getByText("TSUMUGIN")).toBeInTheDocument(); // title bar
    expect(screen.getByText(/backend: tsumugin 0\.3\.0/)).toBeInTheDocument(); // status bar

    expect(screen.getByRole("button", { name: /MANUAL/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /AUTO/ })).toBeDisabled();
  });

  it("creating a project swaps the Welcome screen out for the 3-pane workbench (PROJECT tab first)", async () => {
    const user = userEvent.setup();
    installFetchMock();
    render(<App />);

    await waitFor(() => expect(screen.getByText("NEW PROJECT")).toBeInTheDocument());

    await user.type(screen.getByLabelText("name"), "CaTeO3 cyclic");
    await user.type(screen.getByLabelText("directory"), "C:\\projects");
    await user.click(screen.getByRole("button", { name: "CREATE" }));

    await waitFor(() => expect(screen.getByText("DATASETS")).toBeInTheDocument());
    expect(screen.queryByText("NEW PROJECT")).not.toBeInTheDocument();
    // PROJECT is the first tab (V2a P4).
    const tabButtons = screen.getAllByRole("button", { name: /PROJECT|FIT|LEDGER/ });
    expect(tabButtons[0].textContent).toBe("PROJECT");
  });
});
