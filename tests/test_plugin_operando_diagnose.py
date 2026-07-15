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

import pytest

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_SKILL = _PLUGIN / "skills" / "operando-diagnose" / "SKILL.md"
_COMMAND = _PLUGIN / "commands" / "operando-diagnose.md"
_INSITU_SKILL = _PLUGIN / "skills" / "insitu" / "SKILL.md"
_PLAYBOOK = Path("docs/tasks/operando-diagnosis/AGENT_PLAYBOOK.md")

# 本 skill が駆動する ② 診断ツール (architecture.md §2 の 4 ツール)
_DIAG_TOOLS = ("assess_data_quality", "check_phase_set", "repair_frames", "residual_report")

# `repair_frames` の呼び出し例を載せている全ドキュメント (skill 2 種 + 非 Claude 向け playbook)
_REPAIR_FRAMES_DOCS = (_SKILL, _INSITU_SKILL, _PLAYBOOK)

# `appearances` を「読む/監査する」旨の指示 (語は変わりうるので動詞は選択肢で受ける)
_APPEARANCES_AUDIT = re.compile(r"`appearances`[^\n]{0,40}(監査|読む|読み|確認)")


def _call_sites(text: str, func: str) -> list[str]:
    """``func(`` の呼び出し例を**括弧の対応をとって**丸ごと抜き出す (複数行の呼び出しに対応)。

    表 (``| `repair_frames` | ... |``) や散文中の言及は ``func(`` に一致しないので拾わない —
    検証対象は「③ がそのまま真似する呼び出し例」だけである。
    """
    sites: list[str] = []
    for m in re.finditer(re.escape(func) + r"\(", text):
        start = m.end()
        depth = 1
        for i in range(start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    sites.append(text[start:i])
                    break
        else:  # pragma: no cover - 閉じ括弧の無い壊れた例
            sites.append(text[start:])
    return sites


def _table_rows(text: str, heading: str) -> list[list[str]]:
    """``heading`` 節の markdown 表を ``[セル, ...]`` の行リストへ (区切り行/ヘッダは除く)。"""
    body = text.split(heading, 1)[1].split("\n## ", 1)[0]
    rows: list[list[str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= {"-", ":"} and c for c in cells):  # 区切り行
            continue
        rows.append(cells)
    return rows


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


# ===========================================================================
# ドキュメント整合の恒久ガード (誤った指示 = 実装バグと同等に有害)
# ===========================================================================


@pytest.mark.parametrize("doc", _REPAIR_FRAMES_DOCS, ids=lambda p: p.as_posix())
def test_repair_frames_examples_always_pass_two_theta_limits(doc):
    """ガード1: `repair_frames` の呼び出し例は必ず `two_theta_limits` を伴うこと。

    省略すると修復試行だけが全域で走り、採用規則 `rwp_after < rwp_before - rwp_tol` が
    **系列側と異なるデータ域の Rwp を比較**する。**例外は出ず、無効な比較のまま「修復成功」が
    採用される** ——「呼べるが黙って間違う」は「呼べない」より悪い (architecture.md §4.5 #2)。
    ③ は例をそのまま真似するので、例から欠けることが即ちこの失敗の再導入になる。
    """
    text = doc.read_text(encoding="utf-8")
    sites = _call_sites(text, "repair_frames")
    assert sites, f"{doc}: repair_frames の呼び出し例が無い (③ が真似する例が必要)"
    bad = [s for s in sites if "two_theta_limits" not in s]
    assert not bad, (
        f"{doc}: two_theta_limits の無い repair_frames 呼び出し例がある: {bad}。"
        "系列を精密化したのと同じレンジを必ず渡すこと (異なるデータ域の Rwp 比較は無効)。"
    )


@pytest.mark.parametrize("skill", (_SKILL, _INSITU_SKILL), ids=lambda p: p.as_posix())
def test_skill_authority_tables_agree_on_autonomous_phase_addition(skill):
    """ガード2: 2 つの skill の権限境界表が「新相の自動追加」で矛盾しないこと。

    実装は `phase_id` 有効時、**ユーザー承認なしに**受理基準 (frac∧Rwp∧validity) だけで相を
    追加する (`insitu.engine._accept_new_phase`)。「相追加には常に承認が要る」と書く skill が
    あると、③ は**実際に起きた相追加を監査しない** — 追加された相の化学的妥当性は受理基準の
    視野の外 (残差の説明力しか見ない) なので、監査の欠落は誤った相の見逃しに直結する。

    脆くしないため、語ではなく**主張**を見る: 「新相」の行の決定論コア列が (a) 自律採用すると
    言い (b) 受理基準を根拠に挙げ (c) ❌ (=コアは行わない) でないこと。加えて ③ 側に
    `appearances` の監査指示があること。
    """
    text = skill.read_text(encoding="utf-8")
    rows = [r for r in _table_rows(text, "## 権限境界") if "新相" in r[0]]
    assert rows, f"{skill}: 権限境界表に「新相」の追加に関する行が無い"
    for cells in rows:
        core = cells[1]
        assert "自律" in core and "受理基準" in core, (
            f"{skill}: 新相追加が受理基準による自律採用だと書かれていない: {cells!r}。"
            "実装は承認なしに追加する — 表がそれを隠すと ③ が監査をやめる。"
        )
        assert "❌" not in core, (
            f"{skill}: 新相追加をコアが行わない (❌) と書いている: {cells!r}。"
            "実装は phase_id 有効時に自律追加する (常に承認必須ではない)。"
        )
    assert _APPEARANCES_AUDIT.search(text), (
        f"{skill}: 自動追加された相 (`appearances`) を ③ が監査/確認する指示が無い。"
        "自律追加を許す以上、事後監査が唯一の歯止めである。"
    )


@pytest.mark.parametrize(
    "marker",
    [
        pytest.param(re.compile(r"Rwp が良くても信じない"), id="J5: Rwp が良くても信じない"),
        pytest.param(re.compile(r"J5"), id="J5 の見出し"),
        pytest.param(_APPEARANCES_AUDIT, id="appearances の監査"),
        pytest.param(re.compile(r"残差を説明するためだけに相を足さない"), id="相の水増し禁止"),
    ],
)
def test_playbook_and_skill_share_safety_critical_instructions(marker):
    """ガード3: playbook (`内容は本書と同一` と宣言) と operando-diagnose skill が乖離しないこと。

    playbook は非 Claude ハーネス向けの同一内容版であり、**片方にしか無い安全指示は、その
    ハーネスでだけ失敗が再現する**ことを意味する。安全上の要 (J5/Rwp を信じない・`appearances`
    の監査・相の水増し禁止) を双方に要求する。`two_theta_limits` の必須性は
    `test_repair_frames_examples_always_pass_two_theta_limits` が両文書に対して担保する。

    **本ガードの限界**: 表現の同値性は検査できない (語 → 主張の写像は機械化できない)。
    再言明の欠落を捕らえるだけで、意味の食い違いまでは防げない — 最終防波堤は人間のレビュー。
    """
    for doc in (_SKILL, _PLAYBOOK):
        text = doc.read_text(encoding="utf-8")
        assert marker.search(text), (
            f"{doc}: 安全上の要となる指示 ({marker.pattern}) が無い。"
            "playbook と skill は同一内容を宣言している — 片方だけの安全指示は乖離である。"
        )


@pytest.mark.parametrize("doc", (_SKILL, _PLAYBOOK), ids=lambda p: p.as_posix())
def test_instrument_spec_keys_are_documented_where_instrument_is_required(doc):
    """ガード3c: `instrument` を渡せと指示する文書は、そのキーも文書化していること。

    ③ は JSON しか送れず、`instrument` spec の中身は**サーバ側 runner の全設定**である
    (放射光か実験室 X 線か・背景項数・少数相セル凍結)。「`instrument` を明示せよ」とだけ書いて
    キーを書かない文書は、③ に**組み立てられない値**を要求する (§4.5 到達可能性と同型の欠陥)。

    実際 operando-diagnose skill は `auto_freeze_minor_cells` に一切言及しないまま
    `instrument` を要求しており、playbook の「内容は本書と同一」宣言が偽になっていた。

    **限界**: キーが列挙されていることしか見ない。値の意味の正しさは human review。
    """
    text = doc.read_text(encoding="utf-8")
    assert "instrument" in text, f"{doc}: instrument spec への言及が無い"
    for key in ("path", "radiation", "geometry", "background_coeffs", "auto_freeze_minor_cells"):
        assert key in text, (
            f"{doc}: `instrument` を要求しているのにキー `{key}` を文書化していない。"
            "③ は JSON しか送れないため、キーが書かれていなければ組み立てられない。"
        )
    # 置き場所の取り違え (tool の kwarg として渡す → TypeError が境界を越える) を防ぐ
    assert re.search(r"auto_freeze_minor_cells[^\n]{0,200}(閾値|threshold)", text, re.S), (
        f"{doc}: auto_freeze_minor_cells を閾値と説明していない (bool 誤用は全相凍結になる)"
    )


def test_playbook_documents_auto_freeze_as_instrument_spec_threshold():
    """ガード3b: playbook の `auto_freeze_minor_cells` の説明が実装と一致すること。

    2 通りの取り違えがどちらも**黙って**壊す:
    - **tool の kwarg として渡す** → `TypeError` が MCP 境界を越える (置き場所は `instrument` spec)。
    - **bool を渡す** → `float(True)==1.0` = 「分率 1.0 未満の相をすべて凍結」= 全相のセルが
      黙って凍結される (② が bool を拒否するのはこのため)。

    `insitu` SKILL 側の同じ主張は `test_m9_plugin.py` が守っている。
    """
    import inspect  # noqa: PLC0415

    from tsumugin.autorietveld.engine import run_auto_rietveld  # noqa: PLC0415

    ann = inspect.signature(run_auto_rietveld).parameters["auto_freeze_minor_cells"].annotation
    assert "float" in str(ann), f"実装の型が変わった: {ann}"

    text = _PLAYBOOK.read_text(encoding="utf-8")
    assert "auto_freeze_minor_cells" in text
    assert "閾値" in text, "playbook が auto_freeze_minor_cells を閾値と説明していない"
    assert "bool ではない" in text, "playbook に bool との取り違えへの注意が無い"
    assert re.search(r"`instrument` spec のキー", text), (
        "playbook が auto_freeze_minor_cells の置き場所 (instrument spec) を明示していない"
    )


def test_plugin_manifest_advertises_operando_diagnose():
    """plugin.json の description が operando 診断を明記していること (段4)。"""
    manifest = json.loads((_PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    desc = manifest["description"]
    assert "operando-diagnose" in desc
    for tool in ("assess_data_quality", "check_phase_set", "repair_frames"):
        assert tool in desc, f"manifest が {tool} を宣伝していない"
