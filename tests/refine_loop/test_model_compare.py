"""model_compare (BIC+妥当性のモデル比較オーケストレータ, REQ-005/202) の決定論テスト。"""

from __future__ import annotations

import dataclasses
import math

from tsumugin.autorietveld.compare import ModelVariant
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.model_compare import run_model_comparison
from tsumugin.store.ledger import Ledger


def _result(*, gof: float, k: int, n: int, passed: bool) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=gof * 0.5, gof=gof, n_params=k, converged=True),),
        final_rwp=gof * 0.5, final_gof=gof, refined_cells={},
        validity=ValidityReport(passed=passed), n_obs=n,
    )


def _phase(name: str) -> PhaseSpec:
    return PhaseSpec(f"{name}.cif", name)


def _hist() -> HistogramSpec:
    return HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                        geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")


def _variants():
    return (ModelVariant("model5", (_phase("model5"),)),
            ModelVariant("model6", (_phase("model6"),)))


def test_best_is_valid_min_bic_and_best_phases():
    results = {
        "model5": _result(gof=1.5, k=20, n=20000, passed=True),
        "model6": _result(gof=1.4, k=22, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    out = run_model_comparison([_hist()], _variants(), runner=stub)
    bic5 = 1.5**2 * (20000 - 20) + 20 * math.log(20000)
    bic6 = 1.4**2 * (20000 - 22) + 22 * math.log(20000)
    expected = "model6" if bic6 < bic5 else "model5"
    assert out.comparison.best == expected
    assert out.comparison.best_is_valid is True
    assert out.best_phases[0].phase_name == expected


def test_low_bic_but_invalid_not_best():
    results = {
        "model5": _result(gof=1.2, k=20, n=20000, passed=False),  # 最小BICだが非妥当
        "model6": _result(gof=1.45, k=20, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    out = run_model_comparison([_hist()], _variants(), runner=stub)
    assert out.comparison.best == "model6"
    assert out.comparison.best_is_valid is True
    assert out.best_phases[0].phase_name == "model6"


def test_all_invalid_fallback():
    results = {
        "model5": _result(gof=1.2, k=20, n=20000, passed=False),
        "model6": _result(gof=1.45, k=20, n=20000, passed=False),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    out = run_model_comparison([_hist()], _variants(), runner=stub)
    assert out.comparison.best == "model5"  # 全体最小BIC
    assert out.comparison.best_is_valid is False


def test_ledger_appended_and_verifies():
    results = {
        "model5": _result(gof=1.5, k=20, n=20000, passed=True),
        "model6": _result(gof=1.4, k=22, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    ledger = Ledger()
    out = run_model_comparison([_hist()], _variants(), runner=stub, ledger=ledger)
    assert out.ledger is ledger
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert kinds.count("model_compare_variant") == 2
    assert "model_compare_best" in kinds


def test_deterministic():
    results = {
        "model5": _result(gof=1.5, k=20, n=20000, passed=True),
        "model6": _result(gof=1.4, k=22, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    a = run_model_comparison([_hist()], _variants(), runner=stub)
    b = run_model_comparison([_hist()], _variants(), runner=stub)
    assert a.comparison.best == b.comparison.best
    assert [s.name for s in a.comparison.scores] == [s.name for s in b.comparison.scores]


def test_ledger_rows_say_where_each_variant_fit_is():
    """台帳の各バリアント行に、その fit の成果物パスが載る (棄却モデルも)。

    台帳はこの関数の監査出力であり、ΔBIC の根拠 (棄却側がどう壊れていたか) を後から開くための
    在処を `ModelScore.gpx_path` と同じ行に残す。行に無いと、数字だけが残って fit に辿れない。
    """
    paths = {"model5": "/runs/r1/model_model5.gpx", "model6": "/runs/r1/model_model6.gpx"}

    def stub(hists, phases, **kw):
        name = phases[0].phase_name
        res = _result(gof=1.5 if name == "model5" else 1.4, k=20, n=20000, passed=True)
        return dataclasses.replace(res, gpx_path=paths[name])

    ledger = Ledger()
    run_model_comparison([_hist()], _variants(), runner=stub, ledger=ledger)

    rows = {e.payload["name"]: e.payload for e in ledger.entries
            if e.kind == "model_compare_variant"}
    assert {name: row["gpx_path"] for name, row in rows.items()} == paths


def test_ledger_records_why_artifacts_fell_back_to_temp(tmp_path, monkeypatch):
    """保存先に書けず一時領域へ退避したら、その理由を台帳に残す (gpx-retention 設計 §5)。

    退避理由は `compare_models` の入口でしか分からず、`ModelComparison.warnings` に載って返る。
    台帳を受け取ったこの経路がそれを捨てると、頼んだ ``gpx_dir`` ではなく %TEMP% に置かれたことが
    監査記録のどこにも残らない。
    """
    import tempfile

    def unwritable(root, base):
        raise PermissionError(13, "read-only", root)

    monkeypatch.setattr("tsumugin.gpxstore._make_unique_dir", unwritable)
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))

    def stub(hists, phases, **kw):
        return _result(gof=1.5, k=20, n=20000, passed=True)

    ledger = Ledger()
    out = run_model_comparison(
        [_hist()], _variants(), runner=stub, ledger=ledger, gpx_dir=str(tmp_path / "chosen")
    )

    assert out.comparison.warnings, "前提: 退避が警告として返ること"
    rows = [e.payload for e in ledger.entries if e.kind == "model_compare_warning"]
    assert any("一時領域へ退避" in r["message"] for r in rows), rows
    assert ledger.verify() is True
