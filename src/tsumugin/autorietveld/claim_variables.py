"""値のキー → それが依存する GSAS 変数名 (fit-then-judge P1-1A。GSAS 非依存の純写像)。

`claims` は値の出自を**最終の共分散の varyList**で決める (esd の三状態は「未解放・revert・共分散なし」を
区別しないため — proposal §3.1)。そのために値ごとに「どの GSAS 変数が動けばこの値が動くか」が要る。
相 ID・原子行の添字とラベルの対応を知っているのは engine だけなので、engine はここへ相とヒストグラムの
最小情報 (`PhaseVariables`/`HistogramVariables`) を渡し、結果の ``claim_variables`` に載せる。

値のキーは ``"<class>:<比較キー>"`` で、比較キーは `autorietveld.agreement` が開始点の比較に使う
文字列と同じ (収束確認の判定を値ごとに引き当てるため)。GSAS の変数名の形:

| 値 | GSAS 変数 |
|---|---|
| 格子 a..γ | ``<pid>::A<k>`` (逆格子計量テンソル) のうち、**精密化後の格子でその軸が実際に依存する項** (`cell_axis_terms`)。格子が分からなければ 6 項全部 |
| 座標 | ``<pid>::dA<x\\|y\\|z>:<原子行>`` |
| Uiso / 占有率 | ``<pid>::AUiso:<i>`` / ``<pid>::Afrac:<i>`` |
| 質量分率 | 全相の ``<pid>:<hid>:Scale`` (分率は全相のスケールの比) |
| サイズ / 微小歪み | ``<pid>:<hid>:Size;i`` / ``<pid>:<hid>:Mustrain;i`` (等方の代表成分) |
| プロファイル | ``:<hid>:<key>`` |

⚠ ヒストグラムは GSAS の **id** (`hid`) で名前を作る。列挙の位置 (`index`) は値のキー側
(``hist<index>``) にだけ使う (`engine._profile_esd_map` と同じ区別)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from typing import Sequence

__all__ = [
    "HistogramVariables", "PhaseVariables", "cell_axis_terms", "claim_variable_names",
    "kalpha2_positions",
]

_CELL_AXES = ("a", "b", "c", "alpha", "beta", "gamma")
_CELL_TERMS = tuple(f"A{i}" for i in range(6))


@dataclass(frozen=True)
class PhaseVariables:
    """相 1 つの名前・GSAS の相 id・原子ラベル (原子行の並び)。"""

    name: str
    pid: int
    labels: tuple[str, ...]
    #: 精密化後の格子 (a,b,c,α,β,γ)。あれば格子の各軸が依存する項を絞る (`cell_axis_terms`)
    cell: tuple[float, float, float, float, float, float] | None = None


@dataclass(frozen=True)
class HistogramVariables:
    """ヒストグラム 1 つの列挙位置・GSAS の id・持っているプロファイル項。"""

    index: int
    hid: int
    profile_keys: tuple[str, ...]


def claim_variable_names(
    phases: Sequence[PhaseVariables], histograms: Sequence[HistogramVariables]
) -> dict[str, tuple[str, ...]]:
    """値のキー → 依存する GSAS 変数名の組。"""
    out: dict[str, tuple[str, ...]] = {}
    all_scales = tuple(
        f"{ph.pid}:{h.hid}:Scale" for ph in phases for h in histograms
    )
    for ph in phases:
        terms = cell_axis_terms(ph.cell) if ph.cell is not None else None
        for axis in _CELL_AXES:
            idx = terms[axis] if terms is not None else tuple(range(6))
            out[f"cell:{ph.name}.{axis}"] = tuple(f"{ph.pid}::{_CELL_TERMS[k]}" for k in idx)
        for i, label in enumerate(ph.labels):
            for axis in "xyz":
                out[f"coord:{ph.name}.{label}.{axis}"] = (f"{ph.pid}::dA{axis}:{i}",)
            out[f"uiso:{ph.name}.{label}"] = (f"{ph.pid}::AUiso:{i}",)
            out[f"occupancy:{ph.name}.{label}"] = (f"{ph.pid}::Afrac:{i}",)
        out[f"weight_fraction:{ph.name}.wt"] = all_scales
        for h in histograms:
            out[f"microstructure:{ph.name}.hist{h.index}.size"] = (f"{ph.pid}:{h.hid}:Size;i",)
            out[f"microstructure:{ph.name}.hist{h.index}.mustrain"] = (
                f"{ph.pid}:{h.hid}:Mustrain;i",
            )
    for h in histograms:
        for key in h.profile_keys:
            out[f"profile:hist{h.index}.{key}"] = (f":{h.hid}:{key}",)
    return out


def kalpha2_positions(two_theta: "Sequence[float]", lam1: float, lam2: float) -> tuple[float, ...]:
    """Kα1 の反射位置 (2θ, deg) に対応する Kα2 の位置。GSAS の反射リストは Kα1 の位置しか持たない。

    ``sin θ₂ = (λ₂/λ₁) sin θ₁``。θ₂ が 90° を越える (後方散乱で Kα2 が測定範囲外) ものは落とす。
    """
    ratio = float(lam2) / float(lam1)
    out = []
    for tt in two_theta:
        if not math.isfinite(float(tt)):
            continue  # 1 つの非有限値で残りの Kα2 を失わない (呼び手は例外を握って Kα1 だけで続ける)
        s2 = ratio * math.sin(math.radians(float(tt) / 2.0))
        if s2 < 1.0:
            out.append(2.0 * math.degrees(math.asin(s2)))
    return tuple(out)


def _cell_params(a_terms: np.ndarray) -> np.ndarray:
    """GSAS の逆格子計量テンソル項 A0..A5 → (a, b, c, α, β, γ)。"""
    a0, a1, a2, a3, a4, a5 = a_terms
    gstar = np.array([[a0, a3 / 2, a4 / 2], [a3 / 2, a1, a5 / 2], [a4 / 2, a5 / 2, a2]])
    g = np.linalg.inv(gstar)
    a, b, c = np.sqrt(np.diag(g))
    alpha = np.degrees(np.arccos(g[1, 2] / (b * c)))
    beta = np.degrees(np.arccos(g[0, 2] / (a * c)))
    gamma = np.degrees(np.arccos(g[0, 1] / (a * b)))
    return np.array([a, b, c, alpha, beta, gamma])


def cell_axis_terms(cell: "Sequence[float]") -> dict[str, tuple[int, ...]]:
    """格子の各軸 (a..γ) が、精密化後の格子で**実際に依存する**計量テンソル項の添字 (0..5)。

    GSAS は格子を逆格子計量テンソル ``A0=a*², A1=b*², A2=c*², A3=2a*b*cosγ*, A4=2a*c*cosβ*,
    A5=2b*c*cosα*`` で精密化する。直方晶なら a は A0 だけ、単斜晶 (b 軸ユニーク) なら b は A1 だけで
    a・c・β は A0・A2・A4 に依存する — 対称性で 0 の項に対する微分は 0 になるので、数値ヤコビアンで
    結晶系ごとの表を持たずに決まる。全軸を全項に依存させると、1 項の剪定で 6 軸すべてが止まる
    (止めすぎ)。計算できない格子 (退化) は全項を返す (止めすぎる側に倒す)。
    """
    every = {axis: tuple(range(6)) for axis in _CELL_AXES}
    try:
        a, b, c, al, be, ga = (float(v) for v in cell)
        ca, cb, cg = (math.cos(math.radians(x)) for x in (al, be, ga))
        g = np.array([[a * a, a * b * cg, a * c * cb],
                      [a * b * cg, b * b, b * c * ca],
                      [a * c * cb, b * c * ca, c * c]])
        gs = np.linalg.inv(g)
        terms = np.array([gs[0, 0], gs[1, 1], gs[2, 2], 2 * gs[0, 1], 2 * gs[0, 2], 2 * gs[1, 2]])
        base = _cell_params(terms)
        scale = float(np.max(np.abs(terms[:3])))
        jac = np.zeros((6, 6))
        for k in range(6):
            h = 1e-6 * scale
            up, down = terms.copy(), terms.copy()
            up[k] += h
            down[k] -= h
            jac[:, k] = (_cell_params(up) - _cell_params(down)) / (2 * h)
    except (ValueError, np.linalg.LinAlgError, FloatingPointError):
        return every
    if not np.all(np.isfinite(jac)):
        return every
    out: dict[str, tuple[int, ...]] = {}
    for i, axis in enumerate(_CELL_AXES):
        # 相対的に効く項だけ (丸め誤差の微小な微分は 0 と見なす)
        row = np.abs(jac[i]) * scale
        threshold = 1e-6 * max(abs(float(base[i])), 1.0)
        idx = tuple(int(k) for k in np.flatnonzero(row > threshold))
        out[axis] = idx or tuple(range(6))
    return out
