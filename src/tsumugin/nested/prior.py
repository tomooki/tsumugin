"""restraint からの nested 事前分布自動構成。REQ-008/301/FR-125/NFR-102。

精密化 restraint (格子シフト上限・占有率拘束等) の宣言 ``RestraintSpec`` から、各 free_param の
``PriorSpec`` を自動構成する。restraint 未指定のパラメータには param 種別ごとの既定区間を割り当て、
``overrides`` で手動上書きを受理する (REQ-301)。返す tuple は param_name 昇順で決定論化し、nested の
次元順を固定する (NFR-102/REQ-402)。

パラメータ種別は既存 free_params 命名 (``phase{i}.{key}`` / ``global.{key}``) の末尾キーで判定する
(``backends.base.parse_param`` と整合)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..backends.base import parse_param
from .base import PriorSpec

# 種別既定の区間パラメータ
_LATTICE_REL_MARGIN = 0.05  # 格子は中心 ±5% の uniform (中心不明時は代表値 5.0 を採用)
_LATTICE_DEFAULT_CENTER = 5.0  # 格子長の代表既定 (Å) — restraint 無指定時のプレースホルダ
_SCALE_DEFAULT_HIGH = 1.0e6  # scale は [0, 大] の有限既定 (∞ を有限化)


def _key_suffix(param_name: str) -> str:
    """param_name の末尾キー (種別判定用) を返す。

    ``phase{i}.{key}`` / ``global.{key}`` を ``parse_param`` で解いて {key} の末尾セグメントを取る。
    命名規約に合致しない名前は末尾ドットセグメントへ素直に縮退する (妥当な既定判定のため)。
    """
    try:
        _, key = parse_param(param_name)
    except ValueError:
        key = param_name
    return key.rsplit(".", 1)[-1].lower()


def _default_prior(param_name: str) -> PriorSpec:
    """restraint 未指定パラメータの種別既定 PriorSpec を構成する。REQ-008。

    - occ / occupancy: 占有率 [0,1] uniform。
    - lattice: 中心 ±数% uniform (中心不明時は代表値 ±%)。
    - scale: [0, 大] の有限 uniform。
    - その他: 妥当な既定 [0,1] uniform。
    """
    suffix = _key_suffix(param_name)
    if suffix in ("occ", "occupancy"):
        return PriorSpec(param_name=param_name, kind="uniform", low=0.0, high=1.0)
    if suffix in ("a", "b", "c") or "lattice" in param_name.lower():
        margin = _LATTICE_DEFAULT_CENTER * _LATTICE_REL_MARGIN
        return PriorSpec(
            param_name=param_name,
            kind="uniform",
            low=_LATTICE_DEFAULT_CENTER - margin,
            high=_LATTICE_DEFAULT_CENTER + margin,
        )
    if suffix == "scale":
        return PriorSpec(param_name=param_name, kind="uniform", low=0.0, high=_SCALE_DEFAULT_HIGH)
    # 妥当な既定 (無次元量を想定した [0,1] uniform)
    return PriorSpec(param_name=param_name, kind="uniform", low=0.0, high=1.0)


def _prior_from_restraint(param_name: str, restraint: "RestraintSpec") -> PriorSpec:
    """1 restraint から PriorSpec を構成する。REQ-008。

    - lower/upper 両方指定 → uniform[lower, upper]。
    - center/sigma 指定 → truncated_normal (切断区間は種別既定 or 指定 lower/upper)。
    - 不完全指定 → 種別既定へ縮退しつつ指定境界を尊重する。
    """
    default = _default_prior(param_name)

    if restraint.lower is not None and restraint.upper is not None:
        return PriorSpec(
            param_name=param_name,
            kind="uniform",
            low=restraint.lower,
            high=restraint.upper,
        )

    if restraint.center is not None and restraint.sigma is not None and restraint.sigma > 0.0:
        # 【sigma>0 要求 (数値堅牢化)】: sigma<=0 は truncated_normal の逆 CDF で ZeroDivisionError
        #   (sigma=0) や単調減少 (sigma<0) を招くため、truncated_normal を作らず種別既定 (uniform)
        #   へ縮退する (指定境界は下の不完全指定分岐で尊重される)。決定論維持。
        # 切断区間は指定 lower/upper があれば優先、無ければ種別既定区間を用いる
        low = restraint.lower if restraint.lower is not None else default.low
        high = restraint.upper if restraint.upper is not None else default.high
        return PriorSpec(
            param_name=param_name,
            kind="truncated_normal",
            low=low,
            high=high,
            loc=restraint.center,
            scale=restraint.sigma,
        )

    # 不完全指定: 種別既定へ縮退しつつ指定された境界のみ尊重する
    low = restraint.lower if restraint.lower is not None else default.low
    high = restraint.upper if restraint.upper is not None else default.high
    return PriorSpec(param_name=param_name, kind="uniform", low=low, high=high)


@dataclass(frozen=True)
class RestraintSpec:
    """精密化 restraint (格子シフト上限・占有率拘束等) の宣言。REQ-008/FR-125。

    nested の事前分布自動構成 (``build_prior_from_restraints``) の入力。既存 free_params 命名
    (``phase{i}.{key}`` / ``global.{key}``) と整合させる。
    """

    param_name: str  # 【対象パラメータ名】
    lower: float | None = None  # 【下限 (None は既定推定)】
    upper: float | None = None  # 【上限 (None は既定推定)】
    center: float | None = None  # 【中心値 (normal restraint 用)】
    sigma: float | None = None  # 【拘束幅 (normal restraint 用)】


def build_prior_from_restraints(
    free_params: frozenset[str],
    restraints: Sequence[RestraintSpec] = (),
    *,
    overrides: Mapping[str, PriorSpec] | None = None,
) -> tuple[PriorSpec, ...]:
    """精密化 restraint から nested 事前分布を自動構成する (手動上書き可)。REQ-008/301/FR-125。

    【自動構成】: 各 free_param に対し restraints から区間/中心を引き uniform/truncated_normal を
      構成する。restraint 未指定のパラメータは種別ごとの既定区間 (格子=±数%, 占有率=[0,1], scale=
      [0,大] 等) を割り当てる。
    【手動上書き (REQ-301)】: ``overrides`` に param_name→PriorSpec があれば自動構成を置換する。
    【決定論 (NFR-102/REQ-402)】: 返す tuple は param_name 昇順で固定し nested の次元順を決定論化する。
      同一入力で 2 回ビット同一。
    """
    overrides = overrides or {}
    # param_name → 最初に一致した restraint (決定論のため入力順で最初のものを採用)
    restraint_by_name: dict[str, RestraintSpec] = {}
    for r in restraints:
        restraint_by_name.setdefault(r.param_name, r)

    priors: list[PriorSpec] = []
    for name in sorted(free_params):
        if name in overrides:
            priors.append(overrides[name])
            continue
        restraint = restraint_by_name.get(name)
        if restraint is not None:
            priors.append(_prior_from_restraint(name, restraint))
        else:
            priors.append(_default_prior(name))
    return tuple(priors)
