"""初期値プローブ (fit-then-judge P1-1B, proposal §4.5, REQ-FTJ-1B-601〜603)。

最終状態 (保存した精密化済み gpx) から ±δ の 2 開始点で精密化し直し、値が kσ 以内に戻るかを見る。
戻った値は ``locally_stable`` (`claims.build.with_probe`)。「同じ解か」の判定は収束確認と同じ
`agreement.parameter_agreements` (proposal §5)。Δχ² は使わない。

GSAS を回すのは engine の `probe_from_gpx` (注入できる — テスト用のシーム)。gpx を保存しなかった
呼び出しでは回さず、理由を返す (回さなかった値は基底状態のまま — 強いラベルを残さない)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Mapping

from .._config_spec import check_float, check_int, spec_value
from .._json import finite_or_none
from .agreement import AgreementTolerances
from .model import AutoRietveldResult

__all__ = ["ProbeConfig", "ProbeOutcome", "Prober", "run_initial_value_probe"]

#: 座標の一致の許容幅 (`agreement.AgreementTolerances.coord_dist_floor_ang`)。これ以下の変位は証人にならない。
_COORD_FLOOR_ANG = AgreementTolerances().coord_dist_floor_ang  # 写しを持たない (L-b)

#: ``prober(gpx_path, *, cell_frac, coord_jitter_ang, sign, seed, max_cyc, blas_threads)``
Prober = Callable[..., AutoRietveldResult]


@dataclass(frozen=True)
class ProbeConfig:
    """±δ の大きさ。格子は相対 (a,b,c を 1±cell_frac 倍)、座標は Å (大きさ固定・向きは乱数)。

    **一致の許容幅 (`AgreementTolerances`: 格子 1e-4・座標 0.02 Å) を超える値でなければ証人にならない**
    (許容幅より小さく振って「戻った」と言うのは空虚)。値は P1.5 で調整する。
    """

    cell_frac: float = 0.001
    coord_jitter_ang: float = 0.05
    seed: int = 0
    max_cyc: int = 12

    @classmethod
    def from_dict(cls, d: "Mapping[str, object] | None") -> "ProbeConfig":
        """JSON から (未知キー・型違いは ValueError)。"""
        if d is None:
            return cls()
        if not isinstance(d, Mapping):
            raise ValueError(f"initial_value_probe は dict です: {type(d).__name__}")
        if not d:
            return cls()
        known = {"cell_frac", "coord_jitter_ang", "seed", "max_cyc"}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(f"initial_value_probe に未知のキー: {unknown} (既知: {sorted(known)})")
        s = "initial_value_probe"
        cfg = cls(
            cell_frac=spec_value(d, "cell_frac", s, 0.001, check_float),
            coord_jitter_ang=spec_value(d, "coord_jitter_ang", s, 0.05, check_float),
            seed=spec_value(d, "seed", s, 0, check_int),
            max_cyc=spec_value(d, "max_cyc", s, 12, check_int),
        )
        if cfg.cell_frac < 0 or cfg.coord_jitter_ang < 0 or cfg.max_cyc < 1:
            raise ValueError(f"initial_value_probe の値が範囲外です: {cfg}")
        if 0.0 < cfg.coord_jitter_ang <= _COORD_FLOOR_ANG:
            raise ValueError(
                f"initial_value_probe.coord_jitter_ang={cfg.coord_jitter_ang} は一致の許容幅 "
                f"{_COORD_FLOOR_ANG} Å 以下 — 振っても座標の証人にならない (0 か、それより大きい値)"
            )
        if cfg.cell_frac == 0 and cfg.coord_jitter_ang == 0:
            raise ValueError("initial_value_probe: 何も摂動しないプローブは証人になりません")
        return cfg

    def to_dict(self) -> dict[str, object]:
        return {"cell_frac": self.cell_frac, "coord_jitter_ang": self.coord_jitter_ang,
                "seed": self.seed, "max_cyc": self.max_cyc}


@dataclass(frozen=True)
class ProbeOutcome:
    """±δ の結果 (失敗した開始点は None)。``reason`` が空でなければ回さなかった。"""

    config: ProbeConfig
    probes: tuple["AutoRietveldResult | None", ...] = ()
    errors: tuple[str, ...] = ()
    reason: str = ""

    @property
    def complete(self) -> bool:
        """2 開始点とも回った (証人になり得る)。"""
        return len(self.probes) == 2 and all(p is not None for p in self.probes)

    def to_dict(self) -> dict[str, object]:
        return {
            "config": self.config.to_dict(),
            "n_probes": len(self.probes),
            "complete": self.complete,
            "rwp": [finite_or_none(p.final_rwp) if p is not None else None for p in self.probes],
            "errors": list(self.errors),
            # 成果物 (規定 2026-08-20): ±δ の fit そのもの。保存できなかった開始点は空文字
            "gpx_paths": [p.gpx_path if p is not None else "" for p in self.probes],
            "reason": self.reason,
        }


def run_initial_value_probe(
    gpx_path: str,
    config: "ProbeConfig | None" = None,
    *,
    prober: "Prober | None" = None,
) -> ProbeOutcome:
    """保存した gpx から ±δ の 2 開始点を回す。失敗は例外にせず結果に畳む。"""
    cfg = config or ProbeConfig()
    if not gpx_path or not os.path.isfile(gpx_path):
        return ProbeOutcome(cfg, reason="精密化済みの gpx が保存されていない (save_gpx=false 等)")
    if prober is None:
        from .engine import probe_from_gpx as prober  # type: ignore[assignment]
    probes: list["AutoRietveldResult | None"] = []
    errors: list[str] = []
    for sign in (1, -1):
        try:
            probes.append(
                prober(  # type: ignore[misc]
                    gpx_path, cell_frac=cfg.cell_frac, coord_jitter_ang=cfg.coord_jitter_ang,
                    # 同じ種 = 同じ向きのベクトルを ± で反転 (± が本当に対称な 2 開始点になる。N6)
                    sign=sign, seed=cfg.seed, max_cyc=cfg.max_cyc, blas_threads=1,
                )
            )
        except Exception as exc:  # noqa: BLE001 — 回らなかった開始点は「戻った」と数えない
            probes.append(None)
            errors.append(f"sign={sign}: {exc!r}"[:200])
    for sign, p in zip((1, -1), probes):
        note = p.stage_results[0].note if p is not None and p.stage_results else ""
        if p is not None and "save_failed=" in note:
            # fit は回ったが成果物を残せなかった — 証人には影響しないが黙らない (規定 2026-08-20)
            errors.append(f"sign={sign}: 成果物を保存できない ({note.split('save_failed=', 1)[1]})"[:200])
    return ProbeOutcome(cfg, tuple(probes), tuple(errors))
