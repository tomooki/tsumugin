"""★規定「全解析で gpx を保存する」の ② 露出 (§4.5 到達可能性)。

① に保存機構があっても、② に (a) 置き場所を指定する引数と (b) 保存先を返すキーが無ければ、
③ にとってその機能は**存在しない**。特に MEM 系ツール (`mem_density` /
`mem_rietveld_iterate`) は「精密化済み gpx のパス」を入力に要求するので、
**その出所が ② の中に無いと呼び手が存在しない (dead on arrival)**。

ここで縛るのは「引数がエンジンへ届くこと」と「保存先が返り値に出ること」の 2 点。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport
from tsumugin.insitu.model import FrameRietveldResult, SequentialRietveldResult
from tsumugin.mcp.anchor_tools import anchored_sequential
from tsumugin.mcp.insitu_tools import sequential_rietveld
from tsumugin.mcp.rietveld_tools import auto_rietveld

_H = {
    "data_path": "d.xra",
    "instrument_path": "i.prm",
    "radiation": "xray_lab",
    "geometry": "bragg_brentano",
    "data_format": "GSAS",
}
_P = {"structure_path": "a.cif", "phase_name": "ph"}
_FRAMES = [
    {"data_path": "f0.xye", "axis_value": 300.0, "data_format": "XYE"},
    {"data_path": "f1.xye", "axis_value": 310.0, "data_format": "XYE"},
]


def _seq_result(gpx_dir: str) -> SequentialRietveldResult:
    return SequentialRietveldResult(
        frames=(
            FrameRietveldResult(
                frame_index=0, axis_value=300.0, data_path="f0.xye", rwp=9.0, gof=1.1,
                refined_cells={}, phase_fractions={}, phase_names=("ph",),
                gpx_path=f"{gpx_dir}/f0000_frame.gpx",
            ),
        ),
        phase_names=("ph",),
        gpx_dir=gpx_dir,
    )


def test_auto_rietveld_forwards_gpx_dir_to_the_engine(monkeypatch):
    """``auto_rietveld(gpx_dir=, save_gpx=)`` が既定 runner 経由でエンジンへ届く。"""
    captured: dict[str, object] = {}

    def fake_default_runner(seed, **kwargs):
        captured.update(kwargs)

        def run(inp):
            return AutoRietveldResult(
                stage_results=(), final_rwp=9.0, final_gof=1.0, refined_cells={},
                validity=ValidityReport(passed=True), gpx_path="/out/run/PbSO4.gpx",
            )

        return run

    monkeypatch.setattr(
        "tsumugin.mcp.rietveld_tools._default_gsas_runner", fake_default_runner
    )
    out = auto_rietveld([_H], [_P], gpx_dir="/chosen", save_gpx=True)

    assert captured["gpx_dir"] == "/chosen"
    assert captured["save_gpx"] is True
    # 保存先が ③ に返る = MEM 系ツールの入力の出所になる
    assert out["gpx_path"] == "/out/run/PbSO4.gpx"


def test_auto_rietveld_defaults_to_saving(monkeypatch):
    """★引数を渡さなくても ② は「保存する」でエンジンを呼ぶ (規定そのもの)。"""
    captured: dict[str, object] = {}

    def fake_default_runner(seed, **kwargs):
        captured.update(kwargs)
        return lambda inp: AutoRietveldResult(
            stage_results=(), final_rwp=9.0, final_gof=1.0, refined_cells={},
            validity=ValidityReport(passed=True),
        )

    monkeypatch.setattr(
        "tsumugin.mcp.rietveld_tools._default_gsas_runner", fake_default_runner
    )
    auto_rietveld([_H], [_P])

    assert captured["save_gpx"] is True
    assert captured["gpx_dir"] is None  # 既定の解決 (env → データ隣接) に委ねる


def test_sequential_rietveld_forwards_and_returns_gpx(monkeypatch):
    """系列: ``gpx_dir`` がエンジンへ届き、``gpx_dir``/``frames[].gpx_path`` が返る。"""
    captured: dict[str, object] = {}

    def fake_run(frames, phases, *, config=None, runner=None, phase_finder=None,
                 workdir=None, gpx_dir=None, save_gpx=True):
        captured["gpx_dir"] = gpx_dir
        captured["save_gpx"] = save_gpx
        return _seq_result("/series/run-1")

    monkeypatch.setattr("tsumugin.insitu.engine.run_sequential_rietveld", fake_run)
    out = sequential_rietveld(_FRAMES, [_P], gpx_dir="/series", runner=lambda *a, **k: None)

    assert captured == {"gpx_dir": "/series", "save_gpx": True}
    assert out["gpx_dir"] == "/series/run-1"
    assert out["frames"][0]["gpx_path"] == "/series/run-1/f0000_frame.gpx"


def test_anchored_sequential_forwards_and_returns_gpx(monkeypatch):
    """M10 双方向でも同じ 2 点 (引数がエンジンへ / 保存先が返り値へ)。"""
    captured: dict[str, object] = {}

    def fake_run(frames, base, *, runner=None, identifier=None, cfg=None, ledger=None,
                 charge_constraint=None, gpx_dir=None, save_gpx=True):
        captured["gpx_dir"] = gpx_dir
        captured["save_gpx"] = save_gpx
        return _seq_result("/anchored/run-1")

    monkeypatch.setattr("tsumugin.insitu.anchor.engine.run_anchored_sequential", fake_run)
    out = anchored_sequential(
        _FRAMES, [_P], gpx_dir="/anchored", save_gpx=False, runner=lambda *a, **k: None
    )

    assert captured == {"gpx_dir": "/anchored", "save_gpx": False}
    assert out["gpx_dir"] == "/anchored/run-1"
    assert out["frames"][0]["gpx_path"] == "/anchored/run-1/f0000_frame.gpx"


def test_repair_frames_returns_the_repaired_fit_path(monkeypatch, tmp_path):
    """修復した fit の成果物パスが ② に出る (修復は元フレームを置き換えるため別ハンドル)。

    `frames[i].gpx_path` は**修復前**の fit を指す。取り違えると ③ は「直したつもりの
    フレーム」に対して直す前の fit を開く/MEM を掛けることになる。
    """
    from tsumugin.insitu.repair import FrameRepair, RepairReport
    from tsumugin.mcp.operando_diag_tools import repair_frames

    def fake_repair(frames, seq, phases, runner, discontinuities, **kwargs):
        return RepairReport(
            repairs=(
                FrameRepair(
                    frame_index=1, rwp_before=12.0, rwp_after=8.0, source="L",
                    phase_fractions={"ph": 1.0}, gpx_path="/out/run/f0001_repair_L.gpx",
                ),
            ),
            needs_model_revision=(),
            systematic_hint=(),
        )

    monkeypatch.setattr("tsumugin.insitu.repair.repair_isolated", fake_repair)
    series = {
        "frames": [
            {
                "frame_index": i, "axis_value": 300.0 + 10 * i, "data_path": f"f{i}.xye",
                "rwp": 9.0, "gof": 1.1, "refined_cells": {}, "phase_fractions": {"ph": 1.0},
                "phase_names": ["ph"], "gpx_path": f"/out/run/f000{i}_frame.gpx",
            }
            for i in range(2)
        ],
        "phase_names": ["ph"],
    }
    out = repair_frames(
        series, _FRAMES, [_P], target_frames=[1], two_theta_limits=[10.0, 70.0],
        runner=lambda *a, **k: None,
    )

    assert out["repairs"][0]["gpx_path"] == "/out/run/f0001_repair_L.gpx"


def test_topas_backend_receives_the_same_gpx_arguments(monkeypatch):
    """★ ``backend="topas"`` でも**同じ引数名**で保存指示が届く (バックエンド中立の契約)。

    ② は保存の指定をバックエンドで呼び分けない。TOPAS では ``.gpx`` ではなく
    プロジェクト**ディレクトリ**が残り、返り値は ``project_path`` に出る。
    """
    captured: dict[str, object] = {}

    def fake_topas(histograms, phases, **kwargs):
        captured.update(kwargs)
        return AutoRietveldResult(
            stage_results=(), final_rwp=8.1, final_gof=1.2, refined_cells={},
            validity=ValidityReport(passed=True), backend="topas",
            project_path="/out/run/PBSO4",
        )

    monkeypatch.setattr("tsumugin.topas.engine.run_topas_rietveld", fake_topas)
    out = auto_rietveld([_H], [_P], backend="topas", gpx_dir="/chosen")

    assert captured["gpx_dir"] == "/chosen"
    assert captured["save_gpx"] is True
    assert out["project_path"] == "/out/run/PBSO4"
    assert out["gpx_path"] == ""  # TOPAS に .gpx は無い
