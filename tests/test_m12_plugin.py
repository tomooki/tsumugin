"""M12 T11: ③ 手順書の恒久ガード。

**skill は「③ への実行可能な指示」であり、誤った指示は実装バグと同等に有害** (CLAUDE.md)。
② に無い機能を書かない / 安全上重要な規律が消えないことを機械的に守る。

本ファイルのガードは**変異させて fail することを実証済**である (落ちないガードは無いより悪い)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.mcp.tools import MCP_TOOLS

_ANALYZE = Path("plugins/tsumugin/skills/analyze/SKILL.md")


@pytest.fixture(scope="module")
def analyze_text() -> str:
    return _ANALYZE.read_text(encoding="utf-8")


def test_skill_file_exists():
    assert _ANALYZE.is_file()


def test_backend_selection_tool_is_documented(analyze_text: str):
    """可用性確認ツールが手順書に載っていること。載っていなければ ③ は使わない。"""
    assert "list_refinement_backends" in analyze_text


def test_documented_backend_tool_actually_exists():
    """**② に無い機能を手順書に書かない**。逆方向のガード。"""
    assert "list_refinement_backends" in MCP_TOOLS


def test_availability_is_checked_before_selecting(analyze_text: str):
    """`backend` を渡す前に可用性を確認する指示があること。"""
    assert "前に" in analyze_text
    assert "available" in analyze_text


def test_backend_must_not_be_switched_across_hypotheses(analyze_text: str):
    """**この規律が消えると Rwp/BIC の比較が黙って壊れる**。

    バックエンドが違えば同じ構造でも Rwp は一致しない。仮説間・フレーム間で混ぜると
    「どちらが良いモデルか」の判定が「どちらのエンジンか」の判定にすり替わる。
    """
    assert "跨いで" in analyze_text and "切り替え" in analyze_text


def test_gpx_dependent_tools_are_flagged_as_unavailable_for_topas(analyze_text: str):
    """TOPAS には .gpx が無く MEM 系が使えないことを書いておく (知らないと詰まる)。"""
    assert "gpx" in analyze_text.lower()
    assert "MEM" in analyze_text


def test_unsupported_flags_are_documented_as_failing_loudly(analyze_text: str):
    """未対応フラグが「黙って無視される」と誤解させない。"""
    assert "UnsupportedStageFlagError" in analyze_text


def test_every_backend_named_in_the_skill_is_resolvable(analyze_text: str):
    """手順書が挙げるエンジン名が実際に解決できること (綴りのドリフト防止)。"""
    from tsumugin.autorietveld.backends import BACKEND_NAMES, resolve_backend

    for name in BACKEND_NAMES:
        assert f'"{name}"' in analyze_text, f"{name} が手順書に無い"
        resolve_backend(name)  # 例外が出ないこと


def test_backend_argument_is_shown_on_a_real_tool(analyze_text: str):
    """`backend` を受け取れると書いたツールが実際に受け取れること。"""
    import inspect

    for tool in ("auto_rietveld", "refine_with_revisions"):
        assert tool in analyze_text
        assert "backend" in inspect.signature(MCP_TOOLS[tool]).parameters
