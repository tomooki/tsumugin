"""③ Claude Code プラグイン (operando-diagnose skill/command) の契約テスト (乾式レビュー)。

skill/command が存在し、参照する ② MCP ツールが実在し、権限境界と**この skill の存在理由**
(Rwp では原理的に検出できない相集合の誤り) が明記されていることを検証する。実 LLM は手動検証。

**skill は「実行者 (③) への指示」であり、誤った指示は実装バグと同等に有害である**。
設計: `docs/design/operando-diagnosis/architecture.md` (§3 判断項目 J1-J8, §4.5 到達可能性)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_SKILL = _PLUGIN / "skills" / "operando-diagnose" / "SKILL.md"
_COMMAND = _PLUGIN / "commands" / "operando-diagnose.md"

# 本 skill が駆動する ② 診断ツール (architecture.md §2 の 4 ツール)
_DIAG_TOOLS = ("assess_data_quality", "check_phase_set", "repair_frames", "residual_report")


def test_operando_diagnose_skill_and_command_exist():
    assert _SKILL.exists()
    assert _COMMAND.exists()


def test_skill_references_only_existing_mcp_tools():
    """手順表が挙げる ② ツールはすべて実在すること (存在しないツマミを ③ に指示しない)。

    §4.5 到達可能性: ① に実装済でも ② に配線されていない機能を skill に書くと、③ は呼べない
    ツマミを指示され続ける (`auto_freeze_minor_cells`/`warm_start_fractions` が実際にそうだった)。
    """
    text = _SKILL.read_text(encoding="utf-8")
    body = text.split("## 使う MCP ツール", 1)[1].split("## ", 1)[0]
    names = re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", body, flags=re.MULTILINE)
    assert len(names) >= 4, f"ツール表を抽出できていない: {names}"
    unknown = [n for n in names if n not in MCP_TOOLS]
    assert not unknown, f"skill が実在しない MCP ツールを指示している: {unknown}"


def test_skill_drives_the_four_diagnosis_tools():
    text = _SKILL.read_text(encoding="utf-8")
    for tool in _DIAG_TOOLS:
        assert tool in text, f"operando-diagnose SKILL が {tool} に言及していない"
        # residual_report は auto_rietveld/sequential_rietveld の出力同梱が主経路だが
        # 単独ツールとしても登録されている
        assert tool in MCP_TOOLS, f"{tool} が MCP_TOOLS 未登録"


def test_skill_states_why_rwp_is_insufficient():
    """本 skill の存在理由 = Rwp では原理的に検出できない誤りが実在したこと。

    これが抜けると skill は「もう一つの精密化手順」に退化する。実データでは Rwp 8% (良好) の
    まま tetragonal が monoclinic の強度を肩代わりし非物理な描像を生成し、発見者は人間だった。
    """
    text = _SKILL.read_text(encoding="utf-8")
    assert "Rwp が良くても信じない" in text, "Rwp を信じない旨の明示が無い"
    assert "肩代わり" in text, "計量の近い相が強度を肩代わりする機序の説明が無い"
    assert "check_phase_set" in text, "相集合の完全性確認 (J5) が手順に無い"
    # Rwp 単独での結論を明示的に禁じていること
    assert re.search(r"Rwp が良いことを根拠に相集合を正しいと結論しない", text), (
        "禁止事項に Rwp 単独での相集合判定の禁止が無い"
    )


def test_skill_documents_propose_not_apply_boundary():
    """提案≠適用: 構造改訂・相集合変更はユーザー承認を挟むこと (M8 §4.5 継承)。"""
    text = _SKILL.read_text(encoding="utf-8")
    assert "提案≠適用" in text
    assert "承認" in text
    assert "可逆" in text or "棄却" in text, "受理されない場合の可逆棄却 (P2) の記述が無い"
    assert "原理的に不可" in text, "相の欠落が自律検出できないことが権限境界に無い"


def test_skill_warns_against_adding_phases_to_absorb_residual():
    """`baseline_numerator_fraction` が大きい = データ側の問題。相追加は誤魔化しになる。"""
    text = _SKILL.read_text(encoding="utf-8")
    assert "baseline_numerator_fraction" in text
    assert "残差を説明するためだけに相を足さない" in text


def test_command_references_skill_and_gates_on_data_quality():
    text = _COMMAND.read_text(encoding="utf-8")
    assert "operando-diagnose" in text
    assert "assess_data_quality" in text
    assert "check_phase_set" in text
    assert "承認" in text


def test_plugin_manifest_advertises_operando_diagnose():
    """plugin.json の description が operando 診断を明記していること (段4)。"""
    manifest = json.loads((_PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    desc = manifest["description"]
    assert "operando-diagnose" in desc
    for tool in ("assess_data_quality", "check_phase_set", "repair_frames"):
        assert tool in desc, f"manifest が {tool} を宣伝していない"
