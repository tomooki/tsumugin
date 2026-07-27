import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ShellState } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import { SettingsModal } from "./SettingsModal";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

function makeShell(overrides: Partial<ShellState> = {}): ShellState {
  return {
    project: { name: "p", dataset: "d", frame: "f", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 1, verified: true },
    status: { backend_build: "b", seed: 0, mcp_tools: 36, gsas_available: true, mp_available: true },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    ...overrides,
  };
}

interface MockOptions {
  settingsSequence?: unknown[];
  saveFails?: { status: number; body: unknown };
  clearFails?: { status: number; body: unknown };
  shell?: ShellState;
}

function installFetchMock(opts: MockOptions = {}) {
  let settingsCallIndex = 0;
  const sequence = opts.settingsSequence ?? [
    { mp_api_key_set: false, mp_api_key_hint: null, mp_api_key_source: null },
  ];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/settings") && method === "GET") {
      const body = sequence[Math.min(settingsCallIndex, sequence.length - 1)];
      settingsCallIndex += 1;
      return jsonResponse(body);
    }
    if (url.endsWith("/api/settings") && method === "POST") {
      if (opts.saveFails) return jsonResponse(opts.saveFails.body, false, opts.saveFails.status);
      return jsonResponse({});
    }
    if (url.endsWith("/api/settings/clear") && method === "POST") {
      if (opts.clearFails) return jsonResponse(opts.clearFails.body, false, opts.clearFails.status);
      return jsonResponse({});
    }
    if (url.endsWith("/api/state") && method === "GET") {
      return jsonResponse(opts.shell ?? makeShell());
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderModal(onClose: () => void, opts: MockOptions = {}) {
  const fetchMock = installFetchMock(opts);
  render(
    <StoreProvider>
      <I18nProvider lang="en">
        <SettingsModal onClose={onClose} />
      </I18nProvider>
    </StoreProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingsModal — GET masked status, 3 patterns", () => {
  it("shows the settings-file status with the masked hint", async () => {
    renderModal(() => {}, {
      settingsSequence: [
        { mp_api_key_set: true, mp_api_key_hint: "ab12", mp_api_key_source: "settings" },
      ],
    });
    await waitFor(() => expect(screen.getByText("set · …ab12 (settings)")).toBeInTheDocument());
    expect(screen.queryByText(/environment variable is already set/)).not.toBeInTheDocument();
  });

  it("shows the env-detected status and the env note", async () => {
    renderModal(() => {}, {
      settingsSequence: [{ mp_api_key_set: true, mp_api_key_hint: null, mp_api_key_source: "env" }],
    });
    await waitFor(() => expect(screen.getByText("detected from environment (env)")).toBeInTheDocument());
    expect(screen.getByText(/environment variable is already set/)).toBeInTheDocument();
  });

  it("shows not-set when no key is configured anywhere", async () => {
    renderModal(() => {}, {
      settingsSequence: [{ mp_api_key_set: false, mp_api_key_hint: null, mp_api_key_source: null }],
    });
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());
  });
});

describe("SettingsModal — SAVE", () => {
  it("posts the typed token, refetches settings + state, and clears the input", async () => {
    const user = userEvent.setup();
    const fetchMock = renderModal(() => {}, {
      settingsSequence: [
        { mp_api_key_set: false, mp_api_key_hint: null, mp_api_key_source: null },
        { mp_api_key_set: true, mp_api_key_hint: "cd34", mp_api_key_source: "settings" },
      ],
    });
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());

    const input = screen.getByLabelText("API token") as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.type(input, "sekret-token-value");
    await user.click(screen.getByRole("button", { name: "SAVE" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, init]) => String(u).endsWith("/api/settings") && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
        mp_api_key: "sekret-token-value",
      });
    });

    // — mutation-proof assertion: the input must be empty again after a
    // successful save (the token must not linger on screen — 絶対規則) —
    await waitFor(() => expect(input.value).toBe(""));
    await waitFor(() => expect(screen.getByText("set · …cd34 (settings)")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/state"))).toBe(true);
  });

  it("SAVE is disabled while the input is empty", async () => {
    renderModal(() => {});
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "SAVE" })).toBeDisabled();
  });

  it("shows the server error message on a failed save and does not lose the busy state permanently", async () => {
    const user = userEvent.setup();
    renderModal(() => {}, {
      saveFails: { status: 422, body: { error: "token rejected", error_type: "invalid" } },
    });
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());

    await user.type(screen.getByLabelText("API token"), "bad-token");
    await user.click(screen.getByRole("button", { name: "SAVE" }));

    await waitFor(() => expect(screen.getByText(/token rejected/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "SAVE" })).not.toBeDisabled();
  });
});

describe("SettingsModal — CLEAR", () => {
  it("posts {key: mp_api_key} and refetches", async () => {
    const user = userEvent.setup();
    const fetchMock = renderModal(() => {}, {
      settingsSequence: [
        { mp_api_key_set: true, mp_api_key_hint: "ab12", mp_api_key_source: "settings" },
        { mp_api_key_set: false, mp_api_key_hint: null, mp_api_key_source: null },
      ],
    });
    await waitFor(() => expect(screen.getByText("set · …ab12 (settings)")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "CLEAR" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/settings/clear"));
      expect(call).toBeDefined();
      expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({ key: "mp_api_key" });
    });
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());
  });
});

describe("SettingsModal — close affordances", () => {
  it("calls onClose when the backdrop is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderModal(onClose);
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());

    await user.click(screen.getByRole("presentation"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when clicking inside the dialog", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderModal(onClose);
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());

    await user.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderModal(onClose);
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when CLOSE is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderModal(onClose);
    await waitFor(() => expect(screen.getByText("not set")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "CLOSE" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
