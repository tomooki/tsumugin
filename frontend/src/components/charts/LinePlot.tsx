import { useMemo } from "react";
import { PlaceholderPlot } from "../common";
import "./LinePlot.css";
import { buildPath, domainFromValues, scaleX, scaleY, type Domain } from "./path";

export interface LinePlotSeries {
  x: number[];
  y: number[];
  kind: "points" | "line";
  label: string;
  /** CSS colour — always a `var(--color-*)` token, never a raw hex. */
  color?: string;
  dashed?: boolean;
}

interface LinePlotProps {
  series: LinePlotSeries[] | null;
  height?: string;
  emptyLabel: string;
  xDomain?: Domain;
  yDomain?: Domain;
  /** Draws a minimal mono 10px tick row (bottom, x) / column (left, y).
   * Default on for standalone charts (SeriesChart); FitTab passes `false`
   * for the main/residual panels, which already have their own external 2θ
   * scale row + rotated Intensity label per the handoff geometry. */
  showAxis?: boolean;
  className?: string;
}

const VIEW_W = 600;
const VIEW_H = 200;

function hasFiniteData(series: LinePlotSeries[] | null | undefined): series is LinePlotSeries[] {
  if (!series || series.length === 0) return false;
  return series.some(
    (s) => s.x.length > 0 && s.x.length === s.y.length && s.x.some((v, i) => Number.isFinite(v) && Number.isFinite(s.y[i])),
  );
}

function formatTick(n: number): string {
  if (!Number.isFinite(n)) return "";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs < 0.01 || abs >= 100000)) return n.toExponential(1);
  return abs >= 100 ? n.toFixed(0) : n.toFixed(2);
}

/** Generic XY line/point chart. Renders the same dashed empty-state as
 * PlaceholderPlot when `series` is null/empty/all-non-finite (REQ-GUI-014:
 * never fake a curve — an absent real one degrades to the placeholder
 * frame, not a synthetic one). */
export function LinePlot({
  series,
  height,
  emptyLabel,
  xDomain,
  yDomain,
  showAxis = true,
  className,
}: LinePlotProps) {
  const domains = useMemo(() => {
    if (!hasFiniteData(series)) return null;
    const allX = series.flatMap((s) => s.x);
    const allY = series.flatMap((s) => s.y);
    return {
      x: xDomain ?? domainFromValues(allX, 0.02),
      y: yDomain ?? domainFromValues(allY, 0.08),
    };
  }, [series, xDomain, yDomain]);

  if (!domains) {
    return <PlaceholderPlot label={emptyLabel} height={height} />;
  }

  const xTicks = [domains.x.min, (domains.x.min + domains.x.max) / 2, domains.x.max];
  const yTicks = [domains.y.max, (domains.y.min + domains.y.max) / 2, domains.y.min];

  return (
    <div className={`line-plot${className ? ` ${className}` : ""}`} style={{ minHeight: height }}>
      <div className="line-plot__row">
        {showAxis && (
          <div className="line-plot__y-axis">
            {yTicks.map((v, i) => (
              <span key={i}>{formatTick(v)}</span>
            ))}
          </div>
        )}
        <svg
          className="line-plot__svg"
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={emptyLabel}
        >
          {series!.map((s, i) => {
            if (s.x.length === 0 || s.x.length !== s.y.length) return null;
            if (s.kind === "points") {
              return (
                <g key={i} data-series-label={s.label}>
                  {s.x.map((x, j) => {
                    const y = s.y[j];
                    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
                    return (
                      <circle
                        key={j}
                        cx={scaleX(x, domains.x, VIEW_W)}
                        cy={scaleY(y, domains.y, VIEW_H)}
                        r={1.6}
                        className="line-plot__point"
                        style={s.color ? { fill: s.color } : undefined}
                      />
                    );
                  })}
                </g>
              );
            }
            const d = buildPath(s.x, s.y, domains.x, domains.y, VIEW_W, VIEW_H);
            if (!d) return null;
            return (
              <path
                key={i}
                d={d}
                data-series-label={s.label}
                className={`line-plot__line${s.dashed ? " line-plot__line--dashed" : ""}`}
                style={s.color ? { stroke: s.color } : undefined}
              />
            );
          })}
        </svg>
      </div>
      {showAxis && (
        <div className="line-plot__x-axis">
          {xTicks.map((v, i) => (
            <span key={i}>{formatTick(v)}</span>
          ))}
        </div>
      )}
    </div>
  );
}
