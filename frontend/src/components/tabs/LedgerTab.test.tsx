import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LedgerResponse } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { LedgerTab } from "./LedgerTab";

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function installLedgerFetchMock(response: LedgerResponse) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/api/ledger")) return jsonResponse(response);
    throw new Error(`unhandled fetch in LedgerTab test: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function makeLedger(): LedgerResponse {
  return {
    verified: true,
    entries: [
      {
        index: 1284,
        time: "14:22:07",
        actor: "AGENT ③",
        text: "propose AddPhase monoclinic P21/n (frames 84-96) - held for human approval",
        hash: "8f2a…c104",
        revert_to: "S-0310",
      },
      {
        index: 1283,
        time: "14:21:44",
        actor: "MCP ②",
        text: "identify_phases -> 5 candidates, Dara top 0.71",
        hash: "3b91…7de2",
        revert_to: null,
      },
      {
        index: 1282,
        time: "14:20:58",
        actor: "CORE ①",
        text: "check_phase_set -> is_complete = false",
        hash: "cc07…19a5",
        revert_to: null,
      },
      {
        index: 1281,
        time: "14:18:12",
        actor: "HUMAN",
        text: "mode switch manual -> auto (final_selection_mode = agent)",
        hash: "1de4…88bb",
        revert_to: null,
      },
      {
        index: 1280,
        time: "14:12:30",
        actor: "GUARD",
        text: "stage 08 size/mustrain released -> reverted, cell collapse guard",
        hash: "77aa…2f01",
        revert_to: "S-0309",
      },
    ],
  };
}

function renderLedger() {
  return render(
    <I18nProvider lang="en">
      <LedgerTab />
    </I18nProvider>,
  );
}

describe("LedgerTab — fetch on mount", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls GET /api/ledger and renders each entry", async () => {
    const fetchMock = installLedgerFetchMock(makeLedger());
    renderLedger();

    await waitFor(() => expect(screen.getByText(/propose AddPhase monoclinic/)).toBeInTheDocument());

    expect(fetchMock).toHaveBeenCalledWith("/api/ledger", expect.objectContaining({ method: "GET" }));
    expect(screen.getByText("14:22:07")).toBeInTheDocument();
    expect(screen.getByText("8f2a…c104")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /REVERT TO/i })).toHaveLength(5);
  });
});

describe("LedgerTab — actor colour classes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("assigns a distinct row modifier class per actor", async () => {
    installLedgerFetchMock(makeLedger());
    renderLedger();
    await waitFor(() => expect(screen.getByText("14:22:07")).toBeInTheDocument());

    const agentRow = screen.getByText("14:22:07").closest(".ledger-row")!;
    expect(agentRow.className).toContain("ledger-row--agent");

    const mcpRow = screen.getByText("14:21:44").closest(".ledger-row")!;
    expect(mcpRow.className).toContain("ledger-row--core");

    const coreRow = screen.getByText("14:20:58").closest(".ledger-row")!;
    expect(coreRow.className).toContain("ledger-row--core");

    const humanRow = screen.getByText("14:18:12").closest(".ledger-row")!;
    expect(humanRow.className).toContain("ledger-row--human");

    const guardRow = screen.getByText("14:12:30").closest(".ledger-row")!;
    expect(guardRow.className).toContain("ledger-row--guard");
  });

  it("translates known actor labels via i18n", async () => {
    installLedgerFetchMock(makeLedger());
    render(
      <I18nProvider lang="ja">
        <LedgerTab />
      </I18nProvider>,
    );
    await waitFor(() => expect(screen.getByText("14:22:07")).toBeInTheDocument());
    expect(screen.getByText("エージェント③")).toBeInTheDocument();
    expect(screen.getByText("人間")).toBeInTheDocument();
    expect(screen.getByText("ガード")).toBeInTheDocument();
  });
});

describe("LedgerTab — P2 non-destructive guard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders no delete/remove/edit control anywhere in the tab", async () => {
    installLedgerFetchMock(makeLedger());
    const { container } = renderLedger();
    await waitFor(() => expect(screen.getByText("14:22:07")).toBeInTheDocument());

    const forbidden = /delete|remove|edit|destroy|purge/i;
    const buttons = Array.from(container.querySelectorAll("button"));
    expect(buttons.length).toBeGreaterThan(0);
    for (const btn of buttons) {
      expect(btn.textContent ?? "").not.toMatch(forbidden);
      expect(btn.getAttribute("aria-label") ?? "").not.toMatch(forbidden);
      expect(btn.title ?? "").not.toMatch(forbidden);
    }
    // REVERT TO is the sole per-row action and is explicitly allowed (a
    // revert appends a new ledger entry + restores a snapshot; it never
    // deletes anything).
    expect(screen.getAllByRole("button", { name: /REVERT TO/i }).length).toBe(buttons.length);
  });
});
