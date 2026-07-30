"""TASK-0704/0705: engine.run_auto_rietveld を T1 fluoroapatite 実データで検証。

GSAS-II 必須 (@pytest.mark.gsas)。データ未取得時は自動 skip。
目標: チュートリアル Rwp 10.38% / GOF 3.44 と同等 (合格基準 Rwp ≤ 12%, GOF ≤ 4.5)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld

_DATA = Path("docs/benchmark/testdata/m7/labdata")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "FAP.XRA").exists() and (_DATA / "FAP.EXP").exists()


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_t1_labdata_reaches_tutorial_quality():
    hist = HistogramSpec(
        data_path=str(_DATA / "FAP.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )
    phase = PhaseSpec(
        structure_path=str(_DATA / "FAP.EXP"), phase_name="fap", format_hint="EXP"
    )
    result = run_auto_rietveld([hist], [phase])

    # 合格基準 (チュートリアル 10.38% / 3.44 と同等)
    assert result.final_rwp <= 12.0, f"Rwp={result.final_rwp}"
    assert result.final_gof <= 4.5, f"GOF={result.final_gof}"
    # 段階が単調に (概ね) 改善している
    assert result.stage_results[0].rwp > result.final_rwp
    # 物理的妥当性: 格子 fluoroapatite (a~9.37, c~6.89)
    a, b, c, al, be, ga = result.refined_cells["fap"]
    assert 9.30 < a < 9.45 and 6.80 < c < 6.95
    assert result.validity.passed, [c for c in result.validity.checks if not c[1]]


#: T1 既定経路の実測ベースライン。**ビット同一**で固定する。
#: 出典: `docs/benchmark/stable-auto-rietveld/2026-07-29-0912.md` (真の基準表) および
#: `...-1356.md` (PR 前最終確認) — 両者で完全一致。
_T1_BASELINE_RWP = 9.80617260074067


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_t1_default_route_is_bit_identical_to_the_measured_baseline():
    """★**観測者効果カナリア**: 既定経路は WS-0 の追加で 1 ビットも動かないこと。

    非トートロジー: WS-0 は結果へ座標/esd を足し、`m7_stage` に診断キーを足し、原子行の
    読み取りを共有モジュールへ移し、engine 入口に検証を足した。**どれも「観測を増やすだけ」
    のはずだが、診断層は過去に実際にフィットを壊している** — numpy 配列の真偽値評価で
    例外を投げ、段階ループの except が拾って **T1 の全段が chi2=inf → revert** した
    (Rwp を見ない限り「観測を足しただけ」に見える壊れ方だった)。

    10 案の比較は既定 (A0) を基準に組み立てるので、基準が動くと**全案の順位が無意味になる**。
    `pytest.approx` ではなくビット同一で固定するのは、丸めの外で静かにずれるのを許さないため
    (NFR-102 の再現性契約と同じ規律)。

    ⚠ このテストが落ちたら、まず「既定を変えたつもりが無いのに変わった」を疑うこと。
    意図的に既定を変える差分なら、T1-T4/CaTeO3 のベンチマーク再測定とセットで値を更新する。
    """
    hist = HistogramSpec(
        data_path=str(_DATA / "FAP.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )
    phase = PhaseSpec(
        structure_path=str(_DATA / "FAP.EXP"), phase_name="fap", format_hint="EXP"
    )

    result = run_auto_rietveld([hist], [phase], max_cyc=12)

    assert result.final_rwp == _T1_BASELINE_RWP, (
        f"既定経路の Rwp が動いた: {result.final_rwp!r} != {_T1_BASELINE_RWP!r}。"
        "WS-0 の追加は観測のみで、フィットを変えてはならない"
    )
    # 新フィールドが**実際に埋まっている**こと (空のまま素通りしていないことの対照)。
    assert result.atom_coords["fap"], "座標が抽出されていない"
    assert result.atom_coord_esd["fap"], "座標 esd が抽出されていない"
    assert any(
        any(e is not None and e > 0.0 for e in esd)
        for esd in result.atom_coord_esd["fap"].values()
    ), "解放した座標の esd が 1 つも取れていない (dAx の sig を引けていない疑い)"
