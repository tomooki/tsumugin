"""CIF → 参照相変換の遅延 import 境界 (仕様 §5 FR-101)。

CIF テキスト (COD / ICSD / ユーザー提供) を pymatgen ``CifParser`` で結晶構造へ読み、実構造の
XRD ピーク列 (``mp.xrd.simulate_reference_peaks``) を付けた ``ReferencePhase`` を生成する。
CIF は複数データブロックを持ち得るため、構造ごとに 1 相を返す。

【遅延 import 契約】: ``import tsumugin.reference.cif`` はコア (numpy) のみで成功する。pymatgen を
  要求するのは ``cif_to_reference_phases`` の呼び出し時点のみで、未導入なら ``MPUnavailableError``
  を送出して extra ``mp`` (pymatgen) の導入手順を案内する (mp.xrd と対称)。
"""

from __future__ import annotations

import importlib.util

from ..errors import MPUnavailableError
from ..mp.xrd import _DEFAULT_WAVELENGTH_ANGSTROM, simulate_reference_peaks
from .model import ReferencePhase

__all__ = ["cif_to_reference_phases"]


def cif_to_reference_phases(
    cif: str,
    *,
    source_id: str | None = None,
    wavelength_angstrom: float = _DEFAULT_WAVELENGTH_ANGSTROM,
    two_theta_range: tuple[float, float] = (10.0, 90.0),
) -> tuple[ReferencePhase, ...]:
    """CIF テキストを 1 つ以上の ``ReferencePhase`` へ変換する (FR-101)。🔵

    Args:
        cif: CIF テキスト (1 つ以上のデータブロックを含み得る)。
        source_id: 相 ID の接頭辞 (例 ファイル名 / COD-ID)。None なら "cif"。複数構造なら
            ``{source_id}:{i}`` で採番する。
        wavelength_angstrom: XRD 生成の線源波長 (Å)。既定 Cu Kα1。
        two_theta_range: XRD 生成の 2θ 範囲 (度)。

    Returns:
        構造ごとの ``ReferencePhase`` タプル。``energy_above_hull`` は None (CIF 由来は
        hull 未登録 → hull フィルタで保持)。

    Raises:
        MPUnavailableError: optional extra ``mp`` (pymatgen) 未導入のとき。
    """
    if importlib.util.find_spec("pymatgen") is None:
        raise MPUnavailableError(
            "pymatgen が見つかりません。CIF の読み込み・XRD 生成には optional extra 'mp' が "
            "必要です: `uv sync --extra mp`。"
        )
    from pymatgen.io.cif import CifParser

    parser = CifParser.from_str(cif)
    structures = parser.parse_structures(primitive=False)

    base = source_id if source_id is not None else "cif"
    multiple = len(structures) > 1
    refs: list[ReferencePhase] = []
    for i, structure in enumerate(structures):
        phase_id = f"{base}:{i}" if multiple else base
        peaks = simulate_reference_peaks(
            structure,
            wavelength_angstrom=wavelength_angstrom,
            two_theta_range=two_theta_range,
        )
        composition = structure.composition
        element_system = tuple(sorted(str(e) for e in composition.elements))
        try:
            spacegroup = structure.get_space_group_info()[0]
        except Exception:  # noqa: BLE001  対称性決定失敗は None へ縮退 (相同定は継続)
            spacegroup = None
        refs.append(
            ReferencePhase(
                phase_id=phase_id,
                formula=composition.reduced_formula,
                element_system=element_system,
                peaks=peaks,
                spacegroup=spacegroup,
                energy_above_hull=None,  # CIF 由来は hull 未登録 (FR-103 で保持) 🔵
            )
        )
    return tuple(refs)
