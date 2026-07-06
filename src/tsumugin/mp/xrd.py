"""実構造 → XRD ピーク生成の遅延 import 境界 (仕様 §5 FR-105/102)。

pymatgen ``XRDCalculator`` で結晶構造から回折ピーク列 (2θ + 相対強度) を決定論的に生成する。
``StructureMatcher`` による等価構造グルーピング (FR-102 重複排除) も提供する。

【遅延 import 契約】: ``import tsumugin.mp.xrd`` 自体はコア (numpy) のみで成功し pymatgen を
  引き込まない。pymatgen を要求するのは各関数の**呼び出し時点**のみで、未導入なら
  ``MPUnavailableError`` を送出して extra ``mp`` の導入手順を案内する (nested/oed と対称)。
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence

from ..errors import MPUnavailableError
from ..search.peaks import Peak

__all__ = ["group_equivalent", "simulate_reference_peaks", "structure_cell_and_system"]

# Cu Kα1 波長 (Å)。粉末 XRD の既定線源。
_DEFAULT_WAVELENGTH_ANGSTROM = 1.5406


def _require_pymatgen() -> None:
    """pymatgen 未導入なら ``MPUnavailableError`` を送出する (遅延 import ガード)。🔵"""
    if importlib.util.find_spec("pymatgen") is None:
        raise MPUnavailableError(
            "pymatgen が見つかりません。相ライブラリ供給元 (Materials Project 取り込み・"
            "XRD 生成) には optional extra 'mp' が必要です: `uv sync --extra mp`。"
        )


def simulate_reference_peaks(
    structure: object,
    *,
    wavelength_angstrom: float = _DEFAULT_WAVELENGTH_ANGSTROM,
    two_theta_range: tuple[float, float] = (10.0, 90.0),
    scaled: bool = True,
) -> tuple[Peak, ...]:
    """結晶構造から XRD ピーク列を生成する (FR-105)。🔵

    【決定論 (NFR-102)】: 乱数を使わず同一構造・同一波長に同一ピーク列を返す。強度は
      ``scaled=True`` で最大 100 に正規化した相対強度 (``Peak.height``)。

    Args:
        structure: pymatgen ``Structure`` (本境界には不透明)。
        wavelength_angstrom: 線源波長 (Å, キーワード専用)。既定 Cu Kα1。
        two_theta_range: 生成する 2θ 範囲 (度)。
        scaled: True で相対強度を最大 100 に正規化する。

    Returns:
        ``position`` (2θ 度) 昇順の ``Peak`` タプル。ピークなしは空タプル。

    Raises:
        MPUnavailableError: optional extra ``mp`` (pymatgen) 未導入のとき。
    """
    _require_pymatgen()
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    calc = XRDCalculator(wavelength=wavelength_angstrom)
    pattern = calc.get_pattern(structure, scaled=scaled, two_theta_range=two_theta_range)
    # pattern.x = 2θ 配列, pattern.y = 相対強度, pattern.hkls = 反射指数。2θ 昇順で返る。
    # hkl は異方格子整合 (Issue #20 hybrid) に使う。多重反射は代表 (先頭) の hkl を採る。
    return tuple(
        Peak(position=float(x), height=float(y), hkl=_first_hkl(hkl_entry))
        for x, y, hkl_entry in zip(pattern.x, pattern.y, pattern.hkls)
    )


def _first_hkl(hkl_entry: object) -> tuple[int, int, int] | None:
    """XRDCalculator の hkls エントリ (list[dict{'hkl':(h,k,l)}]) から代表 hkl を取り出す。"""
    if isinstance(hkl_entry, (list, tuple)) and hkl_entry:
        first = hkl_entry[0]
        raw = first["hkl"] if isinstance(first, dict) and "hkl" in first else first
        try:
            return (int(round(raw[0])), int(round(raw[1])), int(round(raw[2])))
        except (TypeError, ValueError, IndexError):
            return None
    return None


def structure_cell_and_system(
    structure: object,
) -> tuple[tuple[float, float, float, float, float, float], str]:
    """pymatgen 構造から格子定数 (a,b,c,α,β,γ) と結晶系名を返す (異方格子整合の初期値)。

    trigonal はセル角で hexagonal / rhombohedral セッティングに振り分ける (異方ソルバの拘束に整合)。

    Raises:
        MPUnavailableError: pymatgen 未導入のとき。
        Exception: ``structure`` が pymatgen ``Structure`` でない (テストのフェイク等) とき
            — 呼び出し側 (provider) が捕捉して格子情報なしに縮退する。
    """
    _require_pymatgen()
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    latt = structure.lattice  # type: ignore[attr-defined]
    cell = (
        float(latt.a), float(latt.b), float(latt.c),
        float(latt.alpha), float(latt.beta), float(latt.gamma),
    )
    system = SpacegroupAnalyzer(structure).get_crystal_system()  # type: ignore[arg-type]
    if system == "trigonal":
        # 菱面体セッティング (a≈b≈c, α≈β≈γ≠90) か六方セッティング (γ≈120) か
        if abs(latt.a - latt.b) < 1e-3 and abs(latt.b - latt.c) < 1e-3 and abs(latt.alpha - 90.0) > 1.0:
            system = "rhombohedral"
        else:
            system = "hexagonal"
    return cell, system


def group_equivalent(structures: Sequence[object]) -> tuple[tuple[int, ...], ...]:
    """``StructureMatcher`` で等価構造をグルーピングする (FR-102 重複排除)。🔵

    Args:
        structures: pymatgen ``Structure`` 列。

    Returns:
        各グループの元 index タプルの並び。各グループ内は index 昇順、グループは代表
        (最小 index) 昇順で決定論的に整列する。空入力は空タプル。

    Raises:
        MPUnavailableError: optional extra ``mp`` (pymatgen) 未導入のとき。
    """
    _require_pymatgen()
    if len(structures) == 0:
        return ()
    from pymatgen.analysis.structure_matcher import StructureMatcher

    matcher = StructureMatcher()
    groups = matcher.group_structures(list(structures))
    # 元 index へ復元する (group_structures は Structure を並べ替えるため id で逆引き)。
    index_of = {id(s): i for i, s in enumerate(structures)}
    result = [tuple(sorted(index_of[id(s)] for s in group)) for group in groups]
    result.sort(key=lambda g: g[0])
    return tuple(result)
