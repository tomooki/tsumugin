"""restraint penalty とデータ項 Rwp の**分離** (REQ-SAR-203 / D4-a の後始末)。

**動機**: `StabilityOptions.enable_restraints` で拘束を χ² に入れると、
`GSASIIstrMath.errRefine`:5210 が残差ベクトルへ penalty を連結するため
``Rvals['Rwp']`` が「データへの合わなさ」を表さなくなる。段の受理/revert は Rwp 比較なので、
そのまま判定すると**拘束が引いた分を適合の悪化と読み違えて全段 revert** する
(実測: bond weight 1e5 で Rwp 3558)。

ここでは GSAS 非依存の純関数 (`data_term_rwp`) と、engine の判定がデータ項で行われること
(スタブ backend を注入した engine レベルではなく、判定式そのもの) を固定する。
実 GSAS 側は `test_restraint_rwp_split_gsas.py`。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.diagnostics import (
    RefinementDiagnostics,
    data_term_rwp,
    diagnostics_from_cov_data,
)
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport


# ---------------------------------------------------------------------------
# data_term_rwp — penalty を χ² から抜いた Rwp の復元
# ---------------------------------------------------------------------------


def test_recovers_the_data_only_rwp_from_the_penalized_one():
    # 【目的】: Rwp = 100·√(chisq/sumwYo) で sumwYo は観測強度のみから積まれる (拘束と無関係)
    #   ので、chisq から pSum を引いた比の平方根を掛ければデータ項 Rwp が出る。
    # 具体値: sumwYo = 10000 とすると chisq_data = 400 → Rwp_data = 20%。
    #   penalty pSum = 500 を足すと chisq = 900 → Rwp = 30%。
    assert data_term_rwp(30.0, 900.0, 500.0) == pytest.approx(20.0)


def test_the_recovered_value_matches_an_independent_forward_computation():
    # 【目的】: 「Rwp·√(1−pSum/chisq)」が便利な代数変形であって近似ではないことを、
    #   分母 sumwYo を明示的に置いた素の定義から往復させて確かめる。
    sumw_yo = 12345.6
    chisq_data = 789.0
    penalty = 321.0
    chisq = chisq_data + penalty
    rwp_penalized = 100.0 * math.sqrt(chisq / sumw_yo)
    expected = 100.0 * math.sqrt(chisq_data / sumw_yo)

    assert data_term_rwp(rwp_penalized, chisq, penalty) == pytest.approx(expected, rel=1e-12)


def test_returns_the_original_rwp_when_there_is_no_penalty():
    # 【目的】: 拘束なし/無効 = **既定経路**。ビット同一で返ることが非回帰契約そのもの。
    for penalty in (0.0, -0.0, None, float("nan")):
        assert data_term_rwp(9.80617, 1234.5, penalty) == 9.80617


def test_returns_the_original_rwp_when_chisq_is_unavailable():
    # 【目的】: 情報が無いときに推測で補正しない (② 不変条件と同じ規律)。
    assert data_term_rwp(12.5, None, 3.0) == 12.5
    assert data_term_rwp(12.5, float("nan"), 3.0) == 12.5
    assert data_term_rwp(12.5, 0.0, 3.0) == 12.5


def test_does_not_subtract_when_the_penalty_is_not_inside_chisq():
    # 【目的】: **これが本命の罠**。GSAS は `RestraintSum` を dlg ゲートの**外**で報告するので、
    #   dlg を渡していない精密化でも巨大な値が載る (実測 4.66e9 に対し Rwp は 40% 相当)。
    #   引き算すると負の chisq = 定義域外になるので、引かずに元の値を返す。
    assert data_term_rwp(40.34906, 1500.0, 4.66e9) == 40.34906
    # ちょうど等しい (データ項 0 = あり得ない) も分離しない。
    assert data_term_rwp(40.0, 1500.0, 1500.0) == 40.0


def test_non_finite_rwp_passes_through_and_unreadable_rwp_is_none():
    # 【目的】: 失敗段の inf は revert 経路がそのまま扱う (分離で有限値に化けさせない)。
    assert data_term_rwp(float("inf"), 100.0, 10.0) is None  # 非有限は読めない値として None
    assert data_term_rwp("abc", 100.0, 10.0) is None


# ---------------------------------------------------------------------------
# RefinementDiagnostics — 読み出し層 (REQ-SAR-105) が分離材料を運ぶ
# ---------------------------------------------------------------------------


def test_diagnostics_carries_rwp_and_chisq_from_rvals():
    # 【目的】: 分離に要る 3 値 (Rwp / chisq / RestraintSum) を**同じ読み出し層**から出す。
    #   別の場所で Rvals を掘ると drift する (REQ-SAR-105 の趣旨)。
    d = diagnostics_from_cov_data(
        {"varyList": [], "Rvals": {"Rwp": 30.0, "chisq": 900.0, "RestraintSum": 500.0}}
    )

    assert d.rwp == pytest.approx(30.0)
    assert d.chisq == pytest.approx(900.0)
    assert d.restraint_sum == pytest.approx(500.0)
    assert d.data_rwp == pytest.approx(20.0)


def test_diagnostics_data_rwp_degenerates_without_restraints():
    d = diagnostics_from_cov_data({"varyList": [], "Rvals": {"Rwp": 9.80617, "chisq": 1234.5}})
    assert d.data_rwp == 9.80617


def test_diagnostics_to_dict_exposes_the_split():
    # 【目的】: ② 境界へ載る形 (JSON 化可能な素の型) で分離値が見えること。
    d = RefinementDiagnostics(rwp=30.0, chisq=900.0, restraint_sum=500.0)
    out = d.to_dict()

    assert out["rwp"] == pytest.approx(30.0)
    assert out["chisq"] == pytest.approx(900.0)
    assert out["data_rwp"] == pytest.approx(20.0)


def test_empty_diagnostics_has_no_rwp():
    # 【目的】: 共分散が無いときに 0.0 を捏造しない (「決まっていない」を潰さない規律)。
    d = RefinementDiagnostics()
    assert d.rwp is None and d.chisq is None and d.data_rwp is None


# ---------------------------------------------------------------------------
# engine._data_rwp — 分離のゲート (GSAS 依存部分を duck-typed スタブで固定)
# ---------------------------------------------------------------------------


class _FakeGpx:
    """`gpx.data["Covariance"]["data"]["Rvals"]` だけを持つ最小スタブ。"""

    def __init__(self, rvals: dict, *, exploding: bool = False) -> None:
        self._exploding = exploding
        self.data = {"Covariance": {"data": {"Rvals": rvals}}}

    def __getattribute__(self, name: str):
        if name == "data" and object.__getattribute__(self, "_exploding"):
            raise AssertionError("split=False なのに Covariance を読んだ (非回帰契約の違反)")
        return object.__getattribute__(self, name)


def test_data_rwp_does_not_touch_covariance_when_restraints_are_disabled():
    # 【目的】: **既定経路の非回帰契約**。分離が無効なら Rvals を 1 度も読まない = 新しい
    #   失敗点も新しい値も持ち込まない。読んだら即座に fail する gpx を渡して固定する。
    from tsumugin.autorietveld.engine import _data_rwp

    gpx = _FakeGpx({"Rwp": 30.0, "chisq": 900.0, "RestraintSum": 500.0}, exploding=True)

    assert _data_rwp(gpx, 9.80617, split=False) == (9.80617, None, 0.0)


def test_data_rwp_splits_when_restraints_are_enabled():
    from tsumugin.autorietveld.engine import _data_rwp

    gpx = _FakeGpx({"Rwp": 30.0, "chisq": 900.0, "RestraintSum": 500.0})
    data, penalized, penalty = _data_rwp(gpx, 30.0, split=True)

    assert data == pytest.approx(20.0)
    assert penalized == pytest.approx(30.0)  # 生値は捨てずに残す
    assert penalty == pytest.approx(500.0)


def test_data_rwp_reports_no_penalized_value_when_nothing_was_separated():
    # 【目的】: 有効化したが拘束が 1 つも無い (pSum=0) 場合、`rwp_penalized` は None のまま =
    #   「penalty 込みの値など存在しない」と正しく言える。0.0 差の偽物を作らない。
    from tsumugin.autorietveld.engine import _data_rwp

    gpx = _FakeGpx({"Rwp": 9.8, "chisq": 900.0, "RestraintSum": 0.0})
    assert _data_rwp(gpx, 9.8, split=True) == (9.8, None, 0.0)


def test_data_rwp_passes_through_non_finite_rwp():
    # 【目的】: 失敗段の inf は revert 経路の入力である。分離で有限値へ化けさせない。
    from tsumugin.autorietveld.engine import _data_rwp

    gpx = _FakeGpx({"Rwp": 30.0, "chisq": 900.0, "RestraintSum": 500.0}, exploding=True)
    data, penalized, penalty = _data_rwp(gpx, float("inf"), split=True)

    assert math.isinf(data) and penalized is None and penalty == 0.0


def test_data_rwp_degenerates_when_covariance_is_missing():
    # 【目的】: 共分散が無い精密化でも分離器が例外で本体を落とさない (fail open)。
    from tsumugin.autorietveld.engine import _data_rwp

    class _Empty:
        data: dict = {}

    assert _data_rwp(_Empty(), 12.0, split=True) == (12.0, None, 0.0)


# ---------------------------------------------------------------------------
# 報告値の意味 — final_rwp / StageResult.rwp は**データ項**であると固定する
# ---------------------------------------------------------------------------


def test_stage_result_defaults_to_no_penalized_value():
    # 【目的】: 既定 (拘束なし) では penalty 込みの値は**存在しない**。
    #   None を 0.0 で埋めると「penalty ゼロで拘束が効いた」と読めてしまう。
    s = StageResult(label="s", rwp=9.8, gof=1.2, n_params=10, converged=True)
    assert s.rwp_penalized is None


def test_result_defaults_keep_final_rwp_meaning_unchanged():
    # 【目的】: `final_rwp` は**常にデータ項**。拘束の有無で出版値の意味が切り替わらないこと。
    r = AutoRietveldResult(
        stage_results=(StageResult(label="s", rwp=9.8, gof=1.2, n_params=10, converged=True),),
        final_rwp=9.8,
        final_gof=1.2,
        refined_cells={},
        validity=ValidityReport(passed=True),
    )
    assert r.final_rwp == 9.8
    assert r.final_rwp_penalized is None
    assert r.final_restraint_penalty == 0.0
