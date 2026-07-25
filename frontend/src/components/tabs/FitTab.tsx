import type { FitHistoryRow, FitValidityRow } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { BlueprintCard, Chip, MetricCard, PlaceholderPlot } from "../common";
import "./FitTab.css";
import { HistogramChips } from "./HistogramChips";

const TICK_SWATCHES = [
  "var(--color-accent-700)",
  "var(--color-accent-400)",
  "var(--color-neutral-500)",
  "var(--color-neutral-400)",
];

function formatDelta(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function deltaClass(row: FitHistoryRow): string {
  if (row.reverted) return "fit-history__delta fit-history__delta--reverted";
  if (row.delta_rwp < 0) return "fit-history__delta fit-history__delta--negative";
  return "fit-history__delta";
}

function validityChipVariant(status: FitValidityRow["status"]): "accent" | "inverted" {
  return status === "pass" ? "accent" : "inverted";
}

/** See docs/design/gui-workbench/handoff/README.md §Centre pane item 1 (FIT):
 * six metric cards, histogram chips, main fit/residual plot, refinement
 * history + physical validity gate. All data comes from
 * `viewModel.fit` (GET /api/viewmodel, api-contract.md). */
export function FitTab() {
  const { t } = useI18n();
  const { state, dispatch } = useStore();
  const fit = state.viewModel?.fit;

  const metrics = fit?.metrics ?? [];
  const histograms = fit?.histograms ?? [];
  const phaseTicks = fit?.phase_ticks ?? [];
  const history = fit?.history ?? [];
  const validity = fit?.validity ?? [];
  const twoTheta = fit?.two_theta ?? { min: 0, max: 0 };

  const step = (twoTheta.max - twoTheta.min) / 4;
  const scaleMarks =
    step > 0
      ? [0, 1, 2, 3, 4].map((i) => (twoTheta.min + i * step).toFixed(1))
      : [twoTheta.min.toFixed(1), twoTheta.max.toFixed(1)];

  return (
    <div className="fit-tab">
      <div className="fit-tab__metrics">
        {metrics.map((m) => (
          <MetricCard key={m.key} label={m.label} value={m.value} note={m.note} />
        ))}
      </div>

      <HistogramChips
        histograms={histograms}
        active={state.hist}
        onSelect={(hist) => dispatch({ type: "SET_HIST", hist })}
        trailing={fit?.limits_note}
      />

      <BlueprintCard
        className="fit-tab__plot-card"
        heading={t("fit.plotTitle")}
        note={t("fit.plotNote")}
        bodyStyle={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
      >
        <div className="fit-tab__plot-layout">
          <div className="fit-tab__axis-label">{t("fit.intensity")}</div>
          <div className="fit-tab__plot-col">
            <PlaceholderPlot label={t("fit.plotPlaceholder")} height="220px" />
            <div className="fit-tab__ticks">
              {phaseTicks.map((label, i) => (
                <div className="fit-tab__tick-row" key={label}>
                  <span className="fit-tab__tick-label">
                    <span
                      className="fit-tab__tick-swatch"
                      style={{ background: TICK_SWATCHES[i % TICK_SWATCHES.length] }}
                    />
                    {label}
                  </span>
                  <span
                    className="fit-tab__tick-strip"
                    style={{ borderColor: TICK_SWATCHES[i % TICK_SWATCHES.length] }}
                  />
                </div>
              ))}
            </div>
            <PlaceholderPlot label={t("fit.residualPlaceholder")} height="74px" />
            <div className="fit-tab__scale">
              {scaleMarks.map((mark, i) => (
                <span key={mark + i}>
                  {mark}
                  {i === scaleMarks.length - 1 ? " · 2θ / deg" : ""}
                </span>
              ))}
            </div>
          </div>
        </div>
      </BlueprintCard>

      <div className="fit-tab__bottom">
        <BlueprintCard heading={t("fit.historyTitle")}>
          <table className="fit-history">
            <thead>
              <tr>
                <th className="fit-history__th fit-history__th--left">{t("col.stage")}</th>
                <th className="fit-history__th fit-history__th--right">Rwp</th>
                <th className="fit-history__th fit-history__th--right">ΔRwp</th>
                <th className="fit-history__th fit-history__th--left">{t("col.guard")}</th>
              </tr>
            </thead>
            <tbody>
              {history.map((row) => (
                <tr key={row.stage}>
                  <td className="fit-history__td">{row.stage}</td>
                  <td className="fit-history__td fit-history__td--right">{row.rwp.toFixed(2)}</td>
                  <td className={`fit-history__td fit-history__td--right ${deltaClass(row)}`}>
                    {formatDelta(row.delta_rwp)}
                  </td>
                  <td className="fit-history__td fit-history__guard">{row.guard}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </BlueprintCard>

        <BlueprintCard heading={t("fit.validityTitle")}>
          <div className="fit-validity">
            {validity.map((row) => (
              <div className="fit-validity__row" key={row.check}>
                <span>{row.check}</span>
                <span className="fit-validity__detail">{row.detail}</span>
                <Chip variant={validityChipVariant(row.status)}>
                  {row.status === "pass" ? t("validity.pass") : t("validity.warn")}
                </Chip>
              </div>
            ))}
            <div className="fit-validity__note">{t("fit.validityNote")}</div>
          </div>
        </BlueprintCard>
      </div>
    </div>
  );
}
