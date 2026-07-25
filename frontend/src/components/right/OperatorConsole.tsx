import { useCallback, useMemo } from "react";
import {
  ApiError,
  getRefineStatus,
  getState,
  getViewModel,
  postRefine,
  postReviewResolve,
  postStage,
} from "../../api/client";
import type { RefineStatus, ReviewItem, StageRow, TranscriptMessage } from "../../api/types";
import { resolveJobConflict } from "../../hooks/useJobConflict";
import { usePollJob } from "../../hooks/usePollJob";
import { useI18n } from "../../i18n";
import type { ApprovalState } from "../../state/types";
import { useStore } from "../../state/store";
import { Btn, Chip } from "../common";
import "./OperatorConsole.css";
import { computeStagesOn, isStageGateOpen, reviewSeverityChipVariant, reviewSeverityLabelKey } from "./gates";
import { jobFailedFallback, rt } from "./right.strings";
import { TranscriptItem } from "./TranscriptItem";

/** Is this transcript message an approval card still awaiting a decision?
 * "Still" accounts for BOTH sources of truth: the server-fetched
 * `message.state` (viewmodel.transcript, refreshed on the next viewmodel
 * fetch) and this session's own local decision (state.approval, keyed by
 * action_id — see TranscriptItem's `decide()`, which OperatorConsole reuses
 * verbatim below). A card the user already decided locally must disappear
 * from PENDING MODEL ACTIONS immediately, without waiting for a refetch. */
function isPendingApproval(message: TranscriptMessage, approval: Record<string, ApprovalState>): boolean {
  if (message.kind !== "approval") return false;
  const local = message.action_id ? approval[message.action_id] : undefined;
  return (local ?? message.state ?? "pending") === "pending";
}

/** MANUAL right-pane body — handoff/README.md §Right pane "MANUAL body":
 * STAGED RELEASE RECIPE (gated by PARAMETERS/STRUCTURE) + RUN
 * REFINEMENT/SNAPSHOT + REVIEW QUEUE (FR-421/423). Gating is derived, never
 * server-supplied — see gates.ts `isStageGateOpen`. */
export function OperatorConsole() {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  const vm = state.viewModel;
  // useMemo (not a bare `?? []`) so this array's identity is stable across
  // renders that don't change vm.stages — handleRunRefinement below depends
  // on it, and a fresh [] literal every render would otherwise defeat that
  // useCallback's memoization entirely.
  const stages: StageRow[] = useMemo(() => vm?.stages ?? [], [vm?.stages]);
  const review: ReviewItem[] = vm?.review ?? [];
  // V2b B5 (api-contract.md §逐次 / operando): sequential runs that detect a
  // changepoint/unexplained residual generate a `kind: "approval"` transcript
  // card ("frame N で新相を同定して追加するか"). Surfacing it here (not only
  // in AgentSession's transcript) is what makes it visible in MANUAL mode —
  // OperatorConsole IS the MANUAL body (see file docstring), and the
  // engine-internal auto-accept path is explicitly not used for GUI approvals
  // (CLAUDE.md: "提案≠適用"), so a human must see and act on this queue.
  const pendingApprovals = (vm?.transcript ?? []).filter((m) => isPendingApproval(m, state.approval));

  const running = state.refine?.status === "running";
  // Tier1 desktop sidecar excludes GSAS-II (desktop/README.md "Tier1 の GSAS 前提") —
  // status.gsas_available is dynamic per GET /api/state (api/types.ts BackendStatus). Default
  // true when shell/status hasn't loaded yet so the button isn't disabled during the initial
  // fetch (mirrors the existing "unknown → not-yet-gated" convention elsewhere in this file).
  const gsasAvailable = state.shell?.status?.gsas_available ?? true;

  const reportError = useCallback(
    (err: unknown, fallback: string) => {
      dispatch({ type: "SET_ERROR", error: err instanceof ApiError ? err.message : fallback });
    },
    [dispatch],
  );

  const handleToggleStage = useCallback(
    async (stage: StageRow, on: boolean, gated: boolean) => {
      // Gated stages never release, even if this fires by some other path —
      // the disabled button is the first guard, this is the second.
      if (!on && gated) return;
      try {
        await postStage(stage.nn, on ? "revert" : "release");
        dispatch({ type: "TOGGLE_STAGE", nn: Number(stage.nn) });
      } catch (err) {
        reportError(err, "failed to update stage");
      }
    },
    [dispatch, reportError],
  );

  // state.refine is a SHARED job-status slot (RUN REFINEMENT / IDENTIFY /
  // MULTISTART all write it — see hooks/usePollJob.ts and state/types.ts
  // ActiveJob) so RUN REFINEMENT also disables itself while one of the
  // other two jobs is running (api-contract.md: one job slot).
  const setRefineStatus = useCallback(
    (refine: RefineStatus) => dispatch({ type: "SET_REFINE_STATUS", refine }),
    [dispatch],
  );

  // On done: refetch state+viewmodel so the real metrics/history/curves land
  // (the completed job wrote them server-side, but this client only sees
  // them via a fresh GET).
  const handleRefineDone = useCallback(async () => {
    dispatch({ type: "SET_ACTIVE_JOB", job: null });
    const [shell, viewModel] = await Promise.all([getState(), getViewModel()]);
    dispatch({ type: "SET_SHELL", shell });
    dispatch({ type: "SET_VIEW_MODEL", viewModel });
  }, [dispatch]);

  const handleRefineFailed = useCallback(
    (next: RefineStatus) => {
      dispatch({ type: "SET_ACTIVE_JOB", job: null });
      // Kind-aware fallback (セルフレビュー指摘 #1 (d)): this poll only ever
      // runs while activeJob === "refine" (see usePollJob's `enabled` below),
      // so next.kind is normally "refine" too — but fall back through the
      // same jobFailedFallback helper other callers use rather than a
      // hardcoded string, in case a stale/legacy status ever disagrees.
      dispatch({ type: "SET_ERROR", error: next.error ?? jobFailedFallback(lang, next.kind) });
    },
    [dispatch, lang],
  );

  const handleRefinePollError = useCallback(
    (err: unknown) => reportError(err, "failed to fetch refinement status"),
    [reportError],
  );

  // Polling loop: only armed while state.refine.status === "running" AND
  // this job kind (activeJob === "refine") owns the shared slot — see
  // usePollJob's `enabled` doc comment for why the second condition matters.
  usePollJob({
    status: state.refine,
    setStatus: setRefineStatus,
    statusFn: getRefineStatus,
    enabled: state.activeJob === "refine",
    onDone: handleRefineDone,
    onFailed: handleRefineFailed,
    onError: handleRefinePollError,
  });

  const handleRunRefinement = useCallback(() => {
    // Second guard against a double press racing the disabled attribute
    // (React state updates are not synchronous with the click handler).
    if (state.refine?.status === "running") return;
    if (!gsasAvailable) return;
    // A1: the recipe UI's gating reaches the real run only through this
    // payload — a gated stage is always sent as false regardless of its
    // client-side toggle (see gates.ts computeStagesOn).
    const stagesOn = computeStagesOn(stages, state);
    postRefine({ stages_on: stagesOn })
      .then((res) => {
        if (res.status === "started") {
          dispatch({ type: "SET_ACTIVE_JOB", job: "refine" });
          setRefineStatus({ status: "running", elapsed_s: 0, last_event: null, error: null });
        }
        // res.status === "recorded": demo mode (no project connected) — a
        // single-shot ledger record, nothing to poll.
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) {
          // Non-fatal: a job is already running (elsewhere, or a stale local
          // state after reload) — fetch the shared status ONCE and sync
          // activeJob from its real `kind` (セルフレビュー指摘 #1 (c)) so the
          // component that actually owns the job keeps polling it, instead
          // of hardcoding "refine" (wrong whenever IDENTIFY/MULTISTART is
          // the real owner — see hooks/useJobConflict.ts).
          void resolveJobConflict(dispatch).catch(() => {
            // best-effort sync; the fetch itself failing is not fatal here —
            // fall back to the pre-existing assumption so the button/status
            // still reflects "busy" rather than silently doing nothing.
            dispatch({ type: "SET_ACTIVE_JOB", job: "refine" });
            setRefineStatus({ status: "running", elapsed_s: null, last_event: null, error: null });
          });
          return;
        }
        reportError(err, "failed to run refinement");
      });
  }, [state, stages, dispatch, setRefineStatus, reportError, gsasAvailable]);

  const handleReviewAction = useCallback(
    async (item: ReviewItem, action: "accept" | "send_back") => {
      try {
        await postReviewResolve(item.id, { action, note: "" });
        dispatch({ type: "SET_REVIEW", id: item.id, decision: action === "accept" ? "accepted" : "sent_back" });
      } catch (err) {
        reportError(err, "failed to resolve review item");
      }
    },
    [dispatch, reportError],
  );

  return (
    <div className="operator-console tg-scroll">
      <section>
        <div className="oc-section-head">
          <span className="oc-section-head__title">{t("recipe.title")}</span>
          <span className="oc-section-head__note">{t("recipe.note")}</span>
        </div>
        <div className="oc-precedence">
          <span className="oc-precedence__rule" />
          <span>
            <span className="oc-precedence__kicker">{t("recipe.precedenceShort")}</span>
            <span className="oc-precedence__body">{t("recipe.precedence")}</span>
          </span>
        </div>
        <div className="oc-stages">
          {stages.map((stage) => {
            const on = !!state.stageOn[Number(stage.nn)];
            const gated = !isStageGateOpen(stage.gate, state.hist, state);
            const subline = gated
              ? stage.nn === "07"
                ? t("stage.gatedOccupancy")
                : t("stage.gatedParams")
              : `${stage.flags} · ${stage.delta_rwp}`;
            return (
              <div key={stage.nn} className={`oc-stage${on ? " oc-stage--on" : ""}`}>
                <span className="oc-stage__n">{stage.nn}</span>
                <span>
                  <span className="oc-stage__name">{stage.name}</span>
                  <span className={`oc-stage__sub${gated ? " oc-stage__sub--gated" : ""}`}>{subline}</span>
                </span>
                <Btn
                  type="button"
                  variant={on ? "outline" : "accent"}
                  disabled={!on && gated}
                  onClick={() => handleToggleStage(stage, on, gated)}
                >
                  {on ? t("stage.action.revert") : t("stage.action.release")}
                </Btn>
              </div>
            );
          })}
        </div>
        <div className="oc-actions">
          <Btn
            type="button"
            variant="accent"
            onClick={handleRunRefinement}
            disabled={running || !gsasAvailable}
            title={!gsasAvailable ? rt(lang, "recipe.gsasUnavailable") : undefined}
          >
            {running ? rt(lang, "recipe.running") : t("recipe.runRefinement")}
          </Btn>
          {/* No dedicated snapshot-creation endpoint exists in the v1 API
             contract (docs/design/gui-workbench/api-contract.md) — only
             POST /api/structure/apply creates one, as a side effect of
             applying a ReviseStructure edit. This control is a visual
             placeholder until a standalone endpoint is added. */}
          <Btn type="button" variant="outline">
            {t("recipe.snapshot")}
          </Btn>
        </div>
        {running && (
          <div className="oc-refine-status">
            {state.refine?.last_event && <span>{state.refine.last_event}</span>}
            {state.refine?.elapsed_s != null && <span>{Math.round(state.refine.elapsed_s)}s</span>}
          </div>
        )}
      </section>

      <section className="oc-approvals">
        <div className="oc-section-head">
          <span className="oc-section-head__title">{rt(lang, "modelActions.pendingTitle")}</span>
          <span className="oc-section-head__note">
            {rt(lang, "modelActions.openCountNote", { n: pendingApprovals.length })}
          </span>
        </div>
        {pendingApprovals.length === 0 ? (
          <div className="oc-approvals__empty">{rt(lang, "modelActions.empty")}</div>
        ) : (
          <div className="oc-approvals-list">
            {pendingApprovals.map((m) => (
              <TranscriptItem key={m.id} message={m} />
            ))}
          </div>
        )}
      </section>

      <section className="oc-review">
        <div className="oc-section-head">
          <span className="oc-section-head__title">{t("review.title")}</span>
          <span className="oc-section-head__note">
            {rt(lang, "review.openCountNote", { n: review.length })}
          </span>
        </div>
        <div className="oc-review-list">
          {review.map((item) => {
            // Local decision (this session's own resolve action) takes precedence
            // over the server-fetched state, but on a fresh page load there is no
            // local decision yet — item.state (from viewmodel.review[]) is then the
            // only source of truth, so a previously-resolved item still shows
            // ACCEPTED ✓ / SENT BACK instead of resetting to "pending" (§語彙,
            // review[].state: pending | accepted | sent_back).
            const decision =
              state.review[item.id] ?? (item.state !== "pending" ? item.state : undefined);
            const acceptLabel =
              decision === "accepted"
                ? t("review.accepted")
                : decision === "sent_back"
                  ? t("review.sentBack")
                  : rt(lang, "review.acceptPending");
            return (
              <div key={item.id} className="blueprint review-card">
                <div className="review-card__head">
                  <Chip variant={reviewSeverityChipVariant(item.severity)}>
                    {(() => {
                      const key = reviewSeverityLabelKey(item.severity);
                      // out-of-vocabulary severity → raw code, uppercased (§語彙)
                      return key === null ? item.severity.toUpperCase() : rt(lang, key);
                    })()}
                  </Chip>
                  <span className="review-card__title">{item.title}</span>
                  <span className="review-card__ref">{item.ref}</span>
                </div>
                <div className="review-card__detail">{item.detail}</div>
                <div className="review-card__actions">
                  <Btn
                    type="button"
                    variant={decision ? "outline" : "accent"}
                    disabled={!!decision}
                    onClick={() => handleReviewAction(item, "accept")}
                  >
                    {acceptLabel}
                  </Btn>
                  <Btn
                    type="button"
                    variant="outline"
                    disabled={!!decision}
                    onClick={() => handleReviewAction(item, "send_back")}
                  >
                    {t("review.sendBack")}
                  </Btn>
                  <button
                    type="button"
                    className="review-card__ledger-link"
                    onClick={() => dispatch({ type: "SET_TAB", tab: "ledger" })}
                  >
                    {t("review.ledgerLink")}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
