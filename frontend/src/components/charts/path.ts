// Pure geometry helpers for the SVG chart components (LinePlot/TickRow/
// ScatterChart). No React, no DOM — unit-tested in isolation (path.test.ts).

export interface Domain {
  min: number;
  max: number;
}

/** Map a domain value to a pixel coordinate in [0, size]. `invert` flips the
 * axis (SVG y grows downward, so the y-axis scale always inverts). A
 * zero-span domain (min === max) maps everywhere to the midpoint rather than
 * dividing by zero. */
function scaleValue(value: number, domain: Domain, size: number, invert: boolean): number {
  const span = domain.max - domain.min;
  if (span === 0) return size / 2;
  const t = (value - domain.min) / span;
  return invert ? size - t * size : t * size;
}

export function scaleX(value: number, domain: Domain, width: number): number {
  return scaleValue(value, domain, width, false);
}

export function scaleY(value: number, domain: Domain, height: number): number {
  return scaleValue(value, domain, height, true);
}

/** Build an SVG path `d` string for a polyline through (xs[i], ys[i]).
 * Non-finite points (NaN/±Infinity) break the line into a new subpath rather
 * than being connected across — a real gap in the data should not render as
 * a straight line spanning it. Mismatched-length or empty inputs return "". */
export function buildPath(
  xs: number[],
  ys: number[],
  xDomain: Domain,
  yDomain: Domain,
  width: number,
  height: number,
): string {
  if (!Array.isArray(xs) || !Array.isArray(ys) || xs.length === 0 || xs.length !== ys.length) {
    return "";
  }

  let d = "";
  let penDown = false;
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i];
    const y = ys[i];
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      penDown = false;
      continue;
    }
    const px = scaleX(x, xDomain, width);
    const py = scaleY(y, yDomain, height);
    d += `${penDown ? " L" : "M"}${px.toFixed(2)},${py.toFixed(2)}`;
    penDown = true;
  }
  return d;
}

/** Domain that spans the finite values in `values`, padded by `pad` fraction
 * of the span on each side. Falls back to [0, 1] for an empty/all-non-finite
 * input, and to a unit-wide domain centred on the single value when every
 * finite value is identical (both avoid a zero-span domain reaching callers
 * that don't handle it, without buildPath itself needing a special case). */
export function domainFromValues(values: number[], pad = 0.05): Domain {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return { min: 0, max: 1 };
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  if (min === max) return { min: min - 1, max: max + 1 };
  const span = max - min;
  return { min: min - span * pad, max: max + span * pad };
}
