import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import type { ViewModel } from "../../api/types";
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
  { lang = "en" as Lang, viewModel }: { lang?: Lang; viewModel?: ViewModel } = {},
) {
  const initialState: Partial<WorkbenchState> = { lang, viewModel: viewModel ?? null };
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
