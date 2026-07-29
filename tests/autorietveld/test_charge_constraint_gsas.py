"""FR-318 T7/T8/T10/T12 の GSAS 統合テスト (PbSO4 実データ, @pytest.mark.gsas)。

- T7: atom_occupancy/atom_uiso/atom_multiplicity のラベルキー配線 + occupancy esd の 4 状態
- T8: initial_occupancies シーダー (占有率グループ非宣言なら値は凍結されたまま)
- T10: ChemComp restraint 直接注入 (占有率が目標へ引かれる / 無拘束コントロールとの比較)
- T12: lock_fractions 相間 EqnConstr (相分率がクーロメトリー解へ拘束される)
- Issue #112 / REQ-SAR-203/204: restraint が χ² に入るかの **dlg スタブ有無の対照**カナリア
  (既定は今も非機能 / `enable_restraints=True` では実際に効く — 両方向を固定)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import RefinementStage, StabilityOptions
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
    """Issue #112 / REQ-SAR-203/204: restraint が χ² に入るかを **dlg スタブの有無で対照**する。

    **背景**: `GSASIIstrMath.errRefine` は penalty 残差を ``if len(pVals) and dlg:`` (L5203) で
    ゲートし、``dlg=None`` (= `G2Project.refine` の既定) では penalty を χ² から除外する。
    `penaltyFxn`/`penaltyDeriv` は Bond/Angle/ChemComp を共有処理するため全 restraint 種が
    同じゲート下にある。一方 `dervRefine`/`HessRefine` は非ゲートなので、既定経路は
    **目的関数だけが拘束を見ない**不整合な最適化になる。

    **2026-07-29 の対照実験 (PbSO4, S–O 距離ターゲット 1.9 / 2.3 Å, weight 1e5)**::

        既定 (dlg なし)         : 1.9 → S–O2 1.411132 / 2.3 → S–O2 1.411132  (ビット同一)
                                  RestraintSum 4.66e9 / 3.69e9 (下がらない = 最小化されていない)
        stability(enable_restraints=True):
                                  1.9 → S–O2 1.411132 / 2.3 → S–O2 1.542264  (ターゲット依存)
                                  RestraintSum 3.69e9 → 0.0876 (10 桁の低下 = 最小化されている)

    よって本クラスは **2 つの向きを同時に固定**する:

    1. **既定経路は今も非機能** — 上流が直ったら気付けるようピン留めする (旧カナリアの役割)
    2. **スタブ経路では実際に効く** — 有効化が壊れたら気付けるようピン留めする (REQ-SAR-204)

    ★ 1 が fail したら朗報 (GSAS-II が修復された)。`_apply_bond_restraints` /
    `_apply_chem_comp_restraints` の非機能 caveat と `insitu.charge` の soft→diagnose 縮退を
    再検証すること。★ 2 が fail したらスタブ契約 (`restraint_dlg`) の破損を疑うこと。
    """

    #: 拘束を有効化する設定。REQ-SAR-203 により esd プルーニングとセットでしか有効にできない。
    _ON = StabilityOptions(enable_restraints=True, report_undetermined=True)

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

    def _run(
        self,
        tmp: str,
        target: float | None,
        *,
        weight: float = 1.0e5,
        stability: StabilityOptions | None = None,
    ) -> tuple[float, float, str]:
        import os

        keep = os.path.join(tmp, f"o_{target}_{weight}_{stability is not None}.gpx")
        br = None if target is None else self._bond_spec(target, weight)
        r = run_auto_rietveld(
            [_hist()],
            [_phase(free_occupancy_labels=())],
            recipe=_stages(_SB, ("xyz", {"coords": True})),
            max_cyc=10,
            bond_restraints=br,
            keep_gpx=keep,
            stability=stability,
        )
        return r.final_rwp, _so2_distance(keep), keep

    @staticmethod
    def _restraint_sum(gpx_path: str) -> float:
        """``Rvals['RestraintSum']`` = penalty の二乗和 (最小化されているかの直接指標)。"""
        from GSASII import GSASIIscriptable as G2sc

        from tsumugin.autorietveld.diagnostics import read_diagnostics

        return read_diagnostics(G2sc.G2Project(gpx_path)).restraint_sum

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

    def test_canary_default_path_still_does_not_track_target(self) -> None:
        """★カナリア①: **既定 (dlg なし)** では距離ターゲット 1.9 vs 2.3 で結果がビット同一。

        機能する距離拘束はターゲット非依存 (target-invariant) になり得ないので、これは
        「penalty が最小二乗目的関数に入っていない」ことの決定的証拠である。

        ★ **fail したら朗報** — GSAS-II 更新で headless restraint が修復された可能性が高い。
        engine の非機能 caveat・`insitu.charge` の soft→diagnose 縮退・本ファイルの
        `TestChemCompRestraint` を実態に合わせて再検証すること。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            rwp_a, d_a, _ = self._run(tmp, 1.9)
            rwp_b, d_b, _ = self._run(tmp, 2.3)

        assert abs(d_a - d_b) < 1.0e-6, (
            f"既定経路で bond restraint がターゲットに追従した (1.9→{d_a:.4f}, 2.3→{d_b:.4f}) — "
            "GSAS-II が headless restraint を修復した可能性。非機能 caveat を再検証せよ"
        )
        assert rwp_a == pytest.approx(rwp_b, abs=1.0e-6), "Rwp も penalty を含んでいない"
        assert d_a < 1.55, f"S–O2={d_a:.4f} が想定外にターゲット側へ動いた"

    def test_restraint_enters_chi_squared_with_the_dlg_stub(self) -> None:
        """★カナリア②: `enable_restraints=True` で penalty が**実際に χ² に入る** (REQ-SAR-204)。

        判定は 2 つの独立な数値で行う (片方だけだと解釈の余地が残る):

        1. **Rwp が penalty を含む値に変わる** — ``Rw = √(ΣM²/SumwYo)`` で、M に penalty が
           連結されるのは `errRefine`:5203 の ``dlg`` ゲート内だけ。同一データ・同一拘束で
           Rwp が桁で変われば、penalty が残差ベクトルに入った以外の説明が付かない。
        2. **RestraintSum が最小化される** — 実測 3.69e9 → 0.0876 (10 桁)。目的関数に入って
           いなければ optimizer は penalty を下げる理由を持たない。

        ★ fail したらスタブ契約 (`restraint_dlg`: Update の戻り値/型名の "G2"/SetHistogram)
        の破損か、GSAS-II 側のゲート仕様変更を疑うこと。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            rwp_off, _d_off, keep_off = self._run(tmp, 2.3)
            rwp_on, _d_on, keep_on = self._run(tmp, 2.3, stability=self._ON)
            sum_off = self._restraint_sum(keep_off)
            sum_on = self._restraint_sum(keep_on)

        assert sum_off > 1.0e6, "対照側の penalty が最初から小さい (実験の前提が崩れている)"
        assert sum_on < sum_off / 1.0e3, (
            f"RestraintSum が最小化されていない ({sum_off:.3g} → {sum_on:.3g}) — "
            "dlg スタブが Refine へ届いていないか、契約が壊れている"
        )
        assert rwp_on != rwp_off, "Rwp が penalty を含んでいない (M に連結されていない)"

    def test_restraint_target_is_tracked_only_with_the_stub(self) -> None:
        """★カナリア③: スタブ経路では**ターゲットの違いが結果に出る** (①の裏返し)。

        既定経路がビット同一 (①) なのに対し、スタブ経路では 1.9 と 2.3 で最終 S–O2 が
        変わる。実測 2026-07-29: 1.9 → 1.411132 (段が revert される), 2.3 → 1.542264。
        「拘束が効く」の最も直接的な表現なので、①と対にして両方向を固定する。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _rwp_a, d_a, _ = self._run(tmp, 1.9, stability=self._ON)
            _rwp_b, d_b, _ = self._run(tmp, 2.3, stability=self._ON)

        assert abs(d_a - d_b) > 1.0e-3, (
            f"スタブ経路でもターゲット非依存 (1.9→{d_a:.6f}, 2.3→{d_b:.6f}) — "
            "拘束が χ² に入っていない。restraint_dlg の契約を再検証せよ"
        )
        # より長いターゲットの方が S–O2 が長い (符号が正しい向きに効いている)。
        assert d_b > d_a

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
