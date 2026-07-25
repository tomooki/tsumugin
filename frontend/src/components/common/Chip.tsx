import type { CSSProperties, ReactNode } from "react";
import "./Chip.css";

export type ChipVariant = "accent" | "neutral" | "inverted" | "hairline";

interface ChipProps {
  children: ReactNode;
  variant?: ChipVariant;
  mono?: boolean;
  className?: string;
  style?: CSSProperties;
}

/** Small hairline-bordered label. Industry's warning states carry no extra
 * hue — "inverted" (neutral-900 field / neutral-100 type) is the only
 * attention treatment (WARN, CLOSE, UNKNOWN, is_complete FALSE, …). */
export function Chip({ children, variant = "hairline", mono = true, className, style }: ChipProps) {
  const classes = ["chip", `chip--${variant}`, mono ? "chip--mono" : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes} style={style}>
      {children}
    </span>
  );
}
