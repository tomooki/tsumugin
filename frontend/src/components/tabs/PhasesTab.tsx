import { useState } from "react";
import { ApiError, getViewModel, postPhaseSettings, postRemovePhase } from "../../api/client";
import type { PhaseCell, PhaseRow } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { Btn } from "../common";
import "./PhasesTab.css";
import { ph } from "./PhasesTab.strings";

/** File name only — the table must not stretch on a long absolute path. */
function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function formatCell(cell: PhaseCell): string {
  return `a ${cell.a} · b ${cell.b} · c ${cell.c} · α ${cell.alpha} · β ${cell.beta} · γ ${cell.gamma}`;
}

/** PHASES tab (api-contract.md §PHASES タブ) — the home for phase-scoped
 * refinement control.
 *
 * The left rail's PHASES IN MODEL answers "which phases are present"; this tab
 * answers "what does each phase release". Deliberately narrow: `refine_cell`
 * is the ONLY per-phase switch `engine._apply_stage` actually reads, so it is
 * the only editable control here. size/microstrain, preferred orientation and
 * the temperature-difference Dij are physically per-phase but the engine
 * applies them to every phase at once — putting checkboxes on them would be a
 * control that silently does nothing, so they appear read-only in the
 * "stages touching this phase" column instead (see phases.scopeNote). */
export function PhasesTab() {
  const { lang } = useI18n();
  const { state, dispatch } = useStore();
  const phases: PhaseRow[] = state.viewModel?.phases ?? [];

  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Spec edits are rejected by the backend while a job holds the slot
  // (`_guard_project_editable`) — pre-disable rather than let the click 409.
  const jobRunning = state.refine?.status === "running";

  function t(key: Parameters<typeof ph>[1], vars?: Record<string, string | number>): string {
    return ph(lang, key, vars);
  }

  async function refresh() {
    const viewModel = await getViewModel();
    dispatch({ type: "SET_VIEW_MODEL", viewModel });
  }

  function handleToggleRefineCell(row: PhaseRow) {
    if (jobRunning) return;
    setError(null);
    setPending(row.name);
    postPhaseSettings(row.name, { refine_cell: !(row.refine_cell ?? true) })
      .then(async (shell) => {
        dispatch({ type: "SET_SHELL", shell });
        await refresh();
      })
      .catch((err: unknown) => {
        const message = err instanceof ApiError ? err.message : String(err);
        setError(t("phases.error", { phase: row.name, message }));
      })
      .finally(() => setPending(null));
  }

  function handleRemove(row: PhaseRow) {
    if (jobRunning) return;
    setError(null);
    setPending(row.name);
    postRemovePhase(row.name)
      .then(async (shell) => {
        dispatch({ type: "SET_SHELL", shell });
        await refresh();
      })
      .catch((err: unknown) => {
        const message = err instanceof ApiError ? err.message : String(err);
        setError(t("phases.error", { phase: row.name, message }));
      })
      .finally(() => setPending(null));
  }

  return (
    <div className="phases-tab">
      <div className="phases-tab__head">
        <span className="phases-tab__title">{t("phases.title")}</span>
        <span className="phases-tab__note">{t("phases.note")}</span>
      </div>

      {jobRunning && <div className="phases-tab__message">{t("phases.busy")}</div>}
      {error && <div className="phases-tab__message phases-tab__message--error">{error}</div>}

      {phases.length === 0 ? (
        <div className="phases-tab__empty">{t("phases.empty")}</div>
      ) : (
        <div className="phases-tab__scroll">
          <table className="phases-table">
            <thead>
              <tr>
                <th>{t("phases.col.name")}</th>
                <th>{t("phases.col.sg")}</th>
                <th className="num">{t("phases.col.wt")}</th>
                <th>{t("phases.col.cell")}</th>
                <th className="center">{t("phases.col.refineCell")}</th>
                <th>{t("phases.col.source")}</th>
                <th>{t("phases.col.stages")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {phases.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span className={`phases-swatch phases-swatch--${row.swatch}`} />
                    {row.name}
                  </td>
                  <td className="mono">{row.space_group || "―"}</td>
                  <td className="num mono">{row.wt_frac}</td>
                  <td className="mono phases-table__cell">
                    {row.cell ? (
                      formatCell(row.cell)
                    ) : (
                      <span className="phases-table__muted">{t("phases.cellPending")}</span>
                    )}
                  </td>
                  <td className="center">
                    <input
                      type="checkbox"
                      className="phases-checkbox"
                      checked={row.refine_cell ?? true}
                      disabled={jobRunning || pending === row.name}
                      title={t("phases.refineCellTip")}
                      aria-label={t("phases.refineCellLabel", { phase: row.name })}
                      onChange={() => handleToggleRefineCell(row)}
                    />
                  </td>
                  <td className="mono phases-table__source" title={row.structure_path}>
                    {row.structure_path ? baseName(row.structure_path) : "―"}
                  </td>
                  <td className="phases-table__stages">
                    {(row.stages ?? []).length ? (row.stages ?? []).join(" · ") : "―"}
                  </td>
                  <td className="right">
                    <Btn
                      type="button"
                      variant="outline"
                      disabled={jobRunning || pending === row.name}
                      title={t("phases.removeTip", { phase: row.name })}
                      onClick={() => handleRemove(row)}
                    >
                      {pending === row.name ? t("phases.removing") : t("phases.remove")}
                    </Btn>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="phases-tab__scope-note">{t("phases.scopeNote")}</div>
    </div>
  );
}
