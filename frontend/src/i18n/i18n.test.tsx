import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "./index";
import { STRINGS } from "./strings";

describe("i18n dictionary — key set invariant", () => {
  it("every key has both a non-empty en and ja string", () => {
    const missing: string[] = [];
    for (const [key, pair] of Object.entries(STRINGS)) {
      if (!pair.en || !pair.en.trim()) missing.push(`${key}.en`);
      if (!pair.ja || !pair.ja.trim()) missing.push(`${key}.ja`);
    }
    expect(missing).toEqual([]);
  });

  it("has a non-trivial number of extracted keys", () => {
    // Guards against an accidental truncation of the extraction.
    expect(Object.keys(STRINGS).length).toBeGreaterThan(150);
  });
});

function Probe() {
  const { t } = useI18n();
  return <div data-testid="probe">{t("tab.fit")}</div>;
}

describe("I18nProvider — language switch", () => {
  it("renders the English string when lang=en", () => {
    render(
      <I18nProvider lang="en">
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("FIT");
  });

  it("renders the Japanese string when lang=ja", () => {
    render(
      <I18nProvider lang="ja">
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("probe")).toHaveTextContent("フィット");
  });

  it("falls back to the raw key for an unknown key rather than throwing", () => {
    function BadProbe() {
      const { t } = useI18n();
      // @ts-expect-error — intentionally invalid key for the fallback test
      return <div data-testid="bad">{t("does.not.exist")}</div>;
    }
    render(
      <I18nProvider lang="en">
        <BadProbe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("bad")).toHaveTextContent("does.not.exist");
  });

  it("interpolates {n} placeholders", () => {
    function CountProbe() {
      const { t } = useI18n();
      return <div data-testid="count">{t("param.releasedCount", { n: 3 })}</div>;
    }
    render(
      <I18nProvider lang="en">
        <CountProbe />
      </I18nProvider>,
    );
    expect(screen.getByTestId("count")).toHaveTextContent("released in this histogram: 3");
  });
});
