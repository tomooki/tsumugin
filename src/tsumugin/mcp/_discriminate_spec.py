"""JSON ↔ discrimination 入力の marshaling ヘルパ (Issue #130 L3)。

② ``discriminate`` ツールが受ける JSON を discrimination のコア入力
(``PhaseInstance`` / ``LatticeParams`` / ``FixedPhaseSpec`` / ``FrameSeries``) へ変換する
**唯一の実装**。コア dataclass に JSON 知識を持ち込まないため mcp 層に置く
(``_recipe_spec`` と同じ方針)。numpy-only・GSAS 非依存。

不正な入力は黙って既定へ落とさず ``ValueError`` に正規化する — 呼び出し側 (② ツール) が
``{"error","error_type"}`` dict へ縮退する契約 (CLAUDE.md ② 不変条件)。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

import numpy as np

from ..model import LatticeParams, PhaseInstance
from ..operando.cell_phases import FixedPhaseSpec
from ..sequential.series import FrameSeries

__all__ = [
    "lattice_to_dict",
    "lattice_from_dict",
    "phase_instance_to_dict",
    "phase_instance_from_dict",
    "fixed_phase_to_dict",
    "fixed_phase_from_dict",
    "frame_series_from_spec",
]

# 単一パターンローダの型: パス → (two_theta, intensity)
PatternLoader = Callable[[str], tuple[np.ndarray, np.ndarray]]


def lattice_to_dict(lattice: LatticeParams) -> dict[str, float]:
    """``LatticeParams`` を JSON dict へ写す (σ は入力 spec に載せない = 出力専用)。"""
    return {
        "a": lattice.a,
        "b": lattice.b,
        "c": lattice.c,
        "alpha": lattice.alpha,
        "beta": lattice.beta,
        "gamma": lattice.gamma,
    }


def lattice_from_dict(d: Mapping[str, object]) -> LatticeParams:
    """JSON dict → ``LatticeParams`` (角度は既定 90.0)。a/b/c 欠落は ValueError。"""
    if not isinstance(d, Mapping):
        raise ValueError(f"lattice は dict である必要があります: {type(d).__name__}")
    for key in ("a", "b", "c"):
        if key not in d:
            raise ValueError(f"lattice に必須キー '{key}' がありません")
    return LatticeParams(
        a=float(d["a"]),
        b=float(d["b"]),
        c=float(d["c"]),
        alpha=float(d.get("alpha", 90.0)),
        beta=float(d.get("beta", 90.0)),
        gamma=float(d.get("gamma", 90.0)),
    )


def phase_instance_to_dict(phase: PhaseInstance) -> dict[str, object]:
    """``PhaseInstance`` を JSON dict へ写す (structure_ref/occupancies/wt_frac 含む)。"""
    return {
        "phase_ref": phase.phase_ref,
        "lattice": lattice_to_dict(phase.lattice),
        "scale": phase.scale,
        "wt_frac": phase.wt_frac,
        "occupancies": dict(phase.occupancies),
        "structure_ref": phase.structure_ref,
    }


def phase_instance_from_dict(d: Mapping[str, object]) -> PhaseInstance:
    """JSON dict → ``PhaseInstance``。phase_ref/lattice 必須、他は既定。"""
    if not isinstance(d, Mapping):
        raise ValueError(f"phase は dict である必要があります: {type(d).__name__}")
    if "phase_ref" not in d:
        raise ValueError("phase に必須キー 'phase_ref' がありません")
    if "lattice" not in d:
        raise ValueError("phase に必須キー 'lattice' がありません")
    occ_raw = d.get("occupancies") or {}
    if not isinstance(occ_raw, Mapping):
        raise ValueError("phase.occupancies は dict である必要があります")
    wt_frac = d.get("wt_frac")
    structure_ref = d.get("structure_ref")
    return PhaseInstance(
        phase_ref=str(d["phase_ref"]),
        lattice=lattice_from_dict(d["lattice"]),  # type: ignore[arg-type]
        scale=float(d.get("scale", 1.0)),
        wt_frac=None if wt_frac is None else float(wt_frac),
        occupancies={str(k): float(v) for k, v in occ_raw.items()},
        structure_ref=None if structure_ref is None else str(structure_ref),
    )


def fixed_phase_to_dict(fixed: FixedPhaseSpec) -> dict[str, object]:
    """``FixedPhaseSpec`` を JSON dict へ写す。"""
    return {"phase": phase_instance_to_dict(fixed.phase), "label": fixed.label}


def fixed_phase_from_dict(d: Mapping[str, object]) -> FixedPhaseSpec:
    """JSON dict → ``FixedPhaseSpec``。phase/label 必須。"""
    if not isinstance(d, Mapping):
        raise ValueError(f"fixed_phase は dict である必要があります: {type(d).__name__}")
    if "phase" not in d or "label" not in d:
        raise ValueError("fixed_phase は 'phase' と 'label' が必須です")
    return FixedPhaseSpec(
        phase=phase_instance_from_dict(d["phase"]),  # type: ignore[arg-type]
        label=str(d["label"]),
    )


def frame_series_from_spec(
    spec: Mapping[str, object], *, loader: PatternLoader | None
) -> FrameSeries:
    """FrameSeries を 2 経路のいずれかで構築する (Issue #130 L3)。

    - **生配列**: ``{"two_theta": [...], "intensities": [[...], ...]}`` を直接 stack する。
    - **ファイル群**: ``{"data_paths": ["f0", "f1", ...]}`` を ``loader`` (パス→(2θ,強度))
      で 1 フレームずつ読み、共通グリッド検証の上で行スタックする。``loader`` 未注入は
      ValueError (到達可能性: ② は ``reference.io.load_pattern`` を注入する)。

    どちらのキーも無い/空は ValueError。ファイル群の 2θ グリッドが不一致なら ValueError
    (FrameSeries は全フレーム共通グリッドが前提)。
    """
    if not isinstance(spec, Mapping):
        raise ValueError(f"series は dict である必要があります: {type(spec).__name__}")

    if spec.get("two_theta") is not None and spec.get("intensities") is not None:
        two_theta = np.asarray(spec["two_theta"], dtype=float)
        intensities = np.asarray(spec["intensities"], dtype=float)
        if intensities.ndim != 2:
            raise ValueError("series.intensities は 2 次元 (n_frames, n_points) が必要です")
        if intensities.shape[1] != two_theta.size:
            raise ValueError(
                f"series.intensities の列数 {intensities.shape[1]} が two_theta 長 "
                f"{two_theta.size} と一致しません"
            )
        return FrameSeries(two_theta=two_theta, intensities=intensities)

    paths = spec.get("data_paths")
    if paths:
        if loader is None:
            raise ValueError(
                "series.data_paths が指定されましたが loader (パターンローダ) が未注入です"
            )
        return _stack_from_files(paths, loader)  # type: ignore[arg-type]

    raise ValueError(
        "series は {two_theta, intensities} 生配列か {data_paths} ファイル群のいずれかが必要です"
    )


def _stack_from_files(paths: Sequence[str], loader: PatternLoader) -> FrameSeries:
    """各パスを loader で読み、共通グリッド検証の上で (n_frames, n_points) へ行スタックする。"""
    grid: np.ndarray | None = None
    rows: list[np.ndarray] = []
    for path in paths:
        tt, intensity = loader(str(path))
        tt = np.asarray(tt, dtype=float)
        intensity = np.asarray(intensity, dtype=float)
        if grid is None:
            grid = tt
        elif tt.shape != grid.shape or not np.allclose(tt, grid):
            raise ValueError(
                f"フレーム '{path}' の 2θ グリッドが先頭フレームと一致しません "
                "(FrameSeries は全フレーム共通グリッドが前提)"
            )
        rows.append(intensity)
    if grid is None:
        raise ValueError("series.data_paths が空です")
    return FrameSeries(two_theta=grid, intensities=np.vstack(rows))
