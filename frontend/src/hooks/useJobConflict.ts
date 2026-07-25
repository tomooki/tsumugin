import type { Dispatch } from "react";
import { getRefineStatus } from "../api/client";
import type { Action } from "../state/actions";

/** Shared 409 ("job slot busy") handler for RUN REFINEMENT (OperatorConsole,
 * A1) / IDENTIFY (PhaseIdTab, A4) / MULTISTART (HypothesesTab, A5). All three
 * POST a job-start request onto the ONE shared backend job slot
 * (api-contract.md §解析ループ: "ジョブ枠は 1 つ"); a 409 means SOME job —
 * not necessarily this caller's own kind — is already running.
 *
 * Before the `kind` field existed (セルフレビュー指摘 #1), each caller could
 * only guess: OperatorConsole hardcoded `activeJob: "refine"` on every 409
 * (wrong whenever IDENTIFY/MULTISTART was the real owner), and PhaseIdTab/
 * HypothesesTab did not touch `activeJob` at all (so if their own job kind
 * turned out to be the real owner, nothing kept polling it — a completed or
 * failed job would sit unnoticed until an unrelated refetch).
 *
 * This fetches the shared status ONCE and syncs `state.refine`/
 * `state.activeJob` from its real `kind`, so whichever component actually
 * owns the job (as reported by the server, not guessed) starts/resumes
 * polling it via `usePollJob`'s `enabled: state.activeJob === "<kind>"` gate.
 *
 * `kind` is optional (older servers omit it, see api/types.ts RefineStatus) —
 * falls back to `"refine"`, mirroring SET_SHELL's identical fallback in
 * state/reducer.ts.
 */
export async function resolveJobConflict(dispatch: Dispatch<Action>): Promise<void> {
  const status = await getRefineStatus();
  dispatch({ type: "SET_REFINE_STATUS", refine: status });
  dispatch({ type: "SET_ACTIVE_JOB", job: status.kind ?? "refine" });
}
