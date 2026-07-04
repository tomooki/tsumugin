"""operando/hysteresis — 充放電ヒステリシス解析 (FR-315 / REQ-104 / EDGE-007)。

【モジュール概要】: operando 充放電往復のトラジェクトリを、組成 x の隣接差 dx の符号で充電枝/放電枝に
自動分離し (``split_branches``)、共通 x グリッド上で同一 x の枝間差分 (格子/分率) を算出する
(``branch_differences``)。差分レコードは不変値 ``BranchComparison`` で表現する。
【実装方針】: 精密化 backend を呼ばない下流の純関数層。補間は numpy の決定論演算のみ。片枝しか値を持たない
x は該当 value/difference を None にし UserWarning で通知して処理をブロックしない (EDGE-007)。
🔵 信頼性レベル: interfaces.py L329-346 / red-phase 凍結契約 / REQ-104 / EDGE-007 に依拠。
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from tsumugin._json import finite_or_none


@dataclass(frozen=True)
class BranchComparison:
    """同一 x での充電/放電枝差分 (frozen / interfaces.py L329-336)。

    【機能概要】: 共通 x グリッド上の 1 点における充電枝値・放電枝値・差分を保持する不変値。
    【実装方針】: 片枝しか値を持たない x は該当 value と difference を None (捏造しない)。
    【テスト対応】: N4/E1/B4 (差分・片枝 None・frozen)。
    🟡 信頼性レベル: interfaces.py L329-336 / EDGE-007 に依拠。
    """

    x: float  # 【共通 x グリッド点】🟡
    charge_value: float | None  # 【充電枝の補間値】: 域外は None 🟡
    discharge_value: float | None  # 【放電枝の補間値】: 域外は None 🟡
    difference: float | None  # 【枝間差分 charge-discharge】: 片枝欠損は None 🟡


def split_branches(
    x_values: Sequence[float | None],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """組成 x の隣接差 dx の符号で充電枝/放電枝の frame index を分離する。

    【機能概要】: dx = x[i]-x[i-1]。dx>0 のフレーム i を充電枝、dx<0 を放電枝に帰属させる。
    【実装方針】: dx==0 (平坦)・先頭フレーム (dx 未定義)・None/非有限フレームは両枝から除外。
    昇順・重複なし・両枝排他。set 反復に依存せず走査順で決定論。
    【テスト対応】: N3/B5/N7 (往復分離・空/単一/平坦・決定論)。
    🟡 信頼性レベル: red-phase 凍結契約 (dx>0→charge, dx<0→discharge) / REQ-104 / interfaces.py L339-341。

    @param x_values: フレーム順の組成 x 列 (非単調/None 許容)
    @returns: (充電枝 frame index tuple, 放電枝 frame index tuple)
    """
    charge: list[int] = []
    discharge: list[int] = []
    # 【隣接走査】: 先頭 (index 0) は dx 未定義のため index 1 から昇順に評価 🔵
    for i in range(1, len(x_values)):
        prev = x_values[i - 1]
        cur = x_values[i]
        # 【欠損除外】: 隣接いずれかが None は dx 未定義で両枝から除外 (帰属固定) 🔵
        if prev is None or cur is None:
            continue
        # 【非有限除外】: inf/NaN は dx を汚染するため両枝から除外 🔵
        if not (math.isfinite(prev) and math.isfinite(cur)):
            continue
        dx = cur - prev
        # 【符号帰属】: dx>0→充電枝、dx<0→放電枝、dx==0 は平坦として両枝除外 🔵
        if dx > 0:
            charge.append(i)
        elif dx < 0:
            discharge.append(i)
    # 【決定論返却】: 走査順 = 昇順・重複なしの tuple ペア 🔵
    return tuple(charge), tuple(discharge)


def _branch_xy(
    indices: tuple[int, ...],
    x_values: Sequence[float | None],
    values: Sequence[float | None],
) -> tuple[np.ndarray, np.ndarray]:
    """枝の frame index 群から、x 昇順にソートした有限な (x, value) 配列を組む。

    【実装方針】: x/value いずれかが None/非有限のフレームは除外。np.interp 前提の昇順ソートを施す。
    🟡 信頼性レベル: red-phase 凍結契約 (共通グリッド補間) / numpy 決定論演算。
    """
    xs: list[float] = []
    ys: list[float] = []
    for i in indices:
        x = x_values[i]
        y = values[i] if i < len(values) else None
        # 【有限フィルタ】: x/value のいずれかが欠損/非有限なら補間対象外 🔵
        if x is None or y is None:
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        xs.append(float(x))
        ys.append(float(y))
    if not xs:
        return np.empty(0), np.empty(0)
    # 【昇順ソート】: np.interp は xp 昇順が前提。放電枝の降順 x を昇順化 (決定論) 🔵
    order = np.argsort(xs, kind="stable")
    xs_arr = np.asarray(xs, dtype=float)[order]
    ys_arr = np.asarray(ys, dtype=float)[order]
    return xs_arr, ys_arr


def _interp_in_domain(
    grid_x: float, xs: np.ndarray, ys: np.ndarray, *, tol: float
) -> float | None:
    """グリッド点 grid_x が枝の x 域内なら線形補間値、域外は None を返す。

    【実装方針】: 枝が値を持たない (空) / 域外は None (外挿しない・捏造しない)。域内は np.interp。
    🟡 信頼性レベル: red-phase 凍結契約 (片枝しか値を持たない x は None)。
    """
    # 【空枝】: 値を持たない枝は常に None (片枝欠損) 🔵
    if xs.size == 0:
        return None
    # 【域外判定】: [min-tol, max+tol] 外は外挿せず None (境界の float 誤差のみ tol で許容) 🟡
    if grid_x < xs[0] - tol or grid_x > xs[-1] + tol:
        return None
    # 【線形補間】: 域内は np.interp で決定論補間 (境界は端値へクランプ) 🔵
    value = float(np.interp(grid_x, xs, ys))
    # 【非有限保護】: 万一の非有限は共有 finite_or_none で None へ縮退し漏らさない (_json と整合) 🔵
    return finite_or_none(value)


def branch_differences(
    x_values: Sequence[float | None],
    values: Sequence[float | None],
    *,
    n_grid: int = 20,
) -> tuple[BranchComparison, ...]:
    """共通 x グリッド上で充放電枝の同一 x 差分 (格子/分率) を算出する。

    【機能概要】: split_branches で分離した充電枝/放電枝の (x, value) を共通 x グリッドへ線形補間し、
    difference = charge_value - discharge_value を求める。
    【実装方針】: 共通グリッドは両枝の finite な x の全域 (min..max) を n_grid 分割 (n_grid 点)。片枝しか
    値を持たない x は該当 value と difference を None にし UserWarning を 1 回出す (処理はブロックしない)。
    【テスト対応】: N4/E1/N7 (差分・片枝 None+警告・決定論)。
    🟡 信頼性レベル: red-phase 凍結契約 / EDGE-007 / interfaces.py L344-346 に依拠。

    @param x_values: フレーム順の組成 x 列 (非単調/None 許容)
    @param values: x_values と同長のフレーム値列 (格子/分率など差分対象)
    @param n_grid: 共通 x グリッドの分割点数 (既定 20)
    @returns: 共通 x グリッド上の枝間差分レコード列 (x 昇順)
    """
    # 【枝分離】: dx 符号で充電枝/放電枝の frame index を取得 🔵
    charge_idx, discharge_idx = split_branches(x_values)
    charge_x, charge_y = _branch_xy(charge_idx, x_values, values)
    discharge_x, discharge_y = _branch_xy(discharge_idx, x_values, values)

    # 【グリッド域取り】: 両枝の finite x を集約し全域 (min..max) を確定 🔵
    all_x = np.concatenate([charge_x, discharge_x])
    # 【縮退】: 有限 x が全く無ければ差分不能で空 tuple (例外化しない) 🟡
    if all_x.size == 0:
        return ()
    grid_lo = float(np.min(all_x))
    grid_hi = float(np.max(all_x))
    # 【グリッド生成】: [min, max] を n_grid 点で等分。退化 (min==max) は 1 点へ縮退 🟡
    if grid_hi <= grid_lo:
        grid = np.asarray([grid_lo], dtype=float)
    else:
        grid = np.linspace(grid_lo, grid_hi, max(1, n_grid))
    # 【境界許容誤差】: グリッド点と枝端の float 誤差を吸収する微小 tol (決定論定数) 🟡
    tol = 1e-9 * (grid_hi - grid_lo) if grid_hi > grid_lo else 0.0

    comparisons: list[BranchComparison] = []
    saw_single_branch = False  # 【片枝検出フラグ】: 一度でも片枝欠損なら警告 (EDGE-007) 🟡
    for gx in grid:
        grid_x = float(gx)
        charge_value = _interp_in_domain(grid_x, charge_x, charge_y, tol=tol)
        discharge_value = _interp_in_domain(grid_x, discharge_x, discharge_y, tol=tol)
        # 【差分算出】: 両枝が値を持つ x のみ difference を計算、片枝欠損は None (捏造しない) 🔵
        if charge_value is not None and discharge_value is not None:
            difference: float | None = charge_value - discharge_value
        else:
            difference = None
            saw_single_branch = True
        comparisons.append(
            BranchComparison(
                x=grid_x,
                charge_value=charge_value,
                discharge_value=discharge_value,
                difference=difference,
            )
        )

    # 【片枝警告】: 片枝しか値を持たない x が存在したら 1 回だけ通知 (縮退継続) 🟡
    if saw_single_branch:
        warnings.warn(
            "枝間差分: 片枝しか値を持たない x が存在するため該当点の差分を None に縮退しました。",
            UserWarning,
            stacklevel=2,
        )

    # 【決定論返却】: x 昇順グリッドの BranchComparison tuple 🔵
    return tuple(comparisons)
