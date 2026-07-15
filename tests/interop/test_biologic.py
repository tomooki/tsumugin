"""BioLogic EC-Lab (.mpr) 電気化学境界のテスト (interop.biologic)。

決定論テストは**合成構造化配列**を ``curve_from_mpr_data`` へ注入して行い、galvani も実ファイルも
要求しない (モジュール import は numpy-only の契約)。実 ``.mpr`` 1 本 (K-10 operando) は
galvani 未導入 / データ未配置で clean に skip する。
"""

from __future__ import annotations

import builtins
from pathlib import Path

import numpy as np
import pytest

from tsumugin.interop.biologic import (
    EchemCurve,
    EchemUnavailableError,
    FramePoint,
    align_frames,
    curve_from_mpr_data,
    parse_mpr,
)

_T0 = 1_700_000_000.0  # 合成データの取得開始 (POSIX 秒)


def _synthetic_data(
    *,
    fields: tuple[str, ...] = (
        "flags",
        "Ns",
        "time/s",
        "dq/mA.h",
        "(Q-Qo)/mA.h",
        "control/V/mA",
        "Ewe/V",
        "I Range",
        "Q charge/discharge/mA.h",
        "half cycle",
    ),
    shuffle: bool = False,
) -> np.ndarray:
    """rest(0-100s) → charge(100-300s) → discharge(300-500s) の 3 ステップ合成データ。

    Ewe/(Q-Qo) は各ステップで時間の線形関数にして、補間の期待値を解析的に書けるようにする。
    """
    # (time, Ns, Ewe, Q, half cycle)
    rows: list[tuple[float, float, float, float, float]] = []
    for t in (0.0, 50.0, 100.0):  # rest: E=1.0 一定, Q=0
        rows.append((t, 0.0, 1.0, 0.0, 0.0))
    for t in (150.0, 200.0, 250.0, 300.0):  # charge: E 1.0→2.0, Q 0→2.0 (t に線形)
        rows.append((t, 1.0, 1.0 + (t - 100.0) / 200.0, (t - 100.0) / 100.0, 0.0))
    for t in (350.0, 400.0, 450.0, 500.0):  # discharge: E 2.0→1.0, Q 2.0→0
        rows.append((t, 2.0, 2.0 - (t - 300.0) / 200.0, 2.0 - (t - 300.0) / 100.0, 1.0))

    if shuffle:
        rows = [rows[i] for i in (5, 0, 9, 2, 7, 1, 10, 3, 8, 4, 6)]

    dtype = np.dtype([(name, "f8") for name in fields])
    data = np.zeros(len(rows), dtype=dtype)
    for i, (t, ns, ewe, q, hc) in enumerate(rows):
        if "time/s" in fields:
            data["time/s"][i] = t
        if "Ns" in fields:
            data["Ns"][i] = ns
        if "Ewe/V" in fields:
            data["Ewe/V"][i] = ewe
        if "(Q-Qo)/mA.h" in fields:
            data["(Q-Qo)/mA.h"][i] = q
        if "half cycle" in fields:
            data["half cycle"][i] = hc
    return data


def _curve(**kwargs: object) -> EchemCurve:
    return curve_from_mpr_data(
        _synthetic_data(**kwargs),  # type: ignore[arg-type]
        start_timestamp=_T0,
        source_path="synthetic.mpr",
    )


# --------------------------------------------------------------------------------------
# curve_from_mpr_data
# --------------------------------------------------------------------------------------
def test_curve_from_mpr_data_extracts_tuples_and_metadata():
    """構造化配列 → EchemCurve: 列が tuple[float, ...] へ写り、メタデータを保持する。"""
    curve = _curve()
    assert isinstance(curve, EchemCurve)
    assert curve.time_s == (0.0, 50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 450.0, 500.0)
    assert all(isinstance(v, float) for v in curve.voltage_v)
    assert curve.voltage_v[0] == pytest.approx(1.0)
    assert curve.charge_mah[6] == pytest.approx(2.0)
    assert curve.step_index == (0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0)
    assert curve.half_cycle[-1] == pytest.approx(1.0)
    assert curve.start_timestamp == _T0
    assert curve.source_path == "synthetic.mpr"
    assert curve.duration_s == pytest.approx(500.0)


def test_curve_from_mpr_data_sorts_unsorted_input():
    """時間順でない入力は時間昇順へ整列される (整列済み入力と同一結果)。"""
    assert _curve(shuffle=True) == _curve()


def test_curve_is_frozen():
    """EchemCurve は frozen dataclass (非破壊性)。"""
    curve = _curve()
    with pytest.raises(Exception):
        curve.time_s = ()  # type: ignore[misc]


def test_missing_voltage_field_error_names_missing_and_present():
    """必須フィールド欠落は、探した候補名と実在フィールド名の双方を挙げて失敗する。"""
    fields = ("flags", "Ns", "time/s", "(Q-Qo)/mA.h", "half cycle")  # Ewe/V なし
    with pytest.raises(ValueError) as excinfo:
        _curve(fields=fields)
    msg = str(excinfo.value)
    assert "Ewe/V" in msg  # 探した候補
    assert "(Q-Qo)/mA.h" in msg and "time/s" in msg  # 実在フィールド
    assert "電圧" in msg or "voltage" in msg.lower()


def test_missing_time_field_error_names_missing_and_present():
    """time/s 欠落も同様に fail-loud する。"""
    with pytest.raises(ValueError, match="time/s"):
        _curve(fields=("flags", "Ns", "Ewe/V", "(Q-Qo)/mA.h"))


def test_alternative_field_names_are_accepted():
    """EC-Lab バージョン差の別名 (<Ewe>/V, (Q-Qo)/C) を受理する。"""
    dtype = np.dtype([("time/s", "f8"), ("<Ewe>/V", "f8"), ("(Q-Qo)/C", "f8")])
    data = np.zeros(3, dtype=dtype)
    data["time/s"] = [0.0, 1.0, 2.0]
    data["<Ewe>/V"] = [1.0, 1.5, 2.0]
    data["(Q-Qo)/C"] = [0.0, 3.6, 7.2]  # C → mA.h は /3.6
    curve = curve_from_mpr_data(data, start_timestamp=_T0, source_path="alt.mpr")
    assert curve.voltage_v == (1.0, 1.5, 2.0)
    assert curve.charge_mah == pytest.approx((0.0, 1.0, 2.0))
    assert curve.step_index == (0.0, 0.0, 0.0)  # Ns 欠落は 0 埋め (任意フィールド)


# --------------------------------------------------------------------------------------
# align_frames
# --------------------------------------------------------------------------------------
def test_align_frames_interpolates_voltage_and_charge():
    """フレーム時刻へ V/Q が線形補間される (合成データは区分線形なので解析解と一致)。"""
    curve = _curve()
    # rel = 175s (charge 区間の中点付近), 400s (discharge 区間の実測点)
    frames = align_frames(curve, (_T0 + 175.0, _T0 + 400.0))
    assert [f.frame_index for f in frames] == [0, 1]
    assert frames[0].time_s == pytest.approx(175.0)
    assert frames[0].voltage_v == pytest.approx(1.375)  # 1.0 + 75/200
    assert frames[0].charge_mah == pytest.approx(0.75)  # 75/100
    assert frames[1].voltage_v == pytest.approx(1.5)
    assert frames[1].charge_mah == pytest.approx(1.0)
    assert isinstance(frames[0], FramePoint)


def test_align_frames_labels_state_from_curve():
    """state は曲線から導出される (rest / charge / discharge)。"""
    curve = _curve()
    frames = align_frames(curve, (_T0 + 25.0, _T0 + 200.0, _T0 + 400.0))
    assert [f.state for f in frames] == ["rest", "charge", "discharge"]
    assert all(f.in_span for f in frames)


def test_align_frames_preserves_input_order_not_time_order():
    """frame_index は入力順 (時系列で並べ替えない — 回折フレーム番号との対応を保つ)。"""
    curve = _curve()
    frames = align_frames(curve, (_T0 + 400.0, _T0 + 25.0))
    assert [f.frame_index for f in frames] == [0, 1]
    assert [f.state for f in frames] == ["discharge", "rest"]


def test_align_frames_out_of_span_returns_none_by_default():
    """曲線の時間範囲外のフレームは外挿せず None を返す (電圧を捏造しない)。"""
    curve = _curve()
    frames = align_frames(curve, (_T0 - 10.0, _T0 + 250.0, _T0 + 600.0))
    assert frames[0].in_span is False
    assert frames[0].voltage_v is None
    assert frames[0].charge_mah is None
    assert frames[0].state == "unknown"
    assert frames[0].time_s == pytest.approx(-10.0)  # 相対時刻自体は返す
    assert frames[1].in_span is True
    assert frames[2].in_span is False
    assert frames[2].voltage_v is None


def test_align_frames_out_of_span_clamped_when_requested():
    """clamp=True では端点値で丸める。丸めた事実は in_span=False で残る。"""
    curve = _curve()
    frames = align_frames(curve, (_T0 - 10.0, _T0 + 600.0), clamp=True)
    assert frames[0].in_span is False
    assert frames[0].voltage_v == pytest.approx(1.0)  # 先頭点の値
    assert frames[0].charge_mah == pytest.approx(0.0)
    assert frames[0].state == "rest"
    assert frames[1].voltage_v == pytest.approx(1.0)  # 末尾点の値
    assert frames[1].state == "discharge"


def test_align_frames_span_boundaries_are_inclusive():
    """端点ちょうどのフレームは in_span (境界の取りこぼしを防ぐ)。"""
    curve = _curve()
    frames = align_frames(curve, (_T0 + 0.0, _T0 + 500.0))
    assert [f.in_span for f in frames] == [True, True]
    assert frames[1].voltage_v == pytest.approx(1.0)


def test_align_frames_empty_frames_returns_empty():
    """フレーム 0 件は空タプル。"""
    assert align_frames(_curve(), ()) == ()


def test_align_frames_rejects_non_finite_epoch():
    """NaN/inf のフレーム時刻は fail-loud (静かに外挿判定へ流さない)。"""
    with pytest.raises(ValueError, match="有限"):
        align_frames(_curve(), (_T0, float("nan")))


# --------------------------------------------------------------------------------------
# 遅延 import 契約
# --------------------------------------------------------------------------------------
def test_parse_mpr_raises_actionable_error_without_galvani(monkeypatch, tmp_path):
    """galvani 未導入では EchemUnavailableError で extra 導入手順を案内する。"""
    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "galvani" or name.startswith("galvani."):
            raise ImportError("No module named 'galvani'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.delitem(__import__("sys").modules, "galvani", raising=False)
    monkeypatch.setattr(builtins, "__import__", _fake_import)
    path = tmp_path / "dummy.mpr"
    path.write_bytes(b"")
    with pytest.raises(EchemUnavailableError, match="echem"):
        parse_mpr(path)


def test_module_import_does_not_pull_galvani():
    """モジュール import 時点で galvani を引き込まない (numpy-only コア契約)。"""
    import subprocess
    import sys

    code = (
        "import sys; import tsumugin.interop.biologic as m; "
        "assert 'galvani' not in sys.modules; print('ok')"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


# --------------------------------------------------------------------------------------
# 実データ (K-10 operando SXRD の電気化学 .mpr)
# --------------------------------------------------------------------------------------
_REAL_MPR = Path(
    "C:/Users/tomoo/Loggbas/Projects/論文-NaK-Hybrid-PBA/refs/OperandoSXRD/K-10/"
    "K-10_0p1C_re2_C01.mpr"
)


def _galvani_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("galvani") is not None


@pytest.mark.skipif(not _REAL_MPR.exists(), reason="K-10 operando .mpr が未配置")
@pytest.mark.skipif(not _galvani_available(), reason="galvani 未導入 (uv sync --extra echem)")
def test_real_mpr_k10_parses_and_aligns():
    """実 .mpr (K-10 0.1C, 13176 点 / 19.42 h): 点数・時間幅・充放電の切替時刻を検証する。"""
    curve = parse_mpr(_REAL_MPR)
    assert len(curve.time_s) == 13176
    assert curve.duration_s / 3600.0 == pytest.approx(19.42, abs=0.02)
    assert curve.step_index[0] == 0.0  # Ns=0 rest 先頭
    assert set(curve.step_index) == {0.0, 1.0, 2.0}

    # 充電 → 放電の切替は ~9.88 h。
    hours = np.asarray(curve.time_s) / 3600.0
    steps = np.asarray(curve.step_index)
    charge_end = float(hours[steps == 1.0].max())
    discharge_start = float(hours[steps == 2.0].min())
    assert charge_end == pytest.approx(9.88, abs=0.02)
    assert discharge_start == pytest.approx(9.88, abs=0.02)

    # 電圧: charge は 1.115 V から始まり 2.100 V まで上がり、discharge は 0.391 V で終わる。
    # (discharge 区間の**最小値**は -0.050 V の過渡スパイクなので、終端値で見ること。)
    volts = np.asarray(curve.voltage_v)
    assert float(volts[steps == 1.0][0]) == pytest.approx(1.115, abs=0.01)
    assert float(volts[steps == 1.0].max()) == pytest.approx(2.100, abs=0.01)
    assert float(volts[steps == 2.0][-1]) == pytest.approx(0.391, abs=0.01)

    # 回折フレーム (1 h 毎に 20 枚 = 19 h 以内) を整列。
    epochs = [curve.start_timestamp + 3600.0 * i for i in range(20)]
    frames = align_frames(curve, epochs)
    assert len(frames) == 20
    assert frames[0].state == "rest"  # t=0 は rest ステップ内
    assert frames[5].state == "charge"  # 5 h は充電中
    assert frames[15].state == "discharge"  # 15 h は放電中
    assert all(f.in_span for f in frames)  # 19 h < 19.42 h なので 20 枚すべて範囲内
    assert all(f.voltage_v is not None for f in frames)
