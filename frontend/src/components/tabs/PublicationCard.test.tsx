import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PublicationViewModel } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { PublicationCard } from "./PublicationCard";

function makePublication(overrides: Partial<PublicationViewModel> = {}): PublicationViewModel {
  return {
    claims_version: "fit-then-judge/1B/1",
    policy: "D-1A/1",
    n_values: 2,
    n_publishable: 1,
    rows: [
      {
        key: "cell:P.a",
        param_class: "cell",
        phase: "P",
        label: null,
        axis: "a",
        value: 5.0,
        esd: 0.001,
        unit: "angstrom",
        scope: "relative_within_sample",
        determinacy: "esd_only",
        publishable: true,
        gate: [],
      },
      {
        key: "coord:P.O1.x",
        param_class: "coord",
        phase: "P",
        label: "O1",
        axis: "x",
        value: 0.25,
        esd: 0.002,
        unit: "fractional",
        scope: "absolute",
        determinacy: "initial_value_dependent",
        publishable: false,
        gate: ["initial_value_dependence"],
      },
    ],
    judgment_requests: [
      {
        id: "initial_value_dependence",
        kind: "initial_value_dependence",
        blocking: true,
        n_blocked: 1,
        trigger: "values split between starts",
        candidates: ["hold", "fix_parameter", "remeasure"],
        default_answer: "hold",
      },
    ],
    sidecar: "/run/refined.claims.json",
    sidecar_reason: "",
    error: null,
    ...overrides,
  };
}

function renderCard(publication?: PublicationViewModel) {
  return render(
    <I18nProvider lang="en">
      <PublicationCard publication={publication} />
    </I18nProvider>,
  );
}

describe("PublicationCard", () => {
  it("renders nothing before a refinement (no fabricated state)", () => {
    const { container } = renderCard(undefined);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows every value together with its state, never bare", () => {
    renderCard(makePublication());
    expect(screen.getByText("1 / 2 publishable")).toBeInTheDocument();
    const rows = screen.getAllByTestId("publication-row");
    expect(rows).toHaveLength(2);
    const held = within(rows[1]);
    expect(held.getByText("held")).toBeInTheDocument();
    expect(held.getByText("initial_value_dependent")).toBeInTheDocument();
    expect(held.getByText(/initial_value_dependence/)).toBeInTheDocument();
    // relative lattice values are marked as such
    expect(within(rows[0]).getByText("(rel)")).toBeInTheDocument();
  });

  it("shows judgment requests read-only — no answer or approve controls", () => {
    renderCard(makePublication());
    const card = screen.getByTestId("publication-card");
    const req = within(screen.getByTestId("judgment-request"));
    expect(req.getByText("blocking")).toBeInTheDocument();
    expect(req.getByText(/hold \/ fix_parameter \/ remeasure/)).toBeInTheDocument();
    expect(within(card).queryAllByRole("button")).toHaveLength(0);
    expect(card.textContent).toContain("decision 2");
  });

  it("renders unknown vocabulary raw instead of crashing", () => {
    const pub = makePublication();
    pub.rows[0] = { ...pub.rows[0], determinacy: "brand_new_state", scope: "galactic" };
    pub.judgment_requests[0] = { ...pub.judgment_requests[0], kind: "future_kind" };
    renderCard(pub);
    expect(screen.getByText("brand_new_state")).toBeInTheDocument();
    expect(screen.getByText("future_kind")).toBeInTheDocument();
  });

  it("says loudly when the state could not be built", () => {
    renderCard(makePublication({ error: "RuntimeError: boom", rows: [], n_values: 0, n_publishable: 0 }));
    expect(screen.getByRole("alert").textContent).toContain("RuntimeError: boom");
    expect(screen.getByText("0 / 0 publishable")).toBeInTheDocument();
  });
});
