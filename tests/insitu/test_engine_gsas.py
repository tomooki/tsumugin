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

    # ★規定「全解析で gpx を全部保存する」(2026-08-20) が**実 GSAS で**成立していること。
    # 決定論テスト (tests/insitu/test_gpx_series.py) はスタブ runner で文脈の配線しか見ない —
    # 実際にファイルが出来ることはここでしか確かめられない。
    from tsumugin.gpxstore import read_manifest

    assert res.gpx_dir and Path(res.gpx_dir).is_dir(), res.gpx_dir
    saved = [Path(f.gpx_path) for f in res.frames]
    assert all(p.is_file() and p.stat().st_size > 0 for p in saved), [str(p) for p in saved]
    assert [p.name for p in saved] == ["f0000_frame.gpx", "f0001_frame.gpx"]
    entries = read_manifest(res.gpx_dir)
    assert len(entries) == 2 and {e["role"] for e in entries} == {"frame"}
    assert entries[0]["rwp"] == pytest.approx(res.frames[0].rwp)


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
@pytest.mark.parametrize(
    "warm_start",
    [
        pytest.param(True, id="warm_start"),
        pytest.param(False, id="static"),
    ],
)
def test_cateo3_mp_gsas_auto_identifies_delta(warm_start):
    """2 フレーム逐次 (frame030 alpha 単相 → frame180 共存) で **MP から delta を自動同定・採用** する。

    Issue #28 T6-B の operando warm-start を実 MP+GSAS で end-to-end 検証する。frame180 の共存域で
    Materials Project から無水 CaTeO3 (delta, mp-1195263) が自動同定・物質化・追加され、相集合が
    ``(alpha, new_CaTeO3)`` に成長する。``warm_start`` は現行相 alpha を精密化格子付きで先に残差減算する
    か (B) 否か (A, identify-all-then-exclude) のスイッチ。**両者とも受理まで到達する**。
    ネットワーク + GSAS で数分要する gated テスト。

    ⚠ **A (static) は一時期 xfail(strict) だった** — 「現行相 alpha を残差から減算せずに探索するため
    プリアラインが**別の軸**を伸ばし (a +4.63% / warm は c +4.56%)、二相精密化で相分率が 8.4e-13 に
    潰れて `frac_min` が正しく棄却する」と記録されていた。その診断は正しく、**原因は 2 段の目的関数
    汚染**だった: (1) プリアラインの FoM が観測ピーク基準で支配相のピークに占められる →
    整合先を既知相減算残差へ (`phaseid.make_residual_cell_refiner`)、(2) 同定段の等方 strain も
    生パターン整合で符号ごと誤り、既に c が +3.4% 過大な DFT セルに **+3.4% を上乗せ**して出発点を
    プリアラインの探索域 (±5%/軸) 外へ押し出す → `cell_refiner` 使用時は strain を掛けない DB 素の
    セルを渡す。両方を直して A も green になったためマーカーを外した (受理閾値は据え置き)。

    注意: frame180 は転移共存フレームで絶対 Rwp は高い (単相 ~33%, preferred orientation + 水素 +
    混合相; README honest status)。本テストは**自動同定の end-to-end 成立**を固定する
    (Rwp 収束帯は別テスト)。

    ⚠ **2026-07-27 の履歴 (閾値を緩めて通したのではない)**: Sample Type 修正で「格子が試料変位を
    吸収した自己整合な誤ったセル」が消えた直後、本テストは一度 xfail に落ちた (二相の Rwp が
    35.32→36.34 と悪化して受理されなかった)。原因は**閾値ではなく 2 つの無言失敗**だった:
    (1) 物質化 CIF が ``P 1`` で書かれ (`insitu.phaseid.structure_to_cif` の symprec 未指定 +
    cell 置換時の Structure 組み直し)、GSAS が delta を三斜晶と見てセル 6 変数を解放 → 特異
    ヘッシアンで ``Refine`` が失敗、(2) その失敗が ``G2Project.refine`` に捨てられ engine が
    陳腐化した Covariance を読むため revert すらされず、**S2 以降の全段が no-op のまま完走**して
    いた (`autorietveld.engine._capture_refine_status`)。両者を直した実測は
    base 32.98 → 二相 30.19 (**相対 +8.4%**、受理閾値 +1%) で、**フィットが実際に良くなって**
    受理されている。負スコア偽相の足切り (`min_identify_score`) は据え置き。
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
    reason="CaTeO3 データ + MATERIALS_PROJECT_API (env or .env) が必要",
)
def test_cateo3_mp_gsas_proposes_delta_and_gates_false_positives():
    """frame180 で **delta が唯一の試行候補になる** ことを固定する (受理の手前まで)。

    上の受理テストが xfail の間、同定パイプラインの健全性はここが守る:
    1. delta CaTeO3 (mp-1195263) が試行精密化まで到達する (提案は正しく行われている)
    2. Dara スコアが負の候補 (Ca3TeO6 / CaTe3O8) は**試行にすら回らない**
       — 残差を説明していない候補が Rwp の母数増だけで正解相に勝つ病理の恒久ガード
       (`PhaseIdConfig.min_identify_score`)。実測で CaTe3O8 が delta を押しのけて
       採用された事例がある。
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
        warm_start_known_phases=True,
    )
    res = run_sequential_rietveld(frames, [alpha], runner=runner,
                                  config=SequentialConfig(warm_start=True, phase_id=pid))

    trials = [e.payload for e in res.ledger.entries if e.kind == "m9_phaseid_trial"]
    skipped = [e.payload for e in res.ledger.entries if e.kind == "m9_phaseid_skipped"]

    assert any(t.get("phase_id") == "mp-1195263" for t in trials), trials
    # 負スコア候補は 1 つも試行されていない
    assert all(t.get("phase_id") != "mp-5279" for t in trials), trials
    assert skipped, "負スコア候補の足切りが記録されていない"
    assert all(float(s["score"]) <= 0.0 for s in skipped), skipped
