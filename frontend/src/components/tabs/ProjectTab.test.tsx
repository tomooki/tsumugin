import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProjectFrameRow, ProjectHistogramRow, ProjectPhaseRow, ShellState, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { ProjectTab } from "./ProjectTab";

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: { name: "CaTeO3 cyclic", dataset: "", frame: "", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 3, verified: true },
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36 },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    source: "project",
    ...overrides,
  };
}

function histogram(overrides: Partial<ProjectHistogramRow> = {}): ProjectHistogramRow {
  return {
    id: "h0",
    data_path: "data/frame0.xye",
    instrument_path: "data/frame0.instprm",
    radiation: "xray_lab",
    geometry: "bragg_brentano",
    data_format: "XYE",
    two_theta_limits: [10, 90],
    bank: null,
    ...overrides,
  };
}

function phase(overrides: Partial<ProjectPhaseRow> = {}): ProjectPhaseRow {
  return { name: "alpha CaTeO3", structure_path: "data/alpha.cif", ...overrides };
}

function frame(overrides: Partial<ProjectFrameRow> = {}): ProjectFrameRow {
  return { id: "fr0", label: "fr0", axis_value: 0, data_path: "data/fr0.xye", ...overrides };
}

function makeViewModel(overrides: Partial<ViewModel> = {}): ViewModel {
  return {
    datasets: [],
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
    project: {
      histograms: [histogram()],
      phases: [phase()],
      settings: { two_theta_limits: [10, 90], background_coeffs: 12, max_cyc: 15 },
    },
    ...overrides,
  };
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function errorResponse(status: number, body: unknown): Response {
  return { ok: false, status, statusText: "error", json: async () => body } as Response;
}

interface MockOptions {
  shell?: ShellState;
  viewModel?: ViewModel;
  removeHistogramStatus?: number;
  echemStatus?: number;
}

function installFetchMock(opts: MockOptions = {}) {
  const shell = opts.shell ?? makeShell();
  const viewModel = opts.viewModel ?? makeViewModel();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/state") && method === "GET") return jsonResponse(shell);
    if (url.endsWith("/api/viewmodel") && method === "GET") return jsonResponse(viewModel);
    if (url.endsWith("/api/project/upload") && method === "POST") {
      const form = init?.body as FormData;
      const kind = form.get("kind");
      const file = form.get("file") as File;
      return jsonResponse({ stored_path: `data/${kind}-${file.name}` });
    }
    if (url.endsWith("/api/project/histograms") && method === "POST") return jsonResponse(shell);
    if (url.includes("/api/project/histograms/") && url.endsWith("/remove") && method === "POST") {
      if (opts.removeHistogramStatus && opts.removeHistogramStatus >= 400) {
        return errorResponse(opts.removeHistogramStatus, { error: "job running", error_type: "conflict" });
      }
      return jsonResponse(shell);
    }
    if (url.endsWith("/api/project/phases") && method === "POST") return jsonResponse(shell);
    if (url.includes("/api/project/phases/") && url.endsWith("/remove") && method === "POST") {
      return jsonResponse(shell);
    }
    if (url.endsWith("/api/project/settings") && method === "POST") return jsonResponse(shell);
    if (url.endsWith("/api/project/frames") && method === "POST") return jsonResponse(shell);
    if (url.endsWith("/api/echem") && method === "POST") {
      if (opts.echemStatus && opts.echemStatus >= 400) {
        return errorResponse(opts.echemStatus, { error: "invalid mpr file", error_type: "validation" });
      }
      return jsonResponse({ curve: [{ t: 0, v: 3.9 }], targets: [{ frame: 0, x_total: 0.5 }] });
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderProjectTab(initialState: Partial<WorkbenchState> = {}, mockOpts: MockOptions = {}) {
  const fetchMock = installFetchMock(mockOpts);
  const merged: Partial<WorkbenchState> = {
    shell: mockOpts.shell ?? makeShell(),
    viewModel: mockOpts.viewModel ?? makeViewModel(),
    ...initialState,
  };
  render(
    <StoreProvider initialState={merged}>
      <I18nProvider lang="en">
        <ProjectTab />
      </I18nProvider>
    </StoreProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ProjectTab — HISTOGRAMS table", () => {
  it("renders existing rows with id / data file / format / radiation / geometry / 2θ range", () => {
    renderProjectTab();
    const table = screen.getAllByRole("table")[0]; // HISTOGRAMS table (PHASES is the second)
    expect(within(table).getByText("h0")).toBeInTheDocument();
    expect(within(table).getByText("data/frame0.xye")).toBeInTheDocument();
    expect(within(table).getByText("XYE")).toBeInTheDocument();
    expect(within(table).getByText("xray_lab")).toBeInTheDocument();
    expect(within(table).getByText("bragg_brentano")).toBeInTheDocument();
    expect(within(table).getByText("10.0–90.0")).toBeInTheDocument();
  });

  it("shows the empty-state note when there are no histograms (never fabricates rows)", () => {
    renderProjectTab({}, { viewModel: makeViewModel({ project: { histograms: [], phases: [], settings: { two_theta_limits: null, background_coeffs: null, max_cyc: null } } }) });
    expect(screen.getByText("no histograms loaded")).toBeInTheDocument();
  });
});

describe("ProjectTab — add histogram flow (file select → upload → postAddHistogram)", () => {
  it("calls upload before postAddHistogram, in that order, for both data and instrument files", async () => {
    const user = userEvent.setup();
    const fetchMock = renderProjectTab();

    const dataInput = screen.getByLabelText("data file") as HTMLInputElement;
    const dataFile = new File(["x"], "frame0.xye", { type: "text/plain" });
    await user.upload(dataInput, dataFile);
    await waitFor(() => expect(screen.getByText(/data-frame0\.xye/)).toBeInTheDocument());

    const instrumentInput = screen.getByLabelText("instrument params") as HTMLInputElement;
    const instrumentFile = new File(["y"], "frame0.instprm", { type: "text/plain" });
    await user.upload(instrumentInput, instrumentFile);
    await waitFor(() => expect(screen.getByText(/instrument-frame0\.instprm/)).toBeInTheDocument());

    const addBtn = screen.getByRole("button", { name: "ADD HISTOGRAM" });
    expect(addBtn).not.toBeDisabled();
    await user.click(addBtn);

    await waitFor(() => {
      const addCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project/histograms"));
      expect(addCall).toBeDefined();
    });

    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    const firstUploadIdx = urls.findIndex((u) => u.endsWith("/api/project/upload"));
    const addIdx = urls.findIndex((u) => u.endsWith("/api/project/histograms"));
    expect(firstUploadIdx).toBeGreaterThanOrEqual(0);
    expect(addIdx).toBeGreaterThan(firstUploadIdx);

    // ADD HISTOGRAM is disabled again until a fresh pair of files is chosen
    // (the successful add cleared dataPath/instrumentPath).
    await waitFor(() => expect(screen.getByRole("button", { name: "ADD HISTOGRAM" })).toBeDisabled());
  });

  it("keeps ADD HISTOGRAM disabled until both a data file and an instrument file are chosen", async () => {
    const user = userEvent.setup();
    renderProjectTab();
    expect(screen.getByRole("button", { name: "ADD HISTOGRAM" })).toBeDisabled();

    const dataInput = screen.getByLabelText("data file") as HTMLInputElement;
    await user.upload(dataInput, new File(["x"], "frame0.xye"));
    await waitFor(() => expect(screen.getByText(/data-frame0\.xye/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "ADD HISTOGRAM" })).toBeDisabled();
  });
});

describe("ProjectTab — remove flow (confirmation gate)", () => {
  it("does not call the remove endpoint when the user cancels the confirm dialog", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchMock = renderProjectTab();

    // index 0 = the HISTOGRAMS table's remove button (h0); index 1 = PHASES'.
    await user.click(screen.getAllByRole("button", { name: "remove" })[0]);

    expect(confirmSpy).toHaveBeenCalled();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/remove"))).toBe(false);
  });

  it("calls the remove endpoint and refetches when the user confirms", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = renderProjectTab();

    await user.click(screen.getAllByRole("button", { name: "remove" })[0]);

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/project/histograms/h0/remove"))).toBe(true);
    });
    // refetch (GET state + viewmodel) follows the remove call.
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/viewmodel")).length).toBeGreaterThan(0);
    });
  });

  it("surfaces a 409 (job running) as a non-fatal inline error, not a crash", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderProjectTab({}, { removeHistogramStatus: 409 });

    await user.click(screen.getAllByRole("button", { name: "remove" })[0]);

    await waitFor(() => expect(screen.getByText("job running")).toBeInTheDocument());
    // the tab body is still intact (no unmount / crash) — the table row is
    // still present because the mocked remove call did not actually mutate
    // server state.
    expect(screen.getByText("h0")).toBeInTheDocument();
  });
});

describe("ProjectTab — refine running disables project edits", () => {
  it("disables ADD HISTOGRAM / ADD PHASE / SAVE SETTINGS / SAVE FRAMES / SYNC ECHEM / remove buttons while a refinement (or sequential) job is running", () => {
    renderProjectTab({ refine: { status: "running", elapsed_s: 5, last_event: null, error: null } });

    for (const label of ["ADD HISTOGRAM", "ADD PHASE", "SAVE SETTINGS", "SAVE FRAMES", "SYNC ECHEM"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
    for (const btn of screen.getAllByRole("button", { name: "remove" })) {
      expect(btn).toBeDisabled();
    }
    expect(screen.getByLabelText("data files (multiple)")).toBeDisabled();
    expect(screen.getByText(/refinement is running/)).toBeInTheDocument();
  });

  // NOTE: an earlier version of this test tried to prove the handler-level
  // `if (locked) return` guard independently of the `disabled` attribute by
  // firing a raw DOM click at the disabled button. jsdom itself suppresses
  // click dispatch on a natively `disabled` <button>, so that test passed
  // even with the handler guard deleted (verified by mutation) — a
  // non-failing guard test is worse than no test (CLAUDE.md), so it was
  // removed rather than kept for false confidence. The `disabled` attribute
  // is what's actually load-bearing here, and is covered by the
  // "disables ADD HISTOGRAM / ADD PHASE / SAVE SETTINGS / remove buttons …"
  // tests above (mutation-verified: see the task report).
});

describe("ProjectTab — demo mode is read-only", () => {
  it("disables ADD HISTOGRAM / ADD PHASE / SAVE SETTINGS / SAVE FRAMES / SYNC ECHEM / remove buttons and shows the read-only banner", () => {
    renderProjectTab({}, { shell: makeShell({ source: "demo" }) });

    for (const label of ["ADD HISTOGRAM", "ADD PHASE", "SAVE SETTINGS", "SAVE FRAMES", "SYNC ECHEM"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
    for (const btn of screen.getAllByRole("button", { name: "remove" })) {
      expect(btn).toBeDisabled();
    }
    expect(screen.getByText(/SAMPLE session/)).toBeInTheDocument();
  });

  it("disables the file inputs and selects too (not just the submit buttons)", () => {
    renderProjectTab({}, { shell: makeShell({ source: "demo" }) });
    expect(screen.getByLabelText("data file")).toBeDisabled();
    expect(screen.getByLabelText("instrument params")).toBeDisabled();
  });
});

describe("ProjectTab — SETTINGS card", () => {
  it("prefills two_theta/background/max_cyc from viewModel.project.settings", () => {
    renderProjectTab();
    expect(screen.getByDisplayValue("10")).toBeInTheDocument();
    expect(screen.getByDisplayValue("90")).toBeInTheDocument();
    expect(screen.getByDisplayValue("12")).toBeInTheDocument();
    expect(screen.getByDisplayValue("15")).toBeInTheDocument();
  });

  it("SAVE SETTINGS posts the edited values and refetches", async () => {
    const user = userEvent.setup();
    const fetchMock = renderProjectTab();

    const maxCycInput = screen.getByDisplayValue("15");
    await user.clear(maxCycInput);
    await user.type(maxCycInput, "20");

    await user.click(screen.getByRole("button", { name: "SAVE SETTINGS" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project/settings"));
      expect(call).toBeDefined();
    });
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project/settings"))!;
    const body = JSON.parse(String((init as RequestInit).body));
    expect(body.max_cyc).toBe(20);
    expect(body.two_theta_limits).toEqual([10, 90]);
    expect(body.background_coeffs).toBe(12);
  });
});

// — V2b B1: FRAMES card —

describe("ProjectTab — FRAMES table", () => {
  it("renders existing frame rows (label / axis value / data file)", () => {
    renderProjectTab(
      {},
      {
        viewModel: makeViewModel({
          project: {
            histograms: [histogram()],
            phases: [phase()],
            settings: { two_theta_limits: [10, 90], background_coeffs: 12, max_cyc: 15 },
            frames: [frame({ id: "fr0", label: "fr0", axis_value: 0 }), frame({ id: "fr1", label: "fr1", axis_value: 1, data_path: "data/fr1.xye" })],
          },
        }),
      },
    );
    expect(screen.getByText("fr0")).toBeInTheDocument();
    expect(screen.getByText("fr1")).toBeInTheDocument();
    expect(screen.getByText("data/fr1.xye")).toBeInTheDocument();
  });

  it("shows the empty-state note when there are no frames configured", () => {
    renderProjectTab();
    expect(screen.getByText("no frames configured")).toBeInTheDocument();
  });
});

describe("ProjectTab — add frames flow (multi-file select → sequential upload → postProjectFrames full replace)", () => {
  it("uploads each selected file with kind=data, in order, then saves the full replaced frame list", async () => {
    const user = userEvent.setup();
    const fetchMock = renderProjectTab(
      {},
      {
        viewModel: makeViewModel({
          project: {
            histograms: [histogram()],
            phases: [phase()],
            settings: { two_theta_limits: [10, 90], background_coeffs: 12, max_cyc: 15 },
            frames: [frame({ id: "fr0", label: "fr0", axis_value: 0, data_path: "data/fr0.xye" })],
          },
        }),
      },
    );

    const filesInput = screen.getByLabelText("data files (multiple)") as HTMLInputElement;
    const f1 = new File(["a"], "fr1.xye");
    const f2 = new File(["b"], "fr2.xye");
    await user.upload(filesInput, [f1, f2]);

    // sequential upload — two /api/project/upload calls with kind=data, in order.
    await waitFor(() => {
      const uploadCalls = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/project/upload"));
      expect(uploadCalls.length).toBe(2);
    });
    const uploadCalls = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/project/upload"));
    for (const [, init] of uploadCalls) {
      const form = (init as RequestInit).body as FormData;
      expect(form.get("kind")).toBe("data");
    }

    // index-mode axis_value defaults sequentially, continuing after the
    // existing frame count (existing has 1 row → new rows start at 1, 2).
    // Scoped by aria-label (not getByDisplayValue("1")/("2")) — the ECHEM
    // card's default "interval (s)" field is also literally "1", so a bare
    // display-value query is ambiguous once both cards are on screen.
    await waitFor(() => expect(screen.getByText("fr1.xye")).toBeInTheDocument());
    expect(screen.getByLabelText("axis value fr1.xye")).toHaveValue("1");
    expect(screen.getByLabelText("axis value fr2.xye")).toHaveValue("2");

    const saveBtn = screen.getByRole("button", { name: "SAVE FRAMES" });
    expect(saveBtn).not.toBeDisabled();
    await user.click(saveBtn);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project/frames"));
      expect(call).toBeDefined();
    });
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project/frames"))!;
    const body = JSON.parse(String((init as RequestInit).body));
    // full replace: existing frame (fr0) plus both new ones.
    expect(body.frames).toEqual([
      { data_path: "data/fr0.xye", axis_value: 0, label: "fr0" },
      { data_path: "data/data-fr1.xye", axis_value: 1, label: "fr1.xye" },
      { data_path: "data/data-fr2.xye", axis_value: 2, label: "fr2.xye" },
    ]);
  });

  it("keeps SAVE FRAMES disabled until at least one file is staged", () => {
    renderProjectTab();
    expect(screen.getByRole("button", { name: "SAVE FRAMES" })).toBeDisabled();
  });
});

// — V2b B4: ECHEM card —

describe("ProjectTab — ECHEM sync flow", () => {
  it("posts the sync form and refetches state/viewmodel on success", async () => {
    const user = userEvent.setup();
    const fetchMock = renderProjectTab();

    await user.type(screen.getByLabelText("MPR path"), "data/cell.mpr");
    await user.clear(screen.getByLabelText("offset (s)"));
    await user.type(screen.getByLabelText("offset (s)"), "22.1");
    await user.clear(screen.getByLabelText("interval (s)"));
    await user.type(screen.getByLabelText("interval (s)"), "283");

    await user.click(screen.getByRole("button", { name: "SYNC ECHEM" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/echem"));
      expect(call).toBeDefined();
    });
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/echem"))!;
    const body = JSON.parse(String((init as RequestInit).body));
    expect(body).toEqual({ mpr_path: "data/cell.mpr", offset_s: 22.1, interval_s: 283, sign: 1 });

    await waitFor(() => expect(screen.getByText(/echem synced/)).toBeInTheDocument());
    // session results surface through a fresh GET, not the response body —
    // refetch (state + viewmodel) must follow the sync call.
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/api/viewmodel")).length).toBeGreaterThan(0);
    });
  });

  it("fills the MPR path field from an uploaded file (kind=echem)", async () => {
    const user = userEvent.setup();
    renderProjectTab();

    const fileInput = screen.getByLabelText("MPR file") as HTMLInputElement;
    await user.upload(fileInput, new File(["x"], "cell.mpr"));

    await waitFor(() => expect(screen.getByDisplayValue(/echem-cell\.mpr/)).toBeInTheDocument());
  });

  it("keeps SYNC ECHEM disabled until an MPR path is set", () => {
    renderProjectTab();
    expect(screen.getByRole("button", { name: "SYNC ECHEM" })).toBeDisabled();
  });

  it("surfaces a 422 (invalid mpr) as a non-fatal inline error", async () => {
    const user = userEvent.setup();
    renderProjectTab({}, { echemStatus: 422 });

    await user.type(screen.getByLabelText("MPR path"), "data/bad.mpr");
    await user.click(screen.getByRole("button", { name: "SYNC ECHEM" }));

    await waitFor(() => expect(screen.getByText("invalid mpr file")).toBeInTheDocument());
  });
});
