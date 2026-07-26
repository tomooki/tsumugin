import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentPolicy, ShellState } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider, useStore } from "../../state/store";
import type { WorkbenchState } from "../../state/types";
import { AgentPolicySegment } from "./AgentPolicySegment";

function makeShell(policy?: AgentPolicy): ShellState {
  return {
    project: { name: "p", dataset: "d", frame: "fr001", echem: null },
    mode: "auto",
    final_selection_mode: "agent",
    ledger: { count: 1, verified: true },
    status: { backend_build: "x", seed: 0, mcp_tools: 36, gsas_available: true },
    agent: { tokens: 100, wall_time_s: 10, idle: true, available: true, policy },
  };
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

/** Exposes state.shell.agent.policy / state.error as text nodes so tests can
 * assert on the SET_SHELL/SET_ERROR side effects that the segment itself
 * doesn't fully render (mirrors AgentSession.test.tsx's DebugState). */
function DebugState() {
  const { state } = useStore();
  return (
    <>
      <span data-testid="debug-policy">{state.shell?.agent.policy ?? ""}</span>
      <span data-testid="debug-error">{state.error ?? ""}</span>
    </>
  );
}

function renderSegment(initialState: Partial<WorkbenchState>) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider lang="en">
        <StoreProvider initialState={{ shell: makeShell("approve"), ...initialState }}>
          {children}
        </StoreProvider>
      </I18nProvider>
    );
  }
  return render(
    <>
      <AgentPolicySegment />
      <DebugState />
    </>,
    { wrapper: Wrapper },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AgentPolicySegment — segment buttons", () => {
  it("renders APPROVE / AUTO / BYPASS and marks the current policy active", () => {
    renderSegment({ shell: makeShell("approve") });
    expect(screen.getByRole("button", { name: "APPROVE" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "AUTO" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "BYPASS" })).toHaveAttribute("aria-pressed", "false");
  });

  it("defaults to approve (active) when shell.agent.policy is omitted (pre-V3a fixture)", () => {
    renderSegment({ shell: makeShell(undefined) });
    expect(screen.getByRole("button", { name: "APPROVE" })).toHaveAttribute("aria-pressed", "true");
  });
});

// The mode chip's text ("BYPASS") collides with the segment button of the
// same name (both are contract-mandated literal strings — api-contract.md
// §エージェント権限モード), so these assertions target the chip element
// specifically (`.agent-policy-seg__chip`) rather than screen.getByText,
// which would ambiguously match the button too.
describe("AgentPolicySegment — mode chip (approve is quiet, auto/bypass are not)", () => {
  it("shows no chip for approve", () => {
    const { container } = renderSegment({ shell: makeShell("approve") });
    expect(container.querySelector(".agent-policy-seg__chip")).toBeNull();
  });

  it("shows AUTO-APPLY for auto", () => {
    const { container } = renderSegment({ shell: makeShell("auto") });
    const chip = container.querySelector(".agent-policy-seg__chip");
    expect(chip).not.toBeNull();
    expect(chip).toHaveTextContent("AUTO-APPLY");
  });

  it("shows BYPASS for bypass", () => {
    const { container } = renderSegment({ shell: makeShell("bypass") });
    const chip = container.querySelector(".agent-policy-seg__chip");
    expect(chip).not.toBeNull();
    expect(chip).toHaveTextContent("BYPASS");
  });
});

describe("AgentPolicySegment — selecting a policy", () => {
  it("clicking AUTO calls postAgentPolicy and dispatches SET_SHELL with the response", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/agent/policy")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as { policy: AgentPolicy };
        expect(body).toEqual({ policy: "auto" });
        return jsonResponse(makeShell("auto"));
      }
      throw new Error(`unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSegment({ shell: makeShell("approve") });
    fireEvent.click(screen.getByRole("button", { name: "AUTO" }));

    await waitFor(() => expect(screen.getByTestId("debug-policy").textContent).toBe("auto"));
    await waitFor(() => expect(screen.getByText("AUTO-APPLY")).toBeInTheDocument());
    expect(screen.getByTestId("debug-error").textContent).toBe("");
  });

  it("clicking the already-active policy is a no-op (no network call)", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderSegment({ shell: makeShell("approve") });
    fireEvent.click(screen.getByRole("button", { name: "APPROVE" }));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a 422 (invalid policy) surfaces through the fatal SET_ERROR path", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({ error: "invalid policy: bogus", error_type: "ValidationError" }),
    })) as unknown as typeof fetch;
    vi.stubGlobal("fetch", fetchMock);

    renderSegment({ shell: makeShell("approve") });
    fireEvent.click(screen.getByRole("button", { name: "AUTO" }));

    await waitFor(() =>
      expect(screen.getByTestId("debug-error").textContent).toBe("invalid policy: bogus"),
    );
  });

  it("a 409 (turn just started) shows a non-fatal inline note instead of the fatal error path", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ error: "agent turn already running", error_type: "ConflictError" }),
    })) as unknown as typeof fetch;
    vi.stubGlobal("fetch", fetchMock);

    renderSegment({ shell: makeShell("approve") });
    fireEvent.click(screen.getByRole("button", { name: "AUTO" }));

    await waitFor(() =>
      expect(
        screen.getByText("a turn is in progress · try again once it finishes"),
      ).toBeInTheDocument(),
    );
    // non-fatal: stays out of the global/fatal error path.
    expect(screen.getByTestId("debug-error").textContent).toBe("");
  });
});

// Mutation-provable guard (task brief: "変異実証 1 件以上"): this proves the
// `disabled={state.agentTurnRunning || pending}` wiring is load-bearing, not
// cosmetic — a disabled DOM button never dispatches a click in the first
// place, so removing `state.agentTurnRunning` from that expression would
// make this assertion fail (the button would be enabled and the click below
// would reach fetch).
describe("AgentPolicySegment — disabled while an agent turn is running", () => {
  it("state.agentTurnRunning === true disables all three buttons and blocks the network call", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderSegment({ shell: makeShell("approve"), agentTurnRunning: true });

    expect(screen.getByRole("button", { name: "APPROVE" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "AUTO" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "BYPASS" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "AUTO" }));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("state.agentTurnRunning === false (default) leaves the segment enabled", () => {
    renderSegment({ shell: makeShell("approve") });
    expect(screen.getByRole("button", { name: "AUTO" })).not.toBeDisabled();
  });
});
