import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom({ fail }: { fail: boolean }): React.ReactElement {
  if (fail) throw new Error("kaboom: null.toFixed");
  return <div>healthy pane</div>;
}

describe("ErrorBoundary — one bad pane must not blank the app", () => {
  beforeEach(() => {
    // React logs the caught error; keep test output readable.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary label="CENTRE">
        <Boom fail={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("healthy pane")).toBeInTheDocument();
  });

  it("shows the pane label and message instead of unmounting on a render error", () => {
    render(
      <ErrorBoundary label="CENTRE">
        <Boom fail />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/CENTRE/)).toBeInTheDocument();
    expect(screen.getByText(/kaboom: null.toFixed/)).toBeInTheDocument();
  });

  it("keeps sibling content alive (the whole window does not go white)", () => {
    render(
      <div>
        <div>sibling survives</div>
        <ErrorBoundary label="CENTRE">
          <Boom fail />
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByText("sibling survives")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("RETRY clears the error so the subtree can render again", async () => {
    const user = userEvent.setup();
    let shouldFail = true;
    function Flaky() {
      if (shouldFail) throw new Error("first render fails");
      return <div>recovered pane</div>;
    }
    render(
      <ErrorBoundary label="CENTRE">
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();

    shouldFail = false; // 原因が解消された状態を模す
    await user.click(screen.getByRole("button", { name: "RETRY" }));
    expect(screen.getByText("recovered pane")).toBeInTheDocument();
  });
});
