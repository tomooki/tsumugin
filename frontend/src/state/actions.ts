import type { GuiMode, RefineStatus, ShellState, Site, TranscriptMessage, ViewModel } from "../api/types";
import type { Lang } from "../i18n";
import type { ApprovalState, HistId, ReviewDecision, TabId } from "./types";

export type Action =
  | { type: "SET_LANG"; lang: Lang }
  | { type: "SET_MODE"; mode: GuiMode }
  | { type: "SET_TAB"; tab: TabId }
  | { type: "SET_HIST"; hist: HistId }
  | { type: "SET_HYP"; hyp: string }
  | { type: "TOGGLE_PARAM_REL"; key: string; fallback: boolean }
  | { type: "SET_PARAM_GROUP"; keys: string[]; value: boolean }
  | { type: "SET_PARAM_VALUE"; key: string; value: string }
  | { type: "EDIT_SITE"; id: string; field: keyof Site; value: string }
  | { type: "TOGGLE_SITE_RELEASE"; id: string; field: "x" | "y" | "z" | "occ" | "uiso" }
  | { type: "ADD_ATOM" }
  | { type: "DELETE_SITE"; id: string }
  | { type: "APPLY_EDITS" }
  | { type: "DISCARD_EDITS" }
  | { type: "TOGGLE_OPEN"; id: string }
  | { type: "TOGGLE_STAGE"; nn: number }
  | { type: "SET_APPROVAL"; actionId: string; approval: ApprovalState }
  | { type: "SET_REVIEW"; id: string; decision: ReviewDecision }
  | { type: "SET_DRAFT"; draft: string }
  | { type: "SET_SHELL"; shell: ShellState }
  | { type: "SET_VIEW_MODEL"; viewModel: ViewModel }
  | { type: "SET_REFINE_STATUS"; refine: RefineStatus | null }
  | { type: "APPEND_TRANSCRIPT_MESSAGE"; message: TranscriptMessage }
  | { type: "SET_LOADING"; loading: boolean }
  | { type: "SET_ERROR"; error: string | null };
