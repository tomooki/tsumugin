import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { STRINGS, type StringKey } from "./strings";

export type Lang = "en" | "ja";

interface I18nContextValue {
  lang: Lang;
  t: (key: StringKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    template,
  );
}

/** lang is an external prop (bound to the app-level `state.lang`), matching
 * the handoff's "also settable as an external prop" note. */
export function I18nProvider({ lang, children }: { lang: Lang; children: ReactNode }) {
  const t = useCallback(
    (key: StringKey, vars?: Record<string, string | number>) => {
      const pair = STRINGS[key];
      if (!pair) return key;
      const template = lang === "ja" ? pair.ja : pair.en;
      return interpolate(template, vars);
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, t }), [lang, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
