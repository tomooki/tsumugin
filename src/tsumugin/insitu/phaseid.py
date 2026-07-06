"""M9 相同定→PhaseSpec 物質化ブリッジ (M6 reference の未配線ギャップの解消)。

M6 の `reference.identify_phases` は候補相をランキングするが、`autorietveld` が精密化できる
`PhaseSpec` (CIF パス) への**物質化 (materialization)** が未配線だった (M6 探索で確認)。本モジュールが
それを埋める: 残差/生パターン + 元素ヒントから新相を同定し、上位候補の実構造を CIF に書き出して
`PhaseSpec` を組む。系列途中で出現する新相を自動で精密化対象にするための橋渡し。

3 層:
- **同定 (numpy)**: `reference.identify_phases` を供給元 (既定 MP) で駆動。既知相は `exclude` で除外。
- **物質化 (遅延 pymatgen)**: `PhaseMaterializer` 抽象 — `phase_id` から CIF を書き出す。MP 実装は
  pymatgen `CifWriter`。供給元・物質化器はともに注入可能 (テストはスタブ、本番は MP)。
- **PhaseSpec 生成**: 書き出した CIF パスで `autorietveld.PhaseSpec` を組む。

コアは numpy のみ。pymatgen / mp-api は本モジュールの関数内で遅延 import する。

信頼性: 🔵 architecture.md §4。M6 identify + M7 PhaseSpec を接続する新規配線。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence, runtime_checkable

import numpy as np

from ..autorietveld.model import PhaseSpec
from ..reference.engine import identify_phases
from ..reference.provider import ReferenceProvider

# 絶対格子 (a, b, c, α, β, γ)
Cell6 = tuple[float, float, float, float, float, float]
# 物質化 CIF パス → 精密化済み絶対格子 (or None)。異方セル補正の注入点 (Issue #20)。
CellRefiner = Callable[[str], "Cell6 | None"]


@runtime_checkable
class PhaseMaterializer(Protocol):
    """相 ID から精密化可能な構造ファイル (CIF) を物質化する境界。"""

    def materialize(
        self,
        phase_id: str,
        elements: Sequence[str],
        out_path: str,
        strain: float = 0.0,
        cell: Cell6 | None = None,
    ) -> str:
        """相 ID の実構造を out_path (CIF ファイルパス) に書き出しそのパスを返す。取得不能なら例外。

        cell を与えると格子を**その絶対値 (a,b,c,α,β,γ) に置換**して書き出す (異方的な DFT 格子誤差を
        Pawley プリアラインで補正した格子を反映; Issue #20)。cell=None かつ strain!=0 なら格子を等方
        (1+strain) 倍する (M6 align_peaks 由来の等方補正)。cell は strain に優先する。
        """
        ...


@dataclass(frozen=True)
class IdentifiedPhase:
    """同定・物質化された 1 相 (PhaseSpec + 根拠)。"""

    phase_spec: PhaseSpec
    phase_id: str
    formula: str
    score: float
    strain: float
    source: str
    # Pawley プリアラインで精密化した絶対格子 (異方補正を適用した場合のみ非 None, Issue #20)。
    refined_cell: Cell6 | None = None


def _sanitize(name: str) -> str:
    """相名/ID をファイル名安全な形へ (英数と -_ のみ)。"""
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name) or "phase"


def structure_to_cif(
    structure: object, path: str | Path, strain: float = 0.0, cell: Cell6 | None = None
) -> str:
    """pymatgen ``Structure`` を CIF に書き出す (遅延 import)。書き出し先パスを返す。

    cell を与えると格子を**その絶対値に置換**して書き出す (分率座標は保持; 異方的 DFT 格子誤差を
    Pawley プリアラインで補正した格子を反映)。cell=None かつ strain!=0 なら格子を等方 (1+strain) 倍
    する。cell は strain に優先する。元構造は不変 (copy/新 Structure に適用)。
    """
    from pymatgen.io.cif import CifWriter

    if cell is not None:
        from pymatgen.core import Lattice, Structure

        structure = Structure(
            Lattice.from_parameters(*(float(x) for x in cell)),
            structure.species,  # type: ignore[attr-defined]
            structure.frac_coords,  # type: ignore[attr-defined]
        )
    elif strain:
        structure = structure.copy()  # type: ignore[attr-defined]
        structure.apply_strain(float(strain))  # type: ignore[attr-defined]
    CifWriter(structure).write_file(str(path))
    return str(path)


def identify_new_phases(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    elements: Sequence[str],
    provider: ReferenceProvider,
    materializer: PhaseMaterializer,
    workdir: str,
    exclude_formulas: Sequence[str] = (),
    exclude_phase_ids: Sequence[str] = (),
    top_k: int = 1,
    hull_cutoff_ev: float | None = 0.1,
    subtract_bg: bool = True,
    refine_lattice: bool = True,
    max_strain: float = 0.05,
    kalpha2: object | None = None,
    name_prefix: str = "phase",
    cell_refiner: CellRefiner | None = None,
) -> tuple[IdentifiedPhase, ...]:
    """パターンから新相を同定し上位 top_k を CIF に物質化して返す。

    既知相 (`exclude_formulas` / `exclude_phase_ids`) はランキングから除外する (系列途中の
    新相出現で「既知の alpha ではない相 = delta」を選ぶため)。物質化に失敗した候補は飛ばして
    次点を採る。1 つも物質化できなければ空タプル。

    :param two_theta: 観測 2θ (度, 昇順)
    :param intensity: 観測強度 (残差 or 生パターン)
    :param elements: 相同定に許す元素系
    :param provider: 候補相供給元 (既定 MP)。identify_phases に渡す
    :param materializer: phase_id→CIF 物質化器 (既定 MP)
    :param workdir: CIF 書き出し先ディレクトリ
    :param exclude_formulas: 除外する組成式 (既知相)
    :param exclude_phase_ids: 除外する相 ID (既知相)
    :param top_k: 物質化する上位候補数
    :param hull_cutoff_ev: MP 安定性フィルタ
    :param subtract_bg: 背景減算 (SNIP) してから同定するか
    :param refine_lattice: 格子精密化 (DFT 格子ズレ吸収) を有効にするか
    :param max_strain: 格子整合で許す等方歪みの上限。**DFT (MP) 構造は実測より格子が ~1–3% 大きい**
        ため既定 0.05 (M6 の 0.01 では吸収できず物質化構造が実測とずれ Rietveld が収束しない)。
        求めた歪みは物質化 CIF の格子にも適用する (materialize の strain)。
    :param name_prefix: 生成する相名/CIF 名の接頭辞
    :param cell_refiner: 物質化 CIF パス→精密化絶対格子 (or None) の異方セル補正器 (Issue #20)。
        与えると等方 strain で物質化した後、この補正器で**異方セル**を求め、非 None なら CIF を
        その絶対格子で再物質化する (DFT の異方的格子誤差を吸収; M6 等方 strain の上位互換)。
        補正器が None を返す/例外を投げると等方 strain 版のまま (安全側フォールバック)。
    :returns: 物質化した IdentifiedPhase の列 (スコア降順・最大 top_k)
    """
    ident = identify_phases(
        np.asarray(two_theta, dtype=float),
        np.asarray(intensity, dtype=float),
        provider,
        elements=list(elements),
        hull_cutoff_ev=hull_cutoff_ev,
        subtract_bg=subtract_bg,
        refine_lattice=refine_lattice,
        max_strain=max_strain,
        kalpha2=kalpha2,  # type: ignore[arg-type]
    )

    excl_forms = {f.lower() for f in exclude_formulas}
    excl_ids = set(exclude_phase_ids)
    workpath = Path(workdir)
    workpath.mkdir(parents=True, exist_ok=True)

    out: list[IdentifiedPhase] = []
    for match in ident.matches:  # score 降順・phase_id 昇順 (identify_phases 保証)
        ref = match.reference
        if ref.phase_id in excl_ids or ref.formula.lower() in excl_forms:
            continue
        cif_name = f"{_sanitize(name_prefix)}_{_sanitize(ref.phase_id)}.cif"
        cif_path = str(workpath / cif_name)
        try:
            # align_peaks が求めた等方歪みを物質化構造に適用し DFT 格子過大評価を実測へ (粗) 補正する。
            materializer.materialize(ref.phase_id, list(elements), cif_path, strain=float(match.strain))
        except Exception:
            continue  # 物質化失敗は飛ばして次点へ (提案≠適用の安全側)
        # 異方セル補正 (Issue #20): 等方 strain で潰しきれない DFT の軸別誤差を Pawley プリアラインで
        # 求め、非 None なら CIF をその絶対格子で再物質化する。失敗/None は等方版のまま (安全側)。
        refined_cell: Cell6 | None = None
        if cell_refiner is not None:
            try:
                refined_cell = cell_refiner(cif_path)
            except Exception:
                refined_cell = None
            if refined_cell is not None:
                try:
                    materializer.materialize(
                        ref.phase_id, list(elements), cif_path, cell=refined_cell
                    )
                except Exception:
                    refined_cell = None  # 再物質化失敗は等方版を維持
        phase_name = f"{_sanitize(name_prefix)}_{_sanitize(ref.formula)}"
        out.append(
            IdentifiedPhase(
                phase_spec=PhaseSpec(
                    structure_path=cif_path, phase_name=phase_name, format_hint="CIF"
                ),
                phase_id=ref.phase_id,
                formula=ref.formula,
                score=float(match.score),
                strain=float(match.strain),
                source="materials_project",
                refined_cell=refined_cell,
            )
        )
        if len(out) >= top_k:
            break
    return tuple(out)


# ------------------------- MP 実装 (遅延 import 境界) -------------------------


class MPMaterializer:
    """Materials Project 実装の物質化器 (phase_id→CIF, 遅延 import)。

    MPClient で元素系を検索し material_id が一致する実構造を pymatgen `CifWriter` で CIF 化する。
    ``entries`` を注入すればネットワーク再取得を避けられる (provider と同じ client を共有)。
    """

    def __init__(self, client: object | None = None) -> None:
        self._client = client
        self._cache: dict[str, object] = {}  # material_id -> structure

    def _lookup(self, phase_id: str, elements: Sequence[str]) -> object:
        if phase_id in self._cache:
            return self._cache[phase_id]
        if self._client is None:
            from ..mp.client import MPRestClient  # pragma: no cover - 環境依存

            self._client = MPRestClient()  # 環境変数 MATERIALS_PROJECT_API を読む
        entries = self._client.search(list(elements))  # type: ignore[union-attr]
        for e in entries:
            sid = getattr(e, "material_id", None)
            struct = getattr(e, "structure", None)
            if sid is not None and struct is not None:
                self._cache[str(sid)] = struct
        if phase_id not in self._cache:
            raise ValueError(f"MP に相 {phase_id} の実構造が見つかりません。")
        return self._cache[phase_id]

    def materialize(
        self,
        phase_id: str,
        elements: Sequence[str],
        out_path: str,
        strain: float = 0.0,
        cell: Cell6 | None = None,
    ) -> str:
        structure = self._lookup(phase_id, elements)
        return structure_to_cif(structure, out_path, strain=strain, cell=cell)
