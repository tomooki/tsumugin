import { ApiError, postApproval, postMode } from "../../api/client";
import type { TranscriptMessage } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { Btn, Chip } from "../common";
import "./AgentSession.css";
import { formatBic } from "./gates";
import { rt } from "./right.strings";

interface TranscriptItemProps {
  message: TranscriptMessage;
}

/** One transcript row, dispatched on TranscriptMessage.kind — handoff/
 * README.md §Right pane "AUTO body" lists the six kinds. */
export function TranscriptItem({ message }: TranscriptItemProps) {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();

  const reportError = (err: unknown, fallback: string) => {
    dispatch({ type: "SET_ERROR", error: err instanceof ApiError ? err.message : fallback });
  };

  switch (message.kind) {
    case "user":
      return (
        <div className="ts-user-row">
          <div className="ts-user-bubble">{message.text}</div>
        </div>
      );

    case "agent":
      return (
        <div className="ts-agent">
          <span className="ts-agent__who">{t("chat.agentLabel")}</span>
          <span className="ts-agent__text">{message.text}</span>
        </div>
      );

    case "tool": {
      const open = !!state.open[message.id];
      return (
        <div className="ts-tool">
          <button
            type="button"
            className="ts-tool__head"
            onClick={() => dispatch({ type: "TOGGLE_OPEN", id: message.id })}
          >
            <span className="ts-tool__caret">{open ? "▾" : "▸"}</span>
            <span className="ts-tool__name">{message.tool}</span>
            <span className="ts-tool__layer">{message.layer}</span>
            <span className="ts-tool__secs">
              {message.secs !== undefined ? `${message.secs.toFixed(1)} s` : ""}
            </span>
          </button>
          {open && (
            <div className="ts-tool__body">
              <div>
                <div className="ts-tool__label">{t("args")}</div>
                <pre className="ts-tool__pre">{message.args}</pre>
              </div>
              <div>
                <div className="ts-tool__label">{t("ret")}</div>
                <pre className="ts-tool__pre">{message.ret}</pre>
              </div>
              <div className="ts-tool__reach">{t("reachability")}</div>
            </div>
          )}
        </div>
      );
    }

    case "judgement":
      return (
        <div className="blueprint ts-judgement">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          <div className="ts-judgement__head">
            <span className="ts-judgement__kicker">{t("judgement")}</span>
            {message.title && <span className="ts-judgement__title">{message.title}</span>}
          </div>
          <div className="ts-judgement__rows">
            {(message.rows ?? []).map((row, i) => (
              <div key={`${row.label}-${i}`} className="ts-judgement__row">
                <span>{row.label}</span>
                <span
                  className={`ts-judgement__value${row.chosen ? " ts-judgement__value--chosen" : ""}`}
                >
                  Rwp {row.rwp} · bic {formatBic(row.bic)}
                </span>
              </div>
            ))}
          </div>
          {message.text && <div className="ts-judgement__text">{message.text}</div>}
        </div>
      );

    case "approval": {
      // Per-action_id: state.approval is keyed by action_id (see state/types.ts)
      // so resolving one ModelAction card never leaks its decision into another
      // pending card that happens to render at the same time.
      const localDecision = message.action_id ? state.approval[message.action_id] : undefined;
      const decided = localDecision ?? message.state ?? "pending";
      const approveLabel = decided === "approved" ? t("chat.approval.applied") : t("chat.approval.approveApply");
      const rejectLabel = decided === "rejected" ? t("chat.approval.rejected") : t("chat.approval.reject");
      const stateLine =
        decided === "approved"
          ? t("chat.approval.stateApplied")
          : decided === "rejected"
            ? t("chat.approval.stateRejected")
            : t("chat.approval.stateHeld");

      const decide = async (decision: "approve" | "reject") => {
        if (!message.action_id) return;
        try {
          const res = await postApproval(message.action_id, decision);
          dispatch({ type: "SET_APPROVAL", actionId: message.action_id, approval: res.state });
        } catch (err) {
          reportError(err, "failed to record approval");
        }
      };

      const inspect = async () => {
        try {
          const shell = await postMode("manual");
          dispatch({ type: "SET_SHELL", shell });
          dispatch({ type: "SET_TAB", tab: "pid" });
        } catch (err) {
          reportError(err, "failed to switch mode");
        }
      };

      return (
        <div className="ts-approval">
          <div className="ts-approval__bar">
            <span className="ts-approval__kicker">{t("modelAction")}</span>
            <span className="ts-approval__not-apply">{t("proposalNotApply")}</span>
          </div>
          <div className="ts-approval__body">
            <div className="ts-approval__title">{message.title}</div>
            <div className="ts-approval__rationale">{message.rationale}</div>
            {message.action_json && <pre className="ts-approval__pre">{message.action_json}</pre>}
            <div className="ts-approval__actions">
              <Btn
                type="button"
                variant="accent"
                disabled={decided !== "pending"}
                onClick={() => decide("approve")}
              >
                {approveLabel}
              </Btn>
              <Btn
                type="button"
                variant="outline"
                disabled={decided !== "pending"}
                onClick={() => decide("reject")}
              >
                {rejectLabel}
              </Btn>
              <button type="button" className="ts-approval__inspect" onClick={inspect}>
                {t("inspectManual")}
              </button>
            </div>
            <div className="ts-approval__state">{stateLine}</div>
          </div>
        </div>
      );
    }

    case "escalation":
      return (
        <div className="ts-escalation">
          <span className="ts-escalation__rule" />
          <span>
            <span className="ts-escalation__head">
              <Chip variant="inverted">
                {rt(lang, "escalationLabel")}
                {message.fr ? ` · ${message.fr}` : ""}
              </Chip>
              {message.title && <span className="ts-escalation__title">{message.title}</span>}
            </span>
            {message.text && <span className="ts-escalation__text">{message.text}</span>}
          </span>
        </div>
      );

    default:
      return null;
  }
}
