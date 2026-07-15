"""① の機能が ② (MCP) / ③ (skill) に露出しているかのカバレッジ検査 (Issue #97)。

**実行者から見えない実装は「無い」と同じ**。`docs/design/operando-diagnosis/architecture.md`
§4.5 規則④ の恒久ガード。

§4.5 の規則①〜③ (引数の到達可能性) は *個々のツール* を見るが、本テストは
**「① のマイルストーン機能が ② に露出しているか」**という別種の検査を行う。

実害 (2026-07-15): M10 anchor (FR-330, 715 行) は ② ツール 0 / skill 言及 0 だったため、
実 operando 解析 (K2Mn[Fe(CN)6] 全 247 フレーム) で使われず、**M10 が既に解いている病理を
③ が再生産**した。テストは全部 green だった — Python から呼べることしか見ていなかったため。

**本テストの意図的な設計**: 未露出そのものを禁じるのではなく、**未露出を明示的に宣言させる**。
宣言の無い未露出 = 「配線を忘れた」を検出する。宣言を書く行為が「本当に非露出でよいか」を
一度考えさせる関門になる。
"""

from __future__ import annotations

import inspect

from tsumugin.mcp.tools import MCP_TOOLS

# ① のマイルストーン機能 → ② への露出状況。
# 値は「露出を示す証拠」: ツール名 (MCP_TOOLS のキー) か、UNEXPOSED(理由)。
# **新しいマイルストーン機能を ① に足したら、ここへ 1 行足すこと** (足さないと下の網羅テストが fail)。
UNEXPOSED = "UNEXPOSED"

LAYER1_FEATURES: dict[str, tuple[str, str]] = {
    # feature: (露出を示すツール名 or UNEXPOSED, 根拠/理由)
    "autorietveld (M7)": ("auto_rietveld", "実構造 Rietveld"),
    "joint (M4/FR-240)": ("auto_rietveld", "auto_rietveld(histograms=[...]) で多ヒストグラム=joint"),
    "reference (M6)": ("identify_phases", "相同定 (単相/多相)"),
    "refine_loop (M8)": ("propose_next_actions", "agentic 閉ループ"),
    "insitu (M9)": ("sequential_rietveld", "逐次 operando"),
    "mem (M8-③)": ("mem_density", "MEM 密度→構造改訂"),
    "operando diag (M8-③)": ("check_phase_set", "相集合の完全性"),
    # --- 未露出 (Issue #97): 宣言することで「忘れた」ではなく「既知の穴」であることを示す ---
    "insitu.anchor (M10/FR-330)": (
        UNEXPOSED,
        "Issue #97: ② ツール 0・skill 言及 0。実 operando 解析で使われず病理を再生産した。"
        "run_anchored_sequential(runner=, identifier=) が callable のため #93 と同型の JSON spec が要る。"
        "**operando の既定手順に含めるべき最優先の穴**",
    ),
    "oed (M5/FR-700)": (UNEXPOSED, "Issue #97: 判別測定の提案。③ から呼べない"),
    "nested (M5/FR-500)": (
        UNEXPOSED,
        "Issue #97: compare_hypotheses は rank へ委譲し nested を参照しない",
    ),
    "chem (FR-412)": (UNEXPOSED, "Issue #97: identify_phases は chem を参照しない"),
    "compare_models (XND)": (UNEXPOSED, "Issue #97: 構造モデル比較 (BIC)。③ から呼べない"),
    "interop (XND)": (
        UNEXPOSED,
        "意図的: 外部形式→GSAS 変換は前処理であり、変換済みパスを auto_rietveld に渡せば足りる",
    ),
}


def test_declared_exposure_tools_actually_exist():
    """露出ありと宣言した機能のツールが実在すること (存在しないツールで「露出済み」と偽らない)。"""
    for feature, (tool, why) in LAYER1_FEATURES.items():
        if tool == UNEXPOSED:
            continue
        assert tool in MCP_TOOLS, (
            f"{feature}: 露出ツールとして {tool!r} を宣言しているが MCP_TOOLS に無い ({why})"
        )


def test_unexposed_features_state_a_reason():
    """未露出は**理由の明示**を必須にする (黙って未露出にしない = §4.5 規則④-3)。"""
    for feature, (tool, why) in LAYER1_FEATURES.items():
        if tool != UNEXPOSED:
            continue
        assert why and len(why) > 20, f"{feature}: 未露出の理由が書かれていない"
        assert ("Issue #" in why) or ("意図的" in why), (
            f"{feature}: 未露出は Issue 番号か「意図的」+理由が要る (現在: {why!r})"
        )


def test_anchor_is_still_unexposed_or_the_note_is_stale():
    """M10 anchor の露出状況と宣言が一致すること (露出したら宣言を更新させる)。

    Issue #97 が解決して ② に anchor ツールが入ったら、このテストが fail して
    `LAYER1_FEATURES` の更新を強制する — **宣言が実態から遅れるのを防ぐ**。
    """
    exposed = [
        t for t in MCP_TOOLS if "anchor" in inspect.getsource(MCP_TOOLS[t]).lower()
    ]
    declared_unexposed = LAYER1_FEATURES["insitu.anchor (M10/FR-330)"][0] == UNEXPOSED
    if exposed:
        assert not declared_unexposed, (
            f"anchor が ② に露出した ({exposed}) — LAYER1_FEATURES と "
            "skills/insitu・skills/operando-diagnose・AGENT_PLAYBOOK の更新も必要 (Issue #97)"
        )
    else:
        assert declared_unexposed, "anchor は ② 未露出のはずだが露出ありと宣言されている"
