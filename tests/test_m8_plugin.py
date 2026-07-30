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


# ---------------------------------------------------------------------------
# レシピ探索 (Phase 2, REQ-SAR-500/501/502) の手順書ガード
#
# **skill は「③ への実行可能な指示」であり、誤った指示は実装バグと同等に有害**。
# ここで縛るのは 3 つの失敗形:
#   (1) ② に無い引数を手順書が指示する ("呼べるが黙って間違う" の再導入)
#   (2) operando で探索を使うよう読める (フレーム数 × 候補数で時間予算が破綻する)
#   (3) 信頼度フラグを読む指示が消える (Rwp だけ見て「探索したから正しい」と誤読する)
# ---------------------------------------------------------------------------

_SKILL_TEXT = (_PLUGIN / "skills" / "analyze" / "SKILL.md").read_text(encoding="utf-8")


def test_search_arguments_documented_in_the_skill_actually_exist_on_the_tool():
    import inspect

    from tsumugin.mcp.rietveld_tools import auto_rietveld

    params = inspect.signature(auto_rietveld).parameters
    for name in ("search", "search_config"):
        assert name in _SKILL_TEXT, f"SKILL が {name} に言及していない"
        assert name in params, f"{name} が ② `auto_rietveld` に存在しない (手順書だけ先行している)"


def test_skill_forbids_the_recipe_search_in_operando():
    # REQ-SAR-502: 時間予算があるのは単一フレーム解析だけ。
    assert "sequential_rietveld" in _SKILL_TEXT
    section = _SKILL_TEXT.split("## どのレシピで回すかを")[1].split("\n## ")[0]
    assert "使わない" in section and "sequential_rietveld" in section, (
        "operando で探索を使わない指示が探索の節から消えている"
    )


def test_skill_tells_the_agent_to_read_the_confidence_flags():
    # 探索の価値は「答え」ではなく「答えの信頼度を言えること」にある。
    for key in ("order_dependent", "convergence_fallback"):
        assert key in _SKILL_TEXT, f"SKILL が {key} の読み方を書いていない"
    assert "順序依存" in _SKILL_TEXT


def test_analyze_skill_tells_the_agent_how_to_read_convergence_agreement():
    """★`search.agreement` の読み方が ③ の手順書にあること (① にあっても読み手が居ないと無い)。

    非トートロジー: 手順書が**誤った指示**を含むほうが害が大きいので、キーの存在だけでなく
    以下 2 つの**判断規律**まで固定する:

    1. `all_trajectories_duplicate` で**閾値を緩めない** (別の手順を足す)。ここを緩めると
       「実質 1 経路を N 回試した」結果が傍証として通ってしまう。
    2. `UNDETERMINED` を「一致」とも「不一致」とも報告しない (判断材料が無い状態である)。
    """
    text = _SKILL_TEXT

    assert "search.agreement" in text
    for key in ("is_corroborated", "corroboration_reason", "is_clique", "worst"):
        assert key in text, key
    for reason in (
        "insufficient_procedures",
        "all_trajectories_duplicate",
        "no_independent_agreement",
        "basin_too_small",
    ):
        assert reason in text, reason
    # ★ 規律 1: 重複経路のときに閾値を緩めさせない
    dup = text[text.index("all_trajectories_duplicate") :][:300]
    assert "閾値を緩めるのではなく" in dup, dup
    # ★ 規律 2: UNDETERMINED を一致/不一致に倒させない
    undet = text[text.index("`UNDETERMINED` は") :][:200]
    assert "ではない" in undet and "判断材料が無い" in undet, undet
