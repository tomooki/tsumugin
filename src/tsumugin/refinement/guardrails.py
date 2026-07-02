"""ガードレール: 精密化の発散検知 (仕様 FR-211)。

純粋関数。精密化結果 (と前段結果) を受け取り、物理的に破綻した状態を GuardViolation の
タプルとして返す。例外は投げず、ledger 記録や固定戻しの判断は呼び出し側 (段階エンジン) に委ねる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..backends.base import RefinementResult, param_name

GuardKind = Literal[
    "chi2_divergence",
    "negative_occupancy",
    "lattice_runaway",
    "negative_adp",
    "phase_fraction_pinned",
]

# 出力の決定論的順序を定める kind の並び。
_KIND_ORDER: tuple[GuardKind, ...] = (
    "chi2_divergence",
    "negative_occupancy",
    "lattice_runaway",
    "negative_adp",
    "phase_fraction_pinned",
)


@dataclass(frozen=True)
class GuardViolation:
    kind: GuardKind
    detail: str
    param: str | None = None


@dataclass(frozen=True)
class GuardConfig:
    chi2_worsen_ratio: float = 1.5
    # 発散判定に要求する chi2 の絶対増分 (1 データ点あたり)。ノイズフリーの
    # 合成データ等で chi2≈0 のとき、数値ゆらぎの比率爆発を発散と誤検知しないため。
    chi2_worsen_floor_per_obs: float = 0.01
    lattice_shift_frac: float = 0.2
    min_wt_frac: float = 1e-4


def check_guards(
    prev: RefinementResult | None,
    cur: RefinementResult,
    *,
    config: GuardConfig = GuardConfig(),
) -> tuple[GuardViolation, ...]:
    """cur の状態を検査し、検知した違反を kind 定義順で返す。"""
    found: list[GuardViolation] = []

    # chi2 発散 (前段がある場合のみ)。比率超過に加えて絶対増分の下限も要求する。
    if prev is not None:
        floor = config.chi2_worsen_floor_per_obs * max(cur.n_obs, 1)
        worsened_ratio = cur.chi2 > prev.chi2 * config.chi2_worsen_ratio
        worsened_abs = (cur.chi2 - prev.chi2) > floor
        if worsened_ratio and worsened_abs:
            found.append(
                GuardViolation(
                    kind="chi2_divergence",
                    detail=f"chi2 {prev.chi2:.4g} -> {cur.chi2:.4g} "
                    f"(>{config.chi2_worsen_ratio}x, +{cur.chi2 - prev.chi2:.4g})",
                )
            )

    # 占有率・ADP の負値
    for i, phase in enumerate(cur.phases):
        for site, value in phase.occupancies.items():
            if value < 0:
                if site.startswith("adp_"):
                    found.append(
                        GuardViolation(
                            kind="negative_adp",
                            detail=f"phase{i} {site}={value:.4g} < 0",
                            param=param_name(i, f"occ.{site}"),
                        )
                    )
                else:
                    found.append(
                        GuardViolation(
                            kind="negative_occupancy",
                            detail=f"phase{i} occ[{site}]={value:.4g} < 0",
                            param=param_name(i, f"occ.{site}"),
                        )
                    )

    # 格子暴走 (前段比)
    if prev is not None:
        for i, phase in enumerate(cur.phases):
            if i >= len(prev.phases):
                continue
            prev_lat = prev.phases[i].lattice
            cur_lat = phase.lattice
            for attr in ("a", "b", "c"):
                p0 = getattr(prev_lat, attr)
                p1 = getattr(cur_lat, attr)
                if p0 > 0 and abs(p1 - p0) / p0 > config.lattice_shift_frac:
                    found.append(
                        GuardViolation(
                            kind="lattice_runaway",
                            detail=f"phase{i} lattice.{attr} {p0:.4g} -> {p1:.4g}",
                            param=param_name(i, f"lattice.{attr}"),
                        )
                    )

    # 相分率のゼロ張り付き
    for i, phase in enumerate(cur.phases):
        if phase.wt_frac is not None and phase.wt_frac < config.min_wt_frac:
            found.append(
                GuardViolation(
                    kind="phase_fraction_pinned",
                    detail=f"phase{i} wt_frac={phase.wt_frac:.4g} < {config.min_wt_frac}",
                    param=param_name(i, "wt_frac"),
                )
            )

    order = {kind: rank for rank, kind in enumerate(_KIND_ORDER)}
    found.sort(key=lambda v: (order[v.kind], v.param or ""))
    return tuple(found)
