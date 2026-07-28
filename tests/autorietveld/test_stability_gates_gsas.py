"""WS-1 診断ゲートの**実 GSAS への配線** (判断ロジックは test_stability_gates.py)。

純関数のテストが green でも、それが `run_auto_rietveld` の段階ループから呼ばれていなければ
機能は存在しない。ここで固定するのは 3 点:

1. 未収束判定が **revert 経路まで届く** (REQ-SAR-101)
2. esd プルーニングが **GSAS の Frozen リストに実際に載る** (REQ-SAR-103) — ledger に書いた
   だけで varyList から外れていなければ「凍結したつもり」になる
3. 既定 (``stability=None``) は**共分散を 1 度も読まない** = 非回帰契約

T1 (fluoroapatite 単相ラボ X 線) を最短レシピで回す。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import RefinementStage, StabilityOptions
from tsumugin.store import Ledger

_DATA = Path("docs/benchmark/testdata/m7/labdata")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "FAP.XRA").exists() and (_DATA / "FAP.EXP").exists()


def _t1_inputs():
    hist = HistogramSpec(
        data_path=str(_DATA / "FAP.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )
    phase = PhaseSpec(
        structure_path=str(_DATA / "FAP.EXP"), phase_name="fap", format_hint="EXP"
    )
    # 最短レシピ (背景+スケール → 格子+変位 → Uiso)。ゲートの配線を測るのが目的で、
    # 到達 Rwp を測るのは bench_recipes.py の仕事。
    recipe = (
        RefinementStage(label="S0 background", flags={"background": {"coeffs": 6}}),
        RefinementStage(
            label="S1 cell+displacement", flags={"cell": True, "displacement": {0: ["Shift"]}}
        ),
        RefinementStage(label="S2 uiso", flags={"uiso": True}),
    )
    return [hist], [phase], recipe


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_unconverged_stage_is_reverted_and_recorded():
    """収束判定が段の受理条件に**実際に効いている** (REQ-SAR-101)。

    ``max_shift_esd=-1.0`` はどんな精密化でも満たせない閾値なので、GSAS が
    ``Max shft/sig`` を返す限り全段が未収束と判定される。`extra_cycles=0` で追加サイクルを
    封じているので、判定はそのまま revert に落ちなければならない。ゲートが繋がっていなければ
    段は普通に受理され、``m7_stage_unconverged`` は 1 件も出ない。
    """
    hists, phases, recipe = _t1_inputs()
    ledger = Ledger()

    result = run_auto_rietveld(
        hists, phases, recipe=recipe, ledger=ledger, max_cyc=3,
        stability=StabilityOptions(
            require_convergence=True, max_shift_esd=-1.0, extra_cycles=0
        ),
    )

    unconverged = [e for e in ledger.entries if e.kind == "m7_stage_unconverged"]
    assert unconverged, "収束判定が段階ループから呼ばれていない (ゲート未配線)"
    flagged = {str(e.payload["stage"]) for e in unconverged}
    for stage in result.stage_results:
        if stage.label in flagged:
            assert stage.reverted is True, f"未収束なのに受理された: {stage.label}"
            assert "unconverged" in stage.note
    assert ledger.verify() is True


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_pruned_variables_land_in_the_gsas_frozen_list(tmp_path):
    """esd プルーニングが GSAS の ``parmFrozen`` に**実際に載る** (REQ-SAR-103)。

    ledger に書くだけでは「凍結したつもり」になる。`GSASIIstrMain.Refine` は
    ``Controls['parmFrozen']['FrozenList']`` を見て varyList から外すので、保存した gpx を
    開き直して同じリストに入っていることを確認する。

    ``prune_exempt_tokens=()`` (除外なし) で回すのは、**座標シフト dAx/dAy/dAz が
    「esd >= |値|」の確実な発生源**だから — 精密化が進むほどシフトは 0 に近づき、esd との比が
    必ず 1 を超える。同時にこれは既定で除外している理由の実測でもある (T1 実測: 除外を切ると
    座標 5 個が凍る = 既定のままなら構造精密化が止まっていた)。

    高相関の記録 (REQ-SAR-104) も同じ run で確認する: T1 のプロファイル段は
    ``|r|≈0.95`` の ``U×V`` / ``V×W`` を出す — F2 が「分割してはならない」と言っている
    Caglioti 群そのもの。
    """
    from GSASII import GSASIIscriptable as G2sc

    hists, phases, _short = _t1_inputs()
    recipe = (
        RefinementStage(label="S0 background", flags={"background": {"coeffs": 6}}),
        RefinementStage(
            label="S1 cell+displacement", flags={"cell": True, "displacement": {0: ["Shift"]}}
        ),
        RefinementStage(label="S2 profile", flags={"profile": True}),
        RefinementStage(label="S3 coords+uiso", flags={"coords": True, "uiso": True}),
    )
    ledger = Ledger()
    out = tmp_path / "t1_pruned.gpx"

    run_auto_rietveld(
        hists, phases, recipe=recipe, ledger=ledger, max_cyc=8, keep_gpx=str(out),
        stability=StabilityOptions(
            prune_weak_vars=True,
            prune_exempt_tokens=(),
            detect_noop_stages=True,
            record_correlations=True,
        ),
    )

    prunes = [e for e in ledger.entries if e.kind == "m7_stage_prune"]
    assert prunes, "esd プルーニングが段階ループから呼ばれていない (ゲート未配線)"
    pruned = {str(v["name"]) for e in prunes for v in e.payload["variables"]}
    assert any(name.startswith("0::dA") for name in pruned), pruned
    frozen = set(G2sc.G2Project(gpxfile=str(out)).get_Frozen())
    assert pruned <= frozen, f"ledger にだけ書かれ GSAS に届いていない: {pruned - frozen}"
    # 凍結理由が台帳から読めること (「なぜ母数が減ったか」が後から追えない台帳は無価値)。
    assert all("esd" in str(e.payload.get("reason", "")) for e in prunes)

    corrs = [e for e in ledger.entries if e.kind == "m7_stage_correlation"]
    assert corrs, "高相関の記録が段階ループから呼ばれていない (ゲート未配線)"
    detected = {
        frozenset((str(p["a"]), str(p["b"])))
        for e in corrs
        for p in e.payload["pairs"]
    }
    assert frozenset((":0:V", ":0:W")) in detected, detected
    assert ledger.verify() is True


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_default_run_emits_no_stability_entries(monkeypatch):
    """既定 (``stability=None``) は診断層を**一切呼ばない** — 非回帰契約の本体。

    `read_diagnostics` を爆発させておくことで、「既定でも共分散を読んでいる」実装ミスを
    検出する (読むだけなら Rwp は変わらないので、Rwp の比較では捕まらない)。
    """
    import tsumugin.autorietveld.engine as engine_mod

    def _boom(*args, **kwargs):  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("既定経路で read_diagnostics が呼ばれた (非回帰契約違反)")

    monkeypatch.setattr(engine_mod, "read_diagnostics", _boom)

    hists, phases, recipe = _t1_inputs()
    ledger = Ledger()
    result = run_auto_rietveld(hists, phases, recipe=recipe, ledger=ledger, max_cyc=3)

    kinds = {e.kind for e in ledger.entries}
    assert kinds <= {"m7_stage", "m7_stage_error"}, kinds
    assert all(
        "unconverged" not in s.note and "noop" not in s.note for s in result.stage_results
    )
