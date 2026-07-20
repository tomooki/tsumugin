"""M9: ③ Claude Code プラグイン (insitu skill/command) の契約テスト (乾式レビュー)。

insitu skill/command が存在し、参照する M9 MCP 3 ツールが実際に MCP_TOOLS へ登録されていること、
権限境界が明記されていることを検証する (doc とコードの整合)。実 LLM は手動検証。

**skill は「実行者 (③) への指示」であり、誤った指示は実装バグと同等に有害である**。そのため
以下を機械的に守る (`docs/design/operando-diagnosis/architecture.md` §3.5 の R1-R5 の恒久ガード):

- 手順表が挙げる MCP ツールは**実在すること** (存在しないツマミを指示しない)。
- **R1 回帰ガード**: 「Rwp が目標帯に収まるか」式の受理基準を復活させないこと。Rwp は相集合の
  誤りに盲目であり、実データで Rwp 8% のまま非物理な描像が生成された。
- **R5 回帰ガード**: MP キーの取得方法など陳腐化しやすい前提が実装と一致すること。
"""

from __future__ import annotations

import re
from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_PLUGIN = Path("plugins/tsumugin")
_INSITU_TOOLS = ("sequential_rietveld", "identify_and_add_phase", "parametric_fit")
_SKILL = _PLUGIN / "skills" / "insitu" / "SKILL.md"


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


def test_insitu_command_does_not_drop_the_skills_mandatory_steps():
    """command の圧縮箇条書きが skill の必須手順を欠落させないこと。

    insitu SKILL.md は手順0 (`assess_data_quality`) と手順5 (`check_phase_set`, 「飛ばしてよい
    手順ではない」) を明示的に必須と言う。圧縮版の command がこれを落とすと、③ が command 経由で
    動くときだけ必須手順を踏まずに回してしまう (operando-diagnose.md には同種の警告がある一方
    insitu-analyze.md には無かった非対称の解消)。転移を含む operando の既定経路
    `anchored_sequential` への言及も同様に欠落していた。
    """
    text = (_PLUGIN / "commands" / "insitu-analyze.md").read_text(encoding="utf-8")
    assert "assess_data_quality" in text, "command が手順0 (assess_data_quality) に言及していない"
    assert "check_phase_set" in text, "command が手順5 (check_phase_set) に言及していない"
    assert "anchored_sequential" in text, "command が転移を含む operando の既定 anchored_sequential に言及していない"


def _skill_tool_table_names() -> list[str]:
    """skill の「使う MCP ツール (②)」表の第1列 (バッククォート付き) を抜き出す。"""
    text = _SKILL.read_text(encoding="utf-8")
    body = text.split("## 使う MCP ツール", 1)[1].split("## ", 1)[0]
    return [m for m in re.findall(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", body, flags=re.MULTILINE)]


def test_insitu_skill_tool_table_lists_only_existing_tools():
    """手順表が挙げる ② ツールはすべて実在すること (存在しないツマミを ③ に指示しない)。

    §4.5 到達可能性: ① に実装済でも ② に配線されていない機能を skill に書くと、③ は呼べない
    ツマミを指示され続ける。実際に `auto_freeze_minor_cells`/`warm_start_fractions` が
    ② 未露出のまま設計 §3.5 R4 に「手順へ配線」と書かれていた (Issue #93 で配線)。
    """
    names = _skill_tool_table_names()
    assert len(names) >= len(_INSITU_TOOLS), f"ツール表を抽出できていない: {names}"
    unknown = [n for n in names if n not in MCP_TOOLS]
    assert not unknown, f"skill が実在しない MCP ツールを指示している: {unknown}"


def test_insitu_skill_does_not_teach_rwp_only_convergence():
    """R1 回帰ガード: Rwp 単独での収束/受理判定を復活させない。

    「Rwp がフレーム全域で目標帯 (チュートリアル値 ± マージン) に収まるか」という旧受理基準は、
    実データ (K2Mn[Fe(CN)6] operando) の失敗そのものだった: **Rwp 8% = 目標帯内のまま**、計量の
    近い tetragonal が monoclinic の強度を肩代わりし非物理な描像を生成した。Rwp は相集合の誤りに
    盲目であり、相集合の完全性確認 (check_phase_set) が代替不能な必須手順である。

    **本テストの限界**: テキストの禁止語ではなく「**指示形**の復活」を検出する。「目標帯」の語自体は
    *失敗の説明*として skill 本文に必要であり (禁止すると次の書き手が説明ごと消す誘因になる)、
    語の有無では指示と警告を区別できない。よって旧受理基準の**指示形**のみを禁じ、併せて代替手順が
    存在することを積極条件で確認する。表現を変えた再導入までは防げない — 最終防波堤は人間のレビュー。
    """
    text = _SKILL.read_text(encoding="utf-8")
    # 旧受理基準の指示形 (手順4「Rwp がフレーム全域で目標帯 … に収まるか」) が復活していないこと
    assert not re.search(r"Rwp が.{0,12}目標帯", text), "Rwp 目標帯による受理基準が復活している (R1)"
    # 代替となる必須手順が存在すること (積極条件)
    assert "check_phase_set" in text, "相集合の完全性確認が手順から欠落している"
    assert "相集合" in text and "盲目" in text, "Rwp が相集合の誤りに盲目である旨の警告が無い"
    assert re.search(r"Rwp だけで|Rwp が良くても|Rwp が良いことを根拠", text), (
        "Rwp 単独で判定しない旨の明示が無い"
    )


def test_insitu_skill_mp_key_precondition_matches_implementation():
    """R5 回帰ガード: MP キーの前提が実装 (.env 自動読込, Issue #51) と一致すること。"""
    text = _SKILL.read_text(encoding="utf-8")
    assert ".env" in text, "MP キーの .env 自動読込 (#51) が skill に反映されていない"
    # 実装が実際に .env を読むことを確認する (doc だけ直して実装が違う事故を防ぐ)
    from tsumugin.mp.client import _API_KEY_ENV, _read_dotenv_key  # noqa: PLC0415

    assert _API_KEY_ENV in text, f"skill が実際の環境変数名 {_API_KEY_ENV} を書いていない"
    assert callable(_read_dotenv_key)


def test_insitu_skill_documents_auto_freeze_as_threshold_not_bool():
    """`auto_freeze_minor_cells` は bool でなく相分率閾値 (float) — 型を取り違えると逆効果。

    bool `True` は `float(True)==1.0` = 「分率 1.0 未満の相をすべて凍結」となり、多相精密化で
    **全相のセルが黙って凍結**される (例外は出ない)。skill が閾値であることを明示していること。
    """
    import inspect  # noqa: PLC0415

    from tsumugin.autorietveld.engine import run_auto_rietveld  # noqa: PLC0415

    ann = inspect.signature(run_auto_rietveld).parameters["auto_freeze_minor_cells"].annotation
    assert "float" in str(ann), f"実装の型が変わった: {ann}"
    text = _SKILL.read_text(encoding="utf-8")
    if "auto_freeze_minor_cells" in text:
        assert "閾値" in text, "auto_freeze_minor_cells を閾値と説明していない"
        assert "bool ではない" in text, "bool と取り違える誤用への注意が無い"


# --------------------------------------------------------------------------------------
# FR-318 電気化学制約 (charge_constraint) の恒久ガード
# --------------------------------------------------------------------------------------

_M9_PLAYBOOK = Path("docs/tasks/m9-insitu-sequential/AGENT_PLAYBOOK.md")


def test_insitu_skill_documents_charge_constraint():
    """FR-318: skill が alkali_budget → charge_constraint の導線と安全指示を持つこと。

    ツールがあっても手順書に無ければ ③ は使わない (カバレッジ規則④-2)。
    """
    text = _SKILL.read_text(encoding="utf-8")
    assert "alkali_budget" in text, "insitu SKILL が alkali_budget に言及していない"
    assert "alkali_budget" in MCP_TOOLS
    assert "charge_constraint" in text
    # §4.5 到達可能性: offset_s/interval_s は align_echem の出力から来る。insitu SKILL がこの
    # 供給元に触れないと、③ は alkali_budget のこの2引数を「どこから来るか言えない」まま渡す
    # ことになる (operando-diagnose J8 には既にあるので insitu 側だけ欠落していた非対称の解消)。
    assert "align_echem" in text, "insitu SKILL が align_echem に言及していない (offset_s/interval_s の出所)"
    assert "align_echem" in MCP_TOOLS
    # 安全指示: diagnose 既定 / lock は明示 opt-in / soft は headless で無効
    assert "diagnose" in text
    assert "lock_fractions" in text
    assert "完全決定" in text, "2相 lock の自由度ゼロ警告が無い (採用判断を誤らせる)"
    assert re.search(r"soft.{0,80}(使わない|無効)", text, flags=re.DOTALL), (
        "soft (ChemComp) が headless で無効である旨の指示が無い — 呼べるが黙って効かない"
    )
    # x₀ 校正は提案のみ (提案≠適用)
    assert "提案≠適用" in text


def test_insitu_playbook_mirrors_charge_constraint_safety():
    """skill と PLAYBOOK は安全上重要な指示を同内容で持つ (ガード規約と同じ規律)。"""
    text = _M9_PLAYBOOK.read_text(encoding="utf-8")
    assert "alkali_budget" in text
    assert "lock_fractions" in text
    assert re.search(r"soft.{0,80}(使わない|無効)", text, flags=re.DOTALL)
    assert "提案≠適用" in text
    # echem 範囲外フレームに拘束しない (捏造禁止)
    assert "拘束されない" in text or "拘束しない" in text


def test_charge_constraint_spec_keys_exist_in_real_signature():
    """skill の JSON 例が実署名に無いキーを教えない (呼べない指示の検出)。"""
    import inspect

    from tsumugin.mcp.insitu_tools import sequential_rietveld

    sig = inspect.signature(sequential_rietveld)
    assert "charge_constraint" in sig.parameters, (
        "skill は charge_constraint を教えるが sequential_rietveld に実在しない"
    )
    from tsumugin.mcp.anchor_tools import anchored_sequential

    sig2 = inspect.signature(anchored_sequential)
    assert "charge_constraint" in sig2.parameters
