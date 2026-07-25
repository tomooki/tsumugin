import { describe, expect, it } from "vitest";
import { RIGHT_STRINGS, rt } from "./right.strings";

describe("RIGHT_STRINGS — key set invariant (mirrors src/i18n/i18n.test.tsx)", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(RIGHT_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("en and ja key sets are identical (same object, so structurally guaranteed, but guard regardless)", () => {
    for (const pair of Object.values(RIGHT_STRINGS)) {
      expect(typeof pair.en).toBe("string");
      expect(typeof pair.ja).toBe("string");
    }
  });
});

describe("rt()", () => {
  it("renders English by default", () => {
    expect(rt("en", "escalationLabel")).toBe("ESCALATION");
  });

  it("renders Japanese", () => {
    expect(rt("ja", "escalationLabel")).toBe("エスカレーション");
  });

  it("interpolates {n}", () => {
    expect(rt("en", "review.openCountNote", { n: 4 })).toBe("FR-421 / 423 · 4 open");
    expect(rt("ja", "review.openCountNote", { n: 4 })).toBe("FR-421 / 423 · 未処理 4 件");
  });
});
