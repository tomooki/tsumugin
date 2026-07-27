import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FsEntry, FsListing, FsRoot } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { PathPicker } from "./PathPicker";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: ok ? "OK" : "error", json: async () => body } as Response;
}

function root(overrides: Partial<FsRoot> = {}): FsRoot {
  return { path: "C:\\", label: "C:\\", ...overrides };
}

function entry(overrides: Partial<FsEntry> = {}): FsEntry {
  return { name: "projects", path: "C:\\projects", is_dir: true, is_project: false, ...overrides };
}

function listing(overrides: Partial<FsListing> = {}): FsListing {
  return { path: "C:\\", parent: null, entries: [], ...overrides };
}

interface MockOptions {
  roots?: FsRoot[];
  // path -> listing, keyed by the exact `path` query value.
  listings: Record<string, FsListing>;
  rootsFail?: boolean;
  listFails?: { status: number; body: unknown };
}

function installFetchMock(opts: MockOptions) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url.endsWith("/api/fs/roots")) {
      if (opts.rootsFail) return jsonResponse({ error: "boom", error_type: "internal" }, false, 500);
      return jsonResponse({ roots: opts.roots ?? [root()] });
    }
    if (url.includes("/api/fs/list")) {
      const path = decodeURIComponent(url.split("path=")[1] ?? "");
      if (opts.listFails) return jsonResponse(opts.listFails.body, false, opts.listFails.status);
      const found = opts.listings[path];
      if (!found) throw new Error(`no listing mocked for ${path}`);
      return jsonResponse(found);
    }
    throw new Error(`unhandled fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPicker(
  props: Partial<Parameters<typeof PathPicker>[0]> = {},
  opts: MockOptions = { listings: { "C:\\": listing() } },
) {
  const fetchMock = installFetchMock(opts);
  const onSelect = props.onSelect ?? vi.fn();
  const onClose = props.onClose ?? vi.fn();
  render(
    <I18nProvider lang="en">
      <PathPicker
        mode={props.mode ?? "directory"}
        title={props.title ?? "CHOOSE A DIRECTORY"}
        initialPath={props.initialPath}
        onSelect={onSelect}
        onClose={onClose}
      />
    </I18nProvider>,
  );
  return { fetchMock, onSelect, onClose };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PathPicker — roots", () => {
  it("lists roots from GET /api/fs/roots and lists the first root's contents by default", async () => {
    const rootEntry = entry({ name: "projects", path: "C:\\projects", is_dir: true });
    renderPicker(
      { mode: "directory" },
      {
        roots: [root({ path: "C:\\", label: "C:\\" }), root({ path: "D:\\", label: "D:\\" })],
        listings: { "C:\\": listing({ path: "C:\\", entries: [rootEntry] }) },
      },
    );
    await waitFor(() => expect(screen.getByText("projects")).toBeInTheDocument());
    expect(screen.getByText("D:\\")).toBeInTheDocument();
  });

  it("clicking a root navigates the main pane to that root", async () => {
    const user = userEvent.setup();
    renderPicker(
      { mode: "directory" },
      {
        roots: [root({ path: "C:\\", label: "C:\\" }), root({ path: "D:\\", label: "D:\\" })],
        listings: {
          "C:\\": listing({ path: "C:\\", entries: [] }),
          "D:\\": listing({ path: "D:\\", entries: [entry({ name: "data", path: "D:\\data" })] }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("empty")).toBeInTheDocument());
    await user.click(screen.getByText("D:\\"));
    await waitFor(() => expect(screen.getByText("data")).toBeInTheDocument());
  });
});

describe("PathPicker — directory navigation", () => {
  it("clicking a directory row descends into it and the breadcrumb path updates", async () => {
    const user = userEvent.setup();
    renderPicker(
      { mode: "directory" },
      {
        listings: {
          "C:\\": listing({
            path: "C:\\",
            entries: [entry({ name: "projects", path: "C:\\projects", is_dir: true })],
          }),
          "C:\\projects": listing({
            path: "C:\\projects",
            parent: "C:\\",
            entries: [entry({ name: "CaTeO3", path: "C:\\projects\\CaTeO3", is_dir: true })],
          }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("projects")).toBeInTheDocument());
    await user.click(screen.getByText("projects"));
    await waitFor(() => expect(screen.getByText("CaTeO3")).toBeInTheDocument());
    expect(screen.getAllByText("C:\\projects").length).toBeGreaterThan(0);
  });

  it("is disabled at a root with no parent", async () => {
    renderPicker(
      { mode: "directory" },
      { listings: { "C:\\": listing({ path: "C:\\", parent: null, entries: [] }) } },
    );
    await waitFor(() => expect(screen.getByLabelText("up to parent directory")).toBeDisabled());
  });

  it("navigates to listing.parent and re-enables/disables itself accordingly", async () => {
    const user = userEvent.setup();
    renderPicker(
      { mode: "directory" },
      {
        listings: {
          "C:\\": listing({
            path: "C:\\",
            parent: null,
            entries: [entry({ name: "projects", path: "C:\\projects", is_dir: true })],
          }),
          "C:\\projects": listing({ path: "C:\\projects", parent: "C:\\", entries: [] }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("projects")).toBeInTheDocument());
    await user.click(screen.getByText("projects"));
    await waitFor(() => expect(screen.getByLabelText("up to parent directory")).not.toBeDisabled());

    await user.click(screen.getByLabelText("up to parent directory"));
    await waitFor(() => expect(screen.getByText("projects")).toBeInTheDocument());
    expect(screen.getByLabelText("up to parent directory")).toBeDisabled();
  });
});

describe("PathPicker — mode=directory SELECT", () => {
  it("SELECT is enabled for the currently browsed directory and returns its path", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderPicker(
      { mode: "directory" },
      { listings: { "C:\\": listing({ path: "C:\\", entries: [] }) } },
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "SELECT" })).not.toBeDisabled());
    await user.click(screen.getByRole("button", { name: "SELECT" }));
    expect(onSelect).toHaveBeenCalledWith("C:\\");
  });
});

describe("PathPicker — mode=project SELECT gating (variant + mutation-proof)", () => {
  it("SELECT is disabled while browsing a non-project directory, with an inline reason", async () => {
    renderPicker(
      { mode: "project" },
      {
        listings: {
          "C:\\": listing({
            path: "C:\\",
            entries: [entry({ name: "plainfolder", path: "C:\\plainfolder", is_dir: true, is_project: false })],
          }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("plainfolder")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "SELECT" })).toBeDisabled();
    expect(screen.getByText("choose a folder marked PROJECT, or a .json file")).toBeInTheDocument();
  });

  it("descending into an is_project directory enables SELECT and returns that directory's path", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderPicker(
      { mode: "project" },
      {
        listings: {
          "C:\\": listing({
            path: "C:\\",
            entries: [
              entry({ name: "CaTeO3", path: "C:\\CaTeO3", is_dir: true, is_project: true }),
            ],
          }),
          "C:\\CaTeO3": listing({ path: "C:\\CaTeO3", parent: "C:\\", entries: [] }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("CaTeO3")).toBeInTheDocument());
    await user.click(screen.getByText("CaTeO3"));
    await waitFor(() => expect(screen.getByRole("button", { name: "SELECT" })).not.toBeDisabled());
    await user.click(screen.getByRole("button", { name: "SELECT" }));
    expect(onSelect).toHaveBeenCalledWith("C:\\CaTeO3");
  });

  it("clicking a .json file selects it (enables SELECT, returns the file path) without navigating", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderPicker(
      { mode: "project" },
      {
        listings: {
          "C:\\": listing({
            path: "C:\\",
            entries: [
              entry({ name: "project.json", path: "C:\\project.json", is_dir: false, is_project: false }),
            ],
          }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("project.json")).toBeInTheDocument());
    await user.click(screen.getByText("project.json"));
    await waitFor(() => expect(screen.getByRole("button", { name: "SELECT" })).not.toBeDisabled());
    await user.click(screen.getByRole("button", { name: "SELECT" }));
    expect(onSelect).toHaveBeenCalledWith("C:\\project.json");
  });

  it("mode=directory renders a .json file row as non-interactive (disabled)", async () => {
    renderPicker(
      { mode: "directory" },
      {
        listings: {
          "C:\\": listing({
            path: "C:\\",
            entries: [entry({ name: "project.json", path: "C:\\project.json", is_dir: false })],
          }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("project.json")).toBeInTheDocument());
    expect(screen.getByRole("option", { name: /project\.json/ })).toBeDisabled();
  });
});

describe("PathPicker — error handling (404/422 stay inline, modal does not close)", () => {
  it("a failed GET /api/fs/list shows the server error inline and does not call onClose", async () => {
    const { onClose } = renderPicker(
      { mode: "directory" },
      {
        listings: {},
        listFails: { status: 404, body: { error: "path not found", error_type: "not_found" } },
      },
    );
    await waitFor(() => expect(screen.getByText("path not found")).toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a failed GET /api/fs/roots shows the server error inline", async () => {
    renderPicker({ mode: "directory" }, { listings: {}, rootsFail: true });
    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
  });
});

describe("PathPicker — close affordances", () => {
  it("calls onClose on backdrop click and on Escape, but not on a dialog click", async () => {
    const user = userEvent.setup();
    const { onClose } = renderPicker({ mode: "directory" }, { listings: { "C:\\": listing() } });
    await waitFor(() => expect(screen.getByText("empty")).toBeInTheDocument());

    await user.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    await user.click(screen.getByRole("presentation"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape closes the picker", async () => {
    const user = userEvent.setup();
    const { onClose } = renderPicker({ mode: "directory" }, { listings: { "C:\\": listing() } });
    await waitFor(() => expect(screen.getByText("empty")).toBeInTheDocument());
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("PathPicker — initialPath", () => {
  it("lists initialPath instead of the first root when provided", async () => {
    renderPicker(
      { mode: "directory", initialPath: "C:\\projects" },
      {
        roots: [root({ path: "C:\\", label: "C:\\" })],
        listings: {
          "C:\\projects": listing({
            path: "C:\\projects",
            parent: "C:\\",
            entries: [entry({ name: "CaTeO3", path: "C:\\projects\\CaTeO3" })],
          }),
        },
      },
    );
    await waitFor(() => expect(screen.getByText("CaTeO3")).toBeInTheDocument());
  });
});
