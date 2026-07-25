import { useCallback } from "react";
import { ApiError, postTranscriptMessage } from "../../api/client";
import { useI18n } from "../../i18n";
import type { StringKey } from "../../i18n/strings";
import { useStore } from "../../state/store";
import { Btn } from "../common";
import "./AgentSession.css";
import { formatTokens, formatWallTime } from "./gates";
import { TranscriptItem } from "./TranscriptItem";

const QUICK_PROMPT_KEYS: readonly StringKey[] = [
  "quickPrompt.stage08",
  "quickPrompt.compare",
  "quickPrompt.discriminating",
];

/** AUTO right-pane body — handoff/README.md §Right pane "AUTO body":
 * tokens/wall-time strip, transcript (user/agent/tool/judgement/approval/
 * escalation — see TranscriptItem), composer with quick-prompt chips. */
export function AgentSession() {
  const { state, dispatch } = useStore();
  const { t } = useI18n();
  const vm = state.viewModel;
  const transcript = vm?.transcript ?? [];
  const tokens = state.shell?.agent.tokens ?? 0;
  const wallTimeS = state.shell?.agent.wall_time_s ?? 0;

  const handleSend = useCallback(async () => {
    const text = state.draft.trim();
    if (!text) return;
    try {
      const res = await postTranscriptMessage(text);
      dispatch({ type: "SET_DRAFT", draft: "" });
      // transcript-only append — SET_VIEW_MODEL would resync stageOn from this
      // stale (non-refetched) viewModel and undo optimistic stage toggles.
      dispatch({ type: "APPEND_TRANSCRIPT_MESSAGE", message: res.message });
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        error: err instanceof ApiError ? err.message : "failed to send message",
      });
    }
  }, [dispatch, state.draft, vm]);

  return (
    <div className="agent-session">
      <div className="agent-session__budget">
        <div className="budget-cell">
          <div className="budget-cell__label">{t("budget.tokens")}</div>
          <div className="budget-cell__value">{formatTokens(tokens)}</div>
        </div>
        <div className="budget-cell">
          <div className="budget-cell__label">{t("budget.wallTime")}</div>
          <div className="budget-cell__value">{formatWallTime(wallTimeS)}</div>
        </div>
      </div>

      <div className="agent-session__transcript tg-scroll">
        {transcript.map((m) => (
          <TranscriptItem key={m.id} message={m} />
        ))}
      </div>

      <div className="agent-session__composer">
        <div className="composer__chips">
          {QUICK_PROMPT_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className="composer__chip"
              onClick={() => dispatch({ type: "SET_DRAFT", draft: t(key) })}
            >
              {t(key)}
            </button>
          ))}
        </div>
        <div className="composer__row">
          <textarea
            className="composer__input"
            value={state.draft}
            placeholder={t("draft.placeholder")}
            onChange={(e) => dispatch({ type: "SET_DRAFT", draft: e.target.value })}
          />
          <Btn type="button" variant="accent" onClick={handleSend}>
            {t("send")}
          </Btn>
        </div>
        <div className="composer__note">{t("composerNote")}</div>
      </div>
    </div>
  );
}
