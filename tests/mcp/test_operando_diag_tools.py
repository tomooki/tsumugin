"""operando 診断 ② 薄い MCP 4 ツール (operando_diag_tools) の純テスト。

SDK 非依存・素の型 dict 応答・json.dumps(allow_nan=False) 安全・決定論を検証する
(docs/design/operando-diagnosis/architecture.md §2)。stub runner のパターンは
tests/insitu/test_repair.py・tests/mcp/test_insitu_tools.py に倣う。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.model import FrameRietveldResult, FrameSpec, SequentialRietveldResult
from tsumugin.mcp.insitu_tools import seq_result_to_dict
from tsumugin.mcp.operando_diag_tools import (
    OPERANDO_DIAG_TOOLS,
    assess_data_quality,
    check_phase_set,
    repair_frames,
    residual_report,
)
from tsumugin.mcp.tools import MCP_TOOLS

ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
GOOD_CELL = {"alpha": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)}


def _frame(i, rwp, fractions, *, cells=None, phase_names=None, refine_failed=False):
    cells = cells or {name: (5.0, 5.0, 5.0, 90.0, 90.0, 90.0) for name in fractions}
    names = phase_names if phase_names is not None else tuple(fractions)
    return FrameRietveldResult(
        frame_index=i,
        axis_value=float(i),
        data_path=f"f{i}.xrdml",
        rwp=rwp,
        gof=1.0,
        refined_cells=cells,
        phase_fractions=fractions,
        phase_names=names,
        refine_failed=refine_failed,
    )


def _autorietveld_result(rwp, cells, fractions, valid=True):
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells=cells,
        validity=ValidityReport(passed=valid),
        phase_fractions=fractions,
    )


def _base_frames(n=5):
    return [FrameSpec(data_path=f"f{i}.xrdml", axis_value=float(i)) for i in range(n)]


# ===========================================================================
# レジストリ
# ===========================================================================


def test_registry_has_four_tools():
    assert set(OPERANDO_DIAG_TOOLS) == {
        "assess_data_quality",
        "residual_report",
        "check_phase_set",
        "repair_frames",
    }


def test_operando_diag_tools_registered_in_mcp_tools():
    for name in OPERANDO_DIAG_TOOLS:
        assert MCP_TOOLS[name] is OPERANDO_DIAG_TOOLS[name]


# ===========================================================================
# assess_data_quality
# ===========================================================================


def _write_xy(tmp_path, x, y, esd=None, name="pattern.xy"):
    path = tmp_path / name
    with path.open("w", encoding="utf-8") as f:
        for i in range(len(x)):
            if esd is not None:
                f.write(f"{x[i]:.4f} {y[i]:.4f} {esd[i]:.4f}\n")
            else:
                f.write(f"{x[i]:.4f} {y[i]:.4f}\n")
    return str(path)


def test_assess_data_quality_detects_background_subtracted(tmp_path):
    rng = np.random.default_rng(0)
    x = np.linspace(5.0, 60.0, 400)
    y = np.zeros_like(x)
    for c in (15.0, 30.0, 45.0):
        y += 500.0 * np.exp(-0.5 * ((x - c) / 0.2) ** 2)
    # 背景減算済み: ピーク間はほぼ 0 (小さいノイズのみ)、esd=sqrt(強度) 慣習
    y = y + rng.normal(0.0, 0.5, size=x.size)
    y = np.maximum(y, 0.0)
    esd = np.sqrt(np.maximum(y, 1.0))
    path = _write_xy(tmp_path, x, y, esd)

    out = assess_data_quality(path)
    assert out["is_subtracted"] is True
    assert out["confidence"] > 0.5
    assert out["reasons"]
    assert out["suggested_two_theta_limit"] is not None
    json.dumps(out, allow_nan=False)


def test_assess_data_quality_raw_like_is_not_subtracted(tmp_path):
    rng = np.random.default_rng(1)
    x = np.linspace(5.0, 60.0, 400)
    # 生データ: 明確な背景 (低角で立ち上がる) + ピーク
    y = 200.0 + 50.0 * np.exp(-x / 30.0) * 10.0
    for c in (15.0, 30.0, 45.0):
        y += 500.0 * np.exp(-0.5 * ((x - c) / 0.2) ** 2)
    y = y + rng.normal(0.0, 5.0, size=x.size)
    path = _write_xy(tmp_path, x, y)

    out = assess_data_quality(path)
    assert out["is_subtracted"] is False
    json.dumps(out, allow_nan=False)


def test_assess_data_quality_missing_file_returns_error_dict(tmp_path):
    out = assess_data_quality(str(tmp_path / "nope.xy"))
    assert "error" in out
    assert "error_type" in out
    json.dumps(out, allow_nan=False)


def test_assess_data_quality_passes_excluded_regions(tmp_path):
    x = np.linspace(5.0, 60.0, 400)
    y = np.zeros_like(x)
    for c in (15.0, 30.0, 45.0):
        y += 500.0 * np.exp(-0.5 * ((x - c) / 0.2) ** 2)
    # 寄生ピークを 50-55° に追加
    y += 300.0 * np.exp(-0.5 * ((x - 52.0) / 0.2) ** 2)
    esd = np.sqrt(np.maximum(y, 1.0))
    path = _write_xy(tmp_path, x, y, esd)

    out_excluded = assess_data_quality(path, excluded_regions=[[49.0, 56.0]])
    out_plain = assess_data_quality(path)
    # 寄生ピークを除外すると上限がより低くなる (信号終端が押し出されない)
    assert out_excluded["suggested_two_theta_limit"] <= out_plain["suggested_two_theta_limit"]
    json.dumps(out_excluded, allow_nan=False)


# ===========================================================================
# residual_report
# ===========================================================================


def test_residual_report_happy_path():
    x = list(np.linspace(5.0, 60.0, 200))
    yobs = [100.0] * 200
    ycalc = [100.0] * 200
    # 未説明の欠落相ピークを 1 点だけ追加
    yobs[50] = 5000.0
    ycalc[50] = 100.0

    out = residual_report(x, yobs, ycalc)
    assert out["rwp"] is not None
    assert out["top_features"]
    assert out["top_features"][0]["two_theta"] == pytest.approx(x[50], abs=1e-6)
    assert out["top_features"][0]["residual"] > 0  # calc 不足
    json.dumps(out, allow_nan=False)


def test_residual_report_graceful_failure_on_length_mismatch():
    out = residual_report([1.0, 2.0, 3.0], [1.0, 2.0], [1.0, 2.0, 3.0])
    assert "error" in out
    assert out["error_type"] == "ValueError"
    json.dumps(out, allow_nan=False)


# ===========================================================================
# check_phase_set
# ===========================================================================


def test_check_phase_set_detects_missing_phase():
    frames = (
        _frame(0, 8.0, {"alpha": 0.6, "beta": 0.4}),
        _frame(1, 8.0, {"alpha": 0.6, "beta": 0.4}),
        _frame(2, 8.0, {"alpha": 1.0}, phase_names=("alpha",)),  # beta 欠落
        _frame(3, 8.0, {"alpha": 0.6, "beta": 0.4}),
        _frame(4, 8.0, {"alpha": 0.6, "beta": 0.4}),
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=frames))

    out = check_phase_set(result)
    assert out["is_complete"] is False
    assert set(out["union"]) == {"alpha", "beta"}
    assert [fi for fi, _ in out["frames_with_missing"]] == [2]
    assert out["frames_with_missing"][0][1] == ["beta"]
    phases_by_name = {p["phase"]: p for p in out["phases"]}
    assert set(phases_by_name) == {"alpha", "beta"}
    json.dumps(out, allow_nan=False)


def test_check_phase_set_complete_series():
    frames = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(4))
    result = seq_result_to_dict(SequentialRietveldResult(frames=frames))

    out = check_phase_set(result)
    assert out["is_complete"] is True
    assert out["frames_with_missing"] == []
    json.dumps(out, allow_nan=False)


def test_check_phase_set_flags_oscillating_fraction():
    fractions = [0.5, 0.15, 0.55, 0.1, 0.6, 0.05]
    frames = tuple(
        _frame(i, 8.0, {"tetra": f, "mono": 1.0 - f}) for i, f in enumerate(fractions)
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=frames))

    out = check_phase_set(result)
    tetra = next(p for p in out["phases"] if p["phase"] == "tetra")
    assert tetra["flagged"] is True
    assert tetra["turning_points"] > 2
    json.dumps(out, allow_nan=False)


# ===========================================================================
# repair_frames
# ===========================================================================


def test_repair_frames_adopts_when_runner_improves():
    frame_specs = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=fr_results))

    def runner(frame, phases, initial_cells):
        return _autorietveld_result(7.0, GOOD_CELL, {"alpha": 1.0})

    out = repair_frames(
        result,
        [f.to_dict() for f in frame_specs],
        [ALPHA.to_dict()],
        rwp_delta=1.8,
        runner=runner,
    )
    assert len(out["repairs"]) == 1
    rep = out["repairs"][0]
    assert rep["frame"] == 2
    assert rep["rwp_before"] == 15.0
    assert rep["rwp_after"] == 7.0
    assert out["needs_model_revision"] == []
    assert [d["frame"] for d in out["discontinuities"]] == [2]
    json.dumps(out, allow_nan=False)


def test_repair_frames_escalates_when_runner_does_not_improve():
    frame_specs = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=fr_results))

    def runner(frame, phases, initial_cells):
        return _autorietveld_result(16.0, GOOD_CELL, {"alpha": 1.0})

    out = repair_frames(
        result,
        [f.to_dict() for f in frame_specs],
        [ALPHA.to_dict()],
        rwp_delta=1.8,
        runner=runner,
    )
    assert out["repairs"] == []
    assert out["needs_model_revision"] == [2]
    json.dumps(out, allow_nan=False)


def test_repair_frames_no_discontinuities_is_a_noop():
    frame_specs = _base_frames(4)
    fr_results = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(4))
    result = seq_result_to_dict(SequentialRietveldResult(frames=fr_results))

    def runner(frame, phases, initial_cells):  # pragma: no cover - 呼ばれないはず
        raise AssertionError("discontinuity が無いので呼ばれないはず")

    out = repair_frames(
        result, [f.to_dict() for f in frame_specs], [ALPHA.to_dict()], runner=runner
    )
    assert out["repairs"] == []
    assert out["needs_model_revision"] == []
    assert out["discontinuities"] == []
    json.dumps(out, allow_nan=False)
