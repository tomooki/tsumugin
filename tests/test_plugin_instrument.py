"""③ `instrument` skill (FR-502) の恒久ガード。

**skill は「③ への実行可能な指示」であり、誤った指示は実装バグと同等に有害** (CLAUDE.md)。
本テストは手順書が壊れたときに落ちる。各ガードは変異させて fail することを実証済み。

守る性質:

1. 手順書が挙げる MCP ツールが**実在する** (存在しないツールの指示を書かない)。
2. **安全上重要な引数が全ての呼び出し例に現れる** — `calibrate_instrument` の
   `two_theta_limits` (欠けるとノイズ域が最小二乗を支配して平坦化する)。
3. **「波長が判らないときは Cu Kα と決め打つ」型の指示が入り込まない** — 放射光データを
   黙って壊す。手順書は「判らないものを既定値で埋めない」を明示すること。
4. **Kα2 整合の確認手順**と、**標準試料から波長を較正したと主張しない**規律が残っていること。
5. 精密化を行う他 skill から本 skill への導線があること (呼び手が存在しない手順書は無意味)。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "tsumugin"
_SKILL = _PLUGIN / "skills" / "instrument" / "SKILL.md"

#: 手順書が指示に使う ② ツール (実在チェックの対象)。
_EXPECTED_TOOLS = (
    "read_pattern_metadata",
    "list_instrument_presets",
    "create_instrument_params",
    "inspect_instrument_params",
    "calibrate_instrument",
    "write_instrument_params",
    "convert_pattern",
)


@pytest.fixture(scope="module")
def text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_skill_exists_and_declares_its_name(text: str):
    assert text.startswith("---\nname: instrument\n")


def _tool_table(text: str) -> str:
    """「使う MCP ツール」節だけを切り出す (他節の表 — severity 等 — を巻き込まないため)。"""
    body = text.split("## 使う MCP ツール", 1)[1]
    return body.split("\n## ", 1)[0]


def test_every_tool_named_in_the_skill_exists_in_mcp_tools(text: str):
    """存在しないツールを指示しないこと (③ は呼べずにハード失敗する)。

    ⚠ **部分一致で見ない** — `calibrate_instrument` は `calibrate_instrument_now` の部分文字列
    なので、`in text` だけでは「実在しないツール名に書き換わった」変異を見逃す (実証済み)。
    正順 (期待するツールが単語として在る) と逆順 (名指しされたツールが実在する) の両方を見る。
    """
    for tool in _EXPECTED_TOOLS:
        assert re.search(rf"`{re.escape(tool)}[`(]", text), f"手順書が {tool} に言及していない"
        assert tool in MCP_TOOLS, f"手順書が実在しない MCP ツール {tool} を指示している"

    named = set(re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", _tool_table(text), re.M))
    named |= set(re.findall(r"`([a-z_][a-z0-9_]*)\(", text))
    unknown = sorted(n for n in named if n not in MCP_TOOLS)
    assert not unknown, f"手順書が実在しない MCP ツールを名指ししている: {unknown}"


def test_calibrate_examples_always_carry_two_theta_limits(text: str):
    """`calibrate_instrument` の JSON 例には必ず `two_theta_limits` があること。

    欠けると直接ビーム/低角ノイズが最小二乗を支配し「呼べるが黙って間違う」を再導入する
    (`repair_frames` で同じ穴を塞いだのと同型のガード)。
    """
    # ``` の分割は偶数=フェンス外/奇数=フェンス内。**フェンス内 (実際の呼び出し例) だけ**見る
    # — 散文や表に現れるツール名を例と誤認すると、ガードが本来の対象を見なくなる。
    fenced = [b for i, b in enumerate(text.split("```")) if i % 2 == 1]
    examples = [b for b in fenced if "out_path" in b and "wavelength_init" in b]
    assert examples, "calibrate_instrument の呼び出し例 (フェンス内 JSON) が手順書に無い"
    for block in examples:
        assert "two_theta_limits" in block, f"two_theta_limits の無い例がある:\n{block}"


def test_skill_forbids_guessing_the_wavelength(text: str):
    """「判らない波長を Cu Kα で埋める」型の指示が入り込まないこと。"""
    assert "波長を勝手に Cu Kα と決めないこと" in text


def test_skill_keeps_the_kalpha2_consistency_procedure(text: str):
    """Kα2 除去済みデータ × 二重線 instprm の確認手順が残っていること (実測で最大の系統残差)。"""
    assert "kalpha2_consistency_question" in text
    assert "kalpha2_stripped" in text
    assert "question" in text and "利用者に聞く" in text


def test_skill_forbids_claiming_wavelength_calibration_from_a_standard(text: str):
    """標準試料からの波長較正を主張しない規律 (試料変位と縮退して分離できない)。"""
    assert "標準試料から波長を較正した" in text and "主張しないこと" in text


def test_skill_keeps_the_nonneg_constraint_rationale(text: str):
    """非負拘束が「転写可能性のため」であることが残っていること。"""
    assert "転写可能な分解能には非負拘束が必須" in text


def test_skill_states_which_tools_need_gsasii(text: str):
    """GSAS-II を要するのはプリセットと較正だけ、と明記されていること。"""
    assert "GSAS-II 無しで動く" in text
    assert "list_instrument_presets" in text and "calibrate_instrument" in text


def test_skill_declares_the_reachability_roundtrip(text: str):
    """出力 `path` が精密化ツールのどの引数になるかが書かれていること (§4.5)。"""
    assert "histograms[].instrument_path" in text
    assert "instrument` spec の `path" in text


@pytest.mark.parametrize("skill", ["analyze", "insitu", "joint"])
def test_refinement_skills_point_at_the_instrument_skill(skill: str):
    """精密化を行う skill から導線があること — 呼び手の無い手順書は存在しないのと同じ。"""
    body = (_PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "`instrument` skill" in body, f"{skill} skill に instrument skill への導線が無い"
    assert "inspect_instrument_params" in body, f"{skill} skill が検査手順に言及していない"
