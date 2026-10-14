"""P0 §1.6・§4: 1A の指標と、その反証 R1A-1 / R1A-2。

- ``P_val`` = 値の集合 V のうち出版できない値の割合 (全事例をまとめて)。
- ``P_case`` = 主相の値がすべて出版できない事例の割合 (主相の値を持つ事例が分母)。
- ``O_det`` / ``O_pub`` = ``determined`` / ``publishable`` の値のうち参照から外れた値の割合 (参照のある値だけ。
  外れの判定は呼び手がそのアーム自身の esd で行い ``outlier`` に入れる — §1.6)。
- 報告のみ: ``O_esd_only``・止めすぎ率 (出版できない値のうち参照と一致するもの)・原因の帰属表。
- R1A-1: ``P_val > 0.50`` または ``P_case > 0.50``。R1A-2: ``O_det > 0.10`` または ``O_pub > 0.10``。
  **それぞれの率の分母が 30 未満なら、その率は判定不能** (P0 は「参照のある値が 30 未満なら判定不能」。率ごとに当てる
  — `determined` の値が数件しか無いのに参照のある値全体の数で判定可能にしない)。
- 区間は事例単位のブートストラップ (10,000 回、種 20261012) の 95% パーセンタイル区間。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

__all__ = ["BOOTSTRAP_ITERATIONS", "BOOTSTRAP_SEED", "OneAResult", "ValueState", "assess_1a", "bootstrap_interval"]

BOOTSTRAP_ITERATIONS = 10_000
BOOTSTRAP_SEED = 20261012
_P_LIMIT = 0.50
_O_LIMIT = 0.10
_MIN_REF_VALUES = 30


@dataclass(frozen=True)
class ValueState:
    """V の 1 値。``outlier``: 参照から外れたか (参照が無い・評価できなければ None)。"""

    key: str
    publishable: bool
    determinacy: str
    main_phase: bool
    outlier: bool | None
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class OneAResult:
    p_val: float | None
    p_case: float | None
    o_det: float | None
    o_pub: float | None
    o_esd_only: float | None
    overblocking: float | None
    n_ref_values: int
    attribution: dict[str, int] = field(default_factory=dict)
    o_det_interval: tuple[float, float] | None = None
    o_pub_interval: tuple[float, float] | None = None
    r1a_1: str = "indeterminate"
    r1a_2: str = "indeterminate"


def _rate(values: Sequence[ValueState], pick) -> tuple[float | None, int]:  # noqa: ANN001
    pool = [v for v in values if pick(v) and v.outlier is not None]
    if not pool:
        return None, 0
    return sum(1 for v in pool if v.outlier) / len(pool), len(pool)


def _per_case(cases: Sequence[Sequence[ValueState]], pick) -> list[tuple[int, int]]:  # noqa: ANN001
    out = []
    for vals in cases:
        pool = [v for v in vals if pick(v) and v.outlier is not None]
        out.append((sum(1 for v in pool if v.outlier), len(pool)))
    return out


def bootstrap_interval(
    per_case: Sequence[tuple[int, int]], *, iterations: int = BOOTSTRAP_ITERATIONS, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float] | None:
    """(外れ数, 値の数) の事例ごとの組から、まとめた率の 95% パーセンタイル区間 (事例を復元抽出)。"""
    if not per_case or sum(n for _, n in per_case) == 0:
        return None
    hits = np.array([h for h, _ in per_case], dtype=float)
    ns = np.array([n for _, n in per_case], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(per_case), size=(iterations, len(per_case)))
    tot = ns[idx].sum(axis=1)
    rates = np.where(tot > 0, hits[idx].sum(axis=1) / np.where(tot > 0, tot, 1.0), np.nan)
    rates = rates[~np.isnan(rates)]
    lo, hi = np.percentile(rates, [2.5, 97.5])
    return float(lo), float(hi)


def assess_1a(cases: Sequence[Sequence[ValueState]]) -> OneAResult:
    """事例ごとの値の状態から 1A の指標と R1A-1 / R1A-2 を計算する。"""
    flat = [v for vals in cases for v in vals]
    p_val = (sum(1 for v in flat if not v.publishable) / len(flat)) if flat else None
    with_main = [vals for vals in cases if any(v.main_phase for v in vals)]
    p_case = (
        sum(1 for vals in with_main if all(not v.publishable for v in vals if v.main_phase)) / len(with_main)
        if with_main
        else None
    )
    attribution = Counter(b for v in flat if not v.publishable for b in v.blocked_by)

    def is_det(v: ValueState) -> bool:
        return v.determinacy == "determined"

    def is_pub(v: ValueState) -> bool:
        return v.publishable

    o_det, n_det = _rate(flat, is_det)
    o_pub, n_pub = _rate(flat, is_pub)
    o_esd, _ = _rate(flat, lambda v: v.determinacy == "esd_only")
    held = [v for v in flat if not v.publishable and v.outlier is not None]
    overblocking = (sum(1 for v in held if not v.outlier) / len(held)) if held else None

    if p_val is None or p_case is None:
        r1a_1 = "indeterminate"
    else:
        r1a_1 = "fired" if (p_val > _P_LIMIT or p_case > _P_LIMIT) else "not_fired"

    def state(rate: float | None, n: int) -> str | None:
        if rate is None:
            return None  # その種類の値が無い = その率は空 (例: Phase B の無い経路の O_det)
        if n < _MIN_REF_VALUES:
            return "indeterminate"
        return "fired" if rate > _O_LIMIT else "not_fired"

    states = [s for s in (state(o_det, n_det), state(o_pub, n_pub)) if s is not None]
    if "fired" in states:
        r1a_2 = "fired"
    elif not states or "indeterminate" in states:
        r1a_2 = "indeterminate"
    else:
        r1a_2 = "not_fired"

    return OneAResult(
        p_val=p_val,
        p_case=p_case,
        o_det=o_det,
        o_pub=o_pub,
        o_esd_only=o_esd,
        overblocking=overblocking,
        n_ref_values=sum(1 for v in flat if v.outlier is not None),
        attribution=dict(attribution),
        o_det_interval=bootstrap_interval(_per_case(cases, is_det)),
        o_pub_interval=bootstrap_interval(_per_case(cases, is_pub)),
        r1a_1=r1a_1,
        r1a_2=r1a_2,
    )
