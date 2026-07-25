import { describe, expect, it } from "vitest";
import { SHELL_STRINGS, st } from "./shell.strings";

describe("SHELL_STRINGS — EN/JA key set invariant (mirrors right.strings.test.ts)", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(SHELL_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });
});

describe("st()", () => {
  it("renders English by default", () => {
    expect(st("en", "refine.running")).toBe("REFINING …");
  });

  it("renders Japanese", () => {
    expect(st("ja", "refine.running")).toBe("精密化 実行中 …");
  });

  it("interpolates {k}/{n}", () => {
    expect(st("en", "frame.nav.label", { k: 3, n: 63 })).toBe("fr 3 / 63");
    expect(st("ja", "frame.nav.label", { k: 3, n: 63 })).toBe("fr 3 / 63");
  });
});
