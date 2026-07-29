"""装置・幾何パラメータの箱拘束 (REQ-SAR-201) と境界到達の検出 (REQ-SAR-202)。

**なぜ「装置・幾何だけ」か (P-SAR-1 / architecture.md D3)**

| 張る | 張らない |
|---|---|
| 格子 (初期値 ±X%)、Shift/DisplaceX,Y、Size/Mustrain の正値性 | 占有率・Uiso・座標 |

構造パラメータ (占有率・Uiso・座標) の逸脱は**モデルが間違っている証拠**であって数値的事故では
ない。NaCuHCF の model5 は Na2/O1 が ``Na>1`` / ``O<0`` に発散したこと自体が「Ow が要る」決め手で、
占有率を [0,1] に箱拘束していれば model5 は「一見まとも」になり model6 と判別できなかった。
よってここに構造パラメータを足してはならない。

**GSAS 側の箱拘束の実体** (`GSASIIstrMain.dropOOBvars`): parmMin/parmMax は最適化中の
制約ではなく「**精密化後に範囲外なら境界へ丸めて凍結**」する事後処理である。したがって

1. 拘束は発散を*防ぐ*のではなく*止める* (1 サイクルは外へ出る)、
2. 境界に到達した変数は ``Controls['parmFrozen']['FrozenList']`` に載る
   → **これが REQ-SAR-202 の検出源**になる (握り潰さずに所見として出せる)。

数値上限を置く場合は**物理的必要値を十分上回る**値にする。低い cap は境界不安定を生み
「偽の "改善せず"」を作る (NaCuHCF: ADP cap を上げたら ND 18.0→14.7%)。

GSAS 依存はゼロ (numpy と標準ライブラリのみ)。engine 側が `set_Controls` へ流し込む。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .._json import finite_or_none

__all__ = [
    "BoundHit",
    "BoxBound",
    "cell_box_bounds",
    "detect_bound_hits",
    "displacement_box_bounds",
    "reciprocal_metric_diagonal",
    "size_strain_box_bounds",
]

#: 試料変位パラメータ (µm)。GSAS の Sample Parameters ``Type`` が**どちらを変数にするか**を決めるので
#: (`engine._apply_sample_geometry`: 反射光学系=Shift / 透過=DisplaceX,Y)、宣言ジオメトリに対応する
#: 側だけに箱を張る。もう一方は varyList に載らず `dropOOBvars` の対象にもならない。
_BRAGG_DISPLACEMENT_KEYS = ("Shift",)
_DEBYE_DISPLACEMENT_KEYS = ("DisplaceX", "DisplaceY")

#: 等方サイズ/微小歪みの GSAS 変数サフィックス。異方 (uniaxial ``;a`` / generalized ``;0``..) は
#: **符号が物理的に自由**な成分を含むため正値性拘束の対象にしない (誤って正に縛ると異方性が消える)。
_ISO_SIZE_KEY = "Size;i"
_ISO_MUSTRAIN_KEY = "Mustrain;i"


@dataclass(frozen=True)
class BoxBound:
    """1 変数に張る箱拘束 (GSAS ``parmMin``/``parmMax`` 1 組)。

    :param variable: GSAS 変数名 (例 ``0::A0`` / ``:0:Shift`` / ``0:0:Size;i``)
    :param lo: 下限 (None なら下限なし)
    :param hi: 上限 (None なら上限なし)
    :param kind: 分類 (``cell`` / ``displacement`` / ``size`` / ``mustrain``)。所見の読み手向け
    :param reason: なぜこの箱なのか (ledger にそのまま載る)
    """

    variable: str
    lo: "float | None"
    hi: "float | None"
    kind: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "lo": finite_or_none(self.lo) if self.lo is not None else None,
            "hi": finite_or_none(self.hi) if self.hi is not None else None,
            "kind": self.kind,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BoundHit:
    """箱の境界に到達した変数 (REQ-SAR-202 の所見)。

    GSAS は境界外へ出た変数を**境界値へ丸めて凍結**する。凍結は結果に現れないので (Rwp にも
    ``reverted`` にも出ない)、ここで明示的に拾って所見にする。**握り潰さない**のが要点:
    境界に当たったということは「そのパラメータは箱の外を欲しがっている」= 箱が間違っているか
    モデルが間違っているかのどちらかで、どちらも人間が知るべき事実である。

    :param side: ``"min"`` / ``"max"`` / ``"unknown"`` (どちら側かが判らない場合)
    """

    variable: str
    side: str
    lo: "float | None"
    hi: "float | None"
    kind: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "side": self.side,
            "lo": finite_or_none(self.lo) if self.lo is not None else None,
            "hi": finite_or_none(self.hi) if self.hi is not None else None,
            "kind": self.kind,
            "reason": self.reason,
        }


def reciprocal_metric_diagonal(
    cell: Sequence[float],
) -> "tuple[float, float, float] | None":
    """格子定数 (a,b,c,α,β,γ) → 逆格子計量テンソルの対角成分 ``(a*², b*², c*²)``。

    GSAS が精密化するのは a,b,c ではなく **逆格子計量テンソル成分 ``A0..A5``**
    (``[G*11, G*22, G*33, 2·G*12, 2·G*13, 2·G*23]``, `GSASIIlattice.cell2A`) である。
    対角の 3 成分 ``A0,A1,A2`` は任意の晶系で ``a*², b*², c*²`` = **常に正**なので箱を張れる。
    非対角 ``A3,A4,A5`` は角度由来で**符号が自由** (90° で 0 を跨ぐ) ため相対的な箱に意味がなく、
    対象にしない。

    退化した格子 (非正定値な計量テンソル) は ``None`` を返す (箱を張らない = fail open;
    そもそも格子が壊れている状態を拘束の前提にしない)。
    """
    if len(cell) < 6:
        return None
    try:
        a, b, c = (float(cell[0]), float(cell[1]), float(cell[2]))
        alpha, beta, gamma = (
            math.radians(float(cell[3])),
            math.radians(float(cell[4])),
            math.radians(float(cell[5])),
        )
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v > 0.0 for v in (a, b, c)):
        return None
    ca, cb, cg = math.cos(alpha), math.cos(beta), math.cos(gamma)
    g = np.array(
        [
            [a * a, a * b * cg, a * c * cb],
            [a * b * cg, b * b, b * c * ca],
            [a * c * cb, b * c * ca, c * c],
        ],
        dtype=float,
    )
    try:
        gstar = np.linalg.inv(g)
    except np.linalg.LinAlgError:
        return None
    diag = (float(gstar[0, 0]), float(gstar[1, 1]), float(gstar[2, 2]))
    if not all(math.isfinite(v) and v > 0.0 for v in diag):
        return None
    return diag


def cell_box_bounds(
    phase_id: int, cell: Sequence[float], fraction: float
) -> "tuple[BoxBound, ...]":
    """格子を「初期値の ±fraction」に閉じ込める箱を作る (REQ-SAR-201)。

    軸長が ``[1-f, 1+f]`` 倍の範囲に収まる ⇔ 逆格子成分 ``A_ii = a*²`` が
    ``[A_ii/(1+f)², A_ii/(1-f)²]`` に収まる (``a* ∝ 1/a``)。直交系では厳密、非直交系では
    ``a*`` が他軸/角度にも依存するため近似だが、**発散ガードとしてはこれで十分**である
    (目的は「格子が桁で飛ぶ・0 へ潰れる」を止めることであって精密な事前分布ではない)。

    :param fraction: 相対許容幅 (例 0.05 = ±5%)。``0 < fraction < 1`` でなければ空を返す
        (箱を張らない = 現行動作。不正な設定で黙って全格子を固定しない)
    """
    if not (math.isfinite(fraction) and 0.0 < fraction < 1.0):
        return ()
    diag = reciprocal_metric_diagonal(cell)
    if diag is None:
        return ()
    lo_scale = 1.0 / (1.0 + fraction) ** 2
    hi_scale = 1.0 / (1.0 - fraction) ** 2
    pct = fraction * 100.0
    return tuple(
        BoxBound(
            variable=f"{phase_id}::A{i}",
            lo=value * lo_scale,
            hi=value * hi_scale,
            kind="cell",
            reason=f"格子の初期値 ±{pct:g}% (逆格子成分 A{i} = {'abc'[i]}*²)",
        )
        for i, value in enumerate(diag)
    )


def displacement_box_bounds(
    hist_index: int, limit_um: float, *, bragg_brentano: bool
) -> "tuple[BoxBound, ...]":
    """試料変位 (µm) に対称な箱 ``±limit_um`` を張る (REQ-SAR-201)。

    変位は格子と強く相関する (CaTeO3 実測: Shift −274 µm + Zero −0.137° = 2θ ~0.29° のズレを
    格子が肩代わりしていた)。相関が強い方向へ暴走すると**格子が変位を吸収した自己整合な誤解**が
    でき、Rwp には現れない。物理的には試料面の設置誤差なので mm オーダーを超える値は装置的に
    あり得ない = **数値的事故であって情報ではない**。

    :param bragg_brentano: 反射光学系なら ``Shift``、透過なら ``DisplaceX``/``DisplaceY``。
        GSAS は Sample Parameters ``Type`` で**どちらを変数にするか**を決めるため、宣言
        ジオメトリに合わせる (`engine._apply_sample_geometry` と同じ根拠)
    """
    if not (math.isfinite(limit_um) and limit_um > 0.0):
        return ()
    keys = _BRAGG_DISPLACEMENT_KEYS if bragg_brentano else _DEBYE_DISPLACEMENT_KEYS
    return tuple(
        BoxBound(
            variable=f":{hist_index}:{key}",
            lo=-limit_um,
            hi=limit_um,
            kind="displacement",
            reason=f"試料変位 |{key}| ≤ {limit_um:g} µm (装置的に到達し得ない値を除外)",
        )
        for key in keys
    )


def size_strain_box_bounds(
    phase_id: int,
    hist_index: int,
    *,
    min_size: float,
    max_size: float,
    min_mustrain: float,
    max_mustrain: float,
) -> "tuple[BoxBound, ...]":
    """等方 Size/Mustrain の**正値性**と、十分緩い上限を箱にする (REQ-SAR-201)。

    ``Size;i`` は ``Sgam = 1.8λ/(π·Size;i·cosθ)`` のように**分母**に入る (`GSASIIstrMath`)。
    0 へ向かうと幅が発散し、負へ抜けると幅が負になる — どちらも物理でなく数値的事故なので
    下限を張る。上限は「大きい結晶 = 装置分解能に埋もれる」領域で目的関数がほぼ平坦になり、
    esd が発散したまま無限へ漂うのを止めるためのもの。

    **上限は物理的必要値を桁で上回る値にすること** (既定は engine 側)。低い cap は境界不安定を
    生み「偽の "改善せず"」を作る (NaCuHCF: ADP cap を上げたら ND 18.0→14.7%)。

    異方 (uniaxial ``;a`` / generalized ``;0``..``;N``) 成分は**符号が物理的に自由**なので
    対象にしない — 正に縛ると異方性そのものを消してしまう。
    """
    out: list[BoxBound] = []
    prefix = f"{phase_id}:{hist_index}:"
    if math.isfinite(min_size) and math.isfinite(max_size) and 0.0 < min_size < max_size:
        out.append(
            BoxBound(
                variable=prefix + _ISO_SIZE_KEY,
                lo=min_size,
                hi=max_size,
                kind="size",
                reason=(
                    f"等方サイズは正 ({min_size:g} µm 以上; 幅の式で分母に入り 0/負は発散) "
                    f"かつ {max_size:g} µm 以下 (分解能限界より上は平坦で決まらない)"
                ),
            )
        )
    if (
        math.isfinite(min_mustrain)
        and math.isfinite(max_mustrain)
        and 0.0 < min_mustrain < max_mustrain
    ):
        out.append(
            BoxBound(
                variable=prefix + _ISO_MUSTRAIN_KEY,
                lo=min_mustrain,
                hi=max_mustrain,
                kind="mustrain",
                reason=(
                    f"等方微小歪みは正 ({min_mustrain:g} ×10⁻⁶ 以上) かつ "
                    f"{max_mustrain:g} ×10⁻⁶ 以下 (物理的必要値を桁で上回る緩い上限)"
                ),
            )
        )
    return tuple(out)


def _hit_side(bound: BoxBound, value: "float | None") -> str:
    """どちら側の境界に当たったか。判らなければ ``"unknown"`` (推測で断定しない)。

    ``value`` は **丸められる前**の精密化値 (covData の ``variables``)。`dropOOBvars` は
    covData を書いた**後**に値を境界へ丸めるため、共分散に残る値は箱の外側にあり、
    どちら側かを一意に決められる。値が無い場合は片側だけの箱ならその側、両側なら不明とする。
    """
    if value is not None and math.isfinite(value):
        if bound.lo is not None and value < bound.lo:
            return "min"
        if bound.hi is not None and value > bound.hi:
            return "max"
    if bound.lo is not None and bound.hi is None:
        return "min"
    if bound.hi is not None and bound.lo is None:
        return "max"
    return "unknown"


def detect_bound_hits(
    bounds: "Iterable[BoxBound]",
    frozen_before: "Iterable[str]",
    frozen_after: "Iterable[str]",
    values: "Mapping[str, float] | None" = None,
) -> "tuple[BoundHit, ...]":
    """精密化の前後で**新たに凍結された箱付き変数**を境界到達として拾う (REQ-SAR-202)。

    `GSASIIstrMain.dropOOBvars` は「範囲外→境界へ丸めて ``parmFrozen`` に追加」なので、
    **箱を張った変数が新たに凍結された = 境界に到達した**である。同じ ``parmFrozen`` には
    esd プルーニング (REQ-SAR-103) も書き込むため、**箱を張った変数だけに絞る**ことで
    取り違えを避ける (前後差を取る窓は精密化呼び出しの前後に限る — engine 側の責務)。

    :param values: 変数名→**丸められる前**の精密化値 (任意)。あれば境界の側を確定できる。
    :returns: 変数名昇順の所見 (決定論, NFR-102)
    """
    by_name = {b.variable: b for b in bounds}
    before = set(frozen_before)
    newly = [n for n in dict.fromkeys(frozen_after) if n not in before and n in by_name]
    vals = values or {}
    out: list[BoundHit] = []
    for name in sorted(newly):
        b = by_name[name]
        raw = vals.get(name)
        side = _hit_side(b, float(raw) if isinstance(raw, (int, float)) else None)
        out.append(
            BoundHit(
                variable=name, side=side, lo=b.lo, hi=b.hi, kind=b.kind, reason=b.reason
            )
        )
    return tuple(out)
