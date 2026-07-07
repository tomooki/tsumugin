"""M10 run_anchored_sequential の実 GSAS 統合テスト (@pytest.mark.gsas)。

コミット済 CaTeO3 実測 2 フレーム (030 純 alpha / 180 転移) + ローカル alpha CIF + スクリプト
identifier で、アンカー抽出→区間→組立が実 GSAS ランナーで end-to-end 動作することを検証する。
全 14 フレーム + MP 自動同定 + crossover の実データ検証は
`scratchpad/run_anchored.py` (要 MATERIALS_PROJECT_API・長時間) で別途行う。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.model import Geometry, PhaseSpec, Radiation
from tsumugin.insitu import make_gsas_runner, run_anchored_sequential
from tsumugin.insitu.anchor.model import AnchorConfig
from tsumugin.insitu.model import FrameSpec

pytestmark = pytest.mark.gsas

CATEO3 = Path("docs/benchmark/testdata/m9/cateo3")


def _frames():
    return [
        FrameSpec(str(CATEO3 / "NB-LM01MO_030.XRDML"), axis_value=30.0,
                  data_format="XRDML", two_theta_limits=(12.0, 70.0)),
        FrameSpec(str(CATEO3 / "NB-LM01MO_180.XRDML"), axis_value=180.0,
                  data_format="XRDML", two_theta_limits=(12.0, 70.0)),
    ]


def test_anchored_runs_with_real_gsas():
    """実 GSAS で 2 フレームを anchored 解析: 030 を alpha アンカー、180 を前方パスで被覆。"""
    alpha = PhaseSpec(str(CATEO3 / "alpha_CaTeO3_H2O.cif"), "alpha", format_hint="CIF")
    runner = make_gsas_runner(
        instrument_path=str(CATEO3 / "cateo3_CuKa.instprm"),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
        max_cyc=8, background_coeffs=24,
    )

    # スクリプト identifier: 030=高信頼 alpha アンカー / 180=低信頼 (前方パスの内側フレーム)
    def identifier(frame):
        conf = 0.9 if frame.axis_value == 30.0 else 0.2
        return (conf, (alpha,))

    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=25.0)
    res = run_anchored_sequential(_frames(), [alpha], runner=runner,
                                  identifier=identifier, cfg=cfg)

    assert len(res.frames) == 2
    # 030 は alpha アンカー (実測 Rwp ~13%)
    f030 = res.frames[0]
    assert not f030.refine_failed and f030.rwp < 25.0
    assert "alpha" in f030.phase_names
    # 180 は前方パスで解かれ有限 Rwp (alpha 単相なので転移域は高いが finite)
    f180 = res.frames[1]
    assert not f180.refine_failed and f180.rwp < float("inf")
    # ledger 追記 + verify
    assert res.ledger is not None and res.ledger.verify()
