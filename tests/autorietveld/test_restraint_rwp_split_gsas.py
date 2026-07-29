"""実 GSAS で **penalty を除いた Rwp** が段の判定を正しくすること (REQ-SAR-203, @pytest.mark.gsas)。

WS-2 は `enable_restraints` で拘束が本当に χ² に入ることを実測確定したが、副産物として
``Rvals['Rwp']`` が penalty 込みになり、段の受理/revert (Rwp 比較) の意味が変わった
(実測: bond weight 1e5 で Rwp 3558 → **全段 revert**)。ここでは実データで:

* penalty 込みの Rwp と**データ項の Rwp** が実際に桁で違うこと (分離が仕事をしている)
* 分離前の判定基準 (penalty 込み) なら**revert される**段が、データ項では受理されること
* データ項 Rwp が**拘束なしの run と同じ土俵の値**であること (出版値として比較できる)

を固定する。拘束なしの run と拘束ありの run を同一レシピで並べるのが唯一の検証法である。
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import RefinementStage, StabilityOptions
from tsumugin.store import Ledger

_DATA = Path("docs/benchmark/testdata")

pytestmark = pytest.mark.gsas

#: 拘束を χ² に入れる設定 (report_undetermined は REQ-SAR-203 の必須前提)。
_ON = StabilityOptions(enable_restraints=True, report_undetermined=True)

#: **データ項を桁で上回る penalty** を作る重み。分離しなければ全段 revert する領域
#: (WS-2 実測の bond weight 1e5 と同じ狙い)。
_HEAVY_WEIGHT = 1.0e5

#: S–O 距離のターゲット。実測値 (~1.41 Å) から**わざと外して**penalty を確実に立てる。
#: ラベルは `PbSO4-Wyckoff.cif` の実際の原子行 (Pb/S/O1/O2/O3) — 存在しないラベルを 1 つでも
#: 混ぜると `addDistRestraint` が失敗して spec ごとスキップされ、**拘束ゼロで green になる**。
_BOND = {"origin": ("S",), "target": ("O1", "O2", "O3"), "distance": 2.3,
         "esd": 0.02, "factor": 2.0, "weight": _HEAVY_WEIGHT}


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


def _phase() -> PhaseSpec:
    return PhaseSpec(
        structure_path=str(_DATA / "PbSO4-Wyckoff.cif"), phase_name="pbso4", format_hint="CIF"
    )


#: 拘束が意味を持つところまで解放する最小のレシピ (構造段まで届かせる)。
_RECIPE = (
    RefinementStage(label="S1 scale+bg", flags={"scale": True, "background": {"coeffs": 6}}),
    RefinementStage(label="S2 cell", flags={"cell": True}),
    RefinementStage(label="S3 coords", flags={"atoms": "XU"}),
)


def _run(stability, ledger=None):
    with tempfile.TemporaryDirectory():
        return run_auto_rietveld(
            [_hist()], [_phase()],
            recipe=_RECIPE,
            max_cyc=8,
            stability=stability,
            ledger=ledger,
            bond_restraints={"pbso4": [_BOND]} if stability is not None else None,
        )


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
def test_penalty_is_separated_and_stages_are_judged_on_the_data_term():
    """★本命: penalty 込みの Rwp では revert される段が、データ項では受理される。"""
    ledger = Ledger()
    on = _run(_ON, ledger)

    # (1) 分離が実際に起きている — penalty 込みの値が別キーに現れる。
    penalized = [s.rwp_penalized for s in on.stage_results]
    assert any(p is not None for p in penalized), (
        "penalty が χ² に入っていない (dlg スタブ経路が壊れた?) — 分離すべきものが無い"
    )

    # (2) penalty はデータ項を**桁で**上回っている = 分離しなければ判定が penalty に支配される。
    last = on.stage_results[-1]
    assert last.rwp_penalized is not None
    assert last.rwp_penalized > 10.0 * last.rwp, (
        f"penalty が小さすぎてこのテストは何も見ていない: "
        f"data={last.rwp} penalized={last.rwp_penalized}"
    )

    # (3) 分離前の基準 (penalty 込み) なら **悪化 = revert** と判定されたはずの段が、
    #     データ項では改善しており受理されている。
    accepted = [s for s in on.stage_results if not s.reverted]
    assert len(accepted) >= 2, f"段が受理されていない: {[s.note for s in on.stage_results]}"
    assert on.final_rwp < on.stage_results[0].rwp, (
        f"データ項で見ても改善していない: {[s.rwp for s in on.stage_results]}"
    )

    # (4) 台帳に分離の材料が残る (「Rwp が下がったのは拘束を緩めたからでは?」の検算経路)。
    splits = [e for e in ledger.entries if e.kind == "m7_stage_restraint_split"]
    assert splits, "m7_stage_restraint_split が 1 件も無い"
    payload = splits[-1].payload
    assert payload["rwp_penalized"] > payload["rwp_data"] > 0.0
    assert payload["restraint_sum"] > 0.0


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
def test_the_data_term_rwp_is_comparable_with_an_unrestrained_run():
    """データ項 Rwp は**拘束なしの run と同じ土俵**の値である (= 出版値として比較できる)。

    拘束はモデルを引くので値は一致しないが、``final_rwp`` が penalty 込みのままなら
    桁で外れる (実測 3558 vs 6.7)。「同じ量として比べられる」ことを緩い上界で固定する。
    """
    off = _run(None)
    on = _run(_ON)

    assert math.isfinite(off.final_rwp) and math.isfinite(on.final_rwp)
    # 拘束は適合を悪くしうるが、**同じ量**である以上せいぜい数倍の範囲に収まる。
    assert on.final_rwp < 5.0 * off.final_rwp, (
        f"データ項 Rwp が拘束なしと桁違い (分離が効いていない?): "
        f"off={off.final_rwp} on={on.final_rwp} penalized={on.final_rwp_penalized}"
    )
    # 拘束なしの run は penalty を持たない = 生値も分離値も存在しない。
    assert off.final_rwp_penalized is None and off.final_restraint_penalty == 0.0
    assert all(s.rwp_penalized is None for s in off.stage_results)


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
def test_gof_is_deliberately_left_penalty_inclusive_as_an_alarm():
    """**GOF は分離しない**という設計判断を固定する (分け忘れとの区別)。

    拘束付き精密化の GOF は拘束項を観測と自由度の双方に数えるのが慣行で、GSAS の式
    (``√(χ²/(Nobs + RestraintTerms − Nvars))``) はそのとおり書かれている。加えて penalty 込みの
    まま残すと**拘束がデータと争っている状態が値に現れる** — データ項 Rwp だけでは見えない警報。
    ここでは「Rwp は穏やかなのに GOF が跳ねる」ことを実測で固定する。
    """
    on = _run(_ON)

    assert on.final_rwp < 100.0, f"データ項 Rwp が分離されていない: {on.final_rwp}"
    assert on.final_gof > 100.0, (
        f"GOF が penalty 込みでない (警報が消えた): rwp={on.final_rwp} gof={on.final_gof}"
    )


@pytest.mark.skipif(not _data_present(), reason="PbSO4 データ未取得")
def test_default_path_reports_no_penalty_fields_and_no_split_ledger_entries():
    """**非回帰契約**: 既定 (拘束無効) では penalty 由来の値も台帳も 1 つも増えない。"""
    ledger = Ledger()
    off = _run(None, ledger)

    assert off.final_rwp_penalized is None
    assert off.final_restraint_penalty == 0.0
    assert not [e for e in ledger.entries if e.kind == "m7_stage_restraint_split"]
