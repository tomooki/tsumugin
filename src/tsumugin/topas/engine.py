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
from ..autorietveld.stagepolicy import StageMetrics, decide_stage
from ..errors import TopasRunError
from ..store import Ledger
from .driver import run_tc
from .flags import apply_stage
from .inp import TopasDocument, _slug
from .instrument import histogram_to_topas
from .parse import TopasRecords, limit_hits_from_out, parse_out_metrics, parse_records
from .structure import BEQ_PER_UISO, structure_to_topas_phase, to_topas_spacegroup

__all__ = ["run_topas_rietveld"]

_BACKEND = "topas"


def _build_document(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    workdir: Path,
    *,
    background_coeffs: int,
    max_cyc: int,
    seed_profile: bool = False,
) -> TopasDocument:
    """入力仕様から初期 (何も解放していない) 文書を組む。"""
    from ..autorietveld.cif_normalize import read_structure_cif

    from .symmetry import ensure_symops

    topas_phases = []
    for spec in phases:
        structure = read_structure_cif(spec.structure_path)
        # 【対称操作の確保】: CIF が対称操作を持たないと座標を一切解放できない
        #   (判定できないものは触らない方針)。TOPAS は空間群を sgcom6 で展開して
        #   Sg/<sg>.sg に一般位置を書くので、そこから補完する (権威的な供給元)。
        sg = to_topas_spacegroup(structure.spacegroup_hm, structure.it_number)
        symops = ensure_symops(sg, structure.symops)
        topas_phases.append(
            structure_to_topas_phase(
                structure, spec.phase_name, spec=spec, symops=symops
            )
        )
    from .inp import PhaseHistogramTerms
    from .instrument import tchz_line

    topas_hists = []
    for i, hist in enumerate(histograms):
        converted = histogram_to_topas(
            hist,
            workdir=workdir,
            index=i,
            background_coeffs=background_coeffs,
            seed_profile=seed_profile,
        )
        if hist.radiation.is_tof:
            # TOF も**相ごと**にピーク形状を持つ (幅が d 依存なので相の微細構造で変わる)。
            from .instrument import read_instrument, tof_peak_type

            spec = read_instrument(hist.instrument_path)
            difc = spec.difc or 0.0
            # 【α/β は装置ファイルから写す】: 捨てると汎用初期値のピーク形状になり、
            #   **ピークはどこかに立つので tc.exe は正常終了し Rwp だけが悪い** (#179)。
            coeffs = spec.profile or {}
            converted = converted.with_updates(
                phase_terms={
                    phase.phase_name: PhaseHistogramTerms(
                        peak_type=tof_peak_type(
                            i,
                            difc=difc,
                            phase_key=_slug(phase.phase_name),
                            alpha=coeffs.get("alpha"),
                            beta0=coeffs.get("beta-0"),
                            beta1=coeffs.get("beta-1"),
                        )
                    )
                    for phase in topas_phases
                }
            )
        else:
            # ピーク形状は**相ごと**に str ブロックへ置く (xdd 直下では TOPAS が解決できない)。
            # 名前も相ごとに分ける — TOPAS のパラメータ名は大域なので、多相で同名を複数の
            # str ブロックへ宣言すると衝突する (全相が 1 つの形状を共有してしまう)。
            converted = converted.with_updates(
                phase_terms={
                    phase.phase_name: PhaseHistogramTerms(
                        peak_type=tchz_line(
                            i,
                            converted.profile_seed,
                            phase_key=_slug(phase.phase_name),
                        )
                    )
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


def _per_histogram_rwp(results_text: str) -> "dict[int, float]":
    """ヒストグラム索引 → その ``xdd`` だけの r_wp (診断用)。

    総合値だけでは**どちらのヒストグラムが悪いのか分からない**。joint では放射源ごとに
    当てはまりが大きく違うのが普通なので、内訳を残す。
    """
    records = parse_records(results_text)
    return {
        int(key[1:]): value
        for key, (value, _) in records.keyed.get("hist_rwp", {}).items()
        if key.startswith("h") and key[1:].isdigit()
    }


def _histogram_rwp_tuple(results_text: str, count: int) -> "tuple[float, ...]":
    """索引順の内訳。**1 本でも欠けたら空タプル**を返す (歯抜けを 0 と読ませない)。"""
    found = _per_histogram_rwp(results_text)
    if len(found) != count or any(i not in found for i in range(count)):
        return ()
    return tuple(found[i] for i in range(count))


def _metrics(run_out: str, results_text: str) -> "tuple[float, float, int]":
    """(rwp, gof, n_params) を取り出す。

    **総合指標は ``.out`` の先頭行から採る**。``results.txt`` の ``Out(Get(r_wp))`` は
    それが書かれた ``xdd`` ブロックの値でしかないため、joint では**第 1 ヒストグラムの
    r_wp を総合値と名乗る**ことになる (実 PbSO4 joint で 8.635 対 10.772)。そのまま使うと
    第 2 ヒストグラムが悪化していても段が受理される。単一ヒストグラムでは両者が一致する。

    ``.out`` が壊れているときだけ ``results.txt`` へ落ちる (段の判定は続けられる方がよい)。

    **`r_wp` を使う** — `r_wp_dash` は背景差引きで GSAS の rwp と同スケールでない (実測)。
    """
    records = parse_records(results_text)
    metrics = dict(parse_out_metrics(run_out))
    rwp = metrics.get("r_wp", records.scalars.get("r_wp", float("inf")))
    gof = metrics.get("gof", records.scalars.get("gof", float("inf")))
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
    seed_profile: bool = False,
    keep_project: "str | None" = None,
    timeout: float = 1800.0,
    stability: object | None = None,
) -> AutoRietveldResult:
    """実構造の自動 Rietveld を **TOPAS** で実行する。

    `run_auto_rietveld` と同じ入出力契約 (段階解放 + 悪化段の revert + ledger)。

    :param keep_project: 指定すると作業ディレクトリ (INP/.out/results.txt) をここへ残す
    :param stability: 安定性診断ゲート (`StabilityOptions`)。**TOPAS 経路は未実装**なので、
        非 None を渡されたら黙って捨てず ``ValidityReport.warnings`` と ledger に残す。
        黙って無視すると「ゲートを頼んだのに何も見ていない」が Rwp にも note にも現れない
        (本モジュールが `flags.UnsupportedStageFlagError` で避けているのと同じ病理)。
    :returns: `AutoRietveldResult` (``backend="topas"``, ``gpx_path=""``)
    """
    unsupported_warnings: list[str] = []
    if stability is not None:
        unsupported_warnings.append(
            "stability ゲート (WS-1/WS-2) は TOPAS バックエンド未実装のため適用していません。"
        )
        if ledger is not None:
            ledger.append(
                "m12_topas_unsupported",
                {"option": "stability", "backend": _BACKEND},
            )
    from .recipe import build_topas_recipe

    # 【既定は TOPAS 向け順序】: 共有の `build_recipe` は GSAS 向けに調整されており、
    #   TOPAS では格子より先にプロファイルを合わせないと収束しない (recipe.py の説明を参照)。
    stages = tuple(recipe) if recipe is not None else build_topas_recipe(
        histograms, phases, background_coeffs=background_coeffs
    )

    with tempfile.TemporaryDirectory(prefix="tsumugin-topas-") as tmp:
        work = Path(tmp)
        doc = _build_document(
            histograms,
            phases,
            work,
            background_coeffs=background_coeffs,
            max_cyc=max_cyc,
            seed_profile=seed_profile,
        )

        stage_results: list[StageResult] = []
        # 【直前の**受理済み**状態】: 段方針 (`autorietveld.stagepolicy`) は gof/母数も見る —
        #   「rwp・gof・n_params がビット同一で revert も立たない」段 = 無言 no-op の検出に要る。
        prev_rwp, prev_gof, prev_nvar = float("inf"), float("inf"), 0

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

            decision = decide_stage(
                StageMetrics(prev_rwp, prev_gof, prev_nvar),
                StageMetrics(rwp, gof, n_params),
                worsen_eps=worsen_eps,
            )
            worsened = decision.reverted
            if worsened:
                doc = before  # revert = 段を適用する前の文書に戻すだけ
            else:
                prev_rwp, prev_gof, prev_nvar = rwp, gof, n_params
                if run is not None:
                    best_results = run.results_text
            if decision.is_noop:
                # 【無言 no-op】: 段を適用したのに rwp/gof/母数がビット同一 = 何も精密化して
                #   いない。**revert はしない** (検出のみ) — 効かない理由 (解放先が無い /
                #   バックエンドの無言失敗) は Rwp からは区別できないので、区別できる事実
                #   として note と ledger に残す。T4 実測で S3/S5 がこの状態だった。
                note = f"{note}; 無言 no-op (指標がビット同一)" if note else (
                    "無言 no-op (指標がビット同一)"
                )

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
                        "revert_reason": decision.reason,
                        "noop": decision.is_noop,
                        "note": note,
                        "backend": _BACKEND,
                    },
                )

        records = parse_records(best_results)
        weight_fractions = {
            name: value / 100.0 for name, (value, _) in records.keyed.get("wt_frac", {}).items()
        }
        weight_fraction_esd = {
            name: (esd / 100.0 if esd is not None else None)
            for name, (_, esd) in records.keyed.get("wt_frac", {}).items()
        }
        # 【Scale 正規化の相分率】: `phase_fractions` は **Scale を和=1 に正規化した値**で、
        #   `phase_weight_fractions` (wt%) とは**相互変換できない別量** (model.py の注記:
        #   単位胞質量が相間で違うと乖離し、単一の換算係数は存在しない)。空のままにすると
        #   `search._fraction_disagreements` や insitu の受理判定が `.get(name, 0.0)` で 0 と
        #   読み、**相分率の不一致検査が静かに空振りする**。
        scale_values = {n: v for n, (v, _) in records.keyed.get("scale_val", {}).items()}
        scale_total = sum(scale_values.values())
        phase_fractions = (
            {n: v / scale_total for n, v in scale_values.items()} if scale_total > 0 else {}
        )
        atom_coords, atom_coord_esd = _atom_coord_maps(records)
        atom_occupancy, atom_occupancy_esd = _atom_scalar_maps(records, "occ")
        atom_beq, atom_beq_esd = _atom_scalar_maps(records, "beq")
        # TOPAS は B、結果契約は Uiso。**Uiso = B / 8π²** で戻す (取り違えると 79 倍ずれる)。
        atom_uiso = {
            ph: {lbl: v / BEQ_PER_UISO for lbl, v in vals.items()}
            for ph, vals in atom_beq.items()
        }
        atom_uiso_esd = {
            ph: {lbl: (v / BEQ_PER_UISO if v is not None else None) for lbl, v in vals.items()}
            for ph, vals in atom_beq_esd.items()
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

        refined_cells = refined_cells_from_records(records, doc, reference_cells)
        cell_strain, cell_strain_esd = _cell_strain_from_records(records)

        return AutoRietveldResult(
            stage_results=tuple(stage_results),
            final_rwp=final_rwp,
            final_gof=final_gof,
            refined_cells=refined_cells,
            validity=_validity(
                refined_cells=refined_cells,
                reference_cells=reference_cells,
                atom_uiso=atom_uiso,
                atom_occupancy=atom_occupancy,
                weight_fractions=weight_fractions,
                converged=math.isfinite(final_rwp),
                extra_warnings=tuple(unsupported_warnings),
            ),
            n_obs=_count_observations(histograms, work),
            phase_fractions=phase_fractions,
            phase_weight_fractions=weight_fractions,
            phase_weight_fraction_esd=weight_fraction_esd,
            cell_esd=_cell_esd_map(records, doc),
            atom_coords=atom_coords,
            atom_coord_esd=atom_coord_esd,
            atom_occupancy=atom_occupancy,
            atom_occupancy_esd=atom_occupancy_esd,
            atom_uiso=atom_uiso,
            atom_uiso_esd=atom_uiso_esd,
            cell_strain=cell_strain,
            cell_strain_esd=cell_strain_esd,
            backend=_BACKEND,
            project_path=str(keep_project) if keep_project else "",
            histogram_rwp=_histogram_rwp_tuple(best_results, len(histograms)),
        )


_CELL_ORDER = ("a", "b", "c", "al", "be", "ga")
_DEFAULT_ANGLES = {"al": 90.0, "be": 90.0, "ga": 90.0}


def _cell_strain_from_records(
    records: TopasRecords,
) -> "tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]":
    """``cell_strain`` レコードを (値, esd) の 相→``"<軸>_h<索引>"`` マップ 2 本へ畳む。

    **ε は per-histogram の量**なので索引をキーに残す (相名+軸だけだと joint で後勝ちになる)。
    **esd も運ぶ** — ε が ±0.002% なのか ±0.4% (未決定) なのかで意味が反転する。

    キーは ``<相名>/<軸>/h<索引>`` だが、**相名に ``/`` が入りうる**ので後ろ 2 つを軸と索引と
    見なし、残りを相名へ戻す (末尾から数える)。3 つ未満だけを壊れたレコードとして落とす。
    """
    values: dict[str, dict[str, float]] = {}
    esds: dict[str, dict[str, float]] = {}
    for key, (value, esd) in records.keyed.get("cell_strain", {}).items():
        parts = key.split("/")
        if len(parts) < 3:
            continue
        phase, axis, hist = "/".join(parts[:-2]), parts[-2], parts[-1]
        values.setdefault(phase, {})[f"{axis}_{hist}"] = value
        if esd is not None and math.isfinite(esd) and esd > 0.0:
            esds.setdefault(phase, {})[f"{axis}_{hist}"] = esd
    return values, esds


def refined_cells_from_records(
    records: TopasRecords,
    doc: TopasDocument,
    reference_cells: "Mapping[str, tuple[float, ...]] | None" = None,
) -> "dict[str, tuple[float, float, float, float, float, float]]":
    """``Out()`` が吐いたセルレコードから精密化後セルを組む。

    **`backends.topas.TopasBackend` も使う** (#180): 従属軸の解決を別実装で持つと、
    片方だけが「格子が動かなかった」ように見える結果を返すようになる。

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


def _atom_coord_maps(
    records: TopasRecords,
) -> "tuple[dict[str, dict[str, tuple[float, float, float]]], dict[str, dict[str, tuple]]]":
    """``coord`` レコード (相/ラベル/軸) を相→ラベル→(x,y,z) と同型の esd へ畳む。

    解放していない軸はレコードに現れない。**欠けた軸は 0.0 で埋めず ``None`` の esd を残す** —
    「対称固定で厳密に決まっている」と「この精密化では決まっていない」を読み分けられるように
    するため (GSAS 経路の 3 状態 esd と同じ規律)。
    """
    values: dict[str, dict[str, dict[str, float]]] = {}
    esds: dict[str, dict[str, dict[str, "float | None"]]] = {}
    for key, (value, esd) in records.keyed.get("coord", {}).items():
        parts = key.split("/")
        if len(parts) != 3:
            continue
        phase, label, axis = parts
        values.setdefault(phase, {}).setdefault(label, {})[axis] = value
        esds.setdefault(phase, {}).setdefault(label, {})[axis] = esd
    coords: dict[str, dict[str, tuple[float, float, float]]] = {}
    coord_esd: dict[str, dict[str, tuple]] = {}
    for phase, labels in values.items():
        for label, axes in labels.items():
            triple = tuple(axes.get(a, 0.0) for a in ("x", "y", "z"))
            coords.setdefault(phase, {})[label] = triple  # type: ignore[assignment]
            e = esds[phase][label]
            coord_esd.setdefault(phase, {})[label] = tuple(e.get(a) for a in ("x", "y", "z"))
    return coords, coord_esd


def _atom_scalar_maps(
    records: TopasRecords, kind: str
) -> "tuple[dict[str, dict[str, float]], dict[str, dict[str, float | None]]]":
    """``occ`` / ``beq`` レコードを相→ラベル→値 と同型の esd へ畳む。"""
    values: dict[str, dict[str, float]] = {}
    esds: dict[str, dict[str, "float | None"]] = {}
    for key, (value, esd) in records.keyed.get(kind, {}).items():
        phase, _, label = key.partition("/")
        if not label:
            continue
        values.setdefault(phase, {})[label] = value
        esds.setdefault(phase, {})[label] = esd
    return values, esds


def _cell_esd_map(
    records: TopasRecords, doc: TopasDocument
) -> "dict[str, tuple]":
    """``cell`` レコードの esd を GSAS 契約と同じ 6 要素 (a,b,c,al,be,ga) 順に並べる。

    従属軸 (``b =Get(a);``) は独立変数と同じ esd を持つ (同一パラメータだから)。
    出していない角は ``None`` (対称固定なので「決まっていない」ではなく「変数でない」)。
    """
    cells = records.keyed.get("cell", {})
    out: dict[str, tuple] = {}
    for phase in doc.phases:
        name = phase.phase_name
        per_axis: dict[str, "float | None"] = {}
        for axis, param in phase.cell.items():
            record = cells.get(f"{name}/{axis}")
            if record is not None:
                per_axis[axis] = record[1]
            elif param.is_reference and param.expression:
                match = re.fullmatch(r"Get\((\w+)\)", param.expression.strip())
                source = cells.get(f"{name}/{match.group(1)}") if match else None
                per_axis[axis] = source[1] if source else None
        if per_axis:
            out[name] = tuple(per_axis.get(a) for a in _CELL_ORDER)
    return out


def _validity(
    *,
    refined_cells: "Mapping[str, tuple[float, ...]]",
    reference_cells: "Mapping[str, tuple[float, ...]] | None",
    atom_uiso: "Mapping[str, Mapping[str, float]]",
    atom_occupancy: "Mapping[str, Mapping[str, float]]",
    weight_fractions: "Mapping[str, float]",
    converged: bool,
    extra_warnings: tuple[str, ...] = (),
) -> ValidityReport:
    """物理妥当性ゲート。**GSAS 経路と同じ `check_validity` を使う** (中立層の共用)。

    これを繋がないと「Rwp は下がったが Uiso が負・占有率が 1 超」という結果が**合格として
    返る**。実 fluoroapatite で実際にそうなった (占有率を全解放していた頃、Rwp 10.1 に見えて
    占有率 0.68-2.24)。精密化の良し悪しを Rwp だけで判定しないための要。
    """
    from ..autorietveld.validity import check_validity

    report = check_validity(
        refined_cells={k: tuple(v) for k, v in refined_cells.items()},
        reference_cells={k: tuple(v) for k, v in (reference_cells or {}).items()},
        # `check_validity` は相名→**値の並び**を取る (ラベルではなく添字で報告する既存契約)。
        uiso={ph: list(vals.values()) for ph, vals in atom_uiso.items()},
        occupancies={ph: list(vals.values()) for ph, vals in atom_occupancy.items()},
        # 【並びで渡す】: `check_validity` は相分率を**値の列**で取る。dict を渡すと
        #   ``sum()`` がキー (相名) を足そうとして TypeError になる。単相では和=1 検査が
        #   たまたま通り、**多相で初めて落ちる** (T4 NAC+CaF2 で露見)。
        phase_fractions=list(weight_fractions.values()) or None,
        converged=converged,
    )
    if extra_warnings:
        from dataclasses import replace as _replace

        report = _replace(report, warnings=(*report.warnings, *extra_warnings))
    return report
