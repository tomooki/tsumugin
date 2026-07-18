"""phase-id skill (M6/M11 相同定フロー) の契約テスト (Issue #102)。

skill は「③ への実行可能な指示」であり誤った指示は実装バグと同等に有害。存在しない MCP ツールを
指示しない・安全上重要な知見 (計量縮退系では Dara/位置マッチが効かない・同定は提案であり採否は ③)
を落とさないことを機械的に固定する。
"""

from __future__ import annotations

import re
from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_SKILL = Path("plugins/tsumugin/skills/phase-id/SKILL.md")
_COMMAND = Path("plugins/tsumugin/commands/phase-id.md")


def _text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_skill_and_command_exist():
    assert _SKILL.exists()
    assert _COMMAND.exists()


def test_skill_has_frontmatter_name():
    lines = _text().splitlines()
    assert lines[0] == "---"
    assert any(line.startswith("name: phase-id") for line in lines[:6])


def test_skill_drives_the_identification_tools():
    text = _text()
    for tool in (
        "assess_data_quality",
        "identify_phases",
        "identify_phase_mixtures",
        "identify_pattern",
    ):
        assert tool in text, f"skill が {tool} に言及していない"
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS に無い"


def test_skill_tool_table_lists_only_existing_tools():
    names = re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", _text(), re.MULTILINE)
    assert len(names) >= 4
    for name in names:
        assert name in MCP_TOOLS, f"skill のツール表に実在しないツール {name!r} がある"


def test_skill_warns_metric_degeneracy_breaks_position_matching():
    """★計量縮退系ではピーク位置マッチング/Dara が効かないことを警告すること (回帰ガード)。

    立方晶派生の多形は位置がほぼ一致し区別が分裂/強度比にあるため、位置マッチングで分離できない。
    これを ③ に伝えないと、Dara スコアを鵜呑みにして誤った相を採る (実測 K2Mn[Fe(CN)6])。
    """
    text = _text()
    assert "縮退" in text
    assert "Dara" in text
    assert "compare_structure_models" in text  # 縮退系の処方箋


def test_skill_states_identification_is_proposal_not_answer():
    """同定は候補提示であり採否は ③ であることを明示すること (自律採択の暴走防止)。"""
    text = _text()
    assert "提案" in text or "候補提示" in text
    assert "unknown_phase_flag" in text  # 未知相を正直に扱う


def test_skill_documents_double_background_subtraction_hazard():
    """二重背景減算の注意 (assess_data_quality で減算済みなら subtract_bg=False) を明示すること。"""
    text = _text()
    assert "subtract_bg" in text
    assert "二重" in text or "is_subtracted" in text


def test_command_references_skill():
    text = _COMMAND.read_text(encoding="utf-8")
    assert "phase-id" in text
    assert "identify_pattern" in text
