"""AutoRietveldResult の不確かさフィールド (esd / 重量分率) の純データ検証。

出版可能な Rietveld 結果には標準不確かさ (esd) が必須。また `phase_fractions` は HAP Scale の
和=1 正規化であって**重量分率ではない** (単位胞質量が相間で異なると大きく乖離する) ため、
GSAS-II の `calcMassFracs` 由来の重量分率を別フィールドとして持つ。

信頼性: 🔵 GSAS-II `G2Phase.get_cell_and_esd` / `G2PwdrData.ComputeMassFracs` の契約に対応。
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from tsumugin.autorietveld import AutoRietveldResult, StageResult, ValidityReport


def _result(**kwargs: object) -> AutoRietveldResult:
    """最小構成の AutoRietveldResult を組み立てる (既存構築サイトと同じ引数のみ)。"""
    base: dict[str, object] = {
        "stage_results": (
            StageResult(label="S1", rwp=8.0, gof=1.4, n_params=10, converged=True),
        ),
        "final_rwp": 8.0,
        "final_gof": 1.4,
        "refined_cells": {"cubic": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)},
        "validity": ValidityReport(passed=True),
    }
    base.update(kwargs)
    return AutoRietveldResult(**base)  # type: ignore[arg-type]


def test_uncertainty_fields_default_to_empty_for_back_compat():
    """既存の構築サイト (insitu/anchor 等) は新フィールドを渡さない → 空 map に縮退する。"""
    res = _result()
    assert res.cell_esd == {}
    assert res.phase_weight_fractions == {}
    assert res.phase_weight_fraction_esd == {}


def test_cell_esd_layout_matches_refined_cells():
    """cell_esd は refined_cells と同一レイアウト (a,b,c,α,β,γ の 6 要素; 体積を含まない)。"""
    res = _result(
        refined_cells={"cubic": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)},
        cell_esd={"cubic": (0.0012, 0.0012, 0.0012, 0.0, 0.0, 0.0)},
    )
    assert set(res.cell_esd) == set(res.refined_cells)
    for name, esd in res.cell_esd.items():
        assert len(esd) == len(res.refined_cells[name]) == 6


def test_weight_fractions_are_distinct_from_phase_fractions():
    """phase_fractions (Scale 正規化) と phase_weight_fractions (質量重み) は別物として保持される。"""
    res = _result(
        phase_fractions={"cubic": 0.5, "tetra": 0.5},
        phase_weight_fractions={"cubic": 0.68, "tetra": 0.32},
        phase_weight_fraction_esd={"cubic": 0.01, "tetra": 0.01},
    )
    assert res.phase_fractions != res.phase_weight_fractions
    assert sum(res.phase_weight_fractions.values()) == pytest.approx(1.0)


def test_result_is_frozen_and_replace_preserves_new_fields():
    """frozen + dataclasses.replace による非破壊更新で新フィールドが保たれる。"""
    res = _result(cell_esd={"cubic": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)})
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.cell_esd = {}  # type: ignore[misc]
    updated = dataclasses.replace(res, final_rwp=7.0)
    assert updated.final_rwp == pytest.approx(7.0)
    assert updated.cell_esd == res.cell_esd


def test_uncertainty_fields_are_json_safe():
    """MCP 境界を跨げるよう素の型 (str キー / float 値 / list) へ落ちること。"""
    res = _result(
        cell_esd={"cubic": (0.0012, 0.0012, 0.0012, 0.0, 0.0, 0.0)},
        phase_weight_fractions={"cubic": 0.68},
        phase_weight_fraction_esd={"cubic": 0.01},
    )
    payload = {
        "cell_esd": {k: list(v) for k, v in res.cell_esd.items()},
        "phase_weight_fractions": dict(res.phase_weight_fractions),
        "phase_weight_fraction_esd": dict(res.phase_weight_fraction_esd),
    }
    assert json.loads(json.dumps(payload)) == payload


def test_weight_fraction_esd_accepts_none_and_is_json_safe():
    """★レビュー第6巡: 多相で未決定の重量分率 esd は ``None`` を保持し JSON では null に落ちる。

    ``None`` = 「この精密化からは決まっていない」(捏造の 0.0 と別物)。単相の 0.0 (真の陳述) と
    多相の None が**同一フィールドで共存**できること。
    """
    res = _result(
        phase_weight_fractions={"mono": 0.71, "cubic": 0.29},
        phase_weight_fraction_esd={"mono": None, "cubic": None},
    )
    assert res.phase_weight_fraction_esd == {"mono": None, "cubic": None}
    payload = {"esd": dict(res.phase_weight_fraction_esd)}
    assert json.loads(json.dumps(payload)) == {"esd": {"mono": None, "cubic": None}}
