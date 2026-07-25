import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PhaseRow, ProjectFrameRow, ShellState, ViewModel } from "../../api/types";
import { I18nProvider, type Lang } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { SequenceTab } from "./SequenceTab";

function emptyViewModel(): ViewModel {
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

function makeViewModel(overrides: Partial<ViewModel["sequence"]> = {}): ViewModel {
  const base = emptyViewModel();
  return {
    ...base,
    sequence: {
      charts: [
        { id: "rwp", title: "Rwp vs frame" },
        { id: "lattice", title: "Lattice a, c vs frame" },
        { id: "fraction", title: "Phase fraction vs frame" },
      ],
      anchors: [
        { id: "fr012", crossover: false },
        { id: "fr044", crossover: false },
        { id: "fr091", crossover: true },
        { id: "fr228", crossover: false },
      ],
      note: "crossover fr091 · total_bic minimum · x_XRD follows x_echem within esd",
      segments: [
        { segment: "012–044", forward: "cubic", backward: "cubic", rwp: "6.2", total_bic: "38 110", selected: "forward" },
        { segment: "044–091", forward: "cubic + tetra", backward: "cubic + tetra", rwp: "6.8", total_bic: "39 402", selected: "backward" },
      ],
      ...overrides,
    },
  };
}

function renderTab(
  ui: ReactElement,
  {
    lang = "en" as Lang,
    viewModel,
    extra,
  }: { lang?: Lang; viewModel?: ViewModel; extra?: Partial<WorkbenchState> } = {},
) {
  const initialState: Partial<WorkbenchState> = { lang, viewModel: viewModel ?? null, ...extra };
  return render(
    <StoreProvider initialState={initialState}>
      <I18nProvider lang={lang}>{ui}</I18nProvider>
    </StoreProvider>,
  );
}

describe("SequenceTab — chart cards", () => {
  it("renders the three chart headings from the API viewModel", () => {
    renderTab(<SequenceTab />, { viewModel: makeViewModel() });
    expect(screen.getByText("Rwp vs frame")).toBeInTheDocument();
    expect(screen.getByText("Lattice a, c vs frame")).toBeInTheDocument();
    expect(screen.getByText("Phase fraction vs frame")).toBeInTheDocument();
  });

  it("falls back to the static three-chart shape before the viewModel loads", () => {
    renderTab(<SequenceTab />, { viewModel: undefined });
    expect(screen.getByText("Rwp vs frame")).toBeInTheDocument();
    expect(screen.getByText("Lattice a, c vs frame")).toBeInTheDocument();
    expect(screen.getByText("Phase fraction vs frame")).toBeInTheDocument();
  });
});

describe("SequenceTab — anchor chips", () => {
  it("gives only the crossover anchor the inverted chip variant", () => {
    renderTab(<SequenceTab />, { viewModel: makeViewModel() });

    const crossoverChip = screen.getByText((_, el) => el?.className === "chip chip--inverted chip--mono");
    expect(crossoverChip.className).toContain("chip--inverted");
    expect(crossoverChip.textContent).toContain("fr091");
    expect(crossoverChip.textContent).toContain("crossover");

    const plainChip = screen.getByText("fr012");
    expect(plainChip.className).toContain("chip--accent");
    expect(plainChip.className).not.toContain("chip--inverted");

    const lastChip = screen.getByText("fr228");
    expect(lastChip.className).toContain("chip--accent");
  });

  it("renders the crossover note from the API", () => {
    renderTab(<SequenceTab />, { viewModel: makeViewModel() });
    expect(
      screen.getByText("crossover fr091 · total_bic minimum · x_XRD follows x_echem within esd"),
    ).toBeInTheDocument();
  });
});

describe("SequenceTab — segment selection table", () => {
  it("shows the SELECTED column value for each segment row", () => {
    renderTab(<SequenceTab />, { viewModel: makeViewModel() });

    const table = screen.getByRole("table");
    expect(within(table).getByText("SELECTED")).toBeInTheDocument();

    const forwardRow = screen.getByText("012–044").closest("tr")!;
    expect(within(forwardRow).getByText("forward")).toBeInTheDocument();

    const backwardRow = screen.getByText("044–091").closest("tr")!;
    expect(within(backwardRow).getByText("backward")).toBeInTheDocument();
  });

  it("renders the Rwp column header untranslated (parameter symbol)", () => {
    renderTab(<SequenceTab />, { lang: "ja", viewModel: makeViewModel() });
    const table = screen.getByRole("table");
    expect(within(table).getByText("Rwp")).toBeInTheDocument();
  });
});

describe("SequenceTab — language switch", () => {
  it("translates static chrome to Japanese", () => {
    renderTab(<SequenceTab />, { lang: "ja", viewModel: makeViewModel() });
    expect(screen.getByText("区間選定 · 前方 vs 後方")).toBeInTheDocument();
    expect(screen.getByText("fr091 ✳ 転移")).toBeInTheDocument();
  });
});

// — V2b B2/B3/B4: RUN SEQUENTIAL job, anchor table, per-frame table, charge
// constraint gating (api-contract.md §逐次 / operando) —

function frameRow(overrides: Partial<ProjectFrameRow> = {}): ProjectFrameRow {
  return { id: "fr0", label: "fr0", axis_value: 0, data_path: "data/fr0.xye", ...overrides };
}

function phaseRow(overrides: Partial<PhaseRow> = {}): PhaseRow {
  return {
    id: "p1",
    name: "cubic",
    swatch: "accent",
    space_group: "Fm-3m",
    mp_id: "mp-1",
    wt_frac: "60%",
    ...overrides,
  };
}

function withProjectFramesAndPhases(overrides: Partial<ViewModel> = {}): ViewModel {
  const base = emptyViewModel();
  return {
    ...base,
    phases: [phaseRow({ id: "p1", name: "cubic" }), phaseRow({ id: "p2", name: "tetragonal" })],
    sequence: makeViewModel().sequence,
    project: {
      histograms: [],
      phases: [],
      settings: { two_theta_limits: null, background_coeffs: null, max_cyc: null },
      frames: [
        frameRow({ id: "fr0", label: "fr0", axis_value: 0 }),
        frameRow({ id: "fr1", label: "fr1", axis_value: 1, data_path: "data/fr1.xye" }),
      ],
    },
    ...overrides,
  };
}

function shellWithEchem(echem: ShellState["project"]["echem"] = null): ShellState {
  return {
    project: { name: "p", dataset: "d", frame: "f", echem },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 0, verified: true },
    status: { backend_build: "b", seed: 0, mcp_tools: 0 },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    source: "project",
  };
}

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

function installSequentialFetchMock(opts: {
  sequentialRejects?: { status: number; body: unknown };
  statuses?: unknown[];
  refetchedViewModel?: ViewModel;
}) {
  let statusCallIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/sequential") && method === "POST") {
      if (opts.sequentialRejects) {
        return {
          ok: false,
          status: opts.sequentialRejects.status,
          statusText: "Conflict",
          json: async () => opts.sequentialRejects!.body,
        } as Response;
      }
      return jsonResponse({ status: "started" });
    }
    if (url.endsWith("/api/sequential/status") && method === "GET") {
      const statuses = opts.statuses ?? [{ status: "running", elapsed_s: 1, last_event: null, error: null }];
      const body = statuses[Math.min(statusCallIndex, statuses.length - 1)];
      statusCallIndex += 1;
      return jsonResponse(body);
    }
    if (url.endsWith("/api/viewmodel") && method === "GET") {
      return jsonResponse(opts.refetchedViewModel ?? withProjectFramesAndPhases());
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function flushMicrotasks(times = 6) {
  await act(async () => {
    for (let i = 0; i < times; i++) {
      await Promise.resolve();
    }
  });
}

async function advanceTimers(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("SequenceTab — RUN SEQUENTIAL job (V2b B2/B3)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("defaults to anchored mode and posts mode=anchored with no anchor_table when nothing is checked", async () => {
    const fetchMock = installSequentialFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    renderTab(<SequenceTab />, { viewModel: withProjectFramesAndPhases() });

    fireEvent.click(screen.getByRole("button", { name: "RUN SEQUENTIAL" }));
    await flushMicrotasks();

    const call = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/sequential") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ mode: "anchored" });
  });

  it("polls sequential/status while running and refetches the viewmodel on done", async () => {
    vi.useFakeTimers();
    const refetched = withProjectFramesAndPhases({
      sequence: { ...makeViewModel().sequence, note: "refreshed after sequential run" },
    });
    const fetchMock = installSequentialFetchMock({
      statuses: [
        { status: "running", elapsed_s: 1, last_event: null, error: null },
        { status: "done", elapsed_s: 5, last_event: "complete", error: null },
      ],
      refetchedViewModel: refetched,
    });
    renderTab(<SequenceTab />, { viewModel: withProjectFramesAndPhases() });

    fireEvent.click(screen.getByRole("button", { name: "RUN SEQUENTIAL" }));
    await flushMicrotasks();
    expect(screen.getByRole("button", { name: "RUNNING …" })).toBeDisabled();

    await advanceTimers(2000); // still running
    await advanceTimers(2000); // done

    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/viewmodel"))).toBe(true);
    expect(screen.getByText("refreshed after sequential run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RUN SEQUENTIAL" })).not.toBeDisabled();
  });

  it("409 (job slot busy) shows a non-fatal inline message, not a crash", async () => {
    installSequentialFetchMock({
      sequentialRejects: { status: 409, body: { error: "job running", error_type: "conflict" } },
    });
    const user = userEvent.setup();
    renderTab(<SequenceTab />, { viewModel: withProjectFramesAndPhases() });

    await user.click(screen.getByRole("button", { name: "RUN SEQUENTIAL" }));
    await flushMicrotasks();

    expect(screen.getByText(/already running \(job slot busy\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RUN SEQUENTIAL" })).not.toBeDisabled();
  });

  it("switching mode to forward posts mode=forward and hides the anchor table", async () => {
    const user = userEvent.setup();
    const fetchMock = installSequentialFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    renderTab(<SequenceTab />, { viewModel: withProjectFramesAndPhases() });

    expect(screen.getByText("ANCHOR TABLE")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("mode"), "forward");
    expect(screen.queryByText("ANCHOR TABLE")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "RUN SEQUENTIAL" }));
    await flushMicrotasks();
    const call = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/sequential") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ mode: "forward" });
  });
});

describe("SequenceTab — anchor table (anchored mode)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds anchor_table from the checked frame × phase cells and sends it with the run", async () => {
    const user = userEvent.setup();
    const fetchMock = installSequentialFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    renderTab(<SequenceTab />, { viewModel: withProjectFramesAndPhases() });

    // fr0 → cubic; fr1 → cubic + tetragonal.
    await user.click(screen.getByLabelText("fr0 cubic"));
    await user.click(screen.getByLabelText("fr1 cubic"));
    await user.click(screen.getByLabelText("fr1 tetragonal"));

    await user.click(screen.getByRole("button", { name: "RUN SEQUENTIAL" }));
    await flushMicrotasks();

    const call = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/sequential") && (init as RequestInit | undefined)?.method === "POST",
    );
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body).toEqual({
      mode: "anchored",
      anchor_table: { "0": ["cubic"], "1": ["cubic", "tetragonal"] },
    });
  });

  it("shows the empty-state note instead of the table when no frames are configured", () => {
    renderTab(<SequenceTab />, { viewModel: makeViewModel() });
    expect(screen.getByText(/no frames configured/)).toBeInTheDocument();
    expect(document.querySelector(".seq-tab__anchor-table")).toBeNull();
  });
});

describe("SequenceTab — per-frame results table (sequence.frames[])", () => {
  function withFrameRows(): ViewModel {
    return withProjectFramesAndPhases({
      sequence: {
        ...makeViewModel().sequence,
        frames: [
          { frame: "fr0", label: "frame zero", axis_value: 0, rwp: 6.2, cells: "a=9.37", fractions: "cubic 1.0", changepoint: false },
          { frame: "fr1", label: "frame one", axis_value: 1, rwp: 8.0, cells: "a=9.35 / a=5.4 c=8.1", fractions: "cubic 0.6 / tetra 0.4", changepoint: true },
        ],
      },
    });
  }

  it("renders one row per sequence.frames[] entry with the CHANGEPOINT flag only on the flagged row", () => {
    renderTab(<SequenceTab />, { viewModel: withFrameRows() });

    const table = document.querySelector(".seq-tab__frames-table") as HTMLElement;
    expect(within(table).getByText("frame zero")).toBeInTheDocument();
    expect(within(table).getByText("frame one")).toBeInTheDocument();
    expect(within(table).getByText("cubic 0.6 / tetra 0.4")).toBeInTheDocument();

    const fr1Row = within(table).getByText("frame one").closest("tr")!;
    expect(within(fr1Row).getByText("CHANGEPOINT")).toBeInTheDocument();
    const fr0Row = within(table).getByText("frame zero").closest("tr")!;
    expect(within(fr0Row).queryByText("CHANGEPOINT")).not.toBeInTheDocument();
  });

  it("highlights the row matching state.frameIndex", () => {
    renderTab(<SequenceTab />, { viewModel: withFrameRows(), extra: { frameIndex: 1 } });

    const table = document.querySelector(".seq-tab__frames-table") as HTMLElement;
    const fr1Row = within(table).getByText("frame one").closest("tr")!;
    const fr0Row = within(table).getByText("frame zero").closest("tr")!;
    expect(fr1Row.className).toContain("seq-tab__frame-row--selected");
    expect(fr0Row.className).not.toContain("seq-tab__frame-row--selected");
  });

  it("does not render the per-frame table before a sequential run has produced frames", () => {
    renderTab(<SequenceTab />, { viewModel: withProjectFramesAndPhases() });
    expect(document.querySelector(".seq-tab__frames-table")).toBeNull();
  });
});

describe("SequenceTab — use charge constraint gating (V2b B4, mutation-verified)", () => {
  it("disables the checkbox when ECHEM has not been synced (shell.project.echem is null)", () => {
    renderTab(<SequenceTab />, {
      viewModel: withProjectFramesAndPhases(),
      extra: { shell: shellWithEchem(null) },
    });
    expect(screen.getByRole("checkbox", { name: "use charge constraint" })).toBeDisabled();
    expect(screen.getByText(/sync ECHEM on the PROJECT tab first/)).toBeInTheDocument();
  });

  it("enables the checkbox once ECHEM has been synced (shell.project.echem is non-null)", () => {
    renderTab(<SequenceTab />, {
      viewModel: withProjectFramesAndPhases(),
      extra: { shell: shellWithEchem({ v: 3.94, q_mah_g: 41.2, x_echem: "0.71(2)" }) },
    });
    expect(screen.getByRole("checkbox", { name: "use charge constraint" })).not.toBeDisabled();
    expect(screen.queryByText(/sync ECHEM on the PROJECT tab first/)).not.toBeInTheDocument();
  });

  // Mutation check performed manually (CLAUDE.md: "変異させて fail することを
  // 実証してから受け入れる") — temporarily changing SequenceTab.tsx's
  // `disabled={jobRunning || !echemSynced}` to `disabled={jobRunning}` made
  // the first test above fail (checkbox was enabled with echem null), and
  // reverting restored both tests to green. See the task report.
  it("includes use_charge_constraint=true in the run payload only when checked AND echem is synced", async () => {
    const user = userEvent.setup();
    const fetchMock = installSequentialFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    renderTab(<SequenceTab />, {
      viewModel: withProjectFramesAndPhases(),
      extra: { shell: shellWithEchem({ v: 3.94, q_mah_g: 41.2, x_echem: "0.71(2)" }) },
    });

    await user.click(screen.getByRole("checkbox", { name: "use charge constraint" }));
    await user.click(screen.getByRole("button", { name: "RUN SEQUENTIAL" }));
    await flushMicrotasks();

    const call = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/sequential") && (init as RequestInit | undefined)?.method === "POST",
    );
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body.use_charge_constraint).toBe(true);
  });
});

describe("SequenceTab — real chart series", () => {
  it("draws an svg line for a chart whose series is present", () => {
    const { container } = renderTab(
      <SequenceTab />,
      {
        viewModel: makeViewModel({
          charts: [
            { id: "rwp", title: "Rwp vs frame", series: { x: [0, 1, 2], ys: [[13.4, 12.1, 9.8]], labels: ["Rwp"] } },
            { id: "lattice", title: "Lattice a, c vs frame", series: null },
            { id: "fraction", title: "Phase fraction vs frame", series: null },
          ],
        }),
      },
    );

    const cards = container.querySelectorAll(".seq-tab__chart-card");
    expect(within(cards[0] as HTMLElement).getByRole("img")).toBeInTheDocument();
    expect(cards[0].querySelector("svg path")).not.toBeNull();
  });

  it("falls back to the empty-state placeholder for a chart whose series is null", () => {
    const { container } = renderTab(
      <SequenceTab />,
      {
        viewModel: makeViewModel({
          charts: [
            { id: "rwp", title: "Rwp vs frame", series: null },
            { id: "lattice", title: "Lattice a, c vs frame", series: null },
            { id: "fraction", title: "Phase fraction vs frame", series: null },
          ],
        }),
      },
    );

    const cards = container.querySelectorAll(".seq-tab__chart-card");
    expect(cards[0].querySelector(".placeholder-plot__frame")).not.toBeNull();
    expect(cards[0].querySelector("svg")).toBeNull();
  });

  it("draws a legend when a chart has more than one series", () => {
    const { container } = renderTab(
      <SequenceTab />,
      {
        viewModel: makeViewModel({
          charts: [
            {
              id: "fraction",
              title: "Phase fraction vs frame",
              series: { x: [0, 1], ys: [[0.6, 0.5], [0.4, 0.5]], labels: ["cubic", "tetragonal"] },
            },
          ],
        }),
      },
    );
    const legend = within(container.querySelector(".series-chart__legend") as HTMLElement);
    expect(legend.getByText("cubic")).toBeInTheDocument();
    expect(legend.getByText("tetragonal")).toBeInTheDocument();
    expect(container.querySelectorAll(".series-chart__legend-item").length).toBe(2);
  });
});
