import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from "react";
import type { Action } from "./actions";
import { initialWorkbenchState, reducer } from "./reducer";
import type { WorkbenchState } from "./types";

interface StoreContextValue {
  state: WorkbenchState;
  dispatch: Dispatch<Action>;
}

const StoreContext = createContext<StoreContextValue | null>(null);

export function StoreProvider({
  children,
  initialState,
}: {
  children: ReactNode;
  initialState?: Partial<WorkbenchState>;
}) {
  const [state, dispatch] = useReducer(reducer, { ...initialWorkbenchState, ...initialState });
  return <StoreContext.Provider value={{ state, dispatch }}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreContextValue {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used within StoreProvider");
  return ctx;
}
