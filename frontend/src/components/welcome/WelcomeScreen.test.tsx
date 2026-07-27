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
  // api-contract.md §ファイル選択: fs/roots + fs/list, used by the BROWSE…
  // picker. Keyed by exact `path` query value, mirroring PathPicker.test.tsx.
  fsRoots?: { path: string; label: string }[];
  fsListings?: Record<
    string,
    { path: string; parent: string | null; entries: { name: string; path: string; is_dir: boolean; is_project: boolean }[] }
  >;
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
    if (url.endsWith("/api/fs/roots") && method === "GET") {
      return jsonResponse({ roots: opts.fsRoots ?? [{ path: "C:\\", label: "C:\\" }] });
    }
    if (url.includes("/api/fs/list") && method === "GET") {
      const path = decodeURIComponent(url.split("path=")[1] ?? "");
      const found = opts.fsListings?.[path];
      if (!found) throw new Error(`no fs listing mocked for ${path}`);
      return jsonResponse(found);
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

describe("WelcomeScreen — BROWSE (api-contract.md §ファイル選択)", () => {
  it("NEW PROJECT's BROWSE opens a directory-mode picker and writes the picked path into the directory field", async () => {
    const user = userEvent.setup();
    renderWelcome(() => {}, {
      fsRoots: [{ path: "C:\\", label: "C:\\" }],
      fsListings: {
        "C:\\": {
          path: "C:\\",
          parent: null,
          entries: [{ name: "projects", path: "C:\\projects", is_dir: true, is_project: false }],
        },
        "C:\\projects": { path: "C:\\projects", parent: "C:\\", entries: [] },
      },
    });

    // There are two BROWSE buttons (directory + open path) — the NEW
    // PROJECT one is the first in document order.
    const browseBtns = screen.getAllByRole("button", { name: "BROWSE …" });
    await user.click(browseBtns[0]);

    await waitFor(() => expect(screen.getByText("projects")).toBeInTheDocument());
    await user.click(screen.getByText("projects"));
    await waitFor(() => expect(screen.getByRole("button", { name: "SELECT" })).not.toBeDisabled());
    await user.click(screen.getByRole("button", { name: "SELECT" }));

    // Picker closes and the directory input reflects the picked path.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect((screen.getByLabelText("directory") as HTMLInputElement).value).toBe("C:\\projects");
  });

  it("OPEN's BROWSE opens a project-mode picker and writes the picked path into the path field", async () => {
    const user = userEvent.setup();
    renderWelcome(() => {}, {
      fsRoots: [{ path: "C:\\", label: "C:\\" }],
      fsListings: {
        "C:\\": {
          path: "C:\\",
          parent: null,
          entries: [{ name: "CaTeO3", path: "C:\\CaTeO3", is_dir: true, is_project: true }],
        },
        "C:\\CaTeO3": { path: "C:\\CaTeO3", parent: "C:\\", entries: [] },
      },
    });

    const browseBtns = screen.getAllByRole("button", { name: "BROWSE …" });
    await user.click(browseBtns[1]);

    await waitFor(() => expect(screen.getByText("CaTeO3")).toBeInTheDocument());
    // Descending into the PROJECT-flagged directory should enable SELECT
    // immediately (mode="project" gating — see PathPicker.test.tsx for the
    // exhaustive/mutation-proof coverage of this gate itself).
    await user.click(screen.getByText("CaTeO3"));
    await waitFor(() => expect(screen.getByRole("button", { name: "SELECT" })).not.toBeDisabled());
    await user.click(screen.getByRole("button", { name: "SELECT" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect((screen.getByLabelText("project path") as HTMLInputElement).value).toBe("C:\\CaTeO3");
  });

  it("CANCEL / Escape closes the picker without touching either input", async () => {
    const user = userEvent.setup();
    renderWelcome(() => {}, {
      fsRoots: [{ path: "C:\\", label: "C:\\" }],
      fsListings: { "C:\\": { path: "C:\\", parent: null, entries: [] } },
    });

    const browseBtns = screen.getAllByRole("button", { name: "BROWSE …" });
    await user.click(browseBtns[0]);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect((screen.getByLabelText("directory") as HTMLInputElement).value).toBe("");
  });
});
