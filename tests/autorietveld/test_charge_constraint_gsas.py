"""FR-318 T7/T8/T10/T12 の GSAS 統合テスト (PbSO4 実データ, @pytest.mark.gsas)。

- T7: atom_occupancy/atom_uiso/atom_multiplicity のラベルキー配線 + occupancy esd の 4 状態
- T8: initial_occupancies シーダー (占有率グループ非宣言なら値は凍結されたまま)
- T10: ChemComp restraint 直接注入 (占有率が目標へ引かれる / 無拘束コントロールとの比較)
- T12: lock_fractions 相間 EqnConstr (相分率がクーロメトリー解へ拘束される)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import RefinementStage
from tsumugin.operando.coulometry import coulometric_fractions

_DATA = Path("docs/benchmark/testdata")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "PBSO4.XRA").exists() and (_DATA / "PbSO4-Wyckoff.cif").exists()


def _hist() -> HistogramSpec:
    return HistogramSpec(
        data_path=str(_DATA / "PBSO4.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )


def _phase(name: str = "pbso4", **kw) -> PhaseSpec:
    return PhaseSpec(
        structure_path=str(_DATA / "PbSO4-Wyckoff.cif"),
        phase_name=name, format_hint="CIF", **kw,
    )


def _stages(*pairs) -> tuple[RefinementStage, ...]:
    return tuple(RefinementStage(label=lb, flags=fl, note="") for lb, fl in pairs)


_SB = ("sb", {"scale": True, "background": {"coeffs": 6}})


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
class TestAtomWiring:
    """T7/T11: 原子パラメータがラベルキーで結果に配線される。"""

    def test_atom_maps_populated(self) -> None:
        r = run_auto_rietveld([_hist()], [_phase()], recipe=_stages(_SB), max_cyc=3)
        # ラベルキーの占有率 (CIF 値 1.0 のまま)
        assert r.atom_occupancy["pbso4"]["Pb"] == pytest.approx(1.0)
        assert set(r.atom_occupancy["pbso4"]) == {"Pb", "S", "O1", "O2", "O3"}
        # Uiso (CIF 0.010)
        assert r.atom_uiso["pbso4"]["Pb"] == pytest.approx(0.010, abs=1e-6)
        # サイト多重度 (Pnma: Pb/S/O1/O2 = 4c, O3 = 8d) — mult/Z 照合の材料 (REQ-318-008)
        assert r.atom_multiplicity["pbso4"]["Pb"] == pytest.approx(4.0)
        assert r.atom_multiplicity["pbso4"]["O3"] == pytest.approx(8.0)
        # 占有率 esd: 精密化していない → None (0.0 の無限精度捏造をしない; §4.5 規則⑤)
        assert r.atom_occupancy_esd["pbso4"]["Pb"] is None

    def test_occupancy_esd_present_when_refined(self) -> None:
        """占有率を精密化した原子の esd は > 0 (共分散由来)。"""
        r = run_auto_rietveld(
            [_hist()],
            [_phase(free_occupancy_labels=("Pb",))],
            recipe=_stages(_SB, ("occ", {"occupancy": True})),
            max_cyc=3,
        )
        esd = r.atom_occupancy_esd["pbso4"]["Pb"]
        assert esd is not None and esd > 0.0
        # 精密化対象外の S は None のまま
        assert r.atom_occupancy_esd["pbso4"]["S"] is None


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
class TestInitialOccupancies:
    """T8: 値シーダー。占有率グループ非宣言なら精密化されず固定のまま (fix モードの機構)。"""

    def test_seeded_value_survives_unrefined(self) -> None:
        r = run_auto_rietveld(
            [_hist()], [_phase()],
            recipe=_stages(_SB),
            max_cyc=3,
            initial_occupancies={"pbso4": {"Pb": 0.8}},
        )
        # F フラグが立たない (どの占有率グループにも属さない) → 値は seed のまま
        assert r.atom_occupancy["pbso4"]["Pb"] == pytest.approx(0.8)
        assert r.atom_occupancy_esd["pbso4"]["Pb"] is None  # 精密化していない
        # 他原子は CIF 値のまま
        assert r.atom_occupancy["pbso4"]["S"] == pytest.approx(1.0)

    def test_unknown_label_fails_open(self) -> None:
        """未知ラベルは無視 (fail-open, `_apply_initial_fractions` と同じ規律)。"""
        r = run_auto_rietveld(
            [_hist()], [_phase()],
            recipe=_stages(_SB),
            max_cyc=3,
            initial_occupancies={"pbso4": {"Xx": 0.5}},
        )
        assert r.atom_occupancy["pbso4"]["Pb"] == pytest.approx(1.0)


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
class TestChemCompRestraint:
    """T10: ChemComp restraint の直接注入 + **headless 無効のカナリア**。

    実測 (engine `_apply_chem_comp_restraints` docstring): 本バージョンの GSAS-II は headless
    最小二乗で restraint penalty が機能しない (χ² 除外 / Hessian 勾配符号逆 / Jacobian 不動)。
    注入機構は正しく、penalty 評価・.lst 報告までは動く — **効かないのは最小二乗への取り込み**。
    """

    def test_restraint_injected_and_survives_refinement(self) -> None:
        """注入した ChemComp が精密化後も gpx ツリーに残る (revert 生存の機構検証)。"""
        import tempfile
        from pathlib import Path as _P

        with tempfile.TemporaryDirectory() as tmp:
            keep = str(_P(tmp) / "out.gpx")
            r = run_auto_rietveld(
                [_hist()], [_phase(free_occupancy_labels=("Pb",))],
                recipe=_stages(_SB, ("occ", {"occupancy": True})),
                max_cyc=3,
                chem_comp_restraints={
                    "pbso4": [
                        {"labels": ["Pb"], "total": 3.2, "esd": 0.005, "weight": 10000.0}
                    ]
                },
                keep_gpx=keep,
            )
            assert r.final_rwp < 40.0  # 精密化自体は完走
            from GSASII import GSASIIstrIO as G2stIO

            rd = G2stIO.GetRestraints(keep)
            sites = rd["pbso4"]["ChemComp"]["Sites"]
            assert len(sites) == 1
            assert sites[0][2] == pytest.approx(3.2)  # obs (セルあたり目標)
            assert rd["pbso4"]["ChemComp"]["Use"] is True

    def test_canary_headless_penalty_is_inert(self) -> None:
        """★カナリア: headless では拘束が占有率を動かさない (GSAS-II バグの現状ピン留め)。

        **このテストが fail したら朗報** — GSAS-II 更新で restraint が headless で機能する
        ようになった可能性が高い。`insitu.charge.plan_frame_constraint` の soft→diagnose 縮退を
        解除し、soft モードを再有効化すること (engine docstring の実測 3 経路を再検証)。
        """
        r = run_auto_rietveld(
            [_hist()], [_phase(free_occupancy_labels=("Pb",))],
            recipe=_stages(_SB, ("occ", {"occupancy": True})),
            max_cyc=4,
            chem_comp_restraints={
                "pbso4": [
                    {"labels": ["Pb"], "total": 3.2, "esd": 0.005, "weight": 10000.0}
                ]
            },
        )
        occ = r.atom_occupancy["pbso4"]["Pb"]
        # 拘束が効いていれば 0.8 側へ大きく引かれるはず。現状は満占有データ解 (~1.0) のまま。
        assert occ > 0.95, (
            f"ChemComp 拘束が headless で効いた (occ={occ}) — GSAS-II が修復された可能性。"
            "soft モードの縮退を解除せよ (engine._apply_chem_comp_restraints docstring)"
        )


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
class TestLockFractions:
    """T12: 相間 EqnConstr Σ cᵢ·Scaleᵢ = 0 が相分率をクーロメトリー解へ拘束する。

    同一構造 2 相 (完全縮退 = XRD は分率を決められない) に拘束を課すと、分率は
    `coulometric_fractions` の解析解に一致するはず — 拘束機構の純粋な検証。
    """

    def test_fractions_forced_to_coulometric_solution(self) -> None:
        x_per_phase = {"a": 2.0, "b": 1.0}
        z = {"a": 4.0, "b": 4.0}
        x_total = 1.25
        expected = coulometric_fractions(x_total, x_per_phase, z_formula=z)
        # 係数 cᵢ = Zᵢ·(xᵢ − x_total)
        coeffs = {nm: z[nm] * (x_per_phase[nm] - x_total) for nm in x_per_phase}
        r = run_auto_rietveld(
            [_hist()],
            [_phase("a"), _phase("b")],
            recipe=_stages(_SB, ("fr", {"phase_fraction_sum": True})),
            max_cyc=4,
            content_constraint=coeffs,
        )
        assert r.phase_fractions["a"] == pytest.approx(expected["a"], abs=0.02)
        assert r.phase_fractions["b"] == pytest.approx(expected["b"], abs=0.02)
