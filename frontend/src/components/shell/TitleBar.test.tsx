import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ShellState } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import { TitleBar } from "./TitleBar";

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: { name: "p", dataset: "d", frame: "fr000", echem: null },
    mode: "auto",
    final_selection_mode: "agent",
    ledger: { count: 12, verified: true },
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 36, gsas_available: true },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    ...overrides,
  };
}

function renderBar(shell: ShellState) {
  return render(
    <StoreProvider initialState={{ shell, mode: shell.mode }}>
      <I18nProvider lang="en">
        <TitleBar onModeChange={() => {}} />
      </I18nProvider>
    </StoreProvider>,
  );
}

describe("TitleBar — chips report real state, never a fixed label", () => {
  it("reports a BROKEN hash chain when the server says the ledger does not verify", () => {
    // 恒久ガード: プロトタイプはここに "ledger.verify() = TRUE" を固定で書いていた。
    // 改竄検知が売りの追記専用台帳で、壊れていても TRUE と表示するのは最悪の嘘。
    renderBar(makeShell({ ledger: { count: 12, verified: false } }));
    expect(screen.getByText(/ledger\.verify\(\) = FALSE/)).toBeInTheDocument();
    expect(screen.queryByText(/ledger\.verify\(\) = TRUE/)).not.toBeInTheDocument();
  });

  it("reports TRUE when the chain does verify", () => {
    renderBar(makeShell());
    expect(screen.getByText(/ledger\.verify\(\) = TRUE/)).toBeInTheDocument();
  });

  it("shows the agent's measured token / wall-time usage, not a fixed number", () => {
    // FR-404: 表示するのは実測のトークンと経過時間だけ (金額は出さない)。
    renderBar(
      makeShell({ agent: { tokens: 12345, wall_time_s: 120, idle: false }, mode: "auto" }),
    );
    expect(screen.getByText(/12,345 tok/)).toBeInTheDocument();
    expect(screen.getByText(/2 m/)).toBeInTheDocument();
    expect(screen.queryByText(/1\.24 M tok/)).not.toBeInTheDocument();
  });
});
