"""実構造 Rietveld のマルチスタート大域最適確認 (Issue #13)。

`run_auto_rietveld` を複数の初期格子摂動点から実行し、収束先をベイスン分類して大域最適の傍証
(全 valid 開始点が単一ベイスンへ収束) を得る。Rietveld は初期値依存の非線形最小二乗で局所解が
多く、単一開始点の自動解析は大域最適を保証しない。既存 `tsumugin.multistart` の摂動幅
(`PerturbationSpec`) と設定 (`MultistartConfig`) を再利用する。

開始点生成・ベイスン分類・最良選択は純関数 (numpy 非依存の決定論ロジック) でユニットテスト可能。
実行 (`run_multistart_rietveld`) のみ GSAS を遅延経由で使う。

スコープ (Issue #13): シーケンシャル実行 + 初期格子摂動軸。並列・原子座標摂動は M-later。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..multistart.perturb import MultistartConfig
from ..store import Ledger
from .model import AutoRietveldResult, HistogramSpec, PhaseSpec


@dataclass(frozen=True)
class MultistartStart:
    """1 開始点: 相名→(fa,fb,fc) 初期格子摂動倍率と、その実行結果 (未実行は None)。"""

    index: int
    cell_scale: Mapping[str, tuple[float, float, float]]
    result: AutoRietveldResult | None = None


@dataclass(frozen=True)
class RietveldMultistartResult:
    """マルチスタート大域最適確認の結果。

    :param best: 最良 (valid かつ最小 final_rwp) の AutoRietveldResult。valid が無ければ最小 Rwp。
        全開始点が実行失敗 (例外) の場合は None (best_index=-1)。
    :param best_index: best を与えた開始点 index。全滅時は -1。
    :param starts: 全開始点 (摂動と結果)。
    :param n_starts: 実行開始点数。
    :param n_diverged: 発散 (final_rwp 非有限) で除外した開始点数。
    :param n_basins: 収束先ベイスン数 (valid 開始点を格子一致でクラスタ)。
    :param is_global_corroborated: n_basins == 1 (大域最適の傍証あり)。
    :param warnings: 縮退・全滅などの警告。
    """

    best: AutoRietveldResult | None
    best_index: int
    starts: tuple[MultistartStart, ...]
    n_starts: int
    n_diverged: int
    n_basins: int
    is_global_corroborated: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _grid_scales(n_starts: int, lattice_frac: float) -> list[float]:
    """1.0 を中心に ±lattice_frac へ対称に配した等方倍率列 (決定論)。

    ``t = -1 + 2i/(n-1)`` を用いるため両側を均等に探索する (M4: 偶数 n でも非対称/重複が出ない)。
    **奇数 n は中心 t=0 を持ち無摂動 1.0 を正確に含む** (整数演算で 1.0 が厳密)。n_starts==1 なら [1.0]。
    """
    if n_starts <= 1:
        return [1.0]
    return [1.0 + lattice_frac * (-1.0 + 2.0 * i / (n_starts - 1)) for i in range(n_starts)]


def generate_cell_scales(
    phase_names: Sequence[str], config: MultistartConfig
) -> tuple[dict[str, tuple[float, float, float]], ...]:
    """決定論的に n_starts 個の初期格子摂動 (相名→等方倍率 (f,f,f)) を生成する。

    全相に同一の等方倍率を与える (格子スケールの局所解確認)。1.0 を中心に ±lattice_frac へ対称配置。
    奇数 n_starts では中心に無摂動 1.0 を含む (偶数は両側対称・中心なし)。
    """
    scales = _grid_scales(config.n_starts, config.spec.lattice_frac)
    starts: list[dict[str, tuple[float, float, float]]] = []
    for f in scales:
        starts.append({name: (f, f, f) for name in phase_names})
    return tuple(starts)


def _cell_key(result: AutoRietveldResult) -> tuple[float, ...]:
    """ベイスン距離用に相ごとの格子 a,b,c を連結したベクトル。"""
    key: list[float] = []
    for name in sorted(result.refined_cells):
        key.extend(result.refined_cells[name][:3])
    return tuple(key)


def _same_basin(k1: tuple[float, ...], k2: tuple[float, ...], rel_tol: float) -> bool:
    """2 つの格子ベクトルが相対許容内で一致するか (同一ベイスン判定)。"""
    if len(k1) != len(k2):
        return False
    for a, b in zip(k1, k2):
        denom = max(abs(a), abs(b), 1e-9)
        if abs(a - b) / denom > rel_tol:
            return False
    return True


def cluster_rietveld_basins(
    results: Sequence[AutoRietveldResult], rel_tol: float
) -> int:
    """valid 結果を格子一致でクラスタしたベイスン数を返す (決定論)。"""
    keys = [_cell_key(r) for r in results]
    reps: list[tuple[float, ...]] = []
    for k in keys:
        if not any(_same_basin(k, rep, rel_tol) for rep in reps):
            reps.append(k)
    return len(reps)


def _is_valid(result: AutoRietveldResult) -> bool:
    return math.isfinite(result.final_rwp) and result.validity.passed


def select_best(
    starts: Sequence[MultistartStart],
) -> tuple[int, AutoRietveldResult | None]:
    """valid かつ最小 final_rwp の (index, result)。valid が無ければ最小 Rwp。

    実行済み開始点が 1 つも無い (全て result=None) 場合は (-1, None) を返す (M5: crash 回避)。
    """
    executed = [s for s in starts if s.result is not None]
    if not executed:
        return -1, None
    valid = [s for s in executed if _is_valid(s.result)]  # type: ignore[arg-type]
    pool = valid if valid else executed
    best = min(pool, key=lambda s: s.result.final_rwp)  # type: ignore[union-attr]
    return best.index, best.result


def summarize_multistart(
    starts: Sequence[MultistartStart], config: MultistartConfig
) -> RietveldMultistartResult:
    """実行済み開始点群からベイスン数・傍証・最良を集計する (純関数, GSAS 非依存)。"""
    executed = [s for s in starts if s.result is not None]
    finite = [s for s in executed if _is_valid_or_finite(s.result)]  # type: ignore[arg-type]
    n_diverged = len(executed) - len(finite)
    valid_results = [s.result for s in executed if _is_valid(s.result)]  # type: ignore[arg-type]
    n_basins = cluster_rietveld_basins(valid_results, config.basin_rel_tol) if valid_results else 0
    warnings: list[str] = []
    if not executed:
        warnings.append("実行された開始点がありません")
    if valid_results and n_basins > 1:
        warnings.append(f"収束先が {n_basins} ベイスンに分岐 (大域最適は未確定)")
    if executed and not valid_results:
        warnings.append("valid な収束が得られませんでした (全開始点が発散/非物理)")
    best_index, best = select_best(starts)
    return RietveldMultistartResult(
        best=best,
        best_index=best_index,
        starts=tuple(starts),
        n_starts=len(executed),
        n_diverged=n_diverged,
        n_basins=n_basins,
        is_global_corroborated=(n_basins == 1),
        warnings=tuple(warnings),
    )


def _is_valid_or_finite(result: AutoRietveldResult) -> bool:
    return math.isfinite(result.final_rwp)


def run_multistart_rietveld(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    config: MultistartConfig | None = None,
    ledger: Ledger | None = None,
    **run_kwargs: object,
) -> RietveldMultistartResult:
    """複数の初期格子摂動点から `run_auto_rietveld` を実行し大域最適を確認する (Issue #13)。

    :param histograms: 観測ヒストグラム仕様
    :param phases: 相仕様
    :param config: マルチスタート設定 (n_starts / spec.lattice_frac / basin_rel_tol)。None で既定。
    :param ledger: 遷移を追記する Ledger (None で内部生成)。開始点ごとの最良 Rwp を記録。
    :param run_kwargs: `run_auto_rietveld` へ透過する追加引数 (max_cyc, recipe 等)。
    :returns: RietveldMultistartResult (最良 + ベイスン数 + is_global_corroborated)。
    """
    from .engine import run_auto_rietveld

    config = config if config is not None else MultistartConfig()
    ledger = ledger if ledger is not None else Ledger()
    phase_names = [p.phase_name for p in phases]
    scales = generate_cell_scales(phase_names, config)

    starts: list[MultistartStart] = []
    for i, scale in enumerate(scales):
        try:
            result = run_auto_rietveld(
                histograms, phases, initial_cell_scale=scale, **run_kwargs  # type: ignore[arg-type]
            )
        except Exception as exc:  # 実行失敗は発散扱い (結果 None) で継続
            ledger.append("multistart_error", {"start": i, "error": repr(exc)[:200]})
            starts.append(MultistartStart(index=i, cell_scale=scale, result=None))
            continue
        ledger.append(
            "multistart_start",
            {"start": i, "scale": scale, "rwp": result.final_rwp, "valid": result.validity.passed},
        )
        starts.append(MultistartStart(index=i, cell_scale=scale, result=result))

    return summarize_multistart(starts, config)
