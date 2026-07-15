"""M9 薄い MCP 3 ツール (insitu_tools) の純テスト (stub runner/finder, GSAS/MP 非依存)。

SDK 非依存・素の型 dict 応答・json.dumps(allow_nan=False) 安全・決定論を検証する。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.model import FrameSpec
from tsumugin.mcp.insitu_tools import (
    INSITU_TOOLS,
    parametric_fit,
    sequential_rietveld,
)


def _result(rwp, cells, fracs, valid=True):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=1.0, refined_cells=cells,
        validity=ValidityReport(passed=valid), phase_fractions=fracs,
    )


def test_registry_has_three_tools():
    assert set(INSITU_TOOLS) == {"sequential_rietveld", "identify_and_add_phase", "parametric_fit"}


def test_sequential_rietveld_structured_output_json_safe():
    frames = [FrameSpec(f"f{i}.xrdml", axis_value=300.0 + 20 * i).to_dict() for i in range(3)]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    out = sequential_rietveld(frames, initial, runner=runner, reason="test")
    assert out["phase_names"] == ["alpha"]
    assert len(out["frames"]) == 3
    assert out["frames"][0]["rwp"] == 9.0
    assert out["appearances"] == []
    # json 安全 (allow_nan=False)
    json.dumps(out, allow_nan=False)


def test_sequential_rietveld_reports_appearance():
    frames = [FrameSpec(f"f{i}.xrdml", axis_value=300.0 + 20 * i).to_dict() for i in range(3)]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]
    delta = PhaseSpec("delta.cif", "new_delta")

    n = {"i": 0}

    def runner(frame, phases, initial_cells):
        names = [p.phase_name for p in phases]
        if "new_delta" in names:
            return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_delta": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_delta": 0.4})
        i = n["i"]
        n["i"] += 1
        return _result(9.0 if i < 2 else 22.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir, known_phases=()):
        return [(delta, {"source": "materials_project", "dara_score": 0.5})]

    out = sequential_rietveld(
        frames, initial, phase_id={"elements": ["Ca", "Te", "O"], "frac_min": 0.02},
        runner=runner, phase_finder=finder,
    )
    assert len(out["appearances"]) == 1
    ap = out["appearances"][0]
    assert ap["phase_name"] == "new_delta"
    assert ap["frame_index"] == 2
    assert ap["evidence"]["dara_score"] == 0.5
    json.dumps(out, allow_nan=False)


# --- Issue #93: JSON 境界から実運用設定 (装置/背景/#80/#82) に到達できるか -----------------------


def _capture_seq(monkeypatch):
    """run_sequential_rietveld を捕捉スタブに差し替え、captured dict を返す。"""
    captured: dict[str, object] = {}

    def fake_run(frames, phases, *, config=None, runner=None, phase_finder=None, workdir=None):
        captured["frames"] = list(frames)
        captured["phases"] = list(phases)
        captured["config"] = config
        captured["runner"] = runner
        captured["workdir"] = workdir
        from tsumugin.insitu.model import SequentialRietveldResult

        return SequentialRietveldResult(frames=(), phase_names=("alpha",))

    monkeypatch.setattr("tsumugin.insitu.engine.run_sequential_rietveld", fake_run)
    return captured


def _capture_make_runner(monkeypatch):
    """make_gsas_runner を捕捉スタブに差し替え、captured dict を返す。"""
    captured: dict[str, object] = {}

    def fake_make(**kwargs):
        captured.update(kwargs)

        def runner(frame, phases, initial_cells, initial_fractions=None):
            return _result(9.0, {}, {})

        captured["runner"] = runner
        return runner

    monkeypatch.setattr("tsumugin.insitu.engine.make_gsas_runner", fake_make)
    return captured


def _frames_and_phases(n=2):
    frames = [FrameSpec(f"f{i}.xye", data_format="XYE", axis_value=300.0 + i).to_dict()
              for i in range(n)]
    return frames, [PhaseSpec("alpha.cif", "alpha").to_dict()]


def test_sequential_rietveld_instrument_spec_builds_runner(monkeypatch):
    """instrument spec (JSON) からサーバ側で runner を組み立て、設定が make_gsas_runner に届く。"""
    from tsumugin.autorietveld.model import Geometry, Radiation

    made = _capture_make_runner(monkeypatch)
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    out = sequential_rietveld(
        frames, initial,
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
    assert made["two_theta_limits"] == (2.0, 18.0)
    # 組み立てた runner が run_sequential_rietveld に渡る
    assert seq["runner"] is made["runner"]
    json.dumps(out, allow_nan=False)


def test_sequential_rietveld_instrument_defaults(monkeypatch):
    """background_coeffs/max_cyc の既定は 6/12、auto_freeze は None (非回帰の既定)。"""
    made = _capture_make_runner(monkeypatch)
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    sequential_rietveld(frames, initial, instrument={"path": "x.instprm"})

    assert made["background_coeffs"] == 6
    assert made["max_cyc"] == 12
    assert made["auto_freeze_minor_cells"] is None
    assert made["two_theta_limits"] is None


def test_sequential_rietveld_instrument_paths_per_frame(monkeypatch):
    """paths (frames と 1:1) を渡すとフレーム毎に instprm を返す callable が組まれる。"""
    made = _capture_make_runner(monkeypatch)
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases(2)

    sequential_rietveld(frames, initial, instrument={"paths": ["a.instprm", "b.instprm"]})

    resolver = made["instrument_path"]
    assert callable(resolver)
    fs = seq["frames"]
    assert resolver(fs[0]) == "a.instprm"
    assert resolver(fs[1]) == "b.instprm"


def test_sequential_rietveld_instrument_paths_length_mismatch_error(monkeypatch):
    _capture_make_runner(monkeypatch)
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases(3)

    out = sequential_rietveld(frames, initial, instrument={"paths": ["a.instprm"]})
    assert out["error_type"] == "ValueError"
    assert "paths" in out["error"]
    json.dumps(out, allow_nan=False)


def test_sequential_rietveld_explicit_runner_overrides_instrument(monkeypatch):
    """runner= 明示注入は instrument より優先 (テスト注入経路の後方互換)。"""
    def boom(**kwargs):
        raise AssertionError("runner= 注入時は make_gsas_runner を呼んではいけない")

    monkeypatch.setattr("tsumugin.insitu.engine.make_gsas_runner", boom)
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    def runner(frame, phases, initial_cells):
        return _result(9.0, {}, {})

    sequential_rietveld(
        frames, initial, runner=runner,
        instrument={"path": "sr.instprm", "radiation": "xray_synchrotron"},
    )
    assert seq["runner"] is runner


def test_sequential_rietveld_default_path_unchanged(monkeypatch):
    """instrument=None + runner=None は従来通り runner=None を engine へ (既定 GSAS runner)。"""
    def boom(**kwargs):
        raise AssertionError("instrument 未指定時は make_gsas_runner を呼んではいけない")

    monkeypatch.setattr("tsumugin.insitu.engine.make_gsas_runner", boom)
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    sequential_rietveld(frames, initial)
    assert seq["runner"] is None


def test_sequential_rietveld_warm_start_fractions_reaches_config(monkeypatch):
    """warm_start_fractions=True が SequentialConfig へ配線される (Issue #82)。"""
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    def runner(frame, phases, initial_cells):
        return _result(9.0, {}, {})

    sequential_rietveld(frames, initial, runner=runner, warm_start_fractions=True)
    assert seq["config"].warm_start_fractions is True


def test_sequential_rietveld_warm_start_fractions_default_false(monkeypatch):
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    def runner(frame, phases, initial_cells):
        return _result(9.0, {}, {})

    sequential_rietveld(frames, initial, runner=runner)
    assert seq["config"].warm_start_fractions is False


def test_sequential_rietveld_auto_freeze_bool_rejected(monkeypatch):
    """auto_freeze_minor_cells は bool でなく float 閾値 (#80)。true は 1.0=全相凍結の罠なので拒否。"""
    _capture_make_runner(monkeypatch)
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    out = sequential_rietveld(
        frames, initial, instrument={"path": "x.instprm", "auto_freeze_minor_cells": True}
    )
    assert out["error_type"] == "ValueError"
    assert "threshold" in out["error"]
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "spec",
    [
        {"path": "x.instprm", "radiation": "synchrotron"},
        {"path": "x.instprm", "geometry": "capillary"},
        {"radiation": "xray_lab"},
    ],
)
def test_sequential_rietveld_bad_instrument_spec_returns_error_dict(monkeypatch, spec):
    """不正な enum 文字列/path 欠落は例外でなく {"error","error_type"} dict へ縮退。"""
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    out = sequential_rietveld(frames, initial, instrument=spec)
    assert out["error_type"] == "ValueError"
    assert isinstance(out["error"], str)
    json.dumps(out, allow_nan=False)


def test_parametric_fit_from_result_dict():
    # sequential_rietveld の出力を parametric_fit に渡す往復
    frames = [
        FrameSpec(f"f{k}.xrdml", axis_value=T).to_dict()
        for k, T in enumerate([300.0, 320.0, 340.0, 360.0, 380.0])
    ]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        a = 14.8 + 0.002 * (frame.axis_value - 300.0)
        return _result(9.0, {"alpha": (a, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    seq = sequential_rietveld(frames, initial, runner=runner)
    pf = parametric_fit(seq, "alpha", component="a", degree=1)
    assert pf["phase"] == "alpha"
    assert pf["baseline"]["coefficients"][1] == pytest.approx(0.002, abs=1e-5)
    assert pf["transition"] is None  # 単相
    json.dumps(pf, allow_nan=False)


# --- G1: seq_result_to_dict への residual_report 同梱 (§4.5 到達可能性 #3) -----------------


def _residual(n=64, peak_at=32, peak=500.0):
    tt = [10.0 + 0.05 * i for i in range(n)]
    resid = [0.0] * n
    resid[peak_at] = peak
    sigma = [10.0] * n
    return tt, resid, sigma


def _result_with_residual(rwp, cells, fracs):
    tt, resid, sigma = _residual()
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=1.0, refined_cells=cells,
        validity=ValidityReport(passed=True), phase_fractions=fracs,
        residual_two_theta=tuple(tt), residual_intensity=tuple(resid),
        residual_sigma=tuple(sigma),
    )


def test_seq_result_frames_embed_residual_report():
    """系列フレームに residual_report が同梱され ③ が J2/J3 を再精密化なしに判断できる。"""
    frames = [FrameSpec(f"f{i}.xrdml", axis_value=300.0 + i).to_dict() for i in range(3)]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        return _result_with_residual(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    out = sequential_rietveld(frames, initial, runner=runner)
    for fd in out["frames"]:
        rep = fd["residual_report"]
        assert rep is not None
        # auto_rietveld 経路 (rietveld_tools._result_to_dict) と同じ形 (単一 serializer)
        assert set(rep) == {
            "rwp", "peak_only_rwp", "baseline_numerator_fraction", "peak_numerator_fraction",
            "angular_rwp", "top_features",
        }
        assert rep["top_features"][0]["two_theta"] == pytest.approx(10.0 + 0.05 * 32)
        assert rep["top_features"][0]["residual"] == pytest.approx(500.0)
    json.dumps(out, allow_nan=False)


def test_seq_result_residual_report_key_always_present_as_none():
    """残差なし (スタブ runner) でもキーは存在し None (スキーマ安定, auto_rietveld と同規律)。"""
    frames = [FrameSpec("f0.xrdml", axis_value=300.0).to_dict()]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    out = sequential_rietveld(frames, initial, runner=runner)
    assert "residual_report" in out["frames"][0]
    assert out["frames"][0]["residual_report"] is None
    json.dumps(out, allow_nan=False)


def test_seq_result_residual_report_matches_auto_rietveld_shape():
    """同じ AutoRietveldResult なら auto_rietveld と seq の residual_report は完全一致する。"""
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    res = _result_with_residual(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})
    hist = {
        "data_path": "f0.xye", "instrument_path": "x.instprm",
        "radiation": "xray_lab", "geometry": "bragg_brentano", "data_format": "XYE",
    }
    single = auto_rietveld([hist], [PhaseSpec("alpha.cif", "alpha").to_dict()],
                           runner=lambda inp: res)

    def runner(frame, phases, initial_cells):
        return res

    seq = sequential_rietveld([FrameSpec("f0.xye", data_format="XYE").to_dict()],
                              [PhaseSpec("alpha.cif", "alpha").to_dict()], runner=runner)
    assert seq["frames"][0]["residual_report"] == single["residual_report"]


def test_seq_result_247_frame_payload_size_is_sane():
    """247 フレーム (実 K2Mn[Fe(CN)6] 系列長) でも JSON 全体が小さいまま (配列は跨がせない)。"""
    frames = [FrameSpec(f"f{i}.xye", data_format="XYE", axis_value=float(i)).to_dict()
              for i in range(247)]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        return _result_with_residual(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    out = sequential_rietveld(frames, initial, runner=runner)
    payload = json.dumps(out, allow_nan=False)
    assert len(out["frames"]) == 247
    assert all(f["residual_report"] is not None for f in out["frames"])
    # レポートは 1 フレーム ~0.7KB (スカラ + 角度ビン 5 + 特徴 6)。実データ相当 (2392 点 × 3 本の
    # 残差配列 = 13.5MiB/247frames, JSON テキストなら 2 桁上) を跨がせていないことの回帰ガード。
    assert len(json.dumps(out["frames"][0]["residual_report"], allow_nan=False)) < 2_000
    assert len(payload) < 1_000_000


def test_sequential_rietveld_bad_two_theta_limits_returns_error_dict(monkeypatch):
    """two_theta_limits の要素数不正は IndexError を境界に貫かせず error dict へ縮退。"""
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    def runner(frame, phases, initial_cells):
        return _result(9.0, {}, {})

    out = sequential_rietveld(frames, initial, runner=runner, two_theta_limits=[2.0])
    assert out["error_type"] == "ValueError"
    assert "two_theta_limits" in out["error"]
    json.dumps(out, allow_nan=False)
