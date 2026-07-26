import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConstraintRow, MemMap, MemPeak, MemViewModel, Site, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import type { WorkbenchState } from "../../state/types";
import { StoreProvider } from "../../state/store";
import { STRUCT_LOCAL_STRINGS } from "./StructureTab.strings";
import { StructureTab } from "./StructureTab";

function makeSite(overrides: Partial<Site> = {}): Site {
  return {
    id: "s1",
    label: "K1",
    el: "K",
    x: "0.2500",
    y: "0.2500",
    z: "0.2500",
    occ: "0.710",
    uiso: "0.041",
    note: "free_occupancy",
    lock: { x: true, y: true, z: true },
    rel: { occ: true },
    ...overrides,
  };
}

function makeConstraint(overrides: Partial<ConstraintRow> = {}): ConstraintRow {
  return { kind: "EqnConstr", text: "Σ occ(K1) · Z = x_total(t)", ref: "FR-318", ...overrides };
}

function makeMemPeak(overrides: Partial<MemPeak> = {}): MemPeak {
  return { position: "(0.5, 0.25, 0.0)", density: "0.82 fm Å⁻³", assign: "Ow?", ...overrides };
}

function makeViewModel(sites: Site[]): ViewModel {
  return {
    datasets: [],
    phases: [],
    channels: [],
    snapshots: [],
    fit: { metrics: [], histograms: [], limits_note: "", phase_ticks: [], two_theta: { min: 0, max: 0 }, history: [], validity: [] },
    parameters: {},
    hypotheses: { rows: [], diff: { vs: "", rows: [] }, evidence: [] },
    phase_id: { candidates: [], unexplained: [], completeness: { is_complete: true, notes: [], flagged_frames: "" } },
    sequence: { charts: [], anchors: [], note: "", segments: [] },
    structure: { sites, constraints: [makeConstraint()], mem_peaks: [makeMemPeak()] },
    stages: [],
    review: [],
    transcript: [],
  };
}

function renderTab(initialState: Partial<WorkbenchState> = {}) {
  return render(
    <StoreProvider initialState={initialState}>
      <I18nProvider lang="en">
        <StructureTab />
      </I18nProvider>
    </StoreProvider>,
  );
}

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

describe("StructureTab — SITES table editing", () => {
  it("editing a numeric cell increments the pending-edit count", async () => {
    const user = userEvent.setup();
    const site = makeSite({ id: "s1", label: "K1", rel: { occ: true }, lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    expect(screen.getByText("no pending edits")).toBeInTheDocument();

    const occInput = screen.getByLabelText("K1 occ");
    await user.clear(occInput);
    await user.type(occInput, "0.5");

    expect(screen.getByText(/pending edit/)).toBeInTheDocument();
  });

  it("changing the ELEMENT dropdown also increments the pending-edit count", async () => {
    const user = userEvent.setup();
    const site = makeSite({ id: "s1", label: "K1", el: "K", lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    const select = screen.getByLabelText("K1 element");
    await user.selectOptions(select, "O");

    expect(screen.getByText(/pending edit/)).toBeInTheDocument();
    expect((select as HTMLSelectElement).value).toBe("O");
  });

  it("the 99-element dropdown lists D immediately after H", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    const select = screen.getByLabelText("K1 element") as HTMLSelectElement;
    const labels = Array.from(select.options).map((o) => o.textContent);
    const hIndex = labels.indexOf("1 H");
    expect(labels[hIndex + 1]).toBe("1 D");
    expect(labels).toHaveLength(99);
  });
});

describe("StructureTab — symmetry lock", () => {
  it("disables the checkbox and value input for a locked coordinate", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: { x: true, y: true, z: true } });
    renderTab({ viewModel: makeViewModel([site]) });

    const xInput = screen.getByLabelText("K1 x");
    const xRelease = screen.getByLabelText("release K1 x");
    expect(xInput).toBeDisabled();
    expect(xRelease).toBeDisabled();
  });

  it("leaves occ/uiso editable even though x/y/z are locked (no lock slot for them)", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: { x: true, y: true, z: true } });
    renderTab({ viewModel: makeViewModel([site]) });

    expect(screen.getByLabelText("K1 occ")).not.toBeDisabled();
    expect(screen.getByLabelText("K1 uiso")).not.toBeDisabled();
  });
});

describe("StructureTab — release checkboxes", () => {
  it("toggling a release checkbox updates the released-parameters count", async () => {
    const user = userEvent.setup();
    const site = makeSite({ id: "s1", label: "K1", lock: {}, rel: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    expect(screen.getByText("released: 0 atomic parameters")).toBeInTheDocument();

    await user.click(screen.getByLabelText("release K1 occ"));
    expect(screen.getByText("released: 1 atomic parameters")).toBeInTheDocument();

    await user.click(screen.getByLabelText("release K1 occ"));
    expect(screen.getByText("released: 0 atomic parameters")).toBeInTheDocument();
  });

  it("a released, unlocked cell does not count a locked coordinate even if rel is set", () => {
    // lock wins over rel in the released-count (mirrors the handoff's cellBg/
    // count logic: `rel[k] && !lock[k]`).
    const site = makeSite({ id: "s1", label: "K1", lock: { x: true }, rel: { x: true } });
    renderTab({ viewModel: makeViewModel([site]) });
    expect(screen.getByText("released: 0 atomic parameters")).toBeInTheDocument();
  });
});

describe("StructureTab — ADD ATOM / delete row", () => {
  it("ADD ATOM appends a row flagged 'new' and increments edits", async () => {
    const user = userEvent.setup();
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2); // header + 1 site

    await user.click(screen.getByRole("button", { name: /ADD ATOM/ }));

    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("new")).toBeInTheDocument();
    expect(screen.getByText(/pending edit/)).toBeInTheDocument();
  });

  it("× deletes a row from the working model only (no network call)", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);

    await user.click(screen.getByTitle("delete atom"));

    expect(within(table).getAllByRole("row")).toHaveLength(1); // header only
    expect(screen.getByText(/pending edit/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});

describe("StructureTab — DISCARD", () => {
  it("is disabled when there are no pending edits", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    expect(screen.getByRole("button", { name: "DISCARD" })).toBeDisabled();
  });

  it("restores the working model to the applied baseline, not the original committed model", async () => {
    const user = userEvent.setup();
    // committed/ledger baseline (viewModel seed): occ = 0.500
    // applied baseline (a prior ReviseStructure already applied client-side): occ = 0.600
    const committedSite = makeSite({ id: "s1", label: "K1", lock: {}, occ: "0.500" });
    const appliedSite = makeSite({ id: "s1", label: "K1", lock: {}, occ: "0.600" });
    renderTab({
      viewModel: makeViewModel([committedSite]),
      appliedSites: [appliedSite],
    });

    expect(screen.getByLabelText("K1 occ")).toHaveValue("0.600");

    const occInput = screen.getByLabelText("K1 occ");
    await user.clear(occInput);
    await user.type(occInput, "0.999");
    expect(screen.getByLabelText("K1 occ")).toHaveValue("0.999");

    const discardBtn = screen.getByRole("button", { name: "DISCARD" });
    expect(discardBtn).not.toBeDisabled();
    await user.click(discardBtn);

    expect(screen.getByText("no pending edits")).toBeInTheDocument();
    expect(screen.getByLabelText("K1 occ")).toHaveValue("0.600");
  });
});

describe("StructureTab — APPLY AS ReviseStructure", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ snapshot_id: "S-9001", ledger_index: 42 })),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls postStructureApply with the current sites payload and resets edits on success", async () => {
    const user = userEvent.setup();
    const site = makeSite({ id: "s1", label: "K1", lock: {}, occ: "0.500" });
    renderTab({ viewModel: makeViewModel([site]) });

    const occInput = screen.getByLabelText("K1 occ");
    await user.clear(occInput);
    await user.type(occInput, "0.777");
    expect(screen.getByText(/pending edit/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "APPLY AS ReviseStructure" }));

    await waitFor(() =>
      expect(screen.getByText("applied · ReviseStructure logged, child snapshot S-0312")).toBeInTheDocument(),
    );
    // A3: the applied state also carries a hint that the edit is not live
    // yet — it only feeds initial_occupancies on the next real refine run.
    expect(screen.getByText("applies on the next RUN REFINEMENT")).toBeInTheDocument();

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/structure/apply");
    const body = JSON.parse(String(init.body));
    expect(body.sites).toEqual([{ ...site, occ: "0.777" }]);

    expect(screen.queryByText("no pending edits")).not.toBeInTheDocument();
  });

  it("surfaces an API error and keeps the pending edits on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ error: "guard rejected", error_type: "guard" }, false, 422)),
    );
    const user = userEvent.setup();
    const site = makeSite({ id: "s1", label: "K1", lock: {}, occ: "0.500" });
    renderTab({ viewModel: makeViewModel([site]) });

    const occInput = screen.getByLabelText("K1 occ");
    await user.clear(occInput);
    await user.type(occInput, "0.777");

    await user.click(screen.getByRole("button", { name: "APPLY AS ReviseStructure" }));

    await waitFor(() => expect(screen.getByText(/guard rejected/)).toBeInTheDocument());
    expect(screen.getByText(/pending edit/)).toBeInTheDocument();
  });
});

describe("StructureTab — A3 'next run' hint", () => {
  it("does not show the hint before anything has been applied", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });
    expect(screen.queryByText("applies on the next RUN REFINEMENT")).not.toBeInTheDocument();
  });

  it("does not show the hint while a new edit is pending on top of an applied baseline", async () => {
    const user = userEvent.setup();
    const site = makeSite({ id: "s1", label: "K1", lock: {}, occ: "0.500" });
    renderTab({ viewModel: makeViewModel([site]), applied: true });

    const occInput = screen.getByLabelText("K1 occ");
    await user.clear(occInput);
    await user.type(occInput, "0.6");

    expect(screen.queryByText("applies on the next RUN REFINEMENT")).not.toBeInTheDocument();
  });
});

describe("StructureTab — CONSTRAINTS and MEM DENSITY cards", () => {
  it("renders constraint rows and mem density peaks from the viewModel", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModel([site]) });

    expect(screen.getByText("Σ occ(K1) · Z = x_total(t)")).toBeInTheDocument();
    expect(screen.getByText("EqnConstr · FR-318")).toBeInTheDocument();
    expect(screen.getByText("(0.5, 0.25, 0.0) · 0.82 fm Å⁻³ → Ow?")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// V3b: MEM DENSITY heatmap + RUN MEM job (FR-601, api-contract.md §MEM 密度マップ)
// ---------------------------------------------------------------------------

function makeMemMap(overrides: Partial<MemMap> = {}): MemMap {
  return {
    axis: "c",
    index: 0,
    nx: 2,
    ny: 2,
    values: [
      [0, 1],
      [2, 3],
    ],
    vmin: 0,
    vmax: 3,
    unit: "e·Å⁻³",
    ...overrides,
  };
}

/** Extends `makeViewModel` with structure.mem and (optionally) a refined
 * plot for the default active histogram ("sxrd", see state/types.ts
 * initialWorkbenchState) — RUN MEM's disabled condition reuses FitTab's
 * existing "has this histogram been refined" signal (plot.ycalc presence). */
function makeViewModelWithMem(
  sites: Site[],
  mem: MemViewModel | null,
  refined = false,
): ViewModel {
  const vm = makeViewModel(sites);
  return {
    ...vm,
    structure: { ...vm.structure, mem },
    fit: refined
      ? {
          ...vm.fit,
          plot: {
            sxrd: { x: [1, 2], yobs: [1, 2], ycalc: [1, 2], ybkg: null, residual: null, ticks: {} },
          },
        }
      : vm.fit,
  };
}

function jsonResponseMem(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

function installMemFetchMock(opts: {
  memRejects?: { status: number; body: unknown };
  statuses?: unknown[];
  refetchedViewModel?: ViewModel;
}) {
  let statusCallIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/mem") && method === "POST") {
      if (opts.memRejects) {
        return {
          ok: false,
          status: opts.memRejects.status,
          statusText: "error",
          json: async () => opts.memRejects!.body,
        } as Response;
      }
      return jsonResponseMem({ status: "started" });
    }
    if (url.endsWith("/api/mem/status") && method === "GET") {
      const statuses = opts.statuses ?? [
        { status: "running", elapsed_s: 1, last_event: null, error: null, kind: "mem" },
      ];
      const body = statuses[Math.min(statusCallIndex, statuses.length - 1)];
      statusCallIndex += 1;
      return jsonResponseMem(body);
    }
    if (url.endsWith("/api/refine/status") && method === "GET") {
      return jsonResponseMem({ status: "idle", elapsed_s: null, last_event: null, error: null });
    }
    if (url.endsWith("/api/viewmodel") && method === "GET") {
      return jsonResponseMem(
        opts.refetchedViewModel ??
          makeViewModelWithMem([], { map: makeMemMap(), peaks: [], note: "" }, true),
      );
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function flushMicrotasksMem(times = 6) {
  await act(async () => {
    for (let i = 0; i < times; i++) {
      await Promise.resolve();
    }
  });
}

async function advanceTimersMem(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("StructureTab — MEM DENSITY heatmap (V3b)", () => {
  it("shows the placeholder empty-state when structure.mem is absent", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModelWithMem([site], null) });
    expect(screen.getByText("MAP PLACEHOLDER — Dysnomia section · z = 0.25")).toBeInTheDocument();
  });

  it("renders an SVG heatmap sized nx×ny with a vmin–vmax legend when structure.mem.map is present", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    const mem: MemViewModel = {
      map: makeMemMap(),
      peaks: [makeMemPeak()],
      note: "electron · converged=yes",
    };
    renderTab({ viewModel: makeViewModelWithMem([site], mem) });

    expect(
      screen.queryByText("MAP PLACEHOLDER — Dysnomia section · z = 0.25"),
    ).not.toBeInTheDocument();
    const svg = document.querySelector(".heat-map__svg");
    expect(svg).not.toBeNull();
    expect(svg?.querySelectorAll("rect").length).toBe(4); // nx=2 × ny=2
    expect(screen.getByText(/0\.00 – 3\.00 e·Å⁻³/)).toBeInTheDocument();
  });
});

describe("StructureTab — RUN MEM job (V3b, FR-601)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("is disabled before anything has been refined", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModelWithMem([site], null, false) });
    expect(screen.getByRole("button", { name: "RUN MEM" })).toBeDisabled();
  });

  it("is disabled while another job owns the shared job slot", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({
      viewModel: makeViewModelWithMem([site], null, true),
      refine: { status: "running", elapsed_s: 1, last_event: null, error: null, kind: "refine" },
      activeJob: "refine",
    });
    // 【変異実証】: `memDisabled` を `!hasRefined` だけにする (jobRunning を落とす) と、この
    //   アサーションは fail する — RUN MEM が有効なままになってしまい、共有ジョブ枠の 409 を
    //   起動側でなく応答側でしか検知できなくなる (元の実装は事前に disabled で防いでいる)。
    expect(screen.getByRole("button", { name: "RUN MEM" })).toBeDisabled();
  });

  it("is enabled once the active histogram has been refined and no job is running", () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    renderTab({ viewModel: makeViewModelWithMem([site], null, true) });
    expect(screen.getByRole("button", { name: "RUN MEM" })).not.toBeDisabled();
  });

  it("posts map_type=Fobs by default, polls, and refreshes the heatmap from the refetched viewmodel on done", async () => {
    vi.useFakeTimers();
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    const refetched = makeViewModelWithMem(
      [site],
      { map: makeMemMap({ vmin: -0.5, vmax: 3.2, unit: "e·Å⁻³" }), peaks: [makeMemPeak()], note: "" },
      true,
    );
    const fetchMock = installMemFetchMock({
      statuses: [
        { status: "running", elapsed_s: 1, last_event: null, error: null, kind: "mem" },
        { status: "done", elapsed_s: 5, last_event: "mem finished", error: null, kind: "mem" },
      ],
      refetchedViewModel: refetched,
    });
    renderTab({ viewModel: makeViewModelWithMem([site], null, true) });

    fireEvent.click(screen.getByRole("button", { name: "RUN MEM" }));
    await flushMicrotasksMem();

    const startCall = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/mem") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(startCall).toBeDefined();
    expect(JSON.parse(String((startCall![1] as RequestInit).body))).toEqual({ map_type: "Fobs" });
    expect(screen.getByRole("button", { name: "running…" })).toBeDisabled();

    await advanceTimersMem(2000); // still running
    await advanceTimersMem(2000); // done

    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/viewmodel"))).toBe(true);
    expect(document.querySelectorAll(".heat-map__svg rect").length).toBe(4);
    expect(screen.getByText(/-0\.50 – 3\.20 e·Å⁻³/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RUN MEM" })).not.toBeDisabled();
  });

  it("posts the selected map_type (delt-F)", async () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    const fetchMock = installMemFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    const user = userEvent.setup();
    renderTab({ viewModel: makeViewModelWithMem([site], null, true) });

    await user.selectOptions(screen.getByLabelText("map"), "delt-F");
    await user.click(screen.getByRole("button", { name: "RUN MEM" }));
    await flushMicrotasksMem();

    const call = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/mem") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ map_type: "delt-F" });
  });

  it("409 (job slot busy) shows a non-fatal inline message, not a crash", async () => {
    const site = makeSite({ id: "s1", label: "K1", lock: {} });
    installMemFetchMock({
      memRejects: { status: 409, body: { error: "a job is already running", error_type: "ConflictError" } },
    });
    const user = userEvent.setup();
    renderTab({ viewModel: makeViewModelWithMem([site], null, true) });

    await user.click(screen.getByRole("button", { name: "RUN MEM" }));
    await flushMicrotasksMem();

    expect(screen.getByText("a job is already running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RUN MEM" })).not.toBeDisabled();
  });
});

describe("StructureTab colocated strings — EN/JA key set", () => {
  it("every local key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(STRUCT_LOCAL_STRINGS)) {
      if (!pair.en?.trim()) missing.push(`${key}.en`);
      if (!pair.ja?.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("has the same key set on both sides (object literal invariant, guards accidental split)", () => {
    const keys = Object.keys(STRUCT_LOCAL_STRINGS);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.length).toBeGreaterThan(0);
  });
});
