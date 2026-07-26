// Local strings for the right pane (MANUAL/AUTO bodies) that are NOT part of
// the central extraction (src/i18n/strings.ts). src/i18n/strings.ts is
// read-only for this task and, being a 1:1 extraction of the handoff
// prototype's hardcoded demo text, has no generic entries for the things the
// real API-driven view needs: a review item's severity *code* (the demo
// hardcoded four fixed titles, we render arbitrary server items), a dynamic
// open-item count, and the escalation FR tag (the demo baked "FR-403" into
// the string itself). Everything else the right pane needs already exists
// centrally and is reused via the normal useI18n() `t()`.
import type { JobKind } from "../../api/types";
import type { Lang } from "../../i18n";

export interface StringPair {
  en: string;
  ja: string;
}

export const RIGHT_STRINGS = {
  "review.severity.close": { en: "CLOSE", ja: "僅差" },
  "review.severity.unknown": { en: "UNKNOWN", ja: "未知相" },
  "review.severity.guard": { en: "GUARD", ja: "ガード" },
  "review.severity.echem": { en: "ECHEM", ja: "電気化学" },
  "review.acceptPending": { en: "ACCEPT …", ja: "承認 …" },
  "review.openCountNote": { en: "FR-421 / 423 · {n} open", ja: "FR-421 / 423 · 未処理 {n} 件" },
  "escalationLabel": { en: "ESCALATION", ja: "エスカレーション" },
  // RUN REFINEMENT button label while a background job is polling (real
  // project mode only — demo mode's postRefine resolves "recorded" and never
  // reaches this state). Central STRINGS' "recipe.runRefinement" has no
  // in-progress variant since the handoff prototype never modelled a running
  // job (it was a static mockup).
  "recipe.running": { en: "RUNNING …", ja: "実行中 …" },
  // Fallback error text when a shared-job-slot poll (state.refine) reports
  // "failed" without a server-supplied `error` message. Keyed by the job's
  // real `kind` (セルフレビュー指摘 #1, api-contract.md RefineStatus.kind) so
  // OperatorConsole never mislabels a phaseid/multistart failure as
  // "refinement failed" — see jobFailedFallback below. PhaseIdTab/
  // HypothesesTab have their own kind-specific localized fallbacks already
  // (pid.local.identifyFailed / hyp.local.multistartFailed) and don't use this.
  "job.failed.refine": { en: "refinement failed", ja: "精密化に失敗" },
  "job.failed.phaseid": { en: "phase identification failed", ja: "相同定に失敗" },
  "job.failed.multistart": { en: "multistart failed", ja: "マルチスタートに失敗" },
  "job.failed.sequential": { en: "sequential run failed", ja: "逐次実行に失敗" },
  // PENDING MODEL ACTIONS (V2b B5, api-contract.md §逐次 / operando §B5 新相提案):
  // OperatorConsole's MANUAL-mode surface for `kind: "approval"` transcript
  // cards — see OperatorConsole.tsx's isPendingApproval/pendingApprovals.
  "modelActions.pendingTitle": { en: "PENDING MODEL ACTIONS", ja: "保留中のモデル操作" },
  "modelActions.openCountNote": { en: "{n} pending", ja: "保留 {n} 件" },
  "modelActions.empty": { en: "no pending model actions", ja: "保留中のモデル操作はありません" },
  // Busy/conflict states for TranscriptItem's approval card while
  // POST /api/approval/{action_id} is in flight (レビュー指摘 #2 フロント側).
  // "resolving" replaces the mono state line while the request is pending
  // (buttons disabled too); "conflict" is the non-fatal 409 case — another
  // resolution already won the race (session.py resolve_approval's
  // check-and-set marker) — shown inline instead of the global error path.
  "chat.approval.resolving": { en: "resolving …", ja: "処理中 …" },
  "chat.approval.conflict": {
    en: "already resolved elsewhere · refresh to see the result",
    ja: "他の操作で解決済み · 更新して結果を確認してください",
  },
  // Tooltip for RUN REFINEMENT while status.gsas_available is false (V2c レビュー指摘 #4) —
  // Tier1 desktop sidecar excludes GSAS-II (desktop/README.md), and this job would otherwise
  // 422 with GSASUnavailableError server-side; disabling client-side with an explanatory title
  // makes the reason visible without a failed round-trip.
  "recipe.gsasUnavailable": {
    en: "GSAS-II is not available in this backend — refinement jobs cannot run",
    ja: "このバックエンドでは GSAS-II が利用できません — 精密化ジョブは実行できません",
  },
  // — AUTO 実 LLM ブリッジ (V3a, api-contract.md §AUTO 実 LLM ブリッジ) —
  // Replaces src/i18n/strings.ts' demo-era "composerNote" (a hardcoded
  // handoff-prototype skill name/tool count) now that AgentSession is backed
  // by a real local `claude` CLI bridge — central i18n/strings.ts is a
  // read-only 1:1 extraction of that prototype (see this file's header), so
  // the reality-facing replacement is colocated here instead of edited in.
  "composer.note.real": {
    en: "local Claude Code · custody: approvals stay human",
    ja: "ローカル Claude Code · custody: 承認は人間に残る",
  },
  // Composer footer while an agent turn is in flight (SEND disabled) —
  // shown in place of composer.note.real. {tokens}/{elapsed} are the live
  // polled values (formatTokens/formatWallTime), not the pre-turn strip.
  "agent.running": {
    en: "agent running… ({tokens} · {elapsed})",
    ja: "エージェント実行中…（{tokens}・{elapsed}）",
  },
  // Non-fatal inline failure line (mirrors chat.approval.conflict's
  // precedent — a 409/failed-job outcome stays local text, not the global
  // SET_ERROR path) for when GET /api/agent/status reports status=failed.
  // {detail} is `: <server error>` when the server supplied one, else "".
  "agent.failed": {
    en: "agent failed{detail}",
    ja: "エージェントが失敗しました{detail}",
  },
  // Inverted attention chip (mirrors Chip's "inverted" precedent for WARN/
  // CLOSE/UNKNOWN states) shown in the composer when state.shell.agent.available
  // is false — the local `claude` CLI / claude-agent-sdk optional extra is
  // not importable in this backend process.
  "agent.unavailable.chip": {
    en: "AGENT UNAVAILABLE — claude CLI / agent extra required",
    ja: "AGENT UNAVAILABLE — claude CLI / agent extra が必要",
  },
  // Kind badge on an approval card (api-contract.md §`propose_*` ツールと承認
  // カード) — mono inverted chip, one per gates.ts ApprovalKind. Keyed by the
  // action_id prefix (np-/sr-/rv-/pc-/st-); see gates.ts `approvalKind`.
  "modelAction.badge.np": { en: "NEW PHASE", ja: "新相" },
  "modelAction.badge.sr": { en: "REVISE STRUCTURE", ja: "構造改訂" },
  "modelAction.badge.rv": { en: "REVIEW", ja: "レビュー" },
  "modelAction.badge.pc": { en: "PHASE", ja: "相" },
  "modelAction.badge.st": { en: "SETTINGS", ja: "設定" },
  // `sr-` card summary line above the raw action_json (gates.ts
  // structureRevisionSiteCount) — kept to one line so it doesn't compete with
  // the JSON pre for attention (task brief: "過剰にしない").
  "modelAction.summary.sr": { en: "{n} site(s) changed", ja: "{n} サイト変更" },
  // Kind-specific post-decision state lines (task: "承認/却下後の状態行に
  // kind 別文言"). Only used when gates.ts `approvalKind` recognises the
  // action_id's prefix — an unprefixed/unknown id keeps the pre-existing
  // generic chat.approval.state* text from src/i18n/strings.ts unchanged, so
  // the AgentSession/OperatorConsole tests written against the "a1" fixture
  // (predates the propose_* prefixes) keep passing verbatim.
  "modelAction.state.applied.np": { en: "applied · new phase added to the phase set", ja: "適用 · 新相を相構成に追加" },
  "modelAction.state.applied.sr": { en: "applied · structure revision saved to a child snapshot", ja: "適用 · 構造改訂を子スナップショットに保存" },
  "modelAction.state.applied.rv": { en: "applied · review item resolved", ja: "適用 · レビュー項目を解決" },
  "modelAction.state.applied.pc": { en: "applied · phase set updated", ja: "適用 · 相構成を更新" },
  "modelAction.state.applied.st": { en: "applied · refinement settings updated", ja: "適用 · 精密化設定を更新" },
  "modelAction.state.rejected.np": { en: "rejected · new phase not added", ja: "却下 · 新相は追加されない" },
  "modelAction.state.rejected.sr": { en: "rejected · structure revision not applied", ja: "却下 · 構造改訂は適用されない" },
  "modelAction.state.rejected.rv": { en: "rejected · review item left pending", ja: "却下 · レビュー項目は保留のまま" },
  "modelAction.state.rejected.pc": { en: "rejected · phase set unchanged", ja: "却下 · 相構成は変更されない" },
  "modelAction.state.rejected.st": { en: "rejected · settings unchanged", ja: "却下 · 設定は変更されない" },
} as const satisfies Record<string, StringPair>;

export type RightStringKey = keyof typeof RIGHT_STRINGS;

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)), template);
}

/** Standalone translator for RIGHT_STRINGS, mirroring src/i18n/index.tsx's
 * `t()` — useI18n().t only accepts the central StringKey union, so a
 * colocated dictionary needs its own lookup. Callers pass `useI18n().lang`
 * directly rather than going through a second context provider. */
export function rt(lang: Lang, key: RightStringKey, vars?: Record<string, string | number>): string {
  const pair: StringPair | undefined = RIGHT_STRINGS[key];
  // Missing key → return the key itself (mirrors central t()'s total-function
  // contract): a label bug must degrade to visible text, never unmount the UI.
  if (!pair) return key;
  return interpolate(lang === "ja" ? pair.ja : pair.en, vars);
}

/** Kind-appropriate fallback text for a "failed" job status that carries no
 * server `error` message (セルフレビュー指摘 #1 (d)). `kind` defaults to
 * "refine" when the polled status predates the `kind` field (older server —
 * mirrors the same fallback used by SET_SHELL / resolveJobConflict). */
export function jobFailedFallback(lang: Lang, kind: JobKind | null | undefined): string {
  return rt(lang, `job.failed.${kind ?? "refine"}` as RightStringKey);
}
