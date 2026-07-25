import { describe, expect, it } from "vitest";
import { HYP_LOCAL_STRINGS, interpolateLocal } from "./HypothesesTab.strings";

describe("HYP_LOCAL_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(HYP_LOCAL_STRINGS)) {
      if (!pair.en?.trim()) missing.push(`${key}.en`);
      if (!pair.ja?.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("has no duplicate keys (object literal invariant)", () => {
    const keys = Object.keys(HYP_LOCAL_STRINGS);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.length).toBeGreaterThan(0);
  });
});

describe("interpolateLocal", () => {
  it("substitutes {message}-style placeholders", () => {
    expect(interpolateLocal("failed: {message}", { message: "boom" })).toBe("failed: boom");
  });
});
