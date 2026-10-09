"""② 実行系ツールの I/O 例外縮退 (@degrade_oserror, Issue #94) のテスト。

存在しないファイルパス等で GSAS/ローダーが投げる FileNotFoundError が MCP 境界を越えると ③ (LLM)
にとって回復不能なハード失敗になる。実行系ツールは OSError を {"error","error_type"} へ縮退する。
runner を「FileNotFoundError を投げる」スタブにして GSAS 非依存に決定論検証する (実測: 縮退前は
auto_rietveld/sequential_rietveld/anchored_sequential が FileNotFoundError を送出していた)。
"""

from __future__ import annotations

import inspect

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.insitu.model import FrameSpec
from tsumugin.mcp._degrade import degrade_oserror
from tsumugin.mcp.anchor_tools import anchored_sequential
from tsumugin.mcp.compare_tools import compare_structure_models
from tsumugin.mcp.insitu_tools import sequential_rietveld
from tsumugin.mcp.rietveld_tools import auto_rietveld


def _boom(*args, **kwargs):
    raise FileNotFoundError("missing input file: data.xye")


_H = HistogramSpec(
    data_path="d.xye", instrument_path="i.instprm",
    radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
).to_dict()
_P = PhaseSpec(structure_path="a.cif", phase_name="a").to_dict()
_F = FrameSpec(data_path="f0.xye", axis_value=0.0).to_dict()


def _assert_degraded(out):
    assert isinstance(out, dict)
    assert out.get("error_type") == "FileNotFoundError"
    assert "data.xye" in out["error"]


def test_auto_rietveld_degrades_file_not_found():
    _assert_degraded(auto_rietveld([_H], [_P], runner=_boom))


def test_sequential_rietveld_degrades_file_not_found():
    _assert_degraded(sequential_rietveld([_F], [_P], runner=_boom))


def test_anchored_sequential_degrades_file_not_found():
    _assert_degraded(
        anchored_sequential([_F], [_P], anchor_table={"0": ["a"]}, runner=_boom)
    )


def test_compare_structure_models_degrades_file_not_found():
    variants = [{"name": "m", "phases": [_P]}]
    _assert_degraded(compare_structure_models([_H], variants, runner=_boom))


def test_mem_density_degrades_oserror(monkeypatch, tmp_path):
    """mem_density は実行本体 (run_dysnomia_mem) の OSError も縮退する。"""
    from tsumugin.mcp.mem_tools import mem_density

    gpx = tmp_path / "done.gpx"
    gpx.write_text("stub")
    monkeypatch.setattr(
        "tsumugin.mem.gsas.run_dysnomia_mem",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("missing .grd")),
    )
    out = mem_density(str(gpx))
    assert out["error_type"] == "FileNotFoundError"


# --- degrade_oserror デコレータ単体 ---


def test_degrade_oserror_passes_through_normal_return():
    @degrade_oserror
    def ok(x):
        return {"value": x}

    assert ok(3) == {"value": 3}


def test_degrade_oserror_converts_oserror_to_dict():
    @degrade_oserror
    def bad():
        raise PermissionError("denied")

    out = bad()
    assert out == {"error": "denied", "error_type": "PermissionError"}


def test_degrade_oserror_does_not_swallow_non_oserror():
    """OSError とドメインエラー (TsumuginError) 以外 = 論理バグは透過させる — 握り潰さない。"""

    @degrade_oserror
    def logic_bug():
        raise ValueError("this is a real bug")

    with pytest.raises(ValueError, match="real bug"):
        logic_bug()


def test_degrade_oserror_preserves_signature():
    """inspect.signature が元シグネチャを辿ること (server.py の session 判定が壊れない)。"""

    @degrade_oserror
    def tool(session, x, *, y=1):
        return {}

    params = list(inspect.signature(tool).parameters)
    assert params == ["session", "x", "y"]
    # unwrap で元関数へ到達できる (layer_coverage の AST 網が依存)
    assert inspect.unwrap(tool).__name__ == "tool"


# --- 相の指定の誤り (InvalidPhaseSpecError) — 精密化の前の入力の誤り ---


def _refuse(*args, **kwargs):
    from tsumugin.errors import InvalidPhaseSpecError

    raise InvalidPhaseSpecError(
        "相 'a': 相に無い原子ラベルがあります: {'frozen_uiso_labels': ['Ox']}"
    )


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: auto_rietveld([_H], [_P], runner=_refuse), id="auto_rietveld"),
        pytest.param(
            lambda: auto_rietveld([_H], [_P], search=["default"], search_runner=_refuse),
            id="auto_rietveld-search",
        ),
        pytest.param(
            lambda: auto_rietveld([_H], [_P], multistart={"n_starts": 2}, search_runner=_refuse),
            id="auto_rietveld-multistart",
        ),
        pytest.param(lambda: sequential_rietveld([_F], [_P], runner=_refuse), id="sequential"),
        pytest.param(
            lambda: anchored_sequential([_F], [_P], anchor_table={"0": ["a"]}, runner=_refuse),
            id="anchored_sequential",
        ),
        pytest.param(
            lambda: compare_structure_models([_H], [{"name": "m", "phases": [_P]}], runner=_refuse),
            id="compare_structure_models",
        ),
    ],
)
def test_tools_degrade_a_phase_spec_error(call):
    """GSAS 経路は相を読んで原子ラベルが分かった時点で相の指定を検査する (`check_phase_spec_labels`)。
    逐次系ではそれが最初のフレームを回す中なので、入力の解析を囲む try では捕まらない。
    探索・収束確認は**候補の失敗・発散に畳まずに** InvalidPhaseSpecError として返す
    (畳むと ③ は綴りではなく手順や構造を疑う)。"""
    out = call()
    assert isinstance(out, dict)
    assert out.get("error_type") == "InvalidPhaseSpecError", out
    assert "Ox" in out["error"]


def test_sequential_rietveld_degrades_other_domain_errors():
    """逐次系は GSAS を入力解析の try の外で回すので、GSAS 未導入などのドメインエラーも
    ここで縮退しないと ② を越える (`_run_degrading_domain_errors` と同じ線引き)。"""
    from tsumugin.errors import GSASUnavailableError

    def _no_gsas(*a, **k):
        raise GSASUnavailableError("GSAS-II が見つかりません")

    out = sequential_rietveld([_F], [_P], runner=_no_gsas)
    assert out.get("error_type") == "GSASUnavailableError", out


def test_degrade_oserror_converts_a_phase_spec_error_to_dict():
    @degrade_oserror
    def bad():
        _refuse()

    assert bad()["error_type"] == "InvalidPhaseSpecError"
