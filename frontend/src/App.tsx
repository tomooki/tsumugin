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
import { I18nProvider } from "./i18n";
import { StoreProvider, useStore } from "./state/store";

function AppShell() {
  const { state, dispatch } = useStore();

  useEffect(() => {
    let cancelled = false;
    dispatch({ type: "SET_LOADING", loading: true });
    Promise.all([getState(), getViewModel()])
      .then(([shell, viewModel]) => {
        if (cancelled) return;
        dispatch({ type: "SET_SHELL", shell });
        dispatch({ type: "SET_VIEW_MODEL", viewModel });
        dispatch({ type: "SET_ERROR", error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "failed to load workbench state";
        dispatch({ type: "SET_ERROR", error: message });
      })
      .finally(() => {
        if (!cancelled) dispatch({ type: "SET_LOADING", loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

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

  return (
    <I18nProvider lang={state.lang}>
      <div className="shell">
        <TitleBar onModeChange={handleModeChange} />
        <ContextBar />
        <div className="shell__body">
          <LeftRail />
          <CentreCanvas />
          <RightPane />
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
