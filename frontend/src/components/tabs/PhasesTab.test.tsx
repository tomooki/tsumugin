import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PhaseRow, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { PhasesTab } from "./PhasesTab";

function makePhase(overrides: Partial<PhaseRow> = {}): PhaseRow {
  return {
    id: "p1",
    name: "alpha",
    swatch: "accent",
    space_group: "Pna2₁",
    mp_id: "",
    wt_frac: "―",
    structure_path: "C:/proj/data/alpha_CaTeO3_H2O.cif",
    refine_cell: true,
    temperature: null,
    cell: null,
    stages: ["02 cell+displacement", "03 profile+size_strain"],
    ...overrides,
  };
}

function makeViewModel(phases: PhaseRow[]): ViewModel {
  return {
    datasets: [],
    phases,
    channels: [],
    snapshots: [],
    fit: {
      metrics: [], histograms: [], limits_note: "", phase_ticks: [],
      two_theta: { min: 0, max: 0 }, history: [], validity: [],
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

function renderTab(phases: PhaseRow[], stateOverrides: Partial<WorkbenchState> = {}) {
  return render(
    <StoreProvider initialState={{ viewModel: makeViewModel(phases), ...stateOverrides }}>
      <I18nProvider lang="en">
        <PhasesTab />
      </I18nProvider>
    </StoreProvider>,
  );
}

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

function shellResponse() {
  return {
    project: { name: "p", dataset: "d", frame: "f", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 3, verified: true },
    status: { backend_build: "b", seed: 0, mcp_tools: 36, gsas_available: true },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
  };
}

describe("PhasesTab — real phase rows", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists each phase with its space group and structure file", () => {
    renderTab([
      makePhase(),
      makePhase({ id: "p2", name: "delta", space_group: "Pbca", structure_path: "C:/proj/data/delta.cif" }),
    ]);
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("Pna2₁")).toBeInTheDocument();
    expect(screen.getByText("delta")).toBeInTheDocument();
    // フルパスでなくファイル名 (行が横に伸びない)
    expect(screen.getByText("alpha_CaTeO3_H2O.cif")).toBeInTheDocument();
  });

  it("shows an empty state instead of an empty table when the model has no phases", () => {
    renderTab([]);
    expect(screen.getByText(/no phases in the model/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says the cell is not refined yet rather than inventing numbers", () => {
    renderTab([makePhase({ cell: null })]);
    expect(screen.getByText("not refined yet")).toBeInTheDocument();
  });

  it("renders the refined cell once one exists", () => {
    renderTab([
      makePhase({
        cell: { a: "9.3721(3)", b: "9.3721(3)", c: "6.8861(4)", alpha: "90", beta: "90", gamma: "120" },
      }),
    ]);
    expect(screen.getByText(/9\.3721\(3\)/)).toBeInTheDocument();
    expect(screen.getByText(/6\.8861\(4\)/)).toBeInTheDocument();
  });

  it("lists the recipe stages that touch the phase", () => {
    renderTab([makePhase()]);
    expect(screen.getByText(/02 cell\+displacement/)).toBeInTheDocument();
    expect(screen.getByText(/03 profile\+size_strain/)).toBeInTheDocument();
  });
});

describe("PhasesTab — REFINE CELL (the one per-phase switch the engine reads)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts the new value to the phase settings endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/settings")) return jsonResponse(shellResponse());
      if (url.endsWith("/api/viewmodel")) return jsonResponse(makeViewModel([makePhase({ refine_cell: false })]));
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderTab([makePhase()]);

    await user.click(screen.getByRole("checkbox", { name: "refine cell of alpha" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/settings"));
      expect(call).toBeDefined();
      expect(String(call![0])).toBe("/api/project/phases/alpha/settings");
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ refine_cell: false });
    });
  });

  it("reflects the server value, not local optimism", () => {
    renderTab([makePhase({ refine_cell: false })]);
    expect(screen.getByRole("checkbox", { name: "refine cell of alpha" })).not.toBeChecked();
  });

  it("is disabled while a job is running (spec edits are rejected then)", () => {
    renderTab([makePhase()], {
      refine: { status: "running", elapsed_s: 3, last_event: null, error: null },
    });
    expect(screen.getByRole("checkbox", { name: "refine cell of alpha" })).toBeDisabled();
  });

  it("surfaces a failed update inline instead of silently reverting", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/settings")) {
        return jsonResponse({ error: "a job is already running", error_type: "ConflictError" }, false, 409);
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderTab([makePhase()]);

    await user.click(screen.getByRole("checkbox", { name: "refine cell of alpha" }));

    await waitFor(() => expect(screen.getByText(/failed to update alpha/)).toBeInTheDocument());
  });
});

describe("PhasesTab — honesty about what is NOT per-phase", () => {
  it("explains that only the lattice is per-phase today", () => {
    // 恒久ガード: size_strain 等に相単位のチェックボックスを生やすなら、engine 側に相単位の
    // スイッチを足してからにすること。この注記が消えたら、その前提が崩れた合図。
    renderTab([makePhase()]);
    expect(screen.getByText(/Only the lattice can be released per phase today/)).toBeInTheDocument();
  });

  it("renders no editable control for the flags the engine applies to every phase", () => {
    renderTab([makePhase({ stages: ["03 profile+size_strain"] })]);
    const checkboxes = screen.getAllByRole("checkbox");
    // REFINE CELL 以外のチェックボックスが無いこと (相単位に効かないものを触らせない)
    expect(checkboxes).toHaveLength(1);
    expect(checkboxes[0]).toHaveAccessibleName("refine cell of alpha");
  });
});

describe("PhasesTab — REMOVE", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts to the remove endpoint for that phase", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/remove")) return jsonResponse(shellResponse());
      if (url.endsWith("/api/viewmodel")) return jsonResponse(makeViewModel([]));
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderTab([makePhase()]);

    const row = screen.getByText("alpha").closest("tr")!;
    await user.click(within(row).getByRole("button", { name: /REMOVE/ }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/remove"));
      expect(String(call![0])).toBe("/api/project/phases/alpha/remove");
    });
  });
});
