"""TOPAS 段階解放エンジン (M12 T8)。

`autorietveld.engine.run_auto_rietveld` と**同一の入出力契約**を持つ兵行実装。既存の消費側
(`insitu` / `refine_loop` / `mcp` / `search` / `multistart` / `backend_adapter`) はすべて
``runner: Callable[..., AutoRietveldResult]`` を注入する設計なので、同じ形の関数を用意すれば
そのまま差し替えられる。

**revert の実現**: GSAS 経路は ``.gpx`` をファイルコピーして復元するが、TOPAS では
**文書がそのまま状態**なので、悪化した段は「その段を適用する前の `TopasDocument` に戻す」
だけでよい (追記型・上書きなし = P2 と整合)。

**失敗の扱い**: ``TopasRunError`` は例外のまま上げず ``rwp=inf`` に縮退させ、既存の
「悪化した段は revert」経路に載せる (不変条件「バックエンドの失敗は例外でなく chi2=inf に変換」)。
"""

from __future__ import annotations

import math
import re
import shutil
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from ..autorietveld.model import (
    AutoRietveldResult,
    HistogramSpec,
    PhaseSpec,
    RefinementStage,
    StageResult,
    ValidityReport,
)
from ..errors import TopasRunError
from ..store import Ledger
from .driver import run_tc
from .flags import apply_stage
from .inp import TopasDocument
from .instrument import histogram_to_topas
from .parse import TopasRecords, limit_hits_from_out, parse_out_metrics, parse_records
from .structure import structure_to_topas_phase

__all__ = ["run_topas_rietveld"]

_BACKEND = "topas"


def _build_document(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    workdir: Path,
    *,
    background_coeffs: int,
    max_cyc: int,
) -> TopasDocument:
    """入力仕様から初期 (何も解放していない) 文書を組む。"""
    from ..autorietveld.cif_normalize import read_structure_cif

    topas_phases = []
    for spec in phases:
        structure = read_structure_cif(spec.structure_path)
        topas_phases.append(structure_to_topas_phase(structure, spec.phase_name, spec=spec))
    from .inp import PhaseHistogramTerms
    from .instrument import tchz_line

    topas_hists = []
    for i, hist in enumerate(histograms):
        converted = histogram_to_topas(
            hist, workdir=workdir, index=i, background_coeffs=background_coeffs
        )
        if not hist.radiation.is_tof:
            # ピーク形状は**相ごと**に str ブロックへ置く (xdd 直下では TOPAS が解決できない)。
            peak = tchz_line(i)
            converted = converted.with_updates(
                phase_terms={
                    phase.phase_name: PhaseHistogramTerms(peak_type=peak)
                    for phase in topas_phases
                }
            )
        topas_hists.append(converted)
    return TopasDocument(
        histograms=tuple(topas_hists),
        phases=tuple(topas_phases),
        max_iterations=max(int(max_cyc), 1) * 100,
        results_path="results.txt",
    )


def _metrics(run_out: str, results_text: str) -> "tuple[float, float, int]":
    """(rwp, gof, n_params) を取り出す。``results.txt`` を優先し ``.out`` を補助に使う。

    **`r_wp` を使う** — `r_wp_dash` は背景差引きで GSAS の rwp と同スケールでない (実測)。
    """
    records = parse_records(results_text)
    metrics = dict(parse_out_metrics(run_out))
    rwp = records.scalars.get("r_wp", metrics.get("r_wp", float("inf")))
    gof = records.scalars.get("gof", metrics.get("gof", float("inf")))
    # 解放パラメータ数は .out の ``value`_esd`` 記法の個数で数える (esd が付くのは精密化した値)。
    from .parse import refined_values_from_out

    n_params = len(refined_values_from_out(run_out))
    return float(rwp), float(gof), int(n_params)


def run_topas_rietveld(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    recipe: "Sequence[RefinementStage] | None" = None,
    reference_cells: "dict[str, tuple[float, ...]] | None" = None,
    ledger: "Ledger | None" = None,
    max_cyc: int = 12,
    worsen_eps: float = 1e-6,
    background_coeffs: int = 6,
    keep_project: "str | None" = None,
    timeout: float = 1800.0,
    **_unsupported: object,
) -> AutoRietveldResult:
    """実構造の自動 Rietveld を **TOPAS** で実行する。

    `run_auto_rietveld` と同じ入出力契約 (段階解放 + 悪化段の revert + ledger)。

    :param keep_project: 指定すると作業ディレクトリ (INP/.out/results.txt) をここへ残す
    :returns: `AutoRietveldResult` (``backend="topas"``, ``gpx_path=""``)
    """
    from ..autorietveld.recipe import build_recipe

    stages = tuple(recipe) if recipe is not None else build_recipe(
        histograms, phases, background_coeffs=background_coeffs
    )

    with tempfile.TemporaryDirectory(prefix="tsumugin-topas-") as tmp:
        work = Path(tmp)
        doc = _build_document(
            histograms, phases, work, background_coeffs=background_coeffs, max_cyc=max_cyc
        )

        stage_results: list[StageResult] = []
        prev_rwp = float("inf")

        best_results = ""
        for index, stage in enumerate(stages):
            before = doc
            note = ""
            try:
                doc = apply_stage(doc, stage)
                run = run_tc(
                    doc.render(), workdir=work, basename=f"stage{index}", timeout=timeout
                )
                rwp, gof, n_params = _metrics(run.out_text, run.results_text)
                hits = limit_hits_from_out(run.out_text)
                if hits:
                    note = f"境界張り付き: {','.join(sorted(set(hits)))}"
            except (TopasRunError, Exception) as exc:  # noqa: BLE001
                # 【不変条件】: バックエンドの失敗は例外でなく rwp=inf に変換しガードレールへ。
                rwp, gof, n_params = float("inf"), float("inf"), 0
                note = f"{type(exc).__name__}: {exc}"[:200]
                run = None  # type: ignore[assignment]

            worsened = not math.isfinite(rwp) or rwp > prev_rwp + worsen_eps
            if worsened:
                doc = before  # revert = 段を適用する前の文書に戻すだけ
            else:
                prev_rwp = rwp
                if run is not None:
                    best_results = run.results_text

            stage_results.append(
                StageResult(
                    label=stage.label,
                    rwp=rwp,
                    gof=gof,
                    n_params=n_params,
                    converged=math.isfinite(rwp),
                    reverted=worsened,
                    note=note,
                )
            )
            if ledger is not None:
                ledger.append(
                    "m12_topas_stage",
                    {
                        "stage": stage.label,
                        "rwp": rwp if math.isfinite(rwp) else None,
                        "gof": gof if math.isfinite(gof) else None,
                        "n_params": n_params,
                        "reverted": worsened,
                        "note": note,
                        "backend": _BACKEND,
                    },
                )

        records = parse_records(best_results)
        weight_fractions = {
            name: value / 100.0 for name, (value, _) in records.keyed.get("wt_frac", {}).items()
        }
        final_rwp = prev_rwp if math.isfinite(prev_rwp) else float("inf")
        final_gof = next(
            (s.gof for s in reversed(stage_results) if not s.reverted), float("inf")
        )

        if keep_project:
            destination = Path(keep_project)
            destination.mkdir(parents=True, exist_ok=True)
            for item in work.iterdir():
                if item.is_file():
                    shutil.copyfile(item, destination / item.name)

        return AutoRietveldResult(
            stage_results=tuple(stage_results),
            final_rwp=final_rwp,
            final_gof=final_gof,
            refined_cells=_refined_cells(records, doc, reference_cells),
            validity=ValidityReport(passed=math.isfinite(final_rwp)),
            n_obs=_count_observations(histograms, work),
            phase_weight_fractions=weight_fractions,
            backend=_BACKEND,
            project_path=str(keep_project) if keep_project else "",
        )


_CELL_ORDER = ("a", "b", "c", "al", "be", "ga")
_DEFAULT_ANGLES = {"al": 90.0, "be": 90.0, "ga": 90.0}


def _refined_cells(
    records: TopasRecords,
    doc: TopasDocument,
    reference_cells: "Mapping[str, tuple[float, ...]] | None",
) -> "dict[str, tuple[float, float, float, float, float, float]]":
    """``Out()`` が吐いたセルレコードから精密化後セルを組む。

    従属軸 (``b =Get(a);``) は Out に出していないので、参照式から独立変数を引いて復元する。
    回収できなかった相は参照セルへフォールバックする (**空にしない** — validity ゲートが
    「取れなかった」と「動かなかった」を区別できなくなるため)。
    """
    cells = records.keyed.get("cell", {})
    resolved: dict[str, tuple[float, float, float, float, float, float]] = {}
    for phase in doc.phases:
        name = phase.phase_name
        values: dict[str, float] = {}
        for axis in phase.cell:
            record = cells.get(f"{name}/{axis}")
            if record is not None:
                values[axis] = record[0]
        if not values:
            continue
        for axis, param in phase.cell.items():
            if axis in values:
                continue
            if param.is_reference and param.expression:
                # ``Get(a)`` → 独立変数 a の精密化後値を使う。
                match = re.fullmatch(r"Get\((\w+)\)", param.expression.strip())
                if match and match.group(1) in values:
                    values[axis] = values[match.group(1)]
                    continue
            values[axis] = param.value
        resolved[name] = tuple(  # type: ignore[assignment]
            values.get(axis, _DEFAULT_ANGLES.get(axis, 0.0)) for axis in _CELL_ORDER
        )
    for name, cell in (reference_cells or {}).items():
        resolved.setdefault(name, tuple(cell))  # type: ignore[arg-type]
    return resolved


def _count_observations(histograms: Sequence[HistogramSpec], workdir: Path) -> int:
    """精密化に用いた観測点数 (レンジ制限・除外区間を反映)。

    TOPAS には点数を返す ``Get()`` キーが無いため、**自分で書き出した ``.xye``** から数える。
    BIC の dof に効くので 0 のままにしない。
    """
    total = 0
    for index, spec in enumerate(histograms):
        path = workdir / f"hist{index}.xye"
        if not path.is_file():
            continue
        x = np.array(
            [float(line.split()[0]) for line in path.read_text().splitlines() if line.strip()]
        )
        mask = np.ones(x.shape, dtype=bool)
        if spec.two_theta_limits is not None:
            low, high = spec.two_theta_limits
            mask &= (x >= low) & (x <= high)
        for low, high in spec.excluded_regions:
            mask &= ~((x >= low) & (x <= high))
        total += int(mask.sum())
    return total
