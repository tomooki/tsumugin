"""TOPAS (tc.exe) バックエンド (仕様 §3.1 / P7, M12 T9)。

`GSASIIBackend` と**対の並行実装**。`RefinementModel` を一時 INP へ変換して tc.exe を回す。
`tsumugin.topas.engine` (実構造の段階解放エンジン) とは役割が違う — こちらは
`PhaseInstance` (格子 + スケールしか持たない簡約モデル) を扱う探索層向けの境界で、
``simulate()`` を要求する `search.tree` / `sequential.engine` の口を塞ぐためにある。

**構造モデルの簡約は GSAS 側と同一にする**: 各相を空間群 P m m m (直方晶)・原点に Ni 1 原子と
して扱う。`SimulatedBackend` の直方 d 間隔模型と整合し、格子 a/b/c を個別に識別できる。
両バックエンドで同じ簡約を使わないと、同じ `PhaseInstance` から違う計算パターンが出て
**バックエンドを替えると仮説の順位が変わる**ことになる。

**rwp/chi2 のセマンティクスは残差から自前で計算する** (不変条件「chi2/rwp のセマンティクスは
バックエンド間で統一」)。TOPAS の ``r_wp_dash`` は背景差引きで GSAS と非互換であり、
``r_wp`` も重み付けの規約がこちらの ``model.weights`` と一致する保証がないため、
どちらも指標としては使わず観測/計算パターンから ``100·√(Σw(yo−yc)²/Σw·yo²)`` を組む。
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import numpy as np

from ..errors import TopasRunError, TopasUnavailableError
from ..model import LatticeParams, PhaseInstance
from ..model import strip_lattice_sigma as _strip_sigma
from ..topas.availability import require_tc_exe, topas_available
from ..topas.driver import run_tc
from ..topas.inp import (
    Param,
    PhaseHistogramTerms,
    TopasDocument,
    TopasHistogram,
    TopasPhase,
    TopasSite,
)
from ..topas.instrument import tchz_line, write_xye
from ..topas.parse import parse_records
from .base import RefinementModel, RefinementResult, default_weights, parse_param

__all__ = ["TopasBackend"]

_DEFAULT_WAVELENGTH = 1.5406  # Cu Kα1 (Å)

def _simplified_phase(index: int, phase: PhaseInstance, *, cell_free: bool) -> TopasPhase:
    """`PhaseInstance` を簡約 `TopasPhase` へ写す (P m m m ・ Ni 1 原子)。"""
    lattice = phase.lattice
    name = f"phase{index}"
    return TopasPhase(
        phase_name=name,
        space_group="Pmmm",
        cell={
            "a": Param(lattice.a, refine=cell_free, name=f"{name}_a", minimum=0.5),
            "b": Param(lattice.b, refine=cell_free, name=f"{name}_b", minimum=0.5),
            "c": Param(lattice.c, refine=cell_free, name=f"{name}_c", minimum=0.5),
        },
        sites=(
            TopasSite(
                label="Ni1",
                element="Ni",
                x=Param(0.0),
                y=Param(0.0),
                z=Param(0.0),
                occupancy=Param(1.0),
                beq=Param(0.7895683520871487),  # Uiso 0.01 → B = 8π²·Uiso
            ),
        ),
        free_cell_keys=("a", "b", "c"),
    )


#: 判別が解放する軸 (角度は解放しない — GSAS 経路 `_apply_cell` と同じ規律)。
_LENGTH_AXES = ("a", "b", "c")


def _structure_phase(index: int, phase: PhaseInstance, *, cell_free: bool) -> TopasPhase:
    """実 CIF (``structure_ref``) から `TopasPhase` を組み、格子長だけ warm-start へ上書きする。

    `GSASIIBackend._add_phases` の実 CIF 分岐 (Issue #130) と対の実装。**簡約モデルで黙って
    代替しない** — ③ から見て「実構造で判別した」ことになってしまうため (#180)。

    - **角度は CIF 由来を保つ**: 判別は a/b/c しか解放しないので、`LatticeParams` の
      既定 90° で上書きすると単斜/三斜 CIF の正しい角を潰す (GSAS 側 `_apply_cell` と同じ)。
    - **解放は結晶系の独立軸だけ**: 立方晶で 3 軸を独立に動かすと対称性が壊れる
      (しかも Rwp は下がりうる)。従属軸は ``=Get(a);`` の参照式のまま触らない。
    """
    from ..autorietveld.cif_normalize import read_structure_cif
    from ..topas.structure import structure_to_topas_phase, to_topas_spacegroup
    from ..topas.symmetry import ensure_symops

    structure = read_structure_cif(str(phase.structure_ref))
    spacegroup = to_topas_spacegroup(structure.spacegroup_hm, structure.it_number)
    symops = ensure_symops(spacegroup, structure.symops)
    name = f"phase{index}"
    built = structure_to_topas_phase(structure, name, symops=symops)

    lengths = {"a": phase.lattice.a, "b": phase.lattice.b, "c": phase.lattice.c}
    cell: dict[str, Param] = {}
    for axis, param in built.cell.items():
        if param.is_reference:
            cell[axis] = param  # 従属軸 (=Get(a);) は独立軸に追随する
            continue
        free = cell_free and axis in _LENGTH_AXES and axis in built.free_cell_keys
        cell[axis] = replace(
            param,
            value=lengths.get(axis, param.value),
            refine=free,
            name=param.name or f"{name}_{axis}",
            minimum=param.minimum if axis not in _LENGTH_AXES else 0.5,
        )
    return built.with_updates(cell=cell)


def count_free_params(doc: TopasDocument, *, scale_free: Sequence[int]) -> int:
    """文書中で実際に解放されているパラメータ数 (**BIC の母数**)。

    簡約モデル (P m m m) は常に 3 軸独立なので ``3 * len(cell_free)`` で正しかったが、
    実 CIF では結晶系で変わる (立方晶は 1)。**過大申告すると仮説比較が歪む**ので、
    「何軸解放したつもりか」ではなく**文書が実際に解放している数**を数える。
    """
    cell = sum(
        1 for phase in doc.phases for param in phase.cell.values()
        if param.refine and not param.is_reference
    )
    return cell + len(set(scale_free))


class TopasBackend:
    """`RefinementBackend` の TOPAS 実装。

    認識するパラメータ suffix は GSAS 版と同じ ``"scale"`` と ``"lattice.*"`` のみ。
    それ以外 (profile/texture 等) は**黙って無視する** — 探索層は広い語彙を投げてくるので、
    未知 suffix で落とすと仮説が評価されないまま消える。
    """

    name = "topas"

    def __init__(self, *, wavelength: float = _DEFAULT_WAVELENGTH) -> None:
        if not topas_available():
            raise TopasUnavailableError(
                "tc.exe が見つかりません。TOPAS を導入して TSUMUGIN_TOPAS_PATH を設定するか、"
                "SimulatedBackend / GSASIIBackend を使用してください。"
            )
        require_tc_exe()
        self.wavelength = float(wavelength)

    # ---- 前方モデル -----------------------------------------------------

    def simulate(
        self, phases: Sequence[PhaseInstance], two_theta: np.ndarray
    ) -> np.ndarray:
        """計算パターン (Ycalc) を返す。

        **観測ノイズを混ぜない** (NFR-102 再現性) — TOPAS には「観測データ無しで計算だけ」の
        入口が無いので、ダミーの平坦な観測を与えて ``iters 0`` で回し ``Ycalc`` を読む。
        """
        grid = np.asarray(two_theta, dtype=float)
        with tempfile.TemporaryDirectory(prefix="tsumugin-topas-sim-") as tmp:
            work = Path(tmp)
            write_xye(work / "obs.xye", grid, np.ones_like(grid))
            doc = self._document(
                phases, work, cell_free=set(), scale_free=(), max_cyc=0,
                extras=('Out_X_Ycalc("calc.txt")',),
            )
            run_tc(doc.render(), workdir=work, basename="sim", timeout=600.0)
            calc = np.loadtxt(work / "calc.txt", dtype=float)
        return np.interp(grid, calc[:, 0], calc[:, 1])

    # ---- 精密化 ---------------------------------------------------------

    def refine(
        self, model: RefinementModel, *, max_cycles: int = 20
    ) -> RefinementResult:
        grid = np.asarray(model.two_theta, dtype=float)
        observed = np.asarray(model.intensity, dtype=float)
        # 【既定重みは共有定義】: ここだけ w=1 にしていたため chi2 が GSAS/Simulated と
        #   数桁ずれ、絶対 ΔBIC の閾値 (判別の close_threshold) がエンジン依存になっていた。
        weights = (
            default_weights(observed)
            if model.weights is None
            else np.asarray(model.weights, dtype=float)
        )

        scale_free, cell_free = self._recognized(model.free_params, len(model.phases))
        any_free = bool(scale_free or cell_free)

        with tempfile.TemporaryDirectory(prefix="tsumugin-topas-ref-") as tmp:
            work = Path(tmp)
            write_xye(work / "obs.xye", grid, observed)
            doc = self._document(
                model.phases,
                work,
                cell_free=cell_free,
                scale_free=tuple(scale_free),
                max_cyc=max_cycles if any_free else 0,
                extras=('Out_X_Yobs_Ycalc("fit.txt")',),
            )
            try:
                run = run_tc(doc.render(), workdir=work, basename="refine", timeout=1800.0)
                fit = np.loadtxt(work / "fit.txt", dtype=float)
            except (TopasRunError, OSError, ValueError):
                # 【不変条件】: バックエンドの失敗は例外でなく chi2=inf に変換しガードレールへ。
                #   古い σ を素通しすると chi2=inf の仮説に σ が付いて見えるので剥離する。
                return RefinementResult(
                    phases=_strip_sigma(model.phases),
                    chi2=float("inf"),
                    rwp=float("inf"),
                    n_obs=int(observed.size),
                    n_params=0,
                    converged=False,
                    n_cycles=max_cycles,
                    free_params=model.free_params,
                )
            records = parse_records(run.results_text)

        calc = np.interp(grid, fit[:, 0], fit[:, 2])
        chi2 = float(np.sum(weights * (observed - calc) ** 2))
        denominator = float(np.sum(weights * observed**2))
        rwp = 100.0 * math.sqrt(chi2 / denominator) if denominator > 0.0 else 0.0

        return RefinementResult(
            phases=self._read_back(model.phases, records, doc, scale_free, cell_free),
            chi2=chi2,
            rwp=rwp,
            n_obs=int(observed.size),
            # 【母数は文書から数える】: 実 CIF は結晶系で独立軸の数が変わる (立方晶は 1)。
            #   ``3 * len(cell_free)`` は簡約モデル (P m m m) 専用の数え方だった。
            n_params=count_free_params(doc, scale_free=tuple(scale_free)),
            converged=any_free is False or math.isfinite(chi2),
            n_cycles=max_cycles if any_free else 1,
            free_params=model.free_params,
        )

    # ---- 内部ヘルパ -----------------------------------------------------

    def _document(
        self,
        phases: Sequence[PhaseInstance],
        work: Path,
        *,
        cell_free: "set[int]",
        scale_free: Sequence[int],
        max_cyc: int,
        extras: "tuple[str, ...]" = (),
    ) -> TopasDocument:
        # 【相ごとに解放する】: 集合を bool へ潰すと、要求していない相の格子まで動いて
        #   要求した相のフィットと相関する。しかも `_read_back` は要求分しか読み戻さないので
        #   **TOPAS が実際に動かした値と結果が食い違い**、`n_params` も過少申告になって
        #   BIC 比較が意味を失う (GSAS 側は `if i in cell_free` と相ごとに判定している)。
        free = set(cell_free)
        topas_phases = tuple(
            (
                _structure_phase(i, phase, cell_free=i in free)
                if phase.structure_ref is not None
                else _simplified_phase(i, phase, cell_free=i in free)
            )
            for i, phase in enumerate(phases)
        )
        terms = {
            phase.phase_name: PhaseHistogramTerms(
                scale=Param(
                    float(source.scale) * 1e-4,
                    refine=index in set(scale_free),
                    name=f"{phase.phase_name}_scale",
                    minimum=0.0,
                ),
                # 【名前は相ごとに分ける】: TOPAS のパラメータ名は大域なので、同名だと
                #   全相が 1 つのピーク形状を強制的に共有する。
                peak_type=tchz_line(0, phase_key=phase.phase_name),
            )
            for index, (phase, source) in enumerate(zip(topas_phases, phases))
        }
        histogram = TopasHistogram(
            data_path="obs.xye",
            preamble=(
                "lam",
                "   ymin_on_ymax 0.0001",
                f"   la 1 lo {self.wavelength!r} lh 0.1",
                "LP_Factor(26.4)",
            ),
            background=Param(0.0),
            background_coeffs=1,
            phase_terms=terms,
            # 【``xdd_out`` は xdd ブロックの中】: 文書先頭に置くと
            #   ``Cannot locate xdd_out from non_fit`` で異常終了する (実測)。
            extras=extras,
            calculation_step=float(np.diff(np.loadtxt(work / "obs.xye")[:, 0]).min()),
        )
        return TopasDocument(
            histograms=(histogram,),
            phases=topas_phases,
            max_iterations=max(int(max_cyc), 0),
            results_path="results.txt",
        )

    @staticmethod
    def _recognized(
        free_params: "frozenset[str]", n_phases: int
    ) -> "tuple[set[int], set[int]]":
        """認識できる解放指定を (scale を解放する相, 格子を解放する相) に分ける。

        **未知 suffix は黙って無視する** — 探索層は profile/texture 等の広い語彙を投げてくる
        ので、ここで落とすと仮説が評価されないまま消える (GSAS 版と同挙動)。
        """
        scale: set[int] = set()
        cell: set[int] = set()
        for name in free_params:
            try:
                index, suffix = parse_param(name)
            except ValueError:
                continue
            if not 0 <= index < n_phases:
                continue
            if suffix == "scale":
                scale.add(index)
            elif suffix.startswith("lattice"):
                cell.add(index)
        return scale, cell

    @staticmethod
    def _read_back(
        phases: Sequence[PhaseInstance],
        records: "object",
        doc: TopasDocument,
        scale_free: "set[int]",
        cell_free: "set[int]",
    ) -> "tuple[PhaseInstance, ...]":
        """精密化後の格子/スケールを `PhaseInstance` へ書き戻す。

        **解放していない相には σ を付けない** — 「精密化した」と「初期値のまま」を
        結果から区別できなくなるため。

        **従属軸は参照式から解く**: 実 CIF の立方/正方/六方晶では ``b =Get(a);`` が
        ``Out()`` に出ないので、素直に読むと 3 軸揃わず**格子が「動かなかった」ように
        見える** (実際には TOPAS が動かしている)。解決はエンジンと同じ
        `refined_cells_from_records` を使う — 別実装にすると片方だけが嘘をつく。
        """
        from ..topas.engine import refined_cells_from_records

        keyed = getattr(records, "keyed", {})
        cells = keyed.get("cell", {})
        scales = keyed.get("scale_val", {})
        resolved = refined_cells_from_records(records, doc)
        updated: list[PhaseInstance] = []
        for index, phase in enumerate(phases):
            name = f"phase{index}"
            lattice = phase.lattice
            if index in cell_free:
                found = resolved.get(name)
                if found is not None:
                    # 【σ は当該 refine で推定したものだけ】: esd が取れた軸のみ載せる。
                    #   0/非有限は「取得不能」であって「誤差 0」ではない。
                    #   従属軸は独立軸の esd を継がせない (推定していないため)。
                    sigma = {}
                    for axis in ("a", "b", "c"):
                        record = cells.get(f"{name}/{axis}")
                        if (
                            record is not None
                            and record[1] is not None
                            and math.isfinite(record[1])
                            and record[1] > 0.0
                        ):
                            sigma[axis] = record[1]
                    lattice = LatticeParams(
                        a=found[0],
                        b=found[1],
                        c=found[2],
                        alpha=lattice.alpha,
                        beta=lattice.beta,
                        gamma=lattice.gamma,
                        sigma=sigma,
                        sigma_source="covariance" if sigma else "",
                    )
            scale = phase.scale
            if index in scale_free:
                found = scales.get(name)
                if found is not None:
                    scale = found[0] / 1e-4  # 文書側で 1e-4 倍している分を戻す
            updated.append(phase.with_updates(lattice=lattice, scale=scale))
        return tuple(updated)
