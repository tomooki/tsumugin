import type { ChartSeriesData } from "../../api/types";
import { LinePlot, type LinePlotSeries } from "./LinePlot";
import "./SeriesChart.css";

// Cycle order mirrors FitTab's TICK_SWATCHES (accent-700 → accent-400 →
// neutral-500 → neutral-400) so multi-series charts read consistently with
// the FIT tick rows.
const SERIES_COLORS = [
  "var(--color-accent-700)",
  "var(--color-accent-400)",
  "var(--color-neutral-500)",
  "var(--color-neutral-400)",
];

interface SeriesChartProps {
  series: ChartSeriesData | null | undefined;
  height?: string;
  emptyLabel: string;
}

/** SEQUENCE tab folded-line chart: one line per `series.ys[i]`, sharing
 * `series.x`. Falls back to the LinePlot empty-state when `series` is
 * null/undefined (handoff README: "series: null = データ未取得"). */
export function SeriesChart({ series, height, emptyLabel }: SeriesChartProps) {
  const linePlotSeries: LinePlotSeries[] | null = series
    ? series.ys.map((y, i) => ({
        x: series.x,
        y,
        kind: "line" as const,
        label: series.labels[i] ?? `series ${i + 1}`,
        color: SERIES_COLORS[i % SERIES_COLORS.length],
      }))
    : null;

  return (
    <div className="series-chart">
      <LinePlot series={linePlotSeries} height={height} emptyLabel={emptyLabel} />
      {series && series.labels.length > 1 && (
        <div className="series-chart__legend">
          {series.labels.map((label, i) => (
            <span key={label} className="series-chart__legend-item">
              <span
                className="series-chart__legend-swatch"
                style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }}
              />
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
