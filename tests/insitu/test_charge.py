"""FR-318 insitu.charge (モード分岐 + 診断) の numpy テスト (GSAS 非依存・決定論)。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.charge import (
    frame_alkali_report,
    multiplicity_mismatch_warnings,
    plan_frame_constraint,
)
from tsumugin.insitu.engine import run_sequential_rietveld
from tsumugin.insitu.model import (
    ChargeConstraintConfig,
    FrameSpec,
    SequentialConfig,
    TargetComposition,
)
from tsumugin.operando.coulometry import MobileSiteSpec


def _cfg(mode: str = "diagnose", **kw) -> ChargeConstraintConfig:
    return ChargeConstraintConfig(
        mobile_sites=(
            MobileSiteSpec(phase_name="mono", site_labels=("K",), multiplicities=(4.0,)),
            MobileSiteSpec(phase_name="cubic", site_labels=("K",), multiplicities=(8.0,)),
        ),
        z_formula={"mono": 2.0, "cubic": 4.0},
        formula_weights={"mono": 678.8, "cubic": 1103.4},
        mode=mode,
        **kw,
    )


def _tc(total: float, mode: str = "diagnose", per_phase=None, esd: float = 0.05):
    return TargetComposition(
        total=total, per_phase=per_phase or {}, mode=mode, esd=esd
    )


class TestPlanSinglePhase:
    def test_none_tc_gives_empty_plan(self) -> None:
        p = plan_frame_constraint(None, _cfg(), ["mono"])
        assert p.kwargs == {} and p.applied == "" and not p.warnings

    def test_disabled_cfg_gives_empty_plan(self) -> None:
        p = plan_frame_constraint(_tc(1.0), ChargeConstraintConfig(), ["mono"])
        assert p.kwargs == {}

    def test_diagnose_no_kwargs(self) -> None:
        p = plan_frame_constraint(_tc(1.5, "diagnose"), _cfg(), ["mono"])
        assert p.kwargs == {} and p.applied == ""

    def test_fix_seeds_occupancy(self) -> None:
        """fix: x=1.5, Z=2, mult=4 → occ = 1.5·2/4 = 0.75 に凍結シード。"""
        p = plan_frame_constraint(_tc(1.5, "fix"), _cfg(), ["mono"])
        assert p.applied == "fix"
        occ = p.kwargs["initial_occupancies"]["mono"]["K"]
        assert occ == pytest.approx(0.75)

    def test_soft_degrades_with_headless_bug_warning(self) -> None:
        """soft は現行 GSAS-II headless で penalty が効かない (実測) → 診断縮退 + 警告。

        カナリア (`test_canary_headless_penalty_is_inert`) が fail したら本縮退を解除し、
        x×Z (セルあたり) 換算の ChemComp spec を組み立てる実装へ戻すこと。
        """
        p = plan_frame_constraint(_tc(1.5, "soft", esd=0.02), _cfg(), ["mono"])
        assert p.applied == ""
        assert "chem_comp_restraints" not in p.kwargs
        assert any("headless" in w or "機能しません" in w for w in p.warnings)

    def test_lock_on_single_phase_degrades(self) -> None:
        p = plan_frame_constraint(_tc(1.5, "lock_fractions"), _cfg(), ["mono"])
        assert p.applied == "" and p.kwargs == {}
        assert any("単相" in w for w in p.warnings)

    def test_no_mobile_site_phase_warns(self) -> None:
        p = plan_frame_constraint(_tc(1.5, "fix"), _cfg(), ["unknown_phase"])
        assert p.kwargs == {} and any("存在しません" in w for w in p.warnings)


class TestPlanMultiPhase:
    _PER = {"mono": 1.944, "cubic": 1.0}

    def test_diagnose_multi_seeds_anchor_x(self) -> None:
        """多相 diagnose: xᵢ をアンカー値に凍結シード (Scale は自由)。拘束は無し。"""
        p = plan_frame_constraint(
            _tc(1.5, "diagnose", per_phase=self._PER), _cfg(), ["mono", "cubic"]
        )
        assert p.applied == ""
        occ = p.kwargs["initial_occupancies"]
        assert occ["mono"]["K"] == pytest.approx(1.944 * 2.0 / 4.0)
        assert occ["cubic"]["K"] == pytest.approx(1.0 * 4.0 / 8.0)
        assert "content_constraint" not in p.kwargs
        assert p.feasibility == "feasible"

    def test_lock_builds_linear_constraint(self) -> None:
        """lock: 係数 cᵢ = Zᵢ·(xᵢ − x_total) + 2相の完全決定警告。"""
        p = plan_frame_constraint(
            _tc(1.5, "lock_fractions", per_phase=self._PER), _cfg(), ["mono", "cubic"]
        )
        assert p.applied == "lock_fractions"
        c = p.kwargs["content_constraint"]
        assert c["mono"] == pytest.approx(2.0 * (1.944 - 1.5))
        assert c["cubic"] == pytest.approx(4.0 * (1.0 - 1.5))
        assert any("完全決定" in w for w in p.warnings)

    def test_lock_infeasible_degrades_with_warning(self) -> None:
        """x_total が範囲外 → 拘束せず縮退 + 不可逆容量疑いの警告 (REQ-318-004)。"""
        p = plan_frame_constraint(
            _tc(2.5, "lock_fractions", per_phase=self._PER), _cfg(), ["mono", "cubic"]
        )
        assert p.applied == ""
        assert "content_constraint" not in p.kwargs
        assert p.feasibility == "infeasible"
        assert any("不可逆容量" in w for w in p.warnings)

    def test_lock_degenerate_skips(self) -> None:
        p = plan_frame_constraint(
            _tc(1.0, "lock_fractions", per_phase={"mono": 1.0, "cubic": 1.0}),
            _cfg(), ["mono", "cubic"],
        )
        assert p.applied == "" and p.feasibility == "degenerate"

    def test_missing_per_phase_degrades(self) -> None:
        p = plan_frame_constraint(
            _tc(1.5, "lock_fractions", per_phase={"mono": 1.944}), _cfg(),
            ["mono", "cubic"],
        )
        assert p.applied == "" and any("per_phase" in w for w in p.warnings)

    def test_soft_multi_degrades_to_diagnose(self) -> None:
        p = plan_frame_constraint(
            _tc(1.5, "soft", per_phase=self._PER), _cfg(), ["mono", "cubic"]
        )
        assert p.applied == ""
        assert "chem_comp_restraints" not in p.kwargs
        assert any("非ネイティブ" in w for w in p.warnings)


class TestMultiplicityCheck:
    def test_match_silent(self) -> None:
        assert multiplicity_mismatch_warnings(_cfg(), {"mono": {"K": 4.0}}) == ()

    def test_mismatch_warns(self) -> None:
        w = multiplicity_mismatch_warnings(_cfg(), {"mono": {"K": 8.0}})
        assert len(w) == 1 and "不一致" in w[0]

    def test_missing_label_warns(self) -> None:
        w = multiplicity_mismatch_warnings(_cfg(), {"mono": {"Na": 4.0}})
        assert len(w) == 1 and "ラベル" in w[0]


class TestFrameAlkaliReport:
    def test_single_phase(self) -> None:
        """単相: x = occ·mult/Z (GSAS mult 優先) + 占有率 esd の伝播。"""
        r = frame_alkali_report(
            tc=_tc(1.9),
            cfg=_cfg(),
            phase_names=["mono"],
            atom_occupancy={"mono": {"K": 0.972}},
            atom_multiplicity={"mono": {"K": 4.0}},
            atom_occupancy_esd={"mono": {"K": 0.01}},
        )
        assert r.x_xrd == pytest.approx(1.944)
        assert r.x_xrd_esd == pytest.approx(0.01 * 4.0 / 2.0)
        assert r.residual == pytest.approx(1.944 - 1.9)
        assert r.per_phase["mono"] == pytest.approx(1.944)

    def test_multi_phase_molar_average(self) -> None:
        """多相: FW 除算のモル平均 (x_xrd_from_weight_fractions に委譲)。"""
        r = frame_alkali_report(
            tc=_tc(1.5),
            cfg=_cfg(),
            phase_names=["mono", "cubic"],
            atom_occupancy={"mono": {"K": 0.972}, "cubic": {"K": 0.5}},
            atom_multiplicity={"mono": {"K": 4.0}, "cubic": {"K": 8.0}},
            phase_weight_fractions={"mono": 0.5, "cubic": 0.5},
        )
        # x_mono=1.944, x_cubic=1.0; φmol ∝ w/FW
        n_mono = 0.5 / 678.8
        n_cubic = 0.5 / 1103.4
        expected = (n_mono * 1.944 + n_cubic * 1.0) / (n_mono + n_cubic)
        assert r.x_xrd == pytest.approx(expected, rel=1e-9)
        assert r.x_xrd_esd is None  # esd 入力なし → None (0.0 捏造なし)

    def test_gsas_mult_wins_over_spec(self) -> None:
        """GSAS 実 mult (2.0) が spec (4.0) より優先され、警告も出る。"""
        r = frame_alkali_report(
            tc=_tc(1.0),
            cfg=_cfg(),
            phase_names=["mono"],
            atom_occupancy={"mono": {"K": 1.0}},
            atom_multiplicity={"mono": {"K": 2.0}},
        )
        assert r.per_phase["mono"] == pytest.approx(2.0 / 2.0)
        assert any("不一致" in w for w in r.warnings)

    def test_disabled_cfg_empty(self) -> None:
        r = frame_alkali_report(
            tc=_tc(1.0), cfg=ChargeConstraintConfig(), phase_names=["mono"],
            atom_occupancy={}, atom_multiplicity={},
        )
        assert r.x_xrd is None and r.x_echem is None

    def test_missing_occupancy_warns(self) -> None:
        r = frame_alkali_report(
            tc=_tc(1.0), cfg=_cfg(), phase_names=["mono"],
            atom_occupancy={"mono": {"Pb": 1.0}},  # K が無い
            atom_multiplicity={"mono": {}},
        )
        assert r.x_xrd is None
        assert any("算出できません" in w for w in r.warnings)


# --------------------------------------------------------------------------------------
# T13/T14: エンジン統合 (スタブ runner, GSAS 非依存)
# --------------------------------------------------------------------------------------


def _stub_result(rwp: float, occ_k: float = 0.972) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells={"mono": (10.09, 7.32, 6.96, 90, 90.4, 90)},
        validity=ValidityReport(passed=True),
        phase_fractions={"mono": 1.0},
        n_obs=1000,
        atom_occupancy={"mono": {"K": occ_k}},
        atom_multiplicity={"mono": {"K": 4.0}},
        atom_occupancy_esd={"mono": {"K": 0.01}},
        phase_weight_fractions={"mono": 1.0},
        phase_weight_fraction_esd={"mono": 0.0},
    )


class TestSequentialIntegration:
    """T13: run_sequential_rietveld が alkali_* フィールドをフレーム結果へ流し込む。"""

    def test_alkali_fields_attached(self) -> None:
        spec = PhaseSpec(structure_path="mono.cif", phase_name="mono")
        frames = [
            FrameSpec(
                data_path=f"f{i}.xye", axis_value=float(i), data_format="XYE",
                target_composition=TargetComposition(total=1.9 - 0.1 * i),
            )
            for i in range(3)
        ]
        cfg = SequentialConfig(charge_constraint=_cfg())

        def runner(frame, phases, initial_cells):
            return _stub_result(8.0)

        res = run_sequential_rietveld(frames, [spec], config=cfg, runner=runner)
        fr = res.frames[0]
        assert fr.alkali_x_echem == pytest.approx(1.9)
        assert fr.alkali_x_xrd == pytest.approx(1.944)  # 0.972×4/2
        assert fr.alkali_residual == pytest.approx(1.944 - 1.9)
        assert fr.alkali_x_xrd_esd == pytest.approx(0.02)
        # フレーム毎の目標が変わる
        assert res.frames[2].alkali_x_echem == pytest.approx(1.7)

    def test_disabled_leaves_defaults(self) -> None:
        """機能無効 (charge_constraint なし) なら既定値のまま (後方互換)。"""
        spec = PhaseSpec(structure_path="mono.cif", phase_name="mono")
        frames = [FrameSpec(data_path="f0.xye", axis_value=0.0, data_format="XYE")]

        def runner(frame, phases, initial_cells):
            return _stub_result(8.0)

        res = run_sequential_rietveld(frames, [spec], runner=runner)
        fr = res.frames[0]
        assert fr.alkali_x_echem is None and fr.alkali_x_xrd is None
        assert fr.alkali_constraint_applied == ""


class TestAnchorAB:
    """T14: アンカー A/B (制約有無) → ΔRwp 警告 + x₀ 校正提案 (提案≠適用)。"""

    def _run(self, delta_rwp: float, threshold: float = 1.0):
        from tsumugin.insitu.anchor import run_anchored_sequential

        spec = PhaseSpec(structure_path="mono.cif", phase_name="mono")
        cfg = _cfg()
        cfg = ChargeConstraintConfig(
            mobile_sites=cfg.mobile_sites, z_formula=cfg.z_formula,
            formula_weights=cfg.formula_weights, anchor_ab_threshold=threshold,
        )
        frames = [
            FrameSpec(
                data_path=f"f{i}.xye", axis_value=float(i), data_format="XYE",
                target_composition=TargetComposition(total=1.8),
            )
            for i in range(3)
        ]

        def runner(frame, phases, initial_cells):
            # B (fix モード) は A より delta_rwp だけ悪い — 不可逆容量のシミュレーション
            tc = frame.target_composition
            if tc is not None and tc.mode == "fix":
                return _stub_result(8.0 + delta_rwp)
            return _stub_result(8.0)

        res = run_anchored_sequential(
            frames, [spec], runner=runner, identifier=None, charge_constraint=cfg,
        )
        return res

    def test_large_delta_warns_and_proposes(self) -> None:
        res = self._run(delta_rwp=3.0, threshold=1.0)
        assert any("不可逆容量" in w for w in res.warnings)
        kinds = [e.kind for e in res.ledger.entries]
        assert "fr318_anchor_ab" in kinds
        assert "fr318_x0_calibration_proposal" in kinds
        prop = next(
            e for e in res.ledger.entries if e.kind == "fr318_x0_calibration_proposal"
        )
        assert prop.payload["applied"] is False  # 提案≠適用
        assert prop.payload["x_refined"] == pytest.approx(1.944)
        assert prop.payload["x_echem"] == pytest.approx(1.8)

    def test_small_delta_no_warning(self) -> None:
        res = self._run(delta_rwp=0.2, threshold=1.0)
        assert not any("不可逆容量" in w for w in res.warnings)
        kinds = [e.kind for e in res.ledger.entries]
        assert "fr318_anchor_ab" in kinds  # A/B 自体は記録される
        assert "fr318_x0_calibration_proposal" not in kinds

    def test_anchor_value_comes_from_free_run(self) -> None:
        """アンカー本体は制約なし (A) の結果 — Rwp が A のもの。"""
        res = self._run(delta_rwp=3.0)
        anchor_frame = res.frames[0]
        assert anchor_frame.rwp == pytest.approx(8.0)  # A (free) の Rwp
        assert anchor_frame.alkali_x_xrd == pytest.approx(1.944)
