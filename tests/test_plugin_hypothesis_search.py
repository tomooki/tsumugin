"""hypothesis-search skill (M4 多仮説裁定 + chem 降格 + oed) の契約テスト (Issue #102)。

skill は「③ への実行可能な指示」であり、誤った指示は実装バグと同等に有害。存在しない MCP ツールを
指示しない・安全上重要な原則 (降格は除外でない・最終採択は承認境界) を落とさないことを機械的に固定する。
"""

from __future__ import annotations

import re
from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_SKILL = Path("plugins/tsumugin/skills/hypothesis-search/SKILL.md")
_COMMAND = Path("plugins/tsumugin/commands/hypothesis-search.md")


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_skill_and_command_exist():
    assert _SKILL.exists()
    assert _COMMAND.exists()


def test_skill_has_frontmatter_name():
    lines = _skill_text().splitlines()
    assert lines[0] == "---"
    assert any(line.startswith("name: hypothesis-search") for line in lines[:6])


def test_skill_drives_the_m4_tools():
    """M4 フローの主要ツール + chem/oed ツールに言及し、全て MCP_TOOLS に実在すること。"""
    text = _skill_text()
    required = [
        "submit_analysis",
        "list_hypotheses",
        "compare_hypotheses",
        "propose_discriminating_measurements",
        "accept_hypothesis",
        "revert",
        "export_gpx",
    ]
    for tool in required:
        assert tool in text, f"skill が {tool} に言及していない"
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS に無い (存在しないツールを指示している)"


def test_skill_tool_table_lists_only_existing_tools():
    """「使う MCP ツール」表の第1列 (バッククォート付きツール名) が全て実在すること。"""
    names = re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", _skill_text(), re.MULTILINE)
    assert len(names) >= 5
    for name in names:
        assert name in MCP_TOOLS, f"skill のツール表に実在しないツール {name!r} がある"


def test_skill_states_chem_demotion_is_not_exclusion():
    """★化学降格は除外でなく確率補正であることを明示すること (Dara 教訓の回帰ガード)。

    「化学的に不自然だから候補から消す」は誤り — 稀な準安定相を弾いてしまう。skill が降格を
    除外として教えると、③ は evidence が強い相まで消してしまう。
    """
    text = _skill_text()
    assert "chem_context" in text
    assert "降格" in text
    assert "除外" in text  # 「除外ではない」の文脈で言及
    assert re.search(r"降格は除外", text) or re.search(r"除外(で|では)ない", text), (
        "降格が除外ではないことが明示されていない"
    )
    # 組成の供給が要る旨 (phase_compositions) — これが無いと降格が静かに効かない
    assert "phase_compositions" in text


def test_skill_documents_oed_is_proposal_only():
    """判別測定 (OED) は提案のみ・非破壊であることを明示すること。"""
    text = _skill_text()
    assert "propose_discriminating_measurements" in text
    assert "提案のみ" in text or "非破壊" in text
    assert "情報利得" in text


def test_skill_documents_acceptance_authority_boundary():
    """最終採択の承認境界 (human モードは agent 採択を拒否) を明示すること。"""
    text = _skill_text()
    assert "承認" in text
    assert "human" in text
    assert "recommend_only" in text or "拒否" in text


def test_command_references_skill():
    text = _COMMAND.read_text(encoding="utf-8")
    assert "hypothesis-search" in text
    assert "submit_analysis" in text
