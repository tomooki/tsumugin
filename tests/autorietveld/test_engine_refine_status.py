"""GSAS-II 精密化の**無言失敗**検出のテスト (判定ロジックは numpy-only, 配線のみ @gsas)。

**背景 (CaTeO3 frame180 実測)**: GSAS-II の ``G2Project.refine`` は
``GSASIIstrMain.Refine`` の戻り値 ``(OK, Rvals)`` を**受け取らずに捨てる**。したがって
精密化が失敗しても例外にならず、gpx の ``Covariance`` は前段のまま残る。engine は
そこから rwp/gof/n_params を読むため、**前段とビット同一の値**を「悪化していない結果」
として受理してしまう → revert されないので**その段で立てた精密化フラグが残り、以降の
全段が同じ理由で失敗し続ける**。Rwp には一切現れない (実測: 二相試行が S2 以降 7 段すべて
no-op、単相 base に負けて delta が棄却された)。

CLAUDE.md の不変条件「精密化バックエンドの失敗は例外でなく chi2=inf の結果に変換し、
ガードレールに処理させる」がこの経路だけ成立していなかった。本テストはその変換を固定する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.engine import _capture_refine_status, _refine_failure_message


class _FakeStrMain:
    """``GSASIIstrMain`` の最小スタブ。

    ``Refine`` は**インスタンス属性の素の関数**として持たせる (束縛メソッドだと属性アクセス毎に
    別オブジェクトになり、パッチ復元の同一性検査ができない)。
    """

    def __init__(self, result) -> None:
        self._result = result
        self.calls = 0

        def Refine(*args, **kwargs):  # noqa: N802 — GSAS-II の命名に合わせる
            self.calls += 1
            if isinstance(self._result, Exception):
                raise self._result
            return self._result

        self.Refine = Refine


# --- 失敗メッセージの純関数 -------------------------------------------------


def test_failure_message_none_when_ok():
    """OK=True は失敗ではない (None)。"""
    assert _refine_failure_message(True, {"Rwp": 12.3}) is None


def test_failure_message_reports_gsas_msg():
    """OK=False は GSAS の msg を含む失敗文を返す (ledger に理由を残すため)。"""
    msg = _refine_failure_message(
        False, {"msg": "divide by zero encountered in scalar divide"}
    )
    assert msg is not None
    assert "divide by zero" in msg


def test_failure_message_without_msg_still_fails():
    """msg が無い/Rvals が None でも OK=False なら失敗と判定する (沈黙させない)。"""
    assert _refine_failure_message(False, None) is not None
    assert _refine_failure_message(False, {}) is not None


# --- 戻り値の捕捉 (context manager) ----------------------------------------


def test_capture_records_failure_from_return_value():
    """``Refine`` が (False, {...}) を返したら status に失敗として記録される。"""
    mod = _FakeStrMain((False, {"msg": "**** ERROR: Refinement failed ****"}))
    with _capture_refine_status(_module=mod) as status:
        mod.Refine("proj.gpx")
    assert status["calls"] == 1
    assert status["ok"] is False
    assert "Refinement failed" in status["msg"]


def test_capture_records_success():
    mod = _FakeStrMain((True, {"Rwp": 9.1}))
    with _capture_refine_status(_module=mod) as status:
        mod.Refine("proj.gpx")
    assert status["ok"] is True
    assert status["calls"] == 1


def test_capture_marks_last_call_when_multiple():
    """複数回呼ばれた場合、1 回でも失敗があれば失敗として扱う (見逃さない)。"""
    results = [(True, {}), (False, {"msg": "boom"})]
    mod = _FakeStrMain(None)

    def refine(*args, **kwargs):
        mod.calls += 1
        return results.pop(0)

    mod.Refine = refine
    with _capture_refine_status(_module=mod) as status:
        mod.Refine("a")
        mod.Refine("b")
    assert status["calls"] == 2
    assert status["ok"] is False
    assert "boom" in status["msg"]


def test_capture_restores_original_refine():
    """パッチは必ず元に戻す (例外経路でも) — 他の精密化に副作用を残さない。"""
    mod = _FakeStrMain((True, {}))
    original = mod.Refine
    with _capture_refine_status(_module=mod):
        assert mod.Refine is not original  # パッチ中は差し替わっている
    assert mod.Refine is original

    with pytest.raises(RuntimeError):
        with _capture_refine_status(_module=mod):
            raise RuntimeError("stage blew up")
    assert mod.Refine is original


def test_capture_propagates_refine_exception_and_restores():
    """``Refine`` 自体が例外を投げる場合は素通し (既存の except 経路が inf 化する)。"""
    mod = _FakeStrMain(ValueError("Unknown refinement parameter, Shift"))
    original = mod.Refine
    with pytest.raises(ValueError):
        with _capture_refine_status(_module=mod):
            mod.Refine("proj.gpx")
    assert mod.Refine is original


def test_capture_fails_open_without_gsas_module():
    """GSAS 不在/``Refine`` 属性なしは fail open (ok=True, calls=0) — 精密化を止めない。"""
    with _capture_refine_status(_module=object()) as status:
        pass
    assert status["ok"] is True
    assert status["calls"] == 0


def test_capture_no_call_is_not_a_failure():
    """``Refine`` が一度も呼ばれなければ失敗ではない (fail open)。"""
    mod = _FakeStrMain((False, {"msg": "would have failed"}))
    with _capture_refine_status(_module=mod) as status:
        pass
    assert status["calls"] == 0
    assert status["ok"] is True


# --- engine 段階ループへの配線 (実 GSAS) ------------------------------------

_CATEO3 = Path("docs/benchmark/testdata/m9/cateo3")
_FRAME = _CATEO3 / "NB-LM01MO_030.XRDML"
_INSTR = _CATEO3 / "cateo3_CuKa.instprm"


@pytest.mark.gsas
@pytest.mark.skipif(
    not (_FRAME.exists() and _INSTR.exists()
         and (_CATEO3 / "alpha_CaTeO3_H2O.cif").exists()),
    reason="M9 CaTeO3 検証データが未配置 (docs/benchmark/testdata/m9/cateo3 README 参照)",
)
def test_failed_refinement_reverts_stage_and_records_ledger(tmp_path, monkeypatch):
    """GSAS が失敗を**返した**段は revert され ledger に理由が残る (無言 no-op にならない)。

    実 GSAS で 1 段目は通し、2 段目の ``Refine`` だけ ``(False, {...})`` を返させる。
    配線が無いと Covariance が前段のまま残り「悪化していない結果」として**受理**されてしまい、
    その段のフラグを抱えたまま以降の段が失敗し続ける (実測 CaTeO3 frame180 二相の病理)。
    """
    from GSASII import GSASIIstrMain

    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.model import (
        Geometry,
        HistogramSpec,
        PhaseSpec,
        Radiation,
        RefinementStage,
    )
    from tsumugin.insitu.engine import _xrdml_to_xye
    from tsumugin.store import Ledger

    xye = tmp_path / "frame.xye"
    _xrdml_to_xye(str(_FRAME), str(xye))
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(_INSTR), radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO, data_format="XYE", two_theta_limits=(12.0, 70.0),
    )
    phase = PhaseSpec(str(_CATEO3 / "alpha_CaTeO3_H2O.cif"), "alpha", format_hint="CIF")
    recipe = (
        RefinementStage(label="S0 scale+background",
                        flags={"scale": True, "background": {"coeffs": 24}}, note=""),
        RefinementStage(label="S1 cell+displacement",
                        flags={"cell": True, "displacement": {0: ["Shift"]}}, note=""),
    )

    original = GSASIIstrMain.Refine
    calls = {"n": 0}

    def _fail_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return original(*args, **kwargs)
        return False, {"msg": "injected: divide by zero encountered in scalar divide"}

    monkeypatch.setattr(GSASIIstrMain, "Refine", _fail_second)

    ledger = Ledger()
    res = run_auto_rietveld([hist], [phase], recipe=recipe, max_cyc=5, ledger=ledger)

    assert calls["n"] == 2, "2 段とも Refine が呼ばれること"
    s0, s1 = res.stage_results
    assert s1.reverted is True, "失敗した段が revert されていない (無言 no-op のまま)"
    assert s1.rwp == pytest.approx(s0.rwp), "revert 後は直前の受理状態の指標に戻る"
    errors = [e for e in ledger.entries if e.kind == "m7_stage_error"]
    assert errors, "失敗が ledger に残っていない"
    assert "injected" in str(errors[-1].payload.get("error", "")), errors[-1].payload
    assert ledger.verify() is True
