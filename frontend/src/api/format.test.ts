import { describe, expect, it } from "vitest";
import { formatInt, formatNumber, formatSigned } from "./format";

// Regression: a real CaTeO3 run's first history row has delta_rwp=null (no
// predecessor stage) and null.toFixed unmounted the whole app. Backend-wide,
// finite_or_none serialises ANY non-finite number as null (chi2=inf is a
// normal path) — every numeric cell must degrade to an em-dash.
describe("null-safe numeric formatters (finite_or_none convention)", () => {
  it("formats finite numbers", () => {
    expect(formatNumber(12.568, 2)).toBe("12.57");
    expect(formatSigned(-4.394, 2)).toBe("-4.39");
    expect(formatSigned(0.42, 2)).toBe("+0.42");
    expect(formatInt(39402.4)).toBe("39,402");
  });

  it("degrades null / undefined / non-finite to an em-dash", () => {
    for (const bad of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatNumber(bad as never, 2)).toBe("—");
      expect(formatSigned(bad as never, 2)).toBe("—");
      expect(formatInt(bad as never)).toBe("—");
    }
  });
});
