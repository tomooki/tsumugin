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
from tsumugin.autorietveld.model import AutoRietveldResult, RefinementStage, StabilityOptions
from tsumugin.operando.coulometry import coulometric_fractions
from tsumugin.store import Ledger

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
                                  生 Rwp 40.349063 / 40.349063 (ビット同一)
                                  RestraintSum 3.11e9 / 3.69e9 (下がらない = 最小化されていない)
        stability(enable_restraints=True) / ターゲット 2.3:
                                  生 Rwp 3876.32 vs データ項 40.34906 (= 既定と一致)
                                  RestraintSum 3.687e9 → **試行中に 0.0845** (10 桁の低下)
                                  → データ項が 40.349 → 41.447 に**悪化したので段は revert**

    ⚠ **「拘束が効く」と「その結果が採用される」は別物である。** カナリアはターゲットを
    わざと誤らせている (真値 ~1.47 Å) ので、拘束は**データが支持する位置から遠ざける**方向へ
    引く。段の受理はデータ項 Rwp で判定する (REQ-SAR-205: 段 N と N+1 は同じ拘束下にあり
    apples-to-apples なので、これで何も問題ない) ため、**拘束が正しく効いているほど段は
    revert される**。したがって効き目の観測は**最終構造ではなく試行の中**で行う —
    ledger ``m7_stage_restraint_split`` の ``trial_*`` が revert 後も残る観測窓である。

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

    def _run_full(
        self,
        tmp: str,
        target: float | None,
        *,
        weight: float = 1.0e5,
        stability: StabilityOptions | None = None,
    ) -> "tuple[AutoRietveldResult, Ledger, str]":
        """1 回走らせて (結果, 台帳, 保存 gpx) を返す。**台帳が試行の観測窓**である。"""
        import os

        keep = os.path.join(tmp, f"o_{target}_{weight}_{stability is not None}.gpx")
        br = None if target is None else self._bond_spec(target, weight)
        ledger = Ledger()
        r = run_auto_rietveld(
            [_hist()],
            [_phase(free_occupancy_labels=())],
            recipe=_stages(_SB, ("xyz", {"coords": True})),
            max_cyc=10,
            bond_restraints=br,
            keep_gpx=keep,
            stability=stability,
            ledger=ledger,
        )
        return r, ledger, keep

    def _run(
        self,
        tmp: str,
        target: float | None,
        *,
        weight: float = 1.0e5,
        stability: StabilityOptions | None = None,
    ) -> tuple[float, float, str]:
        r, _ledger, keep = self._run_full(tmp, target, weight=weight, stability=stability)
        return r.final_rwp, _so2_distance(keep), keep

    @staticmethod
    def _splits(ledger: Ledger) -> dict[str, dict]:
        """段ラベル → ``m7_stage_restraint_split`` の payload。

        このエントリだけが**段が revert された後も試行の値を保持している** (``trial_*``)。
        既定経路 (拘束を χ² に入れない) では 1 件も出ない。
        """
        return {
            str(e.payload["stage"]): dict(e.payload)
            for e in ledger.entries
            if e.kind == "m7_stage_restraint_split"
        }

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

        **両方向を pin する** (commit 1c1a19e/cabfda9 の意図。書き直しで ③ が失われていた):
        ①②だけでは「Bond が ChemComp と同様に**完全不動化**した」退化を検出できない — その場合も
        ①②は自明に通り、カナリアは黙って green のままになる (落ちないガードは無いより悪い)。
        現状の Bond は非ゲートの `HessRefine` 経由で**小さな飽和摂動**を注入している
        (`_apply_bond_restraints` の docstring がそう主張している) ので、③で
        **拘束ありがベースライン (拘束なし) と異なる**ことも同時に固定する。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _rwp0, d_none, _ = self._run(tmp, None)
            rwp_a, d_a, _ = self._run(tmp, 1.9)
            rwp_b, d_b, _ = self._run(tmp, 2.3)

        # ①ターゲット非追従: 0.4 Å 離れたターゲットで最終距離が実質同一 (機能拘束では不可能)
        assert abs(d_a - d_b) < 1.0e-6, (
            f"既定経路で bond restraint がターゲットに追従した (1.9→{d_a:.4f}, 2.3→{d_b:.4f}) — "
            "GSAS-II が headless restraint を修復した可能性。非機能 caveat を再検証せよ"
        )
        assert rwp_a == pytest.approx(rwp_b, abs=1.0e-6), "Rwp も penalty を含んでいない"
        # ②データ値近傍に留まりターゲット (>=1.9) へ到達しない
        assert d_a < 1.55, f"S–O2={d_a:.4f} が想定外にターゲット側へ動いた"
        # ③拘束ありは拘束なしと異なる (非ゲート HessRefine 経由の小摂動が残っていること)。
        #   完全不動化 (ChemComp 化) したらここが fail し docstring の「小摂動」記述を再検証させる。
        #   閾 5e-3 は weight=0 対照の cross-machine ノイズ上限 5e-4 の 10 倍 (ノイズで満たさない)
        #   かつ実摂動 0.055 Å の 1/10 (現状は余裕で満たす) — 両閾の間のデッドゾーンを作らない。
        assert abs(d_a - d_none) > 5.0e-3, (
            f"bond restraint がベースラインと同一 (d={d_a:.6f}) = 完全不動 — Bond が "
            "ChemComp のように no-op 化した可能性。engine docstring の『小摂動』記述を再検証せよ"
        )

    def test_restraint_enters_chi_squared_with_the_dlg_stub(self) -> None:
        """★カナリア②: `enable_restraints=True` で penalty が**実際に χ² に入る** (REQ-SAR-204)。

        **観測点は「最終構造」ではなく「試行の中」である。** カナリアは S–O ターゲットを
        わざと 2.3 Å (真値 ~1.47 Å) に誤らせている = 拘束は**データが支持する位置から遠ざける
        方向**へ引く。したがって拘束が正しく効いているほど段のデータ項 Rwp は悪化し、
        **段は revert されるのが正しい** (実測 40.349 → 試行 41.447 で revert)。
        「拘束が効くこと」と「その結果が採用されること」は別の話なので、最終 gpx を見る
        カナリアは*正しい判定*を故障として報告してしまう (2026-07-29 の赤の原因)。

        観測窓は ledger ``m7_stage_restraint_split`` の ``trial_*`` (revert されても残る)。
        3 つの独立な数値で固定する:

        1. **生 Rwp が penalty を含む値に変わる** — ``Rw = √(ΣM²/SumwYo)`` で M に penalty が
           連結されるのは `errRefine`:5203 の ``dlg`` ゲート内だけ。同一データ・同一拘束で
           既定 40.35 に対しスタブ経路の生 Rwp は 3876 (約 96 倍)。
        2. **データ項は既定経路の Rwp へ復元される** — 分離 (REQ-SAR-205) が効いている証拠で
           あり、1 の差が「penalty の分」であることの裏取りでもある。
        3. **penalty が試行中に最小化される** — 実測 3.687e9 → **0.0845** (10 桁)。目的関数に
           入っていなければ optimizer は penalty を下げる理由を持たない。**段が revert された
           かどうかとは無関係**に成り立つ、最も直接的な証拠。

        ★ fail したらスタブ契約 (`restraint_dlg`: Update の戻り値/型名の "G2"/SetHistogram)
        の破損か、GSAS-II 側のゲート仕様変更を疑うこと。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            rwp_off, _d_off, keep_off = self._run(tmp, 2.3)
            _r_on, ledger_on, _keep_on = self._run_full(tmp, 2.3, stability=self._ON)
            sum_off = self._restraint_sum(keep_off)

        splits = self._splits(ledger_on)
        assert set(splits) == {"sb", "xyz"}, (
            f"penalty 分離の記録が段ごとに出ていない ({sorted(splits)}) — "
            "拘束が有効化されていないか ledger の配線が壊れている"
        )
        base, coords = splits["sb"], splits["xyz"]

        # 前提: 誤ターゲットなので penalty は最初から巨大 (既定経路でも報告される値)。
        assert sum_off > 1.0e6, "対照側の penalty が最初から小さい (実験の前提が崩れている)"
        assert base["restraint_sum"] > 1.0e6, "スタブ側の初期 penalty が小さい (前提が崩れた)"
        # 1. penalty が残差ベクトル M に連結された (生 Rwp が桁で変わる)。
        assert base["rwp_penalized"] > 10.0 * rwp_off, (
            f"生 Rwp が penalty を含んでいない (既定 {rwp_off:.3f} / "
            f"スタブ {base['rwp_penalized']:.3f}) — dlg が Refine へ届いていない"
        )
        # 2. データ項は既定経路と一致する (分離が penalty を正しく割っている)。
        assert base["rwp_data"] == pytest.approx(rwp_off, abs=1.0e-6), (
            "データ項 Rwp が既定経路と一致しない — penalty の分離 (REQ-SAR-205) が壊れている"
        )
        # 3. 試行中に penalty が最小化された (段が revert されたかとは無関係な証拠)。
        assert coords["trial_restraint_sum"] < base["restraint_sum"] / 1.0e3, (
            f"RestraintSum が試行中に最小化されていない "
            f"({base['restraint_sum']:.3g} → {coords['trial_restraint_sum']:.3g}) — "
            "dlg スタブが Refine へ届いていないか、契約が壊れている"
        )

    def test_restraint_target_is_tracked_only_with_the_stub(self) -> None:
        """★カナリア③: スタブ経路では**ターゲットの違いが試行の結果に出る** (①の裏返し)。

        ①は既定経路で 1.9 と 2.3 の結果が**ビット同一**であることを固定する。同じ 2 つの
        ターゲットでスタブ経路を走らせると、**段の試行が到達したデータ項 Rwp** が桁で変わる
        (実測 1.9 → 3558.77 / 2.3 → 41.45)。拘束が目的関数の外にあれば座標の動きはターゲットに
        依存しない = この差は生まれない。

        **最終 S–O2 距離ではなく試行の Rwp を見る理由**: どちらのターゲットも誤り (真値
        ~1.47 Å) なので、拘束が効くほど段はデータ項で悪化し **両方 revert される** →
        最終構造は両方とも同じ (拘束を掛ける前の) 値に戻る。最終値の比較は
        「拘束が効いていない」と「効いた結果が正しく捨てられた」を区別できない。

        ★ fail したら ①②と併せてスタブ契約 (`restraint_dlg`) の破損を疑うこと。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _r_a, ledger_a, _ = self._run_full(tmp, 1.9, stability=self._ON)
            _r_b, ledger_b, _ = self._run_full(tmp, 2.3, stability=self._ON)

        splits_a, splits_b = self._splits(ledger_a), self._splits(ledger_b)
        assert "xyz" in splits_a and "xyz" in splits_b, (
            f"座標段の penalty 分離が記録されていない ({sorted(splits_a)} / {sorted(splits_b)}) "
            "— 拘束が χ² に入っていない (dlg スタブが Refine へ届いていない)"
        )
        rwp_a, rwp_b = splits_a["xyz"]["trial_rwp_data"], splits_b["xyz"]["trial_rwp_data"]
        assert rwp_a is not None and rwp_b is not None, (
            "試行のデータ項 Rwp が非有限 (段の精密化自体が失敗している) — "
            "拘束の効き目以前の問題なので先にそちらを調べること"
        )
        # 閾 1.0 (Rwp 点) は実測差 3517 点の 1/3500 かつ、同一設定の再実行揺らぎ
        # (既定経路の 1.9/2.3 はビット同一 = 0) を大きく上回る — デッドゾーンを作らない。
        assert abs(rwp_a - rwp_b) > 1.0, (
            f"スタブ経路でも試行の結果がターゲット非依存 (1.9→{rwp_a:.4f}, 2.3→{rwp_b:.4f}) — "
            "拘束が χ² に入っていない。restraint_dlg の契約を再検証せよ"
        )

    def test_final_penalty_and_penalized_rwp_describe_the_same_state(self) -> None:
        """★`final_*` の 3 つ組は**同じ状態**を指す (捨てた試行の値を混ぜない)。

        `final_rwp` (データ項) / `final_rwp_penalized` (生) / `final_restraint_penalty` は
        「出版される fit を説明する数字」の組である。段が revert された run で penalty だけ
        試行値だと ``final_rwp_penalized`` は penalty 込み (3876) なのに
        ``final_restraint_penalty`` は最小化後の 0.08 という、**存在しない状態**を報告する。

        揃える先は **revert 後 = 実際に採用された状態**である (出版値は採用された fit のもの
        だから)。捨てた試行の penalty は ledger の ``trial_restraint_sum`` に段ごとに残るので、
        情報は失われない — 報告を混ぜるのではなく層を分ける。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            r, ledger, _keep = self._run_full(tmp, 2.3, stability=self._ON)

        splits = self._splits(ledger)
        assert "xyz" in splits, (
            f"座標段の penalty 分離が記録されていない ({sorted(splits)}) — 拘束が χ² に "
            "入っていないので、状態の整合以前に有効化そのものを疑うこと (カナリア②③ を先に見る)"
        )
        coords = splits["xyz"]
        assert coords["reverted"] is True, (
            "誤ターゲット 2.3 Å の座標段が revert されなかった — 本テストの前提 "
            "(採用状態と試行が食い違う状況) が成立していない"
        )
        # 採用状態: ledger の無印キー (revert 後) と最終報告が一致する。
        assert r.final_rwp == pytest.approx(coords["rwp_data"], abs=1.0e-9)
        assert r.final_rwp_penalized == pytest.approx(coords["rwp_penalized"], abs=1.0e-9)
        # penalty は最終 gpx から独立に読んだ値 — 台帳側の追跡と一致すること。
        assert r.final_restraint_penalty == pytest.approx(coords["restraint_sum"], rel=1.0e-9)
        # ★回帰の実体: 捨てた試行 (最小化された penalty) を報告していないこと。
        assert r.final_restraint_penalty > 1.0e3 * coords["trial_restraint_sum"], (
            f"final_restraint_penalty が捨てた試行の値 "
            f"({coords['trial_restraint_sum']:.3g}) を指している — "
            "final_rwp_penalized (採用状態) と別の状態を混ぜている"
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
