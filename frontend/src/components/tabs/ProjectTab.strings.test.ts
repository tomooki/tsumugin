import { describe, expect, it } from "vitest";
import { PROJECT_STRINGS, pt } from "./ProjectTab.strings";

describe("PROJECT_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(PROJECT_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });
});

describe("pt()", () => {
  it("renders English by default", () => {
    expect(pt("en", "tab.project")).toBe("PROJECT");
  });

  it("renders Japanese", () => {
    expect(pt("ja", "tab.project")).toBe("プロジェクト");
  });

  it("interpolates {id}/{name}", () => {
    expect(pt("en", "project.histograms.remove.confirm", { id: "h0" })).toBe(
      "Remove histogram h0? Its analysis history stays in the ledger.",
    );
    expect(pt("ja", "project.phases.remove.confirm", { name: "alpha" })).toBe(
      "相 alpha を除去しますか? 解析履歴は ledger に残ります。",
    );
  });

  it("degrades to the raw key for an unknown key rather than throwing", () => {
    // @ts-expect-error deliberate out-of-vocabulary key for the degrade path
    expect(pt("en", "not.a.real.key")).toBe("not.a.real.key");
  });
});
