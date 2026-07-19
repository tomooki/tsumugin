"""operando/coulometry.py (FR-318 物理コア) のテスト。numpy-only・決定論。

T1: electron_count (F 定数ピン留め) / T2: alkali_targets (in_span/rest/state 分岐 + sign 照合) /
T3: MobileSiteSpec 複数元素合算 + content 変換 / T4: x_xrd_from_weight_fractions (FW 除算) +
feasibility + coulometric_fractions。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.interop.biologic import FramePoint
from tsumugin.operando.coulometry import (
    F_MAH_PER_MOL,
    AlkaliBudget,
    FrameTarget,
    MobileSiteSpec,
    alkali_targets,
    content_from_occupancies,
    coulometric_fractions,
    electron_count,
    feasibility,
    occupancies_for_content,
    x_xrd_from_weight_fractions,
)

# --------------------------------------------------------------------------------------
# T1: electron_count
# --------------------------------------------------------------------------------------


class TestElectronCount:
    def test_faraday_constant_pinned(self) -> None:
        """F = 96485.33212 C/mol ÷ 3.6 ≈ 26801.48 mAh/mol (要件1 の換算定数)。"""
        assert F_MAH_PER_MOL == pytest.approx(26801.4811, abs=0.01)

    def test_known_value_gives_one_electron(self) -> None:
        """Q = F·m/M のとき n_e = 1 (解析値ピン留め)。"""
        m_mg, fw = 10.0, 100.0
        q_mah = F_MAH_PER_MOL * (m_mg / 1000.0) / fw  # = 2.6801 mAh
        assert electron_count(q_mah, m_mg, fw) == pytest.approx(1.0, rel=1e-12)

    def test_z2_halves_the_count(self) -> None:
        m_mg, fw = 10.0, 100.0
        q_mah = F_MAH_PER_MOL * (m_mg / 1000.0) / fw
        assert electron_count(q_mah, m_mg, fw, z=2) == pytest.approx(0.5, rel=1e-12)

    def test_array_input(self) -> None:
        m_mg, fw = 20.0, 250.0
        q = np.array([0.0, 1.0, -1.0])
        out = electron_count(q, m_mg, fw)
        assert isinstance(out, np.ndarray)
        assert out[0] == 0.0
        assert out[2] == pytest.approx(-out[1])

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"active_mass_mg": 0.0, "formula_weight": 100.0},
            {"active_mass_mg": -1.0, "formula_weight": 100.0},
            {"active_mass_mg": 10.0, "formula_weight": 0.0},
            {"active_mass_mg": 10.0, "formula_weight": 100.0, "z": 0},
        ],
    )
    def test_invalid_inputs_raise(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            electron_count(1.0, **kwargs)


# --------------------------------------------------------------------------------------
# T2: alkali_targets
# --------------------------------------------------------------------------------------


def _fp(i: int, q: float | None, state: str, in_span: bool = True) -> FramePoint:
    return FramePoint(
        frame_index=i, time_s=float(i) * 100.0, voltage_v=1.5 if in_span else None,
        charge_mah=q, state=state, in_span=in_span,
    )


# n_e = 1 になる Q (m=10mg, M=100g/mol)
_Q1 = F_MAH_PER_MOL * 0.01 / 100.0


class TestAlkaliTargets:
    def _budget(self, points, *, sign: int = 1, x0: float = 2.0) -> AlkaliBudget:
        return alkali_targets(
            points, x0=x0, active_mass_mg=10.0, formula_weight=100.0, sign=sign,
            x0_source="given",
        )

    def test_charge_decreases_x(self) -> None:
        """充電 (Q 増) で x_total が x0 から減る (sign=+1 = 正極規約)。"""
        b = self._budget([_fp(0, 0.0, "charge"), _fp(1, _Q1, "charge")])
        assert b.targets[0].x_total == pytest.approx(2.0)
        assert b.targets[1].x_total == pytest.approx(1.0)
        assert b.targets[1].n_e == pytest.approx(1.0)
        assert not b.warnings

    def test_out_of_span_has_no_target(self) -> None:
        """echem 範囲外 (in_span=False / Q=None) には目標を作らない (捏造禁止)。"""
        b = self._budget([_fp(0, 0.0, "charge"), _fp(1, None, "unknown", in_span=False)])
        t = b.targets[1]
        assert t.x_total is None
        assert t.n_e is None
        assert not t.in_span

    def test_rest_keeps_target(self) -> None:
        """rest は Q 一定なので目標は有効 (適用可)。"""
        b = self._budget([_fp(0, _Q1, "rest")])
        assert b.targets[0].x_total == pytest.approx(1.0)

    def test_sign_mismatch_warns(self) -> None:
        """sign=-1 だと充電区間で x が増える → state と矛盾 → 警告。"""
        b = self._budget([_fp(0, 0.0, "charge"), _fp(1, _Q1, "charge")], sign=-1)
        assert any("sign" in w for w in b.warnings)

    def test_x0_source_recorded_and_validated(self) -> None:
        b = self._budget([_fp(0, 0.0, "charge")])
        assert b.x0_source == "given"
        with pytest.raises(ValueError):
            alkali_targets(
                [_fp(0, 0.0, "charge")], x0=2.0, active_mass_mg=10.0,
                formula_weight=100.0, sign=1, x0_source="bogus",
            )

    def test_frame_order_preserved(self) -> None:
        """FrameTarget は入力順を保つ (回折フレーム番号との対応)。"""
        b = self._budget([_fp(5, 0.0, "charge"), _fp(2, _Q1, "charge")])
        assert [t.frame_index for t in b.targets] == [5, 2]

    def test_invalid_sign_raises(self) -> None:
        with pytest.raises(ValueError):
            self._budget([_fp(0, 0.0, "charge")], sign=0)


# --------------------------------------------------------------------------------------
# T3: MobileSiteSpec / content 変換
# --------------------------------------------------------------------------------------


class TestMobileSites:
    def test_mono_kmnfe_case(self) -> None:
        """実例ピン留め: mono K₂Mn[Fe(CN)₆] — K 4e サイト mult=4, Z=2, occ 0.972 → x=1.944。"""
        spec = MobileSiteSpec(
            phase_name="mono", site_labels=("K",), multiplicities=(4.0,),
        )
        x = content_from_occupancies({"K": 0.972}, spec, z_formula=2.0)
        assert x == pytest.approx(1.944)

    def test_multi_element_site_sums(self) -> None:
        """Na+K 合算 (REQ-318-008): 同一サイトの複数元素占有を合算する。"""
        spec = MobileSiteSpec(
            phase_name="cubic", site_labels=("Na1", "K1"), multiplicities=(8.0, 8.0),
        )
        x = content_from_occupancies({"Na1": 0.2, "K1": 0.5}, spec, z_formula=4.0)
        assert x == pytest.approx((0.2 + 0.5) * 8.0 / 4.0)

    def test_missing_label_raises(self) -> None:
        spec = MobileSiteSpec(phase_name="p", site_labels=("K",), multiplicities=(4.0,))
        with pytest.raises(ValueError, match="K"):
            content_from_occupancies({"Na": 0.5}, spec, z_formula=2.0)

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError):
            MobileSiteSpec(phase_name="p", site_labels=("K", "Na"), multiplicities=(4.0,))

    def test_inverse_proportional_scaling(self) -> None:
        """目標 x への等比配分: 既存占有比を保って全体をスケール。往復一致。"""
        spec = MobileSiteSpec(
            phase_name="p", site_labels=("Na1", "K1"), multiplicities=(8.0, 8.0),
        )
        base = {"Na1": 0.2, "K1": 0.5}
        occ = occupancies_for_content(1.0, spec, z_formula=4.0, base_occupancies=base)
        # 比率保存
        assert occ["K1"] / occ["Na1"] == pytest.approx(0.5 / 0.2)
        # 往復
        assert content_from_occupancies(occ, spec, z_formula=4.0) == pytest.approx(1.0)

    def test_inverse_zero_base_uniform(self) -> None:
        """既存占有ゼロなら均等配分。"""
        spec = MobileSiteSpec(
            phase_name="p", site_labels=("A", "B"), multiplicities=(4.0, 4.0),
        )
        occ = occupancies_for_content(
            1.0, spec, z_formula=2.0, base_occupancies={"A": 0.0, "B": 0.0}
        )
        assert occ["A"] == pytest.approx(occ["B"])
        assert content_from_occupancies(occ, spec, z_formula=2.0) == pytest.approx(1.0)

    def test_inverse_overflow_raises(self) -> None:
        """占有率が 1 を超える配分は物理的に不可能 → ValueError。"""
        spec = MobileSiteSpec(phase_name="p", site_labels=("K",), multiplicities=(4.0,))
        with pytest.raises(ValueError, match="1"):
            occupancies_for_content(
                3.0, spec, z_formula=2.0, base_occupancies={"K": 0.9}
            )


# --------------------------------------------------------------------------------------
# T4: x_XRD (FW 除算) / feasibility / coulometric_fractions
# --------------------------------------------------------------------------------------


class TestXxrd:
    def test_asymmetric_fw_pins_the_divisor(self) -> None:
        """★最重要ピン留め: 重量分率→モル分率は FW で割る (セル質量 Z·FW ではない)。

        A(FW=100, x=2) / B(FW=50, x=1), w=0.5/0.5:
          正: n_A∝0.5/100, n_B∝0.5/50 → φ_A=1/3 → x = (1/3)·2+(2/3)·1 = 4/3
          誤 (セル質量 Z_A=4, Z_B=2 で割る): φ_A=0.2 → x=1.2 — これを弾く。
        """
        x, _ = x_xrd_from_weight_fractions(
            {"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 50.0}, {"A": 2.0, "B": 1.0},
        )
        assert x == pytest.approx(4.0 / 3.0, rel=1e-12)
        assert not math.isclose(x, 1.2, rel_tol=1e-3)

    def test_single_phase_identity(self) -> None:
        x, esd = x_xrd_from_weight_fractions({"A": 1.0}, {"A": 123.0}, {"A": 1.7})
        assert x == pytest.approx(1.7)
        assert esd is None  # esd 入力なしなら None (0.0 の捏造をしない)

    def test_esd_propagation_first_order(self) -> None:
        """σ²(x) = Σ ((x_k − x)/(FW_k·S))²·σ²(w_k) の解析値と一致。"""
        w = {"A": 0.5, "B": 0.5}
        fw = {"A": 100.0, "B": 50.0}
        xp = {"A": 2.0, "B": 1.0}
        w_esd = {"A": 0.02, "B": 0.02}
        x, esd = x_xrd_from_weight_fractions(w, fw, xp, weight_esd=w_esd)
        s = 0.5 / 100.0 + 0.5 / 50.0
        var = sum(
            ((xp[k] - x) / (fw[k] * s)) ** 2 * w_esd[k] ** 2 for k in ("A", "B")
        )
        assert esd == pytest.approx(math.sqrt(var), rel=1e-9)

    def test_x_esd_term_added(self) -> None:
        """占有率 esd 項 (diagnose): σ² に Σ φ_k²·σ²(x_k) が加算される。"""
        w = {"A": 1.0}
        _, esd = x_xrd_from_weight_fractions(
            w, {"A": 100.0}, {"A": 2.0}, x_esd={"A": 0.1}
        )
        assert esd == pytest.approx(0.1)


class TestFeasibility:
    def test_in_range(self) -> None:
        assert feasibility(1.5, {"a": 1.0, "b": 2.0}) == "feasible"

    def test_out_of_range(self) -> None:
        assert feasibility(2.5, {"a": 1.0, "b": 2.0}) == "infeasible"
        assert feasibility(0.5, {"a": 1.0, "b": 2.0}) == "infeasible"

    def test_degenerate_equal_content(self) -> None:
        """xᵢ が相間で等しい → 制約は和制約と縮退 → skip 対象。"""
        assert feasibility(1.0, {"a": 1.0, "b": 1.0}) == "degenerate"

    def test_single_phase_is_degenerate(self) -> None:
        assert feasibility(1.0, {"a": 1.0}) == "degenerate"


class TestCoulometricFractions:
    def test_two_phase_equal_z(self) -> None:
        """Z 等値: Scale_1 = (x_t − x_2)/(x_1 − x_2)。"""
        s = coulometric_fractions(
            1.25, {"a": 2.0, "b": 1.0}, z_formula={"a": 1.0, "b": 1.0}
        )
        assert s["a"] == pytest.approx(0.25)
        assert s["b"] == pytest.approx(0.75)

    def test_two_phase_asymmetric_z(self) -> None:
        """Z 非対称でもモル平均が x_total に一致する解になる。"""
        s = coulometric_fractions(
            1.25, {"a": 2.0, "b": 1.0}, z_formula={"a": 4.0, "b": 2.0}
        )
        n = {k: s[k] * z for k, z in {"a": 4.0, "b": 2.0}.items()}
        tot = sum(n.values())
        x = (n["a"] * 2.0 + n["b"] * 1.0) / tot
        assert x == pytest.approx(1.25, rel=1e-12)
        assert sum(s.values()) == pytest.approx(1.0)

    def test_infeasible_raises(self) -> None:
        with pytest.raises(ValueError, match="範囲"):
            coulometric_fractions(3.0, {"a": 2.0, "b": 1.0}, z_formula={"a": 1.0, "b": 1.0})

    def test_three_phase_unsupported(self) -> None:
        """3 相以上は 1 DOF 残り解が一意でない → 明示エラー (要件5 は 2 相を主対象)。"""
        with pytest.raises(ValueError, match="2"):
            coulometric_fractions(
                1.0, {"a": 2.0, "b": 1.0, "c": 0.5},
                z_formula={"a": 1.0, "b": 1.0, "c": 1.0},
            )


class TestFrameTargetShape:
    def test_frame_target_is_frozen(self) -> None:
        t = FrameTarget(frame_index=0, x_total=1.0, n_e=0.5, state="charge", in_span=True)
        with pytest.raises((AttributeError, TypeError)):
            t.x_total = 2.0  # type: ignore[misc]
