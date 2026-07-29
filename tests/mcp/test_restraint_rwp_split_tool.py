"""② / ③ 到達可能性 — restraint penalty を除いた **データ項 Rwp** が呼び手に届くこと。

**なぜガードが要るか** (CLAUDE.md ★不変条件): ① で分離しても ② に出さなければ ③ にとって
その分離は存在しない。しかも今回は**同じ名前の値が 2 つある** (データ項 / penalty 込み) ので、
③ が取り違えると「拘束を強めたら Rwp が悪化した」という**誤った結論**を出版経路へ流す。
出す/読ませるところまでを恒久ガードにする。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.mcp.rietveld_tools import auto_rietveld

_SKILL = Path("plugins/tsumugin/skills/analyze/SKILL.md")

_H = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
).to_dict()
_P = PhaseSpec(structure_path="a.cif", phase_name="ph").to_dict()

#: ③ が読むべき分離キー (② の出力 / ③ の手順書の**両方**に現れること)。
_SPLIT_KEYS = ("final_rwp_penalized", "final_restraint_penalty")


def _runner_with_restraints(_inp) -> AutoRietveldResult:
    """拘束を χ² に入れた精密化の結果を模す (データ項 20% / penalty 込み 30%)。"""
    return AutoRietveldResult(
        stage_results=(
            StageResult(
                label="S1", rwp=20.0, gof=1.0, n_params=5, converged=True, rwp_penalized=30.0
            ),
        ),
        final_rwp=20.0,
        final_gof=1.0,
        refined_cells={},
        validity=ValidityReport(passed=True),
        final_rwp_penalized=30.0,
        final_restraint_penalty=500.0,
    )


def _runner_without_restraints(_inp) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="S1", rwp=9.8, gof=1.0, n_params=5, converged=True),),
        final_rwp=9.8,
        final_gof=1.0,
        refined_cells={},
        validity=ValidityReport(passed=True),
    )


def test_tool_reports_the_data_term_as_final_rwp():
    # 【目的】: `final_rwp` は**データ項**。penalty 込みの値をここへ載せてはならない
    #   (出版される数値の意味をオプションで切り替えない)。
    out = auto_rietveld([_H], [_P], runner=_runner_with_restraints)

    assert out["final_rwp"] == pytest.approx(20.0)
    assert out["final_rwp_penalized"] == pytest.approx(30.0)
    assert out["final_restraint_penalty"] == pytest.approx(500.0)
    assert out["stages"][0]["rwp"] == pytest.approx(20.0)
    assert out["stages"][0]["rwp_penalized"] == pytest.approx(30.0)


def test_tool_reports_null_penalized_value_when_no_restraints_were_applied():
    # 【目的】: 拘束なしのとき penalty 込みの値は**存在しない**。0.0 を捏造すると
    #   「penalty ゼロで拘束が効いた」と読めてしまう (esd の 0.0 捏造禁止と同じ規律)。
    out = auto_rietveld([_H], [_P], runner=_runner_without_restraints)

    assert out["final_rwp"] == pytest.approx(9.8)
    assert out["final_rwp_penalized"] is None
    assert out["stages"][0]["rwp_penalized"] is None
    # キー自体は常に存在する (欠落と null を ③ が取り違えないため)。
    assert "final_rwp_penalized" in out and "rwp_penalized" in out["stages"][0]


def test_skill_tells_the_agent_which_rwp_to_read():
    # 【目的】: ③ は JSON しか見ない。手順書にキー名が無ければ、そのキーは無いのと同じ。
    text = _SKILL.read_text(encoding="utf-8")
    for key in _SPLIT_KEYS:
        assert key in text, f"analyze skill が {key} に言及していない (③ から読み手が存在しない)"


def test_skill_does_not_keep_the_stale_instruction_to_read_a_penalized_rwp():
    """**古い指示が残っていないこと** — 誤った指示は実装バグと同等に有害。

    分離前の skill は「有効化すると Rwp が penalty を含む値に変わる」「重みが過大だと全段が
    revert される」と書いていた。分離後はどちらも**偽**であり、そのまま残すと ③ は
    `final_rwp` を penalty 込みだと思い込んで拘束ありの run を出版値から外してしまう。
    """
    text = _SKILL.read_text(encoding="utf-8")
    assert "Rwp が penalty を含む値に変わる" not in text
    assert "データ項のみの Rwp" in text


def test_skill_keys_all_exist_in_the_tool_output():
    """手順書が名指しするキーが ② の出力に**実在**すること (§4.5 到達可能性)。"""
    text = _SKILL.read_text(encoding="utf-8")
    out = auto_rietveld([_H], [_P], runner=_runner_with_restraints)
    stage_keys = set(out["stages"][0])
    for key in _SPLIT_KEYS:
        assert key in text and key in out
    for key in ("rwp", "rwp_penalized"):
        assert f"stages[*].{key}" in text, f"skill が stages[*].{key} を案内していない"
        assert key in stage_keys, f"② の stages 要素に {key} が無い"
