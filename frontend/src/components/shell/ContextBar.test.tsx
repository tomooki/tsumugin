import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ProjectFrameRow, ShellState, ViewModel } from "../../api/types";
import { I18nProvider, type Lang } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { ContextBar } from "./ContextBar";

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: { name: "K2Mn[Fe(CN)6] operando", dataset: "SR-XRD · 63 frames", frame: "fr091", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 3, verified: true },
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36, gsas_available: true },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    ...overrides,
  };
}

function frame(overrides: Partial<ProjectFrameRow> = {}): ProjectFrameRow {
  return { id: "fr0", label: "fr0", axis_value: 0, data_path: "data/fr0.xye", ...overrides };
}

function emptyViewModel(overrides: Partial<ViewModel> = {}): ViewModel {
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

function renderBar(
  initialState: Partial<WorkbenchState> = {},
  { lang = "en" as Lang }: { lang?: Lang } = {},
): ReturnType<typeof render> {
  return render(
    <StoreProvider initialState={{ shell: makeShell(), viewModel: emptyViewModel(), ...initialState }}>
      <I18nProvider lang={lang}>
        <ContextBar />
      </I18nProvider>
    </StoreProvider>,
  );
}

describe("ContextBar — static frame chip (no frame column configured)", () => {
  it("shows shell.project.frame when viewModel.project.frames is absent", () => {
    renderBar();
    expect(screen.getByText("fr091")).toBeInTheDocument();
    expect(screen.queryByLabelText("next frame")).not.toBeInTheDocument();
  });
});

describe("ContextBar — frame k / N nav (V2b B2/B3)", () => {
  function withFrames(n: number, viewModelOverrides: Partial<ViewModel> = {}) {
    const frames = Array.from({ length: n }, (_, i) => frame({ id: `fr${i}`, label: `fr${i}`, axis_value: i }));
    return {
      viewModel: emptyViewModel({ project: { histograms: [], phases: [], settings: { two_theta_limits: null, background_coeffs: null, max_cyc: null }, frames }, ...viewModelOverrides }),
    };
  }

  it("renders fr 1 / N at the initial cursor and disables the prev button", () => {
    renderBar(withFrames(4));
    expect(screen.getByText("fr 1 / 4")).toBeInTheDocument();
    expect(screen.getByLabelText("previous frame")).toBeDisabled();
    expect(screen.getByLabelText("next frame")).not.toBeDisabled();
  });

  it("advances the cursor on next and disables next at the last frame", async () => {
    const user = userEvent.setup();
    renderBar(withFrames(3));

    await user.click(screen.getByLabelText("next frame"));
    expect(screen.getByText("fr 2 / 3")).toBeInTheDocument();

    await user.click(screen.getByLabelText("next frame"));
    expect(screen.getByText("fr 3 / 3")).toBeInTheDocument();
    expect(screen.getByLabelText("next frame")).toBeDisabled();
  });

  it("goes back on prev and disables prev at the first frame", async () => {
    const user = userEvent.setup();
    renderBar({ ...withFrames(3), frameIndex: 2 });

    expect(screen.getByText("fr 3 / 3")).toBeInTheDocument();
    await user.click(screen.getByLabelText("previous frame"));
    expect(screen.getByText("fr 2 / 3")).toBeInTheDocument();
    await user.click(screen.getByLabelText("previous frame"));
    expect(screen.getByText("fr 1 / 3")).toBeInTheDocument();
    expect(screen.getByLabelText("previous frame")).toBeDisabled();
  });

  it("clamps a stale frameIndex beyond the current frame count", () => {
    renderBar({ ...withFrames(2), frameIndex: 99 });
    expect(screen.getByText("fr 2 / 2")).toBeInTheDocument();
  });

  it("translates the prev/next labels to Japanese", () => {
    renderBar(withFrames(2), { lang: "ja" });
    expect(screen.getByLabelText("前のフレーム")).toBeInTheDocument();
    expect(screen.getByLabelText("次のフレーム")).toBeInTheDocument();
  });
});

// api-contract.md §プロジェクトを閉じる導線
describe("ContextBar — CLOSE PROJECT visibility", () => {
  it("is hidden when source is none (Welcome screen)", () => {
    renderBar({ shell: makeShell({ source: "none" }) });
    expect(screen.queryByRole("button", { name: "CLOSE PROJECT" })).not.toBeInTheDocument();
  });

  it("is shown when source is project", () => {
    renderBar({ shell: makeShell({ source: "project" }) });
    expect(screen.getByRole("button", { name: "CLOSE PROJECT" })).toBeInTheDocument();
  });

  // Requirement: "demo セッションでも表示する" — SAMPLE must be exitable
  // back to Welcome too, not just real project sessions.
  it("is shown when source is demo", () => {
    renderBar({ shell: makeShell({ source: "demo" }) });
    expect(screen.getByRole("button", { name: "CLOSE PROJECT" })).toBeInTheDocument();
  });

  // Mutation-proof pair for the visibility condition above: fixtures that
  // predate the `source` field (undefined) must still show the button — see
  // ContextBar.tsx's doc comment mirroring App.tsx's isWelcome precedent. If
  // the condition were flipped to `source === "project"` (excluding
  // undefined/demo) both this test and the "is shown when source is demo"
  // test above would fail.
  it("is shown when source is undefined (pre-source fixture)", () => {
    renderBar({ shell: makeShell() });
    expect(screen.getByRole("button", { name: "CLOSE PROJECT" })).toBeInTheDocument();
  });
});

describe("ContextBar — CLOSE PROJECT click flow", () => {
  function jsonResponse(body: unknown, ok = true, status = 200): Response {
    return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
  }

  it("POSTs /api/project/close then refetches state+viewmodel and dispatches the new (source=none) shell", async () => {
    const user = userEvent.setup();
    const closedShell = makeShell({ source: "none" });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/project/close") && method === "POST") return jsonResponse(closedShell);
      if (url.endsWith("/api/state") && method === "GET") return jsonResponse(closedShell);
      if (url.endsWith("/api/viewmodel") && method === "GET") return jsonResponse(emptyViewModel());
      throw new Error(`unhandled fetch: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderBar({ shell: makeShell({ source: "project" }) });
    await user.click(screen.getByRole("button", { name: "CLOSE PROJECT" }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/project/close"))).toBe(true),
    );
    // The store's shell is now source=none, so ContextBar re-renders without
    // the button (it hides itself — see the visibility describe block).
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "CLOSE PROJECT" })).not.toBeInTheDocument(),
    );
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/state"))).toBe(true);
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/viewmodel"))).toBe(true);

    vi.unstubAllGlobals();
  });

  it("a 409 (job running) shows a non-fatal inline message and keeps the button (project stays open)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/project/close") && method === "POST") {
        return jsonResponse({ error: "refine running", error_type: "conflict" }, false, 409);
      }
      throw new Error(`unhandled fetch: ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderBar({ shell: makeShell({ source: "project" }) });
    await user.click(screen.getByRole("button", { name: "CLOSE PROJECT" }));

    await waitFor(() =>
      expect(screen.getByText("a job is running — cannot close now")).toBeInTheDocument(),
    );
    // The button remains — the project session was NOT torn down.
    expect(screen.getByRole("button", { name: "CLOSE PROJECT" })).toBeInTheDocument();

    vi.unstubAllGlobals();
  });
});
