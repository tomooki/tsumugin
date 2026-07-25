import { describe, expect, it } from "vitest";
import { buildPath, domainFromValues, scaleX, scaleY } from "./path";

describe("scaleX / scaleY — domain mapping", () => {
  it("maps the domain min/max to the pixel extremes", () => {
    expect(scaleX(0, { min: 0, max: 10 }, 100)).toBe(0);
    expect(scaleX(10, { min: 0, max: 10 }, 100)).toBe(100);
    expect(scaleX(5, { min: 0, max: 10 }, 100)).toBe(50);
  });

  it("inverts y (SVG y grows downward, so domain max maps to pixel 0)", () => {
    expect(scaleY(0, { min: 0, max: 10 }, 100)).toBe(100);
    expect(scaleY(10, { min: 0, max: 10 }, 100)).toBe(0);
    expect(scaleY(5, { min: 0, max: 10 }, 100)).toBe(50);
  });

  it("maps a zero-span domain to the midpoint instead of dividing by zero", () => {
    expect(scaleX(4, { min: 4, max: 4 }, 100)).toBe(50);
    expect(scaleY(4, { min: 4, max: 4 }, 100)).toBe(50);
  });
});

describe("buildPath", () => {
  const xDomain = { min: 0, max: 10 };
  const yDomain = { min: 0, max: 10 };

  it("returns '' for an empty array", () => {
    expect(buildPath([], [], xDomain, yDomain, 100, 100)).toBe("");
  });

  it("returns '' when xs/ys lengths mismatch", () => {
    expect(buildPath([0, 1, 2], [0, 1], xDomain, yDomain, 100, 100)).toBe("");
  });

  it("builds an M-then-L path through every finite point", () => {
    const d = buildPath([0, 5, 10], [0, 5, 10], xDomain, yDomain, 100, 100);
    expect(d).toBe("M0.00,100.00 L50.00,50.00 L100.00,0.00");
  });

  it("starts a new subpath (M, not L) after a NaN point instead of connecting across the gap", () => {
    const d = buildPath([0, 5, 10], [0, NaN, 10], xDomain, yDomain, 100, 100);
    expect(d).toBe("M0.00,100.00M100.00,0.00");
    expect(d).not.toContain("L");
  });

  it("skips ±Infinity points the same way as NaN", () => {
    const d = buildPath([0, 5, 10], [0, Infinity, 10], xDomain, yDomain, 100, 100);
    expect(d).toBe("M0.00,100.00M100.00,0.00");
    expect(d).not.toContain("L");
  });

  it("returns '' when every point is non-finite", () => {
    expect(buildPath([1, 2], [NaN, NaN], xDomain, yDomain, 100, 100)).toBe("");
  });
});

describe("domainFromValues", () => {
  it("pads the span on both sides by the given fraction", () => {
    const d = domainFromValues([0, 10], 0.1);
    expect(d.min).toBeCloseTo(-1);
    expect(d.max).toBeCloseTo(11);
  });

  it("falls back to [0, 1] for an empty array", () => {
    expect(domainFromValues([])).toEqual({ min: 0, max: 1 });
  });

  it("falls back to [0, 1] when every value is non-finite", () => {
    expect(domainFromValues([NaN, Infinity, -Infinity])).toEqual({ min: 0, max: 1 });
  });

  it("ignores non-finite values mixed in with finite ones", () => {
    const d = domainFromValues([0, NaN, 10, Infinity], 0);
    expect(d).toEqual({ min: 0, max: 10 });
  });

  it("widens a zero-span (all-identical) input by ±1 instead of returning a degenerate domain", () => {
    expect(domainFromValues([4, 4, 4])).toEqual({ min: 3, max: 5 });
  });
});
