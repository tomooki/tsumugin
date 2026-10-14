import { formatNumber } from "../../api/format";
import type { PublicationRow, PublicationViewModel } from "../../api/types";
import { useI18n } from "../../i18n";
import { BlueprintCard, Chip } from "../common";
import "./PublicationCard.css";
import { PUBLICATION_STRINGS, type PublicationKey } from "./PublicationCard.strings";

function valueText(row: PublicationRow): string {
  if (row.value === null) return "—";
  const v = formatNumber(row.value, 6);
  const e = row.esd === null ? "" : ` ± ${formatNumber(row.esd, 6)}`;
  return `${v}${e} ${row.unit}`.trim();
}

/** Publication state of the last refinement (fit-then-judge P1c,
 * api-contract.md viewmodel.publication). Every number is shown together with
 * its state (publishable / determinacy / scope / gate) — never as a bare value.
 * Judgment requests are display-only: closing one belongs to decision 2, so
 * this card deliberately has no answer/approve controls. */
export function PublicationCard({ publication }: { publication?: PublicationViewModel }) {
  const { lang } = useI18n();
  if (!publication) return null;
  const s = (key: PublicationKey) => PUBLICATION_STRINGS[key][lang];

  return (
    <BlueprintCard heading={s("title")}>
      <div className="publication" data-testid="publication-card">
        <div className="publication__summary">
          <Chip variant={publication.n_publishable > 0 ? "accent" : "inverted"}>
            {`${publication.n_publishable} / ${publication.n_values} ${s("summary")}`}
          </Chip>
          <span className="publication__meta">
            {publication.claims_version} · {publication.policy}
          </span>
        </div>
        {publication.error !== null && (
          <div className="publication__error" role="alert">
            {s("error")}: {publication.error}
          </div>
        )}
        {publication.rows.length > 0 && (
          <table className="publication__table">
            <thead>
              <tr>
                <th>key</th>
                <th>{s("colValue")}</th>
                <th>{s("colState")}</th>
              </tr>
            </thead>
            <tbody>
              {publication.rows.map((row) => (
                <tr
                  key={row.key}
                  data-testid="publication-row"
                  className={row.publishable ? "" : "publication__row--held"}
                >
                  <td className="publication__key">{row.key}</td>
                  <td className="publication__value">
                    {valueText(row)}
                    {row.scope === "relative_within_sample" && (
                      <span className="publication__scope" title={s("relative")}>
                        {" (rel)"}
                      </span>
                    )}
                  </td>
                  <td className="publication__state">
                    <Chip variant={row.publishable ? "accent" : "inverted"}>
                      {row.publishable ? s("publishable") : s("held")}
                    </Chip>{" "}
                    <span className="publication__determinacy">{row.determinacy}</span>
                    {row.gate.length > 0 && (
                      <span className="publication__gate">{` ⊘ ${row.gate.join(", ")}`}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="publication__requests-title">{s("requestsTitle")}</div>
        {publication.judgment_requests.length === 0 ? (
          <div className="publication__note">{s("noRequests")}</div>
        ) : (
          <ul className="publication__requests">
            {publication.judgment_requests.map((req) => (
              <li key={req.id} className="publication__request" data-testid="judgment-request">
                <div className="publication__request-head">
                  <span className="publication__request-kind">{req.kind}</span>
                  <Chip variant={req.blocking ? "inverted" : "hairline"}>
                    {req.blocking ? s("blocking") : s("nonBlocking")}
                  </Chip>
                  {req.blocking && (
                    <span className="publication__note">{`${req.n_blocked} ${s("blocks")}`}</span>
                  )}
                </div>
                <div className="publication__trigger">{req.trigger}</div>
                <div className="publication__note">
                  {s("candidates")}: {req.candidates.join(" / ")} · {s("defaultAnswer")}:{" "}
                  {req.default_answer ?? "—"}
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="publication__note">{s("readOnlyNote")}</div>
      </div>
    </BlueprintCard>
  );
}
