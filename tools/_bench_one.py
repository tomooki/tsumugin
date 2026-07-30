"""ベンチマーク 1 件を実行して JSON を 1 行 stdout に出す (`bench_recipes.py` の子プロセス)。

spec とレシピの定義は `bench_specs.py` に集約してある (このファイルには持たない) —
以前は spec がここにあり「gated テストと 1 対 1 で一致させること」というコメントだけで
担保されていた。

**別プロセスで動かす前提**: GSAS-II はグローバル状態を多く持つため、1 件 1 プロセスにして
並列化と隔離を同時に得る。親は stdout の**最終 JSON 行だけ**を読むので、出力は必ず 1 行にする
(段ごとの詳細は行に含めるが、`--out` を渡せば同じ payload をファイルにも書く)。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "tools"))

from bench_specs import (  # noqa: E402 — sys.path 調整後に import する必要がある
    DATA_ROOT,
    DATASETS,
    OBSERVE_ONLY_STABILITY,
    RECIPE_REGISTRY,
)


def _specs(dataset: str):
    """(histograms, phases, background_coeffs, max_cyc) を組む。"""
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation

    spec = DATASETS[dataset]
    bg, cyc = spec.background_coeffs, spec.max_cyc
    if dataset == "T1":
        d = DATA_ROOT / "m7/labdata"
        return ([HistogramSpec(data_path=str(d / "FAP.XRA"),
                               instrument_path=str(d / "INST_XRY.PRM"),
                               radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                               data_format="GSAS")],
                [PhaseSpec(structure_path=str(d / "FAP.EXP"), phase_name="fap",
                           format_hint="EXP")],
                bg, cyc)
    if dataset == "T2":
        d = DATA_ROOT / "m7/cwneutron"
        return ([HistogramSpec(data_path=str(d / "garnet.raw"),
                               instrument_path=str(d / "inst_d1a.prm"),
                               radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS")],
                [PhaseSpec(structure_path=str(d / "garnet_YFeAlO.cif"), phase_name="garnet",
                           format_hint="CIF",
                           mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")))],
                bg, cyc)
    if dataset == "T3":
        d = DATA_ROOT / "m7/cwcombined"
        return ([HistogramSpec(data_path=str(d / "PBSO4.XRA"),
                               instrument_path=str(d / "INST_XRY.PRM"),
                               radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                               data_format="GSAS", temperature=295.0),
                 HistogramSpec(data_path=str(d / "PBSO4.CWN"),
                               instrument_path=str(d / "inst_d1a.prm"),
                               radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS", temperature=10.0)],
                [PhaseSpec(structure_path=str(DATA_ROOT / "PbSO4-Wyckoff.cif"),
                           phase_name="PbSO4", format_hint="CIF")],
                bg, cyc)
    if dataset == "T4":
        d = DATA_ROOT / "m7/tofcw"
        return ([HistogramSpec(data_path=str(d / "11BM_NAC.fxye"),
                               instrument_path=str(d / "11bm_gsas.prm"),
                               radiation=Radiation.XRAY_SYNCHROTRON,
                               geometry=Geometry.DEBYE_SCHERRER,
                               data_format="FXYE", two_theta_limits=(3.0, 40.0)),
                 HistogramSpec(data_path=str(d / "PG3_22048.gsa"),
                               instrument_path=str(d / "POWGEN_1066.instprm"),
                               radiation=Radiation.NEUTRON_TOF,
                               geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS", bank=1,
                               two_theta_limits=(2000.0, 15000.0)),
                 HistogramSpec(data_path=str(d / "PG3_22049.gsa"),
                               instrument_path=str(d / "POWGEN_2665.instprm"),
                               radiation=Radiation.NEUTRON_TOF,
                               geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS", bank=1,
                               two_theta_limits=(2000.0, 30000.0))],
                [PhaseSpec(structure_path=str(d / "NAC.cif"), phase_name="NAC"),
                 PhaseSpec(structure_path=str(d / "CaF2.cif"), phase_name="CaF2")],
                bg, cyc)
    if dataset == "CaTeO3":
        from tsumugin.insitu.engine import _xrdml_to_xye

        d = DATA_ROOT / "m9/cateo3"
        tmp = Path(tempfile.mkdtemp(prefix="bench-cateo3-"))
        xye = tmp / "frame.xye"
        _xrdml_to_xye(str(d / "NB-LM01MO_030.XRDML"), str(xye))
        return ([HistogramSpec(data_path=str(xye),
                               instrument_path=str(d / "cateo3_CuKa.instprm"),
                               radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                               data_format="XYE", two_theta_limits=(12.0, 70.0))],
                [PhaseSpec(structure_path=str(d / "alpha_CaTeO3_H2O.cif"), phase_name="alpha")],
                bg, cyc)
    raise SystemExit(f"unknown dataset: {dataset}")


def _negative_cell_alone_recipe(hists, phases, bg):
    """N0 (負の対照): **既定レシピを変形**して S1 から変位を抜き、構造段の後へ回す。

    ⚠ **手組みの段列にしてはならない**。最初の実装は段列を一から書いており、T2 の
    ``occupancy`` 段 (混合占有アダプタ) と T3 の ``hydrostatic_strain`` (温度差 Dij) を
    落としていた。結果 T2 が 15.73% で壊れたが、それは**測ろうとしている順序の失敗ではなく
    アダプタの欠落**であり、対照として無意味になる (F1 の問いは「変位をいつ解放するか」
    だけ)。既定から**変位の位置だけ**を動かすことで他のアダプタは全部保たれる。

    F1 実測ではこの配置が T3 を 6.66 → **14.38% + 格子発散**にした。
    """
    from tsumugin.autorietveld.model import RefinementStage
    from tsumugin.autorietveld.recipe import _finalize, build_recipe

    base = build_recipe(hists, phases, background_coeffs=bg)
    moved = None
    stages: list[RefinementStage] = []
    for st in base:
        label = st.label.split(" ", 1)[1] if " " in st.label else st.label
        flags = dict(st.flags)
        if "displacement" in flags:
            moved = flags.pop("displacement")
            # 変位を抜いた残り (格子・Dij・多相のプロファイル併合) はその場に残す。
            stages.append(
                RefinementStage(
                    label=label.replace("+displacement", ""),
                    flags=flags,
                    note=st.note + " [N0: 変位を抜いて格子を単独解放]",
                )
            )
            continue
        stages.append(RefinementStage(label=label, flags=flags, note=st.note))
    if moved is None:  # 変位アダプタが無い構成 (対照にならないので既定のまま)
        return base
    # 構造段 (uiso) の直後へ差し込む — F1 の「…構造段… → 変位」配置。
    idx = next(
        (i + 1 for i, st in enumerate(stages) if st.label.endswith("uiso")), len(stages)
    )
    stages.insert(
        idx,
        RefinementStage(
            label="displacement",
            flags={"displacement": moved},
            note="★負の対照: 試料変位を構造段の後へ (F1 で T3 を壊した配置)",
        ),
    )
    return _finalize(stages, hists)


def _build(build, hists, phases, bg):
    """`RecipeBuild` → 段列 (+ 必要なら差し替えたヒストグラム)。"""
    from tsumugin.autorietveld.recipe import build_recipe, build_serious_recipe

    if build.builder == "serious":
        return build_serious_recipe(hists, phases, background_coeffs=bg,
                                    **build.recipe_kwargs), hists
    if build.builder == "negative_cell_alone":
        return _negative_cell_alone_recipe(hists, phases, bg), hists
    if build.builder == "default_autorange":
        # A4: レンジだけを自動判定した**別の観測集合**で回す。判定できなければ既定と同じ
        # ヒストグラムのままになる (= A0 と縮退するので選定の 0d で落ちる)。
        import dataclasses

        from tsumugin.autorietveld.autorange import suggest_two_theta_range
        from tsumugin.reference.io import load_pattern

        trimmed = []
        for h in hists:
            try:
                x, y = load_pattern(h.data_path, h.data_format)
                sug = suggest_two_theta_range(x, y)
                trimmed.append(
                    dataclasses.replace(h, two_theta_limits=(sug.lower, sug.upper))
                )
            except Exception:  # noqa: BLE001 — 読めない形式/TOF はレンジを変えない
                trimmed.append(h)
        return build_recipe(trimmed, phases, background_coeffs=bg,
                            **build.recipe_kwargs), trimmed
    return build_recipe(hists, phases, background_coeffs=bg, **build.recipe_kwargs), hists


def main() -> int:
    dataset, recipe_name = sys.argv[1], sys.argv[2]
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.model import StabilityOptions

    build = RECIPE_REGISTRY[recipe_name]
    hists, phases, bg, max_cyc = _specs(dataset)
    recipe, hists = _build(build, hists, phases, bg)
    # 観測列は全候補共通・ゲート列は候補の定義にあるものだけ (観測がフィットを変えない前提)。
    stability = StabilityOptions(**{**OBSERVE_ONLY_STABILITY, **build.stability})

    result = run_auto_rietveld(
        hists, phases, recipe=recipe,
        max_cyc=max(1, int(round(max_cyc * build.max_cyc_scale))),
        stability=stability,
    )
    payload = {
        "dataset": dataset,
        "recipe": recipe_name,
        "axis": build.axis,
        "rwp": float(result.final_rwp) if result.final_rwp == result.final_rwp else None,
        "gof": float(result.final_gof) if result.final_gof == result.final_gof else None,
        "n_obs": int(result.n_obs),
        "n_stages": len(result.stage_results),
        "n_reverted": sum(1 for s in result.stage_results if s.reverted),
        "validity": "pass" if result.validity.passed else "fail",
        "validity_failed_checks": [
            name for name, ok, _ in result.validity.checks if not ok
        ],
        "frozen_parameters": list(result.frozen_parameters),
        "final_polish_applied": bool(
            result.final_polish is not None and result.final_polish.applied
        ),
        "n_undetermined": len(result.undetermined_parameters),
        # 【段ごとの記録】: 「各ステップの結果を吟味する」の実体。最終 Rwp だけでは
        #   「どこで効いたか」「どこが無言で効かなかったか」が判らない。
        "stages": [
            {
                "index": i,
                "label": s.label,
                "rwp": float(s.rwp) if s.rwp == s.rwp else None,
                "gof": float(s.gof) if s.gof == s.gof else None,
                "n_params": int(s.n_params),
                "converged": s.converged,
                "reverted": bool(s.reverted),
                "note": s.note,
            }
            for i, s in enumerate(result.stage_results)
        ],
        # 【構造】: 一致判定の材料。親はこれを集めて `agreement` を後段で計算する。
        "refined_cells": {k: list(v) for k, v in result.refined_cells.items()},
        "cell_esd": {k: list(v) for k, v in result.cell_esd.items()},
        "atom_coords": {
            p: {lab: list(xyz) for lab, xyz in atoms.items()}
            for p, atoms in result.atom_coords.items()
        },
        "atom_coord_esd": {
            p: {lab: list(esd) for lab, esd in atoms.items()}
            for p, atoms in result.atom_coord_esd.items()
        },
        "atom_occupancy": {p: dict(v) for p, v in result.atom_occupancy.items()},
        "atom_occupancy_esd": {p: dict(v) for p, v in result.atom_occupancy_esd.items()},
        "atom_uiso": {p: dict(v) for p, v in result.atom_uiso.items()},
        "atom_uiso_esd": {p: dict(v) for p, v in result.atom_uiso_esd.items()},
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{dataset}-{recipe_name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    # ⚠ **必ず最後の 1 行**に出す (親は `{` で始まる最終行だけを読む)。
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
