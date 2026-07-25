import { describe, expect, it } from "vitest";
import { WELCOME_STRINGS, wt } from "./WelcomeScreen.strings";

describe("WELCOME_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(WELCOME_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });
});

describe("wt()", () => {
  it("renders English by default", () => {
    expect(wt("en", "welcome.title")).toBe("TSUMUGIN WORKBENCH");
  });

  it("renders Japanese", () => {
    expect(wt("ja", "welcome.title")).toBe("TSUMUGIN ワークベンチ");
  });

  it("degrades to the raw key for an unknown key rather than throwing", () => {
    // @ts-expect-error deliberate out-of-vocabulary key for the degrade path
    expect(wt("en", "not.a.real.key")).toBe("not.a.real.key");
  });
});
