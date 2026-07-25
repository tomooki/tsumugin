import { describe, expect, it } from "vitest";
import type { RefineStatus, ShellState, Site, StageRow, ViewModel } from "../api/types";
import { initialWorkbenchState, reducer, siteList } from "./reducer";
import type { WorkbenchState } from "./types";

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: { name: "p", dataset: "d", frame: "f", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 0, verified: true },
    status: { backend_build: "b", seed: 0, mcp_tools: 0 },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    ...overrides,
  };
}

function refineStatus(overrides: Partial<RefineStatus> = {}): RefineStatus {
  return { status: "running", elapsed_s: 1, last_event: null, error: null, ...overrides };
}

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
    lock: { x: true, y: true, z: true },
    rel: {},
    ...overrides,
  };
}

function stateWithSites(sites: Site[]): WorkbenchState {
  return {
    ...initialWorkbenchState,
    viewModel: { structure: { sites, constraints: [], mem_peaks: [] } } as unknown as ViewModel,
  };
}

describe("reducer — tab / hist switching", () => {
  it("SET_TAB switches the active tab", () => {
    const next = reducer(initialWorkbenchState, { type: "SET_TAB", tab: "struct" });
    expect(next.tab).toBe("struct");
    expect(next.hist).toBe(initialWorkbenchState.hist); // unrelated state untouched
  });

  it("SET_HIST switches the active histogram", () => {
    const next = reducer(initialWorkbenchState, { type: "SET_HIST", hist: "nd2" });
    expect(next.hist).toBe("nd2");
  });
});

describe("reducer — paramRel toggle", () => {
  const key = "sxrd.bkg.1";

  it("toggles from the fallback default on first press", () => {
    const next = reducer(initialWorkbenchState, {
      type: "TOGGLE_PARAM_REL",
      key,
      fallback: true,
    });
    expect(next.paramRel[key]).toBe(false);
  });

  it("toggles back on the second press", () => {
    let s = reducer(initialWorkbenchState, { type: "TOGGLE_PARAM_REL", key, fallback: true });
    s = reducer(s, { type: "TOGGLE_PARAM_REL", key, fallback: true });
    expect(s.paramRel[key]).toBe(true);
  });

  it("SET_PARAM_GROUP sets every key in the group", () => {
    const next = reducer(initialWorkbenchState, {
      type: "SET_PARAM_GROUP",
      keys: ["sxrd.bkg.1", "sxrd.bkg.2"],
      value: true,
    });
    expect(next.paramRel["sxrd.bkg.1"]).toBe(true);
    expect(next.paramRel["sxrd.bkg.2"]).toBe(true);
  });
});

describe("reducer — edits increment", () => {
  it("EDIT_SITE increments the pending-edit counter and clears applied", () => {
    const state = { ...stateWithSites([makeSite()]), applied: true };
    const next = reducer(state, { type: "EDIT_SITE", id: "s1", field: "occ", value: "0.800" });
    expect(next.edits).toBe(1);
    expect(next.applied).toBe(false);
    expect(siteList(next)[0].occ).toBe("0.800");
  });

  it("ADD_ATOM increments edits and appends a row", () => {
    const state = stateWithSites([makeSite()]);
    const next = reducer(state, { type: "ADD_ATOM" });
    expect(next.edits).toBe(1);
    expect(siteList(next)).toHaveLength(2);
  });

  it("DELETE_SITE increments edits and removes the row", () => {
    const state = stateWithSites([makeSite(), makeSite({ id: "s2", label: "K2" })]);
    const next = reducer(state, { type: "DELETE_SITE", id: "s2" });
    expect(next.edits).toBe(1);
    expect(siteList(next)).toHaveLength(1);
  });

  it("repeated edits accumulate the counter", () => {
    let state = stateWithSites([makeSite()]);
    state = reducer(state, { type: "EDIT_SITE", id: "s1", field: "x", value: "0.10" });
    state = reducer(state, { type: "EDIT_SITE", id: "s1", field: "y", value: "0.20" });
    expect(state.edits).toBe(2);
  });
});

describe("reducer — DISCARD", () => {
  it("drops unapplied edits only, restoring the applied baseline", () => {
    const applied = [makeSite({ occ: "0.710" })];
    let state: WorkbenchState = { ...stateWithSites(applied), appliedSites: applied };
    state = reducer(state, { type: "EDIT_SITE", id: "s1", field: "occ", value: "0.900" });
    expect(state.edits).toBe(1);
    expect(siteList(state)[0].occ).toBe("0.900");

    const discarded = reducer(state, { type: "DISCARD_EDITS" });
    expect(discarded.edits).toBe(0);
    expect(discarded.sites).toBeNull();
    // falls back to the applied baseline, not the server seed
    expect(siteList(discarded)[0].occ).toBe("0.710");
  });

  it("is a no-op when there are zero pending edits (cannot discard nothing)", () => {
    const state = { ...stateWithSites([makeSite()]), edits: 0 };
    const next = reducer(state, { type: "DISCARD_EDITS" });
    expect(next).toBe(state); // same reference: reducer did not touch anything
  });

  it("never rolls back an already-applied model", () => {
    const applied = [makeSite({ occ: "0.900" })];
    const state: WorkbenchState = {
      ...stateWithSites(applied),
      appliedSites: applied,
      applied: true,
      edits: 0,
    };
    const next = reducer(state, { type: "DISCARD_EDITS" });
    expect(next).toBe(state);
    expect(siteList(next)[0].occ).toBe("0.900");
  });
});

describe("reducer — APPLY_EDITS", () => {
  it("promotes the working set to the applied baseline and resets edits", () => {
    let state = stateWithSites([makeSite()]);
    state = reducer(state, { type: "EDIT_SITE", id: "s1", field: "occ", value: "0.5" });
    const applied = reducer(state, { type: "APPLY_EDITS" });
    expect(applied.edits).toBe(0);
    expect(applied.applied).toBe(true);
    expect(applied.sites).toBeNull();
    expect(applied.appliedSites?.[0].occ).toBe("0.5");
  });
});

describe("reducer — SET_VIEW_MODEL stageOn server sync", () => {
  function makeStage(nn: string, released: boolean): StageRow {
    return { nn, name: nn, flags: "", delta_rwp: "", released, gate: null };
  }

  function viewModelWithStages(stages: StageRow[]): ViewModel {
    return { structure: { sites: [], constraints: [], mem_peaks: [] }, stages } as unknown as ViewModel;
  }

  it("overwrites stageOn from viewModel.stages[].released — server truth wins", () => {
    // Mirrors seed.py's seed_stages(): 01-06 and 08 released, 07 not — the
    // opposite of the client-side default (stageOn 1-5 true, 6-8 false).
    const stages = [
      makeStage("01", true),
      makeStage("02", true),
      makeStage("03", true),
      makeStage("04", true),
      makeStage("05", true),
      makeStage("06", true),
      makeStage("07", false),
      makeStage("08", true),
    ];
    const next = reducer(initialWorkbenchState, {
      type: "SET_VIEW_MODEL",
      viewModel: viewModelWithStages(stages),
    });

    expect(next.stageOn).toEqual({ 1: true, 2: true, 3: true, 4: true, 5: true, 6: true, 7: false, 8: true });
  });

  it("keeps the existing stageOn when stages[] is empty (no data yet, not a reset to {})", () => {
    const withCustomStageOn: WorkbenchState = { ...initialWorkbenchState, stageOn: { 1: false, 2: true } };
    const next = reducer(withCustomStageOn, {
      type: "SET_VIEW_MODEL",
      viewModel: viewModelWithStages([]),
    });

    expect(next.stageOn).toEqual({ 1: false, 2: true });
  });
});

describe("reducer — SET_SHELL activeJob sync from refine.kind (セルフレビュー指摘 #1 (b))", () => {
  it("syncs activeJob from shell.refine.kind while a job is running", () => {
    const next = reducer(initialWorkbenchState, {
      type: "SET_SHELL",
      shell: makeShell({ refine: refineStatus({ kind: "phaseid" }) }),
    });
    expect(next.activeJob).toBe("phaseid");
  });

  it('falls back to "refine" when kind is absent (older server)', () => {
    const status = refineStatus();
    delete (status as { kind?: unknown }).kind;
    const next = reducer(initialWorkbenchState, {
      type: "SET_SHELL",
      shell: makeShell({ refine: status }),
    });
    expect(next.activeJob).toBe("refine");
  });

  it('falls back to "refine" when kind is explicitly null (older server variant)', () => {
    const next = reducer(initialWorkbenchState, {
      type: "SET_SHELL",
      shell: makeShell({ refine: refineStatus({ kind: null }) }),
    });
    expect(next.activeJob).toBe("refine");
  });

  it("leaves activeJob untouched when no job is running", () => {
    const state: WorkbenchState = { ...initialWorkbenchState, activeJob: "multistart" };
    const next = reducer(state, {
      type: "SET_SHELL",
      shell: makeShell({
        refine: refineStatus({ status: "idle", elapsed_s: null, kind: null }),
      }),
    });
    expect(next.activeJob).toBe("multistart");
  });
});

describe("reducer — APPEND_TRANSCRIPT_MESSAGE", () => {
  function transcriptViewModel(stages: StageRow[]): ViewModel {
    return {
      structure: { sites: [], constraints: [], mem_peaks: [] },
      stages,
      transcript: [],
    } as unknown as ViewModel;
  }

  // Regression (self-review round 2): AgentSession's composer used to reuse
  // SET_VIEW_MODEL with a stale local viewModel, whose new stageOn resync then
  // silently undid optimistic TOGGLE_STAGE updates. The transcript-only action
  // must append without ever touching stageOn.
  it("appends to the transcript and leaves stageOn untouched", () => {
    const stages: StageRow[] = [
      { nn: "01", name: "background", flags: "", delta_rwp: "", released: false, gate: null },
    ];
    const loaded = reducer(initialWorkbenchState, {
      type: "SET_VIEW_MODEL",
      viewModel: transcriptViewModel(stages),
    });
    // optimistic local toggle diverging from the (now stale) viewModel.stages
    const toggled = reducer(loaded, { type: "TOGGLE_STAGE", nn: 1 });
    expect(toggled.stageOn[1]).toBe(true);

    const next = reducer(toggled, {
      type: "APPEND_TRANSCRIPT_MESSAGE",
      message: { id: "tX", kind: "user", text: "hello" },
    });

    expect(next.viewModel?.transcript.map((m) => m.id)).toContain("tX");
    expect(next.stageOn[1]).toBe(true); // NOT reverted to the stale server value
  });

  it("is a no-op before the first viewmodel fetch", () => {
    const next = reducer(initialWorkbenchState, {
      type: "APPEND_TRANSCRIPT_MESSAGE",
      message: { id: "tX", kind: "user", text: "hello" },
    });
    expect(next).toBe(initialWorkbenchState);
  });
});

describe("reducer — SET_VIEW_MODEL hist re-pointing", () => {
  // Regression: project mode's histograms are "h0"/"h1"/… while the client
  // default hist is the demo's "sxrd" — the stranded id made fit.plot["sxrd"]
  // undefined and the real curves never rendered (placeholder fallback).
  function vmWithHists(ids: string[], active?: string): ViewModel {
    return {
      structure: { sites: [], constraints: [], mem_peaks: [] },
      stages: [],
      transcript: [],
      fit: {
        metrics: [], limits_note: "", phase_ticks: [],
        two_theta: { min: 4, max: 38 }, history: [], validity: [],
        histograms: ids.map((id) => ({ id, label: id, active: id === (active ?? ids[0]) })),
      },
    } as unknown as ViewModel;
  }

  it("re-points a stranded hist to the active histogram id", () => {
    const next = reducer(initialWorkbenchState, {
      type: "SET_VIEW_MODEL",
      viewModel: vmWithHists(["h0"]),
    });
    expect(next.hist).toBe("h0");
  });

  it("keeps a hist that exists in the new viewmodel", () => {
    const loaded = reducer(initialWorkbenchState, {
      type: "SET_VIEW_MODEL",
      viewModel: vmWithHists(["sxrd", "nd1"], "sxrd"),
    });
    const onNd = reducer(loaded, { type: "SET_HIST", hist: "nd1" });
    const refetched = reducer(onNd, {
      type: "SET_VIEW_MODEL",
      viewModel: vmWithHists(["sxrd", "nd1"], "sxrd"),
    });
    expect(refetched.hist).toBe("nd1");
  });
});

describe("SET_FRAME_INDEX (V2b B2/B3 — ContextBar frame nav)", () => {
  it("defaults frameIndex to 0", () => {
    expect(initialWorkbenchState.frameIndex).toBe(0);
  });

  it("sets frameIndex to the given value", () => {
    const next = reducer(initialWorkbenchState, { type: "SET_FRAME_INDEX", index: 3 });
    expect(next.frameIndex).toBe(3);
  });

  it("clamps a negative index to 0 rather than storing it", () => {
    const next = reducer(initialWorkbenchState, { type: "SET_FRAME_INDEX", index: -1 });
    expect(next.frameIndex).toBe(0);
  });
});
