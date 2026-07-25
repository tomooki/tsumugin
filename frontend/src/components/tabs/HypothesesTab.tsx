import { useCallback, useState } from "react";
import { ApiError, getMultistartStatus, getViewModel, postMultistart } from "../../api/client";
import { formatInt, formatNumber } from "../../api/format";
import type { RefineStatus } from "../../api/types";
import { usePollJob } from "../../hooks/usePollJob";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { ScatterChart } from "../charts/ScatterChart";
import { BlueprintCard, Btn } from "../common";
import "./HypothesesTab.css";
import { HYP_LOCAL_STRINGS, interpolateLocal, type HypLocalKey } from "./HypothesesTab.strings";

const DEFAULT_N_STARTS = 3;

/** See handoff README §Centre pane item 3 (HYPOTHESES): ranking table
 * (`# / ID / PHASES / P / Rwp / GOF / BIC / CLOSE / STATUS`), a DIFF card
 * against the comparison hypothesis, and an EVIDENCE & BASIN card. Data
 * comes from `viewModel.hypotheses` (api-contract.md); `phases`/`status`
 * cell text is server-supplied and rendered verbatim (API surface, not
 * translated — see README "Interactions & behaviour" table).
 *
 * A5 (api-contract.md §解析ループ): MULTISTART runs `run_multistart_rietveld`
 * as a background job on the SAME shared job slot as RUN REFINEMENT /
 * IDENTIFY — see state/types.ts ActiveJob and hooks/usePollJob.ts. On done,
 * the basin scatter above draws real points and a "corroborated" row shows
 * up in EVIDENCE — both purely from the refetched viewModel, no local state
 * needed for them. */
export function HypothesesTab() {
  const { t, lang } = useI18n();
  const { state, dispatch } = useStore();
  const vm = state.viewModel?.hypotheses ?? { rows: [], diff: { vs: "", rows: [] }, evidence: [] };

  // Kept as raw text (not a parsed number) so the field can be cleared and
  // retyped without a controlled-input "snap back to the default mid-typing"
  // fight — parsing (with a fallback to DEFAULT_N_STARTS) happens only when
  // MULTISTART is actually clicked.
  const [nStartsInput, setNStartsInput] = useState(String(DEFAULT_N_STARTS));
  const [multistartError, setMultistartError] = useState<string | null>(null);

  function tl(key: HypLocalKey, vars?: Record<string, string | number>): string {
    const pair = HYP_LOCAL_STRINGS[key];
    return interpolateLocal(lang === "ja" ? pair.ja : pair.en, vars);
  }

  // state.refine is the SHARED job-status slot — see PhaseIdTab's identical
  // comment. Any of the three job kinds running disables MULTISTART too.
  const jobRunning = state.refine?.status === "running";
  const multistartRunning = jobRunning && state.activeJob === "multistart";

  const setRefineStatus = useCallback(
    (refine: RefineStatus) => dispatch({ type: "SET_REFINE_STATUS", refine }),
    [dispatch],
  );

  const handleMultistartDone = useCallback(async () => {
    dispatch({ type: "SET_ACTIVE_JOB", job: null });
    try {
      const viewModel = await getViewModel();
      dispatch({ type: "SET_VIEW_MODEL", viewModel });
    } catch (err) {
      setMultistartError(err instanceof ApiError ? err.message : String(err));
    }
  }, [dispatch]);

  const handleMultistartFailed = useCallback(
    (next: RefineStatus) => {
      dispatch({ type: "SET_ACTIVE_JOB", job: null });
      setMultistartError(tl("hyp.local.multistartFailed", { message: next.error ?? "unknown error" }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dispatch, lang],
  );

  const handleMultistartPollError = useCallback(
    (err: unknown) => {
      const message = err instanceof ApiError ? err.message : String(err);
      setMultistartError(tl("hyp.local.multistartPollError", { message }));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lang],
  );

  usePollJob({
    status: state.refine,
    setStatus: setRefineStatus,
    statusFn: getMultistartStatus,
    enabled: state.activeJob === "multistart",
    onDone: handleMultistartDone,
    onFailed: handleMultistartFailed,
    onError: handleMultistartPollError,
  });

  function handleMultistartClick() {
    if (jobRunning) return;
    setMultistartError(null);
    const parsed = Number(nStartsInput);
    const nStarts = Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : DEFAULT_N_STARTS;
    postMultistart({ n_starts: nStarts })
      .then((res) => {
        if (res.status === "started") {
          dispatch({ type: "SET_ACTIVE_JOB", job: "multistart" });
          setRefineStatus({ status: "running", elapsed_s: 0, last_event: null, error: null });
        }
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) {
          setMultistartError(tl("hyp.local.multistartBusy"));
          return;
        }
        const message = err instanceof ApiError ? err.message : String(err);
        setMultistartError(tl("hyp.local.multistartError", { message }));
      });
  }

  return (
    <div className="hyp-tab">
      <div className="hyp-tab__head">
        <span className="hyp-tab__title">{t("hyp.title")}</span>
        <span className="hyp-tab__note">{t("hyp.note")}</span>
      </div>

      <table className="hyp-table">
        <thead>
          <tr>
            <th>#</th>
            <th>ID</th>
            <th>{t("col.phases")}</th>
            <th className="num">P</th>
            <th className="num">Rwp</th>
            <th className="num">GOF</th>
            <th className="num">BIC</th>
            <th className="center">{t("col.close")}</th>
            <th>{t("col.status")}</th>
          </tr>
        </thead>
        <tbody>
          {vm.rows.map((row) => (
            <tr
              key={row.id}
              className={`hyp-table__row${state.hyp === row.id ? " hyp-table__row--selected" : ""}`}
              onClick={() => dispatch({ type: "SET_HYP", hyp: row.id })}
            >
              <td>{row.rank}</td>
              <td className="mono">{row.id}</td>
              <td>{row.phases}</td>
              <td className="num">{formatNumber(row.p, 2)}</td>
              <td className="num">{formatNumber(row.rwp, 2)}</td>
              <td className="num">{formatNumber(row.gof, 2)}</td>
              <td className="num">{formatInt(row.bic)}</td>
              <td className="center">
                {row.close && <span className="hyp-table__close-dot">●</span>}
              </td>
              <td className="hyp-table__status">{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="hyp-bottom">
        <BlueprintCard
          heading={`${t("diff.title")} · ${state.hyp} vs ${vm.diff.vs}`}
          className="hyp-bottom__card"
        >
          <table className="diff-table">
            <thead>
              <tr>
                <th>{t("field")}</th>
                <th className="num">{state.hyp}</th>
                <th className="num">{vm.diff.vs}</th>
              </tr>
            </thead>
            <tbody>
              {vm.diff.rows.map((d, i) => (
                <tr key={i}>
                  <td>{d.field}</td>
                  <td className="num">{d.a}</td>
                  <td className={`num${d.changed ? " diff-table__cell--changed" : ""}`}>{d.b}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </BlueprintCard>

        <BlueprintCard
          heading={t("evidence.title")}
          className="hyp-bottom__card"
          bodyStyle={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
        >
          <div className="hyp-multistart">
            <label className="hyp-multistart__n">
              <span className="hyp-multistart__n-label">{tl("hyp.local.nStartsLabel")}</span>
              <input
                type="number"
                min={1}
                aria-label={tl("hyp.local.nStartsLabel")}
                value={nStartsInput}
                disabled={jobRunning}
                onChange={(e) => setNStartsInput(e.target.value)}
              />
            </label>
            <Btn type="button" variant="accent" onClick={handleMultistartClick} disabled={jobRunning}>
              {multistartRunning ? tl("hyp.local.multistarting") : tl("hyp.local.multistart")}
            </Btn>
          </div>
          {multistartError && <div className="hyp-multistart__error">{multistartError}</div>}
          <ScatterChart points={vm.basin?.points} height="120px" emptyLabel={t("evidence.basinPlaceholder")} />
          <div className="hyp-evidence__rows">
            {vm.evidence.map(([k, v], i) => (
              <div key={i} className="hyp-evidence__row">
                <span>{k}</span>
                <span className="hyp-evidence__row-value">{v}</span>
              </div>
            ))}
          </div>
        </BlueprintCard>
      </div>
    </div>
  );
}
