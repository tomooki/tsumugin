import "./MetricCard.css";

interface MetricCardProps {
  label: string;
  value: string;
  note?: string;
}

/** FIT tab metric card: mono 9.5px label, Barlow Condensed 600 24px value,
 * 10.5px note — a blueprint card with no separate heading row. */
export function MetricCard({ label, value, note }: MetricCardProps) {
  return (
    <div className="metric-card blueprint">
      <div className="metric-card__label">{label}</div>
      <div className="metric-card__value">{value}</div>
      {note && <div className="metric-card__note">{note}</div>}
    </div>
  );
}
