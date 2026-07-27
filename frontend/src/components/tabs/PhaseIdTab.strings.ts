// Colocated strings for PhaseIdTab's A4 IDENTIFY job UI (api-contract.md
// §解析ループ: POST /api/phaseid, GET /api/phaseid/status, POST
// /api/phaseid/add) — src/i18n/strings.ts is read-only for this task (a
// parallel agent owns it) and, being a 1:1 extraction of the static handoff
// mockup, has no vocabulary for this real network flow (mode picker,
// in-flight/error/success chrome). Central STRINGS already covers the
// static table/card copy (pid.title, pid.action.addAsPhase, …) — this file
// only adds what the mockup never needed.
export interface StringPair {
  en: string;
  ja: string;
}

export const PID_LOCAL_STRINGS = {
  "pid.local.modeLabel": { en: "mode", ja: "モード" },
  "pid.local.modePattern": { en: "pattern", ja: "パターン" },
  "pid.local.modeResidual": { en: "residual", ja: "残差" },
  "pid.local.identify": { en: "IDENTIFY", ja: "同定実行" },
  "pid.local.identifying": { en: "IDENTIFYING …", ja: "同定中 …" },
  "pid.local.identifyBusy": {
    en: "phase identification is already running (job slot busy) — try again once it finishes",
    ja: "相同定は既に実行中です（ジョブ枠が使用中）— 完了後に再試行してください",
  },
  "pid.local.identifyError": {
    en: "failed to start phase identification: {message}",
    ja: "相同定の開始に失敗: {message}",
  },
  "pid.local.identifyFailed": {
    en: "phase identification failed: {message}",
    ja: "相同定に失敗: {message}",
  },
  "pid.local.identifyPollError": {
    en: "failed to fetch phase identification status: {message}",
    ja: "相同定の状態取得に失敗: {message}",
  },
  "pid.local.addAdding": { en: "adding …", ja: "追加中 …" },
  "pid.local.addSuccess": {
    en: "{formula} added — included on the next RUN REFINEMENT",
    ja: "{formula} を追加しました — 次回の RUN REFINEMENT で反映されます",
  },
  "pid.local.addError": {
    en: "failed to add {formula} as a phase: {message}",
    ja: "{formula} の相追加に失敗: {message}",
  },
  // api-contract.md §アプリ設定: pre-disable tooltip for IDENTIFY/ADD AS
  // PHASE when status.mp_available is false — same "gsas_available と同じ
  // 流儀" precedent as OperatorConsole's recipe.gsasUnavailable tooltip
  // (right.strings.ts).
  // 相同定に実際に使われる元素系 (viewmodel.phase_id.elements)。空なら**表示自体を出さない** —
  // プロトタイプの固定表記 (K, Mn, Fe, C, N, O) の置き換え。
  "pid.local.elements": { en: "elements {elements}", ja: "元素 {elements}" },
  // 元素セレクタ (未知試料の動線): CIF を読み込まずに元素系を直接指定する。
  "pid.local.elementsLabel": { en: "element system", ja: "元素系" },
  "pid.local.elementsAdd": { en: "add element", ja: "元素を追加" },
  "pid.local.elementsAddHint": { en: "+ element", ja: "+ 元素" },
  "pid.local.elementsRemove": { en: "remove {element}", ja: "{element} を外す" },
  "pid.local.elementsEmpty": {
    en: "none selected — the server will derive it from the current phases' CIFs",
    ja: "未選択 — 現相集合の CIF から導出されます",
  },
  "pid.local.elementsHint": {
    en: "for an unknown sample, pick the elements here — no CIF needed",
    ja: "未知試料はここで元素を選ぶ (CIF の読み込みは不要)",
  },
  "pid.local.mpUnavailable": {
    en: "Materials Project token not set — enter it from Settings",
    ja: "Materials Project トークン未設定 — 設定から入力してください",
  },
} as const satisfies Record<string, StringPair>;

export type PidLocalKey = keyof typeof PID_LOCAL_STRINGS;

/** Same `{n}`-style interpolation as src/i18n/index.tsx, duplicated locally
 * since that helper isn't exported (mirrors StructureTab.strings.ts's
 * interpolateLocal). */
export function interpolateLocal(
  template: string,
  vars?: Record<string, string | number>,
): string {
  if (!vars) return template;
  return Object.entries(vars).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    template,
  );
}
