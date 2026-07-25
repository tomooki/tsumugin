import { useEffect, useState, type ChangeEvent } from "react";
import {
  ApiError,
  getState,
  getViewModel,
  postAddHistogram,
  postAddPhase,
  postProjectSettings,
  postRemoveHistogram,
  postRemovePhase,
  uploadProjectFile,
} from "../../api/client";
import type { ProjectHistogramRow, ProjectPhaseRow } from "../../api/types";
import { DATA_FORMAT_OPTIONS, GEOMETRY_OPTIONS, RADIATION_OPTIONS } from "../../data/projectOptions";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { BlueprintCard, Btn } from "../common";
import "./ProjectTab.css";
import { pt, type ProjectStringKey } from "./ProjectTab.strings";

function formatTwoTheta(range: [number, number] | null): string {
  if (!range) return "—";
  return `${range[0].toFixed(1)}–${range[1].toFixed(1)}`;
}

function parseOptionalNumber(raw: string): number | null {
  const v = raw.trim();
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** PROJECT tab (V2a P4, REQ-GUI-015/016) — HISTOGRAMS / PHASES / SETTINGS
 * cards for the project-lifecycle mutating endpoints
 * (api-contract.md §プロジェクトライフサイクル). Data comes from
 * `viewModel.project` (see api/types.ts's ProjectViewModel doc comment for
 * why that field is a judgment-call addition, not yet in api-contract.md).
 * Read-only in demo mode (SAMPLE session) and while a refinement job is
 * running — see the `locked` derivation below. */
export function ProjectTab() {
  const { lang } = useI18n();
  const { state, dispatch } = useStore();

  function t(key: ProjectStringKey, vars?: Record<string, string | number>): string {
    return pt(lang, key, vars);
  }

  const source = state.shell?.source;
  const demoReadOnly = source === "demo";
  const refineRunning = state.refine?.status === "running";
  const locked = demoReadOnly || refineRunning;

  const vm = state.viewModel?.project;
  const histograms: ProjectHistogramRow[] = vm?.histograms ?? [];
  const phases: ProjectPhaseRow[] = vm?.phases ?? [];
  const settings = vm?.settings ?? { two_theta_limits: null, background_coeffs: null, max_cyc: null };

  const [error, setError] = useState<string | null>(null);

  // — HISTOGRAMS add form —
  const [dataPath, setDataPath] = useState("");
  const [instrumentPath, setInstrumentPath] = useState("");
  const [radiation, setRadiation] = useState(RADIATION_OPTIONS[0].value);
  const [geometry, setGeometry] = useState(GEOMETRY_OPTIONS[0].value);
  const [dataFormat, setDataFormat] = useState(DATA_FORMAT_OPTIONS[0].value);
  const [ttMin, setTtMin] = useState("");
  const [ttMax, setTtMax] = useState("");
  const [bank, setBank] = useState("");
  const [uploadingData, setUploadingData] = useState(false);
  const [uploadingInstrument, setUploadingInstrument] = useState(false);
  const [addingHist, setAddingHist] = useState(false);

  // — PHASES add form —
  const [cifPath, setCifPath] = useState("");
  const [phaseName, setPhaseName] = useState("");
  const [uploadingCif, setUploadingCif] = useState(false);
  const [addingPhase, setAddingPhase] = useState(false);

  // — SETTINGS form — resynced from the server on every viewmodel fetch
  // (mirrors reducer.ts's stageOn resync note: a page reload or an edit made
  // through another path must never leave this stale).
  const [setMin, setSetMin] = useState("");
  const [setMax, setSetMax] = useState("");
  const [setBg, setSetBg] = useState("");
  const [setMaxCyc, setSetMaxCyc] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);

  useEffect(() => {
    setSetMin(settings.two_theta_limits ? String(settings.two_theta_limits[0]) : "");
    setSetMax(settings.two_theta_limits ? String(settings.two_theta_limits[1]) : "");
    setSetBg(settings.background_coeffs != null ? String(settings.background_coeffs) : "");
    setSetMaxCyc(settings.max_cyc != null ? String(settings.max_cyc) : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.two_theta_limits?.[0], settings.two_theta_limits?.[1], settings.background_coeffs, settings.max_cyc]);

  function reportError(err: unknown) {
    setError(err instanceof ApiError ? err.message : t("project.error.generic"));
  }

  async function refetch() {
    const [shell, viewModel] = await Promise.all([getState(), getViewModel()]);
    dispatch({ type: "SET_SHELL", shell });
    dispatch({ type: "SET_VIEW_MODEL", viewModel });
  }

  // — HISTOGRAMS —

  async function handleDataFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploadingData(true);
    try {
      const res = await uploadProjectFile(file, "data");
      setDataPath(res.stored_path);
    } catch (err) {
      reportError(err);
    } finally {
      setUploadingData(false);
    }
  }

  async function handleInstrumentFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploadingInstrument(true);
    try {
      const res = await uploadProjectFile(file, "instrument");
      setInstrumentPath(res.stored_path);
    } catch (err) {
      reportError(err);
    } finally {
      setUploadingInstrument(false);
    }
  }

  async function handleAddHistogram() {
    if (locked || !dataPath || !instrumentPath) return;
    setError(null);
    setAddingHist(true);
    try {
      const min = parseOptionalNumber(ttMin);
      const max = parseOptionalNumber(ttMax);
      const two_theta_limits: [number, number] | null = min !== null && max !== null ? [min, max] : null;
      await postAddHistogram({
        data_path: dataPath,
        instrument_path: instrumentPath,
        radiation,
        geometry,
        data_format: dataFormat,
        two_theta_limits,
        bank: parseOptionalNumber(bank),
      });
      setDataPath("");
      setInstrumentPath("");
      setTtMin("");
      setTtMax("");
      setBank("");
      await refetch();
    } catch (err) {
      reportError(err);
    } finally {
      setAddingHist(false);
    }
  }

  async function handleRemoveHistogram(row: ProjectHistogramRow) {
    // Second guard against a stale `disabled` attribute (mirrors
    // OperatorConsole.handleRunRefinement's "second guard against a double
    // press racing the disabled attribute" — React state updates are not
    // synchronous with the click handler). jsdom itself already suppresses
    // click dispatch on a natively `disabled` button, so this line is not
    // independently exercisable via RTL fireEvent; the `toBeDisabled()`
    // assertions below are what's actually verified.
    if (locked) return;
    if (!window.confirm(t("project.histograms.remove.confirm", { id: row.id }))) return;
    setError(null);
    try {
      await postRemoveHistogram(row.id);
      await refetch();
    } catch (err) {
      reportError(err);
    }
  }

  // — PHASES —

  async function handleCifFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploadingCif(true);
    try {
      const res = await uploadProjectFile(file, "structure");
      setCifPath(res.stored_path);
    } catch (err) {
      reportError(err);
    } finally {
      setUploadingCif(false);
    }
  }

  async function handleAddPhase() {
    if (locked || !cifPath || !phaseName.trim()) return;
    setError(null);
    setAddingPhase(true);
    try {
      await postAddPhase({ structure_path: cifPath, phase_name: phaseName.trim() });
      setCifPath("");
      setPhaseName("");
      await refetch();
    } catch (err) {
      reportError(err);
    } finally {
      setAddingPhase(false);
    }
  }

  async function handleRemovePhase(row: ProjectPhaseRow) {
    if (locked) return;
    if (!window.confirm(t("project.phases.remove.confirm", { name: row.name }))) return;
    setError(null);
    try {
      await postRemovePhase(row.name);
      await refetch();
    } catch (err) {
      reportError(err);
    }
  }

  // — SETTINGS —

  async function handleSaveSettings() {
    if (locked) return;
    setError(null);
    setSavingSettings(true);
    try {
      const min = parseOptionalNumber(setMin);
      const max = parseOptionalNumber(setMax);
      const two_theta_limits: [number, number] | null = min !== null && max !== null ? [min, max] : null;
      await postProjectSettings({
        two_theta_limits,
        background_coeffs: parseOptionalNumber(setBg),
        max_cyc: parseOptionalNumber(setMaxCyc),
      });
      await refetch();
    } catch (err) {
      reportError(err);
    } finally {
      setSavingSettings(false);
    }
  }

  const histBusy = uploadingData || uploadingInstrument || addingHist;
  const phaseBusy = uploadingCif || addingPhase;

  return (
    <div className="proj-tab">
      <div className="proj-tab__head">
        <span className="proj-tab__title">{t("project.title")}</span>
        <span className="proj-tab__note">{t("project.note")}</span>
      </div>

      {demoReadOnly && <div className="proj-tab__banner">{t("project.demoReadOnly")}</div>}
      {!demoReadOnly && refineRunning && (
        <div className="proj-tab__banner">{t("project.refineRunning")}</div>
      )}
      {error && <div className="proj-tab__error">{error}</div>}

      <BlueprintCard heading={t("project.histograms.heading")} className="proj-card">
        <table className="proj-table">
          <thead>
            <tr>
              <th>{t("project.histograms.col.id")}</th>
              <th>{t("project.histograms.col.dataFile")}</th>
              <th>{t("project.histograms.col.format")}</th>
              <th>{t("project.histograms.col.radiation")}</th>
              <th>{t("project.histograms.col.geometry")}</th>
              <th className="num">{t("project.histograms.col.twoTheta")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {histograms.map((row) => (
              <tr key={row.id}>
                <td className="mono">{row.id}</td>
                <td className="mono proj-table__path">{row.data_path}</td>
                <td className="mono">{row.data_format}</td>
                <td className="mono">{row.radiation}</td>
                <td className="mono">{row.geometry}</td>
                <td className="num mono">{formatTwoTheta(row.two_theta_limits)}</td>
                <td className="right">
                  <Btn
                    type="button"
                    variant="outline"
                    disabled={locked}
                    onClick={() => handleRemoveHistogram(row)}
                  >
                    {t("project.histograms.remove")}
                  </Btn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {histograms.length === 0 && (
          <div className="proj-table__empty">{t("project.histograms.empty")}</div>
        )}

        <div className="proj-add">
          <span className="proj-add__heading">{t("project.histograms.add.heading")}</span>
          <div className="proj-add__grid">
            <label className="proj-add__field">
              <span>{t("project.histograms.add.dataFile")}</span>
              <input type="file" disabled={locked} onChange={handleDataFile} />
              {dataPath && <span className="proj-add__chosen mono">{dataPath}</span>}
              {uploadingData && <span className="proj-add__status">{t("project.histograms.add.uploading")}</span>}
            </label>
            <label className="proj-add__field">
              <span>{t("project.histograms.add.instrumentFile")}</span>
              <input type="file" disabled={locked} onChange={handleInstrumentFile} />
              {instrumentPath && <span className="proj-add__chosen mono">{instrumentPath}</span>}
              {uploadingInstrument && (
                <span className="proj-add__status">{t("project.histograms.add.uploading")}</span>
              )}
            </label>
            <label className="proj-add__field">
              <span>{t("project.histograms.add.radiation")}</span>
              <select value={radiation} disabled={locked} onChange={(e) => setRadiation(e.target.value)}>
                {RADIATION_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="proj-add__field">
              <span>{t("project.histograms.add.geometry")}</span>
              <select value={geometry} disabled={locked} onChange={(e) => setGeometry(e.target.value)}>
                {GEOMETRY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="proj-add__field">
              <span>{t("project.histograms.add.format")}</span>
              <select value={dataFormat} disabled={locked} onChange={(e) => setDataFormat(e.target.value)}>
                {DATA_FORMAT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="proj-add__field">
              <span>{t("project.histograms.add.twoThetaMin")}</span>
              <input value={ttMin} disabled={locked} onChange={(e) => setTtMin(e.target.value)} />
            </label>
            <label className="proj-add__field">
              <span>{t("project.histograms.add.twoThetaMax")}</span>
              <input value={ttMax} disabled={locked} onChange={(e) => setTtMax(e.target.value)} />
            </label>
            <label className="proj-add__field">
              <span>{t("project.histograms.add.bank")}</span>
              <input value={bank} disabled={locked} onChange={(e) => setBank(e.target.value)} />
            </label>
          </div>
          <Btn
            type="button"
            variant="accent"
            disabled={locked || histBusy || !dataPath || !instrumentPath}
            onClick={handleAddHistogram}
          >
            {addingHist ? t("project.histograms.add.adding") : t("project.histograms.add.submit")}
          </Btn>
        </div>
      </BlueprintCard>

      <BlueprintCard heading={t("project.phases.heading")} className="proj-card">
        <table className="proj-table">
          <thead>
            <tr>
              <th>{t("project.phases.col.name")}</th>
              <th>{t("project.phases.col.cif")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {phases.map((row) => (
              <tr key={row.name}>
                <td>{row.name}</td>
                <td className="mono proj-table__path">{row.structure_path}</td>
                <td className="right">
                  <Btn
                    type="button"
                    variant="outline"
                    disabled={locked}
                    onClick={() => handleRemovePhase(row)}
                  >
                    {t("project.phases.remove")}
                  </Btn>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {phases.length === 0 && <div className="proj-table__empty">{t("project.phases.empty")}</div>}

        <div className="proj-add">
          <span className="proj-add__heading">{t("project.phases.add.heading")}</span>
          <div className="proj-add__grid">
            <label className="proj-add__field">
              <span>{t("project.phases.add.cif")}</span>
              <input type="file" disabled={locked} onChange={handleCifFile} />
              {cifPath && <span className="proj-add__chosen mono">{cifPath}</span>}
              {uploadingCif && <span className="proj-add__status">{t("project.phases.add.uploading")}</span>}
            </label>
            <label className="proj-add__field">
              <span>{t("project.phases.add.name")}</span>
              <input
                value={phaseName}
                disabled={locked}
                placeholder={t("project.phases.add.namePlaceholder")}
                onChange={(e) => setPhaseName(e.target.value)}
              />
            </label>
          </div>
          <Btn
            type="button"
            variant="accent"
            disabled={locked || phaseBusy || !cifPath || !phaseName.trim()}
            onClick={handleAddPhase}
          >
            {addingPhase ? t("project.phases.add.adding") : t("project.phases.add.submit")}
          </Btn>
        </div>
      </BlueprintCard>

      <BlueprintCard heading={t("project.settings.heading")} className="proj-card">
        <div className="proj-add__grid">
          <label className="proj-add__field">
            <span>{t("project.settings.twoThetaMin")}</span>
            <input value={setMin} disabled={locked} onChange={(e) => setSetMin(e.target.value)} />
          </label>
          <label className="proj-add__field">
            <span>{t("project.settings.twoThetaMax")}</span>
            <input value={setMax} disabled={locked} onChange={(e) => setSetMax(e.target.value)} />
          </label>
          <label className="proj-add__field">
            <span>{t("project.settings.backgroundCoeffs")}</span>
            <input value={setBg} disabled={locked} onChange={(e) => setSetBg(e.target.value)} />
          </label>
          <label className="proj-add__field">
            <span>{t("project.settings.maxCyc")}</span>
            <input value={setMaxCyc} disabled={locked} onChange={(e) => setSetMaxCyc(e.target.value)} />
          </label>
        </div>
        <Btn type="button" variant="accent" disabled={locked || savingSettings} onClick={handleSaveSettings}>
          {savingSettings ? t("project.settings.saving") : t("project.settings.save")}
        </Btn>
      </BlueprintCard>
    </div>
  );
}
