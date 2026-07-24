"""② discriminate ツール (Issue #130) の numpy 層テスト。

GSAS 実行 (discriminate_interval の中身) は @pytest.mark.gsas の別モジュールで検証する。
本モジュールは **例外を送出せず error dict へ縮退する契約** と config 構築を、GSASIIBackend を
monkeypatch (差し替え backend + 差し替え discriminate_interval) して GSAS 非依存に検証する。
"""

from __future__ import annotations

import pytest

from tsumugin.mcp import discriminate_tools
from tsumugin.mcp.discriminate_tools import _build_config, discriminate


def _phase(ref: str = "a") -> dict:
    return {"phase_ref": ref, "lattice": {"a": 5.0, "b": 5.0, "c": 5.0}}


def _series() -> dict:
    return {
        "two_theta": [10.0, 10.1, 10.2, 10.3],
        "intensities": [[1.0, 2.0, 3.0, 1.0], [1.0, 2.5, 2.5, 1.0]],
    }


# --- error dict 縮退 (例外を送出しない) ---


def test_gsas_unavailable_degrades_to_error_dict(monkeypatch):
    # GSASIIBackend 構築が GSASUnavailableError → error dict (例外送出しない)
    from tsumugin.errors import GSASUnavailableError

    class _Boom:
        def __init__(self, *a, **k):
            raise GSASUnavailableError("no gsas")

    monkeypatch.setattr("tsumugin.backends.gsasii.GSASIIBackend", _Boom)
    out = discriminate(_series(), [_phase()], [0, 1])
    assert "error" in out and out["error_type"] == "GSASUnavailableError"


def test_empty_initial_phases_is_error_not_normal(monkeypatch):
    # 空 initial_phases を「正常」と答えない (② 不変条件)
    monkeypatch.setattr(
        "tsumugin.backends.gsasii.GSASIIBackend", lambda **k: object()
    )
    out = discriminate(_series(), [], [0, 1])
    assert "error" in out
    assert "initial_phases" in out["error"]


def test_bad_frame_range_is_error(monkeypatch):
    monkeypatch.setattr(
        "tsumugin.backends.gsasii.GSASIIBackend", lambda **k: object()
    )
    out = discriminate(_series(), [_phase()], [0, 1, 2])
    assert "error" in out and "frame_range" in out["error"]


def test_bad_series_is_error(monkeypatch):
    monkeypatch.setattr(
        "tsumugin.backends.gsasii.GSASIIBackend", lambda **k: object()
    )
    out = discriminate({}, [_phase()], [0, 1])
    assert "error" in out


# --- 正常経路 (discriminate_interval を差し替えて配線を検証) ---


class _FakeResult:
    verdict = "solid_solution"
    delta_evidence = -12.5
    adjudicated_by = "bic"
    nested_delta_evidence = None
    escalations = ()
    warnings = ()

    class _H:
        id = "x"

    hypothesis_single = _H()
    hypothesis_two_phase = _H()

    class _MS:
        basins = ()
        n_starts = 8

    multistart_single = _MS()
    multistart_two_phase = _MS()


def test_happy_path_returns_verdict_dict(monkeypatch):
    captured = {}

    def fake_discriminate_interval(backend, frames, rng, phases, **kw):
        captured["rng"] = rng
        captured["n_phases"] = len(phases)
        captured["nested_backend"] = kw.get("nested_backend")
        captured["config"] = kw.get("config")
        return _FakeResult()

    monkeypatch.setattr(
        "tsumugin.backends.gsasii.GSASIIBackend", lambda **k: object()
    )
    monkeypatch.setattr(
        discriminate_tools, "discriminate_interval", fake_discriminate_interval
    )
    out = discriminate(_series(), [_phase(), _phase("b")], [0, 1])
    assert out["verdict"] == "solid_solution"
    assert out["delta_evidence"] == -12.5
    assert out["hypothesis_single"]["n_starts"] == 8
    assert captured["rng"] == (0, 1)
    assert captured["n_phases"] == 2
    # 既定は nested オプトインなし → nested_backend は None
    assert captured["nested_backend"] is None


def test_nested_opt_in_constructs_nested_backend(monkeypatch):
    captured = {}

    def fake_discriminate_interval(backend, frames, rng, phases, **kw):
        captured["nested_backend"] = kw.get("nested_backend")
        return _FakeResult()

    monkeypatch.setattr(
        "tsumugin.backends.gsasii.GSASIIBackend", lambda **k: object()
    )
    monkeypatch.setattr(
        discriminate_tools, "discriminate_interval", fake_discriminate_interval
    )
    discriminate(
        _series(), [_phase()], [0, 1],
        config={"nested_arbitration": {"close_threshold": 8.0}},
    )
    from tsumugin.nested.sampler import NestedBackend

    assert isinstance(captured["nested_backend"], NestedBackend)


# --- config 構築 ---


def test_build_config_defaults():
    cfg = _build_config({})
    assert cfg.close_threshold == 10.0
    assert cfg.multistart.n_starts == 8
    assert cfg.nested_arbitration is None
    assert cfg.physical_problem is not None  # 既定 ON


def test_build_config_physical_problem_null_disables():
    cfg = _build_config({"physical_problem": None})
    assert cfg.physical_problem is None  # 明示 null で v1 サロゲート退避


def test_build_config_physical_problem_margin_override():
    cfg = _build_config({"physical_problem": {"lattice_rel_margin": 0.05}})
    assert cfg.physical_problem.lattice_rel_margin == 0.05


def test_build_config_nested_opt_in():
    cfg = _build_config({"nested_arbitration": {"close_threshold": 5.0, "full_nested": True}})
    assert cfg.nested_arbitration is not None
    assert cfg.nested_arbitration.close_threshold == 5.0
    assert cfg.nested_arbitration.full_nested is True


def test_build_config_bad_multistart_raises():
    with pytest.raises(ValueError):
        _build_config({"multistart": [1, 2]})
