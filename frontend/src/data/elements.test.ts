import { describe, expect, it } from "vitest";
import { ELEMENTS, elementLabel } from "./elements";

describe("ELEMENTS — GSAS-II atomic-number order + D isotope insertion", () => {
  it("has exactly 99 entries (98 elements + D)", () => {
    expect(ELEMENTS).toHaveLength(99);
  });

  it("starts with 1 H", () => {
    expect(ELEMENTS[0]).toEqual({ z: 1, symbol: "H" });
    expect(elementLabel(ELEMENTS[0])).toBe("1 H");
  });

  it("places D immediately after H, sharing Z=1", () => {
    expect(ELEMENTS[1]).toEqual({ z: 1, symbol: "D" });
    expect(elementLabel(ELEMENTS[1])).toBe("1 D");
  });

  it("ends with 98 Cf", () => {
    const last = ELEMENTS[ELEMENTS.length - 1];
    expect(last).toEqual({ z: 98, symbol: "Cf" });
    expect(elementLabel(last)).toBe("98 Cf");
  });

  it("is in non-decreasing atomic-number order", () => {
    for (let i = 1; i < ELEMENTS.length; i++) {
      expect(ELEMENTS[i].z).toBeGreaterThanOrEqual(ELEMENTS[i - 1].z);
    }
  });

  it("contains no duplicate symbols other than D sharing H's Z", () => {
    const symbols = ELEMENTS.map((e) => e.symbol);
    expect(new Set(symbols).size).toBe(symbols.length);
  });
});
