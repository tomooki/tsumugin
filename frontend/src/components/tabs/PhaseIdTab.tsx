import { formatNumber } from "../../api/format";
import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { BlueprintCard, Btn, Chip, PlaceholderPlot } from "../common";
import "./PhaseIdTab.css";

/** See handoff README §Centre pane item 4 (PHASE ID): candidate table
 * (`# / FORMULA / SOURCE / SG / DARA / m/w/ms/x / STRAIN / CHEM GUARD /
 * action`), an UNEXPLAINED FEATURES card (`residual_report`) and a PHASE
 * SET COMPLETENESS card (`check_phase_set`). Data comes from
 * `viewModel.phase_id` (api-contract.md); `source`/`chem_guard`/`notes`
 * text is server-supplied and rendered verbatim (API surface, not
 * translated). `ADD AS PHASE` is display-only in v1 — clicking it is a
 * no-op, backend wiring is a later integration step. */
export function PhaseIdTab() {
  const { t } = useI18n();
  const { state } = useStore();
  const vm = state.viewModel?.phase_id ?? {
    candidates: [],
    unexplained: [],
    completeness: { is_complete: true, notes: [], flagged_frames: "" },
  };

  return (
    <div className="pid-tab">
      <div className="pid-tab__head">
        <span className="pid-tab__title">{t("pid.title")}</span>
        <span className="pid-tab__note">{t("pid.note")}</span>
      </div>

      <table className="pid-table">
        <thead>
          <tr>
            <th>#</th>
            <th>{t("col.formula")}</th>
            <th>{t("col.source")}</th>
            <th>{t("col.sg")}</th>
            <th className="num">{t("col.dara")}</th>
            <th className="num">m/w/ms/x</th>
            <th className="num">{t("col.strain")}</th>
            <th>{t("col.chemGuard")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {vm.candidates.map((row) => (
            <tr key={row.rank} className={row.rank === 1 ? "pid-table__row--top" : undefined}>
              <td>{row.rank}</td>
              <td>{row.formula}</td>
              <td className="mono">{row.source}</td>
              <td className="mono">{row.sg}</td>
              <td className="num">{formatNumber(row.dara, 2)}</td>
              <td className="num mono">{row.mwmsx}</td>
              <td className="num">{row.strain}</td>
              <td>
                <Chip variant={row.guard_fail ? "inverted" : "hairline"}>{row.chem_guard}</Chip>
              </td>
              <td className="right">
                <Btn type="button" variant="outline">
                  {t("pid.action.addAsPhase")}
                </Btn>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="pid-bottom">
        <BlueprintCard
          heading={t("pid.residualTitle")}
          className="pid-bottom__card"
          bodyStyle={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
        >
          <PlaceholderPlot
            label={t("pid.residualDecompPlaceholder")}
            height="112px"
            style={{ flex: 1 }}
          />
          <div className="pid-residual__list">
            {vm.unexplained.map((f, i) => (
              <div key={i}>
                {`2θ ${formatNumber(f.two_theta, 2)} · S/N ${formatNumber(f.sn, 1)} · ${f.indexing}`}
              </div>
            ))}
          </div>
        </BlueprintCard>

        <BlueprintCard heading={t("pid.completenessTitle")} className="pid-bottom__card">
          <div className="pid-completeness">
            <div className="pid-completeness__row">
              <span>{t("completeness.isComplete")}</span>
              <Chip variant={vm.completeness.is_complete ? "hairline" : "inverted"}>
                {vm.completeness.is_complete ? "TRUE" : "FALSE"}
              </Chip>
            </div>
            {vm.completeness.notes.map((note, i) => (
              <div key={i} className="pid-completeness__note">
                {note}
              </div>
            ))}
            <div className="pid-completeness__row">
              <span>{t("completeness.flagged.k")}</span>
              <span className="pid-completeness__value">{vm.completeness.flagged_frames}</span>
            </div>
            <div className="pid-completeness__footer">{t("pid.completenessNote")}</div>
          </div>
        </BlueprintCard>
      </div>
    </div>
  );
}
