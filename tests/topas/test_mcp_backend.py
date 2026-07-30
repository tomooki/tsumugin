"""M12 T10: ② からのバックエンド選択 (★不変条件「③ が実際に呼べる」)。

CLAUDE.md の ★: **実装は必ず ②MCP と ③skill に露出させる — 実行者から見えない実装は「無い」と同じ**。
③ (LLM) は **JSON しか送れない**ので、`runner` callable は経路にならない。ここでは
「JSON 引数だけで TOPAS を選べるか」を検証する。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.mcp.rietveld_tools import auto_rietveld, list_refinement_backends
from tsumugin.mcp.tools import MCP_TOOLS


def _hist() -> dict:
    return HistogramSpec(
        data_path="d.xra",
        instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    ).to_dict()


def _phase() -> dict:
    return PhaseSpec(structure_path="p.cif", phase_name="P").to_dict()


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
