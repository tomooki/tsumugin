"""M9: ③ Claude Code プラグイン (insitu skill/command) の契約テスト (乾式レビュー)。

insitu skill/command が存在し、参照する M9 MCP 3 ツールが実際に MCP_TOOLS へ登録されていること、
権限境界が明記されていることを検証する (doc とコードの整合)。実 LLM は手動検証。
"""

from __future__ import annotations

from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_INSITU_TOOLS = ("sequential_rietveld", "identify_and_add_phase", "parametric_fit")


def test_insitu_skill_and_command_exist():
    assert (_PLUGIN / "skills" / "insitu" / "SKILL.md").exists()
    assert (_PLUGIN / "commands" / "insitu-analyze.md").exists()


def test_insitu_skill_references_only_registered_mcp_tools():
    text = (_PLUGIN / "skills" / "insitu" / "SKILL.md").read_text(encoding="utf-8")
    for tool in _INSITU_TOOLS:
        assert tool in text, f"insitu SKILL が {tool} に言及していない"
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS 未登録"


def test_insitu_skill_documents_authority_boundary():
    text = (_PLUGIN / "skills" / "insitu" / "SKILL.md").read_text(encoding="utf-8")
    # 権限境界 (新相の採否・受理基準・ユーザー承認) が明記されていること
    assert "受理基準" in text
    assert "承認" in text
    # 初期相のみ与え新相を自動同定する要点
    assert "自動同定" in text


def test_insitu_command_references_skill():
    text = (_PLUGIN / "commands" / "insitu-analyze.md").read_text(encoding="utf-8")
    assert "insitu" in text
    assert "sequential_rietveld" in text
