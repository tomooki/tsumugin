"""joint skill (X線+中性子 マルチヒストグラム精密化) の契約テスト (Issue #102)。

skill は「③ への実行可能な指示」であり誤った指示は実装バグと同等に有害。存在しない MCP ツールを
指示しない・安全上重要な知見 (joint = histograms 複数指定・占有率は中性子先行・サイト有無は BIC・
決定不能を正直に書く) を落とさないことを機械的に固定する。
"""

from __future__ import annotations

import re
from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_SKILL = Path("plugins/tsumugin/skills/joint/SKILL.md")
_COMMAND = Path("plugins/tsumugin/commands/joint-analyze.md")


def _text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_skill_and_command_exist():
    assert _SKILL.exists()
    assert _COMMAND.exists()


def test_skill_has_frontmatter_name():
    lines = _text().splitlines()
    assert lines[0] == "---"
    assert any(line.startswith("name: joint") for line in lines[:6])


def test_skill_drives_existing_tools():
    text = _text()
    for tool in (
        "auto_rietveld",
        "convert_pattern",
        "write_instrument_params",
        "compare_structure_models",
    ):
        assert tool in text, f"skill が {tool} に言及していない"
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS に無い"


def test_skill_tool_table_lists_only_existing_tools():
    names = re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", _text(), re.MULTILINE)
    assert len(names) >= 4
    for name in names:
        assert name in MCP_TOOLS, f"skill のツール表に実在しないツール {name!r} がある"


def test_skill_states_joint_is_multiple_histograms():
    """★joint = auto_rietveld に histograms を複数渡すこと、を明示すること。

    joint 専用ツールは無く、histograms=[...] の複数指定が joint 精密化の入口である。
    これを ③ に伝えないと joint に到達できない (② には別ツールが無いため)。
    """
    text = _text()
    assert "histograms" in text
    assert "joint" in text


def test_skill_documents_occupancy_needs_neutron_contrast_before_uiso():
    """占有率は中性子コントラストで・Uiso より先に解放する知見を明示すること。"""
    text = _text()
    assert "中性子" in text
    assert "占有率" in text
    assert "Uiso" in text and "先" in text  # 解放順序


def test_skill_documents_site_existence_by_bic():
    """サイトの有無 (Ow/D) は Rwp 単独でなく BIC (compare_structure_models) で判定すること。"""
    text = _text()
    assert "compare_structure_models" in text
    assert "BIC" in text
    assert "delta_bic" in text


def test_skill_documents_undeterminable_honesty():
    """joint でも決まらないもの (水素位置等) は「決定不能」と正直に書く指示があること。"""
    text = _text()
    assert "決定不能" in text or "決められ" in text


def test_command_references_skill():
    text = _COMMAND.read_text(encoding="utf-8")
    assert "joint" in text
    assert "auto_rietveld" in text
