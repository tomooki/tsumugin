"""★③ の手順書が「測定温度はヒストグラムに入れる」と言い、相の `temperature` を効く設定として指示しない恒久ガード。

`PhaseSpec.temperature` は**どの精密化エンジンも読まないメタデータ**である (docstring と
`test_recipe.py` / `topas/test_recipe.py` の `test_phase_temperature_is_not_read_*` が実証)。
ヒストグラム間の温度差の段 (静水圧歪み Dij) は `HistogramSpec.temperature` だけで決まる。

③ (LLM) は `auto_rietveld` の `specs` ハンドルで各相に `"temperature": null` を見るので、手順書が
温度の置き場所を言わなければ相の側を埋めて「温度差を入れたつもり」になる — 段は張られず、
エラーも出ない (呼べるが黙って効かない)。ここは「文書に書いてあること」を機械検査する。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_PLAYBOOKS = (
    Path("docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md"),
    Path("docs/tasks/m9-insitu-sequential/AGENT_PLAYBOOK.md"),
    Path("docs/tasks/operando-diagnosis/AGENT_PLAYBOOK.md"),
)

#: 相の temperature への言及 (`phases[].temperature` / `PhaseSpec.temperature` / 相の `temperature`)。
_PHASE_TEMPERATURE = re.compile(
    r"phases\[[^\]]*\]\.temperature|PhaseSpec\.temperature|相の\s*`?temperature\b"
)


def _offending_lines(name: str, text: str) -> list[str]:
    """相の temperature に触れているのに「読まない」を同じ行で言っていない行。"""
    return [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _PHASE_TEMPERATURE.search(line) and "読まない" not in line
    ]


def test_the_guard_pattern_catches_an_instruction_to_set_a_phase_temperature():
    """検出器の自己検査: 相に温度を入れさせる行は拾い、効かないと併記した行は通す。"""
    assert _offending_lines("x", "温度差があれば `phases[].temperature` に入れる")
    assert _offending_lines("x", "PhaseSpec.temperature を測定温度にする")
    assert _offending_lines("x", "相の `temperature` を 10 K にする")
    assert not _offending_lines("x", "相の `temperature` はどのエンジンも読まない")
    assert not _offending_lines("x", "各 `histograms[].temperature` に入れる")


@pytest.mark.parametrize(
    "path",
    [*sorted(_PLUGIN.rglob("*.md")), *_PLAYBOOKS],
    ids=lambda p: p.as_posix(),
)
def test_documents_never_present_a_phase_temperature_as_effective(path: Path):
    """skill/コマンド/PLAYBOOK が相の temperature に触れるなら、効かないことを同じ行で言う。"""
    bad = _offending_lines(path.as_posix(), path.read_text(encoding="utf-8"))
    assert not bad, "相の temperature を効く設定として読める指示がある:\n" + "\n".join(bad)


def test_mcp_tool_docstrings_never_present_a_phase_temperature_as_effective():
    """② のツール docstring も同じ規則 (③ が読む説明の一次情報)。"""
    bad: list[str] = []
    for name, fn in MCP_TOOLS.items():
        bad += _offending_lines(f"MCP_TOOLS[{name!r}]", getattr(fn, "__doc__", None) or "")
    assert not bad, "相の temperature を効く設定として読める docstring がある:\n" + "\n".join(bad)


@pytest.mark.parametrize("skill", ["analyze", "joint"])
def test_spec_building_skills_say_where_the_measurement_temperature_goes(skill: str):
    """`HistogramSpec`/`PhaseSpec` を組ませる skill は、温度の置き場所と相の側が効かないことを言う。

    `analyze` (手順 1 の入力組み立て) と `joint` (温度の違うヒストグラムを束ねる典型 —
    M7 T3 は X 線 295 K / 中性子 10 K) が対象。置き場所だけでなく「相の側は読まれない」まで
    書かないと、`specs` ハンドルで相の `"temperature": null` を見た ③ はそこを埋める。
    """
    body = (_PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "histograms[].temperature" in body, f"{skill}: 測定温度の置き場所を言っていない"
    assert _PHASE_TEMPERATURE.search(body), f"{skill}: 相の temperature が効かないことを言っていない"
