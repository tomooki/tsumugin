import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import "./shell.css";

/** 26px status bar: backend build / seed / ledger / MCP tool chips on the
 * left, mode sentence right-aligned (neutral-400 MANUAL, accent-300 AUTO). */
export function StatusBar() {
  const { state } = useStore();
  const { t } = useI18n();
  const manual = state.mode === "manual";
  const status = state.shell?.status;
  const ledger = state.shell?.ledger;

  return (
    <div className="status-bar">
      <div className="status-bar__items">
        <span>{status ? `backend: ${status.backend_build}` : t("status.backend")}</span>
        <span>{status ? `seed = ${status.seed} · bit-identical (NFR-102)` : t("status.seed")}</span>
        <span>
          {ledger
            ? `ledger entries ${ledger.count} · chain ${ledger.verified ? "OK" : "BROKEN"}`
            : t("status.ledger")}
        </span>
        <span>
          {status ? `MCP tools ${status.mcp_tools} · layer ② reachable` : t("status.mcp")}
        </span>
      </div>
      <span className={`status-bar__sentence${manual ? "" : " status-bar__sentence--auto"}`}>
        {manual ? t("status.text.manual") : t("status.text.auto")}
      </span>
    </div>
  );
}
