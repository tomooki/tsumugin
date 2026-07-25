import type { ReactNode } from "react";
import type { FitHistogramChip } from "../../api/types";
import { useI18n } from "../../i18n";
import type { HistId } from "../../state/types";
import "./HistogramChips.css";

interface HistogramChipsProps {
  histograms: FitHistogramChip[];
  active: HistId;
  onSelect: (id: HistId) => void;
  trailing?: ReactNode;
}

/** Histogram chip row shared by FIT and PARAMETERS (handoff README: "Histogram
 * chip → Re-points FIT and all four PARAMETERS cards"). Both tabs re-point off
 * the same `state.hist`, so this is one component rather than two copies.
 * Data comes from `viewModel.fit.histograms` — the only place the API
 * contract defines the chip list. */
export function HistogramChips({ histograms, active, onSelect, trailing }: HistogramChipsProps) {
  const { t } = useI18n();
  return (
    <div className="hist-chips">
      <span className="hist-chips__label">{t("histogram")}</span>
      {histograms.map((h) => (
        <button
          key={h.id}
          type="button"
          className={`hist-chips__chip${h.id === active ? " hist-chips__chip--active" : ""}`}
          onClick={() => onSelect(h.id as HistId)}
        >
          {h.label}
        </button>
      ))}
      {trailing !== undefined && <span className="hist-chips__trailing">{trailing}</span>}
    </div>
  );
}
