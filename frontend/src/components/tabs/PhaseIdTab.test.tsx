import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PhaseIdViewModel, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
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

function renderTab(overrides: Partial<PhaseIdViewModel> = {}) {
  const initialState: Partial<WorkbenchState> = {
    viewModel: { phase_id: makePhaseId(overrides) } as unknown as ViewModel,
  };
  return render(
    <StoreProvider initialState={initialState}>
      <I18nProvider lang="en">
        <PhaseIdTab />
      </I18nProvider>
    </StoreProvider>,
  );
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

describe("PhaseIdTab — ADD AS PHASE is display-only in v1", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("clicking ADD AS PHASE is a no-op (no network call, no throw)", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const user = userEvent.setup();
    renderTab();

    const buttons = screen.getAllByRole("button", { name: "ADD AS PHASE" });
    await user.click(buttons[0]);

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
