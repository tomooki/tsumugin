"""2 つの精密化が**同じ解に収束したか**を判定する (収束安定性の傍証, numpy-only)。

**なぜ Rwp では判定できないか**: T3 実測で `serious` と `adaptive` は Rwp 差 0.361 なのに
格子が 0.161% 違う (PbSO4 a 8.47385 vs 8.48749) — 精密化された esd より桁で大きい。
「同じくらい合っている」と「同じ答えに来た」は別の問いであり、後者を答えるには
**パラメータそのもの**を突き合わせるしかない。

**判定は esd スケール + クラス毎の床**:

- 主判定 ``z = |Δ| / √(σa² + σb²) ≤ k`` (既定 k=3)。
- 床は**クラス毎に別**である。単位が非可換なので単一の相対床は成立しない — とくに
  **座標の床は比ではなく Å 距離**でなければならない (``x=0.0012`` vs ``0.0031`` は相対差
  158% だが変位 0.002 Å = 化学的に同一原子)。

**単一 bool を返さない**。クラス毎の判定と**最悪の犯人**を名指す — 「一致しなかった」だけでは
次に何を見ればよいか判らないため (`RecipeSearchResult.selection_reason` と同じ設計)。

**``UNDETERMINED`` を agreement に畳んではならない**。esd も床も判断材料が無い状態を
「一致」と答えるのは、`check_phase_set` が garbage から ``is_complete=True`` を返すのと
同じ最悪の失敗形である。

**対称等価な座標比較は範囲外**とし、近似せず拒否する (`compare_results` は
`ProcedureProvenance` を必須引数で取り、構造パスや相集合が違えば構造クラスを
``INCOMPARABLE`` にする)。本用途では両者が同じ ``structure_path`` から出発し GSAS が
``dA*`` シフトで動かすだけなので、周期ラップ以外の等価は発生しない。半端な対称処理は
**違う構造を一致と答える**ので、しないほうが安全である。

信頼性: 🔵 esd の 3 状態は `model.CellEsd`/`CoordEsd` の契約、座標 esd の出所は
`atomrows` の GSAS 実ソース確認に依る。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..search.clustering import _UnionFind
from .lattice import direct_metric_from_cell
from .model import AutoRietveldResult

__all__ = [
    "AgreementBasin",
    "AgreementTolerances",
    "ClassAgreement",
    "CorroborationReport",
    "PairAgreement",
    "ParameterAgreement",
    "ProcedureIndependence",
    "INDEPENDENCE_BASES",
    "ProcedureProvenance",
    "cluster_agreement_basins",
    "compare_results",
    "effective_trajectory",
    "is_agreement",
]

#: パラメータクラス。``structure_classes`` の既定はこの前半 3 つ。
CELL, COORD, OCCUPANCY = "cell", "coord", "occupancy"
UISO, PROFILE, WEIGHT_FRACTION = "uiso", "profile", "weight_fraction"
PARAM_CLASSES = (CELL, COORD, OCCUPANCY, UISO, PROFILE, WEIGHT_FRACTION)

#: 判定語彙。``AGREE*`` の 3 つだけが「一致」であり、``UNDETERMINED`` は**一致ではない**。
AGREE = "AGREE"
AGREE_BY_FLOOR = "AGREE_BY_FLOOR"
AGREE_ONE_SIDED_ESD = "AGREE_ONE_SIDED_ESD"
DISAGREE = "DISAGREE"
UNDETERMINED = "UNDETERMINED"
INCOMPARABLE = "INCOMPARABLE"
ASYMMETRIC = "ASYMMETRIC"

#: 深刻な順 (``worst`` の選定に使う)。``is_agreement`` とは**別の問い**なので関数を分ける。
_SEVERITY = {
    DISAGREE: 0,
    UNDETERMINED: 1,
    INCOMPARABLE: 2,
    ASYMMETRIC: 3,
    AGREE_BY_FLOOR: 4,
    AGREE_ONE_SIDED_ESD: 5,
    AGREE: 6,
}

#: 対の判定。
SAME_SOLUTION = "SAME_SOLUTION"
SAME_ON_SHARED_SUBSET = "SAME_ON_SHARED_SUBSET"
DIFFERENT = "DIFFERENT"

#: 独立性の判定。
INDEPENDENT, WEAK, DUPLICATE = "INDEPENDENT", "WEAK", "DUPLICATE"

#: **何がこの 2 つを別の実験にしているか** — 用途で違うので明示する。
#:
#: - ``"procedure"`` (既定): *手順*が違うことが独立性の根拠。同じ道を歩いた 2 案の一致は
#:   情報量ゼロなので、実効軌跡の同一とビット同一を DUPLICATE にする。
#: - ``"start"``: *初期値*が違うことが根拠 (マルチスタート)。全開始点が同じ手順を走るので
#:   軌跡は**構造的に同一**になり、``procedure`` のまま使うと**傍証が永久に成立しない**。
#:   さらに別の初期値からビット同一の解へ来ることは収束の**最強の証拠**であって
#:   「情報量ゼロ」ではない。よってこのモードでは軌跡もビット同一も DUPLICATE にしない。
INDEPENDENCE_BASES = ("procedure", "start")


def is_agreement(verdict: str) -> bool:
    """その判定を「一致」として数えるか。**``UNDETERMINED`` は含まない**。"""
    return verdict in (AGREE, AGREE_BY_FLOOR, AGREE_ONE_SIDED_ESD)


@dataclass(frozen=True)
class AgreementTolerances:
    """一致判定の閾値。

    :param k_esd: esd スケールの許容 (``|Δ|/√(σa²+σb²) ≤ k_esd``)
    :param coord_dist_floor_ang: **Å 距離**の床 (比ではない)。0.02 Å は通常の粉末 Rietveld の
        結合距離精度で、これ以下の差は同じ構造とみなす
    :param structure_classes: ``SAME_SOLUTION`` に一致を要求するクラス。
        ⚠ 既定に ``profile``/``uiso`` を含めないのは意図的 — U/V/W はほぼ平坦な相関谷にあり
        (T1 実測 ``V×W r=−0.959``)、同じ構造・同じ Rwp で谷の別の点に落ちるのが正常である。
        `serious` は Uiso を段階的に解放し `default` は一度に解放するので、Uiso 集合は
        **設計上違う**。ここに足すと問われている問いと無関係な理由で不一致になる
    :param min_procedures: 傍証を主張するのに必要な比較可能な結果の数。
        1 つでは「クラスタが 1 つ」が空虚に成立するため
    """

    k_esd: float = 3.0
    cell_rel_floor: float = 1e-4
    coord_dist_floor_ang: float = 0.02
    occupancy_abs_floor: float = 0.02
    uiso_abs_floor: float = 0.002
    profile_rel_floor: float = 0.05
    fraction_abs_floor: float = 0.01
    structure_classes: tuple[str, ...] = (CELL, COORD, OCCUPANCY)
    min_procedures: int = 3
    min_agreeing: int = 2
    duplicate_veto: bool = True
    weak_jaccard_min: float = 0.25


@dataclass(frozen=True)
class ProcedureProvenance:
    """比較の前提が揃っているかを判断するための出自 (**必須引数**)。

    省略可能にすると呼び出し側が渡さなくなり、「違うモデルどうしを一致と答える」拒否が
    **静かに一度も発火しなくなる**。必須にすることでそれを防ぐ。

    :param structure_paths: 相名 → 入力構造ファイル。違えば構造クラスは比較不能
        (それは*モデル*の比較であって収束の比較ではない → `compare_structure_models`)
    :param trajectory: 実効軌跡 (`effective_trajectory`)。独立性の判定に使う
    """

    label: str
    structure_paths: Mapping[str, str] = field(default_factory=dict)
    trajectory: tuple[tuple[str, int], ...] = ()
    stage_metrics: tuple[tuple[float, float, int], ...] = ()
    n_obs: int = 0
    frozen_parameters: tuple[str, ...] = ()
    # 【末尾追加】: この実行に適用した**初期値摂動** (マルチスタートの開始点キー)。
    #   ``basis="start"`` のときの独立性はこれが違うことで決まる。空 = 無摂動 (基準点)。
    start_key: tuple[object, ...] = ()


@dataclass(frozen=True)
class ParameterAgreement:
    """1 パラメータの突き合わせ結果 (esd の 3 状態を**生のまま**保つ)。"""

    param_class: str
    key: str
    value_a: "float | None"
    value_b: "float | None"
    esd_a: "float | None"
    esd_b: "float | None"
    delta: "float | None"
    z: "float | None"
    metric: "float | None"
    floor: float
    verdict: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "param_class": self.param_class,
            "key": self.key,
            "value_a": finite_or_none(self.value_a) if self.value_a is not None else None,
            "value_b": finite_or_none(self.value_b) if self.value_b is not None else None,
            "esd_a": self.esd_a,
            "esd_b": self.esd_b,
            "delta": finite_or_none(self.delta) if self.delta is not None else None,
            "z": finite_or_none(self.z) if self.z is not None else None,
            "metric": finite_or_none(self.metric) if self.metric is not None else None,
            "floor": self.floor,
            "verdict": self.verdict,
            "note": self.note,
        }


@dataclass(frozen=True)
class ClassAgreement:
    """パラメータクラス 1 つの集計。``worst`` が**最悪の犯人**を名指す。"""

    param_class: str
    verdict: str
    n_compared: int = 0
    n_agree: int = 0
    n_asymmetric: int = 0
    n_undetermined: int = 0
    n_incomparable: int = 0
    worst: "ParameterAgreement | None" = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "param_class": self.param_class,
            "verdict": self.verdict,
            "n_compared": self.n_compared,
            "n_agree": self.n_agree,
            "n_asymmetric": self.n_asymmetric,
            "n_undetermined": self.n_undetermined,
            "n_incomparable": self.n_incomparable,
            "worst": None if self.worst is None else self.worst.to_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ProcedureIndependence:
    """2 手順が**別の経路を通ったか** (一致を証拠にしてよいかの前提)。"""

    verdict: str
    identical_values: bool = False
    identical_trajectory: bool = False
    label_jaccard: float = 1.0
    same_observation_set: bool = True
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "identical_values": self.identical_values,
            "identical_trajectory": self.identical_trajectory,
            "label_jaccard": finite_or_none(self.label_jaccard),
            "same_observation_set": self.same_observation_set,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class PairAgreement:
    """2 手順の突き合わせ結果。"""

    index_a: int
    index_b: int
    label_a: str
    label_b: str
    verdict: str
    classes: tuple[ClassAgreement, ...]
    independence: ProcedureIndependence
    rwp_a: float = float("nan")
    rwp_b: float = float("nan")
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_a": self.index_a,
            "index_b": self.index_b,
            "label_a": self.label_a,
            "label_b": self.label_b,
            "verdict": self.verdict,
            "classes": [c.to_dict() for c in self.classes],
            "independence": self.independence.to_dict(),
            "rwp_a": finite_or_none(self.rwp_a),
            "rwp_b": finite_or_none(self.rwp_b),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AgreementBasin:
    """同じ解へ来た手順の集合。

    :param is_clique: 内部の**全対**が直接一致しているか。union-find は推移閉包を取るので
        「鎖」(a≈b≈c だが a≉c) も 1 ベイスンになる — 鎖は clique より弱い証拠なのでそう言う
    """

    representative_index: int
    member_indices: tuple[int, ...]
    rwp: float
    is_clique: bool
    n_distinct_trajectories: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "representative_index": self.representative_index,
            "member_indices": list(self.member_indices),
            "rwp": finite_or_none(self.rwp),
            "is_clique": self.is_clique,
            "n_distinct_trajectories": self.n_distinct_trajectories,
        }


@dataclass(frozen=True)
class CorroborationReport:
    """N 手順の傍証まとめ。``corroboration_reason`` が**最初に落ちた条件**を名指す。"""

    pairs: tuple[PairAgreement, ...]
    basins: tuple[AgreementBasin, ...]
    n_results: int
    n_comparable: int
    n_diverged: int
    n_distinct_trajectories: int
    n_agreeing_pairs: int
    n_independent_agreeing_pairs: int
    largest_basin_size: int
    is_corroborated: bool
    corroboration_reason: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pairs": [p.to_dict() for p in self.pairs],
            "basins": [b.to_dict() for b in self.basins],
            "n_results": self.n_results,
            "n_comparable": self.n_comparable,
            "n_diverged": self.n_diverged,
            "n_distinct_trajectories": self.n_distinct_trajectories,
            "n_agreeing_pairs": self.n_agreeing_pairs,
            "n_independent_agreeing_pairs": self.n_independent_agreeing_pairs,
            "largest_basin_size": self.largest_basin_size,
            "is_corroborated": self.is_corroborated,
            "corroboration_reason": self.corroboration_reason,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# 原始判定
# ---------------------------------------------------------------------------


def _verdict(
    param_class: str,
    key: str,
    value_a: "float | None",
    value_b: "float | None",
    esd_a: "float | None",
    esd_b: "float | None",
    metric: "float | None",
    floor: float,
    k: float,
) -> ParameterAgreement:
    """1 パラメータの判定 (esd の 3 状態を混同しない)。

    ``metric`` は「どれだけ違うか」の床比較用の量 (座標は Å 距離・格子は相対差・他は絶対差)。
    ``delta`` は esd スケール用の生の差。両者を分けているのは、座標だけ床の単位が違うため。
    """
    def make(v: str, delta: "float | None", z: "float | None", note: str = "") -> ParameterAgreement:
        return ParameterAgreement(
            param_class=param_class, key=key, value_a=value_a, value_b=value_b,
            esd_a=esd_a, esd_b=esd_b, delta=delta, z=z, metric=metric, floor=floor,
            verdict=v, note=note,
        )

    if value_a is None or value_b is None:
        return make(INCOMPARABLE, None, None, "片方に値が無い")
    delta = float(value_a) - float(value_b)
    floor_ok = metric is not None and metric <= floor

    # 【両方 0.0 = 双方とも対称拘束で厳密固定】: 除算しない (0 割りは inf か例外になる)。
    if esd_a == 0.0 and esd_b == 0.0:
        if floor_ok:
            return make(AGREE_BY_FLOOR, delta, None, "双方とも対称拘束で固定")
        return make(INCOMPARABLE, delta, None, "双方固定なのに値が違う (設定/対称性が異なる)")
    # 【片方だけ 0.0】: 一方は厳密固定・他方は可変 = 対称性の仮定が違う。大声で言う。
    if esd_a == 0.0 or esd_b == 0.0:
        return make(INCOMPARABLE, delta, None, "片方だけ対称拘束で固定されている (対称性の仮定が違う)")

    if esd_a is not None and esd_b is not None:
        z = abs(delta) / math.sqrt(esd_a * esd_a + esd_b * esd_b)
        if z <= k:
            return make(AGREE, delta, z)
        return make(AGREE_BY_FLOOR, delta, z) if floor_ok else make(DISAGREE, delta, z)

    present = esd_a if esd_a is not None else esd_b
    if present is not None:
        # 【片側 esd】: 欠落 σ を 0 と仮定する = 二側検定より**厳しい**。安全方向にしか動かない
        #   ので経験的な仮定を置かずに済む (σ を推定して埋めると一致を安売りする)。
        z = abs(delta) / present
        if z <= k:
            return make(AGREE_ONE_SIDED_ESD, delta, z, "σ 欠落を 0 と仮定 (二側検定より厳しい)")
        return make(AGREE_BY_FLOOR, delta, z) if floor_ok else make(DISAGREE, delta, z)

    # 【両方 esd 無し】: 統計的な判定材料が無い。床が通れば一致、通らなければ **UNDETERMINED**
    #   (「違う」でも「同じ」でもない — ここを DISAGREE や AGREE に倒すのが最悪の嘘になる)。
    if floor_ok:
        return make(AGREE_BY_FLOOR, delta, None, "esd 無し (床で一致)")
    return make(UNDETERMINED, delta, None, "esd が両方とも無く、差は床を超えている")


def _class_verdict(items: Sequence[ParameterAgreement], param_class: str) -> ClassAgreement:
    """パラメータ列 → クラス判定。**比較できた部分集合**の上で判断する。

    手順は意図的に別のパラメータ集合を解放するので、片方が触っていないパラメータの一致を
    要求すると**構成上達成不可能**になる。だから ``INCOMPARABLE``/``ASYMMETRIC`` は
    クラス判定を汚さず、件数として別に数える。
    """
    if not items:
        return ClassAgreement(param_class=param_class, verdict=INCOMPARABLE)
    n_agree = sum(1 for it in items if is_agreement(it.verdict))
    n_undet = sum(1 for it in items if it.verdict == UNDETERMINED)
    n_incomp = sum(1 for it in items if it.verdict == INCOMPARABLE)
    n_asym = sum(1 for it in items if it.verdict == ASYMMETRIC)
    n_dis = sum(1 for it in items if it.verdict == DISAGREE)
    worst = min(items, key=lambda it: (_SEVERITY.get(it.verdict, 9), it.key))
    if n_dis:
        verdict = DISAGREE
    elif n_undet:
        verdict = UNDETERMINED
    elif n_agree:
        verdict = AGREE
    else:
        verdict = INCOMPARABLE
    return ClassAgreement(
        param_class=param_class,
        verdict=verdict,
        n_compared=len(items),
        n_agree=n_agree,
        n_asymmetric=n_asym,
        n_undetermined=n_undet,
        n_incomparable=n_incomp,
        worst=worst,
    )


# ---------------------------------------------------------------------------
# クラス別の突き合わせ
# ---------------------------------------------------------------------------


def _wrap(delta: float) -> float:
    """分率座標の周期ラップ ([-0.5, 0.5) へ)。0.999 と 0.001 は**同じサイト**である。"""
    return ((delta + 0.5) % 1.0) - 0.5


def _cell_items(
    a: AutoRietveldResult, b: AutoRietveldResult, tol: AgreementTolerances
) -> list[ParameterAgreement]:
    out: list[ParameterAgreement] = []
    axes = ("a", "b", "c", "alpha", "beta", "gamma")
    for phase in sorted(set(a.refined_cells) & set(b.refined_cells)):
        ca, cb = a.refined_cells[phase], b.refined_cells[phase]
        ea = a.cell_esd.get(phase, (None,) * 6)
        eb = b.cell_esd.get(phase, (None,) * 6)
        for i, axis in enumerate(axes):
            va, vb = float(ca[i]), float(cb[i])
            denom = max(abs(va), abs(vb), 1e-12)
            out.append(
                _verdict(
                    CELL, f"{phase}.{axis}", va, vb,
                    ea[i] if i < len(ea) else None, eb[i] if i < len(eb) else None,
                    abs(va - vb) / denom, tol.cell_rel_floor, tol.k_esd,
                )
            )
    return out


def _coord_items(
    a: AutoRietveldResult, b: AutoRietveldResult, tol: AgreementTolerances
) -> list[ParameterAgreement]:
    """座標。**床は Å 距離**で、周期ラップを掛けてから計量テンソルで実距離に直す。"""
    out: list[ParameterAgreement] = []
    for phase in sorted(set(a.atom_coords) & set(b.atom_coords)):
        pa, pb = a.atom_coords[phase], b.atom_coords[phase]
        ea = a.atom_coord_esd.get(phase, {})
        eb = b.atom_coord_esd.get(phase, {})
        cell_a = a.refined_cells.get(phase)
        cell_b = b.refined_cells.get(phase)
        metric = None
        if cell_a is not None and cell_b is not None:
            mean_cell = tuple((float(x) + float(y)) / 2.0 for x, y in zip(cell_a, cell_b))
            try:
                metric = direct_metric_from_cell(mean_cell)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 — 退化セルは距離を出さない (床は効かない)
                metric = None
        for label in sorted(set(pa) & set(pb)):
            df = np.array([_wrap(float(x) - float(y)) for x, y in zip(pa[label], pb[label])])
            dist = None
            if metric is not None:
                q = float(df @ metric @ df)
                dist = math.sqrt(q) if q > 0.0 else 0.0
            esd_a = ea.get(label, (None, None, None))
            esd_b = eb.get(label, (None, None, None))
            for i, axis in enumerate("xyz"):
                out.append(
                    _verdict(
                        COORD, f"{phase}.{label}.{axis}",
                        float(pa[label][i]), float(pb[label][i]),
                        esd_a[i] if i < len(esd_a) else None,
                        esd_b[i] if i < len(esd_b) else None,
                        # 床は原子単位の距離で判断する (軸ごとに割ると意味を失う)。
                        dist, tol.coord_dist_floor_ang, tol.k_esd,
                    )
                )
    return out


def _mapping_items(
    param_class: str,
    va: Mapping[str, Mapping[str, float]],
    vb: Mapping[str, Mapping[str, float]],
    ea: Mapping[str, Mapping[str, Any]],
    eb: Mapping[str, Mapping[str, Any]],
    floor: float,
    k: float,
) -> list[ParameterAgreement]:
    """相→ラベル→スカラ の共通処理 (占有率 / Uiso)。"""
    out: list[ParameterAgreement] = []
    for phase in sorted(set(va) & set(vb)):
        for label in sorted(set(va[phase]) & set(vb[phase])):
            x, y = float(va[phase][label]), float(vb[phase][label])
            out.append(
                _verdict(
                    param_class, f"{phase}.{label}", x, y,
                    ea.get(phase, {}).get(label), eb.get(phase, {}).get(label),
                    abs(x - y), floor, k,
                )
            )
    return out


def _profile_items(
    a: AutoRietveldResult, b: AutoRietveldResult, tol: AgreementTolerances
) -> list[ParameterAgreement]:
    out: list[ParameterAgreement] = []
    for h, (pa, pb) in enumerate(zip(a.hist_profile, b.hist_profile)):
        ea = a.hist_profile_esd[h] if h < len(a.hist_profile_esd) else {}
        eb = b.hist_profile_esd[h] if h < len(b.hist_profile_esd) else {}
        ra = a.hist_profile_refined[h] if h < len(a.hist_profile_refined) else {}
        rb = b.hist_profile_refined[h] if h < len(b.hist_profile_refined) else {}
        for key in sorted(set(pa) & set(pb)):
            x, y = float(pa[key]), float(pb[key])
            denom = max(abs(x), abs(y), 1e-12)
            item = _verdict(
                PROFILE, f"hist{h}.{key}", x, y, ea.get(key), eb.get(key),
                abs(x - y) / denom, tol.profile_rel_floor, tol.k_esd,
            )
            # 【解放の非対称】: 片方だけが解放した項は「凍結していた」であって
            #   「試したが決まらなかった」ではない。区別できるのは解放フラグがあるからで、
            #   esd の有無だけでは同じに見える。
            if bool(ra.get(key, False)) != bool(rb.get(key, False)) and not is_agreement(
                item.verdict
            ):
                out.append(
                    ParameterAgreement(
                        param_class=item.param_class, key=item.key,
                        value_a=item.value_a, value_b=item.value_b,
                        esd_a=item.esd_a, esd_b=item.esd_b, delta=item.delta, z=item.z,
                        metric=item.metric, floor=item.floor, verdict=ASYMMETRIC,
                        note="片方だけがこの項を解放した (凍結 vs 決まらなかった の区別)",
                    )
                )
                continue
            out.append(item)
    return out


def _fraction_items(
    a: AutoRietveldResult, b: AutoRietveldResult, tol: AgreementTolerances
) -> list[ParameterAgreement]:
    out: list[ParameterAgreement] = []
    for phase in sorted(set(a.phase_weight_fractions) & set(b.phase_weight_fractions)):
        x = float(a.phase_weight_fractions[phase])
        y = float(b.phase_weight_fractions[phase])
        out.append(
            _verdict(
                WEIGHT_FRACTION, f"{phase}.wt", x, y,
                a.phase_weight_fraction_esd.get(phase),
                b.phase_weight_fraction_esd.get(phase),
                abs(x - y), tol.fraction_abs_floor, tol.k_esd,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 独立性
# ---------------------------------------------------------------------------


def effective_trajectory(result: AutoRietveldResult) -> tuple[tuple[str, int], ...]:
    """**実効軌跡** = revert も no-op もされなかった段の ``(ラベル, 母数)`` 列。

    宣言 (レシピ) ではなく**観測** (revert フラグ) で経路を定義するのが要点。「revert される段
    だけが違う 2 案」は宣言上は別物でも実際には同じ道を歩いており、その一致は証拠にならない。
    """
    out: list[tuple[str, int]] = []
    for s in result.stage_results:
        if s.reverted or "noop" in (s.note or ""):
            continue
        out.append((str(s.label), int(s.n_params)))
    return tuple(out)


def _independence(
    a: AutoRietveldResult,
    b: AutoRietveldResult,
    pa: ProcedureProvenance,
    pb: ProcedureProvenance,
    items: Sequence[ParameterAgreement],
    tol: AgreementTolerances,
    basis: str = "procedure",
) -> ProcedureIndependence:
    reasons: list[str] = []
    # (a) ビット同一 — **許容差ではなく ``==``**。30 個超の float が偶然一致することはない。
    same_values = bool(items) and all(
        it.value_a == it.value_b for it in items if it.value_a is not None and it.value_b is not None
    )
    identical_values = (
        same_values and a.final_rwp == b.final_rwp and pa.stage_metrics == pb.stage_metrics
    )
    identical_traj = pa.trajectory == pb.trajectory
    labels_a = {lab for lab, _ in pa.trajectory}
    labels_b = {lab for lab, _ in pb.trajectory}
    union = labels_a | labels_b
    jaccard = len(labels_a & labels_b) / len(union) if union else 1.0
    same_obs = pa.n_obs == pb.n_obs
    if basis == "start":
        # 【初期値が違えば独立】: 軌跡の同一もビット同一も DUPLICATE にしない (定数の docstring)。
        #   独立でないのは「同じ初期値から 2 回走った」場合だけ。
        same_start = pa.start_key == pb.start_key
        if same_start:
            reasons.append("初期値摂動が同一 (同じ開始点から 2 度走ったのと同じ)")
        if identical_values:
            reasons.append(
                "別の初期値からビット同一の解へ収束した (収束の最強の証拠であって重複ではない)"
            )
        return ProcedureIndependence(
            verdict=DUPLICATE if same_start else INDEPENDENT,
            identical_values=identical_values,
            identical_trajectory=identical_traj,
            label_jaccard=jaccard,
            same_observation_set=same_obs,
            reasons=tuple(reasons),
        )
    if identical_values:
        reasons.append("全パラメータと段指標がビット同一 (同じ精密化が 2 度走ったのと同じ)")
    if identical_traj:
        reasons.append("実効軌跡が同一 (revert/no-op を除くと同じ道を歩いている)")
    if identical_values or identical_traj:
        return ProcedureIndependence(
            verdict=DUPLICATE, identical_values=identical_values,
            identical_trajectory=identical_traj, label_jaccard=jaccard,
            same_observation_set=same_obs, reasons=tuple(reasons),
        )
    if (
        jaccard >= 1.0 - tol.weak_jaccard_min
        and same_obs
        and set(pa.frozen_parameters) == set(pb.frozen_parameters)
    ):
        reasons.append("段ラベルがほぼ同一で観測集合も凍結集合も同じ")
        return ProcedureIndependence(
            verdict=WEAK, label_jaccard=jaccard, same_observation_set=same_obs,
            reasons=tuple(reasons),
        )
    if not same_obs:
        # 観測集合が違うのは**独立性を上げる** (別レンジで同じ構造に至る方が強い証拠)。
        reasons.append("観測集合が違う (Rwp は比較不能だがパラメータ一致はより強い証拠)")
    return ProcedureIndependence(
        verdict=INDEPENDENT, label_jaccard=jaccard, same_observation_set=same_obs,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# 対の比較
# ---------------------------------------------------------------------------


def compare_results(
    a: AutoRietveldResult,
    b: AutoRietveldResult,
    provenance_a: ProcedureProvenance,
    provenance_b: ProcedureProvenance,
    *,
    tolerances: "AgreementTolerances | None" = None,
    index_a: int = 0,
    index_b: int = 1,
    basis: str = "procedure",
) -> PairAgreement:
    """2 つの結果が同じ解に収束したかを判定する。

    ``provenance_*`` は**必須**である (docstring 冒頭の理由)。

    :param basis: 独立性の根拠 (`INDEPENDENCE_BASES`)。マルチスタートは ``"start"``
        を渡さないと**傍証が永久に成立しない** (全開始点が同じ手順を走るため)
    """
    if basis not in INDEPENDENCE_BASES:
        raise ValueError(
            f"basis は {list(INDEPENDENCE_BASES)} のいずれか: {basis!r}"
        )
    tol = tolerances or AgreementTolerances()
    warnings: list[str] = []

    shared = set(a.refined_cells) & set(b.refined_cells)
    incomparable_structure = False
    if set(a.refined_cells) != set(b.refined_cells):
        warnings.append(
            f"相集合が違う (A={sorted(a.refined_cells)} / B={sorted(b.refined_cells)}) — "
            "共通相のみ比較する"
        )
    for phase in sorted(shared):
        sa = provenance_a.structure_paths.get(phase)
        sb = provenance_b.structure_paths.get(phase)
        if sa is not None and sb is not None and sa != sb:
            incomparable_structure = True
            warnings.append(
                f"相 {phase!r} の入力構造が違う ({sa} vs {sb}) — これは*モデル*の比較であって "
                "収束の比較ではない (compare_structure_models を使うこと)"
            )

    by_class: dict[str, list[ParameterAgreement]] = {
        CELL: _cell_items(a, b, tol),
        COORD: _coord_items(a, b, tol),
        OCCUPANCY: _mapping_items(
            OCCUPANCY, a.atom_occupancy, b.atom_occupancy,
            a.atom_occupancy_esd, b.atom_occupancy_esd, tol.occupancy_abs_floor, tol.k_esd,
        ),
        UISO: _mapping_items(
            UISO, a.atom_uiso, b.atom_uiso,
            a.atom_uiso_esd, b.atom_uiso_esd, tol.uiso_abs_floor, tol.k_esd,
        ),
        PROFILE: _profile_items(a, b, tol),
        WEIGHT_FRACTION: _fraction_items(a, b, tol),
    }
    classes = tuple(_class_verdict(by_class[c], c) for c in PARAM_CLASSES)
    all_items = [it for c in PARAM_CLASSES for it in by_class[c]]
    independence = _independence(
        a, b, provenance_a, provenance_b, all_items, tol, basis=basis
    )

    if incomparable_structure:
        verdict = INCOMPARABLE
    else:
        # 【クラスが「存在しない」と「比較できなかった」を区別する】: 双方に 1 件も無いクラス
        #   (例: 単相なので相分率が無い / 占有率を持たない構造) は**適用外**であって降格の
        #   理由にならない。データはあるが突き合わせられなかったクラスだけが降格させる。
        required = [
            c
            for c in classes
            if c.param_class in tol.structure_classes and c.n_compared > 0
        ]
        if any(c.verdict == DISAGREE for c in required):
            verdict = DIFFERENT
        elif any(c.verdict == UNDETERMINED for c in required):
            verdict = UNDETERMINED
        elif not any(c.verdict == AGREE for c in required):
            verdict = INCOMPARABLE
        elif any(c.n_asymmetric for c in classes) or any(
            c.verdict == INCOMPARABLE for c in required
        ):
            verdict = SAME_ON_SHARED_SUBSET
        else:
            verdict = SAME_SOLUTION

    if (
        verdict in (SAME_SOLUTION, SAME_ON_SHARED_SUBSET)
        and independence.same_observation_set
        and math.isfinite(a.final_rwp)
        and math.isfinite(b.final_rwp)
        and abs(a.final_rwp - b.final_rwp) > 0.5
    ):
        warnings.append(
            f"パラメータは一致するのに Rwp が {abs(a.final_rwp - b.final_rwp):.3f} 離れている "
            "— 比較していない何か (レンジ/背景項数/拘束) が違う疑い"
        )

    return PairAgreement(
        index_a=index_a, index_b=index_b,
        label_a=provenance_a.label, label_b=provenance_b.label,
        verdict=verdict, classes=classes, independence=independence,
        rwp_a=a.final_rwp, rwp_b=b.final_rwp, warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# クラスタリングと傍証
# ---------------------------------------------------------------------------


def cluster_agreement_basins(
    results: Sequence["AutoRietveldResult | None"],
    provenances: Sequence[ProcedureProvenance],
    *,
    tolerances: "AgreementTolerances | None" = None,
    basis: str = "procedure",
) -> CorroborationReport:
    """N 手順を全対比較し、ベイスンへまとめて傍証を判定する。

    **union-find を使う** — 許容差による「同一」は推移的でないため、貪欲な「先頭一致」
    (旧 `autorietveld.multistart.cluster_rietveld_basins`。本モジュールへ委譲したので削除済)
    だと**列挙順でベイスン数が変わる**。
    探索側が全ての同点を列挙順で解決している決定論規律と矛盾するので、ここでは推移閉包
    (= 一意な最細分割) を取る。ただし閉包は「鎖」を作り得るので `is_clique` を併記する。
    """
    tol = tolerances or AgreementTolerances()
    n = len(results)
    comparable = [
        i for i, r in enumerate(results) if r is not None and math.isfinite(r.final_rwp)
    ]
    n_diverged = sum(
        1 for r in results if r is None or not math.isfinite(r.final_rwp)
    )
    pairs: list[PairAgreement] = []
    uf = _UnionFind(n)
    agreeing: set[tuple[int, int]] = set()
    for ai in range(len(comparable)):
        for bi in range(ai + 1, len(comparable)):
            i, j = comparable[ai], comparable[bi]
            pair = compare_results(
                results[i], results[j], provenances[i], provenances[j],  # type: ignore[arg-type]
                tolerances=tol, index_a=i, index_b=j, basis=basis,
            )
            pairs.append(pair)
            if pair.verdict in (SAME_SOLUTION, SAME_ON_SHARED_SUBSET):
                uf.union(i, j)
                agreeing.add((i, j))

    groups: dict[int, list[int]] = {}
    for i in comparable:
        groups.setdefault(uf.find(i), []).append(i)
    basins: list[AgreementBasin] = []
    for members in sorted(groups.values(), key=lambda m: min(m)):
        members = sorted(members)
        rep = min(members, key=lambda i: (results[i].final_rwp, i))  # type: ignore[union-attr]
        clique = all(
            (x, y) in agreeing
            for k, x in enumerate(members)
            for y in members[k + 1:]
        )
        trajs = {provenances[i].trajectory for i in members}
        basins.append(
            AgreementBasin(
                representative_index=rep,
                member_indices=tuple(members),
                rwp=float(results[rep].final_rwp),  # type: ignore[union-attr]
                is_clique=clique,
                n_distinct_trajectories=len(trajs),
            )
        )

    # 【何本の"別の実験"を走らせたか】: 根拠がモードで違うので数える対象も変える。
    if basis == "start":
        distinct = len({provenances[i].start_key for i in comparable})
    else:
        distinct = len({provenances[i].trajectory for i in comparable})
    independent_agreeing = sum(
        1
        for p in pairs
        if p.verdict in (SAME_SOLUTION, SAME_ON_SHARED_SUBSET)
        and not (tol.duplicate_veto and p.independence.verdict == DUPLICATE)
    )
    largest = max((len(b.member_indices) for b in basins), default=0)

    warnings: list[str] = []
    if distinct < len(comparable):
        what = "初期値" if basis == "start" else "実効経路"
        warnings.append(
            f"{len(comparable)} 件を比較したが{what}は {distinct} 通りしかない "
            f"(重複した{what}どうしの一致は傍証にならない)"
        )
    if n_diverged:
        warnings.append(f"{n_diverged} 手順が発散/未実行のため比較対象外")

    conditions = (
        ("insufficient_procedures", len(comparable) >= tol.min_procedures),
        ("all_trajectories_duplicate", distinct >= 2),
        ("no_independent_agreement", independent_agreeing >= 1),
        ("basin_too_small", largest >= tol.min_agreeing),
    )
    reason = next((name for name, ok in conditions if not ok), "corroborated")
    return CorroborationReport(
        pairs=tuple(pairs),
        basins=tuple(basins),
        n_results=n,
        n_comparable=len(comparable),
        n_diverged=n_diverged,
        n_distinct_trajectories=distinct,
        n_agreeing_pairs=len(agreeing),
        n_independent_agreeing_pairs=independent_agreeing,
        largest_basin_size=largest,
        is_corroborated=all(ok for _, ok in conditions),
        corroboration_reason=reason,
        warnings=tuple(warnings),
    )
