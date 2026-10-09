"""既定経路のゴールデン (fit-then-judge P1a タスク 0)。

P1a の engine の部品は**すべて opt-in で、既存経路はビット同一**を約束する
(`docs/tasks/fit-then-judge/p1a.md`)。その約束を検査するのが本テストである。既存の T1 カナリア
(`test_engine_t1.py`) は最終 Rwp の 1 値しか固定していないので、**段列・格子・座標・esd・Uiso・
相分率まで含む指紋**を採り、変更前のコードで採取した値とビット比較する。

**環境の指紋が一致するときだけ比較する**。浮動小数の縮約順序は Python/numpy (同梱 BLAS)/
GSAS-II の版で変わり得るので、別環境での不一致は「コードが変わった」証拠にならない。
環境が違えば skip し、理由に差分を出す (黙って通さない)。採り直しは

    TSUMUGIN_GOLDEN_CAPTURE=1 uv run pytest -m gsas tests/autorietveld/test_golden_default_routes.py

で行う。**採り直してよいのは「既定経路の数値を意図的に変える差分」のときだけ** — その場合は
T1-T4/CaTeO3 のベンチマーク再測定とセットにする (T1 カナリアと同じ規律)。

使うデータは公開チュートリアル (GSAS-II T1 fluoroapatite・Jana2020 CaTeO3) のみ。
"""

from __future__ import annotations

import json
import os
import platform
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation

pytestmark = pytest.mark.gsas

_GOLDEN = Path(__file__).parent / "golden" / "default_routes.json"
_T1 = Path("docs/benchmark/testdata/m7/labdata")
_CATEO3 = Path("docs/benchmark/testdata/m9/cateo3")


def _jsonable(obj: object) -> object:
    """Mapping/tuple を JSON の dict/list へ。浮動小数は repr で往復するのでそのまま渡す。"""
    if isinstance(obj, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (tuple, list)):
        return [_jsonable(v) for v in obj]
    return obj


def fingerprint(result: object) -> dict:
    """結果の**フィットの数値**だけを取り出す (観測用の注記・新設フィールドは含めない)。

    含めないもの: 段の ``note`` (文言は変わってよい)・P1a が足す観測フィールド
    (revert 理由・積分強度など)。それらは「観測を足すだけ」で、フィットではないから。
    """
    return {
        "final_rwp": result.final_rwp,
        "final_gof": result.final_gof,
        "stages": [
            [s.label, s.rwp, s.gof, s.n_params, s.converged, s.reverted]
            for s in result.stage_results
        ],
        "cells": _jsonable(result.refined_cells),
        "coords": _jsonable(result.atom_coords),
        "coord_esd": _jsonable(result.atom_coord_esd),
        "uiso": _jsonable(result.atom_uiso),
        "occupancy": _jsonable(result.atom_occupancy),
        "phase_fractions": _jsonable(result.phase_fractions),
    }


def environment_fingerprint() -> dict:
    """ビット比較が意味を持つ条件 (縮約順序を左右するもの)。"""
    import numpy
    from GSASII import GSASIIpath

    return {
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "gsas2": str(GSASIIpath.GetVersionNumber()),
        "machine": platform.machine(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS"),
    }


def _run_t1() -> object:
    from tsumugin.autorietveld.engine import run_auto_rietveld

    hist = HistogramSpec(
        data_path=str(_T1 / "FAP.XRA"),
        instrument_path=str(_T1 / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )
    phase = PhaseSpec(structure_path=str(_T1 / "FAP.EXP"), phase_name="fap", format_hint="EXP")
    return run_auto_rietveld([hist], [phase], max_cyc=12)


def _run_cateo3_frame030() -> object:
    from tsumugin.insitu import FrameSpec, make_gsas_runner

    runner = make_gsas_runner(
        instrument_path=str(_CATEO3 / "cateo3_CuKa.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        max_cyc=20,
        background_coeffs=24,
    )
    frame = FrameSpec(
        str(_CATEO3 / "NB-LM01MO_030.XRDML"),
        axis_value=30.0,
        data_format="XRDML",
        two_theta_limits=(12.0, 70.0),
    )
    alpha = PhaseSpec(str(_CATEO3 / "alpha_CaTeO3_H2O.cif"), "alpha", format_hint="CIF")
    return runner(frame, [alpha], None)


_ROUTES = {
    "t1_default": (_run_t1, (_T1 / "FAP.XRA", _T1 / "FAP.EXP", _T1 / "INST_XRY.PRM")),
    "cateo3_frame030_default": (
        _run_cateo3_frame030,
        (
            _CATEO3 / "NB-LM01MO_030.XRDML",
            _CATEO3 / "alpha_CaTeO3_H2O.cif",
            _CATEO3 / "cateo3_CuKa.instprm",
        ),
    ),
}


def _load_golden() -> dict:
    if not _GOLDEN.exists():
        return {}
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_default_route_matches_golden_bit_for_bit(
    route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, inputs = _ROUTES[route]
    # 既定経路のまま (成果物の保存も既定どおり) 走らせ、置き場所だけ一時ディレクトリへ逃がす。
    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path))
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        pytest.skip(f"公開ベンチのデータ未取得: {missing}")

    env = environment_fingerprint()
    capture = os.environ.get("TSUMUGIN_GOLDEN_CAPTURE") == "1"
    golden = _load_golden()

    if not capture:
        if route not in golden:
            pytest.fail(f"ゴールデン {route!r} が未採取 ({_GOLDEN})。変更前のコードで採取すること")
        if golden[route]["environment"] != env:
            pytest.skip(
                "環境が採取時と違うのでビット比較は意味を持たない: "
                f"採取時 {golden[route]['environment']} / 現在 {env}"
            )

    result = run()
    fp = fingerprint(result)
    # 非トートロジー: 指紋が空のまま一致するのを防ぐ (抽出が壊れても「一致」してしまう)。
    assert fp["stages"] and fp["cells"] and fp["coords"], f"指紋が空: {fp}"
    # P1a タスク 5: 相ごとの積分計算強度が埋まり、正の有限値であること。
    for name, values in result.phase_integrated_intensity.items():
        assert values and all(v is not None and v > 0 for v in values), (name, values)
    assert set(result.phase_integrated_intensity) == set(result.refined_cells)
    # P1a タスク 6: 公開チュートリアルの構造では座標の自由度の食い違いは無い。
    assert result.coordinate_freedom_mismatches == {}, result.coordinate_freedom_mismatches
    # P1a タスク 1 の観測の整合: GSAS 経路は revert 理由を必ず記録する (受理なら None)。
    for s in result.stage_results:
        assert (s.revert_reason is not None) == bool(s.reverted), (
            f"段 {s.label!r}: reverted={s.reverted} なのに revert_reason={s.revert_reason!r}"
        )

    if capture:
        golden[route] = {"environment": env, "fingerprint": _jsonable(fp)}
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(
            json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return

    expected = golden[route]["fingerprint"]
    actual = json.loads(json.dumps(_jsonable(fp)))  # 保存時と同じ正規化 (tuple→list, キー整列)
    assert actual == expected, (
        f"既定経路 {route!r} のフィットが変わった。P1a の部品は opt-in でビット同一を約束している。"
        "意図的に既定を変える差分なら、ベンチマーク再測定とセットでゴールデンを採り直すこと"
    )
