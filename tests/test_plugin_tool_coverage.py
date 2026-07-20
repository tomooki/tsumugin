"""② MCP_TOOLS → ③ skill 手順書の逆方向カバレッジガード。

CLAUDE.md のカバレッジ規則 (Issue #97) は「① に実装しテスト green でも ② に配線されていなければ
③ から見て存在しない」ことを言う。本ファイルはその**逆方向**を機械的に固定する:
「② MCP_TOOLS に登録されていても、③ の SKILL.md のどれにも出現しなければ呼び手が存在しない
(dead on arrival)」。実害は同型で実証済み — M10 anchor (`anchored_sequential`) は実装済・
テスト green だったが露出時点まで手順書 0 件で、実 operando 解析では使われなかった
(CLAUDE.md 「⚠ ②到達可能性の『カバレッジ』規則」節)。

意図的に未露出のツールは `UNEXPOSED_MCP_TOOLS` に理由付きで宣言し、宣言の無い未露出だけを fail
させる。新しい ② ツールを追加して ③ への配線を忘れると本ガードが検出する。
"""

from __future__ import annotations

from pathlib import Path

from tsumugin.mcp.tools import MCP_TOOLS

_SKILLS_DIR = Path("plugins/tsumugin/skills")

# 現時点で③の手順書 (SKILL.md) に一度も出現しないことが確認済みの MCP ツールと、その理由。
# ここに載っていないツールが手順書へ出現しなくなると本ガードが fail する
# (= 新規ツール追加時の ③ 配線忘れを検出する)。
UNEXPOSED_MCP_TOOLS: dict[str, str] = {
    "get_trajectory": (
        "M2 逐次 Trajectory の読み出しツールだが、session.trajectory を埋める ② ツールが存在せず"
        "入力を作る経路が MCP に無い (dead on arrival)。Issue 化済み — 生成側の露出 or 廃止の判断待ち"
    ),
    "run_mem": (
        "M4/M5 シミュレート joint 検証用の旧 MEM 境界。実データ経路は mem_density/"
        "mem_rietveld_iterate (mem-model-fix skill) が担う。シミュレート経路を ③ の手順に載せるかは"
        "Issue で判断"
    ),
    "residual_report": (
        "設計上、単体呼び出しは主経路でない (auto_rietveld/sequential_rietveld の residual_report"
        "フィールド同梱が主経路 — ツール docstring に明記)。skill には同梱フィールドとして言及済み"
    ),
}


def _skill_files() -> list[Path]:
    return sorted(_SKILLS_DIR.glob("*/SKILL.md"))


def _all_skill_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _skill_files())


def test_skills_directory_has_expected_number_of_files():
    """本ガードが空ディレクトリに対して偽陰性 (全ツール「未出現」だが誰も気づかない) を出さないこと。"""
    files = _skill_files()
    assert len(files) == 7, f"SKILL.md の数が想定 (7) と違う: {[p.as_posix() for p in files]}"


def test_unexposed_declarations_reference_real_mcp_tools():
    """宣言表が実在しないツール名を挙げていないこと (宣言の陳腐化検出)。"""
    unknown = [name for name in UNEXPOSED_MCP_TOOLS if name not in MCP_TOOLS]
    assert not unknown, f"UNEXPOSED_MCP_TOOLS に実在しないツール名がある: {unknown}"


def test_every_mcp_tool_is_reachable_from_some_skill_or_declared_unexposed():
    """② の全ツールが、③ のいずれかの SKILL.md に出現するか、明示的に未露出宣言されていること。

    「①に実装済でも②に無ければ③に存在しない」の逆版。② にツールがあっても手順書のどこにも
    現れなければ、③ (JSON しか送れない LLM) はそのツールを使う手順を持たず呼び手が存在しない。
    宣言の無い未露出はツール追加時の配線漏れとして fail させる。
    """
    text = _all_skill_text()
    missing = sorted(
        name for name in MCP_TOOLS if name not in text and name not in UNEXPOSED_MCP_TOOLS
    )
    assert not missing, (
        f"以下の MCP ツールがどの SKILL.md にも出現せず、UNEXPOSED_MCP_TOOLS にも未宣言: {missing}。"
        "③ から見て存在しないツールになっている — SKILL.md に手順を書くか、理由を添えて"
        "UNEXPOSED_MCP_TOOLS に登録すること。"
    )
