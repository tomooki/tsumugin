"""TASK-0805: 実構造 (T1) 規則ループ回帰 — 背景増項を規則で自律化 (gsas)。

M7 教訓「背景項数不足で Rwp 平坦」を RuleBasedPolicy + 既定 GSAS runner/粗診断で自動化する。
背景係数を過少 (3) から開始し、ループが自律的に増項して Rwp を改善することを検証する。
ModelAction (リミット/相追加/構造改訂) は open_proposals に申し送られる (③ へ)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.refine_loop import PolicyBudget, run_refinement_loop
from tsumugin.store.ledger import Ledger

pytestmark = pytest.mark.gsas

_DATA = Path("docs/benchmark/testdata/m7/labdata")


@pytest.mark.skipif(not (_DATA / "FAP.XRA").exists(), reason="M7 T1 データ未取得")
def test_t1_rule_loop_auto_increases_background():
    h = HistogramSpec(
        data_path=str(_DATA / "FAP.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    p = PhaseSpec(structure_path=str(_DATA / "FAP.EXP"), phase_name="fap", format_hint="EXP")
    ledger = Ledger()
    # 過少背景 (3) から開始 → 規則ループが増項して改善する
    res = run_refinement_loop(
        [h],
        [p],
        background_coeffs=3,
        budget=PolicyBudget(max_iterations=3, target_rwp=None),
        ledger=ledger,
    )

    # 自律増項でチュートリアル級 (Rwp <= 12%) に到達
    assert res.best.final_rwp <= 12.0, f"Rwp={res.best.final_rwp}"
    assert res.best.validity.passed
    # 少なくとも 1 手が受理された (背景増項が効いた)
    assert any(s.accepted for s in res.steps), [s.result_rwp for s in res.steps]
    # 非破壊台帳は整合
    assert ledger.verify()
    # Issue #16: engine が実観測点数を通す (BIC 厳密化)
    assert res.best.n_obs > 0
