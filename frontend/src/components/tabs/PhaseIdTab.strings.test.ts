import { describe, expect, it } from "vitest";
import { interpolateLocal, PID_LOCAL_STRINGS } from "./PhaseIdTab.strings";

describe("PID_LOCAL_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(PID_LOCAL_STRINGS)) {
      if (!pair.en?.trim()) missing.push(`${key}.en`);
      if (!pair.ja?.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("has no duplicate keys (object literal invariant)", () => {
    const keys = Object.keys(PID_LOCAL_STRINGS);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.length).toBeGreaterThan(0);
  });
});

describe("interpolateLocal", () => {
  it("substitutes {name}-style placeholders", () => {
    expect(interpolateLocal("hello {formula}", { formula: "KMnFe(CN)6" })).toBe("hello KMnFe(CN)6");
  });

  it("is a no-op with no vars", () => {
    expect(interpolateLocal("IDENTIFY")).toBe("IDENTIFY");
  });
});
