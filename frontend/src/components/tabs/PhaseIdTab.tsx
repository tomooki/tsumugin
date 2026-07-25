import { useCallback, useState } from "react";
import {
  ApiError,
  getPhaseIdStatus,
  getViewModel,
  postPhaseId,
  postPhaseIdAdd,
} from "../../api/client";
import { formatNumber } from "../../api/format";
import type { PhaseIdCandidate, PhaseIdMode, RefineStatus } from "../../api/types";
import { usePollJob } from "../../hooks/usePollJob";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { BlueprintCard, Btn, Chip, PlaceholderPlot } from "../common";
import "./PhaseIdTab.css";
import { interpolateLocal, PID_LOCAL_STRINGS, type PidLocalKey } from "./PhaseIdTab.strings";

/** See handoff README §Centre pane item 4 (PHASE ID): candidate table
 * (`# / FORMULA / SOURCE / SG / DARA / m/w/ms/x / STRAIN / CHEM GUARD /
 * action`), an UNEXPLAINED FEATURES card (`residual_report`) and a PHASE
 * SET COMPLETENESS card (`check_phase_set`). Data comes from
 * `viewModel.phase_id` (api-contract.md); `source`/`chem_guard`/`notes`
 * text is server-supplied and rendered verbatim (API surface, not
 * translated).
 *
 * A4 (api-contract.md §解析ループ): IDENTIFY runs `identify_pattern`
 * (mode=pattern|residual) as a background job on the SAME shared job slot
 * as RUN REFINEMENT / MULTISTART — see state/types.ts ActiveJob and
 * hooks/usePollJob.ts. ADD AS PHASE materialises a specific candidate's CIF
 * and appends it to the model; re-refining with it is left to the user (RUN
 * REFINEMENT), matching the contract's "再精密化はユーザーが RUN で明示". */
export function PhaseIdTab() {
  const { t, lang } = useI18n();
  const { state, dispatch } = useStore();
  const vm = state.viewModel?.phase_id ?? {
    candidates: [],
    unexplained: [],
    completeness: { is_complete: true, notes: [], flagged_frames: "" },
  };

  const [mode, setMode] = useState<PhaseIdMode>("pattern");
  const [identifyError, setIdentifyError] = useState<string | null>(null);
  const [addingFormula, setAddingFormula] = useState<string | null>(null);
  const [addMessage, setAddMessage] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);

  function tl(key: PidLocalKey, vars?: Record<string, string | number>): string {
    const pair = PID_LOCAL_STRINGS[key];
    return interpolateLocal(lang === "ja" ? pair.ja : pair.en, vars);
  }

  // state.refine is the SHARED job-status slot (RUN REFINEMENT / IDENTIFY /
  // MULTISTART) — any of the three running disables the other two's start
  // buttons (api-contract.md: one job slot, mutually 409).
  const jobRunning = state.refine?.status === "running";
  const identifyRunning = jobRunning && state.activeJob === "phaseid";

  const setRefineStatus = useCallback(
    (refine: RefineStatus) => dispatch({ type: "SET_REFINE_STATUS", refine }),
    [dispatch],
  );

  const handleIdentifyDone = useCallback(async () => {
    dispatch({ type: "SET_ACTIVE_JOB", job: null });
    try {
      const viewModel = await getViewModel();
      dispatch({ type: "SET_VIEW_MODEL", viewModel });
    } catch (err) {
      setIdentifyError(err instanceof ApiError ? err.message : String(err));
    }
  }, [dispatch]);

  const handleIdentifyFailed = useCallback(
    (next: RefineStatus) => {
      dispatch({ type: "SET_ACTIVE_JOB", job: null });
      setIdentifyError(tl("pid.local.identifyFailed", { message: next.error ?? "unknown error" }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dispatch, lang],
  );

  const handleIdentifyPollError = useCallback(
    (err: unknown) => {
      const message = err instanceof ApiError ? err.message : String(err);
      setIdentifyError(tl("pid.local.identifyPollError", { message }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lang],
  );

  usePollJob({
    status: state.refine,
    setStatus: setRefineStatus,
    statusFn: getPhaseIdStatus,
    enabled: state.activeJob === "phaseid",
    onDone: handleIdentifyDone,
    onFailed: handleIdentifyFailed,
    onError: handleIdentifyPollError,
  });

  function handleIdentifyClick() {
    if (jobRunning) return;
    setIdentifyError(null);
    postPhaseId({ mode })
      .then((res) => {
        if (res.status === "started") {
          dispatch({ type: "SET_ACTIVE_JOB", job: "phaseid" });
          setRefineStatus({ status: "running", elapsed_s: 0, last_event: null, error: null });
        }
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) {
          // Non-fatal (api-contract.md: shared job slot) — surface it inline
          // rather than as a fatal store error; nothing here changed.
          setIdentifyError(tl("pid.local.identifyBusy"));
          return;
        }
        const message = err instanceof ApiError ? err.message : String(err);
        setIdentifyError(tl("pid.local.identifyError", { message }));
      });
  }

  function handleAddAsPhase(row: PhaseIdCandidate) {
    setAddMessage(null);
    setAddError(null);
    setAddingFormula(row.formula);
    postPhaseIdAdd({ formula: row.formula, mp_id: row.mp_id ?? "" })
      .then(async (shell) => {
        dispatch({ type: "SET_SHELL", shell });
        const viewModel = await getViewModel();
        dispatch({ type: "SET_VIEW_MODEL", viewModel });
        setAddMessage(tl("pid.local.addSuccess", { formula: row.formula }));
      })
      .catch((err: unknown) => {
        const message = err instanceof ApiError ? err.message : String(err);
        setAddError(tl("pid.local.addError", { formula: row.formula, message }));
      })
      .finally(() => setAddingFormula(null));
  }

  return (
    <div className="pid-tab">
      <div className="pid-tab__head">
        <span className="pid-tab__title">{t("pid.title")}</span>
        <span className="pid-tab__note">{t("pid.note")}</span>
      </div>

      <div className="pid-tab__controls">
        <label className="pid-tab__mode">
          <span className="pid-tab__mode-label">{tl("pid.local.modeLabel")}</span>
          <select
            aria-label={tl("pid.local.modeLabel")}
            value={mode}
            disabled={jobRunning}
            onChange={(e) => setMode(e.target.value as PhaseIdMode)}
          >
            <option value="pattern">{tl("pid.local.modePattern")}</option>
            <option value="residual">{tl("pid.local.modeResidual")}</option>
          </select>
        </label>
        <Btn type="button" variant="accent" onClick={handleIdentifyClick} disabled={jobRunning}>
          {identifyRunning ? tl("pid.local.identifying") : tl("pid.local.identify")}
        </Btn>
        {identifyError && <span className="pid-tab__message pid-tab__message--error">{identifyError}</span>}
      </div>
      {addMessage && <div className="pid-tab__message pid-tab__message--success">{addMessage}</div>}
      {addError && <div className="pid-tab__message pid-tab__message--error">{addError}</div>}

      <table className="pid-table">
        <thead>
          <tr>
            <th>#</th>
            <th>{t("col.formula")}</th>
            <th>{t("col.source")}</th>
            <th>{t("col.sg")}</th>
            <th className="num">{t("col.dara")}</th>
            <th className="num">m/w/ms/x</th>
            <th className="num">{t("col.strain")}</th>
            <th>{t("col.chemGuard")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {vm.candidates.map((row) => (
            <tr key={row.rank} className={row.rank === 1 ? "pid-table__row--top" : undefined}>
              <td>{row.rank}</td>
              <td>{row.formula}</td>
              <td className="mono">{row.source}</td>
              <td className="mono">{row.sg}</td>
              <td className="num">{formatNumber(row.dara, 2)}</td>
              <td className="num mono">{row.mwmsx}</td>
              <td className="num">{row.strain}</td>
              <td>
                <Chip variant={row.guard_fail ? "inverted" : "hairline"}>{row.chem_guard}</Chip>
              </td>
              <td className="right">
                <Btn
                  type="button"
                  variant="outline"
                  disabled={addingFormula === row.formula}
                  onClick={() => handleAddAsPhase(row)}
                >
                  {addingFormula === row.formula ? tl("pid.local.addAdding") : t("pid.action.addAsPhase")}
                </Btn>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="pid-bottom">
        <BlueprintCard
          heading={t("pid.residualTitle")}
          className="pid-bottom__card"
          bodyStyle={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
        >
          <PlaceholderPlot
            label={t("pid.residualDecompPlaceholder")}
            height="112px"
            style={{ flex: 1 }}
          />
          <div className="pid-residual__list">
            {vm.unexplained.map((f, i) => (
              <div key={i}>
                {`2θ ${formatNumber(f.two_theta, 2)} · S/N ${formatNumber(f.sn, 1)} · ${f.indexing}`}
              </div>
            ))}
          </div>
        </BlueprintCard>

        <BlueprintCard heading={t("pid.completenessTitle")} className="pid-bottom__card">
          <div className="pid-completeness">
            <div className="pid-completeness__row">
              <span>{t("completeness.isComplete")}</span>
              <Chip variant={vm.completeness.is_complete ? "hairline" : "inverted"}>
                {vm.completeness.is_complete ? "TRUE" : "FALSE"}
              </Chip>
            </div>
            {vm.completeness.notes.map((note, i) => (
              <div key={i} className="pid-completeness__note">
                {note}
              </div>
            ))}
            <div className="pid-completeness__row">
              <span>{t("completeness.flagged.k")}</span>
              <span className="pid-completeness__value">{vm.completeness.flagged_frames}</span>
            </div>
            <div className="pid-completeness__footer">{t("pid.completenessNote")}</div>
          </div>
        </BlueprintCard>
      </div>
    </div>
  );
}
