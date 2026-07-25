import type { Dispatch } from "react";
import type { ParamCard, ParamRow } from "../../api/types";
import { useI18n } from "../../i18n";
import type { Action } from "../../state/actions";
import { useStore } from "../../state/store";
import type { HistId } from "../../state/types";
import "./ParametersTab.css";
import { HistogramChips } from "./HistogramChips";

function paramKey(hist: HistId, cardId: string, field: string): string {
  return `${hist}.${cardId}.${field}`;
}

function isReleased(row: ParamRow, key: string, paramRel: Record<string, boolean>): boolean {
  return key in paramRel ? paramRel[key] : row.released;
}

interface ParamCardBlockProps {
  card: ParamCard;
  hist: HistId;
  span2: boolean;
  paramRel: Record<string, boolean>;
  paramValue: Record<string, string>;
  dispatch: Dispatch<Action>;
}

function ParamCardBlock({ card, hist, span2, paramRel, paramValue, dispatch }: ParamCardBlockProps) {
  const { t } = useI18n();
  const unlockedKeys = card.rows.filter((r) => !r.locked).map((r) => paramKey(hist, card.id, r.field));

  return (
    <div className={`bp-card blueprint param-card${span2 ? " param-card--span2" : ""}`}>
      <i className="corner tl" />
      <i className="corner tr" />
      <i className="corner bl" />
      <i className="corner br" />
      <div className="param-card__head">
        <span className="param-card__title">{card.title}</span>
        <span className="param-card__note">{card.note}</span>
      </div>

      {card.dropdown && (
        <div className="param-card__dropdown-row">
          <span className="param-card__dropdown-label">{card.dropdown.label}</span>
          <select
            className="param-card__dropdown"
            value={card.dropdown.value}
            onChange={() => {
              // Presentational only — no dropdown-mutation action exists yet
              // (matches the handoff prototype's no-op onChange for selects).
            }}
          >
            {card.dropdown.options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
      )}

      <table className="param-card__table">
        <thead>
          <tr>
            <th className="param-card__th param-card__th--left">{t("field")}</th>
            <th className="param-card__th param-card__th--right">{t("param.valueCol")}</th>
            <th className="param-card__th param-card__th--right">{t("param.esdCol")}</th>
          </tr>
        </thead>
        <tbody>
          {card.rows.map((row) => {
            const key = paramKey(hist, card.id, row.field);
            const released = isReleased(row, key, paramRel);
            const value = paramValue[key] ?? row.value;
            return (
              <tr
                key={row.field}
                className={`param-row${row.locked ? " param-row--locked" : ""}`}
              >
                <td className="param-card__td">{row.field}</td>
                <td
                  className={`param-card__td param-card__td--value${released ? " param-card__td--released" : ""}`}
                >
                  <span className="param-card__value-cell">
                    <input
                      type="checkbox"
                      className="param-card__checkbox"
                      checked={released}
                      disabled={row.locked}
                      title={released ? t("param.tip.released") : t("param.tip.fixed")}
                      onChange={() =>
                        dispatch({ type: "TOGGLE_PARAM_REL", key, fallback: row.released })
                      }
                    />
                    <input
                      className="param-card__value-input"
                      value={value}
                      disabled={row.locked}
                      onChange={(e) =>
                        dispatch({ type: "SET_PARAM_VALUE", key, value: e.target.value })
                      }
                    />
                  </span>
                </td>
                <td
                  className={`param-card__td param-card__td--esd${released ? " param-card__td--released" : ""}`}
                >
                  {row.esd}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="param-card__actions">
        <button
          type="button"
          className="param-card__btn param-card__btn--release"
          onClick={() => dispatch({ type: "SET_PARAM_GROUP", keys: unlockedKeys, value: true })}
        >
          {t("param.releaseAll")}
        </button>
        <button
          type="button"
          className="param-card__btn param-card__btn--fix"
          onClick={() => dispatch({ type: "SET_PARAM_GROUP", keys: unlockedKeys, value: false })}
        >
          {t("param.fixAll")}
        </button>
      </div>
      <div className="param-card__footer">{card.footer}</div>
    </div>
  );
}

/** See docs/design/gui-workbench/handoff/README.md §Centre pane item 2
 * (PARAMETERS): per-histogram cards (RADIATION/WAVELENGTH, SAMPLE &
 * GEOMETRY, BACKGROUND, PROFILE, SIZE/MICROSTRAIN) with release checkboxes
 * gating the staged recipe. Data comes from `viewModel.parameters[hist]`
 * (GET /api/viewmodel, api-contract.md); the last card in the list spans
 * both grid columns (SIZE/MICROSTRAIN in the handoff prototype). */
export function ParametersTab() {
  const { t } = useI18n();
  const { state, dispatch } = useStore();
  const hist = state.hist;
  const histograms = state.viewModel?.fit.histograms ?? [];
  const paramsForHist = state.viewModel?.parameters[hist];
  const cards = paramsForHist?.cards ?? [];

  // Live count = paramRel overlay layered over the viewModel's per-row
  // `released` baseline, summed across every card in this histogram — not
  // the server's precomputed `released_count`, which does not see local
  // checkbox edits that have not round-tripped through the API yet.
  const releasedCount = cards.reduce(
    (total, card) =>
      total +
      card.rows.filter((row) => isReleased(row, paramKey(hist, card.id, row.field), state.paramRel))
        .length,
    0,
  );

  return (
    <div className="param-tab">
      <div className="param-tab__title-row">
        <span className="param-tab__title">{t("param.title")}</span>
        <span className="param-tab__title-note">{t("param.note")}</span>
      </div>

      <div className="param-tab__precedence">
        <span className="param-tab__precedence-bar" />
        <span className="param-tab__precedence-body">
          <span className="param-tab__precedence-kicker">{t("param.precedenceShort")}</span>
          <span className="param-tab__precedence-text">{t("param.precedence")}</span>
        </span>
      </div>

      <HistogramChips
        histograms={histograms}
        active={hist}
        onSelect={(h) => dispatch({ type: "SET_HIST", hist: h })}
        trailing={t("param.releasedCount", { n: releasedCount })}
      />

      <div className="param-tab__grid">
        {cards.map((card, i) => (
          <ParamCardBlock
            key={card.id}
            card={card}
            hist={hist}
            span2={i === cards.length - 1}
            paramRel={state.paramRel}
            paramValue={state.paramValue}
            dispatch={dispatch}
          />
        ))}
      </div>
    </div>
  );
}
