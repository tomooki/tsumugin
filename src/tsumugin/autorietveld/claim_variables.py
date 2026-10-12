"""値のキー → それが依存する GSAS 変数名 (fit-then-judge P1-1A。GSAS 非依存の純写像)。

`claims` は値の出自を**最終の共分散の varyList**で決める (esd の三状態は「未解放・revert・共分散なし」を
区別しないため — proposal §3.1)。そのために値ごとに「どの GSAS 変数が動けばこの値が動くか」が要る。
相 ID・原子行の添字とラベルの対応を知っているのは engine だけなので、engine はここへ相とヒストグラムの
最小情報 (`PhaseVariables`/`HistogramVariables`) を渡し、結果の ``claim_variables`` に載せる。

値のキーは ``"<class>:<比較キー>"`` で、比較キーは `autorietveld.agreement` が開始点の比較に使う
文字列と同じ (収束確認の判定を値ごとに引き当てるため)。GSAS の変数名の形:

| 値 | GSAS 変数 |
|---|---|
| 格子 a..γ | ``<pid>::A0..A5`` (逆格子計量テンソル。どの軸も 6 項のどれかに依存しうるので全部) |
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
from typing import Sequence

__all__ = ["HistogramVariables", "PhaseVariables", "claim_variable_names", "kalpha2_positions"]

_CELL_AXES = ("a", "b", "c", "alpha", "beta", "gamma")
_CELL_TERMS = tuple(f"A{i}" for i in range(6))


@dataclass(frozen=True)
class PhaseVariables:
    """相 1 つの名前・GSAS の相 id・原子ラベル (原子行の並び)。"""

    name: str
    pid: int
    labels: tuple[str, ...]


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
        cell_vars = tuple(f"{ph.pid}::{term}" for term in _CELL_TERMS)
        for axis in _CELL_AXES:
            out[f"cell:{ph.name}.{axis}"] = cell_vars
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
        s2 = ratio * math.sin(math.radians(float(tt) / 2.0))
        if s2 < 1.0:
            out.append(2.0 * math.degrees(math.asin(s2)))
    return tuple(out)
