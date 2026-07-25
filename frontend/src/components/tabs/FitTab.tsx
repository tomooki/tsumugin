import { formatNumber, formatSigned } from "../../api/format";
import type { FitHistoryRow, FitValidityRow } from "../../api/types";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { LinePlot, type LinePlotSeries } from "../charts/LinePlot";
import { TickRow } from "../charts/TickRow";
import { BlueprintCard, Chip, MetricCard } from "../common";
import "./FitTab.css";
import { HistogramChips } from "./HistogramChips";

const TICK_SWATCHES = [
  "var(--color-accent-700)",
  "var(--color-accent-400)",
  "var(--color-neutral-500)",
  "var(--color-neutral-400)",
];

function deltaClass(row: FitHistoryRow): string {
  if (row.reverted) return "fit-history__delta fit-history__delta--reverted";
  if (row.delta_rwp !== null && row.delta_rwp < 0) {
    return "fit-history__delta fit-history__delta--negative";
  }
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

  // Real curve for the active histogram (api-contract.md fit.plot: hist id →
  // {x,yobs,ycalc,ybkg,residual,ticks} | null). null/undefined = no curve
  // yet — LinePlot/TickRow fall back to the dashed empty-state on their own.
  const plot = fit?.plot?.[state.hist];

  // The 2θ scale row (and the shared x domain for the plot/residual/tick
  // panels) follows the real curve's x range once it exists; before that it
  // falls back to fit.two_theta, per the task brief.
  const xRange =
    plot && plot.x.length > 0 ? { min: Math.min(...plot.x), max: Math.max(...plot.x) } : twoTheta;

  const step = (xRange.max - xRange.min) / 4;
  const scaleMarks =
    step > 0
      ? [0, 1, 2, 3, 4].map((i) => (xRange.min + i * step).toFixed(1))
      : [xRange.min.toFixed(1), xRange.max.toFixed(1)];

  const mainSeries: LinePlotSeries[] | null = plot
    ? [
        { x: plot.x, y: plot.yobs, kind: "points", label: "Yobs", color: "var(--color-neutral-700)" },
        ...(plot.ycalc
          ? [{ x: plot.x, y: plot.ycalc, kind: "line" as const, label: "Ycalc", color: "var(--color-accent-600)" }]
          : []),
        ...(plot.ybkg
          ? [
              {
                x: plot.x,
                y: plot.ybkg,
                kind: "line" as const,
                label: "Ybkg",
                color: "var(--color-neutral-400)",
                dashed: true,
              },
            ]
          : []),
      ]
    : null;

  const residualSeries: LinePlotSeries[] | null = plot?.residual
    ? [{ x: plot.x, y: plot.residual, kind: "line", label: "Δ", color: "var(--color-neutral-600)" }]
    : null;

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
            <LinePlot
              series={mainSeries}
              height="220px"
              emptyLabel={t("fit.plotPlaceholder")}
              xDomain={plot ? xRange : undefined}
              showAxis={false}
            />
            <div className="fit-tab__ticks">
              {phaseTicks.map((label, i) => (
                <TickRow
                  key={label}
                  label={label}
                  color={TICK_SWATCHES[i % TICK_SWATCHES.length]}
                  positions={plot?.ticks?.[label]}
                  xDomain={plot ? xRange : undefined}
                />
              ))}
            </div>
            <LinePlot
              series={residualSeries}
              height="74px"
              emptyLabel={t("fit.residualPlaceholder")}
              xDomain={plot ? xRange : undefined}
              showAxis={false}
            />
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
                  <td className="fit-history__td fit-history__td--right">{formatNumber(row.rwp, 2)}</td>
                  <td className={`fit-history__td fit-history__td--right ${deltaClass(row)}`}>
                    {formatSigned(row.delta_rwp, 2)}
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
