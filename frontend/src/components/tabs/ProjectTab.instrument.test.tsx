// 装置パラメータファイルの導線 (FR-502) — GUI 側。
//
// 従来 workbench は `kind="instrument"` のアップロードしか持たず、**装置ファイルを既に
// 持っている**ことが前提だった。持っていない利用者には出口が無く、しかも追加時に装置ファイルは
// 一度も開かれないため、誤ったファイルは精密化の深部まで行って初めて壊れた。
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ShellState, ViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { StoreProvider } from "../../state/store";
import { ProjectTab } from "./ProjectTab";

function makeShell(): ShellState {
  return {
    project: { name: "proj", dataset: "", frame: "", echem: null },
    mode: "manual",
    final_selection_mode: "human",
    ledger: { count: 0, verified: true },
    status: { backend_build: "tsumugin 0.3.0", seed: 0, mcp_tools: 43, gsas_available: true },
    agent: { tokens: 0, wall_time_s: 0, idle: true },
    source: "project",
  };
}

function makeViewModel(): ViewModel {
  return {
    datasets: [],
    phases: [],
    channels: [],
    snapshots: [],
    fit: {
      metrics: [], histograms: [], limits_note: "", phase_ticks: [],
      two_theta: { min: 4, max: 38 }, history: [], validity: [],
    },
    parameters: {},
    hypotheses: { rows: [], diff: { vs: "", rows: [] }, evidence: [] },
    phase_id: {
      candidates: [], unexplained: [],
      completeness: { is_complete: true, notes: [], flagged_frames: "" },
    },
    sequence: { charts: [], anchors: [], note: "", segments: [] },
    structure: { sites: [], constraints: [], mem_peaks: [] },
    stages: [],
    review: [],
    transcript: [],
    project: {
      histograms: [],
      phases: [],
      settings: { two_theta_limits: null, background_coeffs: 6, max_cyc: 12 },
    },
  };
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
}

function errorResponse(status: number, body: unknown): Response {
  return { ok: false, status, statusText: "error", json: async () => body } as Response;
}

interface Opts {
  presets?: unknown;
  createResponse?: unknown;
  createStatus?: number;
  addResponse?: unknown;
}

function installFetchMock(opts: Opts = {}) {
  const shell = makeShell();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    if (url.endsWith("/api/state") && method === "GET") return jsonResponse(shell);
    if (url.endsWith("/api/viewmodel") && method === "GET") return jsonResponse(makeViewModel());
    if (url.endsWith("/api/instrument/presets")) {
      return jsonResponse(
        opts.presets ?? {
          presets: [
            {
              label: "CuKa lab data", radiation: "xray_lab", geometry: "bragg_brentano",
              summary: "Kα1=1.5405 Å / Kα2=1.5443 Å (二重線)",
            },
            {
              label: "APS 30keV 11BM", radiation: "xray_synchrotron",
              geometry: "debye_scherrer", summary: "λ=0.413263 Å (単色)",
            },
          ],
        },
      );
    }
    if (url.endsWith("/api/instrument/create") && method === "POST") {
      if (opts.createStatus && opts.createStatus >= 400) {
        return errorResponse(opts.createStatus, { error: "radiation が決まりません", error_type: "ValueError" });
      }
      return jsonResponse(
        opts.createResponse ?? {
          path: "data/made.instprm", type: "PXC", radiation: "xray_lab",
          geometry: "bragg_brentano", wavelength: 1.5405, kalpha2_stripped: false,
          source: "preset:CuKa lab data", ok: true, findings: [],
        },
      );
    }
    if (url.endsWith("/api/project/histograms") && method === "POST") {
      return jsonResponse(opts.addResponse ?? { ...shell, instrument_findings: [] });
    }
    if (url.endsWith("/api/project/upload") && method === "POST") {
      const form = init?.body as FormData;
      const file = form.get("file") as File;
      return jsonResponse({ stored_path: `data/${file.name}` });
    }
    throw new Error(`unhandled fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderTab(opts: Opts = {}) {
  const fetchMock = installFetchMock(opts);
  render(
    <StoreProvider initialState={{ shell: makeShell(), viewModel: makeViewModel() }}>
      <I18nProvider lang="en">
        <ProjectTab />
      </I18nProvider>
    </StoreProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ProjectTab — instrument file creation (FR-502)", () => {
  it("offers a way out when the user has no instrument file", () => {
    renderTab();
    expect(screen.getByRole("button", { name: /don't have one/i })).toBeInTheDocument();
  });

  it("loads presets only when the panel is opened", async () => {
    const fetchMock = renderTab();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/instrument/presets"))).toBe(
      false,
    );
    await userEvent.click(screen.getByRole("button", { name: /don't have one/i }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).includes("/api/instrument/presets")),
      ).toBe(true),
    );
    expect(await screen.findByRole("option", { name: /CuKa lab data/ })).toBeInTheDocument();
  });

  it("creates an instrument file and fills the instrument path field", async () => {
    const fetchMock = renderTab();
    await userEvent.click(screen.getByRole("button", { name: /don't have one/i }));
    await screen.findByRole("option", { name: /CuKa lab data/ });
    await userEvent.click(screen.getByRole("button", { name: /^create instrument file$/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/instrument/create"));
      expect(call).toBeDefined();
    });
    expect(await screen.findByText("data/made.instprm")).toBeInTheDocument();
  });

  it("sends the wavelength instead of a preset when one is typed", async () => {
    const fetchMock = renderTab();
    await userEvent.click(screen.getByRole("button", { name: /don't have one/i }));
    await screen.findByRole("option", { name: /CuKa lab data/ });
    await userEvent.type(screen.getByLabelText(/^wavelength \(/i), "0.79958");
    await userEvent.click(screen.getByRole("button", { name: /^create instrument file$/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/instrument/create"));
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.wavelength).toBe(0.79958);
      expect(body.preset).toBeUndefined();
    });
  });

  it("shows the server error instead of silently doing nothing", async () => {
    renderTab({ createStatus: 422 });
    await userEvent.click(screen.getByRole("button", { name: /don't have one/i }));
    await screen.findByRole("option", { name: /CuKa lab data/ });
    await userEvent.click(screen.getByRole("button", { name: /^create instrument file$/i }));
    expect(await screen.findByText(/radiation が決まりません/)).toBeInTheDocument();
  });

  it("still works when GSAS-II is missing and presets fail to load", async () => {
    renderTab({ presets: { error: "GSAS-II 未導入", error_type: "GSASUnavailableError" } });
    await userEvent.click(screen.getByRole("button", { name: /don't have one/i }));
    // プリセットが引けなくても波長入力の経路は残る (「作れない」で終わらせない)
    expect(await screen.findByLabelText(/^wavelength \(/i)).toBeInTheDocument();
  });
});

describe("ProjectTab — instrument findings after adding a histogram", () => {
  it("surfaces non-blocking findings instead of dropping them", async () => {
    renderTab({
      addResponse: {
        ...makeShell(),
        instrument_findings: [
          {
            code: "kalpha2_consistency_question",
            severity: "question",
            message: "この instprm は Kα1+Kα2 の二重線モデルです。",
            hint: "データが Kα2 除去済みかを確認してください。",
          },
        ],
      },
    });
    const files = screen.getAllByLabelText(/file|params/i);
    await userEvent.upload(files[0] as HTMLInputElement, new File(["1 1\n"], "d.xye"));
    await userEvent.upload(files[1] as HTMLInputElement, new File(["#\n"], "d.instprm"));
    await userEvent.click(screen.getByRole("button", { name: /^add histogram$/i }));

    expect(await screen.findByText(/Kα1\+Kα2 の二重線モデル/)).toBeInTheDocument();
    expect(screen.getByText(/Kα2 除去済みかを確認/)).toBeInTheDocument();
  });
});
