import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  getAgentStatus,
  getViewModel,
  isAgentStartedResponse,
  postTranscriptMessage,
} from "../../api/client";
import type { AgentJobStatus } from "../../api/types";
import { useI18n } from "../../i18n";
import type { StringKey } from "../../i18n/strings";
import { useStore } from "../../state/store";
import { Btn, Chip } from "../common";
import "./AgentSession.css";
import { formatTokens, formatWallTime } from "./gates";
import { rt } from "./right.strings";
import { TranscriptItem } from "./TranscriptItem";

const QUICK_PROMPT_KEYS: readonly StringKey[] = [
  "quickPrompt.stage08",
  "quickPrompt.compare",
  "quickPrompt.discriminating",
];

const AGENT_POLL_MS = 2000;

/** AUTO right-pane body — handoff/README.md §Right pane "AUTO body":
 * tokens/wall-time strip, transcript (user/agent/tool/judgement/approval/
 * escalation — see TranscriptItem), composer with quick-prompt chips.
 *
 * V3a (api-contract.md §AUTO 実 LLM ブリッジ): SEND now has two outcomes.
 * mode=auto + the local `claude` CLI bridge available ⇒ POST
 * /api/transcript/message returns 202 {"status": "agent_started"} and the
 * agent session runs asynchronously — this component then polls GET
 * /api/agent/status every 2s (agentTurn below) and, while still "running",
 * refetches the viewmodel so the transcript grows in place. Any other
 * outcome (demo mode, manual-in-practice, or the bridge unavailable) keeps
 * the pre-V3a behaviour: 200 {"message"} is appended to the transcript
 * directly, no polling.
 *
 * This poll loop is intentionally NOT hooks/usePollJob.ts: that hook is
 * typed to RefineStatus's "idle" | "running" | "done" | "failed" vocabulary
 * and only re-fetches on the *terminal* "done" tick. AgentJobStatus has no
 * "done" state (a turn just returns to "idle") and the contract calls for a
 * refetch on *every* "running" tick, not just the last one — shoehorning
 * that through usePollJob's onDone-only contract would need more machinery
 * than this local effect. agentTurn is local component state (not the global
 * store's `state.refine`/`activeJob` slot) because the agent bridge is its
 * own independent job lane, not a fourth kind sharing the GSAS job slot. */
export function AgentSession() {
  const { state, dispatch } = useStore();
  const { t, lang } = useI18n();
  const vm = state.viewModel;
  const transcript = vm?.transcript ?? [];

  // null = no agent turn started this session yet — display falls back to
  // the shell-seeded values (state.shell.agent), matching the pre-V3a strip.
  const [agentTurn, setAgentTurn] = useState<AgentJobStatus | null>(null);

  const running = agentTurn?.status === "running";
  const failed = agentTurn?.status === "failed";
  // `available` defaults to true when neither the live poll nor the shell
  // snapshot has an opinion (older server predating this field) — mirrors
  // the existing gsasAvailable / status.gsas_available precedent in
  // OperatorConsole.tsx rather than spuriously disabling SEND.
  const available = agentTurn?.available ?? state.shell?.agent.available ?? true;
  const tokens = agentTurn?.tokens ?? state.shell?.agent.tokens ?? 0;
  const wallTimeS = agentTurn?.wall_time_s ?? state.shell?.agent.wall_time_s ?? 0;

  const handleSend = useCallback(async () => {
    const text = state.draft.trim();
    if (!text) return;
    // Runtime guard (not just the SEND button's `disabled` attribute below):
    // proves the gate is real rather than cosmetic — a disabled DOM button
    // never dispatches a click in the first place, so this is the line a
    // mutation test actually exercises (see AgentSession.test.tsx "available
    // === false blocks the network call, not just the button").
    if (!available || running) return;
    try {
      const res = await postTranscriptMessage(text);
      dispatch({ type: "SET_DRAFT", draft: "" });
      if (isAgentStartedResponse(res)) {
        // Optimistic "running" so the composer disables immediately, without
        // waiting for the first 2s poll tick — carries forward whatever
        // tokens/wall_time_s/available this session already knew about.
        setAgentTurn((prev) => ({
          status: "running",
          available: prev?.available ?? available,
          tokens: prev?.tokens ?? tokens,
          wall_time_s: prev?.wall_time_s ?? wallTimeS,
          error: null,
        }));
      } else {
        // transcript-only append — SET_VIEW_MODEL would resync stageOn from this
        // stale (non-refetched) viewModel and undo optimistic stage toggles.
        dispatch({ type: "APPEND_TRANSCRIPT_MESSAGE", message: res.message });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // A turn is already running (elsewhere, or a stale local state after
        // a reload) — this is expected under a slow double-send, not an
        // operator-facing failure, so start polling instead of a fatal error.
        setAgentTurn(
          (prev) => prev ?? { status: "running", available, tokens, wall_time_s: wallTimeS, error: null },
        );
        return;
      }
      dispatch({
        type: "SET_ERROR",
        error: err instanceof ApiError ? err.message : "failed to send message",
      });
    }
  }, [dispatch, state.draft, available, running, tokens, wallTimeS]);

  // Poll loop: only armed while an agent turn is running. Every tick fetches
  // the agent status and, while it's still "running", refetches the
  // viewmodel too (api-contract.md: "フロントは running 中 2s で viewmodel
  // を再フェッチ") so the transcript grows in place as the agent appends
  // agent/tool messages server-side.
  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getAgentStatus();
        if (cancelled) return;
        setAgentTurn(status);
        if (status.status === "running") {
          try {
            const viewModel = await getViewModel();
            if (!cancelled) dispatch({ type: "SET_VIEW_MODEL", viewModel });
          } catch {
            // Best-effort transcript refetch — a transient failure here
            // should not stop the status poll from noticing idle/failed on
            // the next tick (mirrors usePollJob's tick isolation).
          }
        }
      } catch (err) {
        if (!cancelled) {
          dispatch({
            type: "SET_ERROR",
            error: err instanceof ApiError ? err.message : "failed to poll agent status",
          });
        }
      }
    };
    const id = setInterval(() => {
      tick();
    }, AGENT_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [running, dispatch]);

  const footerNote = running
    ? rt(lang, "agent.running", { tokens: formatTokens(tokens), elapsed: formatWallTime(wallTimeS) })
    : failed
      ? rt(lang, "agent.failed", { detail: agentTurn?.error ? `: ${agentTurn.error}` : "" })
      : rt(lang, "composer.note.real");

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
        {!available && (
          <div className="composer__availability">
            <Chip variant="inverted">{rt(lang, "agent.unavailable.chip")}</Chip>
          </div>
        )}
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
          <Btn type="button" variant="accent" onClick={handleSend} disabled={running || !available}>
            {t("send")}
          </Btn>
        </div>
        <div className="composer__note">{footerNote}</div>
      </div>
    </div>
  );
}
