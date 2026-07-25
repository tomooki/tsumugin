import { useCallback } from "react";
import { ApiError, postRefine, postReviewResolve, postStage } from "../../api/client";
import type { ReviewItem, StageRow } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { Btn, Chip } from "../common";
import "./OperatorConsole.css";
import { isStageGateOpen, reviewSeverityChipVariant, reviewSeverityLabelKey } from "./gates";
import { rt } from "./right.strings";

/** MANUAL right-pane body — handoff/README.md §Right pane "MANUAL body":
 * STAGED RELEASE RECIPE (gated by PARAMETERS/STRUCTURE) + RUN
 * REFINEMENT/SNAPSHOT + REVIEW QUEUE (FR-421/423). Gating is derived, never
 * server-supplied — see gates.ts `isStageGateOpen`. */
export function OperatorConsole() {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  const vm = state.viewModel;
  const stages: StageRow[] = vm?.stages ?? [];
  const review: ReviewItem[] = vm?.review ?? [];

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

  const handleRunRefinement = useCallback(() => {
    postRefine().catch((err: unknown) => reportError(err, "failed to run refinement"));
  }, [reportError]);

  const handleReviewAction = useCallback(
    async (item: ReviewItem, action: "accept" | "send_back") => {
      try {
        await postReviewResolve(item.id, { action, note: "" });
        dispatch({ type: "SET_REVIEW", id: item.id, decision: action === "accept" ? "accepted" : "sent" });
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
          <Btn type="button" variant="accent" onClick={handleRunRefinement}>
            {t("recipe.runRefinement")}
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
            const decision = state.review[item.id] ?? (item.state !== "pending" ? item.state : undefined);
            const acceptLabel =
              decision === "accepted"
                ? t("review.accepted")
                : decision === "sent"
                  ? t("review.sentBack")
                  : rt(lang, "review.acceptPending");
            return (
              <div key={item.id} className="blueprint review-card">
                <i className="corner tl" />
                <i className="corner tr" />
                <i className="corner bl" />
                <i className="corner br" />
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
