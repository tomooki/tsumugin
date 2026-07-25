import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReviewItem, StageRow, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { initialWorkbenchState } from "../../state/reducer";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { OperatorConsole } from "./OperatorConsole";

// initialWorkbenchState.stageOn defaults stages 1-5 to "on" (matching the
// handoff demo, where the first five stages are already released). The
// gating tests below need stage 01 to start unreleased so the RELEASE
// button (not REVERT) is on screen — override just that key.
const STAGE_01_UNRELEASED = { ...initialWorkbenchState.stageOn, 1: false };

function makeViewModel(overrides: Partial<ViewModel> = {}): ViewModel {
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

function stage(overrides: Partial<StageRow> = {}): StageRow {
  return {
    nn: "01",
    name: "background",
    flags: "6→24 terms",
    delta_rwp: "−41.2",
    released: false,
    gate: "bkg",
    ...overrides,
  };
}

function reviewItem(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: "rv1",
    severity: "close",
    title: "ΔlogZ 1.2 below threshold",
    ref: "H-014 / H-011",
    detail: "detail text",
    state: "pending",
    ...overrides,
  };
}

function renderConsole(initialState: Partial<WorkbenchState>) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider lang="en">
        <StoreProvider initialState={initialState}>{children}</StoreProvider>
      </I18nProvider>
    );
  }
  return render(<OperatorConsole />, { wrapper: Wrapper });
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/stages/")) {
      const nn = url.split("/api/stages/")[1];
      return jsonResponse({ stage: stage({ nn }) });
    }
    if (url.endsWith("/api/refine")) {
      return jsonResponse({ status: "recorded" });
    }
    if (url.includes("/api/review-queue/")) {
      return jsonResponse({ item: reviewItem() });
    }
    throw new Error(`unhandled fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("OperatorConsole — staged release recipe gating", () => {
  let fetchMock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    fetchMock = installFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the gated sub-line and disables RELEASE when nothing is released in PARAMETERS", async () => {
    renderConsole({
      viewModel: makeViewModel({ stages: [stage({ nn: "01", gate: "bkg" })] }),
      paramRel: {},
      stageOn: STAGE_01_UNRELEASED,
    });

    expect(screen.getByText("gated · nothing released in PARAMETERS")).toBeInTheDocument();
    const releaseBtn = screen.getByRole("button", { name: "RELEASE" });
    expect(releaseBtn).toBeDisabled();
  });

  it("does not call postStage when clicking a disabled/gated RELEASE button", async () => {
    const user = userEvent.setup();
    renderConsole({
      viewModel: makeViewModel({ stages: [stage({ nn: "01", gate: "bkg" })] }),
      paramRel: {},
      stageOn: STAGE_01_UNRELEASED,
    });

    const releaseBtn = screen.getByRole("button", { name: "RELEASE" });
    await user.click(releaseBtn); // disabled — userEvent will not fire onClick
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("opens the gate and enables RELEASE once one PARAMETERS checkbox is on", async () => {
    const user = userEvent.setup();
    renderConsole({
      viewModel: makeViewModel({ stages: [stage({ nn: "01", gate: "bkg" })] }),
      paramRel: { "sxrd.bkg.1": true },
      stageOn: STAGE_01_UNRELEASED,
    });

    expect(screen.queryByText("gated · nothing released in PARAMETERS")).not.toBeInTheDocument();
    expect(screen.getByText("6→24 terms · −41.2")).toBeInTheDocument();

    const releaseBtn = screen.getByRole("button", { name: "RELEASE" });
    expect(releaseBtn).not.toBeDisabled();
    await user.click(releaseBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/stages/01"));
      expect(call).toBeDefined();
    });
    // after the TOGGLE_STAGE dispatch, the row flips to released (REVERT)
    await waitFor(() => expect(screen.getByRole("button", { name: "REVERT" })).toBeInTheDocument());
  });

  it("stage 07 gates on STRUCTURE per-atom occupancy release, not PARAMETERS", async () => {
    renderConsole({
      viewModel: makeViewModel({
        stages: [stage({ nn: "07", name: "occupancies", gate: "occ" })],
        structure: { sites: [], constraints: [], mem_peaks: [] },
      }),
      paramRel: { "sxrd.bkg.1": true }, // irrelevant to occ gating
    });

    expect(screen.getByText("gated · no atom occupancy checked in STRUCTURE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RELEASE" })).toBeDisabled();
  });

  it("stage 07 opens once a site has occ released", async () => {
    renderConsole({
      viewModel: makeViewModel({
        stages: [stage({ nn: "07", name: "occupancies", gate: "occ" })],
        structure: {
          sites: [
            {
              id: "s1",
              label: "K1",
              el: "K",
              x: "0.25",
              y: "0.25",
              z: "0.25",
              occ: "0.71",
              uiso: "0.04",
              note: "",
              lock: {},
              rel: { occ: true },
            },
          ],
          constraints: [],
          mem_peaks: [],
        },
      }),
      paramRel: {},
    });

    expect(screen.queryByText("gated · no atom occupancy checked in STRUCTURE")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "RELEASE" })).not.toBeDisabled();
  });
});

describe("OperatorConsole — review queue", () => {
  let fetchMock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    fetchMock = installFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ACCEPT calls postReviewResolve and swaps the primary button to ACCEPTED ✓", async () => {
    const user = userEvent.setup();
    renderConsole({ viewModel: makeViewModel({ review: [reviewItem()] }) });

    const acceptBtn = screen.getByRole("button", { name: "ACCEPT …" });
    await user.click(acceptBtn);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/review-queue/rv1/resolve"));
      expect(call).toBeDefined();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "ACCEPTED ✓" })).toBeInTheDocument());
  });

  it("SEND BACK calls postReviewResolve and swaps the primary button to SENT BACK", async () => {
    const user = userEvent.setup();
    renderConsole({ viewModel: makeViewModel({ review: [reviewItem()] }) });

    await user.click(screen.getByRole("button", { name: "SEND BACK" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/api/review-queue/rv1/resolve"));
      expect(call).toBeDefined();
      const [, init] = call!;
      expect(JSON.parse(String((init as RequestInit).body))).toEqual({ action: "send_back", note: "" });
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "SENT BACK" })).toBeInTheDocument());
  });
});
