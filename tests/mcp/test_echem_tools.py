"""② align_echem (電気化学同期) の MCP 露出テスト (Issue #103)。

interop.biologic (parse_mpr/align_frames) は callable 不要なのに ② 未露出で KMnHCF 解析では
毎回 ① 直叩きだった。parse_mpr を monkeypatch して galvani 非依存の決定論テスト。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.interop.biologic import EchemCurve
from tsumugin.mcp.echem_tools import ECHEM_TOOLS, align_echem


def _curve() -> EchemCurve:
    """開始 1000.0s の合成充放電曲線 (0-300s 充電 1.5→2.1V/Q↑, 360-600s 放電 2.1→1.5V/Q↓)。

    state は Ns (step_index) ブロック毎の正味 ΔQ から導出されるため、充電/放電で **step_index を
    分け・charge_mah を増→減**にする (単一ブロック・単調 Q だと全域が同一ラベルになる)。
    """
    t = tuple(float(x) for x in range(0, 601, 60))  # 0,60,...,600 (11 点)
    v = tuple(1.5 + 0.6 * (x / 300.0) if x <= 300 else 2.1 - 0.6 * ((x - 300) / 300.0) for x in t)
    q = tuple(x / 100.0 if x <= 300 else 3.0 - (x - 300) / 100.0 for x in t)  # 増→減
    step = tuple(0.0 if x <= 300 else 1.0 for x in t)  # 充電=step0 / 放電=step1
    return EchemCurve(
        time_s=t, voltage_v=v, charge_mah=q, half_cycle=step,
        step_index=step, start_timestamp=1000.0, source_path="k.mpr",
    )


@pytest.fixture
def patched_parse(monkeypatch):
    monkeypatch.setattr("tsumugin.interop.biologic.parse_mpr", lambda p: _curve())


def test_registry():
    from tsumugin.mcp.echem_tools import alkali_budget

    assert ECHEM_TOOLS == {"align_echem": align_echem, "alkali_budget": alkali_budget}


def test_align_echem_constant_cadence(patched_parse):
    """一定ケイデンス (offset+interval+n) でフレームを整列し per-frame 状態を返す。"""
    # rel = 90, 270, 450 s — frame0 は充電域の内側、frame2 は放電域の内側 (境界を避ける)
    out = align_echem("k.mpr", offset_s=90.0, interval_s=180.0, n_frames=3)
    assert "error" not in out
    assert len(out["frames"]) == 3
    assert out["frames"][0]["state"] == "charge"
    assert out["frames"][2]["state"] == "discharge"
    assert out["frames"][0]["time_h"] == pytest.approx(90.0 / 3600.0)
    assert out["curve"]["n_points"] == 11
    assert out["n_in_span"] == 3
    json.dumps(out, allow_nan=False)


def test_align_echem_explicit_epochs(patched_parse):
    """明示 POSIX epoch 列でも整列できる (mtime 由来の厳密時刻)。"""
    # start=1000 なので epoch 1090 = rel 90s (充電域)
    out = align_echem("k.mpr", frame_epoch_s=[1090.0, 1400.0])
    assert "error" not in out
    assert len(out["frames"]) == 2
    assert out["frames"][0]["voltage_v"] == pytest.approx(1.5 + 0.6 * (90.0 / 300.0), abs=1e-3)


def test_align_echem_out_of_span_is_none_without_clamp(patched_parse):
    """範囲外フレームは voltage=None・state=unknown (電圧の外挿捏造を避ける)。"""
    out = align_echem("k.mpr", frame_epoch_s=[5000.0])  # rel 4000s > 600s 範囲外
    f = out["frames"][0]
    assert f["voltage_v"] is None
    assert f["in_span"] is False


def test_align_echem_mutually_exclusive_inputs_error(patched_parse):
    out = align_echem("k.mpr", frame_epoch_s=[1090.0], offset_s=30.0)
    assert "error" in out
    assert out["error_type"] == "ValueError"


def test_align_echem_missing_cadence_field_error(patched_parse):
    out = align_echem("k.mpr", offset_s=30.0, interval_s=150.0)  # n_frames 欠落
    assert "error" in out
    assert out["error_type"] == "ValueError"


def test_align_echem_galvani_unavailable_returns_error_dict(monkeypatch):
    from tsumugin.interop.biologic import EchemUnavailableError

    def boom(p):
        raise EchemUnavailableError("galvani 未導入")

    monkeypatch.setattr("tsumugin.interop.biologic.parse_mpr", boom)
    out = align_echem("k.mpr", offset_s=0.0, interval_s=1.0, n_frames=2)
    assert out["error_type"] == "EchemUnavailableError"


def test_align_echem_registered_in_mcp_tools():
    from tsumugin.mcp.tools import MCP_TOOLS

    assert "align_echem" in MCP_TOOLS
