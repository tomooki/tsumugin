"""M8-③ Phase D: mem-model-fix plugin (skill/command) の契約テスト。

skill/command ファイルの存在と、skill が参照する MCP ツールが実際に登録されていることを検証する
(乾式レビューの機械化。実 LLM 判断は手動)。
"""
from __future__ import annotations

from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_SKILL = _PLUGIN / "skills" / "mem-model-fix" / "SKILL.md"
_CMD = _PLUGIN / "commands" / "mem-fix.md"


def test_skill_and_command_exist():
    assert _SKILL.is_file()
    assert _CMD.is_file()


def test_skill_has_frontmatter_name():
    head = _SKILL.read_text(encoding="utf-8").splitlines()
    assert head[0].strip() == "---"
    assert any(ln.startswith("name: mem-model-fix") for ln in head[:6])


def test_skill_references_registered_mcp_tools():
    """skill 本文が参照する MCP ツールが MCP_TOOLS に登録済みであること (契約整合)。"""
    text = _SKILL.read_text(encoding="utf-8")
    for tool in ("mem_density", "propose_structure_revisions", "edit_cif",
                 "refine_with_revisions"):
        assert tool in text, f"skill が {tool} を参照していない"
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS 未登録"


def test_skill_states_approval_boundary():
    """構造編集にユーザー承認を課す権限境界が明記されていること。"""
    text = _SKILL.read_text(encoding="utf-8")
    assert "承認" in text
    assert "edit_cif" in text
    # 受理基準 (Rwp 改善 ∧ 妥当性維持) の明記
    assert "妥当性" in text and "Rwp" in text


def test_analyze_skill_links_to_mem_model_fix():
    analyze = (_PLUGIN / "skills" / "analyze" / "SKILL.md").read_text(encoding="utf-8")
    assert "mem-model-fix" in analyze
