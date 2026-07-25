import { render, screen, waitFor } from "@testing-library/react";
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
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36, gsas_available: true },
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
    expect((centreBody as HTMLElement).querySelector(".struct-tab")).not.toBeNull();
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

  it("shows the status-bar labels in Japanese after switching language, even with real fetched data", async () => {
    const user = userEvent.setup();
    render(<App />);

    // wait for the real /api/state payload to land (English label first).
    await waitFor(() => expect(screen.getByText(/backend: tsumugin 0\.3\.0/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "日本語" }));

    // Previously the post-fetch status-bar text was built with raw English
    // template literals (`backend: ${...}`, `ledger entries ${...}`, ...)
    // that ignored state.lang entirely — this asserts the fix: switching to
    // JA re-localises the labels even though the values came from the server.
    await waitFor(() => expect(screen.getByText("バックエンド: tsumugin 0.3.0")).toBeInTheDocument());
    expect(screen.getByText("seed = 0 · ビット同一 (NFR-102)")).toBeInTheDocument();
    expect(screen.getByText("ledger 1281 件 · チェーン OK")).toBeInTheDocument();
    expect(screen.getByText("MCP ツール 36 個 · ②到達可能")).toBeInTheDocument();
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

// — V2c レビュー指摘 #4: GSAS-II 不在の可視化 —
// Tier1 desktop sidecar excludes GSAS-II (desktop/README.md "Tier1 の GSAS 前提"), and
// status.gsas_available (api/types.ts BackendStatus) is dynamic per GET /api/state. Previously
// this field was fetched into state but never rendered anywhere — a user on a GSAS-less Tier1
// build had no way to tell why RUN REFINEMENT/RUN SEQUENTIAL/MULTISTART would 422.
describe("StatusBar — GSAS-II availability chip", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function installFetchMockWithGsas(gsasAvailable: boolean) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/state") && method === "GET") {
        return jsonResponse(
          makeShell({
            status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36, gsas_available: gsasAvailable },
          }),
        );
      }
      if (url.endsWith("/api/viewmodel") && method === "GET") {
        return jsonResponse(makeViewModel());
      }
      throw new Error(`unhandled fetch: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("shows the inverted GSAS-II NOT FOUND chip once /api/state reports gsas_available: false", async () => {
    installFetchMockWithGsas(false);
    render(<App />);

    await waitFor(() => expect(screen.getByText("GSAS-II NOT FOUND")).toBeInTheDocument());
    expect(screen.getByText("GSAS-II NOT FOUND").className).toContain("chip--inverted");
  });

  it("does not show the chip when gsas_available is true", async () => {
    installFetchMockWithGsas(true);
    render(<App />);

    await waitFor(() => expect(screen.getByText("OPERATOR CONSOLE")).toBeInTheDocument());
    expect(screen.queryByText("GSAS-II NOT FOUND")).not.toBeInTheDocument();
  });

  it("shows the chip localised to Japanese", async () => {
    const user = userEvent.setup();
    installFetchMockWithGsas(false);
    render(<App />);

    await waitFor(() => expect(screen.getByText("GSAS-II NOT FOUND")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "日本語" }));
    await waitFor(() => expect(screen.getByText("GSAS-II 未検出")).toBeInTheDocument());
  });
});
