import { useCallback, useState } from "react";
import { ApiError, getSequentialStatus, getViewModel, postSequential } from "../../api/client";
import type { RefineStatus, SequenceChart, SequentialMode, SequentialRequest } from "../../api/types";
import { resolveJobConflict } from "../../hooks/useJobConflict";
import { usePollJob } from "../../hooks/usePollJob";
import { formatNumber } from "../../api/format";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { SeriesChart } from "../charts/SeriesChart";
import { BlueprintCard, Btn, Chip } from "../common";
import { sqt, type SequenceStringKey } from "./SequenceTab.strings";
import "./SequenceTab.css";

interface ChartChrome {
  noteKey: "seq.rwp.note" | "seq.lattice.note" | "seq.fraction.note";
  placeholderKey: "seq.rwp.placeholder" | "seq.lattice.placeholder" | "seq.fraction.placeholder";
  height: string;
}

// Static per-chart chrome (note + placeholder label + frame height) keyed by
// the chart id the API is expected to send (handoff/README.md §Centre pane
// item 5: three fixed cards — Rwp / lattice / phase fraction vs frame).
// Headings come straight from the API (`chart.title`) rather than this map,
// matching the ContextBar precedent of preferring live data over the static
// mockup copy once it has loaded.
const CHART_CHROME: Record<string, ChartChrome> = {
  rwp: { noteKey: "seq.rwp.note", placeholderKey: "seq.rwp.placeholder", height: "92px" },
  lattice: { noteKey: "seq.lattice.note", placeholderKey: "seq.lattice.placeholder", height: "92px" },
  fraction: { noteKey: "seq.fraction.note", placeholderKey: "seq.fraction.placeholder", height: "108px" },
};

// Pre-load fallback: the three known charts in design order, so the tab has
// its expected shape before GET /api/viewmodel resolves.
const FALLBACK_CHARTS = [
  { id: "rwp", title: "seq.rwp.title" as const },
  { id: "lattice", title: "seq.lattice.title" as const },
  { id: "fraction", title: "seq.fraction.title" as const },
];

/** SEQUENCE tab — see handoff README §Centre pane item 5: three equally
 * growing chart cards (Rwp / lattice a,c / phase fraction vs frame), an
 * anchor chip row (crossover anchor gets the inverted "attention" chip),
 * and the SEGMENT SELECTION forward-vs-backward table. Data:
 * `state.viewModel.sequence` (FR-330 anchored bidirectional analysis).
 *
 * V2b B2/B3 (api-contract.md §逐次 / operando) adds RUN SEQUENTIAL: mode
 * select (forward/anchored — anchored is the recommended default per
 * CLAUDE.md's "相数は bic で抑制" operando rule) + a simplified anchor_table
 * editor (frame index → phase checkboxes from the current model phase set) +
 * a per-frame results table (`sequence.frames[]`). Job polling mirrors
 * PhaseIdTab (IDENTIFY) / HypothesesTab (MULTISTART): the shared job slot
 * (state.refine/state.activeJob) is reused with kind="sequential". */
export function SequenceTab() {
  const { lang, t } = useI18n();
  const { state, dispatch } = useStore();
  const seq = state.viewModel?.sequence;

  function tl(key: SequenceStringKey, vars?: Record<string, string | number>): string {
    return sqt(lang, key, vars);
  }

  const charts: SequenceChart[] =
    seq && seq.charts.length > 0
      ? seq.charts
      : FALLBACK_CHARTS.map((c) => ({ id: c.id, title: t(c.title), series: null }));

  const anchors = seq?.anchors ?? [];
  const crossoverNote = seq?.note ?? t("seq.crossoverNote");
  const segments = seq?.segments ?? [];
  const frameRows = seq?.frames ?? [];

  // — RUN SEQUENTIAL (V2b B2/B3) —
  const projectFrames = state.viewModel?.project?.frames ?? [];
  const phaseNames = (state.viewModel?.phases ?? []).map((p) => p.name);
  // Judgment call: postEchem's response body shape is left open-ended by the
  // contract ("{"curve", "targets", ...}"), so "has ECHEM been synced" is
  // read from the session-held readout it feeds (shell.project.echem, the
  // same field ContextBar's echem chip reads) rather than any local flag —
  // this also means a demo/seed session that already carries an echem
  // readout is treated as synced, which matches "結果はセッション保持".
  const echemSynced = state.shell?.project?.echem != null;

  const [mode, setMode] = useState<SequentialMode>("anchored");
  const [anchorSelections, setAnchorSelections] = useState<Record<number, Set<string>>>({});
  const [useChargeConstraint, setUseChargeConstraint] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const jobRunning = state.refine?.status === "running";
  const sequentialRunning = jobRunning && state.activeJob === "sequential";

  function toggleAnchorPhase(frameIdx: number, phaseName: string) {
    setAnchorSelections((prev) => {
      const next = { ...prev };
      const set = new Set(next[frameIdx] ?? []);
      if (set.has(phaseName)) set.delete(phaseName);
      else set.add(phaseName);
      if (set.size === 0) delete next[frameIdx];
      else next[frameIdx] = set;
      return next;
    });
  }

  function buildAnchorTable(): Record<string, string[]> {
    const table: Record<string, string[]> = {};
    for (const [idx, set] of Object.entries(anchorSelections)) {
      if (set.size > 0) table[idx] = Array.from(set);
    }
    return table;
  }

  const setRefineStatus = useCallback(
    (refine: RefineStatus) => dispatch({ type: "SET_REFINE_STATUS", refine }),
    [dispatch],
  );

  const handleSequentialDone = useCallback(async () => {
    dispatch({ type: "SET_ACTIVE_JOB", job: null });
    try {
      const viewModel = await getViewModel();
      dispatch({ type: "SET_VIEW_MODEL", viewModel });
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : String(err));
    }
  }, [dispatch]);

  const handleSequentialFailed = useCallback(
    (next: RefineStatus) => {
      dispatch({ type: "SET_ACTIVE_JOB", job: null });
      setRunError(tl("seq.run.failed", { message: next.error ?? "unknown error" }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dispatch, lang],
  );

  const handleSequentialPollError = useCallback(
    (err: unknown) => {
      const message = err instanceof ApiError ? err.message : String(err);
      setRunError(tl("seq.run.pollError", { message }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lang],
  );

  usePollJob({
    status: state.refine,
    setStatus: setRefineStatus,
    statusFn: getSequentialStatus,
    enabled: state.activeJob === "sequential",
    onDone: handleSequentialDone,
    onFailed: handleSequentialFailed,
    onError: handleSequentialPollError,
  });

  function handleRunSequential() {
    if (jobRunning) return;
    setRunError(null);
    const payload: SequentialRequest = { mode };
    if (mode === "anchored") {
      const table = buildAnchorTable();
      if (Object.keys(table).length > 0) payload.anchor_table = table;
    }
    if (useChargeConstraint && echemSynced) payload.use_charge_constraint = true;
    postSequential(payload)
      .then((res) => {
        if (res.status === "started") {
          dispatch({ type: "SET_ACTIVE_JOB", job: "sequential" });
          setRefineStatus({ status: "running", elapsed_s: 0, last_event: null, error: null });
        }
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) {
          // Non-fatal (api-contract.md: shared job slot) — same
          // resolveJobConflict pattern as OperatorConsole/PhaseIdTab/
          // HypothesesTab.
          setRunError(tl("seq.run.busy"));
          void resolveJobConflict(dispatch).catch(() => {});
          return;
        }
        const message = err instanceof ApiError ? err.message : String(err);
        setRunError(tl("seq.run.error", { message }));
      });
  }

  return (
    <div className="seq-tab">
      <div className="seq-tab__head">
        <span className="seq-tab__title">{t("seq.title")}</span>
        <span className="seq-tab__note">{t("seq.note")}</span>
      </div>

      <BlueprintCard heading={tl("seq.run.heading")} className="seq-tab__run-card">
        <div className="seq-tab__run-controls">
          <label className="seq-tab__run-field">
            <span>{tl("seq.run.modeLabel")}</span>
            <select
              aria-label={tl("seq.run.modeLabel")}
              value={mode}
              disabled={jobRunning}
              onChange={(e) => setMode(e.target.value as SequentialMode)}
            >
              <option value="anchored">{tl("seq.run.modeAnchored")}</option>
              <option value="forward">{tl("seq.run.modeForward")}</option>
            </select>
          </label>
          <label className="seq-tab__run-charge">
            <input
              type="checkbox"
              checked={useChargeConstraint}
              disabled={jobRunning || !echemSynced}
              onChange={(e) => setUseChargeConstraint(e.target.checked)}
            />
            <span>{tl("seq.run.chargeConstraint")}</span>
          </label>
          <Btn type="button" variant="accent" onClick={handleRunSequential} disabled={jobRunning}>
            {sequentialRunning ? tl("seq.run.running") : tl("seq.run.button")}
          </Btn>
        </div>
        {!echemSynced && (
          <div className="seq-tab__run-hint">{tl("seq.run.chargeConstraintHint")}</div>
        )}
        {runError && <div className="seq-tab__run-error">{runError}</div>}

        {mode === "anchored" && (
          <div className="seq-tab__anchor-editor">
            <div className="seq-tab__anchor-editor-head">
              <span>{tl("seq.anchorTable.heading")}</span>
              <span className="seq-tab__anchor-editor-note">{tl("seq.anchorTable.note")}</span>
            </div>
            {projectFrames.length === 0 ? (
              <div className="seq-tab__anchor-editor-empty">{tl("seq.anchorTable.empty")}</div>
            ) : (
              <table className="seq-tab__anchor-table">
                <thead>
                  <tr>
                    <th>{t("col.label")}</th>
                    {phaseNames.map((name) => (
                      <th key={name}>{name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {projectFrames.map((f, idx) => (
                    <tr key={f.id}>
                      <td className="mono">{f.label}</td>
                      {phaseNames.map((name) => (
                        <td key={name}>
                          <input
                            type="checkbox"
                            aria-label={`${f.label} ${name}`}
                            checked={anchorSelections[idx]?.has(name) ?? false}
                            disabled={jobRunning}
                            onChange={() => toggleAnchorPhase(idx, name)}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </BlueprintCard>

      <div className="seq-tab__charts">
        {charts.map((chart) => {
          const chrome = CHART_CHROME[chart.id];
          return (
            <BlueprintCard
              key={chart.id}
              heading={chart.title}
              note={chrome ? t(chrome.noteKey) : undefined}
              className="seq-tab__chart-card"
              bodyStyle={{ display: "flex", flex: 1, minHeight: 0 }}
            >
              <SeriesChart
                series={chart.series}
                height={chrome?.height ?? "96px"}
                emptyLabel={chrome ? t(chrome.placeholderKey) : tl("chart.fallback.placeholder")}
              />
            </BlueprintCard>
          );
        })}
      </div>

      <div className="seq-tab__anchors">
        <div className="seq-tab__anchors-chips">
          <span className="seq-tab__anchors-label">{t("seq.anchors")}</span>
          {anchors.map((anchor) => (
            <Chip key={anchor.id} variant={anchor.crossover ? "inverted" : "accent"}>
              {anchor.crossover ? `${anchor.id} ${tl("anchor.crossoverSuffix")}` : anchor.id}
            </Chip>
          ))}
        </div>
        <span className="seq-tab__anchors-note">{crossoverNote}</span>
      </div>

      <BlueprintCard heading={t("seq.segTitle")}>
        <table className="seq-tab__seg-table">
          <thead>
            <tr>
              <th className="seq-tab__seg-th--left">{t("col.segment")}</th>
              <th className="seq-tab__seg-th--left">{t("col.forwardSet")}</th>
              <th className="seq-tab__seg-th--left">{t("col.backwardSet")}</th>
              <th className="seq-tab__seg-th--right">Rwp</th>
              <th className="seq-tab__seg-th--right">{t("col.totalBic")}</th>
              <th className="seq-tab__seg-th--left">{t("col.selected")}</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((row) => (
              <tr key={row.segment}>
                <td className="seq-tab__seg-td--mono">{row.segment}</td>
                <td>{row.forward}</td>
                <td>{row.backward}</td>
                <td className="seq-tab__seg-td--right-mono">{row.rwp}</td>
                <td className="seq-tab__seg-td--right-mono">{row.total_bic}</td>
                <td className="seq-tab__seg-td--selected">{row.selected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </BlueprintCard>

      {frameRows.length > 0 && (
        <BlueprintCard heading={tl("seq.framesTable.heading")}>
          <table className="seq-tab__frames-table">
            <thead>
              <tr>
                <th className="seq-tab__seg-th--left">{tl("col.frame")}</th>
                <th className="seq-tab__seg-th--left">{t("col.label")}</th>
                <th className="seq-tab__seg-th--right">{tl("col.axisValue")}</th>
                <th className="seq-tab__seg-th--right">Rwp</th>
                <th className="seq-tab__seg-th--left">{tl("col.cells")}</th>
                <th className="seq-tab__seg-th--left">{tl("col.fractions")}</th>
                <th className="seq-tab__seg-th--left">{tl("col.changepoint")}</th>
              </tr>
            </thead>
            <tbody>
              {frameRows.map((row, i) => (
                <tr
                  key={row.frame}
                  className={`seq-tab__frame-row${state.frameIndex === i ? " seq-tab__frame-row--selected" : ""}`}
                >
                  <td className="seq-tab__seg-td--mono">{row.frame}</td>
                  <td>{row.label}</td>
                  <td className="seq-tab__seg-td--right-mono">{formatNumber(row.axis_value, 2)}</td>
                  <td className="seq-tab__seg-td--right-mono">{formatNumber(row.rwp, 2)}</td>
                  <td className="seq-tab__seg-td--mono">{row.cells}</td>
                  <td className="seq-tab__seg-td--mono">{row.fractions}</td>
                  <td>{row.changepoint && <Chip variant="inverted">{tl("col.changepoint")}</Chip>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </BlueprintCard>
      )}
    </div>
  );
}
