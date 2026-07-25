import type { ButtonHTMLAttributes } from "react";
import "./Btn.css";

type BtnVariant = "accent" | "outline";

interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BtnVariant;
}

/** Square-cornered button — accent fill or hairline outline, radius 0 per
 * Industry. */
export function Btn({ variant = "outline", className, ...rest }: BtnProps) {
  const classes = ["btn", `btn--${variant}`, className].filter(Boolean).join(" ");
  return <button className={classes} {...rest} />;
}
