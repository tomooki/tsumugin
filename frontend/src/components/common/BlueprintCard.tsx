import type { CSSProperties, ReactNode } from "react";
import "./BlueprintCard.css";

interface BlueprintCardProps {
  heading?: ReactNode;
  note?: ReactNode;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  bodyStyle?: CSSProperties;
}

/** Industry "blueprint object": hairline border, `--color-neutral-100` field,
 * square corners, 10px 12px padding — the container used by every card. (The
 * prototype's four corner "+" registration marks were a Claude Design artifact
 * and are intentionally omitted from the product chrome.) */
export function BlueprintCard({
  heading,
  note,
  children,
  className,
  style,
  bodyStyle,
}: BlueprintCardProps) {
  return (
    <div className={`bp-card blueprint${className ? ` ${className}` : ""}`} style={style}>
      {(heading || note) && (
        <div className="bp-card__head">
          {heading && <span className="bp-card__heading">{heading}</span>}
          {note && <span className="bp-card__note">{note}</span>}
        </div>
      )}
      <div className="bp-card__body" style={bodyStyle}>
        {children}
      </div>
    </div>
  );
}
