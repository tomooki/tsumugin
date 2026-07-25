import { useCallback, useEffect } from "react";
import type { RefineStatus } from "../api/types";

// GET .../status responses (RUN REFINEMENT / IDENTIFY / MULTISTART) all
// share this shape (api-contract.md §解析ループ: "GET /api/phaseid/status |
// refine/status と同形", and the multistart entry likewise).
export type JobStatus = RefineStatus;

const DEFAULT_POLL_MS = 2000;

export interface UsePollJobOptions {
  /** Current job status — controlled by the caller (global store slot for
   * OperatorConsole/PhaseIdTab/HypothesesTab, since the three job kinds
   * share ONE backend job slot; a component-local useState would also work
   * for an independent job). null/idle/done/failed ⇒ not polling. */
  status: JobStatus | null | undefined;
  /** Setter for the controlled status above — called with every poll tick's
   * result, including "running" ticks (mirrors the pre-extraction
   * OperatorConsole behaviour of dispatching SET_REFINE_STATUS on every
   * tick, not just on done/failed). */
  setStatus: (status: JobStatus) => void;
  /** GET .../status call for this job kind (getRefineStatus / getPhaseIdStatus
   * / getMultistartStatus — see api/client.ts). */
  statusFn: () => Promise<JobStatus>;
  /** Runs once a tick reports status === "done", after setStatus has already
   * run. Typically a viewmodel/state refetch — see api-contract.md's per-job
   * "完了で viewmodel.… が実候補/実データに" notes. May be async; the poll
   * tick awaits it so a caller can safely dispatch further store updates
   * inside without a race against the next tick. */
  onDone: (status: JobStatus) => void | Promise<void>;
  /** Runs once a tick reports status === "failed" (the job itself failed
   * server-side, as opposed to onError below). */
  onFailed?: (status: JobStatus) => void;
  /** Runs when the statusFn() fetch itself throws (network/API error, not a
   * job failure — e.g. the server is unreachable mid-poll). */
  onError?: (err: unknown) => void;
  /** Whether this hook instance is allowed to poll right now. Needed because
   * `status` is a SHARED slot across job kinds (state.refine): without this,
   * every mounted job-owning component would start polling its own endpoint
   * the moment ANY job kind reports "running", even one it doesn't own. Pass
   * `state.activeJob === "phaseid"` etc. Defaults to true for callers with
   * their own independent (non-shared) status state. */
  enabled?: boolean;
  intervalMs?: number;
}

/** Shared "poll a background job until it leaves running" loop. One job slot
 * on the backend (api-contract.md §解析ループ: "refine/phaseid/multistart は
 * 相互に 409") is exposed as three separate GET .../status endpoints on the
 * frontend; this hook is the single tick/interval implementation reused by
 * OperatorConsole (RUN REFINEMENT, A1), PhaseIdTab (IDENTIFY, A4) and
 * HypothesesTab (MULTISTART, A5) rather than three copies of the same
 * setInterval-while-running logic.
 *
 * Side-effect-only: callers own where `status` lives and how the job is
 * *started* (POST /api/refine, /api/phaseid, /api/multistart differ per job
 * kind) — this hook only drives the polling once a caller has flipped
 * `status` to "running".
 *
 * Callers should memoize `onDone`/`onFailed`/`onError`/`statusFn` (useCallback)
 * — the interval is torn down and recreated whenever any of them changes
 * identity (mirrors the original OperatorConsole implementation's own
 * useCallback-wrapped tick). */
export function usePollJob({
  status,
  setStatus,
  statusFn,
  onDone,
  onFailed,
  onError,
  enabled = true,
  intervalMs = DEFAULT_POLL_MS,
}: UsePollJobOptions): void {
  const poll = useCallback(async () => {
    try {
      const next = await statusFn();
      setStatus(next);
      if (next.status === "done") {
        await onDone(next);
      } else if (next.status === "failed") {
        onFailed?.(next);
      }
    } catch (err) {
      onError?.(err);
    }
  }, [statusFn, setStatus, onDone, onFailed, onError]);

  useEffect(() => {
    if (!enabled || status?.status !== "running") return;
    const id = setInterval(() => {
      poll();
    }, intervalMs);
    return () => clearInterval(id);
  }, [enabled, status?.status, poll, intervalMs]);
}
