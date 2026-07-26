import { useCallback, useState } from "react";
import { ApiError, postAgentPolicy } from "../../api/client";
import type { AgentPolicy } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { Chip } from "../common";
import "./AgentPolicySegment.css";
import { rt, type RightStringKey } from "./right.strings";

const POLICIES: { key: AgentPolicy; labelKey: RightStringKey }[] = [
  { key: "approve", labelKey: "agentPolicy.segment.approve" },
  { key: "auto", labelKey: "agentPolicy.segment.auto" },
  { key: "bypass", labelKey: "agentPolicy.segment.bypass" },
];

// "approve" (the default) gets no chip — api-contract.md: "approve のとき
// はチップ無し (既定なので静か)".
const MODE_CHIP_KEY: Partial<Record<AgentPolicy, RightStringKey>> = {
  auto: "agentPolicy.modeChip.auto",
  bypass: "agentPolicy.modeChip.bypass",
};

/** AGENT SESSION header's 3-way permission segment (api-contract.md
 * §エージェント権限モード, V3a) — APPROVE (existing propose_* + human-approval
 * default) / AUTO (propose_* auto-applies) / BYPASS (also opens the project
 * lifecycle to the agent). Mirrors TitleBar's MANUAL/AUTO mode-toggle
 * pattern (segmented buttons, POST → SET_SHELL on success) at a smaller
 * scale for the 30px pane-head.
 *
 * Disabled while an agent turn is running (state.agentTurnRunning, synced by
 * AgentSession — see its doc comment) since the contract 409s a policy
 * change mid-turn. That flag can still lag a turn that started in the
 * instant between the last render and the click landing, so a 409 from the
 * request itself is also handled defensively as a non-fatal inline note
 * (mirrors TranscriptItem's approval-409 precedent) rather than the fatal
 * SET_ERROR path. */
export function AgentPolicySegment() {
  const { state, dispatch } = useStore();
  const { lang } = useI18n();
  const [pending, setPending] = useState(false);
  const [conflict, setConflict] = useState(false);

  const policy: AgentPolicy = state.shell?.agent.policy ?? "approve";
  const disabled = state.agentTurnRunning || pending;

  const handleSelect = useCallback(
    async (next: AgentPolicy) => {
      if (next === policy || disabled) return;
      setPending(true);
      setConflict(false);
      try {
        const shell = await postAgentPolicy(next);
        dispatch({ type: "SET_SHELL", shell });
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setConflict(true);
        } else {
          dispatch({
            type: "SET_ERROR",
            error: err instanceof ApiError ? err.message : "failed to switch agent policy",
          });
        }
      } finally {
        setPending(false);
      }
    },
    [policy, disabled, dispatch],
  );

  const modeChipKey = MODE_CHIP_KEY[policy];

  return (
    <div className="agent-policy-seg">
      <div className="agent-policy-seg__toggle blueprint">
        {POLICIES.map((p) => {
          const active = policy === p.key;
          return (
            <button
              key={p.key}
              type="button"
              className={`agent-policy-seg__btn${active ? " agent-policy-seg__btn--active" : ""}`}
              disabled={disabled}
              aria-pressed={active}
              onClick={() => handleSelect(p.key)}
            >
              {rt(lang, p.labelKey)}
            </button>
          );
        })}
      </div>
      {modeChipKey && (
        <Chip variant="inverted" className="agent-policy-seg__chip">
          {rt(lang, modeChipKey)}
        </Chip>
      )}
      {conflict && (
        <span className="agent-policy-seg__conflict">{rt(lang, "agentPolicy.conflict")}</span>
      )}
    </div>
  );
}
