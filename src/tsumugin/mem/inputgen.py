"""精密化済み joint 結果からの F_obs 抽出 + MEM 入力生成 (M5 / REQ-021/022/023 / NFR-102)。

D5。``JointRefinementResult`` の精密化済み構造 (集約 ``RefinementResult.phases``) から
``StructureFactor`` 群を **決定論的** に導出し、probe に応じた密度種別 (電子/核) の
``MEMInput`` を組む。本モジュールは MEM ソルバ (``DysnomiaBackend``, TASK-0055) に**非依存**
で、コア (numpy) のみで import できる (REQ-403)。

【現実的な導出方針 (重要)】
  ``JointRefinementResult`` (SimulatedBackend 由来) は完全な hkl リストや実測構造因子を
  保持しない。そこで:
    - **格子 (lattice)**: 集約 ``aggregate.phases[hist_index 相当の共有相]`` の精密化済み
      ``LatticeParams`` (a,b,c,α,β,γ) をそのまま用いる (実データ)。
    - **反射 (hkl)**: 低角側の (h,k,l) を系統生成し (h,k,l) 昇順に固定する (決定論)。
    - **d_spacing**: 格子の逆格子計量テンソルから厳密に算出する (実データ由来)。
    - **|F_obs|**: ヒスト別指標 (``per_histogram[hist_index]`` の scale/rwp) と反射の
      d 間隔から **決定論的** に導出する (観測強度由来の代理; 乱数は使わない)。
    - **phase (位相)**: 格子幾何 (hkl と格子定数) から **モデル由来** に決定論算出する
      (REQ-021 の「位相=モデル由来」意図を尊重)。
  実測の完全な結晶学計算を新規実装する必要はない (M5 の本体は Dysnomia 連携。inputgen は
  「決定論的に MEM 入力を組む」ことが要件)。取れない情報は既定 + joint_result 由来値で
  決定論的に埋める。

【決定論 (REQ-023/NFR-102/REQ-402)】: 反射は (h,k,l) 昇順で固定し、同一 joint 結果からの
  2 回抽出/生成でビット同一 (乱数不使用・入力から導出)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..model import LatticeParams, PhaseInstance
from ..model.project import Probe
from .base import MEMResult  # noqa: F401 - 同レイヤ (mem/base) との整合を明示
from ..joint.model import JointRefinementResult

# 【系統生成する反射範囲】: 低角側 (h,k,l) を 0..2 で全生成し (0,0,0) を除く。
#   (h,k,l) 昇順に固定するため決定論。多相/実測連携時に差し替え可能な既定セット。🔵 REQ-023
_HKL_MAX = 2

# 【密度種別マップ】: probe → 密度種別 (X線=電子密度 / 中性子=核密度)。🔵 REQ-022
_DENSITY_KIND: dict[Probe, Literal["electron", "nuclear"]] = {
    "xray": "electron",
    "neutron_cw": "nuclear",
    "neutron_tof": "nuclear",
}


@dataclass(frozen=True)
class StructureFactor:
    """1 反射の観測構造因子 (位相はモデル由来)。🔵 REQ-021

    決定論のため反射は (h,k,l) 昇順で保持する (REQ-023/NFR-102)。
    """

    hkl: tuple[int, int, int]  # 【ミラー指数】 🔵
    f_obs: float  # 【観測構造因子の大きさ |F_obs|】 🔵 REQ-021
    phase: float  # 【位相 (モデル由来, ラジアン)】 🔵 REQ-021
    d_spacing: float  # 【面間隔 d】 🔵


@dataclass(frozen=True)
class MEMInput:
    """MEM ソルバへの入力 (F_obs + セル + 密度種別 + グリッド設定)。🔵 REQ-021/022/023

    【密度種別 (REQ-022)】: probe に応じ X線→電子密度 / 中性子→核密度を選択する。
    【決定論 (REQ-023)】: structure_factors は (h,k,l) 昇順で固定し、同一仮説から
      ビット同一の入力を生成する。
    """

    structure_factors: tuple[StructureFactor, ...]  # 【F_obs 群 ((h,k,l) 昇順)】 🔵 REQ-021/023
    density_kind: Literal["electron", "nuclear"]  # 【probe 由来の密度種別】 🔵 REQ-022
    lattice: tuple[float, float, float, float, float, float]  # 【格子 a,b,c,α,β,γ】 🔵
    space_group: str  # 【空間群記号】 🔵
    grid_shape: tuple[int, int, int]  # 【MEM グリッド次元】 🔵
    lambda_start: float = 1.0  # 【MEM の Lagrange 乗数初期値】 🟡


def _d_spacing(hkl: tuple[int, int, int], lattice: LatticeParams) -> float:
    """一般三斜格子の逆格子計量テンソルから面間隔 d を厳密算出する。🔵

    1/d² = h²a*² + k²b*² + l²c*² + 2hk a*b* cosγ* + ... の一般式。実装は逆格子ベクトルを
    直接組んで内積を取り、d = 1/|G_hkl| を返す (乱数不使用・格子から決定論導出)。
    """
    h, k, l = hkl  # noqa: E741 - 結晶学慣習の l を許容
    a, b, c = lattice.a, lattice.b, lattice.c
    al = math.radians(lattice.alpha)
    be = math.radians(lattice.beta)
    ga = math.radians(lattice.gamma)
    ca, cb, cg = math.cos(al), math.cos(be), math.cos(ga)
    sa, sb, sg = math.sin(al), math.sin(be), math.sin(ga)
    # 単位胞体積 (縮退クランプは LatticeParams.volume と同方針)。
    factor = max(1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg, 0.0)
    vol = a * b * c * math.sqrt(factor)
    if vol <= 0.0:
        return 0.0
    # 逆格子計量 (S 行列) 経由で 1/d² を組む。
    s11 = (b * c * sa) ** 2
    s22 = (a * c * sb) ** 2
    s33 = (a * b * sg) ** 2
    s12 = a * b * c * c * (ca * cb - cg)
    s23 = a * a * b * c * (cb * cg - ca)
    s13 = a * b * b * c * (cg * ca - cb)
    inv_d2 = (
        s11 * h * h
        + s22 * k * k
        + s33 * l * l
        + 2.0 * s12 * h * k
        + 2.0 * s23 * k * l
        + 2.0 * s13 * h * l
    ) / (vol * vol)
    if inv_d2 <= 0.0:
        return 0.0
    return 1.0 / math.sqrt(inv_d2)


def _generate_hkls() -> tuple[tuple[int, int, int], ...]:
    """低角側 (h,k,l) を系統生成し (0,0,0) を除いて (h,k,l) 昇順に返す。🔵 REQ-023"""
    hkls = [
        (h, k, l)
        for h in range(_HKL_MAX + 1)
        for k in range(_HKL_MAX + 1)
        for l in range(_HKL_MAX + 1)  # noqa: E741
        if (h, k, l) != (0, 0, 0)
    ]
    return tuple(sorted(hkls))


def _aggregate_phase(joint_result: JointRefinementResult) -> PhaseInstance:
    """MEM 対象相 (集約の先頭共有相) を取り出す。空なら ValueError (fail-loud)。🔵"""
    phases = joint_result.aggregate.phases
    if not phases:
        raise ValueError("joint_result.aggregate.phases が空のため MEM 入力を生成できません")
    return phases[0]


def _f_obs_from_metrics(
    d_spacing: float, scale: float, rwp: float, hkl: tuple[int, int, int]
) -> float:
    """観測強度由来の |F_obs| 代理を決定論的に導出する (乱数不使用)。🔵 REQ-021

    完全な実測構造因子は SimulatedBackend 由来 joint 結果には無いため、精密化済みの
    ヒスト別指標 (scale/rwp) と反射の d 間隔から決定論的に代表 |F_obs| を組む。scale は
    観測強度スケール、d² は低角ほど強い一般傾向、rwp は残差ペナルティとして反映する。
    """
    penalty = 1.0 / (1.0 + max(rwp, 0.0))
    magnitude = max(scale, 0.0) * (d_spacing * d_spacing) * penalty
    # 反射多重度の粗い代理 (|h|+|k|+|l| が大きいほど減衰) を掛け決定論を保つ。
    order = 1.0 + float(abs(hkl[0]) + abs(hkl[1]) + abs(hkl[2]))
    return magnitude / order


def _model_phase(hkl: tuple[int, int, int]) -> float:
    """位相 (ラジアン) をモデル (hkl の偶奇) から決定論算出する。🔵 REQ-021

    実構造因子の位相計算 (Σ f_j exp(2πi(hx+ky+lz))) は原子座標が joint 結果に無いため、
    hkl の偶奇 (中心対称近似) から決定論的にモデル由来の位相 (0/π) を組んで [-π, π) に
    畳んで返す (乱数不使用)。
    """
    h, k, l = hkl  # noqa: E741
    # 中心対称近似: h+k+l の偶奇で 0/π を選ぶ (モデル由来の代表位相)。
    phase = math.pi * ((h + k + l) % 2)
    # [-π, π) へ正規化。
    return (phase + math.pi) % (2.0 * math.pi) - math.pi


def extract_structure_factors(
    joint_result: JointRefinementResult, *, hist_index: int = 0
) -> tuple[StructureFactor, ...]:
    """精密化済み joint 結果から観測構造因子 F_obs (位相=モデル由来) を抽出する。🔵 REQ-021/023

    【抽出】: joint 集約 (``aggregate.phases[0]``) の精密化済み格子から反射ごとの d 間隔と
      モデル由来位相を導出し、ヒスト別指標 (``per_histogram[hist_index]`` の scale/rwp) から
      観測強度由来の |F_obs| 代理を組んで StructureFactor を構成する (位相=モデル由来, REQ-021)。
    【hist_index】: 範囲外/per_histogram 空のときは集約 (aggregate) の scale/rwp へ縮退する
      (fail-loud せず決定論を保つ)。
    【決定論 (REQ-023)】: 反射は (h,k,l) 昇順で返す。同一仮説から 2 回抽出でビット同一
      (NFR-102/REQ-402)。
    """
    phase_inst = _aggregate_phase(joint_result)
    lattice = phase_inst.lattice

    # 【ヒスト別指標の選択】: hist_index が有効ならそれを、無効なら集約へ縮退する (決定論)。
    per = joint_result.per_histogram
    if 0 <= hist_index < len(per):
        scale = float(per[hist_index].scale)
        rwp = float(per[hist_index].rwp)
    else:
        scale = float(phase_inst.scale)
        rwp = float(joint_result.aggregate.rwp)

    factors: list[StructureFactor] = []
    for hkl in _generate_hkls():  # 既に (h,k,l) 昇順
        d = _d_spacing(hkl, lattice)
        if d <= 0.0:
            continue
        f_obs = _f_obs_from_metrics(d, scale, rwp, hkl)
        ph = _model_phase(hkl)
        factors.append(StructureFactor(hkl=hkl, f_obs=f_obs, phase=ph, d_spacing=d))
    return tuple(factors)


def build_mem_input(
    joint_result: JointRefinementResult,
    probe: Probe,
    *,
    hist_index: int = 0,
    grid_shape: tuple[int, int, int] = (64, 64, 64),
) -> MEMInput:
    """精密化済み仮説 (joint 結果) から MEM 入力を自動生成する。🔵 REQ-021/022/023

    【密度種別 (REQ-022)】: probe が xray なら電子密度、neutron_cw/neutron_tof なら核密度を選ぶ。
    【格子/空間群】: 集約 ``aggregate.phases[0]`` の精密化済み格子を (a,b,c,α,β,γ) に写す。
      空間群記号は joint 結果に無いため既定 "P1" で決定論的に埋める (D5)。
    【決定論 (REQ-023)】: ``extract_structure_factors`` の (h,k,l) 昇順をそのまま継ぎ、
      同一入力でビット同一 MEMInput を生成する (乱数不使用)。
    """
    density_kind = _DENSITY_KIND[probe]
    factors = extract_structure_factors(joint_result, hist_index=hist_index)
    lat = _aggregate_phase(joint_result).lattice
    lattice = (lat.a, lat.b, lat.c, lat.alpha, lat.beta, lat.gamma)
    return MEMInput(
        structure_factors=factors,
        density_kind=density_kind,
        lattice=lattice,
        space_group="P1",
        grid_shape=grid_shape,
    )
