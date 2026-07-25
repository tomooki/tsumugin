// Null-safe numeric formatting for server-supplied values. The backend follows
// the repo-wide finite_or_none convention (api-contract.md): any non-finite
// number (chi2=inf is a *normal* path for failed refinements) is serialised as
// null. Every numeric table cell must therefore degrade to an em-dash instead
// of crashing the tree (the UI must never unmount on data — §語彙 and the
// delta_rwp regression).

export function formatNumber(n: number | null | undefined, digits: number): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

/** Signed variant used for ΔRwp-style columns ("+0.42" / "−4.39"). */
export function formatSigned(n: number | null | undefined, digits: number): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}`;
}

/** Integer with thousands separators ("39 402" style comes from the server as a number). */
export function formatInt(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}
