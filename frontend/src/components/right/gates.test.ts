import { describe, expect, it } from "vitest";
import type { Site, StageRow, ViewModel } from "../../api/types";
import { initialWorkbenchState } from "../../state/reducer";
import type { WorkbenchState } from "../../state/types";
import {
  computeStagesOn,
  formatBic,
  formatTokens,
  formatWallTime,
  isStageGateOpen,
  reviewSeverityChipVariant,
  reviewSeverityLabelKey,
} from "./gates";

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
    note: "",
    lock: {},
    rel: {},
    ...overrides,
  };
}

function stateWith(overrides: Partial<WorkbenchState>): WorkbenchState {
  return { ...initialWorkbenchState, ...overrides };
}

describe("isStageGateOpen", () => {
  it("is always open for gate = null", () => {
    expect(isStageGateOpen(null, "sxrd", stateWith({ paramRel: {} }))).toBe(true);
  });

  it("is closed when no paramRel key in the gate group is released", () => {
    const state = stateWith({ paramRel: {} });
    expect(isStageGateOpen("bkg", "sxrd", state)).toBe(false);
  });

  it("opens once one paramRel key in the gate group is released", () => {
    const state = stateWith({ paramRel: { "sxrd.bkg.1": true } });
    expect(isStageGateOpen("bkg", "sxrd", state)).toBe(true);
  });

  it("ignores a released key belonging to a different gate group", () => {
    const state = stateWith({ paramRel: { "sxrd.profile.1": true } });
    expect(isStageGateOpen("bkg", "sxrd", state)).toBe(false);
  });

  it("ignores a released key belonging to a different histogram", () => {
    const state = stateWith({ paramRel: { "nd.bkg.1": true } });
    expect(isStageGateOpen("bkg", "sxrd", state)).toBe(false);
  });

  it("treats a false value as not released", () => {
    const state = stateWith({ paramRel: { "sxrd.bkg.1": false } });
    expect(isStageGateOpen("bkg", "sxrd", state)).toBe(false);
  });

  describe("gate = occ (STRUCTURE per-atom occupancy release)", () => {
    it("is closed when no site has occ released", () => {
      const state = stateWith({
        viewModel: {
          structure: { sites: [makeSite({ rel: {} })], constraints: [], mem_peaks: [] },
        } as unknown as ViewModel,
      });
      expect(isStageGateOpen("occ", "sxrd", state)).toBe(false);
    });

    it("opens once a site has occ released", () => {
      const state = stateWith({
        viewModel: {
          structure: { sites: [makeSite({ rel: { occ: true } })], constraints: [], mem_peaks: [] },
        } as unknown as ViewModel,
      });
      expect(isStageGateOpen("occ", "sxrd", state)).toBe(true);
    });

    it("reads the working (edited) site list over the server seed when present", () => {
      const state = stateWith({
        sites: [makeSite({ rel: { occ: true } })],
        viewModel: {
          structure: { sites: [makeSite({ rel: {} })], constraints: [], mem_peaks: [] },
        } as unknown as ViewModel,
      });
      expect(isStageGateOpen("occ", "sxrd", state)).toBe(true);
    });
  });
});

function makeStage(overrides: Partial<StageRow> = {}): StageRow {
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

describe("computeStagesOn (A1 — POST /api/refine stages_on payload)", () => {
  it("sends true for an ungated stage that is toggled on", () => {
    const state = stateWith({ stageOn: { 1: true }, paramRel: {} });
    const stages = [makeStage({ nn: "01", gate: null })];
    expect(computeStagesOn(stages, state)).toEqual({ "01": true });
  });

  it("sends false for an ungated stage that is toggled off", () => {
    const state = stateWith({ stageOn: { 1: false }, paramRel: {} });
    const stages = [makeStage({ nn: "01", gate: null })];
    expect(computeStagesOn(stages, state)).toEqual({ "01": false });
  });

  // Regression/mutation guard: a stage toggled on client-side (state.stageOn
  // true) whose PARAMETERS gate is still closed must NOT be sent as true —
  // this is the whole point of A1 (the UI's gating reaching the real run).
  // Verified by mutation: replacing the `gated ? false : …` branch with the
  // raw `!!state.stageOn[...]` value makes this test fail (the naive
  // implementation forwards the stale "on" toggle straight through).
  it("forces a gated stage to false even when state.stageOn says it is on", () => {
    const state = stateWith({ stageOn: { 1: true }, paramRel: {} }); // nothing released in PARAMETERS
    const stages = [makeStage({ nn: "01", gate: "bkg" })];
    expect(computeStagesOn(stages, state)).toEqual({ "01": false });
  });

  it("sends true for a gated stage once its gate opens", () => {
    const state = stateWith({ stageOn: { 1: true }, paramRel: { "sxrd.bkg.1": true } });
    const stages = [makeStage({ nn: "01", gate: "bkg" })];
    expect(computeStagesOn(stages, state)).toEqual({ "01": true });
  });

  it("computes each stage independently across a mixed set", () => {
    const state = stateWith({
      stageOn: { 1: true, 2: true, 7: true },
      paramRel: { "sxrd.bkg.1": true },
      viewModel: {
        structure: { sites: [], constraints: [], mem_peaks: [] },
      } as unknown as ViewModel,
    });
    const stages = [
      makeStage({ nn: "01", gate: "bkg" }), // open — released in PARAMETERS
      makeStage({ nn: "02", gate: null }), // ungated, on
      makeStage({ nn: "07", gate: "occ" }), // gated — no site has occ released
    ];
    expect(computeStagesOn(stages, state)).toEqual({ "01": true, "02": true, "07": false });
  });
});

describe("reviewSeverityChipVariant / reviewSeverityLabelKey", () => {
  it("maps close/unknown to the inverted (attention) chip", () => {
    expect(reviewSeverityChipVariant("close")).toBe("inverted");
    expect(reviewSeverityChipVariant("unknown")).toBe("inverted");
  });
  it("maps guard to neutral and echem to accent", () => {
    expect(reviewSeverityChipVariant("guard")).toBe("neutral");
    expect(reviewSeverityChipVariant("echem")).toBe("accent");
  });
  it("returns a distinct RIGHT_STRINGS key per severity", () => {
    const keys = new Set(
      (["close", "unknown", "guard", "echem"] as const).map((s) => reviewSeverityLabelKey(s)),
    );
    expect(keys.size).toBe(4);
  });
});

describe("formatTokens", () => {
  it("formats millions with 2 decimals", () => {
    expect(formatTokens(1_240_000)).toBe("1.24 M");
  });
  it("formats thousands with 1 decimal", () => {
    expect(formatTokens(18_400)).toBe("18.4 k");
  });
  it("formats small counts verbatim", () => {
    expect(formatTokens(512)).toBe("512");
  });
});

describe("formatWallTime", () => {
  it("matches the seeded shell fixture (1084 s → 18 m 04 s)", () => {
    expect(formatWallTime(1084)).toBe("18 m 04 s");
  });
  it("zero-pads single-digit seconds", () => {
    expect(formatWallTime(65)).toBe("1 m 05 s");
  });
  it("handles zero", () => {
    expect(formatWallTime(0)).toBe("0 m 00 s");
  });
});

describe("formatBic", () => {
  it("space-groups thousands", () => {
    expect(formatBic(41208)).toBe("41 208");
  });
  it("leaves small numbers unchanged", () => {
    expect(formatBic(42)).toBe("42");
  });
});

describe("out-of-vocabulary severity fallback (api-contract.md §語彙)", () => {
  // Regression: the demo backend once sent severity="warn" (not in the
  // close/unknown/guard/echem vocabulary) and the whole app unmounted.
  // The selectors must be total functions over arbitrary strings.
  it("falls back to the neutral chip variant", () => {
    expect(reviewSeverityChipVariant("warn")).toBe("neutral");
    expect(reviewSeverityChipVariant("")).toBe("neutral");
  });

  it("returns null for the label key so callers render the raw code", () => {
    expect(reviewSeverityLabelKey("warn")).toBeNull();
    expect(reviewSeverityLabelKey("anything-else")).toBeNull();
  });
});
