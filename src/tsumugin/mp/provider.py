"""Materials Project 相ライブラリ供給元 (``ReferenceProvider`` 実装, 仕様 §5 FR-100〜105)。

``MPClient`` から取得した ``MPEntry`` 群を、重複排除 (FR-102) → XRD ピーク生成 (FR-105) を経て
コアの ``ReferencePhase`` へ変換する。相同定エンジン (``identify_phases``) はこの供給元を
``ReferenceProvider`` として受け取り、pymatgen / mp_api を直接引き込まない。

pymatgen を要求する処理 (XRD 生成・StructureMatcher) は ``simulate`` / ``dedupe`` に注入された
呼び出し可能物へ委譲する。既定は ``mp.xrd`` の遅延 import 実装で、テストはフェイクを注入できる。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ..reference.model import ReferencePhase
from .client import MPClient, MPEntry
from .xrd import group_equivalent, simulate_reference_peaks, structure_cell_and_system

__all__ = ["MPReferenceProvider"]

# 型エイリアス: 構造 → ピーク列 / 構造列 → 等価グループ index / 構造 → (格子, 結晶系)。
SimulateFn = Callable[..., Sequence]
GroupFn = Callable[[Sequence[object]], Sequence[Sequence[int]]]
StructureMetaFn = Callable[[object], "tuple[tuple[float, ...], str]"]


class MPReferenceProvider:
    """Materials Project を供給元とする ``ReferenceProvider`` 実装。🔵 FR-100〜105

    Args:
        client: ``MPClient`` (元素系 → ``MPEntry`` 群)。
        wavelength_angstrom: XRD 生成の線源波長 (Å)。
        two_theta_range: XRD 生成の 2θ 範囲 (度)。
        deduplicate: True で ``StructureMatcher`` により等価構造を重複排除する (FR-102)。
        simulate: 構造 → ピーク列 (テスト注入用, 既定 ``simulate_reference_peaks``)。
        group: 構造列 → 等価グループ (テスト注入用, 既定 ``group_equivalent``)。
        structure_meta: 構造 → (格子, 結晶系) (異方格子整合用, 既定 ``structure_cell_and_system``)。
            抽出に失敗した相 (フェイク構造・pymatgen 無し) は格子情報なしに縮退する (異方 re-score をスキップ)。
    """

    def __init__(
        self,
        client: MPClient,
        *,
        wavelength_angstrom: float = 1.5406,
        two_theta_range: tuple[float, float] = (10.0, 90.0),
        deduplicate: bool = True,
        simulate: SimulateFn = simulate_reference_peaks,
        group: GroupFn = group_equivalent,
        structure_meta: StructureMetaFn = structure_cell_and_system,
    ) -> None:
        self._client = client
        self._wavelength = wavelength_angstrom
        self._two_theta_range = two_theta_range
        self._deduplicate = deduplicate
        self._simulate = simulate
        self._group = group
        self._structure_meta = structure_meta

    def fetch(self, elements: Sequence[str]) -> tuple[ReferencePhase, ...]:
        """MP から候補相を取得し ``ReferencePhase`` へ変換する。🔵 FR-101/102/105

        構造を持たない相はスキップする (XRD 生成不可)。重複排除を有効にすると等価構造の
        代表 (最小 index) のみを残す。
        """
        entries = list(self._client.search(elements))
        representatives = self._select_representatives(entries)

        refs: list[ReferencePhase] = []
        for entry in representatives:
            if entry.structure is None:  # 構造なしは XRD 生成不可のためスキップ 🔵
                continue
            peaks = tuple(
                self._simulate(
                    entry.structure,
                    wavelength_angstrom=self._wavelength,
                    two_theta_range=self._two_theta_range,
                )
            )
            # 異方格子整合 (Issue #20 hybrid) 用の格子情報。抽出失敗 (フェイク構造/pymatgen 無し) は
            # None に縮退し、当該相は等方スコアのみ (異方 re-score をスキップ; 提案≠適用の安全側)。
            cell: tuple[float, ...] | None
            crystal_system: str | None
            try:
                cell, crystal_system = self._structure_meta(entry.structure)
            except Exception:
                cell, crystal_system = None, None
            refs.append(
                ReferencePhase(
                    phase_id=entry.material_id,
                    formula=entry.formula,
                    element_system=entry.element_system,
                    peaks=peaks,
                    spacegroup=entry.spacegroup,
                    energy_above_hull=entry.energy_above_hull,
                    cell=cell,  # type: ignore[arg-type]
                    crystal_system=crystal_system,
                )
            )
        return tuple(refs)

    def _select_representatives(self, entries: Sequence[MPEntry]) -> list[MPEntry]:
        """重複排除 (FR-102)。無効時 / 構造付き 2 件未満はそのまま返す。🔵"""
        with_structure = [e for e in entries if e.structure is not None]
        if not self._deduplicate or len(with_structure) < 2:
            return list(entries)

        groups = self._group([e.structure for e in with_structure])
        # 各グループの代表 (最小 index) のみ残す。構造なし相は影響を受けないため別途保持。
        rep_indices = {min(g) for g in groups}
        reps = [e for i, e in enumerate(with_structure) if i in rep_indices]
        without_structure = [e for e in entries if e.structure is None]
        return reps + without_structure
