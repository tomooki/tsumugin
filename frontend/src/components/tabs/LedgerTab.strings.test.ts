import { describe, expect, it } from "vitest";
import { LEDGER_STRINGS } from "./LedgerTab.strings";

describe("LEDGER_STRINGS — EN/JA key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(LEDGER_STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("has exactly the keys LedgerTab.tsx is known to use", () => {
    expect(Object.keys(LEDGER_STRINGS).sort()).toEqual(
      ["ledger.actor.guard", "ledger.loading", "ledger.error", "ledger.empty"].sort(),
    );
  });
});
