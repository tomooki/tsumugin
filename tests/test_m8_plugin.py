"""TASK-0809: ③ Claude Code プラグインの契約テスト (乾式レビュー)。

プラグイン成果物 (plugin.json / skill / command) が存在し、SKILL が参照する MCP 3 ツールが
実際に MCP_TOOLS へ登録されていることを検証する (doc とコードの整合)。実 LLM は手動検証。
"""

from __future__ import annotations

import json
from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_CLOSED_LOOP_TOOLS = ("auto_rietveld", "propose_next_actions", "refine_with_revisions")


def test_plugin_manifest_exists_and_valid_json():
    manifest = _PLUGIN / ".claude-plugin" / "plugin.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["name"] == "tsumugin"


def test_skill_and_command_exist():
    assert (_PLUGIN / "skills" / "analyze" / "SKILL.md").exists()
    assert (_PLUGIN / "commands" / "analyze.md").exists()


def test_skill_references_only_registered_mcp_tools():
    text = (_PLUGIN / "skills" / "analyze" / "SKILL.md").read_text(encoding="utf-8")
    for tool in _CLOSED_LOOP_TOOLS:
        assert tool in text, f"SKILL が {tool} に言及していない"
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS 未登録"


def test_skill_documents_authority_boundary():
    text = (_PLUGIN / "skills" / "analyze" / "SKILL.md").read_text(encoding="utf-8")
    # 権限境界 (SafeAction 自律 / ModelAction 承認) が明記されていること
    assert "SafeAction" in text and "ModelAction" in text
    assert "承認" in text  # ユーザー承認を挟む記述
