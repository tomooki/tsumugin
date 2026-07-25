import { useCallback, useEffect } from "react";
import { ApiError, getState, getViewModel, postMode } from "./api/client";
import type { GuiMode } from "./api/types";
import { CentreCanvas } from "./components/shell/CentreCanvas";
import { ContextBar } from "./components/shell/ContextBar";
import { LeftRail } from "./components/shell/LeftRail";
import "./components/shell/shell.css";
import { StatusBar } from "./components/shell/StatusBar";
import { TitleBar } from "./components/shell/TitleBar";
import { RightPane } from "./components/right/RightPane";
import { WelcomeScreen } from "./components/welcome/WelcomeScreen";
import { I18nProvider } from "./i18n";
import { StoreProvider, useStore } from "./state/store";

function AppShell() {
  const { state, dispatch } = useStore();

  // Shared by the initial mount fetch and WelcomeScreen's onReady (fired
  // after project create/open/demo succeeds) — both need the same
  // "GET state + viewmodel, dispatch, surface errors" sequence.
  const refetchWorkbench = useCallback(async () => {
    dispatch({ type: "SET_LOADING", loading: true });
    try {
      const [shell, viewModel] = await Promise.all([getState(), getViewModel()]);
      dispatch({ type: "SET_SHELL", shell });
      dispatch({ type: "SET_VIEW_MODEL", viewModel });
      dispatch({ type: "SET_ERROR", error: null });
    } catch (err: unknown) {
      const message = err instanceof ApiError ? err.message : "failed to load workbench state";
      dispatch({ type: "SET_ERROR", error: message });
    } finally {
      dispatch({ type: "SET_LOADING", loading: false });
    }
  }, [dispatch]);

  useEffect(() => {
    refetchWorkbench();
  }, [refetchWorkbench]);

  const handleModeChange = useCallback(
    (mode: GuiMode) => {
      if (mode === state.mode) return;
      postMode(mode)
        .then((shell) => dispatch({ type: "SET_SHELL", shell }))
        .catch((err: unknown) => {
          const message = err instanceof ApiError ? err.message : "failed to switch mode";
          dispatch({ type: "SET_ERROR", error: message });
        });
    },
    [dispatch, state.mode],
  );

  // REQ-GUI-017: no project loaded ⇒ Welcome screen instead of the 3-pane
  // body. Title bar + status bar stay visible; the mode toggle is disabled
  // (there is no project session for final_selection_mode to attach to).
  // `=== "none"` (not falsy) so fixtures that predate the `source` field
  // (undefined) keep rendering the normal 3-pane layout — see api/types.ts.
  const isWelcome = state.shell?.source === "none";

  return (
    <I18nProvider lang={state.lang}>
      <div className="shell">
        <TitleBar onModeChange={handleModeChange} disabled={isWelcome} />
        <ContextBar />
        <div className="shell__body">
          {isWelcome ? (
            <WelcomeScreen onReady={refetchWorkbench} />
          ) : (
            <>
              <LeftRail />
              <CentreCanvas />
              <RightPane />
            </>
          )}
        </div>
        <StatusBar />
      </div>
    </I18nProvider>
  );
}

function App() {
  return (
    <StoreProvider>
      <AppShell />
    </StoreProvider>
  );
}

export default App;
