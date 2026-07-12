"""make_gsas_runner が FrameSpec.excluded_regions を HistogramSpec へ伝播するかのテスト (Issue #53)。

run_auto_rietveld を monkeypatch し、build_recipe/GSAS 呼び出しを避けつつ、runner が組み立てた
HistogramSpec.excluded_regions を捕捉して検証する (GSAS/MP 非依存)。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    PhaseSpec,
    Radiation,
    ValidityReport,
)
from tsumugin.insitu.engine import make_gsas_runner
from tsumugin.insitu.model import FrameSpec


def test_make_gsas_runner_propagates_excluded_regions(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_auto_rietveld(histograms, phases, **kwargs):
        captured["excluded_regions"] = histograms[0].excluded_regions
        return AutoRietveldResult(
            stage_results=(),
            final_rwp=9.0,
            final_gof=1.0,
            refined_cells={},
            validity=ValidityReport(passed=True),
        )

    monkeypatch.setattr(
        "tsumugin.autorietveld.engine.run_auto_rietveld", fake_run_auto_rietveld
    )

    runner = make_gsas_runner(
        instrument_path="i.instprm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    frame = FrameSpec(
        data_path="f0.xye",
        data_format="XYE",
        two_theta_limits=(2.4, 18.0),
        excluded_regions=((7.9, 8.3),),
    )
    phase = PhaseSpec(structure_path="p.cif", phase_name="p")

    runner(frame, [phase], None)

    assert captured["excluded_regions"] == ((7.9, 8.3),)
