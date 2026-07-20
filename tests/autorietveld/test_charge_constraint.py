"""FR-318 T8/T9 の numpy 部: initial_occupancies の事前検証と Uiso 妥当性/結合警告 (GSAS 不要)。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import (
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
)
from tsumugin.autorietveld.validity import (
    check_initial_uiso,
    warn_occupancy_uiso_coupling,
)


def _hist() -> HistogramSpec:
    return HistogramSpec(
        data_path="dummy.xra", instrument_path="dummy.prm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
    )


def _phase() -> PhaseSpec:
    return PhaseSpec(structure_path="dummy.cif", phase_name="p", format_hint="CIF")


class TestInitialOccupanciesValidation:
    """REQ-318-002: 範囲外の占有率指定は GSAS に触れる前に大声で失敗する。"""

    def test_out_of_range_raises_before_gsas(self) -> None:
        from tsumugin.autorietveld.engine import run_auto_rietveld

        # ダミーパスでも GSAS import 前に検証が走るため ValueError になる (FileNotFound でなく)
        with pytest.raises(ValueError, match="占有率"):
            run_auto_rietveld(
                [_hist()], [_phase()],
                initial_occupancies={"p": {"Pb": 1.5}},
            )

    def test_negative_raises(self) -> None:
        from tsumugin.autorietveld.engine import run_auto_rietveld

        with pytest.raises(ValueError, match="占有率"):
            run_auto_rietveld(
                [_hist()], [_phase()],
                initial_occupancies={"p": {"Pb": -0.1}},
            )


class TestInitialUisoCheck:
    """REQ-318-005: 初期 Uiso の妥当帯 [1e-3, 0.05] を外れたら**精密化前に**警告。"""

    def test_plausible_no_warning(self) -> None:
        assert check_initial_uiso({"p": {"Pb": 0.010, "O1": 0.015}}) == ()

    def test_too_small_warns(self) -> None:
        w = check_initial_uiso({"p": {"Pb": 1e-5}})
        assert len(w) == 1
        assert "Pb" in w[0] and "Uiso" in w[0]

    def test_too_large_warns(self) -> None:
        w = check_initial_uiso({"p": {"K": 0.2}})
        assert len(w) == 1 and "K" in w[0]

    def test_custom_band(self) -> None:
        # 可動イオンは大きめの Uiso が物理的 → 上限を緩められる
        assert check_initial_uiso({"p": {"K": 0.08}}, uiso_max=0.10) == ()


class TestOccupancyUisoCoupling:
    """REQ-318-005: 占有率と Uiso の同時精密化は縮退 → 導出組成が汚染される警告。"""

    def _stage(self, label: str, flags: dict) -> RefinementStage:
        return RefinementStage(label=label, flags=flags, note="")

    def test_both_stages_warn(self) -> None:
        recipe = (
            self._stage("occ", {"occupancy": True}),
            self._stage("uiso", {"uiso": True}),
        )
        w = warn_occupancy_uiso_coupling(recipe)
        assert len(w) == 1
        assert "占有率" in w[0] and "Uiso" in w[0]

    def test_occupancy_only_no_warning(self) -> None:
        recipe = (self._stage("occ", {"occupancy": True}),)
        assert warn_occupancy_uiso_coupling(recipe) == ()

    def test_neither_no_warning(self) -> None:
        recipe = (self._stage("sb", {"scale": True}),)
        assert warn_occupancy_uiso_coupling(recipe) == ()
