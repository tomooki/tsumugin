"""② compare_structure_models (構造モデル BIC 比較) の MCP 露出テスト (Issue #100)。

compare_models (XND) は callable 制約が無い (runner 既定が実装関数) のに ② 未露出だった。
Ow 要否 (model5 vs model6) の ΔBIC 判定を ③ に露出する。runner はスタブ注入で決定論テスト。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.mcp.compare_tools import COMPARE_TOOLS, compare_structure_models


def _hist() -> dict:
    return HistogramSpec(
        data_path="d.xye",
        instrument_path="i.instprm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    ).to_dict()


def _variant(name: str, phase_names: list[str]) -> dict:
    return {
        "name": name,
        "phases": [PhaseSpec(structure_path=f"{n}.cif", phase_name=n).to_dict() for n in phase_names],
    }


def _make_runner(rwp_by_nphases: dict[int, float]):
    """相数に応じた Rwp/段階を返すスタブ (相が多い方が Rwp 低 = BIC で母数罰を効かせる)。"""

    def runner(histograms, phases, **kw) -> AutoRietveldResult:
        n = len(phases)
        rwp = rwp_by_nphases[n]
        return AutoRietveldResult(
            stage_results=(
                StageResult(
                    label="final", rwp=rwp, gof=rwp / 6.0, n_params=10 + 12 * n,
                    converged=True, reverted=False,
                ),
            ),
            final_rwp=rwp,
            final_gof=rwp / 6.0,
            refined_cells={p.phase_name: (10.0,) * 3 + (90.0,) * 3 for p in phases},
            validity=ValidityReport(passed=True),
            phase_fractions={p.phase_name: 1.0 / n for p in phases},
            n_obs=2000,
        )

    return runner


def test_compare_tools_registry():
    assert COMPARE_TOOLS == {"compare_structure_models": compare_structure_models}


def test_compare_structure_models_ranks_by_bic():
    """2 バリアントを BIC 昇順で序列化し best/scores/delta_bic を返すこと。"""
    out = compare_structure_models(
        [_hist()],
        [_variant("model5", ["host"]), _variant("model6", ["host", "ow"])],
        runner=_make_runner({1: 12.0, 2: 8.0}),
    )
    assert "error" not in out
    assert {s["name"] for s in out["scores"]} == {"model5", "model6"}
    assert out["scores"][0]["delta_bic"] == 0.0  # 先頭 = 最良 (ΔBIC 基準点)
    assert all("bic" in s and "delta_bic" in s for s in out["scores"])
    assert out["best"] in {"model5", "model6"}


def test_compare_structure_models_prefers_valid_model():
    """best は物理妥当なモデルのうち最小 BIC (妥当性を無視しない)。"""

    def runner(histograms, phases, **kw):
        n = len(phases)
        # 相が多い方が Rwp は低い (BIC 有利) が妥当性 fail にする → best は妥当な単相側
        passed = n == 1
        return AutoRietveldResult(
            stage_results=(
                StageResult(label="f", rwp=8.0 if n == 2 else 11.0, gof=1.0, n_params=10 + 12 * n,
                            converged=True, reverted=False),
            ),
            final_rwp=8.0 if n == 2 else 11.0,
            final_gof=1.0,
            refined_cells={},
            validity=ValidityReport(passed=passed),
            n_obs=2000,
        )

    out = compare_structure_models(
        [_hist()],
        [_variant("valid1", ["a"]), _variant("invalid2", ["a", "b"])],
        runner=runner,
    )
    assert out["best"] == "valid1"
    assert out["best_is_valid"] is True


def test_compare_structure_models_empty_variants_returns_error_dict():
    out = compare_structure_models([_hist()], [], runner=_make_runner({1: 8.0}))
    assert "error" in out
    assert "error_type" in out


def test_compare_structure_models_bad_variant_shape_returns_error_dict():
    """variant に 'phases' キーが無い → error dict (③ の JSON 組み立てミスを縮退)。"""
    out = compare_structure_models(
        [_hist()], [{"name": "broken"}], runner=_make_runner({1: 8.0})
    )
    assert "error" in out
    assert "error_type" in out


def test_compare_structure_models_registered_in_mcp_tools():
    from tsumugin.mcp.tools import MCP_TOOLS

    assert "compare_structure_models" in MCP_TOOLS
    assert MCP_TOOLS["compare_structure_models"] is compare_structure_models
