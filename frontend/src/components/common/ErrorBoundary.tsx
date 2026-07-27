import { Component, type ErrorInfo, type ReactNode } from "react";
import "./ErrorBoundary.css";

interface Props {
  /** Shown above the message so the user knows *which* pane failed. */
  label: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Contains a render error to one pane instead of blanking the whole app.
 *
 * React unmounts the *entire* tree when any component throws during render and
 * nothing catches it. A single bad number (e.g. `two_theta: {min: null}` on a
 * freshly created project → `null.toFixed()`) therefore produced a completely
 * white window with no way to recover — the failure mode a user actually hit.
 *
 * Individual null-safety fixes are still the right first line of defence
 * (see api/format.ts); this boundary is the structural backstop so the next
 * unforeseen shape mismatch degrades to one broken panel with a visible
 * message, keeping the rest of the workbench (and the ledger/close controls)
 * usable.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Console only — the app has no telemetry sink, and the message itself is
    // already rendered for the user below.
    console.error(`[${this.props.label}] render failed`, error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="error-boundary" role="alert">
        <div className="error-boundary__label">{this.props.label} — render error</div>
        <div className="error-boundary__message">{error.message}</div>
        <button
          type="button"
          className="error-boundary__retry"
          onClick={() => this.setState({ error: null })}
        >
          RETRY
        </button>
      </div>
    );
  }
}
