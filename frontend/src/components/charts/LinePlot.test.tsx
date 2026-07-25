import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LinePlot, type LinePlotSeries } from "./LinePlot";

const LINE_SERIES: LinePlotSeries[] = [
  { x: [0, 1, 2], y: [0, 1, 0], kind: "line", label: "ycalc", color: "var(--color-accent-600)" },
];

const POINT_SERIES: LinePlotSeries[] = [
  { x: [0, 1, 2], y: [0, 1, 0], kind: "points", label: "yobs", color: "var(--color-neutral-700)" },
];

describe("LinePlot — series present", () => {
  it("renders an svg <path> for a line-kind series", () => {
    const { container } = render(<LinePlot series={LINE_SERIES} emptyLabel="empty" />);
    const path = container.querySelector("svg path.line-plot__line");
    expect(path).not.toBeNull();
    expect(path!.getAttribute("d")).not.toBe("");
  });

  it("renders svg <circle> points for a points-kind series", () => {
    const { container } = render(<LinePlot series={POINT_SERIES} emptyLabel="empty" />);
    const points = container.querySelectorAll("svg circle.line-plot__point");
    expect(points.length).toBe(3);
  });

  it("does not render the empty-state placeholder frame when data is present", () => {
    const { container } = render(<LinePlot series={LINE_SERIES} emptyLabel="empty" />);
    expect(container.querySelector(".placeholder-plot")).toBeNull();
  });
});

describe("LinePlot — no data → empty-state", () => {
  it("renders the PlaceholderPlot dashed frame + label for series=null", () => {
    const { container } = render(<LinePlot series={null} emptyLabel="NO CURVE YET" />);
    expect(container.querySelector(".placeholder-plot__frame")).not.toBeNull();
    expect(screen.getByText("NO CURVE YET")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders the empty-state for an empty series array", () => {
    const { container } = render(<LinePlot series={[]} emptyLabel="NO CURVE YET" />);
    expect(container.querySelector(".placeholder-plot__frame")).not.toBeNull();
  });

  it("renders the empty-state when every series has zero-length x/y (no fabricated curve for empty data)", () => {
    const { container } = render(
      <LinePlot series={[{ x: [], y: [], kind: "line", label: "ycalc" }]} emptyLabel="NO CURVE YET" />,
    );
    expect(container.querySelector(".placeholder-plot__frame")).not.toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders the empty-state when every point is non-finite (no interpolated line across all-NaN data)", () => {
    const { container } = render(
      <LinePlot series={[{ x: [0, 1], y: [NaN, NaN], kind: "line", label: "ycalc" }]} emptyLabel="NO CURVE YET" />,
    );
    expect(container.querySelector(".placeholder-plot__frame")).not.toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });
});

describe("LinePlot — axis", () => {
  it("shows tick labels when showAxis is true (default)", () => {
    const { container } = render(
      <LinePlot series={LINE_SERIES} emptyLabel="empty" xDomain={{ min: 0, max: 2 }} yDomain={{ min: 0, max: 1 }} />,
    );
    expect(container.querySelector(".line-plot__x-axis")).not.toBeNull();
    expect(container.querySelector(".line-plot__y-axis")).not.toBeNull();
  });

  it("omits the axis rows when showAxis is false", () => {
    const { container } = render(<LinePlot series={LINE_SERIES} emptyLabel="empty" showAxis={false} />);
    expect(container.querySelector(".line-plot__x-axis")).toBeNull();
    expect(container.querySelector(".line-plot__y-axis")).toBeNull();
  });
});
