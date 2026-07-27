"""`HistogramSpec.geometry` を GSAS-II の Sample Parameters ``Type`` に反映させる (Issue: Shift)。

**背景 (実測で判明した無言の失敗)**: GSAS-II は Sample Parameters の ``Type`` を**装置パラメータ
ファイルから**決める (`GSASIIfiles.py`: ``Lam1`` があれば Bragg-Brentano、無ければ
Debye-Scherrer)。Kα1 単色の instprm (``Lam:`` 1 本) を使う実験室 X 線は、たとえ反射光学系
(Bragg-Brentano) でも ``Type='Debye-Scherrer'`` になり ``Shift`` キーが存在しない。すると
``recipe._GEOMETRY_DISPLACEMENT[BRAGG_BRENTANO] == ["Shift"]`` を解放しようとした
``cell+displacement`` 段が ``ValueError('Unknown refinement parameter, Shift')`` で落ち、
**格子が一度も精密化されないまま** revert して以降の段が進む (CaTeO3 M9 実データで発生)。

``Type`` は単なるキー集合の話ではない:
- `GSASIIstrIO.py` は ``Type`` を見て**どの試料パラメータを変数にできるか**を決める
- `GSASIIstrMath.py` は ``Type`` を見て**ピーク位置の補正式**を選ぶ
  (Bragg: ``Shift``/``Transparency`` / Debye: ``DisplaceX``/``DisplaceY``)

したがって「足りないキーを足すだけ」では駄目で (足しても変数にならず式にも入らない)、
**spec が宣言したジオメトリを正として ``Type`` ごと合わせる**必要がある。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import _apply_sample_geometry


class _FakeHist:
    """`hist.data["Sample Parameters"]` だけを持つ最小フェイク (GSAS 非依存の単体検証用)。"""

    def __init__(self, sample: dict):
        self.data = {"Sample Parameters": sample}


def _debye_sample() -> dict:
    """GSAS `SetDefaultSample()` 相当 (Kα1 単色 instprm で実際に得られる形)。"""
    return {
        "Type": "Debye-Scherrer",
        "Scale": [1.0, True],
        "Absorption": [0.0, False],
        "DisplaceX": [0.0, False],
        "DisplaceY": [0.0, False],
    }


# ---------------------------------------------------------------------------
# 単体 (GSAS 不要)
# ---------------------------------------------------------------------------


def test_bragg_brentano_sets_type_and_adds_its_parameters():
    hist = _FakeHist(_debye_sample())

    _apply_sample_geometry(hist, Geometry.BRAGG_BRENTANO)

    sample = hist.data["Sample Parameters"]
    assert sample["Type"] == "Bragg-Brentano"
    # GSASIIstrIO が Bragg 分岐で参照する 4 つ (Scale は既存)
    for key in ("Shift", "Transparency", "SurfRoughA", "SurfRoughB"):
        assert sample[key] == [0.0, False], key


def test_debye_scherrer_sets_type_and_adds_its_parameters():
    hist = _FakeHist({"Type": "Bragg-Brentano", "Scale": [1.0, True], "Shift": [0.0, False]})

    _apply_sample_geometry(hist, Geometry.DEBYE_SCHERRER)

    sample = hist.data["Sample Parameters"]
    assert sample["Type"] == "Debye-Scherrer"
    for key in ("Absorption", "DisplaceX", "DisplaceY"):
        assert sample[key] == [0.0, False], key


def test_existing_values_are_never_overwritten():
    # 【目的】: importer/instprm が既に持っている値 (精密化フラグ含む) を潰さない。
    #   欠けているキーを補うだけ — GSAS 自身の Sample.update と同じ加算的な流儀。
    sample = _debye_sample()
    sample["Shift"] = [0.25, True]
    hist = _FakeHist(sample)

    _apply_sample_geometry(hist, Geometry.BRAGG_BRENTANO)

    assert hist.data["Sample Parameters"]["Shift"] == [0.25, True]


def test_debye_keys_are_left_in_place_when_switching_to_bragg():
    # 【目的】: 破壊的に消さない (GSAS も update しか行わない)。Type だけが「どちらを使うか」を決める。
    hist = _FakeHist(_debye_sample())

    _apply_sample_geometry(hist, Geometry.BRAGG_BRENTANO)

    assert "DisplaceX" in hist.data["Sample Parameters"]


def test_is_idempotent():
    hist = _FakeHist(_debye_sample())

    _apply_sample_geometry(hist, Geometry.BRAGG_BRENTANO)
    first = dict(hist.data["Sample Parameters"])
    _apply_sample_geometry(hist, Geometry.BRAGG_BRENTANO)

    assert hist.data["Sample Parameters"] == first


def test_missing_sample_parameters_is_not_fatal():
    # 【目的】: 想定外の形の histogram で精密化全体を落とさない (fail open)。
    hist = _FakeHist({})
    hist.data.pop("Sample Parameters")

    _apply_sample_geometry(hist, Geometry.BRAGG_BRENTANO)  # 例外を出さない


# ---------------------------------------------------------------------------
# 実データ結合 (GSAS-II 必須) — Kα1 単色 instprm + 反射光学系
# ---------------------------------------------------------------------------

_M9 = Path("docs/benchmark/testdata/m9/cateo3")


def _m9_present() -> bool:
    return (
        (_M9 / "NB-LM01MO_030.XRDML").exists()
        and (_M9 / "cateo3_CuKa.instprm").exists()
        and (_M9 / "alpha_CaTeO3_H2O.cif").exists()
    )


@pytest.mark.gsas
@pytest.mark.skipif(not _m9_present(), reason="M9 CaTeO3 データ未取得")
def test_kalpha1_bragg_brentano_refines_the_cell_instead_of_dying(tmp_path):
    """回帰: Kα1 単色 instprm + BRAGG_BRENTANO で ``cell+displacement`` 段が完走し格子が動く。

    修正前はこの段が ``Unknown refinement parameter, Shift`` で落ちて revert し、
    **格子が CIF 初期値のまま**最終結果になっていた (Rwp だけ見ると気付けない)。
    """
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.insitu.engine import _xrdml_to_xye
    from tsumugin.store.ledger import Ledger

    xye = tmp_path / "frame.xye"
    _xrdml_to_xye(str(_M9 / "NB-LM01MO_030.XRDML"), str(xye))
    hist = HistogramSpec(
        data_path=str(xye),
        instrument_path=str(_M9 / "cateo3_CuKa.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XYE",
        two_theta_limits=(12.0, 70.0),
    )
    phase = PhaseSpec(structure_path=str(_M9 / "alpha_CaTeO3_H2O.cif"), phase_name="alpha")
    ledger = Ledger()

    result = run_auto_rietveld([hist], [phase], ledger=ledger, max_cyc=20)

    # 1. cell 段が例外で落ちていない
    errors = [
        e for e in ledger.entries
        if e.kind == "m7_stage_error" and "cell" in str(e.payload.get("stage", ""))
    ]
    assert not errors, [e.payload for e in errors]
    # 2. 格子が CIF 初期値から実際に動いた (段が revert されただけなら一致したままになる)
    initial = (8.0595, 6.7876, 14.7813)
    refined = result.refined_cells["alpha"][:3]
    assert any(abs(r - i) > 1e-4 for r, i in zip(refined, initial)), refined
