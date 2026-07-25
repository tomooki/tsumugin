import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HypothesesViewModel, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { HypothesesTab } from "./HypothesesTab";

function makeHypotheses(): HypothesesViewModel {
  return {
    rows: [
      {
        rank: 1,
        id: "H-014",
        phases: "cubic + tetra + mono",
        p: 0.48,
        rwp: 6.71,
        gof: 1.29,
        bic: 39402,
        close: true,
        status: "candidate",
        selected: true,
      },
      {
        rank: 2,
        id: "H-011",
        phases: "cubic + tetra",
        p: 0.39,
        rwp: 8.04,
        gof: 1.42,
        bic: 41208,
        close: true,
        status: "candidate",
        selected: false,
      },
      {
        rank: 5,
        id: "H-013",
        phases: "cubic + tetra + Ca3TeO6",
        p: 0.02,
        rwp: 6.62,
        gof: 1.27,
        bic: 41990,
        close: false,
        status: "demoted · chem",
        selected: false,
      },
    ],
    diff: {
      vs: "H-011",
      rows: [
        { field: "phases", a: "3", b: "2", changed: true },
        { field: "cubic a / Å", a: "10.104(2)", b: "10.106(2)", changed: false },
      ],
    },
    evidence: [
      ["evidence backend", "bic → nested"],
      ["ΔlogZ", "1.2 < 2.5 threshold"],
    ],
  };
}

function renderTab(overrides: Partial<WorkbenchState> = {}) {
  const initialState: Partial<WorkbenchState> = {
    viewModel: { hypotheses: makeHypotheses() } as unknown as ViewModel,
    ...overrides,
  };
  return render(
    <StoreProvider initialState={initialState}>
      <I18nProvider lang="en">
        <HypothesesTab />
      </I18nProvider>
    </StoreProvider>,
  );
}

/** The ranking table (as opposed to the DIFF card table, which repeats the
 * selected id and comparison id as column headers). */
function rankingRow(id: string): HTMLElement {
  const table = document.querySelector(".hyp-table") as HTMLElement;
  return within(table).getByText(id).closest("tr") as HTMLElement;
}

describe("HypothesesTab — ranking table selection + DIFF re-pointing", () => {
  it("marks the initially-selected row and points DIFF at it", () => {
    renderTab();
    expect(rankingRow("H-014").className).toContain("hyp-table__row--selected");
    expect(screen.getByText("DIFF · H-014 vs H-011")).toBeInTheDocument();
  });

  it("clicking a row selects it and re-points the DIFF card to that id", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(rankingRow("H-013"));

    expect(screen.getByText("DIFF · H-013 vs H-011")).toBeInTheDocument();
    expect(rankingRow("H-013").className).toContain("hyp-table__row--selected");
    // the previously-selected row must lose the highlight
    expect(rankingRow("H-014").className).not.toContain("hyp-table__row--selected");
  });
});

describe("HypothesesTab — demoted status + close-competitor dot", () => {
  it("renders the raw 'demoted · chem' status text for a demoted row", () => {
    renderTab();
    expect(screen.getByText("demoted · chem")).toBeInTheDocument();
  });

  it("shows the close-competitor dot only for rows flagged close", () => {
    renderTab();
    expect(rankingRow("H-014").textContent).toContain("●");
    expect(rankingRow("H-013").textContent).not.toContain("●");
  });
});

describe("HypothesesTab — basin scatter", () => {
  it("falls back to the empty-state placeholder when hypotheses.basin is absent", () => {
    const { container } = renderTab();
    expect(container.querySelector(".placeholder-plot__frame")).not.toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("draws real basin points as svg circles when hypotheses.basin is present", () => {
    const { container } = renderTab({
      viewModel: {
        hypotheses: {
          ...makeHypotheses(),
          basin: {
            points: [
              { x: 9.372, y: 6.71, label: "start 1" },
              { x: 9.375, y: 6.9, label: "start 2" },
            ],
          },
        },
      } as unknown as ViewModel,
    });

    expect(container.querySelector(".placeholder-plot__frame")).toBeNull();
    expect(container.querySelectorAll("svg circle.scatter-chart__point").length).toBe(2);
    expect(screen.getByText("start 1")).toBeInTheDocument();
  });
});

// — A5: MULTISTART job (api-contract.md §解析ループ) —

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

function installMultistartFetchMock(opts: {
  multistartRejects?: { status: number; body: unknown };
  statuses?: unknown[];
  refetchedHypotheses?: HypothesesViewModel;
}) {
  let statusCallIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/multistart") && method === "POST") {
      if (opts.multistartRejects) {
        return {
          ok: false,
          status: opts.multistartRejects.status,
          statusText: "Conflict",
          json: async () => opts.multistartRejects!.body,
        } as Response;
      }
      return jsonResponse({ status: "started" });
    }
    if (url.endsWith("/api/multistart/status") && method === "GET") {
      const statuses = opts.statuses ?? [{ status: "running", elapsed_s: 1, last_event: null, error: null }];
      const body = statuses[Math.min(statusCallIndex, statuses.length - 1)];
      statusCallIndex += 1;
      return jsonResponse(body);
    }
    if (url.endsWith("/api/viewmodel") && method === "GET") {
      return jsonResponse({
        datasets: [],
        phases: [],
        channels: [],
        snapshots: [],
        fit: { metrics: [], histograms: [], limits_note: "", phase_ticks: [], two_theta: { min: 0, max: 0 }, history: [], validity: [] },
        parameters: {},
        hypotheses: opts.refetchedHypotheses ?? makeHypotheses(),
        phase_id: { candidates: [], unexplained: [], completeness: { is_complete: true, notes: [], flagged_frames: "" } },
        sequence: { charts: [], anchors: [], note: "", segments: [] },
        structure: { sites: [], constraints: [], mem_peaks: [] },
        stages: [],
        review: [],
        transcript: [],
      } satisfies ViewModel);
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

describe("HypothesesTab — MULTISTART job (A5)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("posts n_starts=3 by default, polls, and draws real basin points from the refetched viewmodel on done", async () => {
    vi.useFakeTimers();
    const refetched: HypothesesViewModel = {
      ...makeHypotheses(),
      basin: {
        points: [
          { x: 9.372, y: 6.71, label: "start 1" },
          { x: 9.375, y: 6.9, label: "start 2" },
          { x: 9.371, y: 6.8, label: "start 3" },
        ],
      },
    };
    const fetchMock = installMultistartFetchMock({
      statuses: [
        { status: "running", elapsed_s: 1, last_event: null, error: null },
        { status: "done", elapsed_s: 5, last_event: "complete", error: null },
      ],
      refetchedHypotheses: refetched,
    });
    const { container } = renderTab();

    fireEvent.click(screen.getByRole("button", { name: "MULTISTART" }));
    await flushMicrotasks();

    const startCall = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/multistart") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(startCall).toBeDefined();
    expect(JSON.parse(String((startCall![1] as RequestInit).body))).toEqual({ n_starts: 3 });
    expect(screen.getByRole("button", { name: "RUNNING …" })).toBeDisabled();

    await advanceTimers(2000); // still running
    await advanceTimers(2000); // done

    expect(container.querySelectorAll("svg circle.scatter-chart__point").length).toBe(3);
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/viewmodel"))).toBe(true);
    expect(screen.getByRole("button", { name: "MULTISTART" })).not.toBeDisabled();
  });

  it("posts a custom n_starts value", async () => {
    const fetchMock = installMultistartFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    const user = userEvent.setup();
    renderTab();

    const input = screen.getByLabelText("n_starts");
    await user.clear(input);
    await user.type(input, "5");
    await user.click(screen.getByRole("button", { name: "MULTISTART" }));

    await flushMicrotasks();
    const call = fetchMock.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/multistart") && (init as RequestInit | undefined)?.method === "POST",
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ n_starts: 5 });
  });

  it("409 (job slot busy) shows a non-fatal inline message, not a crash", async () => {
    installMultistartFetchMock({
      multistartRejects: { status: 409, body: { error: "job running", error_type: "conflict" } },
    });
    const user = userEvent.setup();
    renderTab();

    await user.click(screen.getByRole("button", { name: "MULTISTART" }));

    await flushMicrotasks();
    expect(screen.getByText(/already running \(job slot busy\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MULTISTART" })).not.toBeDisabled();
  });
});

// — V2c レビュー指摘 #4: GSAS-II 不在時の MULTISTART 無効化 —
// Tier1 desktop sidecar excludes GSAS-II (desktop/README.md); this job would otherwise 422
// server-side with GSASUnavailableError. status.shell.status.gsas_available (api/types.ts
// BackendStatus) is dynamic per GET /api/state.
describe("HypothesesTab — MULTISTART disabled while GSAS-II is unavailable", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function shellWithGsas(gsasAvailable: boolean) {
    return {
      project: { name: "p", dataset: "d", frame: "f", echem: null },
      mode: "manual" as const,
      final_selection_mode: "human" as const,
      ledger: { count: 0, verified: true },
      status: { backend_build: "b", seed: 0, mcp_tools: 0, gsas_available: gsasAvailable },
      agent: { tokens: 0, wall_time_s: 0, idle: true },
    };
  }

  it("disables the button and sets an explanatory title when gsas_available is false", () => {
    renderTab({ shell: shellWithGsas(false) });

    const btn = screen.getByRole("button", { name: "MULTISTART" });
    expect(btn).toBeDisabled();
    expect(btn.getAttribute("title")).toBe(
      "GSAS-II is not available in this backend — multistart cannot run",
    );
  });

  it("keeps the button enabled (no title) when gsas_available is true", () => {
    renderTab({ shell: shellWithGsas(true) });

    const btn = screen.getByRole("button", { name: "MULTISTART" });
    expect(btn).not.toBeDisabled();
    expect(btn.getAttribute("title")).toBeNull();
  });

  it("keeps the button enabled before shell/status has loaded (defaults to available)", () => {
    renderTab();

    expect(screen.getByRole("button", { name: "MULTISTART" })).not.toBeDisabled();
  });

  it("does not call postMultistart when clicking the disabled button", async () => {
    const fetchMock = installMultistartFetchMock({
      statuses: [{ status: "idle", elapsed_s: null, last_event: null, error: null }],
    });
    const user = userEvent.setup();
    renderTab({ shell: shellWithGsas(false) });

    await user.click(screen.getByRole("button", { name: "MULTISTART" }));

    expect(
      fetchMock.mock.calls.some(
        ([u, init]) => String(u).endsWith("/api/multistart") && (init as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(false);
  });
});
