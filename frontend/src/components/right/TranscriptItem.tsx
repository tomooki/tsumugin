import { useRef, useState } from "react";
import { ApiError, postApproval, postMode } from "../../api/client";
import type { TranscriptMessage } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { Btn, Chip } from "../common";
import "./AgentSession.css";
import { approvalKind, formatBic, structureRevisionSiteCount, type ApprovalKind } from "./gates";
import { rt, type RightStringKey } from "./right.strings";

const KIND_BADGE_KEY: Record<ApprovalKind, RightStringKey> = {
  np: "modelAction.badge.np",
  sr: "modelAction.badge.sr",
  rv: "modelAction.badge.rv",
  pc: "modelAction.badge.pc",
  st: "modelAction.badge.st",
};

interface TranscriptItemProps {
  message: TranscriptMessage;
}

/** One transcript row, dispatched on TranscriptMessage.kind — handoff/
 * README.md §Right pane "AUTO body" lists the six kinds. */
export function TranscriptItem({ message }: TranscriptItemProps) {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  // 【approval の二重 approve/reject 対策 (レビュー指摘 #2 フロント側)】: `busy` は再レンダーで
  // ボタンを disabled にし待機中の mono 表示を出すための state。だが setState は非同期なので、
  // 同一 tick 内の連打 (dblClick 等、React が再レンダーを挟まずに 2 回ハンドラを呼ぶケース) は
  // state だけでは防げない — `inFlightRef` で同期的にガードする (両方揃えて初めて「1 回だけ
  // postApproval が飛ぶ」を保証できる)。バックエンド側 (session.py resolve_approval の
  // check-and-set マーカー) と対になる、フロント側の防御。
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const inFlightRef = useRef(false);

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
      const kindForBadge = approvalKind(message.action_id);

      // auto_applied (api-contract.md §エージェント権限モード): the server
      // already applied this ModelAction under agent_policy=auto/bypass — it
      // was never held for a human decision, so there is no APPROVE/REJECT
      // to offer. Rendering this before the disabled/label plumbing below
      // (which assumes a pending|approved|rejected card) keeps that logic
      // from having to reason about a fourth state it can never act on.
      if (decided === "auto_applied") {
        return (
          <div className="ts-approval ts-approval--auto">
            <div className="ts-approval__bar">
              <span className="ts-approval__kicker">{t("modelAction")}</span>
              {kindForBadge && (
                <Chip variant="inverted" className="ts-approval__kind">
                  {rt(lang, KIND_BADGE_KEY[kindForBadge])}
                </Chip>
              )}
              <Chip variant="inverted" className="ts-approval__auto-chip">
                {rt(lang, "agentPolicy.autoApplied.chip")}
              </Chip>
            </div>
            <div className="ts-approval__body">
              <div className="ts-approval__title">{message.title}</div>
              <div className="ts-approval__rationale">{message.rationale}</div>
              {message.action_json && <pre className="ts-approval__pre">{message.action_json}</pre>}
              <div className="ts-approval__state">{rt(lang, "agentPolicy.autoApplied.note")}</div>
            </div>
          </div>
        );
      }

      const disabled = decided !== "pending" || busy;
      const approveLabel = decided === "approved" ? t("chat.approval.applied") : t("chat.approval.approveApply");
      const rejectLabel = decided === "rejected" ? t("chat.approval.rejected") : t("chat.approval.reject");
      // Which propose_* kind this card is (gates.ts approvalKind) — null for
      // ids with no recognised np-/sr-/rv-/pc-/st- prefix, which is also the
      // pre-V3a "a1"-style fixture shape, so this must never throw on it.
      const kind = kindForBadge;
      const stateLine = busy
        ? rt(lang, "chat.approval.resolving")
        : conflict
          ? rt(lang, "chat.approval.conflict")
          : decided === "approved"
            ? kind
              ? rt(lang, `modelAction.state.applied.${kind}` as RightStringKey)
              : t("chat.approval.stateApplied")
            : decided === "rejected"
              ? kind
                ? rt(lang, `modelAction.state.rejected.${kind}` as RightStringKey)
                : t("chat.approval.stateRejected")
              : t("chat.approval.stateHeld");
      // sr- (propose_structure_revision) 1-line summary above the raw JSON —
      // task brief: "過剰にしない", so this is the only kind with a bespoke
      // summary line (its payload shape — a `sites` array — is the one case
      // where a plain count adds real signal over the pre).
      const siteCount = kind === "sr" ? structureRevisionSiteCount(message.action_json) : null;

      const decide = async (decision: "approve" | "reject") => {
        // `inFlightRef` is checked+set synchronously (unlike `busy`, a useState
        // value that only takes effect on the next render) so a second
        // invocation arriving before React re-renders — e.g. a fast
        // double-click, or an Enter-key repeat — can never slip through and
        // fire a second POST /api/approval/{action_id}.
        if (!message.action_id || inFlightRef.current) return;
        inFlightRef.current = true;
        setBusy(true);
        setConflict(false);
        try {
          const res = await postApproval(message.action_id, decision);
          dispatch({ type: "SET_APPROVAL", actionId: message.action_id, approval: res.state });
        } catch (err) {
          // 409 ("already resolved: <action_id>" / in-progress marker, see
          // session.py resolve_approval) means another resolution already
          // won the race — this is expected under concurrent clicks/tabs, not
          // an operator-facing failure, so it stays a local inline note
          // instead of going through the global SET_ERROR path.
          if (err instanceof ApiError && err.status === 409) {
            setConflict(true);
          } else {
            reportError(err, "failed to record approval");
          }
        } finally {
          inFlightRef.current = false;
          setBusy(false);
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
            {kind && (
              <Chip variant="inverted" className="ts-approval__kind">
                {rt(lang, KIND_BADGE_KEY[kind])}
              </Chip>
            )}
            <span className="ts-approval__not-apply">{t("proposalNotApply")}</span>
          </div>
          <div className="ts-approval__body">
            <div className="ts-approval__title">{message.title}</div>
            <div className="ts-approval__rationale">{message.rationale}</div>
            {siteCount !== null && (
              <div className="ts-approval__summary">
                {rt(lang, "modelAction.summary.sr", { n: siteCount })}
              </div>
            )}
            {message.action_json && <pre className="ts-approval__pre">{message.action_json}</pre>}
            <div className="ts-approval__actions">
              <Btn
                type="button"
                variant="accent"
                disabled={disabled}
                onClick={() => decide("approve")}
              >
                {approveLabel}
              </Btn>
              <Btn
                type="button"
                variant="outline"
                disabled={disabled}
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
