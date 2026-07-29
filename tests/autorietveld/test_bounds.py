"""WS-2 箱拘束 (REQ-SAR-201) と境界到達の検出 (REQ-SAR-202) — GSAS 非依存の純関数。

ここで固定するのは**どこに箱を張るか / 張らないか**と、境界に当たった事実をどう拾うか。
実 GSAS への配線は `test_box_bounds_gsas.py`。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.bounds import (
    BoxBound,
    cell_box_bounds,
    detect_bound_hits,
    displacement_box_bounds,
    reciprocal_metric_diagonal,
    size_strain_box_bounds,
)
from tsumugin.autorietveld.model import StabilityOptions

_CUBIC = (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)
_MONO = (9.0, 7.0, 11.0, 90.0, 103.0, 90.0)


# ---------------------------------------------------------------------------
# P-SAR-1 — 構造パラメータには箱を張らない (設計原則そのものを固定する)
# ---------------------------------------------------------------------------


def test_no_option_exists_for_boxing_structural_parameters():
    # 【目的】: P-SAR-1 の恒久ガード。占有率/Uiso/座標に箱を張る設定を**足させない**。
    #   NaCuHCF model5 は占有率が Na>1 / O<0 に発散したこと自体が「Ow が必要」の決め手で、
    #   [0,1] に拘束していれば model5/model6 を判別できなかった (診断信号の握り潰し)。
    #   ここを緩める差分は必ずこのテストを落とす。
    forbidden = ("occupancy", "occ", "uiso", "adp", "coord", "xyz", "atom")
    fields = set(StabilityOptions().to_dict())
    offenders = sorted(f for f in fields if any(tok in f.lower() for tok in forbidden))
    assert offenders == [], (
        f"構造パラメータの箱拘束らしき設定が増えた: {offenders} — P-SAR-1 違反。"
        "異常値はモデル誤りの診断信号なのでクランプせず報告すること"
    )


def test_planned_bound_kinds_are_instrument_and_geometry_only():
    # 【目的】: 実際に作られる箱の kind が装置・幾何に限られること (実装が増えても崩れない形)。
    bounds = (
        cell_box_bounds(0, _MONO, 0.05)
        + displacement_box_bounds(0, 5000.0, bragg_brentano=True)
        + size_strain_box_bounds(
            0, 0, min_size=1e-3, max_size=1e4, min_mustrain=1e-3, max_mustrain=1e5
        )
    )
    assert {b.kind for b in bounds} == {"cell", "displacement", "size", "mustrain"}


# ---------------------------------------------------------------------------
# 逆格子計量の対角成分
# ---------------------------------------------------------------------------


def test_cubic_reciprocal_diagonal_is_one_over_a_squared():
    # 【目的】: 直交系では A_ii = 1/a² であることの数値的な足場。
    diag = reciprocal_metric_diagonal(_CUBIC)
    assert diag is not None
    for v in diag:
        assert v == pytest.approx(1.0 / 25.0)


def test_monoclinic_diagonal_is_positive_on_every_axis():
    # 【目的】: 非直交系でも A0..A2 は常に正 (= 箱を張れる) こと。a*² は 1/a² より大きい。
    diag = reciprocal_metric_diagonal(_MONO)
    assert diag is not None
    assert all(v > 0.0 for v in diag)
    assert diag[0] > 1.0 / _MONO[0] ** 2  # β≠90° の分だけ a* は 1/a より大きい


@pytest.mark.parametrize(
    "cell",
    [
        (0.0, 5.0, 5.0, 90.0, 90.0, 90.0),  # 崩壊した軸
        (5.0, 5.0, 5.0, 170.0, 170.0, 170.0),  # 幾何学的に不可能な角度 (非正定値)
        (5.0, 5.0),  # 要素不足
        ("x", 5.0, 5.0, 90.0, 90.0, 90.0),  # 非数値
    ],
)
def test_degenerate_cells_yield_no_bounds(cell):
    # 【目的】: 既に壊れた格子を「拘束の前提」にしない (fail open)。箱を張らずに None/空を返す。
    assert reciprocal_metric_diagonal(cell) is None
    assert cell_box_bounds(0, cell, 0.05) == ()


# ---------------------------------------------------------------------------
# REQ-SAR-201 格子の箱
# ---------------------------------------------------------------------------


def test_cell_bounds_cover_the_requested_relative_window():
    # 【目的】: ±5% の軸長変化が箱の内側、±6% が外側になること (箱の意味の検算)。
    (b0, _b1, _b2) = cell_box_bounds(0, _CUBIC, 0.05)
    a0 = 1.0 / 25.0
    inside_short = 1.0 / (5.0 * 0.95) ** 2  # a が 5% 縮む → A0 は増える
    inside_long = 1.0 / (5.0 * 1.05) ** 2
    assert b0.lo == pytest.approx(inside_long)
    assert b0.hi == pytest.approx(inside_short)
    assert b0.lo < a0 < b0.hi
    outside = 1.0 / (5.0 * 0.94) ** 2
    assert outside > b0.hi


def test_cell_bounds_target_only_the_diagonal_components():
    # 【目的】: A3/A4/A5 (角度由来) には張らない — 90° で 0 を跨ぐので相対的な箱に意味がない。
    names = {b.variable for b in cell_box_bounds(3, _MONO, 0.02)}
    assert names == {"3::A0", "3::A1", "3::A2"}


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.0, 2.0, float("nan")])
def test_nonsensical_cell_fraction_registers_nothing(fraction):
    # 【目的】: 不正な設定で黙って「幅ゼロの箱」= 全格子固定を作らない。何も張らない方が安全。
    assert cell_box_bounds(0, _CUBIC, fraction) == ()


# ---------------------------------------------------------------------------
# REQ-SAR-201 試料変位の箱
# ---------------------------------------------------------------------------


def test_bragg_brentano_bounds_shift_and_debye_bounds_displace_xy():
    # 【目的】: GSAS は Sample Parameters の Type でどちらを**変数にするか**を決めるので、
    #   宣言ジオメトリに合わせる (engine._apply_sample_geometry と同じ根拠)。
    bragg = displacement_box_bounds(0, 5000.0, bragg_brentano=True)
    debye = displacement_box_bounds(1, 5000.0, bragg_brentano=False)
    assert [b.variable for b in bragg] == [":0:Shift"]
    assert [b.variable for b in debye] == [":1:DisplaceX", ":1:DisplaceY"]
    assert all(b.lo == -5000.0 and b.hi == 5000.0 for b in bragg + debye)


@pytest.mark.parametrize("limit", [0.0, -1.0, float("inf"), float("nan")])
def test_nonsensical_displacement_limit_registers_nothing(limit):
    assert displacement_box_bounds(0, limit, bragg_brentano=True) == ()


# ---------------------------------------------------------------------------
# REQ-SAR-201 Size/Mustrain の正値性
# ---------------------------------------------------------------------------


def test_size_and_mustrain_get_a_positive_floor():
    # 【目的】: Size;i は幅の式で**分母**に入る (Sgam = 1.8λ/(π·Size;i·cosθ)) ので 0/負は発散。
    bounds = size_strain_box_bounds(
        1, 2, min_size=1e-3, max_size=1e4, min_mustrain=1e-3, max_mustrain=1e5
    )
    by_name = {b.variable: b for b in bounds}
    assert set(by_name) == {"1:2:Size;i", "1:2:Mustrain;i"}
    assert all(b.lo is not None and b.lo > 0.0 for b in bounds)


def test_anisotropic_size_strain_components_are_never_boxed():
    # 【目的】: uniaxial (;a) / generalized (;0..;N) は**符号が物理的に自由**。正に縛ると
    #   異方性そのものを消してしまうため対象外にする。
    names = {
        b.variable
        for b in size_strain_box_bounds(
            0, 0, min_size=1e-3, max_size=1e4, min_mustrain=1e-3, max_mustrain=1e5
        )
    }
    assert not any(n.endswith(";a") or ";0" in n for n in names)


def test_upper_caps_are_far_above_any_physical_value():
    # 【目的】: 実測教訓「低い cap は境界不安定 = 偽の "改善せず" を作る」(NaCuHCF: ADP cap を
    #   上げたら ND 18.0→14.7%)。既定の上限が物理的必要値を**桁で**上回ることを固定する。
    opts = StabilityOptions()
    assert opts.max_size >= 1.0e3, "粉末回折で分離できるサイズ (< 数 µm) を桁で上回ること"
    assert opts.max_mustrain >= 1.0e4, "実在する微小歪み (~1e3 ×10⁻⁶) を桁で上回ること"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_size": 10.0, "max_size": 1.0},  # 下限 > 上限
        {"min_size": -1.0},  # 負の下限
        {"min_size": float("nan")},
        {"max_size": float("inf")},
    ],
)
def test_inconsistent_size_window_registers_no_size_bound(kwargs):
    base = dict(min_size=1e-3, max_size=1e4, min_mustrain=1e-3, max_mustrain=1e5)
    base.update(kwargs)
    names = {b.variable for b in size_strain_box_bounds(0, 0, **base)}
    assert "0:0:Size;i" not in names


# ---------------------------------------------------------------------------
# REQ-SAR-202 境界到達の検出
# ---------------------------------------------------------------------------

_BOX = BoxBound(variable=":0:Shift", lo=-5000.0, hi=5000.0, kind="displacement")
_FLOOR = BoxBound(variable="0:0:Size;i", lo=1e-3, hi=None, kind="size")


def test_newly_frozen_boxed_variable_is_reported_as_a_hit():
    # 【目的】: GSAS は箱外の変数を境界へ丸めて凍結する = Rwp にも reverted にも現れない。
    #   握り潰さずに所見として拾うのが REQ-SAR-202。
    hits = detect_bound_hits([_BOX], frozen_before=[], frozen_after=[":0:Shift"])
    assert [h.variable for h in hits] == [":0:Shift"]


def test_already_frozen_variables_are_not_re_reported():
    # 【目的】: 段ごとに同じ境界到達を繰り返し台帳へ流さない (差分だけを事実として残す)。
    hits = detect_bound_hits([_BOX], [":0:Shift"], [":0:Shift"])
    assert hits == ()


def test_variables_frozen_for_other_reasons_are_not_mistaken_for_bound_hits():
    # 【目的】: **同じ parmFrozen に esd プルーニング (REQ-SAR-103) も書く**。箱を張っていない
    #   変数まで拾うと「自分で凍らせた変数」を境界到達と誤報する (最悪の静かな嘘)。
    hits = detect_bound_hits([_BOX], [], ["0::AUiso:0", "0::A0"])
    assert hits == ()


def test_hit_side_is_determined_from_the_pre_clamp_value():
    # 【目的】: dropOOBvars は covData を書いた**後**に値を境界へ丸めるので、共分散に残る値は
    #   箱の外側にある = どちら側かを一意に決められる (推測しない)。
    lo_hit = detect_bound_hits([_BOX], [], [":0:Shift"], {":0:Shift": -9000.0})
    hi_hit = detect_bound_hits([_BOX], [], [":0:Shift"], {":0:Shift": 9000.0})
    assert lo_hit[0].side == "min"
    assert hi_hit[0].side == "max"


def test_two_sided_box_without_values_reports_unknown_side():
    # 【目的】: 判らないことを「min」と断定しない (情報が無いことを正常と答えない規律)。
    assert detect_bound_hits([_BOX], [], [":0:Shift"])[0].side == "unknown"


def test_one_sided_box_reports_that_side_without_values():
    assert detect_bound_hits([_FLOOR], [], ["0:0:Size;i"])[0].side == "min"


def test_hits_are_sorted_for_determinism():
    # 【目的】: NFR-102。凍結リストの順序 (GSAS の内部順) に結果が依存しないこと。
    b = BoxBound(variable="0::A0", lo=1.0, hi=2.0, kind="cell")
    names = [h.variable for h in detect_bound_hits([_BOX, b, _FLOOR], [], ["0:0:Size;i", ":0:Shift", "0::A0"])]
    assert names == sorted(names)


def test_hit_dict_is_json_ready_for_the_ledger():
    # 【目的】: ledger/② 境界へそのまま載る形 (非有限は None)。
    d = detect_bound_hits([_FLOOR], [], ["0:0:Size;i"])[0].to_dict()
    assert d["variable"] == "0:0:Size;i" and d["hi"] is None
    assert isinstance(d["lo"], float) and math.isfinite(d["lo"])


# ---------------------------------------------------------------------------
# 登録の縮退 (engine 側の純ロジック)
# ---------------------------------------------------------------------------


class _PartialControls:
    """``parmMax`` だけ拒否する GSAS 代役 (古い GSAS / 解釈できない変数名の縮退を模す)。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float, str]] = []

    def set_Controls(self, control, value, variable=None):  # noqa: N802
        if control == "parmMax":
            raise Exception("unsupported")
        self.calls.append((control, value, variable))


def test_half_registered_box_still_reports_its_registered_side():
    # 【目的】: 片側の登録に失敗しても、**登録できた側は境界検出に残す**。落としてしまうと
    #   「GSAS は凍結したのに所見が出ない」= 検出できない失敗を作る (P-SAR-2 違反)。
    from tsumugin.autorietveld.engine import _apply_box_bounds

    applied = _apply_box_bounds(_PartialControls(), [_BOX])
    assert len(applied) == 1
    assert applied[0].lo == _BOX.lo and applied[0].hi is None


class _RejectingControls:
    def set_Controls(self, control, value, variable=None):  # noqa: N802
        raise Exception("unsupported")


def test_a_box_that_could_not_be_registered_at_all_is_dropped():
    # 【目的】: 逆に、1 つも登録できなかった箱は落とす — 張っていない箱の「境界到達」を
    #   報告すると、存在しない拘束のせいにする嘘の所見になる。
    from tsumugin.autorietveld.engine import _apply_box_bounds

    assert _apply_box_bounds(_RejectingControls(), [_BOX]) == ()
