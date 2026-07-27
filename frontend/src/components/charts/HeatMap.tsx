import { formatNumber } from "../../api/format";
import type { MemMap } from "../../api/types";
import { PlaceholderPlot } from "../common";
import "./HeatMap.css";

interface HeatMapProps {
  map: MemMap | null | undefined;
  height?: string;
  emptyLabel: string;
}

// Discrete neutral↔accent ramp (api-contract.md §MEM 密度マップ: "トークンの neutral↔accent
// ランプで塗り分け") — tokens only, no raw hex (frontend/src/styles/tokens.css is the single
// place hex values may live).
const RAMP = [
  "var(--color-neutral-100)",
  "var(--color-accent-200)",
  "var(--color-accent-300)",
  "var(--color-accent-400)",
  "var(--color-accent-500)",
  "var(--color-accent-600)",
  "var(--color-accent-700)",
  "var(--color-accent-800)",
];

const VIEW = 200;

function bucketColor(value: number, vmin: number, vmax: number): string {
  if (!Number.isFinite(value) || vmax <= vmin) return RAMP[0];
  const t = Math.min(1, Math.max(0, (value - vmin) / (vmax - vmin)));
  const idx = Math.min(RAMP.length - 1, Math.floor(t * RAMP.length));
  return RAMP[idx];
}

/** STRUCTURE tab's MEM DENSITY card (V3b, FR-601, api-contract.md §MEM 密度マップ): a c-axis
 * mid-slice density heatmap. `map.values` is already ≤128×128 (server-side decimation, see
 * workbench/density.py `extract_mem_map`) — cells are drawn 1 sample per SVG unit, so the
 * viewBox scales with the grid rather than a fixed domain (unlike ScatterChart/LinePlot,
 * which plot continuous axes). Falls back to the shared PlaceholderPlot empty-state when
 * `map` is null (MEM not yet run) or empty. */
export function HeatMap({ map, height, emptyLabel }: HeatMapProps) {
  if (!map || map.nx <= 0 || map.ny <= 0 || map.values.length === 0) {
    return <PlaceholderPlot label={emptyLabel} height={height} />;
  }
  const { nx, ny, values, vmin, vmax, unit } = map;
  const cell = VIEW / Math.max(nx, ny);

  return (
    <div className="heat-map" style={{ minHeight: height }}>
      <svg
        className="heat-map__svg"
        viewBox={`0 0 ${nx * cell} ${ny * cell}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={emptyLabel}
      >
        {values.map((row, i) =>
          row.map((v, j) => (
            <rect
              key={`${i}-${j}`}
              x={i * cell}
              y={j * cell}
              width={cell}
              height={cell}
              fill={bucketColor(v, vmin, vmax)}
            />
          )),
        )}
      </svg>
      <div className="heat-map__legend">
        <span className="heat-map__legend-swatches">
          {RAMP.map((color) => (
            <span key={color} className="heat-map__swatch" style={{ background: color }} />
          ))}
        </span>
        <span className="heat-map__legend-text">
          {formatNumber(vmin, 2)} – {formatNumber(vmax, 2)} {unit}
        </span>
      </div>
    </div>
  );
}
