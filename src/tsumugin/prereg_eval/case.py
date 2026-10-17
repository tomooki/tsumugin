"""P0 §2.1: 事例ごとの劣化の判定 W_i (テンプレート対 比較相手 1 つ)。

| 小項目 | 条件 (W_i = 1) |
|---|---|
| (a) | テンプレートのアームが失敗し、比較相手は失敗していない (比較相手だけ失敗なら比較相手の負け) |
| (b) | ``χ²(T-*/bkg) / χ²(比較相手) > 1.10`` (観測集合のハッシュが一致するときだけ — §1.5) |
| (c) | 参照あり: ``D_T − D_B > 1.0`` または ``n_out,T − n_out,B ≥ 2`` (分母はアーム間で共通 — §1.3) |
| (d) | ``f_T > f_B`` (全事例) |
| (e) | 参照なし: ``b_T − b_B ≥ 2`` |

判定できない小項目は飛ばす。全部できなければ事例ごと ``unevaluated``。両方失敗は ``both_failed`` (劣化に数えない)。
構造の部分 ((c)(d)(e)) は §1.2 の 50% 規則のために別にまとめる。失敗で決まった事例の構造は ``n/a``
(比べようがないのであって「評価できなかった」のではない)。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from .structure import FitValue, RefValue, deviations, metrics

__all__ = [
    "CHI2_RATIO_MARGIN",
    "D_MARGIN",
    "N_OUT_MARGIN",
    "SHORT_BOND_MARGIN",
    "ArmOutcome",
    "CaseInput",
    "Judgment",
    "judge",
]

#: P0 U3 / U4 の同値幅
CHI2_RATIO_MARGIN = 1.10
D_MARGIN = 1.0
N_OUT_MARGIN = 2
SHORT_BOND_MARGIN = 2


@dataclass(frozen=True)
class ArmOutcome:
    """1 (事例, アーム) の結果を写した不変の値 (GSAS を知らない)。"""

    failed: bool
    chi2: float | None = None
    obs_hash: str | None = None
    values: tuple[FitValue, ...] = ()
    fail_count: int | None = None
    short_bonds: int | None = None
    failure_reason: str = ""


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    reference: tuple[RefValue, ...] | None
    lattice: tuple[tuple[float, ...], ...] | None
    arms: Mapping[str, ArmOutcome] = field(default_factory=dict)


@dataclass(frozen=True)
class Judgment:
    """``status``: degraded / not_degraded / unevaluated / both_failed。``structure``: 同じ語彙 + ``n/a``。"""

    status: str
    structure: str
    fired: tuple[str, ...]
    evaluated: tuple[str, ...]


def _finite(x: float | None) -> bool:
    return x is not None and math.isfinite(float(x))


def _fit_item(tf: ArmOutcome, b: ArmOutcome) -> bool | None:
    """(b) が発火したか。判定できなければ None。"""
    if tf.failed or not _finite(tf.chi2) or not _finite(b.chi2):
        return None
    if tf.obs_hash is None or tf.obs_hash != b.obs_hash or float(b.chi2) <= 0.0:  # type: ignore[arg-type]
        return None
    return float(tf.chi2) / float(b.chi2) > CHI2_RATIO_MARGIN  # type: ignore[arg-type]


def _reference_item(case: CaseInput, t: ArmOutcome, b: ArmOutcome) -> bool | None:
    """(c) が発火したか。判定できなければ None。"""
    if case.reference is None or case.lattice is None:
        return None
    lattice = np.asarray(case.lattice, dtype=float)
    dt = deviations(case.reference, t.values, lattice=lattice, other=b.values)
    db = deviations(case.reference, b.values, lattice=lattice, other=t.values)
    mt = metrics(dt.values, unevaluated=dt.unevaluated)
    mb = metrics(db.values, unevaluated=db.unevaluated)
    if mt.d is None or mb.d is None:
        return None
    return mt.d - mb.d > D_MARGIN or (mt.n_out or 0) - (mb.n_out or 0) >= N_OUT_MARGIN


def judge(case: CaseInput, *, template: str, comparator: str, template_fit: str) -> Judgment:
    """``template`` 対 ``comparator`` の W_i。フィット (b) は ``template_fit`` (= ``T-*/bkg``) で比べる。"""
    t = case.arms[template]
    b = case.arms[comparator]
    if t.failed and b.failed:
        return Judgment("both_failed", "n/a", (), ())
    if t.failed:
        return Judgment("degraded", "n/a", ("a",), ("a",))
    if b.failed:
        return Judgment("not_degraded", "n/a", (), ("a",))

    items: dict[str, bool | None] = {
        "b": _fit_item(case.arms.get(template_fit, t), b),
        "c": _reference_item(case, t, b),
        "d": None if t.fail_count is None or b.fail_count is None else t.fail_count > b.fail_count,
        "e": (
            None
            if case.reference is not None or t.short_bonds is None or b.short_bonds is None
            else t.short_bonds - b.short_bonds >= SHORT_BOND_MARGIN
        ),
    }
    evaluated = tuple(k for k, v in items.items() if v is not None)
    fired = tuple(k for k, v in items.items() if v)
    if not evaluated:
        return Judgment("unevaluated", "unevaluated", (), ())
    structure_items = [k for k in ("c", "d", "e") if items[k] is not None]
    if not structure_items:
        structure = "unevaluated"
    elif any(items[k] for k in structure_items):
        structure = "degraded"
    else:
        structure = "not_degraded"
    return Judgment("degraded" if fired else "not_degraded", structure, fired, evaluated)
