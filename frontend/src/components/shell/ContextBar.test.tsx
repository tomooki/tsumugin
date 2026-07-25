import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ProjectFrameRow, ShellState, ViewModel } from "../../api/types";
import { I18nProvider, type Lang } from "../../i18n";
import { StoreProvider } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { ContextBar } from "./ContextBar";

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: { name: "K2Mn[Fe(CN)6] operando", dataset: "SR-XRD · 63 frames", frame: "fr091", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 3, verified: true },
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36, gsas_available: true },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    ...overrides,
  };
}

function frame(overrides: Partial<ProjectFrameRow> = {}): ProjectFrameRow {
  return { id: "fr0", label: "fr0", axis_value: 0, data_path: "data/fr0.xye", ...overrides };
}

function emptyViewModel(overrides: Partial<ViewModel> = {}): ViewModel {
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

function renderBar(
  initialState: Partial<WorkbenchState> = {},
  { lang = "en" as Lang }: { lang?: Lang } = {},
): ReturnType<typeof render> {
  return render(
    <StoreProvider initialState={{ shell: makeShell(), viewModel: emptyViewModel(), ...initialState }}>
      <I18nProvider lang={lang}>
        <ContextBar />
      </I18nProvider>
    </StoreProvider>,
  );
}

describe("ContextBar — static frame chip (no frame column configured)", () => {
  it("shows shell.project.frame when viewModel.project.frames is absent", () => {
    renderBar();
    expect(screen.getByText("fr091")).toBeInTheDocument();
    expect(screen.queryByLabelText("next frame")).not.toBeInTheDocument();
  });
});

describe("ContextBar — frame k / N nav (V2b B2/B3)", () => {
  function withFrames(n: number, viewModelOverrides: Partial<ViewModel> = {}) {
    const frames = Array.from({ length: n }, (_, i) => frame({ id: `fr${i}`, label: `fr${i}`, axis_value: i }));
    return {
      viewModel: emptyViewModel({ project: { histograms: [], phases: [], settings: { two_theta_limits: null, background_coeffs: null, max_cyc: null }, frames }, ...viewModelOverrides }),
    };
  }

  it("renders fr 1 / N at the initial cursor and disables the prev button", () => {
    renderBar(withFrames(4));
    expect(screen.getByText("fr 1 / 4")).toBeInTheDocument();
    expect(screen.getByLabelText("previous frame")).toBeDisabled();
    expect(screen.getByLabelText("next frame")).not.toBeDisabled();
  });

  it("advances the cursor on next and disables next at the last frame", async () => {
    const user = userEvent.setup();
    renderBar(withFrames(3));

    await user.click(screen.getByLabelText("next frame"));
    expect(screen.getByText("fr 2 / 3")).toBeInTheDocument();

    await user.click(screen.getByLabelText("next frame"));
    expect(screen.getByText("fr 3 / 3")).toBeInTheDocument();
    expect(screen.getByLabelText("next frame")).toBeDisabled();
  });

  it("goes back on prev and disables prev at the first frame", async () => {
    const user = userEvent.setup();
    renderBar({ ...withFrames(3), frameIndex: 2 });

    expect(screen.getByText("fr 3 / 3")).toBeInTheDocument();
    await user.click(screen.getByLabelText("previous frame"));
    expect(screen.getByText("fr 2 / 3")).toBeInTheDocument();
    await user.click(screen.getByLabelText("previous frame"));
    expect(screen.getByText("fr 1 / 3")).toBeInTheDocument();
    expect(screen.getByLabelText("previous frame")).toBeDisabled();
  });

  it("clamps a stale frameIndex beyond the current frame count", () => {
    renderBar({ ...withFrames(2), frameIndex: 99 });
    expect(screen.getByText("fr 2 / 2")).toBeInTheDocument();
  });

  it("translates the prev/next labels to Japanese", () => {
    renderBar(withFrames(2), { lang: "ja" });
    expect(screen.getByLabelText("前のフレーム")).toBeInTheDocument();
    expect(screen.getByLabelText("次のフレーム")).toBeInTheDocument();
  });
});
