"""P0 §6: 合成ケース (`S-dev` / `S-eval`) の生成器の核 (numpy だけ)。

GSAS で Ycalc を計算する部分は別モジュール (遅延 import)。ここは決定論で検査できる部分:

- **除外** (§6.1): 準 hold-out の化合物とゲート確認に使った 5 種を組成で拒否する。解釈できない式は「当たらない」とせず拒否する。
- **雑音** (§6.2): Ycalc を最大計数 (1e4 / 1e5 の 2 水準) に合わせ、平坦な背景を足して Poisson。
- **欠陥** (§6.3) と**モデルの不一致** (§6.2) の登録。大きさの範囲と、期待する検出器の結果は**ここで**決まる (凍結版に入る)。
- **manifest** (§6.4): 期待する結果が空なら作れない (生成の前に書く)。パターンの sha256 は生成の後で足す。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np

__all__ = [
    "COUNT_LEVELS",
    "DEFECTS",
    "DELTA_ZERO_DEG",
    "EXCLUDED_COMPOUNDS",
    "INSTRUMENTS",
    "MISMATCHES",
    "CaseManifest",
    "DefectKind",
    "DefectSpec",
    "NoisyPattern",
    "PhaseSource",
    "add_counting_noise",
    "check_set_mismatch_fraction",
    "composition_fractions",
    "excluded_reason",
    "sample_defect",
]

_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr "
    "Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb "
    "Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu D".split()
)
_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9.()\s]+$")
_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*\.?\d*)|(\()|(\))(\d*\.?\d*)")

#: §6.1 の除外: 準 hold-out の化合物 (水和物を含む) とゲート確認に使った 5 種 (P0 §3.2.1-10)
EXCLUDED_COMPOUNDS: dict[str, str] = {
    "Ca5 (P O4)3 F": "quasi-holdout T1 (fluoroapatite)",
    "Ca Te O3": "quasi-holdout CaTeO3",
    "Ca Te O3 (H2 O)": "quasi-holdout CaTeO3 hydrate",
    "Pb S O4": "quasi-holdout T3 / gate check (anglesite)",
    "Na2 Ca3 Al2 F14": "quasi-holdout T4 (NAC)",
    "Ca F2": "quasi-holdout T4 / gate check (fluorite)",
    "Si O2": "gate check (quartz)",
    "Ca C O3": "gate check (calcite)",
    "Al2 O3": "gate check (corundum)",
}


def composition_fractions(formula: str) -> dict[str, float] | None:
    """H と D を除いた原子数の割合。席の混合・変数・空孔など一意な量に直せない式は None。"""
    if not formula or not _ALLOWED_CHARS.match(formula):
        return None
    text = formula.replace(" ", "")
    stack: list[dict[str, float]] = [{}]
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None or m.end() == pos:
            return None
        pos = m.end()
        if m.group(1):
            el = m.group(1)
            if el not in _ELEMENTS:
                return None
            n = float(m.group(2)) if m.group(2) else 1.0
            stack[-1][el] = stack[-1].get(el, 0.0) + n
        elif m.group(3):
            stack.append({})
        else:
            if len(stack) < 2:
                return None
            mult = float(m.group(5)) if m.group(5) else 1.0
            inner = stack.pop()
            for el, n in inner.items():
                stack[-1][el] = stack[-1].get(el, 0.0) + n * mult
    if len(stack) != 1:
        return None
    counts = {el: n for el, n in stack[0].items() if el not in ("H", "D")}
    total = sum(counts.values())
    if total <= 0:
        return None
    return {el: n / total for el, n in counts.items()}


def _same_composition(a: Mapping[str, float], b: Mapping[str, float]) -> bool:
    """P0 §3.2.1-2 と同じ一致: 元素の集合が同じで、各元素の割合が相対 5% (+ 絶対 0.005) 以内。"""
    if set(a) != set(b):
        return False
    return all(abs(a[el] - b[el]) <= 0.05 * b[el] + 0.005 for el in a)


def excluded_reason(formula: str) -> str | None:
    """除外に当たれば理由、当たらなければ None。解釈できない式も理由付きで拒否する。"""
    comp = composition_fractions(formula)
    if comp is None:
        return f"unparseable formula {formula!r} (cannot prove it is not an excluded compound)"
    for name, why in EXCLUDED_COMPOUNDS.items():
        ref = composition_fractions(name)
        if ref is not None and _same_composition(comp, ref):
            return why
    return None


# --- 雑音 ------------------------------------------------------------------------------------

COUNT_LEVELS = (1e4, 1e5)


@dataclass(frozen=True)
class NoisyPattern:
    y: np.ndarray
    esd: np.ndarray
    expected: np.ndarray


def add_counting_noise(ycalc: np.ndarray, *, max_counts: float, background: float, seed: int) -> NoisyPattern:
    """Ycalc の最大を ``max_counts`` に合わせ、平坦な ``background`` を足して Poisson 雑音を掛ける。"""
    if max_counts not in COUNT_LEVELS:
        raise ValueError(f"最大計数は登録した水準 {COUNT_LEVELS} のどれか (受け取った値 {max_counts})")
    yc = np.asarray(ycalc, dtype=float)
    peak = float(yc.max()) if yc.size else 0.0
    if peak <= 0.0:
        raise ValueError("Ycalc が正の値を持たない")
    expected = max_counts * yc / peak + float(background)
    y = np.random.default_rng(seed).poisson(expected).astype(float)
    return NoisyPattern(y=y, esd=np.sqrt(np.maximum(y, 1.0)), expected=expected)


# --- 欠陥と不一致 ----------------------------------------------------------------------------

#: §5.2 の登録効果量 (ゼロ点)。欠陥 7 はその 1 倍と 3 倍
DELTA_ZERO_DEG = 0.01


@dataclass(frozen=True)
class DefectKind:
    kind: int
    name: str
    unit: str
    expected: str
    low: float | None = None
    high: float | None = None
    choices: tuple[float, ...] = ()


DEFECTS: dict[int, DefectKind] = {
    1: DefectKind(1, "site_element_swap", "", "crystal-chemistry fail or short bond"),
    2: DefectKind(2, "missing_atom", "", "residual / judgment request"),
    3: DefectKind(3, "mixed_occupancy_ratio", "fraction", "recovered by sum=1 + equal Uiso", 0.10, 0.25),
    4: DefectKind(4, "atom_displacement", "angstrom", "recovered or crystal-chemistry fail", 0.2, 0.4),
    5: DefectKind(5, "missing_phase", "wt_fraction", "phase-set completeness witness fails (pass = miss)", 0.02, 0.10),
    6: DefectKind(6, "anisotropic_cell_error", "relative_per_axis", "recovered within convergence radius", 0.01, 0.03),
    7: DefectKind(7, "zero_offset", "x delta_zero (0.01 deg)", "zero-point falsification probe", choices=(1.0, 3.0)),
    8: DefectKind(8, "minor_phase_cell_error_frozen", "relative_all_axes", "cell-freezing falsification probe",
                  choices=(0.005,)),
    9: DefectKind(9, "polar_translation", "fractional_along_polar_axis", "origin fixed, same solution modulo translation",
                  0.02, 0.10),
    10: DefectKind(10, "preferred_orientation", "march_dollase_r", "stage 8 / 8R", choices=(0.8,)),
}

MISMATCHES: dict[str, str] = {
    "asymmetry": "peak asymmetry not modelled by the refinement",
    "kalpha2_ratio": "Kalpha2/Kalpha1 ratio differs from the instrument file",
    "impurity_peak": "one unmodelled impurity peak at <= 1% of the maximum",
    "amorphous_hump": "background outside the polynomial family (amorphous hump)",
}


def sample_defect(kind: int, rng: np.random.Generator) -> float | None:
    """登録した範囲から大きさを引く (範囲の無い欠陥は None)。"""
    spec = DEFECTS[kind]
    if spec.choices:
        return float(spec.choices[int(rng.integers(0, len(spec.choices)))])
    if spec.low is None or spec.high is None:
        return None
    return float(rng.uniform(spec.low, spec.high))


# --- manifest --------------------------------------------------------------------------------

INSTRUMENTS = ("lab_bb", "sync_ds")
_SETS = ("S-dev", "S-eval")


@dataclass(frozen=True)
class PhaseSource:
    db: str
    entry_id: str
    revision: str
    sha256: str
    license: str
    phase_name: str
    formula: str
    wt_fraction: float


@dataclass(frozen=True)
class DefectSpec:
    kind: int
    target: str
    magnitude: float | None
    truth: str
    start: str


@dataclass(frozen=True)
class CaseManifest:
    case_id: str
    case_set: str
    phases: tuple[PhaseSource, ...]
    instrument: str
    max_counts: float
    seed: int
    defects: tuple[DefectSpec, ...]
    mismatches: tuple[str, ...]
    expected: tuple[str, ...]
    generator_commit: str = ""
    versions: Mapping[str, str] = field(default_factory=dict)
    pattern_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.expected:
            raise ValueError("expected detector outcomes must be written before the pattern is generated")
        if self.case_set not in _SETS:
            raise ValueError(f"case_set は {_SETS} のどれか")
        if self.instrument not in INSTRUMENTS:
            raise ValueError(f"instrument は {INSTRUMENTS} のどれか")
        if self.max_counts not in COUNT_LEVELS:
            raise ValueError(f"max_counts は {COUNT_LEVELS} のどれか")
        for m in self.mismatches:
            if m not in MISMATCHES:
                raise ValueError(f"未登録のモデルの不一致: {m!r}")
        for d in self.defects:
            if d.kind not in DEFECTS:
                raise ValueError(f"未登録の欠陥: {d.kind}")
        for p in self.phases:
            why = excluded_reason(p.formula)
            if why is not None:
                raise ValueError(f"excluded compound {p.formula!r}: {why}")
        if self.phases and abs(sum(p.wt_fraction for p in self.phases) - 1.0) > 1e-6:
            raise ValueError("phase wt fractions must sum to 1")

    def with_pattern(self, xye: np.ndarray) -> CaseManifest:
        """生成したパターン (x, y, esd の列) の sha256 を記録した manifest を返す。"""
        data = np.ascontiguousarray(np.asarray(xye, dtype=np.float64))
        return replace(self, pattern_sha256=hashlib.sha256(data.tobytes()).hexdigest())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["versions"] = dict(self.versions)
        return json.loads(json.dumps(d))

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CaseManifest:
        return cls(
            case_id=d["case_id"],
            case_set=d["case_set"],
            phases=tuple(PhaseSource(**p) for p in d["phases"]),
            instrument=d["instrument"],
            max_counts=float(d["max_counts"]),
            seed=int(d["seed"]),
            defects=tuple(DefectSpec(**x) for x in d["defects"]),
            mismatches=tuple(d["mismatches"]),
            expected=tuple(d["expected"]),
            generator_commit=d.get("generator_commit", ""),
            versions=dict(d.get("versions", {})),
            pattern_sha256=d.get("pattern_sha256", ""),
        )


def check_set_mismatch_fraction(manifests: Sequence[CaseManifest]) -> str | None:
    """§6.2: 事例の半数以上にモデルの不一致を 1 つ以上入れる。満たさなければ理由を返す。"""
    if not manifests:
        return "no cases"
    with_mismatch = sum(1 for m in manifests if m.mismatches)
    if with_mismatch * 2 < len(manifests):
        return f"only {with_mismatch}/{len(manifests)} cases carry a model mismatch (need at least half)"
    return None
