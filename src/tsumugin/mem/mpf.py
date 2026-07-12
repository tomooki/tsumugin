"""実データ MEM-Rietveld 反復 (MPF) (REQ-024/025/026/107/202 / EDGE-008/009 実データ実装)。

M5 の ``mem.iterate.run_mem_rietveld`` は **シミュレート joint** (``JointRefinementResult`` +
``MEMBackend`` Protocol) 上の MPF だった。本モジュールは **精密化済み実データ gpx** に対し、
``mem.gsas.run_dysnomia_mem`` (実 Dysnomia MEM) と GSAS-II の Rietveld 再精密化を交互に回す
実 MPF ループ (``run_mem_rietveld_gpx``) を提供する。

【ループ (REQ-024)】各反復で (1) gpx を子スナップショットへコピー (P2)、(2) Rietveld 再精密化、
  (3) 実 Dysnomia MEM で密度を算出、(4) 収束/発散判定。**既定オフ** (``enabled=False``)。

【非破壊 (P2 / REQ-025/202)】各反復は ``snapshot_dir`` に **独立の gpx ファイル** として追記
  される (前反復の gpx は上書きしない)。ledger に各反復と停止理由を追記する (verify 保持)。

【停止 (REQ-026/107/EDGE-008/009)】Rwp 相対変化 ∧ 密度 max 相対変化がともに閾値未満で収束、
  Rwp 悪化で発散 (当該反復を残し停止)、いずれでもなければ max_iter で停止。

【F_calc 更新の位置づけ (正直な範囲)】Sakata-Takata 型の「重なり反射強度の MEM 再配分」は
  GSAS-II scriptable が露出しないため、本ループの MEM は各反復の精密化済みモデル由来 F から
  実密度を再構成する。ループの実用価値は **密度マップの収束監視** と、モデルで説明されない
  **未モデル密度ピークの提示** (提案のみ・非破壊、構造の自動編集はしない; Dara 教訓) にある。

【core-only import (REQ-403)】``import tsumugin.mem.mpf`` は numpy のみで成功する (GSAS は関数内
  遅延 import)。バイナリ/GSAS 未導入時は ``run_dysnomia_mem`` 経由で ``MEMUnavailableError``。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..store.ledger import Ledger
from .gsas import MEMRunConfig, run_dysnomia_mem


@dataclass(frozen=True)
class MPFConfig:
    """実データ MEM-Rietveld 反復 (MPF) 設定。既定オフ。🔵 REQ-024/026/302

    :param enabled: 反復の有効化 (既定オフ・明示有効化なしでは反復しない)。
    :param max_iter: 最大反復数。
    :param rwp_tol: Rwp 相対変化の収束閾値。
    :param density_tol: 密度 max 相対変化の収束閾値。
    :param worsen_eps: Rwp 悪化 (発散) とみなす相対閾値。
    :param refine_max_cyc: 各反復の Rietveld 再精密化サイクル数。
    :param mem: 各反復の MEM 実行設定。
    :param unmodeled_distance: 未モデル密度ピークとみなす最近接原子距離 (Å) 下限。
    """

    enabled: bool = False
    max_iter: int = 5
    rwp_tol: float = 1e-3
    density_tol: float = 1e-3
    worsen_eps: float = 1e-3
    refine_max_cyc: int = 5
    mem: MEMRunConfig = field(default_factory=MEMRunConfig)
    unmodeled_distance: float = 0.8


@dataclass(frozen=True)
class MPFCycle:
    """MPF 反復 1 サイクルの記録 (子スナップショット gpx 参照付き)。🔵 REQ-025/026"""

    iteration: int  # 【反復番号 (0 始まり)】
    gpx_path: str  # 【子スナップショット gpx パス (追記型・上書きしない)】 🔵 REQ-025
    rwp: float  # 【当該反復の Rietveld Rwp】 🔵 REQ-026
    density_max: float  # 【MEM 密度の最大値】 🔵 REQ-026
    density_min: float  # 【MEM 密度の最小値】
    mem_r_factor: float | None  # 【Dysnomia MEM R 因子 (取得できれば)】
    n_unmodeled: int  # 【未モデル密度ピーク数 (最近接原子まで unmodeled_distance 以上)】


@dataclass(frozen=True)
class MPFResult:
    """MPF 反復の全体結果 (停止理由 + サイクル列)。🔵 REQ-024/026/107

    【非破壊 (REQ-202/NFR-005)】各反復は独立の子スナップショット gpx として追記される。
    """

    cycles: tuple[MPFCycle, ...]  # 【反復サイクル列 (追記順)】 🔵 REQ-025
    stop_reason: Literal["converged", "max_iter", "diverged", "disabled"]  # 🔵 REQ-026/107
    warnings: tuple[str, ...] = ()  # 【発散等の警告】 🔵 REQ-107


# ---------------------------------------------------------------------------
# 純関数 (GSAS 非依存・決定論)
# ---------------------------------------------------------------------------


def _relative_change(prev: float, cur: float) -> float:
    """相対変化 |cur-prev|/max(|prev|,eps) を返す (prev=0 でも発散しない)。🔵 REQ-026"""
    denom = max(abs(prev), 1e-12)
    return abs(cur - prev) / denom


def _decide_stop(
    prev: MPFCycle, cur: MPFCycle, config: MPFConfig
) -> Literal["converged", "diverged"] | None:
    """直前/現反復から停止判定する。継続なら None。🔵 REQ-026/107/EDGE-008

    収束を先に判定する: Rwp と密度 max の相対変化がともに閾値未満なら (符号によらず) 収束
    ノイズとみなし ``converged``。収束でなく Rwp が worsen_eps 超で悪化していれば ``diverged``
    (当該反復を残し停止)。いずれでもなければ継続 (None)。
    """
    if (
        _relative_change(prev.rwp, cur.rwp) < config.rwp_tol
        and _relative_change(prev.density_max, cur.density_max) < config.density_tol
    ):
        return "converged"
    if cur.rwp > prev.rwp * (1.0 + config.worsen_eps):
        return "diverged"
    return None


# ---------------------------------------------------------------------------
# 実 MPF ループ (GSAS-II 遅延 import)
# ---------------------------------------------------------------------------


def _refine_gpx_cycles(gpx_path: str, max_cyc: int) -> float:
    """gpx を現在のフラグで max_cyc サイクル再精密化し Rwp を返す (in-place)。🔵 REQ-024

    GSAS-II の ``do_refinements`` は現在の精密化フラグ (autorietveld が解放済み) を継続する。
    ``do_refinements`` は gpx を自動保存するため、呼び出し側は事前にコピー済みの子スナップショット
    に対して実行すること (前反復の gpx を壊さない)。
    """
    from GSASII import GSASIIscriptable as G2sc  # noqa: PLC0415

    try:
        G2sc.SetPrintLevel("none")
    except Exception:  # noqa: BLE001
        pass
    g = G2sc.G2Project(gpx_path)
    g.data["Controls"]["data"]["max cyc"] = int(max_cyc)
    g.do_refinements([{}])
    g.save(gpx_path)
    cov = g.data["Covariance"]["data"]
    return float(cov.get("Rvals", {}).get("Rwp", float("inf")))


def run_mem_rietveld_gpx(
    gpx_path: str,
    *,
    phase_name: str | None = None,
    hist_name: str | None = None,
    config: MPFConfig = MPFConfig(),
    snapshot_dir: str | None = None,
    ledger: Ledger | None = None,
) -> MPFResult:
    """精密化済み gpx に対し実データ MEM-Rietveld (MPF) 反復を回す。🔵 REQ-024/025/026/107

    【既定オフ (REQ-024)】``config.enabled=False`` なら即 ``stop_reason="disabled"`` を返す
      (子スナップショットも作らない)。
    【反復】各反復で子スナップショット gpx へコピー → Rietveld 再精密化 → 実 Dysnomia MEM →
      収束/発散判定。前反復の gpx は上書きしない (P2)。
    【停止 (REQ-026/107)】Rwp∧密度 max の相対変化 < 閾値で収束、Rwp 悪化で発散 (当該反復を残す)、
      いずれでもなければ max_iter。停止理由と各反復を ledger に追記する。
    """
    if not config.enabled:
        return MPFResult(cycles=(), stop_reason="disabled")

    snap_dir = Path(snapshot_dir) if snapshot_dir is not None else Path(gpx_path).parent
    snap_dir.mkdir(parents=True, exist_ok=True)

    if ledger is not None:
        ledger.append("mpf_start", {"gpx": Path(gpx_path).name, "max_iter": config.max_iter})

    cycles: list[MPFCycle] = []
    warnings: list[str] = []
    stop_reason: Literal["converged", "max_iter", "diverged"] = "max_iter"
    prev_gpx = gpx_path

    for it in range(config.max_iter):
        # 子スナップショット: 前反復の gpx をコピー (P2: 上書きしない)。
        cur_gpx = str(snap_dir / f"mpf_iter{it}.gpx")
        shutil.copyfile(prev_gpx, cur_gpx)

        # (2) Rietveld 再精密化 (現フラグ継続)。
        rwp = _refine_gpx_cycles(cur_gpx, config.refine_max_cyc)

        # (3) 実 Dysnomia MEM (当該反復の gpx 上)。
        mem = run_dysnomia_mem(
            cur_gpx, phase_name=phase_name, hist_name=hist_name, config=config.mem,
            out_grd=str(snap_dir / f"mpf_iter{it}.mem.grd"),
        )
        n_unmodeled = sum(
            1 for p in mem.peaks
            if p.magnitude > 0 and p.distance >= config.unmodeled_distance
        )
        cyc = MPFCycle(
            iteration=it, gpx_path=cur_gpx, rwp=rwp,
            density_max=mem.density_map.max_density,
            density_min=mem.density_map.min_density,
            mem_r_factor=mem.mem_r_factor, n_unmodeled=n_unmodeled,
        )
        cycles.append(cyc)
        if ledger is not None:
            ledger.append("mpf_cycle", {
                "iteration": it, "rwp": round(rwp, 4),
                "density_max": round(cyc.density_max, 4), "n_unmodeled": n_unmodeled,
            })

        # (4) 収束/発散判定 (直前反復と比較)。
        if it > 0:
            decision = _decide_stop(cycles[-2], cyc, config)
            if decision == "diverged":
                stop_reason = "diverged"
                warnings.append(
                    f"反復 {it} で Rwp が悪化 ({cycles[-2].rwp:.3f}→{rwp:.3f}) → 発散停止。"
                    "当該反復の子スナップショットは残します (P2)。"
                )
                break
            if decision == "converged":
                stop_reason = "converged"
                break

        prev_gpx = cur_gpx

    if ledger is not None:
        ledger.append("mpf_done", {"stop_reason": stop_reason, "n_cycles": len(cycles)})

    return MPFResult(cycles=tuple(cycles), stop_reason=stop_reason, warnings=tuple(warnings))
