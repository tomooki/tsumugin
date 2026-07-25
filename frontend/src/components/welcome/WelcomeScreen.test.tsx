import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n";
import { WelcomeScreen } from "./WelcomeScreen";

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function errorResponse(status: number, body: unknown): Response {
  return { ok: false, status, statusText: "error", json: async () => body } as Response;
}

interface MockOptions {
  recent?: { name: string; path: string; last_opened: string }[];
  createFails?: boolean;
  openFails?: boolean;
}

function installFetchMock(opts: MockOptions = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";

    if (url.endsWith("/api/project/recent") && method === "GET") {
      return jsonResponse({ projects: opts.recent ?? [] });
    }
    if (url.endsWith("/api/project") && method === "POST") {
      if (opts.createFails) return errorResponse(409, { error: "directory exists", error_type: "conflict" });
      return jsonResponse({ ok: true });
    }
    if (url.endsWith("/api/project/open") && method === "POST") {
      if (opts.openFails) return errorResponse(404, { error: "not found", error_type: "not_found" });
      return jsonResponse({ ok: true });
    }
    if (url.endsWith("/api/project/demo") && method === "POST") {
      return jsonResponse({ ok: true });
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderWelcome(onReady: () => void, opts: MockOptions = {}) {
  const fetchMock = installFetchMock(opts);
  render(
    <I18nProvider lang="en">
      <WelcomeScreen onReady={onReady} />
    </I18nProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WelcomeScreen — layout", () => {
  it("shows the three lanes: NEW PROJECT, OPEN, SAMPLE", async () => {
    renderWelcome(() => {});
    expect(screen.getByText("NEW PROJECT")).toBeInTheDocument();
    // "OPEN" is both the card heading and the button label — assert at
    // least one instance instead of picking a single (ambiguous) match.
    expect(screen.getAllByText("OPEN").length).toBeGreaterThan(0);
    expect(screen.getByText("SAMPLE")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("no recent projects")).toBeInTheDocument());
  });
});

describe("WelcomeScreen — NEW PROJECT", () => {
  it("CREATE is disabled until both name and directory are filled", async () => {
    const user = userEvent.setup();
    renderWelcome(() => {});
    const createBtn = screen.getByRole("button", { name: "CREATE" });
    expect(createBtn).toBeDisabled();

    await user.type(screen.getByLabelText("name"), "CaTeO3 cyclic");
    expect(createBtn).toBeDisabled();

    await user.type(screen.getByLabelText("directory"), "C:\\projects");
    expect(createBtn).not.toBeDisabled();
  });

  it("submitting calls postProjectCreate with {name, directory} and then onReady()", async () => {
    const user = userEvent.setup();
    const onReady = vi.fn();
    const fetchMock = renderWelcome(onReady);

    await user.type(screen.getByLabelText("name"), "CaTeO3 cyclic");
    await user.type(screen.getByLabelText("directory"), "C:\\projects");
    await user.click(screen.getByRole("button", { name: "CREATE" }));

    await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project"));
    expect(call).toBeDefined();
    const [, init] = call!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      name: "CaTeO3 cyclic",
      directory: "C:\\projects",
    });
  });

  it("shows the server error message and does not call onReady on failure", async () => {
    const user = userEvent.setup();
    const onReady = vi.fn();
    renderWelcome(onReady, { createFails: true });

    await user.type(screen.getByLabelText("name"), "dup");
    await user.type(screen.getByLabelText("directory"), "C:\\projects");
    await user.click(screen.getByRole("button", { name: "CREATE" }));

    await waitFor(() => expect(screen.getByText("directory exists")).toBeInTheDocument());
    expect(onReady).not.toHaveBeenCalled();
  });
});

describe("WelcomeScreen — OPEN", () => {
  it("typing a path and clicking OPEN calls postProjectOpen and onReady()", async () => {
    const user = userEvent.setup();
    const onReady = vi.fn();
    const fetchMock = renderWelcome(onReady);

    await user.type(screen.getByLabelText("project path"), "C:\\projects\\CaTeO3 cyclic");
    await user.click(screen.getByRole("button", { name: "OPEN" }));

    await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project/open"));
    expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
      path: "C:\\projects\\CaTeO3 cyclic",
    });
  });

  it("renders RECENT rows and clicking one opens it directly (skipping the path field)", async () => {
    const user = userEvent.setup();
    const onReady = vi.fn();
    const fetchMock = renderWelcome(onReady, {
      recent: [{ name: "CaTeO3 cyclic", path: "C:\\projects\\CaTeO3 cyclic", last_opened: "2026-07-24" }],
    });

    await waitFor(() => expect(screen.getByText("CaTeO3 cyclic")).toBeInTheDocument());
    await user.click(screen.getByText("CaTeO3 cyclic"));

    await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/project/open"));
    expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
      path: "C:\\projects\\CaTeO3 cyclic",
    });
  });

  it("shows the server error message on a failed open", async () => {
    const user = userEvent.setup();
    renderWelcome(
      () => {},
      { openFails: true },
    );
    await user.type(screen.getByLabelText("project path"), "C:\\nope");
    await user.click(screen.getByRole("button", { name: "OPEN" }));
    await waitFor(() => expect(screen.getByText("not found")).toBeInTheDocument());
  });
});

describe("WelcomeScreen — SAMPLE", () => {
  it("clicking OPEN SAMPLE calls postProjectDemo and onReady()", async () => {
    const user = userEvent.setup();
    const onReady = vi.fn();
    const fetchMock = renderWelcome(onReady);

    await user.click(screen.getByRole("button", { name: "OPEN SAMPLE" }));

    await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/project/demo"))).toBe(true);
  });
});
