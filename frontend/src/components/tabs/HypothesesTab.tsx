import { formatInt, formatNumber } from "../../api/format";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { ScatterChart } from "../charts/ScatterChart";
import { BlueprintCard } from "../common";
import "./HypothesesTab.css";

/** See handoff README §Centre pane item 3 (HYPOTHESES): ranking table
 * (`# / ID / PHASES / P / Rwp / GOF / BIC / CLOSE / STATUS`), a DIFF card
 * against the comparison hypothesis, and an EVIDENCE & BASIN card. Data
 * comes from `viewModel.hypotheses` (api-contract.md); `phases`/`status`
 * cell text is server-supplied and rendered verbatim (API surface, not
 * translated — see README "Interactions & behaviour" table). */
export function HypothesesTab() {
  const { t } = useI18n();
  const { state, dispatch } = useStore();
  const vm = state.viewModel?.hypotheses ?? { rows: [], diff: { vs: "", rows: [] }, evidence: [] };

  return (
    <div className="hyp-tab">
      <div className="hyp-tab__head">
        <span className="hyp-tab__title">{t("hyp.title")}</span>
        <span className="hyp-tab__note">{t("hyp.note")}</span>
      </div>

      <table className="hyp-table">
        <thead>
          <tr>
            <th>#</th>
            <th>ID</th>
            <th>{t("col.phases")}</th>
            <th className="num">P</th>
            <th className="num">Rwp</th>
            <th className="num">GOF</th>
            <th className="num">BIC</th>
            <th className="center">{t("col.close")}</th>
            <th>{t("col.status")}</th>
          </tr>
        </thead>
        <tbody>
          {vm.rows.map((row) => (
            <tr
              key={row.id}
              className={`hyp-table__row${state.hyp === row.id ? " hyp-table__row--selected" : ""}`}
              onClick={() => dispatch({ type: "SET_HYP", hyp: row.id })}
            >
              <td>{row.rank}</td>
              <td className="mono">{row.id}</td>
              <td>{row.phases}</td>
              <td className="num">{formatNumber(row.p, 2)}</td>
              <td className="num">{formatNumber(row.rwp, 2)}</td>
              <td className="num">{formatNumber(row.gof, 2)}</td>
              <td className="num">{formatInt(row.bic)}</td>
              <td className="center">
                {row.close && <span className="hyp-table__close-dot">●</span>}
              </td>
              <td className="hyp-table__status">{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="hyp-bottom">
        <BlueprintCard
          heading={`${t("diff.title")} · ${state.hyp} vs ${vm.diff.vs}`}
          className="hyp-bottom__card"
        >
          <table className="diff-table">
            <thead>
              <tr>
                <th>{t("field")}</th>
                <th className="num">{state.hyp}</th>
                <th className="num">{vm.diff.vs}</th>
              </tr>
            </thead>
            <tbody>
              {vm.diff.rows.map((d, i) => (
                <tr key={i}>
                  <td>{d.field}</td>
                  <td className="num">{d.a}</td>
                  <td className={`num${d.changed ? " diff-table__cell--changed" : ""}`}>{d.b}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </BlueprintCard>

        <BlueprintCard
          heading={t("evidence.title")}
          className="hyp-bottom__card"
          bodyStyle={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
        >
          <ScatterChart points={vm.basin?.points} height="120px" emptyLabel={t("evidence.basinPlaceholder")} />
          <div className="hyp-evidence__rows">
            {vm.evidence.map(([k, v], i) => (
              <div key={i} className="hyp-evidence__row">
                <span>{k}</span>
                <span className="hyp-evidence__row-value">{v}</span>
              </div>
            ))}
          </div>
        </BlueprintCard>
      </div>
    </div>
  );
}
