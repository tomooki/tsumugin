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
_INSTR = _CATEO3 / "cateo3_CuKa.instprm"  # Cu Kα1 (Kα2-stripped HighScore data), broad W


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
def test_cateo3_two_frame_sequential_converges():
    """CaTeO3 の 2 フレーム逐次 (alpha 単相): 配線・ウォームスタート・ledger + Rwp 収束を検証。

    調整済み設定 (Kα1-only instprm・背景 24 項・標準セッティング CIF・X/Y/Zero プロファイル解放) で
    frame0 Rwp ~13% (LeBail 到達可能 12.7%, チュートリアル 9.4%)。GOF ~1.4。
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
        geometry=Geometry.BRAGG_BRENTANO, max_cyc=20, background_coeffs=24,
    )
    res = run_sequential_rietveld(frames, [alpha], runner=runner,
                                  config=SequentialConfig(warm_start=True))

    assert len(res.frames) == 2
    for f in res.frames:
        assert "alpha" in f.refined_cells
        assert f.refined_cells["alpha"][0] > 1.0  # 格子崩壊していない
    assert res.ledger.verify() is True
    # Rwp 収束帯: frame0 は調整済み設定で ~13% (LeBail 12.7% 近傍)。回帰上限 18%。
    assert res.frames[0].rwp < 18.0, f"frame0 Rwp={res.frames[0].rwp}"


@pytest.mark.skip(
    reason="全 14 フレーム + delta 自動同定は MATERIALS_PROJECT_API + 全フレーム配置が必要 (README)"
)
def test_cateo3_full_series_auto_identifies_delta():
    """全 14 フレーム逐次で delta 無水相が転移域で自動同定・採用される (MP キー gate)。

    有効化条件: MATERIALS_PROJECT_API 設定 + 全 14 フレーム配置。目標: 各フレーム wRp ≲ 15%、
    appearances に delta が転移フレーム (150–300) で出現。
    """
    raise AssertionError("未有効化 (README honest status)")
