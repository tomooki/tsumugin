"""出版用の不確かさ抽出 (格子 esd / 重量分率±esd) の実データ検証。

GSAS-II 必須。K₂Mn[Fe(CN)₆] 放射光 operando の frame 124 (転移ドーム = mono+cubic+tetra の 3 相)
を実精密化し、次を検証する:

- (a) 収束した精密化で格子 esd が非ゼロかつ物理的に妥当 (格子定数より桁違いに小さい)
- (a') **凍結した格子の相 (cubic/tetra) に esd=0.0 を捏造しない** — レビュー第5巡 HIGH
- (b) 重量分率が `phase_fractions` (Scale 正規化) と**乖離する** — 単位胞質量が cubic 1103.4 vs
  tetra 517.8 と ~2.1x 違うため、Scale をそのまま定量値として読むと重大な誤りになる
- (c) 重量分率の総和 ≈ 1

`phase_weight_fractions` は GSAS-II 自身の `G2PwdrData.ComputeMassFracs()`
(→ `GSASIIstrMath.calcMassFracs`) 由来なので、(b) は GSAS の値との一致検証でもある。

> **(a') を足した理由 (レビュー第5巡 HIGH)**: 本 fixture は `refine_cell=False` で **cubic/tetra の
> 格子を凍結して**いるのに、旧テストは「格子を解放した主相 (mono)」しか assert していなかった。
> **fixture が作った条件を、その fixture のテストが見ていなかった**。実際そこにバグがあった:
> `get_cell_and_esd()` は凍結セルでも例外を出さず `(0.0,)*6` を返すため、`_cell_esd_map` の
> present-guard (例外時のみ相を落とす) を素通りし、`a = 10.5200(0)` と読める値が論文用 CSV へ
> 流れていた (実測: `tetra_a_esd=0.0` が 63/63 フレーム、`cubic` は auto_freeze 分 34/211)。
> **fixture が用意した条件は、そのテストが assert すること。**
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.recipe import build_recipe

pytestmark = pytest.mark.gsas

_SCRATCH = Path(
    "C:/Users/tomoo/AppData/Local/Temp/claude/"
    "C--Users-tomoo-Documents-programming-tsumugin/"
    "42d5114f-8527-4de8-a07f-d7e22f4e413a/scratchpad/kmnfe"
)
_MODELS = Path("scratchpad/kmnfe/models")
_DATA = _SCRATCH / "raw_xye" / "frame_0124.xye"
_INSTPRM = _SCRATCH / "staged" / "kmnfe.instprm"
_MONO = _SCRATCH / "manual" / "0001" / "0001.cif"


def _data_present() -> bool:
    return all(
        p.exists()
        for p in (_DATA, _INSTPRM, _MONO, _MODELS / "cubic_pba.cif", _MODELS / "tetra_real.cif")
    )


@pytest.fixture(scope="module")
def frame124_result():
    """frame 124 (3 相) を実精密化した AutoRietveldResult (module スコープで 1 回だけ)。"""
    if not _data_present():
        pytest.skip("K₂Mn[Fe(CN)₆] operando 実データ未取得")
    hist = HistogramSpec(
        data_path=str(_DATA),
        instrument_path=str(_INSTPRM),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=(2.4, 18.0),  # 高角ノイズ除外 (未設定だと最小二乗が平坦化)
    )
    phases = (
        PhaseSpec(structure_path=str(_MONO), phase_name="mono"),
        # 副相の格子は既知参照に固定 (分率が 0 近傍に落ちた際の格子発散 → 段全体 revert を回避, #47)
        PhaseSpec(structure_path=str(_MODELS / "cubic_pba.cif"), phase_name="cubic",
                  refine_cell=False),
        PhaseSpec(structure_path=str(_MODELS / "tetra_real.cif"), phase_name="tetra",
                  refine_cell=False),
    )
    recipe = build_recipe(list([hist]), list(phases), background_coeffs=18)
    return run_auto_rietveld(list([hist]), list(phases), recipe=recipe)


#: fixture が **`refine_cell=False` で格子を凍結した**相 (= このテストが assert すべき条件)。
_FROZEN_PHASES = ("cubic", "tetra")
#: fixture が格子を解放した相。
_REFINED_PHASE = "mono"


def test_cell_esd_is_nonzero_and_physically_sane(frame124_result):
    """(a) 収束した精密化で格子 esd が非ゼロかつ格子定数より桁違いに小さいこと。"""
    res = frame124_result
    assert res.cell_esd, "cell_esd が空 (共分散から esd を抽出できていない)"
    assert set(res.cell_esd) == set(res.refined_cells)
    # 格子を解放した主相 (mono) は esd が立つ
    esd = res.cell_esd[_REFINED_PHASE]
    cell = res.refined_cells[_REFINED_PHASE]
    assert len(esd) == len(cell) == 6
    assert all(e is not None and math.isfinite(e) and e >= 0.0 for e in esd)
    assert any(e > 0.0 for e in esd[:3]), f"解放した格子長の esd が全て 0: {esd}"
    for length, sigma in zip(cell[:3], esd[:3]):
        # 出版可能な精密化なら su は格子長の 1% 未満 (通常 1e-3 Å オーダー)
        assert sigma < 0.01 * length, f"esd {sigma} が格子長 {length} に対し非物理的に大きい"


def test_frozen_phase_cell_esd_is_none_not_fabricated_zero(frame124_result):
    """★(a') fixture が凍結した相 (cubic/tetra) の格子 esd が `None` であること。

    **これが本テストモジュールの盲点だった** (レビュー第5巡 HIGH): fixture は `refine_cell=False`
    で 2 相の格子を凍結しているのに、旧テストは mono だけを見て「esd が立つ」と確認して終わって
    いた。実測はこうだった (実 GSAS・AGENT_PLAYBOOK のコピペ設定そのまま):

        mono  (解放): (0.013303, 0.017739, 0.010871, 0.0, 0.130036, 0.0) -> a = 10.0316(133)
        cubic (凍結): (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)                     -> a = 10.5200(0)  ← 捏造
        tetra (凍結): (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)                     -> a =  7.1407(0)  ← 捏造

    `0.0` は「精密化して 0 に決まった」と読まれる。凍結セルの値は**入力 CIF の値**であって
    このデータから決まったものではないので、esd を書いてはならない (= `None`)。
    """
    res = frame124_result
    for name in _FROZEN_PHASES:
        esd = res.cell_esd[name]
        assert esd == (None,) * 6, (
            f"{name} は fixture が refine_cell=False で凍結した相なのに esd={esd} が立っている。"
            f"0.0 なら捏造 (a = {res.refined_cells[name][0]:.4f}(0) と読める)"
        )


def test_symmetry_fixed_angles_stay_zero_and_are_distinguishable_from_frozen(frame124_result):
    """★対称拘束の 0.0 (mono の α/γ=90°) は**真の陳述**なので `None` にしないこと。

    3 状態 (`>0` 解放 / `0.0` 対称拘束 / `None` 未解放) が **1 つの結果の中で判別できる**ことが
    ③ の要件である。「0 は固定を意味する」というヒューリスティックは使えない — mono 自身が
    α/γ に真の 0.0 を持つため。
    """
    res = frame124_result
    mono = res.cell_esd[_REFINED_PHASE]
    assert mono[3] == 0.0 and mono[5] == 0.0, f"monoclinic の α/γ は対称拘束で 0.0 のはず: {mono}"
    assert mono[4] is not None and mono[4] > 0.0, f"monoclinic の β は解放されている: {mono}"
    # 3 状態が同一結果内で区別できる。
    assert res.cell_esd[_FROZEN_PHASES[0]][3] is None, "凍結の角度は None (対称拘束の 0.0 と別物)"


def test_weight_fractions_differ_from_scale_fractions_and_sum_to_one(frame124_result):
    """(b)(c) 重量分率が Scale 正規化と乖離し、かつ総和 ≈ 1 であること。"""
    res = frame124_result
    wf = res.phase_weight_fractions
    assert wf, "phase_weight_fractions が空 (calcMassFracs を駆動できていない)"
    assert set(wf) == set(res.phase_fractions)
    assert sum(wf.values()) == pytest.approx(1.0, abs=1e-6)  # (c)
    assert all(0.0 <= v <= 1.0 for v in wf.values())
    # (b) 単位胞質量が ~2.1x 違う → Scale 正規化と重量分率は一致しない
    assert any(
        abs(wf[name] - res.phase_fractions[name]) > 0.01 for name in wf
    ), f"重量分率が Scale 正規化と一致してしまった: {dict(wf)} vs {dict(res.phase_fractions)}"


def test_weight_fraction_esd_is_reported(frame124_result):
    """重量分率の esd が相分率を解放した相で立つこと (出版値には su が必須)。"""
    res = frame124_result
    esd = res.phase_weight_fraction_esd
    assert set(esd) == set(res.phase_weight_fractions)
    assert all(math.isfinite(v) and v >= 0.0 for v in esd.values())
    assert any(v > 0.0 for v in esd.values()), f"重量分率 esd が全て 0: {dict(esd)}"


def test_single_phase_weight_fraction_is_unity():
    """単相は calcMassFracs が空を返す仕様 → 自明な 1.0 に縮退すること。"""
    if not _data_present():
        pytest.skip("K₂Mn[Fe(CN)₆] operando 実データ未取得")
    hist = HistogramSpec(
        data_path=str(_DATA),
        instrument_path=str(_INSTPRM),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=(2.4, 18.0),
    )
    phases = (PhaseSpec(structure_path=str(_MONO), phase_name="mono"),)
    recipe = build_recipe(list([hist]), list(phases), background_coeffs=18)[:2]  # 短縮 (単相の縮退確認)
    res = run_auto_rietveld(list([hist]), list(phases), recipe=recipe)
    assert res.phase_weight_fractions == {"mono": 1.0}
    assert res.phase_weight_fraction_esd == {"mono": 0.0}
