"""FR-318 T7/T8/T10/T12 の GSAS 統合テスト (PbSO4 実データ, @pytest.mark.gsas)。

- T7: atom_occupancy/atom_uiso/atom_multiplicity のラベルキー配線 + occupancy esd の 4 状態
- T8: initial_occupancies シーダー (占有率グループ非宣言なら値は凍結されたまま)
- T10: ChemComp restraint 直接注入 (占有率が目標へ引かれる / 無拘束コントロールとの比較)
- T12: lock_fractions 相間 EqnConstr (相分率がクーロメトリー解へ拘束される)
- Issue #112: bond_restraints も headless で非機能 (距離ターゲット非追従) のカナリア
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
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
            assert r.final_rwp < 60.0  # 精密化自体は完走 (短縮レシピなので閾は緩く)
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


def _so2_distance(gpx_path: str) -> float:
    """保存済み gpx から PbSO4 の S–O2 結合距離 (Å) を読む (bond_restraints カナリア用)。"""
    from GSASII import GSASIIlattice as G2lat
    from GSASII import GSASIIscriptable as G2sc

    ph = G2sc.G2Project(gpx_path).phases()[0]
    cell = ph.data["General"]["Cell"][1:7]
    _recip, g_metric = G2lat.cell2Gmat(cell)
    coords = {a.label: np.array(a.coordinates) for a in ph.atoms()}
    d = coords["S"] - coords["O2"]
    d = d - np.round(d)  # 最小イメージ
    return float(np.sqrt(np.dot(d, np.dot(g_metric, d))))


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
class TestBondRestraintHeadlessCanary:
    """Issue #112: bond_restraints も headless 最小二乗で**距離拘束として機能しない**カナリア。

    背景 (`_apply_chem_comp_restraints` docstring + 本ファイル TestChemCompRestraint と同根):
    GSAS-II `GSASIIstrMath.errRefine` は penalty 残差を ``if len(pVals) and dlg:`` (L5203) で
    ゲートし、headless (dlg=None) では**全 restraint 種の penalty を χ² から除外**する。
    `penaltyFxn`/`penaltyDeriv` は Bond/Angle/ChemComp を共有処理するため Bond も同じゲート下。

    実測 (この構成): 距離ターゲットを 1.9 Å と 2.3 Å (0.4 Å 差・データ真値 ~1.41 から遠い) に
    しても最終 S–O2 距離は**ビット同一**で、いずれもデータ値近傍に留まりターゲットへ全く追従
    しない。機能する距離拘束はターゲット非依存 (target-invariant) になり得ないため、これは
    「拘束が最小二乗目的関数に入っていない」ことの決定的証拠。拘束は HessRefine 経由で
    小さな飽和摂動を注入するのみ (dose 非依存・Rwp は僅かに悪化) で距離を引かない。

    ★ **このカナリアが fail したら朗報** — GSAS-II 更新で bond restraint が headless で
    機能するようになった可能性が高い。engine `_apply_bond_restraints` の非機能 caveat と
    skill 記述を実態に合わせて再検証し、依存機能 (D/H 漂流防止等) を再有効化すること。
    """

    @staticmethod
    def _bond_spec(target: float, weight: float) -> dict:
        return {
            "pbso4": [
                {
                    "origin": ["S"],
                    "target": ["O1", "O2", "O3"],
                    "distance": target,
                    "esd": 0.005,
                    "factor": 1.45,
                    "weight": weight,
                }
            ]
        }

    def _run(self, tmp: str, target: float | None, *, weight: float = 1.0e5) -> tuple[float, float, str]:
        import os

        keep = os.path.join(tmp, f"o_{target}_{weight}.gpx")
        br = None if target is None else self._bond_spec(target, weight)
        r = run_auto_rietveld(
            [_hist()],
            [_phase(free_occupancy_labels=())],
            recipe=_stages(_SB, ("xyz", {"coords": True})),
            max_cyc=10,
            bond_restraints=br,
            keep_gpx=keep,
        )
        return r.final_rwp, _so2_distance(keep), keep

    def test_bond_restraint_injected_and_survives(self) -> None:
        """拘束が gpx の Bond ツリーに登録され精密化後も残る (注入機構の検証)。

        「非機能」を「未登録」と取り違えないための対照 — 登録は正しく動くが最小二乗に
        効かない、を切り分ける。
        """
        import tempfile

        from GSASII import GSASIIstrIO as G2stIO

        with tempfile.TemporaryDirectory() as tmp:
            _rwp, _d, keep = self._run(tmp, 1.9)
            rd = G2stIO.GetRestraints(keep)
            bonds = rd["pbso4"]["Bond"]["Bonds"]
            assert len(bonds) > 0  # S–O 対が登録された
            assert rd["pbso4"]["Bond"]["Use"] is True

    def test_canary_bond_restraint_does_not_track_target(self) -> None:
        """★カナリア: 距離ターゲット 1.9 vs 2.3 で最終 S–O2 が不変 = 距離拘束として非機能。

        機能する拘束なら target=2.3 は target=1.9 より S–O2 を長く引くはず。実際は両者
        ビット同一かつデータ値近傍 (< 1.55 Å, ターゲット 1.9/2.3 から遠い) に留まる。

        **両方向を pin する** (レビュー指摘): ターゲット非追従 (機能拘束なら fail) に加え、
        拘束ありがベースライン (拘束なし) と異なる (= 現状は小さな摂動を注入している) ことも
        assert する。GSAS-II が Bond を ChemComp のように完全不動化した場合も docstring の
        「小さな飽和摂動を注入」記述が崩れるので、その退化も検知する。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _rwp0, d_none, _ = self._run(tmp, None)
            _rwp_a, d_a, _ = self._run(tmp, 1.9)
            _rwp_b, d_b, _ = self._run(tmp, 2.3)

        # ①ターゲット非追従: 0.4 Å 離れたターゲットで最終距離が実質同一 (機能拘束では不可能)
        assert abs(d_a - d_b) < 1.0e-6, (
            f"bond restraint がターゲットに追従した (1.9→{d_a:.4f}, 2.3→{d_b:.4f}) — "
            "GSAS-II が headless restraint を修復した可能性。engine の非機能 caveat を再検証せよ"
        )
        # ②データ値近傍に留まりターゲット (>=1.9) へ到達しない
        assert d_a < 1.55, f"S–O2={d_a:.4f} が想定外にターゲット側へ動いた"
        # ③拘束ありは拘束なしと異なる (現状は非ゲート HessRefine 経由の小摂動を注入している)。
        #   完全不動化 (ChemComp 化) したらここが fail し docstring の摂動記述を再検証させる。
        #   閾 5e-3 は weight=0 対照の cross-machine ノイズ上限 5e-4 の 10 倍 (ノイズで満たさない)
        #   かつ実摂動 0.055 Å の 1/10 (現状は余裕で満たす) — 両閾の間のデッドゾーンを作らない。
        assert abs(d_a - d_none) > 5.0e-3, (
            f"bond restraint がベースラインと同一 (d={d_a:.6f}) = 完全不動 — Bond が "
            "ChemComp のように no-op 化した可能性。engine docstring の『小摂動』記述を再検証せよ"
        )

    def test_canary_zero_weight_matches_no_restraint(self) -> None:
        """対照: weight=0 でベースライン (拘束なし) へ復帰 (摂動が拘束由来であることの確認)。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp0:
            rwp0, d_none, _ = self._run(tmp0, None)
        with tempfile.TemporaryDirectory() as tmpz:
            rwp_z, d_zero, _ = self._run(tmpz, 2.3, weight=0.0)
        # weight=0 は拘束なしと物理的に等価。同一マシンでは決定論だが、cross-machine の
        # 総和順差にも耐えるよう物理スケールの許容で照合する (< 摂動サイズ 0.055 Å の 1/100)。
        assert d_zero == pytest.approx(d_none, abs=5.0e-4)
        assert rwp_z == pytest.approx(rwp0, abs=1.0e-3)
