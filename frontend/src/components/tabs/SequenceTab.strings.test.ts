import { describe, expect, it } from "vitest";
import { SEQUENCE_STRINGS, sqt } from "./SequenceTab.strings";

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
      [
        "anchor.crossoverSuffix",
        "chart.fallback.placeholder",
        // V2b B2/B3 (RUN SEQUENTIAL job UI, api-contract.md §逐次 / operando)
        "seq.run.heading",
        "seq.run.modeLabel",
        "seq.run.modeForward",
        "seq.run.modeAnchored",
        "seq.run.button",
        "seq.run.running",
        "seq.run.busy",
        "seq.run.error",
        "seq.run.failed",
        "seq.run.pollError",
        "seq.run.chargeConstraint",
        "seq.run.chargeConstraintHint",
        // V2c レビュー指摘 #4: GSAS-II 不在時の RUN SEQUENTIAL 無効化ツールチップ
        "seq.run.gsasUnavailable",
        "seq.anchorTable.heading",
        "seq.anchorTable.note",
        "seq.anchorTable.empty",
        "seq.framesTable.heading",
        "col.frame",
        "col.axisValue",
        "col.cells",
        "col.fractions",
        "col.changepoint",
      ].sort(),
    );
  });
});

describe("sqt()", () => {
  it("renders English by default", () => {
    expect(sqt("en", "seq.run.button")).toBe("RUN SEQUENTIAL");
  });

  it("renders Japanese", () => {
    expect(sqt("ja", "seq.run.button")).toBe("逐次実行");
  });

  it("interpolates {message}", () => {
    expect(sqt("en", "seq.run.error", { message: "boom" })).toBe(
      "failed to start sequential run: boom",
    );
    expect(sqt("ja", "seq.run.failed", { message: "boom" })).toBe("逐次実行に失敗: boom");
  });

  it("degrades to the raw key for an unknown key rather than throwing", () => {
    // @ts-expect-error deliberate out-of-vocabulary key for the degrade path
    expect(sqt("en", "not.a.real.key")).toBe("not.a.real.key");
  });
});
