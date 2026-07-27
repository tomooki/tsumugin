"""M9 薄い MCP 3 ツール (insitu_tools) の純テスト (stub runner/finder, GSAS/MP 非依存)。

SDK 非依存・素の型 dict 応答・json.dumps(allow_nan=False) 安全・決定論を検証する。
"""

from __future__ import annotations

import csv
import json

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.model import FrameRietveldResult, FrameSpec, SequentialRietveldResult
from tsumugin.mcp.insitu_tools import (
    INSITU_TOOLS,
    _instrument_path_resolver,
    _result_from_dict,
    parametric_fit,
    seq_result_to_dict,
    sequential_rietveld,
    write_sequential_csv,
)


def _read_rows(path):
    """csv.reader で全行 (ヘッダ含む) を読み戻す (newline/utf-8 固定; test_trajectory.py の範)。"""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def _result(rwp, cells, fracs, valid=True):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=1.0, refined_cells=cells,
        validity=ValidityReport(passed=valid), phase_fractions=fracs,
    )


def test_registry_has_four_tools():
    # 【テスト目的】: FR-504 トラジェクトリ CSV (write_sequential_csv, Issue #116/#117 調査) 追加後は 4 ツール
    assert set(INSITU_TOOLS) == {
        "sequential_rietveld",
        "identify_and_add_phase",
        "parametric_fit",
        "write_sequential_csv",
    }


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


# --- Issue #114: instrument spec の recipe → make_gsas_runner(recipe=...) --------------------


def test_sequential_rietveld_instrument_recipe_reaches_make_gsas_runner(monkeypatch):
    """instrument.recipe (JSON) が RefinementStage タプルに変換され make_gsas_runner(recipe=) に届く。

    make_gsas_runner(recipe=...) は① に既に存在する (Issue #52) が、② の instrument spec からは
    JSON で届かなかった (Issue #114)。共有ヘルパ (_recipe_spec, rietveld_tools と同じ実装) で変換する。
    """
    from tsumugin.autorietveld import RefinementStage

    made = _capture_make_runner(monkeypatch)
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    sequential_rietveld(
        frames, initial,
        instrument={
            "path": "sr.instprm",
            "recipe": [
                {"label": "S0 scale+background", "flags": {"scale": True}},
                {"label": "S1 absorption", "flags": {"absorption": True}, "note": "opt-in"},
            ],
        },
    )

    recipe = made["recipe"]
    assert recipe == (
        RefinementStage(label="S0 scale+background", flags={"scale": True}),
        RefinementStage(label="S1 absorption", flags={"absorption": True}, note="opt-in"),
    )


def test_sequential_rietveld_instrument_recipe_default_is_none(monkeypatch):
    """recipe 省略時は None (make_gsas_runner の既定 build_recipe 経路, 非回帰)。"""
    made = _capture_make_runner(monkeypatch)
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    sequential_rietveld(frames, initial, instrument={"path": "sr.instprm"})

    assert made["recipe"] is None


def test_sequential_rietveld_instrument_invalid_recipe_returns_error_dict(monkeypatch):
    """不正な recipe spec は例外でなく error dict へ縮退する (② は例外を送出しない)。"""
    _capture_make_runner(monkeypatch)
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    out = sequential_rietveld(
        frames, initial,
        instrument={"path": "sr.instprm", "recipe": [{"flags": {"scale": True}}]},
    )
    assert out["error_type"] == "ValueError"
    json.dumps(out, allow_nan=False)


def test_sequential_rietveld_instrument_empty_recipe_returns_error_dict(monkeypatch):
    """★空の recipe ([]) は error dict へ縮退すること (「呼べるが黙って間違う」の予防)。

    recipe は**全置換**の意味論。`[]` は engine の `is not None` 判定を通って空タプルのまま
    使われ、**精密化段階ゼロ = 未精密化の Rwp がそのまま返る**サイレント失敗になる (省略時の
    None は既定 build_recipe にフォールバックするので安全だが、`[]` は別物)。③ が「上書き不要」
    のつもりで [] を送ると operando 系列全体が精密化ゼロの結果を静かに返すため、明示的に弾く。
    """
    _capture_make_runner(monkeypatch)
    _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    out = sequential_rietveld(
        frames, initial, instrument={"path": "sr.instprm", "recipe": []}
    )
    assert out["error_type"] == "ValueError"
    assert "recipe" in out["error"], "どのキーが問題か示していない"
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
    """sequential_rietveld の出力を parametric_fit に渡す往復 (格子ベースライン)。

    **basis="scale" を明示**するようになった (Issue #96 レビュー第4巡): ② の既定は重量分率で、
    このスタブ runner は重量分率を返さないため既定では error dict に縮退する
    (`test_parametric_fit_errors_when_weight_fractions_unavailable` がその契約を固定する)。
    ここで見たいのは格子 vs 軸の回帰なので、診断用の Scale 基準を明示して呼ぶ。
    """
    frames = [
        FrameSpec(f"f{k}.xrdml", axis_value=T).to_dict()
        for k, T in enumerate([300.0, 320.0, 340.0, 360.0, 380.0])
    ]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        a = 14.8 + 0.002 * (frame.axis_value - 300.0)
        return _result(9.0, {"alpha": (a, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    seq = sequential_rietveld(frames, initial, runner=runner)
    pf = parametric_fit(seq, "alpha", component="a", degree=1, basis="scale")
    assert pf["phase"] == "alpha"
    assert pf["baseline"]["coefficients"][1] == pytest.approx(0.002, abs=1e-5)
    assert pf["transition"] is None  # 単相
    json.dumps(pf, allow_nan=False)


# --- parametric_fit の basis (Issue #96 レビュー第4巡 HIGH) --------------------------------
#
# `parametric_fit` は `phase_fractions` (Scale) を**消費して** onset/midpoint という
# **出版値を導出する** ② 表面である。`estimate_transition` は絶対レベル 0.50/0.10 の交差軸値を
# 返すため、y 軸が Scale か wt% かで答えが変わる (実測: Scale なら midpoint 9.515 h、同じ fit の
# wt% なら「転移なし」)。


def _divergent_seq_dict():
    """Scale は 0.50 を横切るが wt% は横切らない系列 dict (実測 tetra fr96-126 の縮図)。"""
    rows = [(0.0, 0.0, 0.0), (1.0, 0.30, 0.19), (2.0, 0.50, 0.34), (3.0, 0.656, 0.472)]
    frames = tuple(
        FrameRietveldResult(
            frame_index=i, axis_value=ax, data_path=f"f{i}.xrdml", rwp=8.0, gof=1.0,
            refined_cells={"tetra": (10.0, 10.0, 10.0, 90, 90, 90)},
            phase_fractions={"tetra": s}, phase_names=("tetra",),
            phase_weight_fractions={"tetra": w}, phase_weight_fraction_esd={"tetra": 0.006},
        )
        for i, (ax, s, w) in enumerate(rows)
    )
    return seq_result_to_dict(SequentialRietveldResult(frames=frames, phase_names=("tetra",)))


def test_result_from_dict_carries_weight_fractions():
    """★系列 dict → 復元で重量分率が落ちないこと (② の到達可能性の前提)。

    落ちていると `parametric_fit(basis="weight")` は「重量分率が無い」と答えるほかなく、
    ③ から見て**重量分率基準の転移は原理的に到達不能**になる (実際に落ちていた)。
    """
    seq = _result_from_dict(_divergent_seq_dict())
    assert dict(seq.frames[3].phase_weight_fractions) == {"tetra": 0.472}


def test_parametric_fit_defaults_to_weight_basis():
    """★② の既定は**重量分率** — 同じ入力で Scale なら出る midpoint が既定では出ない。

    既定が Scale だと、③ は「出版できる転移温度」だと信じて Scale 由来の数字を受け取る
    (それが本 HIGH の実害そのもの)。
    """
    pf = parametric_fit(_divergent_seq_dict(), "tetra")
    assert pf["fraction_basis"] == "weight"
    assert pf["transition"] is None  # wt% は 0.50 に到達しない = 転移なし
    json.dumps(pf, allow_nan=False)


def test_parametric_fit_scale_basis_is_explicitly_labelled():
    """Scale 基準を明示要求したら数字は返るが、**Scale 由来と明記**される。"""
    pf = parametric_fit(_divergent_seq_dict(), "tetra", basis="scale")
    assert pf["fraction_basis"] == "scale"
    assert pf["transition"]["midpoint"] == pytest.approx(2.0, abs=1e-6)
    json.dumps(pf, allow_nan=False)


def test_parametric_fit_errors_when_weight_fractions_unavailable():
    """★重量分率が無ければ **Scale へ黙って落ちず** error dict (② は例外を送出しない)。

    「転移なし」と答えるのも禁止 — それは本物の「転移なし」と区別が付かない静かな嘘になる。
    """
    frames = (
        FrameRietveldResult(
            frame_index=i, axis_value=float(i), data_path=f"f{i}.xrdml", rwp=8.0, gof=1.0,
            refined_cells={"p": (5.0, 5.0, 5.0, 90, 90, 90)},
            phase_fractions={"p": 0.2 + 0.4 * i}, phase_names=("p",),
        )
        for i in range(3)
    )
    seq = seq_result_to_dict(SequentialRietveldResult(frames=frames, phase_names=("p",)))
    pf = parametric_fit(seq, "p")
    assert pf["error_type"] == "FractionBasisUnavailableError"
    assert "basis" in pf["error"]  # 復旧方法 (basis="scale") を示す
    assert "transition" not in pf  # 数字を返さない
    json.dumps(pf, allow_nan=False)


def test_parametric_fit_unknown_basis_is_error_dict():
    """未知 basis は例外でなく error dict へ縮退する (② は例外を送出しない)。"""
    pf = parametric_fit(_divergent_seq_dict(), "tetra", basis="wt%")
    assert pf["error_type"] == "ValueError"
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


# ===========================================================================
# 出版値の露出 (Issue #96 レビュー HIGH-2) — フレーム毎
# ---------------------------------------------------------------------------
# operando の主要な報告値は「相分率 vs 時間」である。③ が受け取れるのが Scale だけなら、
# 報告される定量値がそのまま誤る (実測 K2Mn[Fe(CN)6]: tetra ドーム頂点 65.6 Scale% は
# 実際には 47.2 wt% = この点で 1.39 倍。**乖離はフレーム毎に違い** [系列全体で 1.39-1.62 倍]、
# 大きさは単位胞質量比 [cubic 1103.4 / tetra 517.8 amu = 2.13 倍] と分率で決まるので
# **単一の換算係数は無い**)。esd 無しでは出版もできない。
# ===========================================================================


def test_seq_result_exposes_per_frame_publication_values():
    """フレーム毎に重量分率 ± esd と格子 esd が載ること。"""
    frame = FrameRietveldResult(
        frame_index=0,
        axis_value=1.0,
        data_path="f0.xrdml",
        rwp=7.0,
        gof=1.1,
        refined_cells={"cubic": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)},
        phase_fractions={"cubic": 0.656, "tetra": 0.344},
        phase_names=("cubic", "tetra"),
        phase_weight_fractions={"cubic": 0.472, "tetra": 0.528},
        phase_weight_fraction_esd={"cubic": 0.006, "tetra": 0.006},
        cell_esd={"cubic": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
    )
    out = seq_result_to_dict(SequentialRietveldResult(frames=(frame,)))
    f0 = out["frames"][0]

    assert f0["phase_weight_fractions"] == {"cubic": 0.472, "tetra": 0.528}
    assert f0["phase_weight_fraction_esd"] == {"cubic": 0.006, "tetra": 0.006}
    assert f0["cell_esd"] == {"cubic": [0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0]}
    # Scale 値も従来通り残る (相対比較用) — 出版値と**両方**見えることが要点
    assert f0["phase_fractions"] == {"cubic": 0.656, "tetra": 0.344}
    json.dumps(out, allow_nan=False)


def test_seq_result_publication_keys_present_even_when_unavailable():
    """スタブ runner/失敗フレームでもキーは存在 (欠落と esd=0 を取り違えさせない)。"""
    frame = FrameRietveldResult(
        frame_index=0, axis_value=1.0, data_path="f0.xrdml", rwp=7.0, gof=1.1,
        refined_cells={}, phase_fractions={"alpha": 1.0}, phase_names=("alpha",),
    )
    out = seq_result_to_dict(SequentialRietveldResult(frames=(frame,)))
    f0 = out["frames"][0]

    assert f0["phase_weight_fractions"] == {}
    assert f0["phase_weight_fraction_esd"] == {}
    assert f0["cell_esd"] == {}
    json.dumps(out, allow_nan=False)


def test_seq_result_publication_values_are_json_safe():
    frame = FrameRietveldResult(
        frame_index=0, axis_value=1.0, data_path="f0.xrdml", rwp=7.0, gof=1.1,
        refined_cells={}, phase_fractions={}, phase_names=("cubic",),
        phase_weight_fractions={"cubic": float("nan")},
        phase_weight_fraction_esd={"cubic": float("inf")},
        cell_esd={"cubic": (float("nan"), 0.1, 0.1, 0.0, 0.0, 0.0)},
    )
    out = seq_result_to_dict(SequentialRietveldResult(frames=(frame,)))
    f0 = out["frames"][0]

    assert f0["phase_weight_fractions"]["cubic"] is None
    assert f0["phase_weight_fraction_esd"]["cubic"] is None
    assert f0["cell_esd"]["cubic"][0] is None
    json.dumps(out, allow_nan=False)


def test_sequential_rietveld_end_to_end_delivers_publication_values_to_layer3():
    """★到達可能性 (§4.5): ③ が実際に呼ぶ経路で出版値が届くこと。

    serializer 単体のテストは「フレームが値を持っていれば出せる」ことしか言わない。**エンジンが
    フレームに詰めていなければ**、② の配線があっても ③ には空 dict しか届かない (= 無いのと同じ)。
    ツールの入口から出口まで通して初めて到達可能性が言える。
    """
    cells = {"cubic": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)}

    def runner(frame, phases, initial_cells):
        return AutoRietveldResult(
            stage_results=(), final_rwp=7.0, final_gof=1.1,
            refined_cells=cells, validity=ValidityReport(passed=True),
            phase_fractions={"cubic": 0.656, "tetra": 0.344},
            phase_weight_fractions={"cubic": 0.472, "tetra": 0.528},
            phase_weight_fraction_esd={"cubic": 0.006, "tetra": 0.006},
            cell_esd={"cubic": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
        )

    out = sequential_rietveld(
        [FrameSpec(data_path="f0.xrdml", axis_value=0.0).to_dict()],
        [PhaseSpec(structure_path="c.cif", phase_name="cubic").to_dict()],
        runner=runner,
    )
    f0 = out["frames"][0]

    assert f0["phase_weight_fractions"] == {"cubic": 0.472, "tetra": 0.528}
    assert f0["phase_weight_fraction_esd"] == {"cubic": 0.006, "tetra": 0.006}
    assert f0["cell_esd"] == {"cubic": [0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0]}
    json.dumps(out, allow_nan=False)


# ===========================================================================
# ② の縮退契約 (Issue #96 レビュー第4巡 MEDIUM / MEDIUM-HIGH)
# ---------------------------------------------------------------------------
# `parametric_fit` は `check_phase_set`/`repair_frames` と**同じ復元器** (`_result_from_dict`) を
# 呼びながら、縮退契約だけが食い違っていた:
#   (a) `AttributeError` を捕らえず、壊れた入力で例外が MCP 境界を貫いていた。
#   (b) `_validate_seq_result` を通らず、`{}` を「重量分率基準で見て転移なし」と**断言**していた。
# (b) は最悪の失敗様態である: ③ に指示してある検算 `assert pf["fraction_basis"] == "weight"`
# (skills/insitu:161 / AGENT_PLAYBOOK:228) が**素通りする**ため、③ は無データの答えを出版する。
# ===========================================================================


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("x", id="result が str"),
        pytest.param(["frames"], id="result が list"),
        pytest.param({"frames": {"a": 1}}, id="frames が dict"),
        pytest.param({"frames": ["not-a-frame"]}, id="フレーム要素が str"),
        pytest.param({"frames": [None]}, id="フレーム要素が None"),
    ],
)
def test_parametric_fit_never_raises_across_the_layer2_boundary(malformed):
    """★② は例外を送出しない (③ は LLM なので例外は回復不能なハード失敗)。

    旧実装ではこれらの入力で `_result_from_dict` の `d.get(...)` / `fd.get(...)` が
    **AttributeError** を投げ、MCP 境界を貫いていた (except は (ValueError, TypeError, KeyError,
    IndexError) で AttributeError を含まず、兄弟の `check_phase_set` — 同じ復元器を呼び
    AttributeError も捕らえる — と契約が食い違っていた)。

    現在は `_validate_seq_result` が**先に** ValueError で弾くため経路は変わったが、
    ③ から見た契約 (error dict へ縮退) は同じ。AttributeError 経路そのものの回帰は
    `test_parametric_fit_catches_attribute_error_from_the_deserializer` が固定する。
    """
    out = parametric_fit(malformed, "tetra")

    assert isinstance(out, dict), f"dict でない: {out!r}"
    assert "error" in out and "error_type" in out, f"error dict へ縮退していない: {sorted(out)}"
    # 「答え」を返していないこと (③ が結果と誤読しない)
    assert "transition" not in out and "fraction_basis" not in out
    json.dumps(out, allow_nan=False)


def test_parametric_fit_catches_attribute_error_from_the_deserializer():
    """★復元器が投げる `AttributeError` も error dict へ縮退すること。

    ⚠ **レビューが示した 5 入力 (result が str/list・frames が dict・フレーム要素が str/None) は、
    いずれも `_validate_seq_result` が先に ValueError で弾くようになったため、AttributeError 経路の
    証拠にはならない** (変異検査で判明: except から AttributeError を外しても上のテストは緑のまま)。
    それでも catch は**空振りではない** — 検証を通過してから復元器の `.items()` で落ちる形が残る:
    `refined_cells` / `phase_fractions` が dict でなく list のとき、`_result_from_dict` の
    ``(fd.get("refined_cells") or {}).items()`` が AttributeError を投げる。③ が組む JSON では
    dict と list の取り違えは現実的な誤りであり、これが MCP 境界を貫けば ③ は回復できない。
    """
    seq = {
        "frames": [
            {"frame_index": 0, "rwp": 8.0, "phase_names": ["tetra"], "refined_cells": [1, 2]}
        ]
    }

    out = parametric_fit(seq, "tetra")

    assert out.get("error_type") == "AttributeError", (
        f"AttributeError が error dict へ縮退していない: {sorted(out)}"
    )
    assert "fraction_basis" not in out and "transition" not in out
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize(
    "empty",
    [
        pytest.param({}, id="frames キーが無い"),
        pytest.param({"frames": []}, id="frames が空"),
    ],
)
def test_parametric_fit_refuses_to_certify_an_empty_series(empty):
    """★空/不正な系列を「重量分率基準で転移なし」と**断言しない** (最悪の失敗様態)。

    0 フレームなら `fraction_series(basis="weight")` の欠測検査は **0 件** = 素通りするため、
    `FractionBasisUnavailableError` すら出ずに `fraction_basis="weight"` + `transition=None` が
    返っていた。これは `insitu.model.FractionBasisUnavailableError` が明文で禁じている
    「『転移なし』へ縮退する」= **本物の「転移なし」と区別が付かない**そのものである。
    さらに ③ への指示 `assert pf["fraction_basis"] == "weight"` が素通りするため、
    **自分で定めた妥当性チェックが無データの答えを承認する**。
    """
    out = parametric_fit(empty, "tetra")

    assert out.get("error_type") == "ValueError", f"error dict へ縮退していない: {sorted(out)}"
    assert "fraction_basis" not in out, (
        "空の系列に `fraction_basis` を付けて返している — ③ の "
        '`assert pf["fraction_basis"] == "weight"` が素通りし、無データの答えが出版される'
    )
    assert "transition" not in out, "「転移なし」へ縮退している (本物の転移なしと区別が付かない)"
    json.dumps(out, allow_nan=False)


def test_parametric_fit_still_answers_for_a_valid_series():
    """縮退契約の追加で**正常系を殺していない**こと (検証が厳しすぎれば ③ は使えない)。"""
    frames = tuple(
        FrameRietveldResult(
            frame_index=i, axis_value=float(i), data_path=f"f{i}.xrdml", rwp=8.0, gof=1.0,
            refined_cells={"tetra": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
            phase_fractions={"tetra": 0.25 * i}, phase_names=("tetra",),
            phase_weight_fractions={"tetra": 0.25 * i},
        )
        for i in range(4)
    )
    seq = seq_result_to_dict(SequentialRietveldResult(frames=frames, phase_names=("tetra",)))

    out = parametric_fit(seq, "tetra")

    assert "error" not in out
    assert out["fraction_basis"] == "weight"
    assert out["transition"]["midpoint"] == pytest.approx(2.0, abs=1e-6)


# ===========================================================================
# _instrument_path_resolver: id() を鍵にしない (間欠失敗の根治)
# ---------------------------------------------------------------------------
# 旧実装は `by_id = {id(fs): path}` の fast-path を持ち、`resolve(frame)` が最初に
# `id(frame) in by_id` を見た。テスト/③ は新規 FrameSpec を渡して data_path 経路を検証するが、
# CPython の id() 再利用 (GC された別オブジェクトの id を新規 FrameSpec が再取得) で稀に
# by_id の stale entry にヒットし、data_path に落ちる前に**誤ったパス**を返していた
# (full suite で間欠失敗 = tests/mcp/test_operando_diag_tools.py の per-frame テスト)。
# 根治は id() を鍵にしないこと: フレームの**内容** (data_path / frozen dataclass の値) で解決する。
# ===========================================================================


def test_instrument_path_resolver_resolves_a_fresh_frame_by_data_path():
    """★新規生成した (= 元 frame_specs と id が異なる) フレームを data_path で正しく引く。

    ③ / runner は元オブジェクトと同一 id を持つとは限らない。id() 一致を前提にすると、
    id() 再利用で stale entry に当たったフレームだけ静かに誤ったパスへ解決される。
    """
    frame_specs = [FrameSpec(data_path=f"f{i}.xrdml", axis_value=float(i)) for i in range(3)]
    resolver = _instrument_path_resolver(
        {"paths": ["a.instprm", "b.instprm", "c.instprm"]}, frame_specs
    )
    assert callable(resolver)
    # id の異なる新規オブジェクト (元 frame_specs とは別インスタンス)
    assert resolver(FrameSpec(data_path="f1.xrdml", axis_value=1.0)) == "b.instprm"
    assert resolver(FrameSpec(data_path="f0.xrdml", axis_value=0.0)) == "a.instprm"


def test_instrument_path_resolver_duplicate_data_path_resolves_by_position():
    """★同一 data_path が複数フレームにある系列は data_path では区別できない → 値 (位置) で解決。

    旧 `by_data = {data_path: path}` は最後のパスで上書きされ、id fast-path を外れた
    (新規生成) フレームは全て**最後のパス**に解決されていた。frozen dataclass の値
    (axis_value 等で区別) を鍵にすれば位置ごとに正しく引ける。
    """
    frame_specs = [
        FrameSpec(data_path="same.xye", axis_value=0.0),
        FrameSpec(data_path="same.xye", axis_value=1.0),
    ]
    resolver = _instrument_path_resolver(
        {"paths": ["a.instprm", "b.instprm"]}, frame_specs
    )
    # id の異なる値等価コピー: 位置で区別され正しいパスへ
    assert resolver(FrameSpec(data_path="same.xye", axis_value=0.0)) == "a.instprm"
    assert resolver(FrameSpec(data_path="same.xye", axis_value=1.0)) == "b.instprm"


def test_instrument_path_resolver_unknown_frame_raises_never_stale_path():
    """★系列に無いフレームは ValueError を上げる (stale entry の誤ったパスを黙って返さない)。"""
    frame_specs = [FrameSpec(data_path=f"f{i}.xrdml", axis_value=float(i)) for i in range(2)]
    resolver = _instrument_path_resolver({"paths": ["a.instprm", "b.instprm"]}, frame_specs)
    with pytest.raises(ValueError, match="no instrument path"):
        resolver(FrameSpec(data_path="unknown.xrdml", axis_value=9.0))


def test_instrument_path_resolver_single_path_is_str():
    """`path` (単一) はそのまま str を返す (callable を組まない)。"""
    frame_specs = [FrameSpec(data_path="f0.xrdml", axis_value=0.0)]
    assert _instrument_path_resolver({"path": "one.instprm"}, frame_specs) == "one.instprm"


# ===========================================================================
# write_sequential_csv: FR-504 トラジェクトリ CSV を M9 実データ経路から到達可能にする
# ---------------------------------------------------------------------------
# 調査の帰結 (Issue #116/#117 付帯): M2 `sequential.trajectory.Trajectory.to_csv` は既に実装
# 済みだが `session.trajectory` を設定する ② ツールが無く実データ経路 (M9) からは到達不能だった。
# `sequential_rietveld`/`anchored_sequential` の戻り値 dict は既に格子/scale/wt_frac/esd を
# 持つので、Trajectory を経由せず**この dict を直接 CSV へ写す**方が実データに即しており、
# 他 ② ツールの出力を入力に取るため §4.5 到達可能性も満たす。
# ===========================================================================


def _seq_dict_two_frames():
    """2 相・2 フレームの正常系列結果 dict (write_sequential_csv の主経路検証用)。"""
    frames = (
        FrameRietveldResult(
            frame_index=0, axis_value=300.0, data_path="f0.xrdml", rwp=7.0, gof=1.1,
            refined_cells={"cubic": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)},
            phase_fractions={"cubic": 1.0}, phase_names=("cubic",),
            phase_weight_fractions={"cubic": 1.0},
            phase_weight_fraction_esd={"cubic": 0.0},
            cell_esd={"cubic": (0.002, 0.002, 0.002, 0.0, 0.0, 0.0)},
        ),
        FrameRietveldResult(
            frame_index=1, axis_value=320.0, data_path="f1.xrdml", rwp=8.0, gof=1.2,
            refined_cells={
                "cubic": (10.5, 10.5, 10.5, 90.0, 90.0, 90.0),
                "tetra": (10.2, 10.2, 10.6, 90.0, 90.0, 90.0),
            },
            phase_fractions={"cubic": 0.6, "tetra": 0.4}, phase_names=("cubic", "tetra"),
            phase_weight_fractions={"cubic": 0.7, "tetra": 0.3},
            phase_weight_fraction_esd={"cubic": 0.01, "tetra": 0.01},
            cell_esd={
                "cubic": (0.003, 0.003, 0.003, 0.0, 0.0, 0.0),
                "tetra": (0.004, 0.004, 0.005, 0.0, 0.0, 0.0),
            },
            changepoint=True, changepoint_reasons=("lattice_jump", "new_peaks"),
        ),
    )
    return seq_result_to_dict(
        SequentialRietveldResult(frames=frames, phase_names=("cubic", "tetra"))
    )


def test_write_sequential_csv_writes_expected_header_and_values(tmp_path):
    seq = _seq_dict_two_frames()
    out = tmp_path / "traj.csv"
    result = write_sequential_csv(seq, str(out))

    assert result["path"] == str(out)
    assert result["n_frames"] == 2
    assert result["n_phases"] == 2
    assert out.exists()

    rows = _read_rows(out)
    header = rows[0]
    # 【共通列】: フレーム共通列がすべて存在する
    for col in (
        "frame_index", "data_path", "axis_value", "rwp", "gof",
        "changepoint", "changepoint_reasons", "refine_failed",
    ):
        assert col in header, col
    # 【相ごと列】: cubic/tetra それぞれ 9 列 (a/b/c/a_esd/b_esd/c_esd/scale/wt_frac/wt_frac_esd)
    for ref in ("cubic", "tetra"):
        for suffix in ("a", "b", "c", "a_esd", "b_esd", "c_esd", "scale", "wt_frac", "wt_frac_esd"):
            assert f"{ref}.{suffix}" in header, f"{ref}.{suffix}"

    idx = {name: i for i, name in enumerate(header)}
    row1 = rows[2]  # フレーム 1 (0 起点で 2 行目がヘッダ, 3 行目がフレーム1)
    assert row1[idx["frame_index"]] == "1"
    assert row1[idx["changepoint"]] == "True"
    assert row1[idx["changepoint_reasons"]] == "lattice_jump|new_peaks"
    assert row1[idx["cubic.a"]] == "10.5"
    assert row1[idx["tetra.a"]] == "10.2"
    assert row1[idx["cubic.wt_frac"]] == "0.7"
    assert row1[idx["tetra.wt_frac"]] == "0.3"
    assert row1[idx["cubic.a_esd"]] == "0.003"


def test_write_sequential_csv_does_not_fabricate_m2_only_columns(tmp_path):
    """M2 Trajectory 固有列 (sigma_source/lifecycle 3 列) を M9 データから捏造しないこと。

    M9 の SequentialRietveldResult にはこれらに対応する値が無い。含めて空欄で埋めると
    「持っているように見える」偽装になる (CLAUDE.md ②不変条件と同じ規律の CSV 版)。
    """
    seq = _seq_dict_two_frames()
    out = tmp_path / "traj.csv"
    write_sequential_csv(seq, str(out))
    header = _read_rows(out)[0]

    # 相接頭辞つき (``calcite.sigma_source``) と**素の共通列** (``sigma_source``) の両方を見る。
    # M2 の `sigma_source` は接頭辞の無い共通列なので、endswith(".name") だけだと素の名前で
    # 捏造された列を見逃す (ガードの穴)。
    for forbidden in ("sigma_source", "birth_frame", "death_frame", "confidence"):
        offenders = [c for c in header if c == forbidden or c.endswith(f".{forbidden}")]
        assert not offenders, f"M9 に対応値の無い列を捏造している: {offenders}"


def test_write_sequential_csv_blank_cell_for_phase_absent_in_frame(tmp_path):
    """フレーム 0 に無い tetra の格子/scale 列は空欄 (欠測の捏造をしない)。"""
    seq = _seq_dict_two_frames()
    out = tmp_path / "traj.csv"
    write_sequential_csv(seq, str(out))
    rows = _read_rows(out)
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}
    row0 = rows[1]  # フレーム 0 (cubic のみ)
    assert row0[idx["tetra.a"]] == ""
    assert row0[idx["tetra.scale"]] == ""
    assert row0[idx["tetra.wt_frac"]] == ""


def test_write_sequential_csv_non_finite_and_none_become_blank(tmp_path):
    """rwp=inf (精密化失敗フレーム) は空欄になり、有限値と取り違えない。"""
    frame = FrameRietveldResult(
        frame_index=0, axis_value=1.0, data_path="f0.xrdml",
        rwp=float("inf"), gof=float("inf"), refined_cells={}, phase_fractions={},
        phase_names=("alpha",), refine_failed=True,
    )
    seq = seq_result_to_dict(SequentialRietveldResult(frames=(frame,), phase_names=("alpha",)))
    out = tmp_path / "traj.csv"
    write_sequential_csv(seq, str(out))
    rows = _read_rows(out)
    header, row0 = rows[0], rows[1]
    idx = {name: i for i, name in enumerate(header)}
    assert row0[idx["rwp"]] == ""
    assert row0[idx["gof"]] == ""
    assert row0[idx["refine_failed"]] == "True"
    assert row0[idx["alpha.a"]] == ""


def test_write_sequential_csv_is_deterministic(tmp_path):
    """同一入力から常に同一バイト列 (NFR-102)。"""
    seq = _seq_dict_two_frames()
    out1 = tmp_path / "a.csv"
    out2 = tmp_path / "b.csv"
    write_sequential_csv(seq, str(out1))
    write_sequential_csv(seq, str(out2))
    assert out1.read_bytes() == out2.read_bytes()


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param({}, id="frames キーが無い"),
        pytest.param({"frames": []}, id="frames が空"),
        pytest.param({"frames": [{"rwp": 1.0}]}, id="必須キー欠落 (frame_index/phase_names 無し)"),
        pytest.param("x", id="result が str"),
    ],
)
def test_write_sequential_csv_refuses_malformed_input_without_writing_file(tmp_path, malformed):
    """★空/不正な系列を「0 フレームの正しい CSV」として黙って書き出さない (偽成功の禁止)。"""
    out = tmp_path / "traj.csv"
    result = write_sequential_csv(malformed, str(out))
    assert "error" in result and "error_type" in result
    assert not out.exists()
    json.dumps(result, allow_nan=False)


def test_write_sequential_csv_degrades_oserror_to_error_dict():
    """★書き込み先ディレクトリが無い等の I/O 失敗は例外を送出せず error dict へ縮退する (② 契約)。"""
    seq = _seq_dict_two_frames()
    result = write_sequential_csv(seq, "/no/such/directory/traj.csv")
    assert "error" in result and "error_type" in result
    json.dumps(result, allow_nan=False)


def test_write_sequential_csv_registered_in_mcp_tools():
    from tsumugin.mcp.tools import MCP_TOOLS

    assert MCP_TOOLS["write_sequential_csv"] is write_sequential_csv


# --- ② 到達可能性: min_identify_score (PR #148 セルフレビュー指摘) -------------------------


def test_sequential_rietveld_forwards_min_identify_score(monkeypatch):
    """★``phase_id.min_identify_score`` が JSON から `PhaseIdConfig` へ届く (② 到達可能性)。

    **必要な理由**: 本ゲートは「どの候補が Rietveld 試行に回るか」を決める判断ポリシー閾値で、
    既に転送済みの `frac_min`/`trigger_rwp_ratio` と同格。転送されないと ③ (JSON しか送れない
    LLM) からは**存在しない**のと同じになる (CLAUDE.md ★①→②→③ 露出規則)。
    """
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    sequential_rietveld(
        frames, initial,
        phase_id={"elements": ["Ca", "Te", "O"], "min_identify_score": 0.05},
    )

    pid = seq["config"].phase_id
    assert pid is not None
    assert pid.min_identify_score == pytest.approx(0.05)


def test_sequential_rietveld_min_identify_score_default_is_engine_default(monkeypatch):
    """省略時は ① の既定 (0.0 = 正スコアを要求) を保つ (非回帰)。"""
    from tsumugin.insitu.model import PhaseIdConfig

    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    sequential_rietveld(frames, initial, phase_id={"elements": ["Ca", "Te", "O"]})

    pid = seq["config"].phase_id
    assert pid.min_identify_score == PhaseIdConfig().min_identify_score == 0.0


def test_sequential_rietveld_min_identify_score_null_disables_gate(monkeypatch):
    """★JSON の ``null`` は「ゲート無効」として None で届く (`float(None)` で落ちない)。

    ① の契約が「``None`` で無効 (従来動作)」なので、③ がゲートを外す唯一の手段がこの経路。
    素朴に `float(phase_id.get(...))` と書くと ``null`` で TypeError になり、② の
    「例外を送出せず error dict へ縮退する」契約にも引っかかる。
    """
    seq = _capture_seq(monkeypatch)
    frames, initial = _frames_and_phases()

    out = sequential_rietveld(
        frames, initial,
        phase_id={"elements": ["Ca", "Te", "O"], "min_identify_score": None},
    )

    assert "error" not in out, out
    assert seq["config"].phase_id.min_identify_score is None
