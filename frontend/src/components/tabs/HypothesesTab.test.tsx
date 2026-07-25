import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
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
