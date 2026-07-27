// Colocated strings for the PHASES tab (api-contract.md §PHASES タブ). The
// handoff prototype had no such tab — the left rail's "PHASES IN MODEL" only
// listed what is in the model, with nowhere to control what each phase
// releases — so every string here is new rather than an extraction.
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const PHASES_STRINGS = {
  "tab.phases": { en: "PHASES", ja: "相" },
  "phases.title": { en: "PHASES IN MODEL", ja: "モデル内の相" },
  "phases.note": {
    en: "what each phase releases · the left rail only lists what is present",
    ja: "相ごとに何を解放するか · 左レールは「居るか」だけを示す",
  },
  "phases.empty": {
    en: "no phases in the model — add one from PROJECT, or identify one in PHASE ID",
    ja: "モデルに相がありません — PROJECT で追加するか、PHASE ID で同定してください",
  },
  "phases.col.name": { en: "PHASE", ja: "相" },
  "phases.col.sg": { en: "SG", ja: "空間群" },
  "phases.col.wt": { en: "wt%", ja: "重量分率" },
  "phases.col.cell": { en: "REFINED CELL", ja: "精密化格子" },
  "phases.col.refineCell": { en: "REFINE CELL", ja: "格子を精密化" },
  "phases.col.source": { en: "SOURCE", ja: "構造ファイル" },
  "phases.col.stages": { en: "STAGES TOUCHING THIS PHASE", ja: "この相に触れる段" },
  "phases.remove": { en: "REMOVE", ja: "除去" },
  "phases.removing": { en: "REMOVING …", ja: "除去中 …" },
  "phases.removeTip": { en: "remove {phase} from the model", ja: "{phase} をモデルから除去" },
  "phases.refineCellTip": {
    en: "unchecked = lattice held at its initial value for this phase",
    ja: "オフ = この相の格子を初期値に固定",
  },
  "phases.refineCellLabel": { en: "refine cell of {phase}", ja: "{phase} の格子を精密化" },
  "phases.busy": {
    en: "a job is running — phase settings are locked until it finishes",
    ja: "ジョブ実行中 — 完了するまで相設定は変更できません",
  },
  "phases.error": { en: "failed to update {phase}: {message}", ja: "{phase} の更新に失敗: {message}" },
  "phases.cellPending": { en: "not refined yet", ja: "未精密化" },
  // ⚠ 相単位で制御できるフラグは今 refine_cell だけ。「触れるのに効かない」チェックボックスを
  //    置かないための説明 (api-contract.md §PHASES タブ の明示宣言と対)。
  "phases.scopeNote": {
    en:
      "Only the lattice can be released per phase today. Size/microstrain, preferred orientation " +
      "and the temperature-difference Dij are physically per-phase too, but the engine applies " +
      "them to every phase at once — so they are shown here read-only and are switched as whole " +
      "recipe stages in the OPERATOR CONSOLE.",
    ja:
      "相単位で解放を切り替えられるのは今のところ格子だけです。サイズ/微小歪み・選択配向・" +
      "温度差 Dij も物理的には相スコープですが、エンジンは全相へ一律に適用するため、ここでは" +
      "読み取り専用で示し、切替は右ペインのレシピ段の ON/OFF で行います。",
  },
} as const satisfies Record<string, StringPair>;

export type PhasesStringKey = keyof typeof PHASES_STRINGS;

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), template);
}

/** Standalone translator for PHASES_STRINGS (mirrors ProjectTab.strings.ts's `pt()`). */
export function ph(
  lang: Lang,
  key: PhasesStringKey,
  vars?: Record<string, string | number>,
): string {
  const pair: StringPair | undefined = PHASES_STRINGS[key];
  if (!pair) return key;
  return interpolate(lang === "ja" ? pair.ja : pair.en, vars);
}
