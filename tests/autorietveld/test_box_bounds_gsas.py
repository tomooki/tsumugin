"""WS-2 箱拘束の**実 GSAS への配線** (純関数は test_bounds.py, @pytest.mark.gsas)。

純関数が green でも `run_auto_rietveld` の段階ループから呼ばれていなければ機能は存在しない。
ここで固定するのは 3 点:

1. 既定 (``stability=None``) は Controls を 1 度も触らない = **非回帰契約** (T1 の Rwp/格子が
   ビット同一)
2. 十分緩い箱は**結果を変えない** (張っただけで動くなら箱ではなく別のバグ)
3. 締めた箱は**実際に効き**、境界到達が ledger と note に**所見として出る** (REQ-SAR-202)

T1 (fluoroapatite 単相ラボ X 線, 既定レシピ 24 秒) を使う。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import StabilityOptions
from tsumugin.autorietveld.recipe import build_recipe
from tsumugin.store import Ledger

_DATA = Path("docs/benchmark/testdata/m7/labdata")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "FAP.XRA").exists() and (_DATA / "FAP.EXP").exists()


def _t1_inputs():
    hists = [
        HistogramSpec(
            data_path=str(_DATA / "FAP.XRA"),
            instrument_path=str(_DATA / "INST_XRY.PRM"),
            radiation=Radiation.XRAY_LAB,
            geometry=Geometry.BRAGG_BRENTANO,
            data_format="GSAS",
        )
    ]
    phases = [
        PhaseSpec(structure_path=str(_DATA / "FAP.EXP"), phase_name="fap", format_hint="EXP")
    ]
    return hists, phases, build_recipe(hists, phases)


def _run(stability):
    hists, phases, recipe = _t1_inputs()
    ledger = Ledger()
    result = run_auto_rietveld(
        hists, phases, recipe=recipe, ledger=ledger, max_cyc=12, stability=stability
    )
    return result, ledger


def _hits(ledger):
    return [
        (e.payload["stage"], h["variable"], h["side"])
        for e in ledger.entries
        if e.kind == "m7_stage_bound_hit"
        for h in e.payload["hits"]
    ]


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
class TestBoxBoundsWiring:
    def test_default_run_registers_no_bounds(self) -> None:
        """既定は Controls (parmMin/parmMax) を 1 度も触らない = 非回帰契約。

        `set_Controls('parmMin', …)` は**プロジェクトの保存を強制する**副作用を持つので、
        「張っていないつもりで張っている」と既定経路の I/O まで変わる。台帳に痕跡が 1 件も
        出ないことで固定する。
        """
        result, ledger = _run(None)
        kinds = {e.kind for e in ledger.entries}
        assert "m7_box_bounds" not in kinds
        assert "m7_stage_bound_hit" not in kinds
        assert result.final_rwp == pytest.approx(9.806, abs=0.05)

    def test_loose_bounds_do_not_change_the_result(self) -> None:
        """物理的に到達し得ないほど緩い箱は結果を**ビット同一**に保つ。

        これが崩れるなら、箱そのものではなく登録の副作用 (保存・index_ids 等) が精密化を
        動かしている = 別のバグ。非回帰の主張の土台なのでビット同一を要求する。
        """
        base, _ = _run(None)
        boxed, ledger = _run(
            StabilityOptions(
                bound_cell=0.2, bound_displacement=5000.0, bound_size_strain=True
            )
        )
        assert boxed.final_rwp == base.final_rwp
        assert boxed.refined_cells["fap"] == base.refined_cells["fap"]
        assert _hits(ledger) == [], "緩い箱で境界に当たるのは箱の作り方が間違っている"
        # 箱は「張られたが当たらなかった」— 登録自体は台帳に残る (何を拘束したかの記録)。
        registered = [e for e in ledger.entries if e.kind == "m7_box_bounds"]
        assert len(registered) == 1 and registered[0].payload["n_bounds"] > 0

    def test_registered_bounds_never_touch_structural_parameters(self) -> None:
        """★P-SAR-1 の実配線ガード: 台帳に載る箱に構造パラメータが 1 つも無いこと。

        GSAS の変数記法で占有率は ``Afrac``、Uiso は ``AUiso``、座標は ``dAx/dAy/dAz``。
        これらに箱が付いたら、NaCuHCF model5/model6 の判別 (占有率の発散が Ow 必要性の決め手)
        のような推論ができなくなる。**純関数側のガードだけでは配線ミスを捕まえられない**ので
        ここでも見る。
        """
        _r, ledger = _run(
            StabilityOptions(
                bound_cell=0.2, bound_displacement=5000.0, bound_size_strain=True
            )
        )
        names = [
            b["variable"]
            for e in ledger.entries
            if e.kind == "m7_box_bounds"
            for b in e.payload["bounds"]
        ]
        assert names, "箱が 1 つも登録されていない (テストが何も見ていない)"
        forbidden = ("Afrac", "AUiso", "dAx", "dAy", "dAz", "AU11", "AM")
        offenders = [n for n in names if any(tok in n for tok in forbidden)]
        assert offenders == [], f"構造パラメータに箱を張っている: {offenders} — P-SAR-1 違反"

    def test_tight_displacement_bound_is_hit_and_reported(self) -> None:
        """★REQ-SAR-202: 締めた箱に当たった事実が**握り潰されず**所見になる。

        T1 の試料変位は精密化で数百 µm 動く。1 µm の箱は必ず外れるので、GSAS が境界へ丸めて
        凍結し、engine がそれを検出して ledger (``m7_stage_bound_hit``) と
        ``StageResult.note`` に出さなければならない。実測 (2026-07-29): Rwp 9.81% → 11.19%
        = **拘束が実際に効いている**ことも同時に示す (効かない箱なら Rwp は変わらない)。
        """
        result, ledger = _run(StabilityOptions(bound_displacement=1.0))
        hits = _hits(ledger)
        assert hits, "境界に当たったのに所見が出ていない (握り潰し)"
        assert any(v.endswith(":Shift") for _s, v, _side in hits)
        # 丸められる前の値から「どちら側へ出たか」まで判る (推測していない)。
        assert {side for _s, _v, side in hits} <= {"min", "max"}
        assert any("bound_hits=" in s.note for s in result.stage_results)
        # 拘束が結果を実際に変えている (変位を封じたぶん Rwp は悪化するのが正しい挙動)。
        assert result.final_rwp > 10.0

    def test_bound_hits_are_not_confused_with_esd_pruning(self) -> None:
        """境界到達 (箱) と esd プルーニング (診断) は**同じ parmFrozen を共有する**。

        両方を同時に有効にしても、``m7_stage_bound_hit`` に載るのは箱を張った変数だけで
        なければならない (自分で凍らせた変数を「境界に当たった」と誤報しない)。
        """
        _r, ledger = _run(
            StabilityOptions(bound_displacement=1.0, prune_weak_vars_each_stage=True)
        )
        boxed_names = {
            b["variable"]
            for e in ledger.entries
            if e.kind == "m7_box_bounds"
            for b in e.payload["bounds"]
        }
        hit_names = {v for _s, v, _side in _hits(ledger)}
        assert hit_names, "この構成では境界到達が出るはず (テストが何も見ていない)"
        assert hit_names <= boxed_names
        pruned = {
            w["name"]
            for e in ledger.entries
            if e.kind == "m7_stage_prune"
            for w in e.payload["variables"]
        }
        assert hit_names.isdisjoint(pruned - boxed_names)
