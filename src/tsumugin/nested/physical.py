"""区間 joint 物理 EvidenceProblem 構築 (Issue #76 / FR-122×FR-125×FR-313)。

v1 の定数尤度サロゲート (``operando.discrimination._build_evidence_problem``) は θ 非依存の
logL=-Σbic/2 を運ぶだけで、nested/Laplace を回しても bic 一次と同じ情報しか持たず僅差を
数学的に解消できなかった。本モジュールは**実際に θ で動く物理尤度**を持つ EvidenceProblem を
精密化状態から構築する。

設計 (docs/design/nested-physical-likelihood/architecture.md §2):

- 区間の各フレームは条件付き独立 (仮説間でフレームをまたぐパラメータ共有が無い) ため、区間
  evidence は厳密に ``logZ_interval = Σ_i logZ_i`` に分解する。これを 1 個の **joint problem**
  (θ = フレーム別解放パラメータの連結) で表現し、``arbitrate``/``run_with_fallback`` の単一
  problem 契約と PR #75 三重ガードを不変に保つ。
- 次元名は ``frame{i:04d}.{param}`` で lexicographic 昇順 = フレーム major の決定論順
  (``EvidenceProblem.priors`` 昇順契約, NFR-102)。
- ``logL(θ) = Σ_i -χ²_i(θ_i)/2``。χ²_i は backend の**公開契約** ``refine(free_params=∅)``
  (LM ループに入らず初期状態の chi2 を返す純評価) で得る。backend 失敗 (chi2 非有限) は
  例外化せず logL=-inf (zero probability) へ写す。
- ``map_point`` は精密化済み相から読んだ現在値、``hessian`` は各フレーム ``Curvature``
  (JᵀJ = −logL の Gauss-Newton Hessian) のブロック対角。ブロック対角の ln|H| は Σ ln|H_i|
  なので joint Laplace = Σ per-frame Laplace が自動で成立する。
- 事前分布 (FR-125) は精密化値を中心とする有界区間の ``RestraintSpec`` (格子シフト上限の発想)
  を自動構成して既存 ``build_prior_from_restraints`` へ渡す。**MAP が事前分布の台に必ず入る**
  ことを構成的に保証する (台外 MAP は nested/Laplace 双方を壊すため不変条件)。
- 相から値を読めないパラメータ (``global.*`` 等) は黙って既定事前分布 (台外 MAP のリスク) に
  落とさず ``ValueError`` で大声で失敗する。呼び側 (discrimination) がサロゲートへ縮退する。

コア依存は numpy のみ。backend は ``RefinementBackend`` Protocol 経由 (GSAS 遅延 import 圏外)。
"""

from __future__ import annotations

from dataclasses import dataclass, replace as _dc_replace
from typing import Sequence

import numpy as np

from ..backends.base import Curvature, RefinementBackend, RefinementModel, parse_param
from ..model import PhaseInstance, RefinementMetrics
from .base import EvidenceProblem, PriorSpec
from .prior import RestraintSpec, build_prior_from_restraints

__all__ = [
    "FrameState",
    "PhysicalProblemConfig",
    "build_physical_problem",
    "restraints_from_state",
]


@dataclass(frozen=True)
class PhysicalProblemConfig:
    """物理 EvidenceProblem の事前分布マージン設定 (frozen)。Issue #76 / FR-125。

    restraint 未宣言の判別仮説に対し「格子シフト上限」相当の有界事前分布を精密化値から組む
    ためのマージン。``lattice_rel_margin`` 既定 0.02 は Rietveld 収束半径 (~2%, Issue #20 の
    経験値) に合わせる。手動上書きは ``build_physical_problem(overrides=...)`` で受ける。
    """

    lattice_rel_margin: float = 0.02  # 【格子】: 精密化値 v 中心 ±v·margin の uniform
    scale_upper_factor: float = 4.0  # 【scale】: uniform [0, v·factor] (v>0 のとき)
    scale_degenerate_upper: float = 1.0e6  # 【scale 縮退】: v<=0 のときの有限上限 (prior.py と同値)
    eval_max_cycles: int = 1  # 【純評価 refine の max_cycles】: free=∅ では実質未使用 (契約明示)


@dataclass(frozen=True)
class FrameState:
    """物理 problem 構築に必要な 1 フレームの精密化状態 (frozen)。Issue #76。

    ``phases`` は当該フレームの**精密化済み** (MAP) 相集合、``free_params`` は実際に解放された
    連続パラメータ (仮説の実 DOF)。``curvature`` は backend が公開した最終 p の JᵀJ
    (欠如は None — その場合 joint hessian は組めず Laplace は BIC 縮退するが、logL は物理のまま
    nested 経路で使える)。
    """

    frame_index: int
    phases: tuple[PhaseInstance, ...]
    free_params: frozenset[str]
    two_theta: np.ndarray
    intensity: np.ndarray
    curvature: Curvature | None = None
    weights: np.ndarray | None = None


def _read_param(phases: tuple[PhaseInstance, ...], name: str) -> float:
    """精密化済み相集合からパラメータ現在値を読む (backend 非依存の値リーダ)。

    サポート: ``phase{i}.scale`` / ``phase{i}.wt_frac`` / ``phase{i}.lattice.{attr}`` /
    ``phase{i}.occ.{site}``。相に属さない ``global.*`` や未知 suffix は値を読めない =
    事前分布中心を構成できないため ``ValueError`` (呼び側がサロゲートへ縮退する契約)。
    """
    idx, key = parse_param(name)
    if idx < 0 or idx >= len(phases):
        raise ValueError(f"physical problem: 相から値を読めないパラメータです: {name!r}")
    phase = phases[idx]
    if key == "scale":
        return float(phase.scale)
    if key == "wt_frac":
        return float(phase.wt_frac) if phase.wt_frac is not None else 0.0
    if key.startswith("lattice."):
        return float(getattr(phase.lattice, key.split(".", 1)[1]))
    if key.startswith("occ."):
        return float(phase.occupancies.get(key.split(".", 1)[1], 0.0))
    raise ValueError(f"physical problem: 未サポートのパラメータ種別です: {name!r}")


def _write_param(
    phases: tuple[PhaseInstance, ...], name: str, value: float
) -> tuple[PhaseInstance, ...]:
    """パラメータ値を相集合へ書いた新しい tuple を返す (非破壊・backend 非依存)。

    ``_read_param`` と対で、サポート種別も同一。クリップは行わない (θ は事前分布の台
    [有界区間] からしか来ない前提。台の構成は ``restraints_from_state`` が保証する)。
    """
    idx, key = parse_param(name)
    phase = phases[idx]
    phases_list = list(phases)
    if key == "scale":
        phases_list[idx] = phase.with_updates(scale=value)
    elif key == "wt_frac":
        phases_list[idx] = phase.with_updates(wt_frac=value)
    elif key.startswith("lattice."):
        attr = key.split(".", 1)[1]
        phases_list[idx] = phase.with_updates(
            lattice=_dc_replace(phase.lattice, **{attr: value})
        )
    elif key.startswith("occ."):
        site = key.split(".", 1)[1]
        occ = dict(phase.occupancies)
        occ[site] = value
        phases_list[idx] = phase.with_updates(occupancies=occ)
    else:  # pragma: no cover - _read_param が先に弾くため到達しない防御
        raise ValueError(f"physical problem: 未サポートのパラメータ種別です: {name!r}")
    return tuple(phases_list)


def restraints_from_state(
    phases: tuple[PhaseInstance, ...],
    free_params: frozenset[str],
    *,
    config: PhysicalProblemConfig,
) -> tuple[RestraintSpec, ...]:
    """精密化状態から nested 事前分布用の ``RestraintSpec`` を自動構成する。FR-125。

    判別仮説は明示 restraint を持たないため、「格子シフト上限」の発想で精密化済み値 v を
    中心とする有界区間を組む:

    - ``lattice.*``: uniform [v(1−m), v(1+m)] (m = ``lattice_rel_margin``)
    - ``scale``: uniform [min(0,v), max(v·factor, v)] (v<=0 の上限は ``scale_degenerate_upper``)
    - ``wt_frac`` / ``occ.*``: uniform [min(0,v), max(1, v)]

    いずれも **v が区間に入る** (MAP が事前分布の台内) を構成的に保証する — 全分岐で境界を
    v で括る (負値等の縮退値でも破れない)。値を読めないパラメータは ``_read_param`` が
    ``ValueError`` で弾く (黙って既定分布に落とさない)。返り値は param_name 昇順 (決定論, NFR-102)。
    """
    restraints: list[RestraintSpec] = []
    for name in sorted(free_params):
        v = _read_param(phases, name)
        _, key = parse_param(name)
        if key.startswith("lattice."):
            m = config.lattice_rel_margin
            low, high = v * (1.0 - m), v * (1.0 + m)
            # 【負値/ゼロ格子の防御】: v<=0 は物理的に無効だが、区間の向きだけは保証する
            if low > high:
                low, high = high, low
            restraints.append(RestraintSpec(param_name=name, lower=low, upper=high))
        elif key == "scale":
            upper = v * config.scale_upper_factor if v > 0.0 else config.scale_degenerate_upper
            # 【台内保証 (レビュー指摘)】: 縮退した精密化値 (負の scale 等) でも MAP が区間に
            #   入るよう境界を v で括る。台外 MAP は log_pdf=-inf → Laplace が BIC へ静かに縮退
            #   し「実曲率で解消できない」と誤認させるため、lattice 分岐の swap と同格の防御。
            restraints.append(
                RestraintSpec(param_name=name, lower=min(0.0, v), upper=max(upper, v))
            )
        else:  # wt_frac / occ.* (値は _read_param 通過済み = サポート種別)
            restraints.append(
                RestraintSpec(param_name=name, lower=min(0.0, v), upper=max(1.0, v))
            )
    return tuple(restraints)


def build_physical_problem(
    backend: RefinementBackend,
    frames: Sequence[FrameState],
    *,
    metrics: RefinementMetrics,
    label: str,
    config: PhysicalProblemConfig,
    overrides: dict[str, PriorSpec] | None = None,
) -> EvidenceProblem:
    """区間フレーム列から joint 物理 EvidenceProblem を構築する。Issue #76 / FR-122/125/313。

    【θ の構造】: フレーム index 昇順に、各フレームの ``sorted(free_params)`` を連結する。
      次元名は ``frame{i:04d}.{param}`` (昇順 = フレーム major、``EvidenceProblem`` の
      priors 昇順契約を満たす)。
    【logL】: ``Σ_i -χ²_i(θ_i)/2``。χ²_i は ``backend.refine(free_params=∅)`` の純評価。
      非有限 chi2 は -inf (zero probability) へ写す (例外化しない)。
    【map/hessian】: map_point は精密化済み相の現在値。hessian は全フレームの ``Curvature``
      が揃い、かつ各 ``curvature.param_names`` がフレームの ``sorted(free_params)`` と厳密一致
      するときのみブロック対角で組む (不一致/欠如は None — Laplace は BIC へ縮退し、三重ガード
      が経路を正しくラベルする)。
    【metrics】: 呼び側の合成 metrics (Σbic) をそのまま保持し、BIC フォールバック値を bic 一次と
      厳密一致に保つ (PR #75 ガード/メッセージング前提の維持)。
    【決定論 (NFR-102)】: 乱数不使用・sorted のみ。同一入力 2 回でビット同一。

    :raises ValueError: frames が空 / frame_index 重複 / 値を読めないパラメータを含むとき
      (呼び側がサロゲートへ縮退する契約)。
    """
    if not frames:
        raise ValueError("physical problem: frames が空です")
    ordered = sorted(frames, key=lambda f: f.frame_index)
    indices = [f.frame_index for f in ordered]
    if len(set(indices)) != len(indices):
        raise ValueError(f"physical problem: frame_index が重複しています: {indices}")

    overrides = overrides or {}
    priors: list[PriorSpec] = []
    map_values: list[float] = []
    # (frame, names, θ スライス) の束。log_likelihood 閉包が参照する
    slices: list[tuple[FrameState, tuple[str, ...], slice]] = []
    blocks: list[np.ndarray] = []
    hessian_ok = True
    offset = 0

    for frame in ordered:
        names = tuple(sorted(frame.free_params))
        if not names:
            raise ValueError(
                f"physical problem: frame {frame.frame_index} の解放パラメータが空です"
            )
        restraints = restraints_from_state(frame.phases, frame.free_params, config=config)
        frame_priors = build_prior_from_restraints(
            frame.free_params, restraints, overrides=overrides
        )
        prefix = f"frame{frame.frame_index:04d}."
        for p in frame_priors:
            priors.append(_dc_replace(p, param_name=prefix + p.param_name))
        map_values.extend(_read_param(frame.phases, n) for n in names)
        slices.append((frame, names, slice(offset, offset + len(names))))
        offset += len(names)

        curv = frame.curvature
        if curv is not None and curv.param_names == names:
            blocks.append(np.asarray(curv.hessian, dtype=float))
        else:
            # 【hessian 断念】: 欠如または列順不一致 (例: μt 列が混ざる)。黙って誤った並びで
            #   組むと Laplace が静かに偏るため、joint hessian ごと提供しない (BIC 縮退が正)。
            hessian_ok = False

    ndim = offset
    map_point = np.array(map_values, dtype=float)

    hessian: np.ndarray | None = None
    if hessian_ok and blocks:
        hessian = np.zeros((ndim, ndim), dtype=float)
        pos = 0
        for b in blocks:
            k = b.shape[0]
            hessian[pos : pos + k, pos : pos + k] = b
            pos += k

    eval_max_cycles = config.eval_max_cycles

    def log_likelihood(theta: np.ndarray) -> float:
        """joint 物理対数尤度 Σ_i -χ²_i(θ_i)/2 (backend 純評価・非有限は -inf)。"""
        arr = np.asarray(theta, dtype=float)
        total = 0.0
        for frame, names, sl in slices:
            phases = frame.phases
            for name, value in zip(names, arr[sl]):
                phases = _write_param(phases, name, float(value))
            result = backend.refine(
                RefinementModel(
                    phases=phases,
                    free_params=frozenset(),
                    two_theta=frame.two_theta,
                    intensity=frame.intensity,
                    weights=frame.weights,
                ),
                max_cycles=eval_max_cycles,
            )
            chi2 = float(result.chi2)
            if not np.isfinite(chi2):
                return float("-inf")
            total += -0.5 * chi2
        return total

    return EvidenceProblem(
        metrics=metrics,
        log_likelihood=log_likelihood,
        priors=tuple(priors),
        map_point=map_point,
        hessian=hessian,
        label=label,
    )
