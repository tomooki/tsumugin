import { describe, expect, it } from "vitest";
import { SETTINGS_STRINGS, sm } from "./SettingsModal.strings";

describe("SETTINGS_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(SETTINGS_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });
});

describe("sm()", () => {
  it("renders English by default", () => {
    expect(sm("en", "settings.title")).toBe("SETTINGS");
  });

  it("renders Japanese", () => {
    expect(sm("ja", "settings.title")).toBe("設定");
  });

  it("interpolates {hint} into the settings-source status string", () => {
    expect(sm("en", "settings.status.setSettings", { hint: "ab12" })).toBe("set · …ab12 (settings)");
    expect(sm("ja", "settings.status.setSettings", { hint: "ab12" })).toBe("設定済み · …ab12 (settings)");
  });

  it("degrades to the raw key for an unknown key rather than throwing", () => {
    // @ts-expect-error deliberate out-of-vocabulary key for the degrade path
    expect(sm("en", "not.a.real.key")).toBe("not.a.real.key");
  });
});
