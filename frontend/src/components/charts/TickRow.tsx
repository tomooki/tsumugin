import "./TickRow.css";
import { scaleX, type Domain } from "./path";

interface TickRowProps {
  /** Phase label (132px column, matches the handoff FIT plot geometry). */
  label: string;
  /** Always a `var(--color-*)` token. */
  color: string;
  /** Reflection 2θ positions for this phase (`plot.ticks[label]`). */
  positions?: number[] | null;
  /** Shared x domain with the main plot — required to place real marks. */
  xDomain?: Domain | null;
}

const VIEW_W = 600;
const VIEW_H = 13;

/** One reflection-tick row: a phase label + either real tick marks (when
 * `positions`/`xDomain` are supplied) or the original dashed empty strip
 * (when the phase has no known reflection positions yet — same empty-state
 * discipline as the other chart components). */
export function TickRow({ label, color, positions, xDomain }: TickRowProps) {
  const finitePositions = (positions ?? []).filter((p) => Number.isFinite(p));
  const hasTicks = finitePositions.length > 0 && !!xDomain;

  return (
    <div className="tick-row">
      <span className="tick-row__label">
        <span className="tick-row__swatch" style={{ background: color }} />
        {label}
      </span>
      {hasTicks ? (
        <svg
          className="tick-row__svg"
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={label}
        >
          {finitePositions.map((p, i) => {
            const px = scaleX(p, xDomain!, VIEW_W);
            return (
              <line
                key={i}
                x1={px}
                x2={px}
                y1={0}
                y2={VIEW_H}
                className="tick-row__mark"
                style={{ stroke: color }}
              />
            );
          })}
        </svg>
      ) : (
        <span className="tick-row__strip" style={{ borderColor: color }} />
      )}
    </div>
  );
}
