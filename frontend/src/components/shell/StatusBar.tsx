import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import "./shell.css";

/** 26px status bar: backend build / seed / ledger / MCP tool chips on the
 * left, mode sentence right-aligned (neutral-400 MANUAL, accent-300 AUTO).
 * All four items go through t(key, vars) so they render in the active
 * language both before and after the real /api/state payload arrives —
 * previously the post-fetch values were built with raw template literals
 * that stayed English regardless of state.lang (see CLAUDE.md item 4 fix). */
export function StatusBar() {
  const { state } = useStore();
  const { t } = useI18n();
  const manual = state.mode === "manual";
  const status = state.shell?.status;
  const ledger = state.shell?.ledger;

  return (
    <div className="status-bar">
      <div className="status-bar__items">
        <span>{t("status.backend", { build: status?.backend_build ?? "…" })}</span>
        <span>{t("status.seed", { seed: status?.seed ?? "…" })}</span>
        <span>
          {t("status.ledger", {
            n: ledger?.count ?? "…",
            chain: ledger ? (ledger.verified ? "OK" : "BROKEN") : "…",
          })}
        </span>
        <span>{t("status.mcp", { n: status?.mcp_tools ?? "…" })}</span>
      </div>
      <span className={`status-bar__sentence${manual ? "" : " status-bar__sentence--auto"}`}>
        {manual ? t("status.text.manual") : t("status.text.auto")}
      </span>
    </div>
  );
}
