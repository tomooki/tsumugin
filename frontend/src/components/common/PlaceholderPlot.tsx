import type { CSSProperties } from "react";
import "./PlaceholderPlot.css";

interface PlaceholderPlotProps {
  label: string;
  axis?: string[];
  height?: string;
  style?: CSSProperties;
}

/** Dashed-frame stand-in for a real chart (fit/residual, frame series, MEM
 * section, basin plot, …). Handoff README: "every plot/map region is a
 * dashed frame with a label" — keep the frame geometry + axis labelling so a
 * real chart component can drop in later without a layout change. */
export function PlaceholderPlot({ label, axis, height, style }: PlaceholderPlotProps) {
  return (
    <div className="placeholder-plot" style={{ minHeight: height, ...style }}>
      <div className="placeholder-plot__frame">
        <span className="placeholder-plot__label">{label}</span>
      </div>
      {axis && axis.length > 0 && (
        <div className="placeholder-plot__axis">
          {axis.map((a) => (
            <span key={a}>{a}</span>
          ))}
        </div>
      )}
    </div>
  );
}
