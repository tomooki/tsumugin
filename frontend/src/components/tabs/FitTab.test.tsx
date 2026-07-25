import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import { FitTab } from "./FitTab";

function makeViewModel(overrides: Partial<ViewModel["fit"]> = {}): ViewModel {
  return {
    datasets: [],
    phases: [],
    channels: [],
    snapshots: [],
    fit: {
      metrics: [
        { key: "rwp", label: "Rwp", value: "6.71%", note: "target ≤ 8.0" },
        { key: "gof", label: "GOF", value: "1.29", note: "χ²/dof" },
        { key: "chi2", label: "χ²", value: "3 118", note: "n_obs 2 412" },
        { key: "nparams", label: "n_params", value: "38", note: "released of 96" },
        { key: "delta", label: "Δ vs manual", value: "−9.53", note: "manual ref 16.24%" },
        { key: "basins", label: "basins", value: "1 / 3", note: "global corroborated" },
      ],
      histograms: [
        { id: "sxrd", label: "SR-XRD λ0.79958", active: true },
        { id: "nd", label: "ND TOF bank 1", active: false },
        { id: "nd2", label: "ND TOF bank 3", active: false },
      ],
      limits_note: "two_theta_limits = [4.0, 38.0] · background 24 terms · Kα1 instprm",
      phase_ticks: ["cubic Fm-3m", "tetragonal I4/mmm"],
      two_theta: { min: 4.0, max: 38.0 },
      history: [
        { stage: "01 background (24)", rwp: 29.61, delta_rwp: -18.4, guard: "ok", reverted: false },
        {
          stage: "08 size / mustrain",
          rwp: 18.11,
          delta_rwp: 0.42,
          guard: "REVERTED · cell collapse",
          reverted: true,
        },
      ],
      validity: [
        { check: "occupancy ∈ [0, 1]", status: "pass", detail: "0.71(3)" },
        { check: "coordination Mn", status: "warn", detail: "5.2" },
      ],
      ...overrides,
    },
    parameters: {},
    hypotheses: { rows: [], diff: { vs: "", rows: [] }, evidence: [] },
    phase_id: {
      candidates: [],
      unexplained: [],
      completeness: { is_complete: true, notes: [], flagged_frames: "" },
    },
    sequence: { charts: [], anchors: [], note: "", segments: [] },
    structure: { sites: [], constraints: [], mem_peaks: [] },
    stages: [],
    review: [],
    transcript: [],
  };
}

function renderFitTab(viewModel: ViewModel) {
  return render(
    <StoreProvider initialState={{ viewModel }}>
      <I18nProvider lang="en">
        <FitTab />
      </I18nProvider>
    </StoreProvider>,
  );
}

describe("FitTab — metrics", () => {
  it("shows all six metric cards from viewModel.fit.metrics", () => {
    const { container } = renderFitTab(makeViewModel());
    const metrics = within(container.querySelector(".fit-tab__metrics") as HTMLElement);
    // "Rwp" also appears as a table header below, so scope to the metrics row.
    expect(metrics.getByText("Rwp")).toBeInTheDocument();
    expect(metrics.getByText("6.71%")).toBeInTheDocument();
    expect(metrics.getByText("GOF")).toBeInTheDocument();
    expect(metrics.getByText("1.29")).toBeInTheDocument();
    expect(metrics.getByText("χ²")).toBeInTheDocument();
    expect(metrics.getByText("3 118")).toBeInTheDocument();
    expect(metrics.getByText("n_params")).toBeInTheDocument();
    expect(metrics.getByText("38")).toBeInTheDocument();
    expect(metrics.getByText("Δ vs manual")).toBeInTheDocument();
    expect(metrics.getByText("−9.53")).toBeInTheDocument();
    expect(metrics.getByText("basins")).toBeInTheDocument();
    expect(metrics.getByText("1 / 3")).toBeInTheDocument();
  });
});

describe("FitTab — histogram chips", () => {
  it("marks the active chip and re-points on click (shared state.hist)", async () => {
    const user = userEvent.setup();
    renderFitTab(makeViewModel());

    const sxrdChip = screen.getByRole("button", { name: "SR-XRD λ0.79958" });
    const ndChip = screen.getByRole("button", { name: "ND TOF bank 1" });
    expect(sxrdChip.className).toContain("hist-chips__chip--active");
    expect(ndChip.className).not.toContain("hist-chips__chip--active");

    await user.click(ndChip);

    expect(ndChip.className).toContain("hist-chips__chip--active");
    expect(sxrdChip.className).not.toContain("hist-chips__chip--active");
  });

  it("shows the limits note right-aligned in the chip row", () => {
    renderFitTab(makeViewModel());
    expect(
      screen.getByText("two_theta_limits = [4.0, 38.0] · background 24 terms · Kα1 instprm"),
    ).toBeInTheDocument();
  });
});

describe("FitTab — refinement history", () => {
  it("colors a negative, non-reverted ΔRwp with the accent-800 class", () => {
    renderFitTab(makeViewModel());
    // toFixed emits an ASCII hyphen, not the Unicode minus used in static copy.
    const cell = screen.getByText("-18.40");
    expect(cell.className).toContain("fit-history__delta--negative");
    expect(cell.className).not.toContain("fit-history__delta--reverted");
  });

  it("colors the reverted row's positive ΔRwp with the neutral-900 class, not the negative class", () => {
    renderFitTab(makeViewModel());
    const cell = screen.getByText("+0.42");
    expect(cell.className).toContain("fit-history__delta--reverted");
    expect(cell.className).not.toContain("fit-history__delta--negative");
  });
});

describe("FitTab — physical validity gate", () => {
  it("renders a PASS row with the accent chip variant", () => {
    renderFitTab(makeViewModel());
    const chip = screen.getByText("PASS");
    expect(chip.className).toContain("chip--accent");
  });

  it("renders a WARN row with the inverted chip variant (no extra hue for attention states)", () => {
    renderFitTab(makeViewModel());
    const chip = screen.getByText("WARN");
    expect(chip.className).toContain("chip--inverted");
  });

  it("renders the 'Rwp cannot see a wrong phase set' note", () => {
    renderFitTab(makeViewModel());
    expect(screen.getByText(/Rwp alone cannot see a wrong phase set/)).toBeInTheDocument();
  });
});

describe("FitTab — real fit/residual plot (fit.plot)", () => {
  it("falls back to the dashed placeholder when fit.plot is absent", () => {
    const { container } = renderFitTab(makeViewModel());
    expect(container.querySelector(".placeholder-plot__frame")).not.toBeNull();
    expect(container.querySelector(".fit-tab__plot-col svg")).toBeNull();
    expect(screen.getByText("PLOT PLACEHOLDER — observed vs calculated overlay + peak cursor + 2θ zoom/pan")).toBeInTheDocument();
  });

  it("draws yobs points and an ycalc svg <path> for the active histogram's curve", () => {
    const { container } = renderFitTab(
      makeViewModel({
        histograms: [{ id: "sxrd", label: "SR-XRD λ0.79958", active: true }],
        plot: {
          sxrd: {
            x: [4, 5, 6],
            yobs: [10, 20, 15],
            ycalc: [11, 19, 16],
            ybkg: [2, 2, 2],
            residual: [-1, 1, -1],
            ticks: { "cubic Fm-3m": [4.5, 5.5] },
          },
        },
      }),
    );

    expect(container.querySelectorAll(".fit-tab__plot-col svg circle.line-plot__point").length).toBe(3);
    const ycalcPath = container.querySelector('svg path[data-series-label="Ycalc"]');
    expect(ycalcPath).not.toBeNull();
    expect(ycalcPath!.getAttribute("d")).not.toBe("");
    // residual panel also gets a real curve
    expect(container.querySelector('svg path[data-series-label="Δ"]')).not.toBeNull();
  });

  it("re-points the plot when the histogram chip changes", async () => {
    const user = userEvent.setup();
    const { container } = renderFitTab(
      makeViewModel({
        histograms: [
          { id: "sxrd", label: "SR-XRD λ0.79958", active: true },
          { id: "nd", label: "ND TOF bank 1", active: false },
        ],
        plot: {
          sxrd: {
            x: [4, 5],
            yobs: [10, 20],
            ycalc: [11, 19],
            ybkg: null,
            residual: null,
            ticks: {},
          },
          nd: null,
        },
      }),
    );

    // sxrd is active first — a real curve is drawn.
    expect(container.querySelector('svg path[data-series-label="Ycalc"]')).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "ND TOF bank 1" }));

    // nd's plot entry is null → falls back to the placeholder.
    expect(container.querySelector('svg path[data-series-label="Ycalc"]')).toBeNull();
    expect(container.querySelector(".fit-tab__plot-col .placeholder-plot__frame")).not.toBeNull();
  });
});

describe("FitTab — null delta_rwp (real-run first stage, regression)", () => {
  // A real project run's first stage has delta_rwp=null (no predecessor);
  // null.toFixed(2) used to unmount the entire app after RUN REFINEMENT.
  it("renders an em-dash instead of crashing", () => {
    renderFitTab(
      makeViewModel({
        history: [
          { stage: "01 S0 scale+background", rwp: 48.89, delta_rwp: null, guard: "", reverted: false },
        ],
      }),
    );
    expect(screen.getByText("01 S0 scale+background")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
