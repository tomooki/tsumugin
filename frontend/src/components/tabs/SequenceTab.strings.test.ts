import { describe, expect, it } from "vitest";
import { SEQUENCE_STRINGS } from "./SequenceTab.strings";

describe("SEQUENCE_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(SEQUENCE_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("has exactly the keys SequenceTab.tsx is known to use", () => {
    expect(Object.keys(SEQUENCE_STRINGS).sort()).toEqual(
      ["anchor.crossoverSuffix", "chart.fallback.placeholder"].sort(),
    );
  });
});
