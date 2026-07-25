import { describe, expect, it } from "vitest";
import { FIT_LOCAL_STRINGS } from "./FitTab.strings";

describe("FIT_LOCAL_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(FIT_LOCAL_STRINGS)) {
      if (!pair.en?.trim()) missing.push(`${key}.en`);
      if (!pair.ja?.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("has no duplicate keys (object literal invariant)", () => {
    const keys = Object.keys(FIT_LOCAL_STRINGS);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.length).toBeGreaterThan(0);
  });
});
