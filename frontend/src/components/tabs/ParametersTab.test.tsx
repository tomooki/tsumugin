import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ParametersViewModel, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import { ParametersTab } from "./ParametersTab";

function makeParameters(): ParametersViewModel {
  return {
    sxrd: {
      released_count: 2,
      cards: [
        {
          id: "radiation",
          title: "RADIATION / WAVELENGTH",
          note: "monochromatic · from instprm",
          dropdown: {
            label: "source",
            value: "synchrotron X-ray",
            options: ["synchrotron X-ray", "lab Cu Kα"],
          },
          rows: [
            { field: "wavelength λ / Å", value: "0.799580", esd: "±0.000004", released: false, locked: false },
          ],
          footer: "λ/cell is near-singular — keep λ fixed.",
        },
        {
          id: "sample",
          title: "SAMPLE & GEOMETRY",
          note: "scale, displacement, absorption, texture",
          dropdown: null,
          rows: [{ field: "scale", value: "1.204", esd: "±0.003", released: true, locked: false }],
          footer: "Absorption comes from CellConfig layers.",
        },
        {
          id: "background",
          title: "BACKGROUND",
          note: "24 terms · showing 1–8",
          dropdown: { label: "function", value: "chebyschev", options: ["chebyschev", "cosine"] },
          rows: [{ field: "bkg 1", value: "120.4", esd: "±1.2", released: true, locked: false }],
          footer: "",
        },
        {
          id: "profile",
          title: "PROFILE",
          note: "instprm · Kα1 monochromatic",
          dropdown: null,
          rows: [{ field: "U", value: "0.012", esd: "—", released: false, locked: false }],
          footer: "Lorentzian X, Y and Zero are released separately.",
        },
        {
          id: "micro",
          title: "SIZE / MICROSTRAIN",
          note: "per phase · isotropic model",
          dropdown: null,
          rows: [{ field: "size", value: "1200", esd: "—", released: false, locked: true }],
          footer: "size / microstrain reverted at stage 08 (cell collapse).",
        },
      ],
    },
    nd: {
      released_count: 0,
      cards: [
        {
          id: "radiation",
          title: "RADIATION / WAVELENGTH",
          note: "TOF · λ set by difC / flight path",
          dropdown: { label: "source", value: "neutron TOF", options: ["neutron TOF", "neutron CW"] },
          rows: [{ field: "flight path / m", value: "40.020", esd: "—", released: false, locked: false }],
          footer: "For TOF there is no single λ — calibrate difC instead.",
        },
        {
          id: "sample",
          title: "SAMPLE & GEOMETRY",
          note: "scale, displacement, absorption, texture",
          dropdown: null,
          rows: [{ field: "scale", value: "0.881", esd: "±0.004", released: false, locked: false }],
          footer: "",
        },
        {
          id: "background",
          title: "BACKGROUND",
          note: "18 terms",
          dropdown: null,
          rows: [{ field: "bkg 1", value: "40.1", esd: "±0.8", released: false, locked: false }],
          footer: "",
        },
        {
          id: "profile",
          title: "PROFILE",
          note: "difC / difA from .zDiffractometer",
          dropdown: null,
          rows: [{ field: "difC", value: "3200.4", esd: "—", released: false, locked: false }],
          footer: "TOF profile is released only in a dedicated calibration stage.",
        },
        {
          id: "micro",
          title: "SIZE / MICROSTRAIN",
          note: "per phase · isotropic model",
          dropdown: null,
          rows: [{ field: "size", value: "800", esd: "—", released: false, locked: true }],
          footer: "",
        },
      ],
    },
    nd2: { released_count: 0, cards: [] },
  };
}

function makeViewModel(): ViewModel {
  return {
    datasets: [],
    phases: [],
    channels: [],
    snapshots: [],
    fit: {
      metrics: [],
      histograms: [
        { id: "sxrd", label: "SR-XRD λ0.79958", active: true },
        { id: "nd", label: "ND TOF bank 1", active: false },
        { id: "nd2", label: "ND TOF bank 3", active: false },
      ],
      limits_note: "",
      phase_ticks: [],
      two_theta: { min: 4, max: 38 },
      history: [],
      validity: [],
    },
    parameters: makeParameters(),
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

function renderParametersTab() {
  return render(
    <StoreProvider initialState={{ viewModel: makeViewModel() }}>
      <I18nProvider lang="en">
        <ParametersTab />
      </I18nProvider>
    </StoreProvider>,
  );
}

describe("ParametersTab — cards for the active histogram", () => {
  it("renders every card title for the default (sxrd) histogram", () => {
    renderParametersTab();
    expect(screen.getByText("RADIATION / WAVELENGTH")).toBeInTheDocument();
    expect(screen.getByText("SAMPLE & GEOMETRY")).toBeInTheDocument();
    expect(screen.getByText("BACKGROUND")).toBeInTheDocument();
    expect(screen.getByText("PROFILE")).toBeInTheDocument();
    expect(screen.getByText("SIZE / MICROSTRAIN")).toBeInTheDocument();
  });

  it("spans the last card (SIZE / MICROSTRAIN) across both grid columns", () => {
    renderParametersTab();
    const micro = screen.getByText("SIZE / MICROSTRAIN").closest(".param-card");
    expect(micro?.className).toContain("param-card--span2");
    const radiation = screen.getByText("RADIATION / WAVELENGTH").closest(".param-card");
    expect(radiation?.className).not.toContain("param-card--span2");
  });
});

describe("ParametersTab — released count (live, overlay + viewModel baseline)", () => {
  it("starts at the sum of released rows across all cards (2 here)", () => {
    renderParametersTab();
    expect(screen.getByText("released in this histogram: 2")).toBeInTheDocument();
  });

  it("increments when an unreleased checkbox is checked", async () => {
    const user = userEvent.setup();
    renderParametersTab();
    const wavelengthRow = screen.getByText("wavelength λ / Å").closest("tr");
    const checkbox = within(wavelengthRow as HTMLElement).getByRole("checkbox");
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    expect(screen.getByText("released in this histogram: 3")).toBeInTheDocument();
  });

  it("decrements when a released checkbox is unchecked", async () => {
    const user = userEvent.setup();
    renderParametersTab();
    const scaleRow = screen.getByText("scale").closest("tr");
    expect(scaleRow).not.toBeNull();
    const checkbox = within(scaleRow as HTMLElement).getByRole("checkbox");
    expect(checkbox).toBeChecked();
    await user.click(checkbox);
    expect(screen.getByText("released in this histogram: 1")).toBeInTheDocument();
  });

  it("RELEASE ALL releases every unlocked row in that card and updates the live count", async () => {
    const user = userEvent.setup();
    renderParametersTab();
    const radiationCard = screen.getByText("RADIATION / WAVELENGTH").closest(".param-card") as HTMLElement;
    await user.click(within(radiationCard).getByText("RELEASE ALL"));
    expect(screen.getByText("released in this histogram: 3")).toBeInTheDocument();
    const wavelengthRow = screen.getByText("wavelength λ / Å").closest("tr");
    expect(within(wavelengthRow as HTMLElement).getByRole("checkbox")).toBeChecked();
  });

  it("FIX ALL fixes every unlocked row in that card and updates the live count", async () => {
    const user = userEvent.setup();
    renderParametersTab();
    const sampleCard = screen.getByText("SAMPLE & GEOMETRY").closest(".param-card") as HTMLElement;
    await user.click(within(sampleCard).getByText("FIX ALL"));
    expect(screen.getByText("released in this histogram: 1")).toBeInTheDocument();
  });
});

describe("ParametersTab — locked rows", () => {
  it("disables the checkbox and value input for a locked row", () => {
    renderParametersTab();
    const sizeRow = screen.getByText("size").closest("tr");
    expect(sizeRow).not.toBeNull();
    const row = within(sizeRow as HTMLElement);
    expect(row.getByRole("checkbox")).toBeDisabled();
    expect(row.getByRole("textbox")).toBeDisabled();
  });
});

describe("ParametersTab — histogram switch (shared state.hist)", () => {
  it("swaps every card's field set when the histogram chip changes", async () => {
    const user = userEvent.setup();
    renderParametersTab();
    expect(screen.getByText("wavelength λ / Å")).toBeInTheDocument();
    expect(screen.queryByText("difC")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ND TOF bank 1" }));

    expect(screen.queryByText("wavelength λ / Å")).not.toBeInTheDocument();
    expect(screen.getByText("difC")).toBeInTheDocument();
    expect(screen.getByText("released in this histogram: 0")).toBeInTheDocument();
  });
});
