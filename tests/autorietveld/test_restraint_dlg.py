"""restraint 有効化用 ``dlg`` スタブの契約 (REQ-SAR-203) — GSAS 非依存。

このスタブは GSAS-II の**内部分岐に合わせて作られている**。契約を 1 つ崩すと、例外ではなく
「拘束が効かない」「精密化が黙って中断する」といった**静かな失敗**になるので、各項目を
ソース根拠つきで固定する (`GSASIIstrMath.errRefine` / `GSASIIstrMain`)。

engine 側の注入 (`_capture_refine_status(dlg=…)`) は偽の Refine で検証する — GSAS 本体は不要。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.engine import _capture_refine_status
from tsumugin.autorietveld.restraint_dlg import RefineProgressStub


# ---------------------------------------------------------------------------
# スタブ契約 (GSAS-II ソースから確定)
# ---------------------------------------------------------------------------


def test_update_returns_a_tuple_whose_first_element_is_truthy():
    # 【根拠】: errRefine:5017-5023 は `type(GoOn) is tuple` なら GoOn[0] を、そうでなければ
    #   GoOn 自体を真偽判定する。strMain.AllPrmDerivs:210 は `dlg.Update(i)[0]` と**添字**を取る。
    #   タプルなら両方を満たす。偽を返すと G2RefineCancel で精密化が中断する。
    out = RefineProgressStub().Update(42, newmsg="hello")
    assert isinstance(out, tuple), "添字を取る呼び出し側 (AllPrmDerivs:210) が壊れる"
    assert out[0] is True, "偽を返すと GSAS は G2RefineCancel を投げて精密化を中断する"


def test_update_is_callable_without_a_message():
    # 【根拠】: strMain:210 は `dlg.Update(i)` と newmsg 無しで呼ぶ。
    assert RefineProgressStub().Update(0)[0] is True


def test_set_range_exists_and_is_a_noop():
    # 【根拠】: strMain:207 `if dlg: dlg.SetRange(len(origParms))`。値は使われない。
    stub = RefineProgressStub()
    stub.SetRange(123)
    assert stub.ranges == 1


def test_set_histogram_is_deliberately_absent():
    # 【根拠】: errRefine:4973 等の呼び出しは全て `hasattr(dlg,'SetHistogram')` ガード付き。
    #   実装すると余計な状態を抱えるだけで、GSAS 側の動作は変わらない。
    assert not hasattr(RefineProgressStub(), "SetHistogram")


def test_type_name_must_not_contain_g2():
    # 【根拠】: errRefine:5015 `if 'G2' in str(type(dlg))` が真だと wx の G2 ダイアログ専用経路
    #   (Update に float を渡す) へ分岐する。**クラス名にもモジュールパスにも "G2" を入れない**。
    #   ここが崩れると例外ではなく静かな挙動差になるので、型名そのものを固定する。
    assert "G2" not in str(type(RefineProgressStub()))


def test_message_history_is_bounded():
    # 【目的】: 精密化 1 回で数千回呼ばれる。全部溜めると診断が主記憶を食う。
    stub = RefineProgressStub()
    for i in range(1000):
        stub.Update(i, newmsg=f"m{i}")
    assert stub.updates == 1000
    assert stub.last_message == "m999"


# ---------------------------------------------------------------------------
# engine 側の注入 (`GSASIIstrMain.Refine(dlg=…)`)
# ---------------------------------------------------------------------------


class _FakeStrMain:
    """`GSASIIstrMain` の代役 — Refine が受け取った引数を記録するだけ。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def Refine(self, *args, **kwargs):  # noqa: N802 — GSAS 側の呼び名
        self.calls.append((args, kwargs))
        return (True, {})


def test_no_dlg_is_injected_by_default():
    # 【目的】: 非回帰契約。既定では `Refine` の呼び出しが現行と 1 バイトも変わらない。
    mod = _FakeStrMain()
    with _capture_refine_status(mod):
        mod.Refine("proj.gpx", makeBack=False)
    assert "dlg" not in mod.calls[0][1]


def test_stub_is_injected_as_a_keyword_when_requested():
    mod = _FakeStrMain()
    stub = RefineProgressStub()
    with _capture_refine_status(mod, dlg=stub):
        mod.Refine("proj.gpx", makeBack=False)
    assert mod.calls[0][1]["dlg"] is stub


@pytest.mark.parametrize(
    "args,kwargs",
    [
        (("proj.gpx", None), {}),  # dlg を位置引数で渡す内部呼び出し (allDerivs 経路)
        (("proj.gpx",), {"dlg": None}),  # 明示キーワード
    ],
)
def test_an_explicit_dlg_argument_is_never_overwritten(args, kwargs):
    # 【目的】: GSAS 内部の `Refine(self.filename, None, allDerivs=True)` (scriptable:3354) の
    #   ような別用途を壊さない。**既に決まっている引数を勝手に書き換えない**。
    mod = _FakeStrMain()
    with _capture_refine_status(mod, dlg=RefineProgressStub()):
        mod.Refine(*args, **kwargs)
    got_args, got_kwargs = mod.calls[0]
    assert got_args == args and got_kwargs.get("dlg") is None


def test_injection_is_undone_when_the_scope_exits():
    # 【目的】: scoped patch であること (グローバル汚染で他の精密化へ拘束が漏れない)。
    #   スコープを抜けたら dlg を注入しない元の Refine に戻る。
    mod = _FakeStrMain()
    with _capture_refine_status(mod, dlg=RefineProgressStub()):
        mod.Refine("inside.gpx")
    mod.Refine("outside.gpx")
    assert "dlg" in mod.calls[0][1]
    assert "dlg" not in mod.calls[1][1], "スコープ外の精密化にまで拘束が漏れている"


def test_failure_return_is_still_captured_with_the_stub():
    # 【目的】: dlg 有りだと Refine は成功時に (True, Rvals) を返す (無指定時は暗黙 None)。
    #   失敗検出 (無言失敗ガード) がスタブ経路でも同じように働くこと。
    mod = _FakeStrMain()
    mod.Refine = lambda *a, **k: (False, {"msg": "singular matrix"})  # type: ignore[method-assign]
    with _capture_refine_status(mod, dlg=RefineProgressStub()) as status:
        mod.Refine("proj.gpx")
    assert status["ok"] is False and "singular matrix" in str(status["msg"])
