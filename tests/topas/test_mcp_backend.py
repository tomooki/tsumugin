"""M12 T10: ② からのバックエンド選択 (★不変条件「③ が実際に呼べる」)。

CLAUDE.md の ★: **実装は必ず ②MCP と ③skill に露出させる — 実行者から見えない実装は「無い」と同じ**。
③ (LLM) は **JSON しか送れない**ので、`runner` callable は経路にならない。ここでは
「JSON 引数だけで TOPAS を選べるか」を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.mcp.rietveld_tools import auto_rietveld, list_refinement_backends
from tsumugin.mcp.tools import MCP_TOOLS


def _hist() -> dict:
    return HistogramSpec(
        data_path=str(_DATA[0]),
        instrument_path=str(_DATA[1]),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    ).to_dict()


#: 実データ (gitignore 対象) に依存しないよう合成 CIF を使う。スタブ経路では
#: 構造ファイルは「読めること」しか要らない。
_SYNTHETIC: "Path | None" = None


_DATA: "tuple[Path, Path] | None" = None


@pytest.fixture(autouse=True)
def _use_synthetic_cif(synthetic_cif, synthetic_data):
    global _SYNTHETIC, _DATA
    _SYNTHETIC, _DATA = synthetic_cif, synthetic_data
    yield
    _SYNTHETIC = _DATA = None


def _phase() -> dict:
    assert _SYNTHETIC is not None
    return PhaseSpec(structure_path=str(_SYNTHETIC), phase_name="P").to_dict()


# ---------------- list_refinement_backends ----------------


def test_tool_is_registered():
    assert "list_refinement_backends" in MCP_TOOLS


def test_lists_both_engines_with_availability():
    out = list_refinement_backends()
    assert set(out["backends"]) == {"gsasii", "topas"}
    for info in out["backends"].values():
        assert isinstance(info["available"], bool)
    assert out["default"] == "gsasii"


def test_topas_entry_carries_the_resolved_path_or_a_hint():
    """③ が「なぜ使えないか」を読めること (未導入なら導入方法を示す)。"""
    topas = list_refinement_backends()["backends"]["topas"]
    if topas["available"]:
        assert topas["tc_path"] and topas["home"]
    else:
        assert "TSUMUGIN_TOPAS_PATH" in topas["hint"]


def test_result_is_json_safe():
    import json

    json.dumps(list_refinement_backends(), allow_nan=False)


def test_disabled_topas_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", "none")
    assert list_refinement_backends()["backends"]["topas"]["available"] is False


# ---------------- backend 引数 ----------------


def test_backend_argument_selects_the_topas_engine(monkeypatch):
    """**JSON 引数だけ**で TOPAS 経路に入ること (callable の runner を使わない)。"""
    seen: dict = {}

    def fake_topas(histograms, phases, **kwargs):
        seen["called"] = True
        from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport

        return AutoRietveldResult(
            stage_results=(StageResult(label="S0", rwp=9.0, gof=1.2, n_params=5, converged=True),),
            final_rwp=9.0,
            final_gof=1.2,
            refined_cells={},
            validity=ValidityReport(passed=True),
            backend="topas",
        )

    monkeypatch.setattr("tsumugin.topas.engine.run_topas_rietveld", fake_topas)
    out = auto_rietveld([_hist()], [_phase()], backend="topas")
    assert seen.get("called") is True
    assert out["backend"] == "topas"  # 出所が結果に出る


def test_default_backend_is_gsasii(monkeypatch):
    """既定は据え置き (非回帰)。"""
    seen: dict = {}

    def fake_gsas(histograms, phases, **kwargs):
        seen["called"] = True
        from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport

        return AutoRietveldResult(
            stage_results=(StageResult(label="S0", rwp=9.0, gof=1.2, n_params=5, converged=True),),
            final_rwp=9.0, final_gof=1.2, refined_cells={},
            validity=ValidityReport(passed=True),
        )

    # 解決はパッケージ属性経由 (既存の注入経路を壊さないため — backends.resolve_backend 参照)。
    monkeypatch.setattr("tsumugin.autorietveld.run_auto_rietveld", fake_gsas)
    out = auto_rietveld([_hist()], [_phase()])
    assert seen.get("called") is True
    assert out["backend"] == "gsasii"


def test_unknown_backend_degrades_to_an_error_dict():
    """**綴り間違いを既定へ黙って落とさない** — 意図と違うエンジンで回った結果に気づけなくなる。

    かつ ② は例外を送出しない (③ は LLM なので例外は回復不能なハード失敗になる)。
    """
    out = auto_rietveld([_hist()], [_phase()], backend="topaz")
    assert "error" in out and out["error_type"] == "UnknownBackendError"
    assert "topaz" in out["error"]


def test_unknown_backend_does_not_raise():
    try:
        auto_rietveld([_hist()], [_phase()], backend="nope")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"② は例外を送出してはならない: {exc!r}")


def test_backend_argument_is_reachable_from_the_tool_signature():
    """③ から見た到達可能性: 引数が署名にあり JSON で渡せる型であること。"""
    import inspect

    signature = inspect.signature(MCP_TOOLS["auto_rietveld"])
    assert "backend" in signature.parameters
    assert signature.parameters["backend"].default == "gsasii"


def test_refine_with_revisions_also_takes_backend():
    """反復経路でもエンジンを選べること (片方だけだと途中で GSAS に戻る)。"""
    import inspect

    signature = inspect.signature(MCP_TOOLS["refine_with_revisions"])
    assert "backend" in signature.parameters


def test_backend_with_search_is_refused_rather_than_silently_using_gsas():
    """探索経路は backend を運べない。**黙って GSAS で回さず**明示的に断る。

    黙って落とすと「頼んだのと違うエンジンで回った結果」が `backend` キーだけ正しく見える。
    """
    out = auto_rietveld([_hist()], [_phase()], backend="topas", search=True)
    assert out["error_type"] == "UnsupportedBackendCombination"
    assert "search" in out["error"]


def test_backend_with_multistart_is_refused():
    out = auto_rietveld([_hist()], [_phase()], backend="topas", multistart={"n_starts": 3})
    assert out["error_type"] == "UnsupportedBackendCombination"


def test_default_backend_with_search_is_unaffected(monkeypatch):
    """既定 (gsasii) の探索経路は従来どおり通ること (非回帰)。"""
    called: dict = {}

    def fake_search(inp, names, cfg, max_cyc, opts, runner):
        called["ok"] = True
        return {"search": {"names": list(names)}}

    monkeypatch.setattr("tsumugin.mcp.rietveld_tools._run_search", fake_search)
    auto_rietveld([_hist()], [_phase()], search=True)
    assert called.get("ok") is True


def test_topas_backend_uses_the_topas_recipe_not_the_gsas_one(monkeypatch):
    """**エンジンだけ差し替えてレシピを共有しない**。

    GSAS 順 (格子が先) を TOPAS へ渡すと、格子がピーク幅の不一致を吸収して悪化する
    (実測 garnet: 23.6% 頭打ち)。② 経由でもバックエンド用のレシピが使われること。
    """
    seen: dict = {}

    def fake_topas(histograms, phases, **kwargs):
        seen["labels"] = [s.label for s in kwargs["recipe"]]
        from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport

        return AutoRietveldResult(
            stage_results=(StageResult(label="S", rwp=9.0, gof=1.2, n_params=3, converged=True),),
            final_rwp=9.0, final_gof=1.2, refined_cells={},
            validity=ValidityReport(passed=True), backend="topas",
        )

    monkeypatch.setattr("tsumugin.topas.engine.run_topas_rietveld", fake_topas)
    auto_rietveld([_hist()], [_phase()], backend="topas")
    order = seen["labels"]
    assert any("profile" in x for x in order)
    profile_at = next(i for i, x in enumerate(order) if "profile" in x)
    cell_at = next(i for i, x in enumerate(order) if "cell" in x)
    assert profile_at < cell_at, f"TOPAS 用の順序になっていない: {order}"


def test_stability_is_not_silently_dropped_by_the_topas_engine():
    """TOPAS は stability ゲート未実装。**黙って捨てず**警告として結果に出す。"""
    from tsumugin.autorietveld.model import StabilityOptions
    from tsumugin.topas.engine import run_topas_rietveld

    import tsumugin.topas.engine as eng

    class _R:
        out_text = "r_p 1 r_wp 9.0 r_exp 5 gof 1.2\np 1.0`_0.01\n"
        results_text = "r_wp\t9.0\ngof\t1.2\n"
        stdout = ""

    original = eng.run_tc
    eng.run_tc = lambda *a, **k: _R()
    try:
        from tsumugin.autorietveld.model import RefinementStage

        result = run_topas_rietveld(
            [HistogramSpec(data_path=str(_DATA[0]), instrument_path=str(_DATA[1]),
                           radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                           data_format="XYE")],
            [PhaseSpec(structure_path=str(_SYNTHETIC), phase_name="P")],
            recipe=(RefinementStage(label="S0", flags={}),),
            stability=StabilityOptions(require_convergence=True),
        )
    finally:
        eng.run_tc = original
    assert any("stability" in w for w in result.validity.warnings)


@pytest.mark.parametrize("spelling", [None, "GSASII", "Gsasii", " gsasii "])
def test_default_backend_spellings_are_not_refused_with_search(spelling, monkeypatch):
    """**比較は正規化を通す**。解決系が正規化しているのに生文字列で比べると、
    `null` (JSON) や大小違いの既定指定が「既定でない」と判定され誤って拒否される。
    """
    called: dict = {}

    def fake_search(inp, names, cfg, max_cyc, opts, runner):
        called["ok"] = True
        return {"search": {}}

    monkeypatch.setattr("tsumugin.mcp.rietveld_tools._run_search", fake_search)
    out = auto_rietveld([_hist()], [_phase()], backend=spelling, search=True)
    assert out.get("error_type") != "UnsupportedBackendCombination", out
    assert called.get("ok") is True


def test_phase_fractions_are_populated_from_scale():
    """`phase_fractions` は Scale 正規化。空だと相分率の不一致検査が静かに空振りする。"""
    import tsumugin.topas.engine as eng
    from tsumugin.autorietveld.model import RefinementStage

    class _R:
        out_text = "r_p 1 r_wp 9.0 r_exp 5 gof 1.2\np 1.0`_0.01\n"
        results_text = (
            "r_wp\t9.0\ngof\t1.2\n"
            "scale_val\tA\t0.0003\t1e-06\n"
            "scale_val\tB\t0.0001\t1e-06\n"
        )
        stdout = ""

    original = eng.run_tc
    eng.run_tc = lambda *a, **k: _R()
    try:
        result = eng.run_topas_rietveld(
            [HistogramSpec(data_path=str(_DATA[0]), instrument_path=str(_DATA[1]),
                           radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                           data_format="XYE")],
            [PhaseSpec(structure_path=str(_SYNTHETIC), phase_name="PbSO4")],
            recipe=(RefinementStage(label="S0", flags={}),),
        )
    finally:
        eng.run_tc = original
    assert result.phase_fractions == {"A": pytest.approx(0.75), "B": pytest.approx(0.25)}
