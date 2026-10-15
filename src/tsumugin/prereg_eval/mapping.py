"""P0 §1.3 / §3.1: 出発構造 ↔ 参照構造の原子対応と、参照値を出発の原子へ写すこと。

準ホールドアウトの参照 CIF はラベルも非対称単位の選び方も出発構造と違う。比較は出発のラベル
(= fit 値のキー ``coord:<相>.<ラベル>``) で行うので、参照の各原子を**出発の対称操作で出発原子の近くへ
運んだ像**として書き直す。esd も同じ回転で写す (軸を入れ替える操作では esd の軸も入れ替わる)。

値は表示しない — 呼び手 (凍結の作業スクリプト) は件数・可否だけを出す。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np

from tsumugin.autorietveld.cif_normalize import Structure
from tsumugin.prereg_eval.structure import RefValue
from tsumugin.site_symmetry import parse_symop

#: 対応とみなす最大距離 (Å)。独立な決定どうしの座標差は 0.1 Å を大きく下回るので、0.5 Å を超えたら別の原子。
MAX_PAIR_DISTANCE = 0.5

Triple = tuple[float, float, float]


@dataclass(frozen=True)
class AtomMapping:
    """出発ラベル → 参照ラベル。``images`` は参照原子を出発原子の近くへ運ぶ (R, t)。"""

    pairs: dict[str, str]
    unmatched: tuple[str, ...]
    distances: dict[str, float] = field(default_factory=dict)
    images: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict, compare=False)

    @property
    def ok(self) -> bool:
        return not self.unmatched


def _metric(s: Structure) -> np.ndarray:
    al, be, ga = np.radians([s.alpha, s.beta, s.gamma])
    a, b, c = s.a, s.b, s.c
    return np.array([
        [a * a, a * b * np.cos(ga), a * c * np.cos(be)],
        [a * b * np.cos(ga), b * b, b * c * np.cos(al)],
        [a * c * np.cos(be), b * c * np.cos(al), c * c],
    ])


def _ops(start: Structure, ref: Structure) -> list[tuple[np.ndarray, np.ndarray]]:
    texts = start.symops or ref.symops or ("x,y,z",)
    return [parse_symop(t) for t in texts]


def _nearest_image(p: np.ndarray, q: np.ndarray, ops, g: np.ndarray):
    """q の対称像のうち p に最も近いもの → (距離 Å, R, 格子並進込みの t)。"""
    best = (np.inf, None, None)
    for r, t in ops:
        img = r @ q + t
        shift = np.round(p - img)
        d = p - (img + shift)
        dist = float(np.sqrt(d @ g @ d))
        if dist < best[0]:
            best = (dist, r, t + shift)
    return best


def map_atoms(start: Structure, ref: Structure, max_distance: float = MAX_PAIR_DISTANCE) -> AtomMapping:
    """元素が同じで、対称像の最短距離が ``max_distance`` 以下の原子を 1 対 1 に対応させる (距離の短い順に貪欲)。"""
    g = _metric(start)
    ops = _ops(start, ref)
    cands = []
    for sa in start.atoms:
        p = np.array([sa.x, sa.y, sa.z])
        for ra in ref.atoms:
            if ra.type_symbol.strip().capitalize() != sa.type_symbol.strip().capitalize():
                continue
            dist, r, t = _nearest_image(p, np.array([ra.x, ra.y, ra.z]), ops, g)
            if dist <= max_distance:
                cands.append((dist, sa.label, ra.label, r, t))
    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    pairs: dict[str, str] = {}
    distances: dict[str, float] = {}
    images: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    used: set[str] = set()
    for dist, s_label, r_label, r, t in cands:
        if s_label in pairs or r_label in used:
            continue
        pairs[s_label], distances[s_label], images[s_label] = r_label, dist, (r, t)
        used.add(r_label)
    unmatched = tuple(a.label for a in start.atoms if a.label not in pairs)
    return AtomMapping(pairs, unmatched, distances, images)


def reference_values(
    start: Structure,
    ref: Structure,
    mapping: AtomMapping,
    esd: Mapping[str, "tuple[float | None, float | None, float | None]"],
    phase: str,
) -> list[RefValue]:
    """対応の付いた出発原子ごとに、参照の座標を出発の位置へ写した `RefValue` (esd も回転で写す)。

    ``esd`` は参照ラベル → (σx, σy, σz)。どれかが無い (None / 0) 原子は σ を None にする (§1.3 で unevaluated)。
    """
    by_label = {a.label: a for a in ref.atoms}
    out: list[RefValue] = []
    for sa in start.atoms:
        r_label = mapping.pairs.get(sa.label)
        if r_label is None:
            continue
        ra = by_label[r_label]
        r, t = mapping.images[sa.label]
        value = r @ np.array([ra.x, ra.y, ra.z]) + t
        sig = esd.get(r_label)
        sigma: Triple | None = None
        if sig is not None and all(s is not None and s > 0 for s in sig):
            s2 = np.array(sig, dtype=float) ** 2
            sigma = tuple(float(v) for v in np.sqrt((r**2) @ s2))  # type: ignore[assignment]
        out.append(RefValue("coord", f"coord:{phase}.{sa.label}", tuple(float(v) for v in value), sigma))  # type: ignore[arg-type]
    return out


def same_to_printed_precision(
    start_raw: Mapping[str, tuple[str, ...]], ref_values: Mapping[str, tuple[float, ...]]
) -> bool:
    """参照の値がすべて、出発ファイルに**書かれた桁数**で出発の値と一致するか (= 出発が参照の写しで独立でない)。

    ``start_raw`` は出発ファイルの字面 (例 ``"0.4000"``)。比べられる値が 1 つも無ければ False (判定できない)。
    """
    compared = 0
    for key, tokens in start_raw.items():
        vals = ref_values.get(key)
        if vals is None or len(vals) != len(tokens):
            return False
        for tok, v in zip(tokens, vals):
            body = tok.split("(")[0].strip()
            exp = Decimal(body).as_tuple().exponent
            half = 0.5 * 10.0 ** int(exp) if isinstance(exp, int) else 0.0
            if abs(float(body) - v) > half + 1e-12:
                return False
            compared += 1
    return compared > 0
