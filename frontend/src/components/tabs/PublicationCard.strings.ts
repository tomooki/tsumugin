// Colocated strings for the publication-state card (fit-then-judge P1c,
// api-contract.md viewmodel.publication).
import type { StringPair } from "./FitTab.strings";

export const PUBLICATION_STRINGS = {
  title: { en: "PUBLICATION STATE", ja: "出版状態" },
  summary: { en: "publishable", ja: "出版可" },
  error: {
    en: "the publication state could not be built — nothing is publishable",
    ja: "出版状態を作れませんでした — 出版できる値はありません",
  },
  colValue: { en: "value", ja: "値" },
  colState: { en: "state", ja: "状態" },
  publishable: { en: "publishable", ja: "出版可" },
  held: { en: "held", ja: "止め" },
  requestsTitle: { en: "JUDGMENT REQUESTS", ja: "判断要求" },
  blocking: { en: "blocking", ja: "止める" },
  nonBlocking: { en: "informational", ja: "止めない" },
  blocks: { en: "values held", ja: "止めた値" },
  candidates: { en: "options", ja: "選択肢" },
  defaultAnswer: { en: "default (policy D)", ja: "既定の回答 (ポリシー D)" },
  readOnlyNote: {
    en: "Read only. A request is closed only by evidence in the data or by an approved answer (decision 2, not yet available) — report it, do not resolve it here.",
    ja: "表示のみです。判断要求を閉じられるのはデータの証人か承認済みの回答 (決定 2・未実装) だけです — ここでは閉じず、報告に添えてください。",
  },
  noRequests: { en: "no judgment requests", ja: "判断要求はありません" },
  relative: { en: "relative within this sample", ja: "この試料内の相対値" },
} as const satisfies Record<string, StringPair>;

export type PublicationKey = keyof typeof PUBLICATION_STRINGS;
