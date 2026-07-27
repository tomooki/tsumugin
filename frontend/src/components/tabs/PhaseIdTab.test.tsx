import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PhaseIdViewModel, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { OperatorConsole } from "../right/OperatorConsole";
import { PhaseIdTab } from "./PhaseIdTab";

function makePhaseId(overrides: Partial<PhaseIdViewModel> = {}): PhaseIdViewModel {
  return {
    candidates: [
      {
        rank: 1,
        formula: "K2Mn[Fe(CN)6]",
        source: "MP",
        sg: "P21/n",
        dara: 0.71,
        mwmsx: "18/1/2/0",
        strain: "0.004",
        chem_guard: "full system",
        guard_fail: false,
        mp_id: "mp-583814",
      },
      {
        rank: 4,
        formula: "Mn[Fe(CN)6]",
        source: "MP",
        sg: "Pm-3m",
        dara: 0.38,
        mwmsx: "9/5/9/4",
        strain: "0.019",
        chem_guard: "K missing",
        guard_fail: true,
        mp_id: "mp-999999",
      },
      {
        rank: 5,
        formula: "K4Fe(CN)6·3H2O",
        source: "MP",
        sg: "C2/c",
        dara: 0.21,
        mwmsx: "6/8/14/7",
        strain: "0.031",
        chem_guard: "demoted",
        guard_fail: true,
        mp_id: "mp-111111",
      },
    ],
    unexplained: [
      { two_theta: 12.42, sn: 6.1, indexing: "unindexed" },
      { two_theta: 17.88, sn: 4.4, indexing: "unindexed" },
    ],
    completeness: {
      is_complete: false,
      notes: ["tetragonal fraction non-monotonic on frames 84-96"],
      flagged_frames: "9 / 63",
    },
    ...overrides,
  };
}

function makeMinimalViewModel(phaseId: PhaseIdViewModel): ViewModel {
  return {
    datasets: [],
    phases: [],
    channels: [],
    snapshots: [],
    fit: { metrics: [], histograms: [], limits_note: "", phase_ticks: [], two_theta: { min: 0, max: 0 }, history: [], validity: [] },
    parameters: {},
    hypotheses: { rows: [], diff: { vs: "", rows: [] }, evidence: [] },
    phase_id: phaseId,
    sequence: { charts: [], anchors: [], note: "", segments: [] },
    structure: { sites: [], constraints: [], mem_peaks: [] },
    stages: [],
    review: [],
    transcript: [],
  };
}

function renderTab(overrides: Partial<PhaseIdViewModel> = {}, stateOverrides: Partial<WorkbenchState> = {}) {
  const initialState: Partial<WorkbenchState> = {
    viewModel: { phase_id: makePhaseId(overrides) } as unknown as ViewModel,
    ...stateOverrides,
  };
  return render(
    <StoreProvider initialState={initialState}>
      <I18nProvider lang="en">
        <PhaseIdTab />
      </I18nProvider>
    </StoreProvider>,
  );
}

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

describe("PhaseIdTab — candidate table", () => {
  it("highlights the top-ranked row", () => {
    renderTab();
    const topRow = screen.getByText("K2Mn[Fe(CN)6]").closest("tr");
    expect(topRow?.className).toContain("pid-table__row--top");
  });

  it("renders guard-fail cells as the inverted chip variant", () => {
    renderTab();
    const kMissing = screen.getByText("K missing");
    expect(kMissing.className).toContain("chip--inverted");
    const demoted = screen.getByText("demoted");
    expect(demoted.className).toContain("chip--inverted");
    const fullSystem = screen.getByText("full system");
    expect(fullSystem.className).not.toContain("chip--inverted");
  });

  it("renders the unexplained-feature rows verbatim", () => {
    renderTab();
    expect(screen.getByText(/2θ 12.42 · S\/N 6.1 · unindexed/)).toBeInTheDocument();
  });
});

describe("PhaseIdTab — PHASE SET COMPLETENESS", () => {
  it("renders is_complete FALSE as the inverted chip", () => {
    renderTab();
    const chip = screen.getByText("FALSE");
    expect(chip.className).toContain("chip--inverted");
  });

  it("renders is_complete TRUE as a non-inverted chip", () => {
    renderTab({ completeness: { is_complete: true, notes: [], flagged_frames: "0 / 63" } });
    const chip = screen.getByText("TRUE");
    expect(chip.className).not.toContain("chip--inverted");
  });

  it("shows the flagged-frames value and the acceptance-criteria caveat note", () => {
    renderTab();
    expect(screen.getByText("9 / 63")).toBeInTheDocument();
    expect(
      screen.getByText(/A missing phase is outside their field of view/),
    ).toBeInTheDocument();
  });
});

// — A4: IDENTIFY job + ADD AS PHASE wiring (api-contract.md §解析ループ) —

function installFetchMock(opts: {
  identifyRejects?: { status: number; body: unknown };
  statuses?: unknown[];
  addRejects?: { status: number; body: unknown };
  refetchedPhaseId?: PhaseIdViewModel;
}) {
  let statusCallIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/phaseid") && method === "POST") {
      if (opts.identifyRejects) {
        return {
          ok: false,
          status: opts.identifyRejects.status,
          statusText: "Conflict",
          json: async () => opts.identifyRejects!.body,
        } as Response;
      }
      return jsonResponse({ status: "started" });
    }
    if (url.endsWith("/api/phaseid/status") && method === "GET") {
      const statuses = opts.statuses ?? [{ status: "running", elapsed_s: 1, last_event: null, error: null }];
      const body = statuses[Math.min(statusCallIndex, statuses.length - 1)];
      statusCallIndex += 1;
      return jsonResponse(body);
    }
    if (url.endsWith("/api/viewmodel") && method === "GET") {
      return jsonResponse(makeMinimalViewModel(opts.refetchedPhaseId ?? makePhaseId()));
    }
    if (url.endsWith("/api/phaseid/add") && method === "POST") {
      if (opts.addRejects) {
        return {
          ok: false,
          status: opts.addRejects.status,
          statusText: "error",
          json: async () => opts.addRejects!.body,
        } as Response;
      }
      return jsonResponse({
        project: { name: "p", dataset: "d", frame: "f", echem: null },
        mode: "manual",
        final_selection_mode: "human",
        ledger: { count: 2, verified: true },
        status: { backend_build: "b", seed: 0, mcp_tools: 36, gsas_available: true },
        agent: { tokens: 0, wall_time_s: 0, idle: true },
      });
    }
    if (url.endsWith("/api/refine/status") && method === "GET") {
      return jsonResponse({ status: "idle", elapsed_s: null, last_event: null, error: null });
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

describe("PhaseIdTab — IDENTIFY job (A4)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("posts mode=pattern by default, polls, and refetches the viewmodel on done", async () => {
    vi.useFakeTimers();
    const refetched = makePhaseId({
      candidates: [
        {
          rank: 1,
          formula: "KMnFe(CN)6",
          source: "MP",
          sg: "Fm-3m",
          dara: 0.9,
          mwmsx: "1/0/0/0",
          strain: "0.001",
          chem_guard: "full system",
          guard_fail: false,
          mp_id: "mp-1",
        },
      ],
    });
    const fetchMock = installFetchMock({
      statuses: [
        { status: "running", elapsed_s: 1, last_event: null, error: null },
        { status: "done", elapsed_s: 3, last_event: "complete", error: null },
      ],
      refetchedPhaseId: refetched,
    });
    renderTab();

    fireEvent.click(screen.getByRole("button", { name: "IDENTIFY" }));
    await flushMicrotasks();

    const startCall = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/phaseid") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(startCall).toBeDefined();
    expect(JSON.parse(String((startCall![1] as RequestInit).body))).toEqual({ mode: "pattern" });
    expect(screen.getByRole("button", { name: "IDENTIFYING …" })).toBeDisabled();

    await advanceTimers(2000); // still running
    await advanceTimers(2000); // done — advanceTimersByTimeAsync also flushes the
    // onDone microtask chain (getViewModel().then(dispatch)), so the refetched
    // candidate is already rendered by the time this resolves (no waitFor
    // needed — and waitFor's own internal polling does not advance vitest's
    // fake timers, so it would hang here).

    expect(screen.getByText("KMnFe(CN)6")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/viewmodel"))).toBe(true);
    expect(screen.getByRole("button", { name: "IDENTIFY" })).not.toBeDisabled();
  });

  it("posts mode=residual when the mode select is changed", async () => {
    const fetchMock = installFetchMock({ statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }] });
    const user = userEvent.setup();
    renderTab();

    await user.selectOptions(screen.getByLabelText("mode"), "residual");
    await user.click(screen.getByRole("button", { name: "IDENTIFY" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, init]) => String(u).endsWith("/api/phaseid") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ mode: "residual" });
    });
  });

  it("residual mode 409 (job slot busy) shows a non-fatal inline message, not a crash", async () => {
    installFetchMock({ identifyRejects: { status: 409, body: { error: "job running", error_type: "conflict" } } });
    const user = userEvent.setup();
    renderTab();

    await user.selectOptions(screen.getByLabelText("mode"), "residual");
    await user.click(screen.getByRole("button", { name: "IDENTIFY" }));

    await waitFor(() =>
      expect(screen.getByText(/already running \(job slot busy\)/)).toBeInTheDocument(),
    );
    // still interactive — not a fatal/unmounted state
    expect(screen.getByRole("button", { name: "IDENTIFY" })).not.toBeDisabled();
  });

  it("disables RUN REFINEMENT (OperatorConsole) while IDENTIFY is running — shared job slot", async () => {
    vi.useFakeTimers();
    installFetchMock({ statuses: [{ status: "running", elapsed_s: 1, last_event: null, error: null }] });
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <I18nProvider lang="en">
          <StoreProvider initialState={{ viewModel: makeMinimalViewModel(makePhaseId()) }}>{children}</StoreProvider>
        </I18nProvider>
      );
    }
    render(
      <>
        <OperatorConsole />
        <PhaseIdTab />
      </>,
      { wrapper: Wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "IDENTIFY" }));
    await flushMicrotasks();

    // OperatorConsole's RUN REFINEMENT relabels to RUNNING … (and disables)
    // whenever the shared state.refine slot is running, regardless of which
    // job kind set it — this is that cross-component disabling in action.
    expect(screen.queryByRole("button", { name: "RUN REFINEMENT" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RUNNING …" })).toBeDisabled();
  });
});

// — api-contract.md §アプリ設定: mp_available pre-disables IDENTIFY/ADD AS PHASE —

function makeShellWithMp(mpAvailable: boolean): WorkbenchState["shell"] {
  return {
    project: { name: "p", dataset: "d", frame: "f", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 1, verified: true },
    status: { backend_build: "b", seed: 0, mcp_tools: 36, gsas_available: true, mp_available: mpAvailable },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
  };
}

describe("PhaseIdTab — Materials Project token unavailable (api-contract.md §アプリ設定)", () => {
  it("disables IDENTIFY and shows the settings tooltip when mp_available is false", () => {
    renderTab({}, { shell: makeShellWithMp(false) });
    const identifyBtn = screen.getByRole("button", { name: "IDENTIFY" });
    expect(identifyBtn).toBeDisabled();
    expect(identifyBtn.title).toMatch(/Materials Project token not set/);
  });

  it("disables ADD AS PHASE for every candidate row when mp_available is false", () => {
    renderTab({}, { shell: makeShellWithMp(false) });
    for (const btn of screen.getAllByRole("button", { name: "ADD AS PHASE" })) {
      expect(btn).toBeDisabled();
    }
  });

  it("leaves IDENTIFY and ADD AS PHASE enabled when mp_available is true", () => {
    renderTab({}, { shell: makeShellWithMp(true) });
    expect(screen.getByRole("button", { name: "IDENTIFY" })).not.toBeDisabled();
    for (const btn of screen.getAllByRole("button", { name: "ADD AS PHASE" })) {
      expect(btn).not.toBeDisabled();
    }
  });

  it("does not disable the buttons when shell/status has not loaded yet (mp_available unknown)", () => {
    renderTab({});
    expect(screen.getByRole("button", { name: "IDENTIFY" })).not.toBeDisabled();
  });
});

describe("PhaseIdTab — ADD AS PHASE (A4)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts {formula, mp_id} for the clicked row, then refetches state + viewmodel on success", async () => {
    const fetchMock = installFetchMock({});
    const user = userEvent.setup();
    renderTab();

    const topRow = screen.getByText("K2Mn[Fe(CN)6]").closest("tr")!;
    await user.click(within(topRow).getByRole("button", { name: "ADD AS PHASE" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/phaseid/add"));
      expect(call).toBeDefined();
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
        formula: "K2Mn[Fe(CN)6]",
        mp_id: "mp-583814",
      });
    });

    await waitFor(() =>
      expect(screen.getByText(/K2Mn\[Fe\(CN\)6\] added/)).toBeInTheDocument(),
    );
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/viewmodel"))).toBe(true);
  });

  it("surfaces an API error inline and keeps the row usable on failure", async () => {
    installFetchMock({ addRejects: { status: 422, body: { error: "no such mp_id", error_type: "not_found" } } });
    const user = userEvent.setup();
    renderTab();

    const topRow = screen.getByText("K2Mn[Fe(CN)6]").closest("tr")!;
    await user.click(within(topRow).getByRole("button", { name: "ADD AS PHASE" }));

    await waitFor(() => expect(screen.getByText(/no such mp_id/)).toBeInTheDocument());
    expect(within(topRow).getByRole("button", { name: "ADD AS PHASE" })).not.toBeDisabled();
  });
});

describe("PhaseIdTab — element system (real, not a fixed label)", () => {
  it("shows the element system the server actually derived from the phase CIFs", () => {
    renderTab({ elements: ["Ca", "O", "Te"] });
    const note = document.querySelector(".pid-tab__note")!;
    expect(note.textContent).toContain("Ca, O, Te");
  });

  it("never hard-codes the mockup's element list", () => {
    // 恒久ガード: プロトタイプ由来の固定表記 (K, Mn, Fe, C, N, O) が復活したら落ちる。
    // 表示は viewmodel.phase_id.elements のみを情報源にする。
    renderTab({ elements: ["Ca", "O", "Te"] });
    const note = document.querySelector(".pid-tab__note")!;
    expect(note.textContent).not.toContain("K, Mn, Fe");
  });

  it("says nothing about elements when the server reports none", () => {
    renderTab({ elements: [] });
    const note = document.querySelector(".pid-tab__note")!;
    expect(note.textContent?.toLowerCase()).not.toContain("element");
    // 手法の記述 (実際に固定されている設定) は残す
    expect(note.textContent).toContain("Dara");
  });

  it("does not crash when an older server omits `elements`", () => {
    renderTab();
    expect(document.querySelector(".pid-tab__note")!.textContent).toContain("Dara");
  });
});

describe("PhaseIdTab — element selection (CIF 先読み不要の動線)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("seeds the selector from the server's element system", () => {
    renderTab({ elements: ["Ca", "O", "Te"] });
    for (const el of ["Ca", "O", "Te"]) {
      expect(screen.getByRole("button", { name: `remove ${el}` })).toBeInTheDocument();
    }
  });

  it("adding an element updates the note and is sent with IDENTIFY", async () => {
    const fetchMock = installFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    const user = userEvent.setup();
    renderTab({ elements: ["Ca"] });

    await user.selectOptions(screen.getByLabelText("add element"), "Te");
    expect(document.querySelector(".pid-tab__note")!.textContent).toContain("Ca, Te");

    await user.click(screen.getByRole("button", { name: "IDENTIFY" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, init]) =>
          String(u).endsWith("/api/phaseid") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
        mode: "pattern",
        elements: ["Ca", "Te"],
      });
    });
  });

  it("removing an element drops it from the request", async () => {
    const fetchMock = installFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    const user = userEvent.setup();
    renderTab({ elements: ["Ca", "Te"] });

    await user.click(screen.getByRole("button", { name: "remove Te" }));
    await user.click(screen.getByRole("button", { name: "IDENTIFY" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, init]) =>
          String(u).endsWith("/api/phaseid") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
        mode: "pattern",
        elements: ["Ca"],
      });
    });
  });

  it("omits `elements` entirely when nothing is selected (server derives from CIFs)", async () => {
    const fetchMock = installFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    const user = userEvent.setup();
    renderTab({ elements: [] });

    await user.click(screen.getByRole("button", { name: "IDENTIFY" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, init]) =>
          String(u).endsWith("/api/phaseid") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ mode: "pattern" });
    });
  });

  it("never offers D — an isotope of H that Materials Project's chemsys has no entry for", async () => {
    renderTab({ elements: [] });
    const options = Array.from(
      (screen.getByLabelText("add element") as HTMLSelectElement).options,
    ).map((o) => o.value);
    expect(options).toContain("H");
    expect(options).not.toContain("D");
  });

  it("does not offer an already-selected element twice", () => {
    renderTab({ elements: ["Ca"] });
    const options = Array.from(
      (screen.getByLabelText("add element") as HTMLSelectElement).options,
    ).map((o) => o.value);
    expect(options).not.toContain("Ca");
  });
});
