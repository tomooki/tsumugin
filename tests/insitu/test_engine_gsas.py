"""M9 実データ逐次 Rietveld 検証 (@pytest.mark.gsas, CaTeO3 は MP キー gate)。

配線 (end-to-end): 実 XRDML/fxye + 実 CIF を make_gsas_runner + run_sequential_rietveld で逐次実行し、
フレーム列が生成され・ウォームスタート格子が伝播し・ledger が verify() True になることを検証する。
Rwp 収束帯の締め上げは段階的 (README の honest status)。データ未同梱環境は skip。

データ: docs/benchmark/testdata/m9/ (取得手順は同ディレクトリ README)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gsas

_M9 = Path("docs/benchmark/testdata/m9")
_CATEO3 = _M9 / "cateo3"
_INSTR = Path("docs/benchmark/testdata/INST_XRY.PRM")


def _have(*paths: Path) -> bool:
    return all(p.exists() for p in paths)


@pytest.mark.skipif(
    not _have(
        _CATEO3 / "NB-LM01MO_030.XRDML",
        _CATEO3 / "NB-LM01MO_180.XRDML",
        _CATEO3 / "alpha_CaTeO3_H2O.cif",
        _INSTR,
    ),
    reason="M9 CaTeO3 検証データが未配置 (docs/benchmark/testdata/m9/cateo3 README 参照)",
)
def test_cateo3_two_frame_sequential_wiring():
    """CaTeO3 の 2 フレーム逐次 (alpha 単相): 配線・ウォームスタート・ledger を検証。

    Rwp 目標帯の締め上げ (~9%) は装置/背景/リミット調整後 (README honest status)。ここでは
    end-to-end が成立し有限 Rwp・格子伝播・ledger verify を返すことを回帰する。
    """
    from tsumugin.autorietveld.model import Geometry, PhaseSpec, Radiation
    from tsumugin.insitu import (
        FrameSpec,
        SequentialConfig,
        make_gsas_runner,
        run_sequential_rietveld,
    )

    frames = [
        FrameSpec(str(_CATEO3 / "NB-LM01MO_030.XRDML"), axis_value=30.0,
                  data_format="XRDML", two_theta_limits=(12.0, 70.0)),
        FrameSpec(str(_CATEO3 / "NB-LM01MO_180.XRDML"), axis_value=180.0,
                  data_format="XRDML", two_theta_limits=(12.0, 70.0)),
    ]
    alpha = PhaseSpec(str(_CATEO3 / "alpha_CaTeO3_H2O.cif"), "alpha", format_hint="CIF")
    runner = make_gsas_runner(
        instrument_path=str(_INSTR), radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO, max_cyc=8,
    )
    res = run_sequential_rietveld(frames, [alpha], runner=runner,
                                  config=SequentialConfig(warm_start=True))

    assert len(res.frames) == 2
    # end-to-end 成立: 有限 Rwp・alpha 格子が各フレームに存在・ledger 追記整合
    for f in res.frames:
        assert f.rwp < float("inf")
        assert "alpha" in f.refined_cells
        assert f.refined_cells["alpha"][0] > 1.0  # 格子崩壊していない
    assert res.ledger.verify() is True
    # 目標帯 (段階的に締める): 現状は end-to-end の緩い上限のみ。
    assert res.frames[0].rwp < 100.0


@pytest.mark.skip(
    reason="Rwp 収束帯 (~9%) は装置プロファイル/背景/真空間群 CIF の調整後に有効化 (README honest status)"
)
def test_cateo3_full_series_auto_identifies_delta():
    """全 14 フレーム逐次で delta 無水相が転移域で自動同定・採用される (MP キー gate)。

    有効化条件: MATERIALS_PROJECT_API 設定 + 全フレーム配置 + 装置/背景調整で frame0 Rwp を目標帯へ。
    目標: 各フレーム wRp ≲ 10%、appearances に delta が転移フレームで出現。
    """
    raise AssertionError("未有効化 (README honest status)")
