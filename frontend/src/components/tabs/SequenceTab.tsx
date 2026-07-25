import { useI18n } from "../../i18n";
import { useStore } from "../../state/store";
import { BlueprintCard, Chip, PlaceholderPlot } from "../common";
import { SEQUENCE_STRINGS, type SequenceStringKey } from "./SequenceTab.strings";
import "./SequenceTab.css";

interface ChartChrome {
  noteKey: "seq.rwp.note" | "seq.lattice.note" | "seq.fraction.note";
  placeholderKey: "seq.rwp.placeholder" | "seq.lattice.placeholder" | "seq.fraction.placeholder";
  height: string;
}

// Static per-chart chrome (note + placeholder label + frame height) keyed by
// the chart id the API is expected to send (handoff/README.md §Centre pane
// item 5: three fixed cards — Rwp / lattice / phase fraction vs frame).
// Headings come straight from the API (`chart.title`) rather than this map,
// matching the ContextBar precedent of preferring live data over the static
// mockup copy once it has loaded.
const CHART_CHROME: Record<string, ChartChrome> = {
  rwp: { noteKey: "seq.rwp.note", placeholderKey: "seq.rwp.placeholder", height: "92px" },
  lattice: { noteKey: "seq.lattice.note", placeholderKey: "seq.lattice.placeholder", height: "92px" },
  fraction: { noteKey: "seq.fraction.note", placeholderKey: "seq.fraction.placeholder", height: "108px" },
};

// Pre-load fallback: the three known charts in design order, so the tab has
// its expected shape before GET /api/viewmodel resolves.
const FALLBACK_CHARTS = [
  { id: "rwp", title: "seq.rwp.title" as const },
  { id: "lattice", title: "seq.lattice.title" as const },
  { id: "fraction", title: "seq.fraction.title" as const },
];

/** SEQUENCE tab — see handoff README §Centre pane item 5: three equally
 * growing chart cards (Rwp / lattice a,c / phase fraction vs frame), an
 * anchor chip row (crossover anchor gets the inverted "attention" chip),
 * and the SEGMENT SELECTION forward-vs-backward table. Data:
 * `state.viewModel.sequence` (FR-330 anchored bidirectional analysis). */
export function SequenceTab() {
  const { lang, t } = useI18n();
  const { state } = useStore();
  const seq = state.viewModel?.sequence;

  function tl(key: SequenceStringKey): string {
    return SEQUENCE_STRINGS[key][lang];
  }

  const charts =
    seq && seq.charts.length > 0
      ? seq.charts
      : FALLBACK_CHARTS.map((c) => ({ id: c.id, title: t(c.title) }));

  const anchors = seq?.anchors ?? [];
  const crossoverNote = seq?.note ?? t("seq.crossoverNote");
  const segments = seq?.segments ?? [];

  return (
    <div className="seq-tab">
      <div className="seq-tab__head">
        <span className="seq-tab__title">{t("seq.title")}</span>
        <span className="seq-tab__note">{t("seq.note")}</span>
      </div>

      <div className="seq-tab__charts">
        {charts.map((chart) => {
          const chrome = CHART_CHROME[chart.id];
          return (
            <BlueprintCard
              key={chart.id}
              heading={chart.title}
              note={chrome ? t(chrome.noteKey) : undefined}
              className="seq-tab__chart-card"
              bodyStyle={{ display: "flex", flex: 1, minHeight: 0 }}
            >
              <PlaceholderPlot
                label={chrome ? t(chrome.placeholderKey) : tl("chart.fallback.placeholder")}
                height={chrome?.height ?? "96px"}
                style={{ flex: 1 }}
              />
            </BlueprintCard>
          );
        })}
      </div>

      <div className="seq-tab__anchors">
        <div className="seq-tab__anchors-chips">
          <span className="seq-tab__anchors-label">{t("seq.anchors")}</span>
          {anchors.map((anchor) => (
            <Chip key={anchor.id} variant={anchor.crossover ? "inverted" : "accent"}>
              {anchor.crossover ? `${anchor.id} ${tl("anchor.crossoverSuffix")}` : anchor.id}
            </Chip>
          ))}
        </div>
        <span className="seq-tab__anchors-note">{crossoverNote}</span>
      </div>

      <BlueprintCard heading={t("seq.segTitle")}>
        <table className="seq-tab__seg-table">
          <thead>
            <tr>
              <th className="seq-tab__seg-th--left">{t("col.segment")}</th>
              <th className="seq-tab__seg-th--left">{t("col.forwardSet")}</th>
              <th className="seq-tab__seg-th--left">{t("col.backwardSet")}</th>
              <th className="seq-tab__seg-th--right">Rwp</th>
              <th className="seq-tab__seg-th--right">{t("col.totalBic")}</th>
              <th className="seq-tab__seg-th--left">{t("col.selected")}</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((row) => (
              <tr key={row.segment}>
                <td className="seq-tab__seg-td--mono">{row.segment}</td>
                <td>{row.forward}</td>
                <td>{row.backward}</td>
                <td className="seq-tab__seg-td--right-mono">{row.rwp}</td>
                <td className="seq-tab__seg-td--right-mono">{row.total_bic}</td>
                <td className="seq-tab__seg-td--selected">{row.selected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </BlueprintCard>
    </div>
  );
}
