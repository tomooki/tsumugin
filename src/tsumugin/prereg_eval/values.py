"""P0 §1.6: 出版状態 (`claims`) から 1A の値の集合 V の状態 (`onea.ValueState`) を作る。

- **V** = 各相の独立な格子定数・自由座標・精密化した占有率・Uiso・相分率。プロファイル・背景・装置の値と
  結晶子サイズ/微小歪みは入れない。対称で決まる値 (``provenance`` が ``symmetry``) は独立でも自由でもないので外す。
  占有率は精密化したもの (``refined``) だけ。座標は自由座標なら解放しなかったものも入れる (凍結に無料の得点を与えない)。
- **外れ** (§1.6) はそのアーム自身の esd で §1.3 の定義を当てる。座標は原子ごと (軸ごとの値は原子の判定を継ぐ)。
- **主相** (§1.3) = Σ Fc²·Icorr (全ヒストグラムの和) が最大の相。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np

from .onea import ValueState
from .structure import OUTLIER_U, FitValue, RefValue, deviations

__all__ = ["V_CLASSES", "main_phase", "outlier_map", "value_states"]

V_CLASSES = frozenset({"cell", "coord", "occupancy", "uiso", "weight_fraction"})


def main_phase(result: object) -> str | None:
    pii = getattr(result, "phase_integrated_intensity", None)
    if not pii:
        return None
    totals = {ph: sum(float(v) for v in vals if v is not None) for ph, vals in pii.items()}
    return max(sorted(totals), key=lambda ph: totals[ph]) if totals else None


def outlier_map(reference: Iterable[RefValue], fits: Iterable[FitValue], *, lattice: np.ndarray) -> dict[str, bool]:
    """比較集合のキー (``coord:<相>.<ラベル>`` など) → 外れたか。評価できない値は入れない。"""
    d = deviations(reference, fits, lattice=lattice)
    return {k: u > OUTLIER_U for k, u in d.values.items()}


def _comparison_key(claim: object) -> str | None:
    cls = getattr(claim, "param_class", "")
    key = str(getattr(claim, "key", ""))
    body = key.split(":", 1)[1] if ":" in key else key
    if cls == "coord":
        return "coord:" + body.rsplit(".", 1)[0]
    if cls == "occupancy":
        return "occ:" + body
    if cls == "cell":
        return "cell:" + body
    return None


def value_states(
    claims: Mapping[str, object], *, main: str | None, outliers: Mapping[str, bool]
) -> list[ValueState]:
    out: list[ValueState] = []
    for key in sorted(claims):
        c = claims[key]
        cls = getattr(c, "param_class", "")
        prov = frozenset(getattr(c, "provenance", frozenset()))
        if cls not in V_CLASSES or "symmetry" in prov:
            continue
        if cls == "occupancy" and "refined" not in prov:
            continue
        ck = _comparison_key(c)
        det = getattr(c, "determinacy", "")
        out.append(ValueState(
            key=key,
            publishable=bool(getattr(c, "publishable", False)),
            determinacy=str(getattr(det, "value", det)),
            main_phase=main is not None and getattr(c, "phase", None) == main,
            outlier=None if ck is None else outliers.get(ck),
            blocked_by=tuple(sorted(getattr(c, "gate", ()) or ())),
        ))
    return out
