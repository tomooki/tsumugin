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

import dataclasses
import inspect

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    ValidityReport,
)
from tsumugin.insitu.model import FrameRietveldResult, SequentialRietveldResult
from tsumugin.mcp.insitu_tools import seq_result_to_dict
from tsumugin.mcp.rietveld_tools import auto_rietveld
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


# ===========================================================================
# 粒度②: **マイルストーン単位の宣言では、露出済み機能の中に足した新フィールドが見えない**
# ---------------------------------------------------------------------------
# 上の `LAYER1_FEATURES` は「autorietveld (M7) は auto_rietveld で露出済み」としか言わない。
# そのため **M7 の中に**出版値 (重量分率 ± esd) を足しても、この表は緑のままである。実際に起きた
# (Issue #96 レビュー HIGH-2): `phase_weight_fractions`/`phase_weight_fraction_esd`/`cell_esd` は
# ① に実装され `model.py` が「出版値にはこれを使え」と書いていたのに、② に 1 箇所も配線が無く
# ③ が受け取れるのは Scale (`phase_fractions`) だけだった — 実測で **2.1x 誤る**値である。
#
# **フィールド単位の宣言**にすることで、`AutoRietveldResult` に新フィールドを足したら
# 「② にどう出すか / なぜ出さないか」を必ず一度考えさせる (下の網羅テストが fail する)。
# ===========================================================================

#: `AutoRietveldResult` の各フィールド → ② `auto_rietveld` 出力キー or UNEXPOSED(理由)。
AUTORIETVELD_RESULT_FIELDS: dict[str, tuple[str, str]] = {
    "stage_results": ("stages", "段階別 Rwp/GOF/母数/revert"),
    "final_rwp": ("final_rwp", "最終 Rwp"),
    "final_gof": ("final_gof", "最終 GOF"),
    "refined_cells": ("refined_cells", "精密化格子"),
    "validity": ("validity", "物理妥当性ゲート"),
    "gpx_path": ("gpx_path", "成果物パス"),
    "n_obs": ("n_obs", "観測点数 (bic/dof 用)"),
    # --- 出版値 (Issue #96 レビュー HIGH-2 で配線) ---
    "cell_esd": ("cell_esd", "格子 esd。esd を伴わない精密化値は出版できない"),
    "phase_weight_fractions": (
        "phase_weight_fractions",
        "**定量相分析の出版値**。`phase_fractions` (Scale) は単位胞質量差で乖離する (実測 2.1x)",
    ),
    "phase_weight_fraction_esd": ("phase_weight_fraction_esd", "重量分率 esd (出版に必須)"),
    # --- 未露出 (宣言することで「忘れた」ではなく「既知の穴」であることを示す) ---
    "phase_fractions": (
        UNEXPOSED,
        "意図的: 単一フレームの ② では Scale を出さない。出版値は phase_weight_fractions であり、"
        "Scale は相対比較 (M9 逐次の新相有意性判定) の用途に限る — そちらは "
        "sequential_rietveld が per-frame で出す",
    ),
    "residual_two_theta": (
        UNEXPOSED,
        "意図的: 残差配列は 2392 点 × 3 本 ≈ 150KB。境界を跨がせず ① 側で `residual_report` に畳む",
    ),
    "residual_intensity": (UNEXPOSED, "意図的: 同上 (residual_report に畳む)"),
    "residual_sigma": (UNEXPOSED, "意図的: 同上 (residual_report に畳む)"),
    "atom_uiso": (
        UNEXPOSED,
        "Issue #97: ① `refine_loop.diagnostics`/`diagnose_residual` が消費する内省フィールド。"
        "ただし ② `propose_next_actions` は `_result_from_dict` で復元するため**この値は届かず**、"
        "Uiso 発散の診断が MCP 経路では発火しない (既知の穴; 単体で ③ に出す価値は薄いので "
        "propose_next_actions 側で畳むのが筋)",
    ),
    "atom_occupancy": (UNEXPOSED, "Issue #97: 同上 (① 内省フィールド。占有率 [0,1] 逸脱の検出源)"),
    "hist_absorption": (UNEXPOSED, "Issue #97: 同上 (① 内省フィールド。負吸収の検出源)"),
    "hist_profile": (UNEXPOSED, "Issue #97: 同上 (① 内省フィールド。プロファイル現値)"),
    "peak_width_ratio": (UNEXPOSED, "Issue #97: 同上 (① 内省フィールド。幅ずれ)"),
    "asymmetry_metric": (UNEXPOSED, "Issue #97: 同上 (① 内省フィールド。残差非対称)"),
    "intensity_bias_metric": (UNEXPOSED, "Issue #97: 同上 (① 内省フィールド。選択配向)"),
    "bg_extrema": (UNEXPOSED, "Issue #97: 同上 (① 内省フィールド。背景 overfit)"),
}

_H = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
).to_dict()
_P = PhaseSpec(structure_path="a.cif", phase_name="ph").to_dict()

#: 出版値の 3 フィールド (Scale ではなくこちらが定量相分析の報告値)。
PUBLICATION_FIELDS = ("phase_weight_fractions", "phase_weight_fraction_esd", "cell_esd")


def _populated_result() -> AutoRietveldResult:
    """出版値を実際に持つ精密化結果 (② が落とさず運ぶかを値で確かめるため)。"""
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=7.0,
        final_gof=1.2,
        refined_cells={"ph": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        phase_fractions={"cubic": 0.656, "tetra": 0.344},
        phase_weight_fractions={"cubic": 0.472, "tetra": 0.528},
        phase_weight_fraction_esd={"cubic": 0.006, "tetra": 0.006},
        cell_esd={"ph": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
    )


def test_every_autorietveld_result_field_is_declared():
    """`AutoRietveldResult` の全フィールドが露出状況を宣言していること (粒度の穴を塞ぐ)。

    新フィールドを足したら本テストが fail し、「② にどう出すか / なぜ出さないか」の宣言を強制する。
    マイルストーン単位の `LAYER1_FEATURES` では**露出済み機能の内側**が見えなかった (HIGH-2)。
    """
    actual = {f.name for f in dataclasses.fields(AutoRietveldResult)}
    declared = set(AUTORIETVELD_RESULT_FIELDS)
    assert actual == declared, (
        f"AutoRietveldResult のフィールドと宣言が食い違う。"
        f"未宣言 (② への露出を決めること): {sorted(actual - declared)} / "
        f"実在しない宣言 (削除された?): {sorted(declared - actual)}"
    )


def test_unexposed_result_fields_state_a_reason():
    """未露出フィールドは理由の明示を必須にする (黙って未露出にしない = §4.5 規則④-3)。"""
    for field, (key, why) in AUTORIETVELD_RESULT_FIELDS.items():
        if key != UNEXPOSED:
            continue
        assert why and len(why) > 20, f"{field}: 未露出の理由が書かれていない"
        assert ("Issue #" in why) or ("意図的" in why), (
            f"{field}: 未露出は Issue 番号か「意図的」+理由が要る (現在: {why!r})"
        )


def test_declared_exposed_result_fields_actually_appear_in_tool_output():
    """露出ありと宣言したフィールドが ② の**実際の出力**にキーとして在ること。

    非トートロジー: ソースを grep するのではなく実際に ``auto_rietveld`` を呼んで出力 dict を見る。
    `rietveld_tools._result_to_dict` から配線を落とせば fail する。
    """
    out = auto_rietveld([_H], [_P], runner=lambda inp: _populated_result())
    for field, (key, why) in AUTORIETVELD_RESULT_FIELDS.items():
        if key == UNEXPOSED:
            continue
        assert key in out, (
            f"{field}: ② の出力キー {key!r} を宣言しているが auto_rietveld の出力に無い ({why})"
        )


def test_publication_values_survive_the_layer2_boundary_with_their_values():
    """★出版値が**値ごと** ③ に届くこと (キーがあるだけでは足りない)。

    実測 K2Mn[Fe(CN)6]: Scale 65.6% は重量分率では 47.2% — **2.1x の差**。③ が Scale しか
    受け取れなければ報告する定量値がそのまま誤る。esd 無しでは出版できない。
    """
    out = auto_rietveld([_H], [_P], runner=lambda inp: _populated_result())

    assert out["phase_weight_fractions"] == {"cubic": 0.472, "tetra": 0.528}
    assert out["phase_weight_fraction_esd"] == {"cubic": 0.006, "tetra": 0.006}
    assert out["cell_esd"] == {"ph": [0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0]}


def test_publication_values_are_reachable_per_frame_in_sequential_results():
    """operando (M9 逐次) の per-frame 経路でも出版値が ③ に届くこと。

    operando の主要な報告値は「相分率 vs 時間」であり、**この経路で誤ると論文の数値が誤る**
    (実測: tetra ドーム頂点 65.6 Scale% は実際には 47.2 wt%)。
    """
    frame = FrameRietveldResult(
        frame_index=0, axis_value=1.0, data_path="f0.xrdml", rwp=7.0, gof=1.1,
        refined_cells={"cubic": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)},
        phase_fractions={"cubic": 0.656, "tetra": 0.344},
        phase_names=("cubic", "tetra"),
        phase_weight_fractions={"cubic": 0.472, "tetra": 0.528},
        phase_weight_fraction_esd={"cubic": 0.006, "tetra": 0.006},
        cell_esd={"cubic": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
    )
    out = seq_result_to_dict(SequentialRietveldResult(frames=(frame,)))
    f0 = out["frames"][0]

    for key in PUBLICATION_FIELDS:
        assert key in f0, f"per-frame に {key} が無い (③ は Scale しか読めない)"
    assert f0["phase_weight_fractions"] == {"cubic": 0.472, "tetra": 0.528}


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
