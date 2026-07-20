"""② `alkali_budget` + `charge_constraint` spec (FR-318 T15/T16) のテスト (numpy, GSAS/galvani 非依存)。

MPR 実ファイルは要らない — `alkali_budget` の縮退 (galvani 未導入/ファイル無し) と、
`_apply_charge_constraint_spec` の JSON 往復 + `sequential_rietveld` の E2E (スタブ runner) を検証。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport
from tsumugin.mcp.echem_tools import alkali_budget
from tsumugin.mcp.insitu_tools import _apply_charge_constraint_spec, sequential_rietveld
from tsumugin.insitu.model import FrameSpec

_CC_SPEC = {
    "config": {
        "mobile_sites": [
            {"phase_name": "mono", "site_labels": ["K"], "multiplicities": [4.0]},
        ],
        "z_formula": {"mono": 2.0},
        "formula_weights": {"mono": 678.8},
        "mode": "diagnose",
    },
    # alkali_budget の出力 targets そのままの形 (§4.5 到達可能性)
    "targets": [
        {"frame": 0, "x_total": 1.944, "n_e": 0.0, "state": "rest", "in_span": True},
        {"frame": 1, "x_total": 1.8, "n_e": 0.144, "state": "charge", "in_span": True},
        {"frame": 2, "x_total": None, "n_e": None, "state": "unknown", "in_span": False},
    ],
}


class TestAlkaliBudgetTool:
    def test_missing_file_degrades_to_error_dict(self) -> None:
        out = alkali_budget(
            "no_such_file.mpr", active_mass_mg=10.0, formula_weight=678.8, x0=1.944,
            offset_s=22.1, interval_s=283.0, n_frames=5,
        )
        assert "error" in out and "error_type" in out

    def test_exclusive_epoch_args_error(self) -> None:
        out = alkali_budget(
            "x.mpr", active_mass_mg=10.0, formula_weight=678.8, x0=2.0,
            frame_epoch_s=[0.0], offset_s=1.0,
        )
        assert out["error_type"] == "ValueError"


class TestChargeConstraintSpec:
    def _frames(self, n: int = 3) -> list[FrameSpec]:
        return [FrameSpec(data_path=f"f{i}.xye", axis_value=float(i)) for i in range(n)]

    def test_targets_list_from_alkali_budget_shape(self) -> None:
        cfg, out = _apply_charge_constraint_spec(_CC_SPEC, self._frames())
        assert cfg.enabled and cfg.mode == "diagnose"
        assert out[0].target_composition is not None
        assert out[0].target_composition.total == pytest.approx(1.944)
        assert out[1].target_composition.total == pytest.approx(1.8)
        # echem 範囲外 (x_total None) → 目標なし (拘束されない)
        assert out[2].target_composition is None

    def test_targets_mapping_form(self) -> None:
        spec = {**_CC_SPEC, "targets": {"0": 1.9, "2": 1.5}}
        _, out = _apply_charge_constraint_spec(spec, self._frames())
        assert out[0].target_composition.total == pytest.approx(1.9)
        assert out[1].target_composition is None
        assert out[2].target_composition.total == pytest.approx(1.5)

    def test_per_phase_content_stamped(self) -> None:
        spec = {**_CC_SPEC, "per_phase_content": {"mono": 1.944, "cubic": 1.0}}
        _, out = _apply_charge_constraint_spec(spec, self._frames())
        assert out[0].target_composition.per_phase["cubic"] == pytest.approx(1.0)

    def test_empty_config_raises(self) -> None:
        with pytest.raises(ValueError, match="mobile_sites"):
            _apply_charge_constraint_spec({"targets": []}, self._frames())

    def test_missing_targets_raises(self) -> None:
        with pytest.raises(ValueError, match="targets"):
            _apply_charge_constraint_spec({"config": _CC_SPEC["config"]}, self._frames())

    def test_out_of_range_target_index_raises(self) -> None:
        """レビュー MEDIUM: サブセット frames に全系列 targets を渡す位置ずれは、範囲外 index
        という確実な指紋を持つ — 黙って捨てず ValueError (境界で error dict へ縮退)。"""
        spec = {**_CC_SPEC, "targets": [{"frame": 246, "x_total": 1.9}]}
        with pytest.raises(ValueError, match="範囲外"):
            _apply_charge_constraint_spec(spec, self._frames(3))

    def test_negative_target_index_raises(self) -> None:
        """負 index も手組み spec の不備 — 黙って無視しない (第3巡ピン)。"""
        spec = {**_CC_SPEC, "targets": [{"frame": -1, "x_total": 1.9}]}
        with pytest.raises(ValueError, match="範囲外"):
            _apply_charge_constraint_spec(spec, self._frames(3))

    def test_empty_targets_raises(self) -> None:
        """空 targets は正規の alkali_budget 出力ではあり得ない (範囲外フレームも
        x_total=null で列挙される) — 「拘束ゼロで有効」に黙って縮退しない (第3巡ピン)。"""
        with pytest.raises(ValueError, match="空"):
            _apply_charge_constraint_spec({**_CC_SPEC, "targets": []}, self._frames(3))
        with pytest.raises(ValueError, match="空"):
            _apply_charge_constraint_spec({**_CC_SPEC, "targets": {}}, self._frames(3))


def _stub_result(rwp: float = 8.0) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=1.0,
        refined_cells={"mono": (10.09, 7.32, 6.96, 90, 90.4, 90)},
        validity=ValidityReport(passed=True),
        phase_fractions={"mono": 1.0}, n_obs=1000,
        atom_occupancy={"mono": {"K": 0.972}},
        atom_multiplicity={"mono": {"K": 4.0}},
        atom_occupancy_esd={"mono": {"K": 0.01}},
        phase_weight_fractions={"mono": 1.0},
        phase_weight_fraction_esd={"mono": 0.0},
    )


class TestSequentialRietveldE2E:
    """② → ① → ② の往復: charge_constraint spec が per-frame alkali_* 出力に届く。"""

    def test_alkali_keys_survive_boundary(self) -> None:
        frames = [
            {"data_path": f"f{i}.xye", "axis_value": float(i), "data_format": "XYE"}
            for i in range(3)
        ]
        phases = [{"structure_path": "mono.cif", "phase_name": "mono"}]

        def runner(frame, phases_, initial_cells):
            return _stub_result()

        out = sequential_rietveld(
            frames, phases, charge_constraint=_CC_SPEC, runner=runner,
        )
        assert "error" not in out
        f0 = out["frames"][0]
        assert f0["alkali_x_echem"] == pytest.approx(1.944)
        assert f0["alkali_x_xrd"] == pytest.approx(1.944)
        assert f0["alkali_residual"] == pytest.approx(0.0)
        # echem 範囲外フレームは None (捏造なし)
        f2 = out["frames"][2]
        assert f2["alkali_x_echem"] is None

    def test_bad_spec_degrades_to_error_dict(self) -> None:
        frames = [{"data_path": "f0.xye", "axis_value": 0.0, "data_format": "XYE"}]
        phases = [{"structure_path": "mono.cif", "phase_name": "mono"}]
        out = sequential_rietveld(
            frames, phases, charge_constraint={"targets": []},
            runner=lambda *a: _stub_result(),
        )
        assert out["error_type"] == "ValueError"

    def test_anchors_expose_alkali_for_per_phase_content(self) -> None:
        """最終レビュー F1 ピン: ③ の手順 (per_phase_content ← anchors[].alkali) が実行可能
        であること — anchored_sequential の anchors[] に alkali が実在する。"""
        from tsumugin.mcp.anchor_tools import anchored_sequential

        frames = [
            {"data_path": f"f{i}.xye", "axis_value": float(i), "data_format": "XYE"}
            for i in range(2)
        ]
        phases = [{"structure_path": "mono.cif", "phase_name": "mono"}]
        out = anchored_sequential(
            frames, phases, anchor_table={"0": ["mono"]},
            charge_constraint=_CC_SPEC, runner=lambda *a: _stub_result(),
        )
        assert "error" not in out
        a0 = out["anchors"][0]
        assert "alkali" in a0
        assert a0["alkali"]["alkali_x_xrd"] == pytest.approx(1.944)
        assert a0["alkali"]["alkali_per_phase"]["mono"] == pytest.approx(1.944)

    @pytest.mark.parametrize(
        "bad_cc",
        [
            {"config": "garbage", "targets": [{"frame": 0, "x_total": 1.0}]},  # 非 Mapping config
            {"config": {"mobile_sites": [{"phase_name": "m", "site_labels": ["K"],
                                          "multiplicities": [4.0]}],
                        "z_formula": {"m": 0.0}},  # z=0 → 下流 ZeroDivision (F2)
             "targets": [{"frame": 0, "x_total": 1.0}]},
            {"config": {"mobile_sites": [{"phase_name": "m", "site_labels": ["K"],
                                          "multiplicities": [0.0]}]},  # mult=0 (F2)
             "targets": [{"frame": 0, "x_total": 1.0}]},
            {"config": {"mobile_sites": [{"phase_name": "m", "site_labels": ["K"],
                                          "multiplicities": [4.0]}],
                        "z_formula": "garbage"},  # 深い入れ子のゴミ → AttributeError 系
             "targets": [{"frame": 0, "x_total": 1.0}]},
            {"config": {"mobile_sites": [{"phase_name": "m", "site_labels": ["K"],
                                          "multiplicities": [4.0]}], "mode": "hard"},
             "targets": [{"frame": 0, "x_total": 1.0}]},  # 不正 mode
            "not-a-dict",  # spec 自体が dict でない
        ],
    )
    def test_malformed_spec_never_raises_across_boundary(self, bad_cc) -> None:
        """F-final-1 ピン: どんなゴミ spec でも②は例外を送出せず error dict へ縮退する
        (両ツール)。旧実装は非 Mapping config の AttributeError が境界を貫通した。"""
        from tsumugin.mcp.anchor_tools import anchored_sequential

        frames = [{"data_path": "f0.xye", "axis_value": 0.0, "data_format": "XYE"}]
        phases = [{"structure_path": "mono.cif", "phase_name": "mono"}]
        out = sequential_rietveld(
            frames, phases, charge_constraint=bad_cc, runner=lambda *a: _stub_result(),
        )
        assert "error" in out and "error_type" in out
        out2 = anchored_sequential(
            frames, phases, charge_constraint=bad_cc, runner=lambda *a: _stub_result(),
        )
        assert "error" in out2 and "error_type" in out2
