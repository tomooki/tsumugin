import type { BasinPoint } from "../../api/types";
import { PlaceholderPlot } from "../common";
import "./ScatterChart.css";
import { domainFromValues, scaleX, scaleY } from "./path";

interface ScatterChartProps {
  points: BasinPoint[] | null | undefined;
  height?: string;
  emptyLabel: string;
}

const VIEW_W = 400;
const VIEW_H = 200;

/** HYPOTHESES tab basin scatter (multistart lattice basins). Falls back to
 * the PlaceholderPlot empty-state when `points` is null/undefined/empty, or
 * when every point is non-finite. */
export function ScatterChart({ points, height, emptyLabel }: ScatterChartProps) {
  const finite = (points ?? []).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (finite.length === 0) {
    return <PlaceholderPlot label={emptyLabel} height={height} />;
  }

  const xDomain = domainFromValues(
    finite.map((p) => p.x),
    0.15,
  );
  const yDomain = domainFromValues(
    finite.map((p) => p.y),
    0.15,
  );

  return (
    <div className="scatter-chart" style={{ minHeight: height }}>
      <svg
        className="scatter-chart__svg"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={emptyLabel}
      >
        {finite.map((p, i) => {
          const px = scaleX(p.x, xDomain, VIEW_W);
          const py = scaleY(p.y, yDomain, VIEW_H);
          return (
            <g key={i}>
              <circle cx={px} cy={py} r={3} className="scatter-chart__point" />
              <text x={px + 5} y={py - 5} className="scatter-chart__label">
                {p.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
