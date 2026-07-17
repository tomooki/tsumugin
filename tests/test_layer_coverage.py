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
import importlib
import inspect
import pkgutil
import re
from typing import Callable, Iterator, Mapping

import pytest

import tsumugin.mcp as mcp_pkg
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    ValidityReport,
)
from tsumugin.insitu.model import FrameRietveldResult, FrameSpec, SequentialRietveldResult
from tsumugin.mcp.insitu_tools import seq_result_to_dict, sequential_rietveld
from tsumugin.mcp.operando_diag_tools import repair_frames
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


#: `FrameRietveldResult` (M9 逐次の per-frame 型) の各フィールド → ② `sequential_rietveld` の
#: フレーム出力キー or UNEXPOSED(理由)。`AutoRietveldResult` と**同じ粒度の宣言**を M9 側にも置く
#: (operando の報告値はこの型を通る — 単一フレーム型だけ守っても系列側が抜ける)。
FRAME_RESULT_FIELDS: dict[str, tuple[str, str]] = {
    "frame_index": ("frame_index", "フレーム番号"),
    "axis_value": ("axis_value", "軸値 (温度/時間)"),
    "data_path": ("data_path", "観測データ"),
    "rwp": ("rwp", "最終 Rwp"),
    "gof": ("gof", "最終 GOF"),
    "refined_cells": ("refined_cells", "精密化格子"),
    "phase_fractions": ("phase_fractions", "**Scale**。相対比較専用 (新相の有意性・転移の追跡)"),
    "phase_names": ("phase_names", "このフレームで有効な相"),
    "changepoint": ("changepoint", "変化点フラグ"),
    "changepoint_reasons": ("changepoint_reasons", "発火した指標"),
    "validity_passed": ("validity_passed", "物理妥当性ゲート"),
    "refine_failed": ("refine_failed", "精密化失敗フレーム"),
    "residual_report": ("residual_report", "残差分解 (① 側で畳んだ小さな報告)"),
    "phase_weight_fractions": ("phase_weight_fractions", "**定量相分析の出版値** (実測 2.1x 乖離)"),
    "phase_weight_fraction_esd": ("phase_weight_fraction_esd", "重量分率 esd (出版に必須)"),
    "cell_esd": ("cell_esd", "格子 esd (出版に必須)"),
    # --- 未露出 (宣言することで「忘れた」ではなく「既知の穴」であることを示す) ---
    "n_obs": (
        UNEXPOSED,
        "Issue #97: M10 `anchor.select.frame_bic` が相数抑制に使う ① 内省フィールド。"
        "anchor 自体が ② 未露出 (上の LAYER1_FEATURES 参照) なので ③ から使い道が無い — "
        "anchor を ② へ出す際に一緒に配線すること",
    ),
}


def test_every_frame_result_field_is_declared():
    """`FrameRietveldResult` の全フィールドが露出状況を宣言していること (M9 側の粒度の穴を塞ぐ)。

    `AutoRietveldResult` にしか宣言表が無いと、**operando の報告値が通る per-frame 型**に
    フィールドを足しても表は緑のままになる。出版値の粒度盲点は「型ごと・② 表面ごと」に再発する。
    """
    actual = {f.name for f in dataclasses.fields(FrameRietveldResult)}
    declared = set(FRAME_RESULT_FIELDS)
    assert actual == declared, (
        f"FrameRietveldResult のフィールドと宣言が食い違う。"
        f"未宣言 (② への露出を決めること): {sorted(actual - declared)} / "
        f"実在しない宣言 (削除された?): {sorted(declared - actual)}"
    )


def test_unexposed_frame_result_fields_state_a_reason():
    """未露出フィールドは理由の明示を必須にする (黙って未露出にしない = §4.5 規則④-3)。"""
    for field, (key, why) in FRAME_RESULT_FIELDS.items():
        if key != UNEXPOSED:
            continue
        assert why and len(why) > 20, f"{field}: 未露出の理由が書かれていない"
        assert ("Issue #" in why) or ("意図的" in why), (
            f"{field}: 未露出は Issue 番号か「意図的」+理由が要る (現在: {why!r})"
        )


def test_declared_exposed_frame_result_fields_appear_in_tool_output():
    """露出ありと宣言したフレームフィールドが ② の**実際の出力**にキーとして在ること。

    非トートロジー: ソースを grep せず、実際に ``sequential_rietveld`` を呼んで frames[0] を見る。
    """
    out = _probe_sequential_rietveld()
    frame = out["frames"][0]  # type: ignore[index,call-overload]
    for field, (key, why) in FRAME_RESULT_FIELDS.items():
        if key == UNEXPOSED:
            continue
        assert key in frame, (
            f"{field}: ② のフレーム出力キー {key!r} を宣言しているが "
            f"sequential_rietveld の frames[] に無い ({why})"
        )


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


# ===========================================================================
# 粒度③: **粒度盲点は「② の表面」ごとに再発する** (Issue #96 レビュー 第2巡 HIGH)
# ---------------------------------------------------------------------------
# 上の 2 つの表は `AutoRietveldResult` → `auto_rietveld` という **1 本の経路**しか見ていない。
# 第1巡はその経路 (`_result_to_dict` / `seq_result_to_dict` / `engine._publication_of`) を直して
# 「粒度盲点を塞いだ」としたが、**3 つ目の ② 表面** — `repair_frames` の `repairs[]` — は
# Scale だけを返し続けていた。誰も監査しなかったためである。
#
# しかもそれが最悪の場所だった: ③ が修復するのは `check_phase_set` が名指ししたフレームであり、
# 実測 K2Mn[Fe(CN)6] ではそれが**転移ドーム頂点の直前 6 フレーム (125-130) = 論文の主要値**。
# 修復後に Scale しか無ければ ③ は「2.1x 誤って報告する」(skills/operando-diagnose の禁止事項)
# か「直したばかりのフレームの出版値が無い」の二択に追い込まれる。
#
# **設計**: 表面を列挙して塞ぐのではなく、**発見して宣言を強制する** (列挙は必ず取り残す)。
#   (a) `tsumugin.mcp` 配下で per-frame 相分率を**直列化している関数**をソースから発見し、
#       宣言が無ければ fail (将来のツールも網に掛かる)。
#   (b) 出版値を運ぶと宣言した表面は、**実際に呼んで**出力を再帰走査し、`phase_fractions` を
#       持つ全エントリが出版値も**値ごと**持つことを確かめる (grep でなく振る舞いで見る)。
# ===========================================================================

CARRIES_PUBLICATION = "CARRIES_PUBLICATION"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"

#: per-frame 相分率を ② へ直列化する関数 → (出版値も運ぶか, 根拠/理由)。
#: **`tsumugin.mcp` に新しい直列化点を作ったら、ここへ 1 行足すこと** (足さないと下の網羅テストが fail)。
PER_FRAME_FRACTION_EMITTERS: dict[str, tuple[str, str]] = {
    "tsumugin.mcp.insitu_tools.seq_result_to_dict": (
        CARRIES_PUBLICATION,
        "sequential_rietveld の per-frame。operando の主要な報告値 (相分率 vs 時間) が通る経路",
    ),
    "tsumugin.mcp.operando_diag_tools.repair_frames": (
        CARRIES_PUBLICATION,
        "repairs[] の per-frame。**修復対象は ③ が check_phase_set で名指ししたフレーム** = "
        "実測では転移ドーム頂点の直前 (125-130) = 論文の主要値そのもの",
    ),
    "tsumugin.mcp.operando_diag_tools.check_phase_set": (
        DIAGNOSTIC_ONLY,
        "意図的: seed_pinned_frames/frozen_fraction_frames が返す分率は **Scale であることに意味が"
        "ある指紋** (等分 seed 1/n との厳密一致 / 直前フレームとの厳密一致で張り付きを検出する)。"
        "重量分率に換算すると 1/n との一致が壊れて検出器そのものが成立しない。加えて**flag された"
        "フレームは定義上壊れており出版対象ではない** (だから repair_frames へ送る)。"
        "なお入力の系列 dict を `_result_from_dict` で復元する経路であり、往復で出版値は落ちる — "
        "出版値が要るなら sequential_rietveld / repair_frames の出力を直接読むこと",
    ),
}

#: 出版値を運ぶと宣言した表面の**実物プローブ** (grep でなく実際の出力を見るため)。
#: `_populated_result()` を返すスタブ runner で ② ツールを呼び、出力 dict を返す。
_PUBLICATION_SURFACE_PROBES: dict[str, Callable[[], object]] = {}


def _probe_sequential_rietveld() -> object:
    """② `sequential_rietveld` を決定論スタブ runner で実行した出力。"""
    return sequential_rietveld(
        [FrameSpec(data_path="f0.xrdml", axis_value=0.0).to_dict()],
        [_P],
        runner=lambda frame, phases, initial_cells: _populated_result(),
    )


def _probe_repair_frames() -> object:
    """② `repair_frames` を孤立スパイク系列 + スタブ runner で実行した出力 (修復が採用される)。"""
    cells = {"ph": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)}
    frames = tuple(
        FrameRietveldResult(
            frame_index=i,
            axis_value=float(i),
            data_path=f"f{i}.xrdml",
            rwp=rwp,
            gof=1.0,
            refined_cells=cells,
            phase_fractions={"ph": 1.0},
            phase_names=("ph",),
        )
        for i, rwp in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    return repair_frames(
        seq_result_to_dict(SequentialRietveldResult(frames=frames)),
        [FrameSpec(data_path=f"f{i}.xrdml", axis_value=float(i)).to_dict() for i in range(5)],
        [_P],
        rwp_delta=1.8,
        runner=lambda frame, phases, initial_cells: _populated_result(),
    )


_PUBLICATION_SURFACE_PROBES["tsumugin.mcp.insitu_tools.seq_result_to_dict"] = (
    _probe_sequential_rietveld
)
_PUBLICATION_SURFACE_PROBES["tsumugin.mcp.operando_diag_tools.repair_frames"] = (
    _probe_repair_frames
)

#: dict のキーとして `phase_fractions` を**直列化している**箇所 (`phase_fractions=` の復元側や
#: docstring 中の言及は拾わない)。
_FRACTION_KEY = re.compile(r'"phase_fractions"\s*:')


def _fraction_emitting_functions() -> dict[str, str]:
    """`tsumugin.mcp` 配下で per-frame 相分率を直列化している関数 → そのソース。

    **ツール関数の source だけを見ない**: `sequential_rietveld` は `seq_result_to_dict` へ委譲する
    ため、ツール単位の grep では**素通りする** (実際に落ちた 3 経路のうち 1 つがこの形)。
    パッケージ内の全関数を走査して**直列化点そのもの**を捕まえる。
    """
    found: dict[str, str] = {}
    for mod_info in pkgutil.iter_modules(mcp_pkg.__path__):
        module = importlib.import_module(f"{mcp_pkg.__name__}.{mod_info.name}")
        for name, obj in vars(module).items():
            if not inspect.isfunction(obj) or obj.__module__ != module.__name__:
                continue
            try:
                src = inspect.getsource(obj)
            except OSError:  # pragma: no cover - 動的定義の保険
                continue
            if _FRACTION_KEY.search(src):
                found[f"{module.__name__}.{name}"] = src
    return found


def _entries_with_key(obj: object, key: str) -> Iterator[Mapping[str, object]]:
    """入れ子の JSON 風構造から `key` を持つ dict を全て取り出す (出力の形に依存しない走査)。"""
    if isinstance(obj, Mapping):
        if key in obj:
            yield obj
        for value in obj.values():
            yield from _entries_with_key(value, key)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _entries_with_key(value, key)


def test_every_layer2_fraction_emitter_is_declared():
    """per-frame 相分率を ② へ出す**全ての**直列化点が露出方針を宣言していること。

    新しいツール/ヘルパが Scale を返し始めたら本テストが fail し、「出版値も返すのか / なぜ
    返さないのか」の宣言を強制する。**列挙した表面を守るのではなく、表面の追加を検出する**
    (第1巡は 3 経路を直したが 4 つ目を誰も探さなかった)。
    """
    actual = set(_fraction_emitting_functions())
    declared = set(PER_FRAME_FRACTION_EMITTERS)
    assert actual == declared, (
        f"② の per-frame 相分率 直列化点と宣言が食い違う。"
        f"未宣言 (出版値も返すか決めること — Scale だけ返すと ③ は 2.1x 誤る): "
        f"{sorted(actual - declared)} / "
        f"実在しない宣言 (削除/改名された?): {sorted(declared - actual)}"
    )


def test_diagnostic_only_fraction_emitters_state_a_reason():
    """出版値を返さない表面は理由の明示を必須にする (黙って Scale のみにしない = §4.5 規則④-3)。"""
    for emitter, (kind, why) in PER_FRAME_FRACTION_EMITTERS.items():
        if kind != DIAGNOSTIC_ONLY:
            continue
        assert why and len(why) > 20, f"{emitter}: 出版値を返さない理由が書かれていない"
        assert ("Issue #" in why) or ("意図的" in why), (
            f"{emitter}: Issue 番号か「意図的」+理由が要る (現在: {why!r})"
        )


def test_publication_carrying_emitters_are_all_probed():
    """出版値を運ぶと宣言した表面には**実物プローブ**があること (宣言だけで緑にしない)。

    プローブが無ければ下の振る舞いテストはその表面を黙って飛ばす = 宣言が実質無検査になる。
    """
    declared = {
        e for e, (kind, _) in PER_FRAME_FRACTION_EMITTERS.items() if kind == CARRIES_PUBLICATION
    }
    assert declared == set(_PUBLICATION_SURFACE_PROBES), (
        f"プローブ未整備: {sorted(declared - set(_PUBLICATION_SURFACE_PROBES))} / "
        f"宣言に無いプローブ: {sorted(set(_PUBLICATION_SURFACE_PROBES) - declared)}"
    )


@pytest.mark.parametrize("emitter", sorted(_PUBLICATION_SURFACE_PROBES))
def test_every_per_frame_fraction_entry_carries_publication_values(emitter):
    """★per-frame の Scale を返す ② のエントリは、出版値も**値ごと**返すこと。

    非トートロジー: ソースを grep せず、実際に ② ツールを呼んで出力を再帰走査し、
    ``phase_fractions`` を持つ全エントリを検査する。`repair_frames`/`seq_result_to_dict` から
    出版値の直列化を落とせば fail する (実証済; 出力の形を変えても走査は追随する)。

    **空 dict も不合格にする**: プローブは出版値を持つ結果を runner に返させているので、空なら
    ① → ② のどこかで値が落ちている (実際 `repair.FrameRepair` が Scale しか持たず落としていた)。
    """
    out = _PUBLICATION_SURFACE_PROBES[emitter]()
    entries = list(_entries_with_key(out, "phase_fractions"))

    assert entries, (
        f"{emitter}: プローブが `phase_fractions` を持つエントリを 1 つも返さない。"
        "プローブが陳腐化している (このテストは何も検査していない) か、表面が per-frame 分率を"
        "返さなくなった — どちらでも宣言の更新が要る"
    )
    for entry in entries:
        for key in PUBLICATION_FIELDS:
            assert key in entry, (
                f"{emitter}: per-frame エントリに {key!r} が無い — ③ は Scale しか読めず、"
                f"報告する定量値が 2.1x 誤る (実測 K2Mn[Fe(CN)6]): {sorted(entry)}"
            )
            assert entry[key], (
                f"{emitter}: {key!r} が空 — プローブは値を持つ結果を渡しているので、"
                f"① → ② のどこかで落ちている (空 dict は「値が得られなかった」の意味であり、"
                f"値がある精密化で空になってはならない)"
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
