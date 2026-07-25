// GSAS-II's element table, atomic-number order, 1 H … 98 Cf, with D inserted
// immediately after H as its isotope (99 options total).
// Ported from `Component.ELEMENTS` in
// docs/design/gui-workbench/handoff/Tsumugin Workbench.dc.html (line ~882).

export interface ElementOption {
  z: number;
  symbol: string;
}

const SYMBOLS = [
  "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P",
  "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga",
  "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag",
  "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu",
  "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au",
  "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am",
  "Cm", "Bk", "Cf",
] as const;

function buildElements(): ElementOption[] {
  const out: ElementOption[] = [];
  SYMBOLS.forEach((symbol, i) => {
    const z = i + 1;
    out.push({ z, symbol });
    if (symbol === "H") out.push({ z: 1, symbol: "D" });
  });
  return out;
}

export const ELEMENTS: ElementOption[] = buildElements();

export function elementLabel(el: ElementOption): string {
  return `${el.z} ${el.symbol}`;
}
