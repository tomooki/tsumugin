import { describe, expect, it } from "vitest";
import { DATA_FORMAT_OPTIONS, GEOMETRY_OPTIONS, RADIATION_OPTIONS } from "./projectOptions";

// Legal-value invariants — these must match the backend wire vocabulary
// exactly (src/tsumugin/autorietveld/model.py Radiation/Geometry enums,
// src/tsumugin/reference/io.py _LOADERS keys) or the ADD HISTOGRAM form
// silently sends a value the backend rejects.

describe("RADIATION_OPTIONS — Radiation enum wire values", () => {
  it("matches src/tsumugin/autorietveld/model.py Radiation exactly", () => {
    expect(RADIATION_OPTIONS.map((o) => o.value)).toEqual([
      "xray_lab",
      "xray_synchrotron",
      "neutron_cw",
      "neutron_tof",
    ]);
  });

  it("every option has a non-empty label", () => {
    for (const o of RADIATION_OPTIONS) expect(o.label.trim().length).toBeGreaterThan(0);
  });
});

describe("GEOMETRY_OPTIONS — Geometry enum wire values", () => {
  it("matches src/tsumugin/autorietveld/model.py Geometry exactly", () => {
    expect(GEOMETRY_OPTIONS.map((o) => o.value)).toEqual(["bragg_brentano", "debye_scherrer"]);
  });
});

describe("DATA_FORMAT_OPTIONS — REQ-GUI-016 subset of reference.io _LOADERS", () => {
  it("matches the REQ-GUI-016 list (XRDML/XY/XYE/FXYE/GSAS) exactly", () => {
    expect(DATA_FORMAT_OPTIONS.map((o) => o.value)).toEqual(["XRDML", "XY", "XYE", "FXYE", "GSAS"]);
  });

  it("every value is upper-case (data_format is matched case-insensitively but sent upper-case)", () => {
    for (const o of DATA_FORMAT_OPTIONS) expect(o.value).toBe(o.value.toUpperCase());
  });
});
