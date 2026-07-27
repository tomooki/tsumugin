import { describe, expect, it } from "vitest";
import { PATH_PICKER_STRINGS, pp } from "./PathPicker.strings";

describe("PATH_PICKER_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(PATH_PICKER_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });
});

describe("pp()", () => {
  it("renders English by default", () => {
    expect(pp("en", "picker.select")).toBe("SELECT");
  });

  it("renders Japanese", () => {
    expect(pp("ja", "picker.select")).toBe("選択");
  });

  it("degrades to the raw key for an unknown key rather than throwing", () => {
    // @ts-expect-error deliberate out-of-vocabulary key for the degrade path
    expect(pp("en", "not.a.real.key")).toBe("not.a.real.key");
  });
});
