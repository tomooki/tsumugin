"""M9 実データ逐次 Rietveld 検証 (@pytest.mark.gsas, CaTeO3 は MP キー gate)。

配線 (end-to-end): 実 XRDML/fxye + 実 CIF を make_gsas_runner + run_sequential_rietveld で逐次実行し、
フレーム列が生成され・ウォームスタート格子が伝播し・ledger が verify() True になることを検証する。
Rwp 収束帯の締め上げは段階的 (README の honest status)。データ未同梱環境は skip。

データ: docs/benchmark/testdata/m9/ (取得手順は同ディレクトリ README)。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.gsas

_M9 = Path("docs/benchmark/testdata/m9")
_CATEO3 = _M9 / "cateo3"
_INSTR = _CATEO3 / "cateo3_CuKa.instprm"  # Cu Kα1 (Kα2-stripped HighScore data), broad W


def _have(*paths: Path) -> bool:
    return all(p.exists() for p in paths)


def _mp_key_available() -> bool:
    """MATERIALS_PROJECT_API が env か .env にあるか (delta 自動同定の MP アクセス可否)。"""
    if os.environ.get("MATERIALS_PROJECT_API"):
        return True
    env = Path(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("MATERIALS_PROJECT_API") and "=" in line:
                _, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault("MATERIALS_PROJECT_API", v.strip())
                    return True
    return False


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


@pytest.mark.skipif(
    not (
        _have(
            _CATEO3 / "NB-LM01MO_030.XRDML",
            _CATEO3 / "NB-LM01MO_180.XRDML",
            _CATEO3 / "alpha_CaTeO3_H2O.cif",
            _INSTR,
        )
        and _mp_key_available()
    ),
    reason="CaTeO3 データ + MATERIALS_PROJECT_API (env or .env) が必要 (delta 自動同定, README)",
)
@pytest.mark.parametrize("warm_start", [True, False], ids=["warm_start", "static"])
def test_cateo3_mp_gsas_auto_identifies_delta(warm_start):
    """2 フレーム逐次 (frame030 alpha 単相 → frame180 共存) で **MP から delta を自動同定・採用** する。

    Issue #28 T6-B の operando warm-start を実 MP+GSAS で end-to-end 検証する。frame180 の共存域で
    Materials Project から無水 CaTeO3 (delta, mp-1195263) が自動同定・物質化・追加され、相集合が
    ``(alpha, new_CaTeO3)`` に成長する。``warm_start`` は現行相 alpha を精密化格子付きで先に残差減算する
    か (B) 否か (A, identify-all-then-exclude) のスイッチ。両者とも delta を同定する (B は残差がクリーンで
    delta 定量・妥当性が良い; README の A/B 表参照)。ネットワーク + GSAS で数分要する gated テスト。

    注意: frame180 は転移共存フレームで絶対 Rwp は高い (~33%, preferred orientation + 水素 + 混合相;
    README honest status)。本テストは**自動同定の end-to-end 成立**を固定する (Rwp 収束帯は別テスト)。
    """
    from tsumugin.autorietveld.model import Geometry, PhaseSpec, Radiation
    from tsumugin.insitu import (
        FrameSpec,
        PhaseIdConfig,
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
    pid = PhaseIdConfig(
        elements=("Ca", "Te", "O"), top_k=3, frac_min=0.02, min_rwp_gain=0.01,
        refine_new_phase_cell=True, require_full_element_system=True,
        warm_start_known_phases=warm_start,
    )
    res = run_sequential_rietveld(frames, [alpha], runner=runner,
                                  config=SequentialConfig(warm_start=True, phase_id=pid))

    assert len(res.frames) == 2
    assert res.ledger.verify() is True
    assert res.frames[0].rwp < 18.0  # frame0 alpha 単相は ~12.6% (回帰上限 18%)
    # frame180 の共存域で delta (無水 CaTeO3) が自動同定・採用されている。
    delta_appearances = [a for a in res.appearances if a.evidence.get("formula") == "CaTeO3"]
    assert delta_appearances, f"delta 自動同定なし: appearances={res.appearances}"
    assert delta_appearances[0].source == "materials_project"
    assert "new_CaTeO3" in res.frames[1].phase_names  # 共存フレームに追加された
