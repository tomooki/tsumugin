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
from .base import RefinementModel, RefinementResult, parse_param

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


class TopasBackend:
    """`RefinementBackend` の TOPAS 実装。

    認識するパラメータ suffix は GSAS 版と同じ ``"scale"`` と ``"lattice.*"`` のみ。
    それ以外 (profile/texture 等) は**黙って無視する** — 探索層は広い語彙を投げてくるので、
    未知 suffix で落とすと仮説が評価されないまま消える。
    """

    name = "topas"

    @staticmethod
    def _require_simplified_phases(phases: Sequence[PhaseInstance]) -> None:
        """実 CIF (``structure_ref``) を渡されたら**黙って簡約構造で代替しない**。

        `GSASIIBackend` は ``structure_ref`` があれば実 CIF を読む。TOPAS 版は簡約モデル
        (P m m m・Ni 1 原子) しか持たないので、同じ入力を黙って代替すると **③ から見て
        「実構造で判別した」ことになる**。実構造判別 (`discriminate`) はまさにこの経路なので、
        捏造構造で走った結果が実データの結論として返ってしまう。

        :raises NotImplementedError: いずれかの相が ``structure_ref`` を持つとき。
        """
        offenders = [p.phase_ref for p in phases if getattr(p, "structure_ref", None)]
        if offenders:
            raise NotImplementedError(
                f"TopasBackend は実 CIF (structure_ref) に未対応です: {offenders}。"
                f"簡約モデル (P m m m・Ni 1 原子) で黙って代替すると、実構造で判別したことに"
                f"なってしまうため停止します。実構造の精密化には "
                f"`topas.engine.run_topas_rietveld` (auto_rietveld の backend=\"topas\") を"
                f"使ってください。"
            )

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
        self._require_simplified_phases(phases)
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
        self._require_simplified_phases(model.phases)
        grid = np.asarray(model.two_theta, dtype=float)
        observed = np.asarray(model.intensity, dtype=float)
        weights = (
            np.ones_like(observed)
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
            phases=self._read_back(model.phases, records, scale_free, cell_free),
            chi2=chi2,
            rwp=rwp,
            n_obs=int(observed.size),
            n_params=len(scale_free) + 3 * len(cell_free),
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
        topas_phases = tuple(
            _simplified_phase(i, phase, cell_free=i in set(cell_free))
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
        scale_free: "set[int]",
        cell_free: "set[int]",
    ) -> "tuple[PhaseInstance, ...]":
        """精密化後の格子/スケールを `PhaseInstance` へ書き戻す。

        **解放していない相には σ を付けない** — 「精密化した」と「初期値のまま」を
        結果から区別できなくなるため。
        """
        keyed = getattr(records, "keyed", {})
        cells = keyed.get("cell", {})
        scales = keyed.get("scale_val", {})
        updated: list[PhaseInstance] = []
        for index, phase in enumerate(phases):
            name = f"phase{index}"
            lattice = phase.lattice
            if index in cell_free:
                values = {
                    axis: cells.get(f"{name}/{axis}") for axis in ("a", "b", "c")
                }
                if all(v is not None for v in values.values()):
                    # 【σ は当該 refine で推定したものだけ】: esd が取れた軸のみ載せる。
                    #   0/非有限は「取得不能」であって「誤差 0」ではない。
                    sigma = {
                        axis: values[axis][1]
                        for axis in ("a", "b", "c")
                        if values[axis][1] is not None
                        and math.isfinite(values[axis][1])
                        and values[axis][1] > 0.0
                    }
                    lattice = LatticeParams(
                        a=values["a"][0],
                        b=values["b"][0],
                        c=values["c"][0],
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
