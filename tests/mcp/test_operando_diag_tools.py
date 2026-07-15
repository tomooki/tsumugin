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


def test_assess_data_quality_xye_keeps_esd(tmp_path):
    """XYE は 3 列 ascii なので XY 同様 esd を保持する (J1 の主証拠は esd ケース)。"""
    x = np.linspace(5.0, 60.0, 400)
    y = np.zeros_like(x)
    for c in (15.0, 30.0, 45.0):
        y += 500.0 * np.exp(-0.5 * ((x - c) / 0.2) ** 2)
    esd = np.sqrt(np.maximum(y, 1.0))
    path = _write_xy(tmp_path, x, y, esd, name="pattern.xye")

    out = assess_data_quality(path, data_format="XYE")
    assert out["is_subtracted"] is True
    # esd を保持していれば「補助情報」の esd 注記が reasons に載る
    assert any("esd" in r for r in out["reasons"])
    json.dumps(out, allow_nan=False)


def test_assess_data_quality_rejects_single_column_file(tmp_path):
    """1 列ファイル (強度のみ) は 2 列ガードで弾く — 1 行ファイルと混同してはならない。"""
    path = tmp_path / "one_column.xy"
    path.write_text("100\n105\n102\n99\n101\n", encoding="utf-8")

    out = assess_data_quality(str(path))
    assert "error" in out
    assert out["error_type"] == "ValueError"
    # 3 個の数値が「1 点のパターン」として自信ありげに診断されてはならない
    assert "is_subtracted" not in out
    json.dumps(out, allow_nan=False)


def test_assess_data_quality_accepts_single_row_file(tmp_path):
    """正当な 1 行 3 列ファイルは引き続き読める (1 列ガードの巻き添えにしない)。"""
    path = tmp_path / "one_row.xy"
    path.write_text("10.0 500.0 22.3\n", encoding="utf-8")

    out = assess_data_quality(str(path))
    assert "error" not in out
    assert out["peak_max"] == pytest.approx(500.0)
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "regions",
    [
        [[10.0, 12.0, 14.0]],  # 3 要素
        [[10.0]],  # 1 要素
        [10.0],  # スカラ (区間でない)
        [[12.0, 10.0]],  # lo >= hi
        [["a", "b"]],  # 非数値
    ],
)
def test_assess_data_quality_bad_excluded_regions_returns_error_dict(tmp_path, regions):
    """LLM 由来の不正な excluded_regions は例外でなく error dict (module docstring の約束)。"""
    x = np.linspace(5.0, 60.0, 400)
    y = 100.0 + 500.0 * np.exp(-0.5 * ((x - 30.0) / 0.2) ** 2)
    path = _write_xy(tmp_path, x, y)

    out = assess_data_quality(path, excluded_regions=regions)
    assert "error" in out
    assert out["error_type"] == "ValueError"
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


def test_check_phase_set_malformed_result_returns_error_dict():
    """壊れた系列結果は例外でなく error dict (repair_frames と同じ縮退契約)。

    `frame_index` 欠落は以前 `_result_from_dict` の KeyError として現れたが、現在は前段の
    `_validate_seq_result` が必須キーの欠落として先に捕らえる (ValueError)。error dict へ縮退する
    という契約は不変で、error_type が具体化しただけ。
    """
    out = check_phase_set({"frames": [{"rwp": 8.0}]})  # frame_index 欠落
    assert "error" in out
    assert out["error_type"] == "ValueError"
    assert "frame_index" in out["error"]
    assert "is_complete" not in out
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"nope": 1}, id="frames キーが無い"),
        pytest.param({}, id="空 dict"),
        pytest.param({"frames": [], "phase_names": []}, id="frames が空"),
        pytest.param({"frames": [{"frame_index": 0}]}, id="必須フィールド欠落 (rwp/phase_names)"),
        pytest.param({"frames": "abc"}, id="frames が列でない"),
        pytest.param({"frames": [None]}, id="frame が dict でない"),
    ],
)
def test_check_phase_set_empty_or_malformed_result_is_never_clean(bad):
    """空/壊れた系列結果を「相集合は完全」と報告しない (J5 の最悪の失敗様態)。

    `frames` キーの無い dict は `_result_from_dict` で**例外にならず空の系列**へ復元されるため、
    ガードが働かず `is_complete=True`/`union=[]` の「無罪放免」が返っていた。③ に「相集合は
    完全だ」と告げることは、本設計が防ごうとしたまさにその失敗 (③ が疑うのをやめる) を招く。
    """
    out = check_phase_set(bad)
    assert "error" in out, f"空/壊れた入力が error dict にならない: {out}"
    assert out["error_type"]
    assert "is_complete" not in out, "壊れた入力から相集合の判定を返してはならない"
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


def test_repair_frames_rejects_phase_subset():
    """系列で使われている相が phases に無いと、黙って相を落として「修復成功」に見せてしまう。"""
    frame_specs = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 0.6, "beta": 0.4}, cells={"alpha": (5.0,) * 3 + (90.0,) * 3,
                                                         "beta": (6.0,) * 3 + (90.0,) * 3})
        for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=fr_results))

    def runner(frame, phases, initial_cells):  # pragma: no cover - 検証で弾かれ呼ばれないはず
        raise AssertionError("相集合が不完全なので精密化してはならない")

    out = repair_frames(
        result,
        [f.to_dict() for f in frame_specs],
        [ALPHA.to_dict()],  # beta が欠落
        rwp_delta=1.8,
        runner=runner,
    )
    assert "error" in out
    assert out["error_type"] == "ValueError"
    assert "beta" in out["error"]
    assert "repairs" not in out
    json.dumps(out, allow_nan=False)


def test_repair_frames_accepts_superset_of_phases():
    """phases が系列の相を包含していれば (余剰があっても) 通す。"""
    frame_specs = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL)
        for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=fr_results))
    extra = PhaseSpec(structure_path="beta.cif", phase_name="beta")

    def runner(frame, phases, initial_cells):
        return _autorietveld_result(7.0, GOOD_CELL, {"alpha": 1.0})

    out = repair_frames(
        result,
        [f.to_dict() for f in frame_specs],
        [ALPHA.to_dict(), extra.to_dict()],
        rwp_delta=1.8,
        runner=runner,
    )
    assert len(out["repairs"]) == 1


def test_repair_frames_frame_count_mismatch_returns_error_dict():
    """frames と result のフレーム数不一致は IndexError でなく error dict (docstring の約束)。"""
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL)
        for i, r in enumerate([8.0, 8.0, 8.0, 8.0, 15.0])
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=fr_results))

    def runner(frame, phases, initial_cells):  # pragma: no cover - 検証で弾かれ呼ばれないはず
        raise AssertionError("フレーム数不一致なので精密化してはならない")

    out = repair_frames(
        result,
        [f.to_dict() for f in _base_frames(3)],  # 3 != 5
        [ALPHA.to_dict()],
        rwp_delta=1.8,
        runner=runner,
    )
    assert "error" in out
    assert out["error_type"] == "ValueError"
    assert "3" in out["error"] and "5" in out["error"]
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"nope": 1}, id="frames キーが無い"),
        pytest.param({}, id="空 dict"),
        pytest.param({"frames": [], "phase_names": []}, id="frames が空"),
        pytest.param({"frames": [{"frame_index": 0}]}, id="必須フィールド欠落 (rwp/phase_names)"),
        pytest.param({"frames": "abc"}, id="frames が列でない"),
        pytest.param({"frames": [None]}, id="frame が dict でない"),
    ],
)
def test_repair_frames_empty_or_malformed_result_is_never_clean(bad):
    """空/壊れた系列結果を「不連続なし = 修復不要」と報告しない (check_phase_set と同じ縮退契約)。

    ``{"nope": 1}`` は空の系列へ復元され、フレーム数ガード (0 == 0) すら通り抜けて
    ``repairs=[]``/``needs_model_revision=[]`` の「異常なし」を返していた。
    """

    def runner(frame, phases, initial_cells):  # pragma: no cover - 検証で弾かれ呼ばれないはず
        raise AssertionError("壊れた入力で精密化してはならない")

    out = repair_frames(bad, [], [ALPHA.to_dict()], runner=runner)
    assert "error" in out, f"空/壊れた入力が error dict にならない: {out}"
    assert out["error_type"]
    assert "repairs" not in out, "壊れた入力から修復レポートを返してはならない"
    json.dumps(out, allow_nan=False)


def test_repair_frames_surfaces_ledger_entries():
    """P2 非破壊 — repair の採用/棄却が ledger エントリとして返り値に現れる。"""
    frame_specs = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL)
        for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
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
    entries = out["ledger_entries"]
    assert [e["kind"] for e in entries] == ["insitu_repair_adopted"]
    assert entries[0]["frame"] == 2
    assert entries[0]["rwp_before"] == 15.0
    assert entries[0]["rwp_after"] == 7.0
    json.dumps(out, allow_nan=False)


def test_repair_frames_ledger_records_rejection():
    """改善しなかった試行も ledger に残る (監査可能性)。"""
    frame_specs = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL)
        for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
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
    assert [e["kind"] for e in out["ledger_entries"]] == ["insitu_repair_rejected"]
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


# ===========================================================================
# G2: repair_frames の instrument spec / two_theta_limits (§4.5 到達可能性 #2)
# ===========================================================================


def _repair_inputs(n=5):
    frame_specs = _base_frames(n)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL)
        for i, r in enumerate([8.0, 8.0, 15.0] + [8.0] * (n - 3))
    )
    result = seq_result_to_dict(SequentialRietveldResult(frames=fr_results))
    return result, [f.to_dict() for f in frame_specs], [ALPHA.to_dict()]


def _capture_make_runner(monkeypatch):
    captured: dict[str, object] = {}

    def fake_make(**kwargs):
        captured.update(kwargs)

        def runner(frame, phases, initial_cells, initial_fractions=None):
            return _autorietveld_result(7.0, GOOD_CELL, {"alpha": 1.0})

        captured["runner"] = runner
        return runner

    monkeypatch.setattr("tsumugin.insitu.engine.make_gsas_runner", fake_make)
    return captured


def test_repair_frames_instrument_spec_builds_runner(monkeypatch):
    """instrument spec (JSON) からサーバ側で runner を組み立てる (③ の唯一の実運用経路)。"""
    from tsumugin.autorietveld.model import Geometry, Radiation

    made = _capture_make_runner(monkeypatch)
    result, frames, phases = _repair_inputs()

    out = repair_frames(
        result, frames, phases,
        instrument={
            "path": "sr.instprm",
            "radiation": "xray_synchrotron",
            "geometry": "debye_scherrer",
            "background_coeffs": 18,
            "max_cyc": 20,
            "auto_freeze_minor_cells": 0.2,
        },
        two_theta_limits=[2.0, 18.0],
    )

    assert made["instrument_path"] == "sr.instprm"
    assert made["radiation"] is Radiation.XRAY_SYNCHROTRON
    assert made["geometry"] is Geometry.DEBYE_SCHERRER
    assert made["background_coeffs"] == 18
    assert made["max_cyc"] == 20
    assert made["auto_freeze_minor_cells"] == pytest.approx(0.2)
    # (a) 修復試行を系列と**同じレンジ**で行う: Rwp 比較が同一データ域で成立する
    assert made["two_theta_limits"] == (2.0, 18.0)
    assert len(out["repairs"]) == 1
    json.dumps(out, allow_nan=False)


def test_repair_frames_instrument_paths_per_frame(monkeypatch):
    """paths (frames と 1:1) から フレーム→instprm の解決関数が組まれる (insitu_tools と同一ヘルパ)。"""
    made = _capture_make_runner(monkeypatch)
    result, frames, phases = _repair_inputs(3)

    repair_frames(
        result, frames, phases,
        instrument={"paths": ["a.instprm", "b.instprm", "c.instprm"]},
    )
    resolver = made["instrument_path"]
    assert callable(resolver)
    assert resolver(FrameSpec(data_path="f1.xrdml", axis_value=1.0)) == "b.instprm"


def test_repair_frames_two_theta_limits_reach_default_runner(monkeypatch):
    """instrument 未指定でも two_theta_limits は既定 runner の SequentialConfig へ届く。"""
    made = _capture_make_runner(monkeypatch)
    result, frames, phases = _repair_inputs()

    repair_frames(result, frames, phases, two_theta_limits=[2.0, 18.0])
    assert made["two_theta_limits"] == (2.0, 18.0)


def test_repair_frames_explicit_runner_overrides_instrument(monkeypatch):
    """runner= 明示注入は instrument より優先 (sequential_rietveld と同じ優先順)。"""
    def boom(**kwargs):
        raise AssertionError("runner= 注入時は make_gsas_runner を呼んではいけない")

    monkeypatch.setattr("tsumugin.insitu.engine.make_gsas_runner", boom)
    result, frames, phases = _repair_inputs()

    def runner(frame, phases_, initial_cells):
        return _autorietveld_result(7.0, GOOD_CELL, {"alpha": 1.0})

    out = repair_frames(result, frames, phases, runner=runner,
                        instrument={"path": "sr.instprm", "radiation": "xray_synchrotron"})
    assert len(out["repairs"]) == 1


def test_repair_frames_auto_freeze_bool_rejected(monkeypatch):
    """auto_freeze_minor_cells は float 閾値 (#80)。bool true = 全相凍結の罠なので拒否 (共有ガード)。"""
    _capture_make_runner(monkeypatch)
    result, frames, phases = _repair_inputs()

    out = repair_frames(result, frames, phases,
                        instrument={"path": "x.instprm", "auto_freeze_minor_cells": True})
    assert out["error_type"] == "ValueError"
    assert "threshold" in out["error"]
    assert "repairs" not in out
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "spec",
    [
        {"path": "x.instprm", "radiation": "synchrotron"},
        {"path": "x.instprm", "geometry": "capillary"},
        {"radiation": "xray_lab"},
    ],
)
def test_repair_frames_bad_instrument_spec_returns_error_dict(monkeypatch, spec):
    _capture_make_runner(monkeypatch)
    result, frames, phases = _repair_inputs()

    out = repair_frames(result, frames, phases, instrument=spec)
    assert out["error_type"] == "ValueError"
    assert "repairs" not in out
    json.dumps(out, allow_nan=False)


def test_repair_frames_bad_two_theta_limits_returns_error_dict():
    """two_theta_limits の要素数不正は例外でなく error dict (境界を例外が貫かない)。"""
    result, frames, phases = _repair_inputs()

    def runner(frame, phases_, initial_cells):
        return _autorietveld_result(7.0, GOOD_CELL, {"alpha": 1.0})

    out = repair_frames(result, frames, phases, two_theta_limits=[2.0], runner=runner)
    assert out["error_type"] == "ValueError"
    assert "two_theta_limits" in out["error"]
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    ("label", "args", "kwargs"),
    [
        ("None 入力", (None, None, None), {}),
        ("スカラ入力", (5.0, 5.0, 5.0), {}),
        ("dict 混入", ({"a": 1}, [1.0, 2.0], [1.0, 2.0]), {}),
        ("n_bins 型不正", ([1.0, 2.0, 3.0], [10.0, 20.0, 30.0], [9.0, 19.0, 29.0]), {"n_bins": "x"}),
    ],
)
def test_residual_report_malformed_input_returns_error_dict(label, args, kwargs):
    """residual_report も「例外を送出しない」契約を守ること (兄弟 3 ツールと同じ)。

    ``ValueError`` しか捕捉しておらず ``IndexError``/``TypeError`` が MCP 境界を貫いていた。
    ``server.py:_call_tool`` は ``fn(**kwargs)`` を素通しするため、③ は回復不能なハード失敗を受ける。
    """
    out = residual_report(*args, **kwargs)
    assert "error" in out, f"{label}: 例外が境界を越えた (error dict へ縮退していない)"
    assert "error_type" in out
    json.dumps(out, allow_nan=False)


def test_residual_report_empty_arrays_is_never_a_perfect_fit():
    """空配列は rwp=0.0 (完璧なフィット) でなくエラーであること。

    J5 の garbage→"clean" と同型の最悪の失敗形: 「何も渡さなかったので残差ゼロ」は
    ③ が疑うのをやめる根拠になり得る。
    """
    out = residual_report([], [], [])
    assert "error" in out, f"空配列が完璧なフィットとして返った: {out}"
    assert out.get("rwp") is None


def test_check_phase_set_error_does_not_suggest_an_impossible_chain():
    """`frames` 欠落エラーの案内が、実際に通る手順のみを示すこと。

    旧メッセージは「repair_frames が返す系列結果を渡せ」と案内していたが、`repair_frames` の
    戻り値に `frames` キーは無い (repairs/needs_model_revision のみ, architecture.md §2)。
    案内に従うと**同じエラーを再生産する** — ③ が回復できない自己矛盾した指示だった。
    """
    out = check_phase_set({"nope": 1})
    assert out["error_type"] == "ValueError"
    msg = out["error"]
    assert "sequential_rietveld" in msg, "実際に通る入力元を案内していない"
    assert "渡せません" in msg, "repair_frames の戻り値が渡せないことを案内していない"
