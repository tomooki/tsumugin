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

import ast
import dataclasses
import importlib
import inspect
import pkgutil
import textwrap
from pathlib import Path
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
from tsumugin.mcp.insitu_tools import (
    _result_from_dict as _series_deserializer,
)
from tsumugin.mcp.insitu_tools import (
    _instrument_path_resolver,
    _runner_from_instrument,
    parametric_fit,
    seq_result_to_dict,
    sequential_rietveld,
)
from tsumugin.mcp.operando_diag_tools import check_phase_set, repair_frames
from tsumugin.mcp.rietveld_tools import auto_rietveld
from tsumugin.mcp.tools import MCP_TOOLS

# ① のマイルストーン機能 → ② への露出状況。
# 値は「露出を示す証拠」: ツール名 (MCP_TOOLS のキー) か、UNEXPOSED(理由)。
# **新しいマイルストーン機能を ① に足したら、ここへ 1 行足すこと** (足さないと下の網羅テストが fail)。
UNEXPOSED = "UNEXPOSED"

LAYER1_FEATURES: dict[str, tuple[str, str]] = {
    # feature: (露出を示すツール名 or UNEXPOSED, 根拠/理由)
    "autorietveld (M7)": (
        "auto_rietveld",
        "実構造 Rietveld。Issue #101 解決: 段階解放レシピの追加段階 (`stages` →"
        "AnalysisInput.extra_stages) と `max_cyc` も ② から到達可能 (`_recipe_spec` 共有ヘルパ)",
    ),
    "joint (M4/FR-240)": ("auto_rietveld", "auto_rietveld(histograms=[...]) で多ヒストグラム=joint"),
    "reference (M6)": ("identify_phases", "相同定 (単相/多相)"),
    "refine_loop (M8)": (
        "propose_next_actions",
        "agentic 閉ループ。Issue #101 解決: `refine_with_revisions` も `stages`/`max_cyc` を受け、"
        "action 適用後に追加段階を末尾へ足せる (既定 GSAS runner `_default_gsas_runner(seed, max_cyc=)`)",
    ),
    "insitu (M9)": (
        "sequential_rietveld",
        "逐次 operando。Issue #114 解決: instrument spec の `recipe` で段階解放レシピを全置換可能 "
        "(`make_gsas_runner(recipe=...)` [#52] への到達; `stages` と違い既定レシピの追加ではなく置換)",
    ),
    "mem (M8-③)": ("mem_density", "MEM 密度→構造改訂"),
    "operando diag (M8-③)": ("check_phase_set", "相集合の完全性"),
    # --- 未露出 (Issue #97): 宣言することで「忘れた」ではなく「既知の穴」であることを示す ---
    "insitu.anchor (M10/FR-330)": (
        "anchored_sequential",
        "Issue #97 解決: run_anchored_sequential(runner=, identifier=) の callable を #93 と同型の "
        "JSON spec で露出した — runner→instrument spec (sequential_rietveld と共有)・identifier→"
        "anchor_table {frame_index: [phase_name]}。crossovers[].total_bic で「BIC 相数抑制」も可視化。"
        "FR-335 結合ゲートは anchor_config.require_bond_validity で有効化し crossovers[].bond_gate "
        "で効きを読む (bic は相数を罰するが増えた相の構造が physical かは見ないため)",
    ),
    "oed (M5/FR-700)": (
        "propose_discriminating_measurements",
        "Issue #104 解決: 僅差競合の判別測定を情報利得順に提案 (非破壊)。session 内の探索結果を "
        "入力に取る session ツール (RankedHypothesis を境界に晒さない)。nested はスコープ外 (#76)",
    ),
    "nested (M5/FR-500)": (
        "discriminate",
        "Issue #76 で物理尤度配線 (2026-07-22) → Issue #130 (route X) で ② 露出済み。"
        "discrimination (FR-313) を実データ GSAS で走らせる discriminate ツールを新設し、"
        "その config.nested_arbitration が nested 物理尤度裁定のオプトイン引数 (裁定力+呼び手が揃った)。"
        "PhaseInstance.structure_ref で実 CIF を GSASIIBackend へ渡す (でっち上げ CIF をやめる)",
    ),
    "chem (FR-412)": (
        "compare_hypotheses",
        "Issue #100 解決: ChemPlausibility 降格を compare_hypotheses の chem_context 引数で配線 "
        "(降格のみ・除外しない = Dara 教訓)。相の組成メタは ③ が同定結果から phase_compositions で供給",
    ),
    "compare_models (XND)": (
        "compare_structure_models",
        "Issue #100 解決: callable 制約が無い (runner 既定=実装関数) 単純配線漏れだった。"
        "variants [{name, phases:[PhaseSpec]}] を JSON で受け BIC/AIC 序列化 (Ow 要否の ΔBIC 判定)",
    ),
    "interop (XND)": (
        "convert_pattern",
        "Issue #108 解決: 外部形式→GSAS 変換を ② 露出 (当初意図的非露出→2026-07-17 方針転換)。"
        "convert_pattern (RIETAN .int / Z-Code Igor TOF → xye/FXYE) + write_instrument_params "
        "(.zDiffractometer → instprm。出力は instrument spec の path へ往復)。numpy-only",
    ),
    # --- 未宣言だった穴 (Issue #99): 宣言リスト自体に載っておらず「忘れ」が再発していた ---
    # これらは既に宣言済みパッケージ (mem/reference) の**内側**の能力、または宣言リストに
    # 完全に欠けていたパッケージ (operando) であり、パッケージ網 (PACKAGE_COVERAGE) だけでは
    # 捕まらない。能力単位で明示宣言することで「既知の穴」に格上げする。
    "mem.mpf (FR-603)": (
        "mem_rietveld_iterate",
        "Issue #100 解決: 実データ MEM-Rietveld 反復 (run_mem_rietveld_gpx) を露出。callable 不要・"
        "全引数 JSON 互換の単純配線漏れだった。ツール呼び出し自体が反復の opt-in (① enabled 既定 "
        "False は安全弁)。子スナップショット gpx (P2) + ledger",
    ),
    "reference.identify_pattern (M11)": (
        "identify_pattern",
        "Issue #100 解決: 単相/多相統一の残差減算反復同定を session ツールとして露出 "
        "(identify_phases と同じ reference_provider 経路)。相数を事前指定せず残差 S/N < 5σ まで"
        "積み上げる。トップレベル __all__ 未 re-export は #105 で別途 (② 到達性には影響なし)",
    ),
    "echem sync (M3/FR-311)": (
        "align_echem",
        "Issue #103 解決: 電気化学同期 (interop.biologic parse_mpr/align_frames) を露出。callable "
        "不要の単純配線漏れだった。mpr_path + 一定ケイデンス (offset_s/interval_s/n_frames) or 明示 "
        "epoch 列 → per-frame の電位/状態 (rest/charge/discharge)。転移点を充放電イベントと突合",
    ),
    "charge-constrained rietveld (FR-318)": (
        "alkali_budget",
        "電気化学制約付き operando Rietveld: クーロメトリー (実測 Q) → per-frame 総アルカリ量 "
        "x_total(t) の表 (alkali_budget) を作り、sequential_rietveld/anchored_sequential の "
        "charge_constraint spec (JSON) へ渡す。診断 (x_XRD vs x_echem)・fix (占有率凍結)・"
        "lock_fractions (相間 EqnConstr)。soft (ChemComp) は GSAS headless バグで縮退 (カナリア有)",
    ),
}


# ===========================================================================
# 粒度⓪: **宣言リスト自体に載っていないパッケージは誰も見ていない** (Issue #99)
# ---------------------------------------------------------------------------
# 上の `LAYER1_FEATURES` は「宣言されたもの」の露出しか見ない。そのため **src/tsumugin に
# パッケージが丸ごと存在するのに宣言表に 1 行も無い**場合、露出テストは緑のまま通る。
# 実際に起きた (Issue #99): `operando` (M3 電気化学; parse_mpr/align_frames) はどの宣言表にも
# 無く、`mem.mpf` (反復 MEM-Rietveld) は `mem` パッケージの内側に隠れ、`identify_pattern` (M11) は
# `reference` の陰に隠れていた — Issue #97 の恒久ガードを入れた後もこの「忘れ」が再発した。
#
# **設計**: 全サブパッケージを列挙し、各々が (a) LAYER1_FEATURES のいずれかの機能の ① 実装元か、
# (b) FOUNDATIONAL (③ に露出する独立能力ではないインフラ) を**明示宣言**することを強制する。
# 新パッケージを足したら本網が fail し、「これは ③ 向け能力か / インフラか」を一度考えさせる。
# パッケージより細かい能力 (`mem.mpf` 等) は網では捕まらないので LAYER1_FEATURES に能力単位で
# 明示宣言する (上記参照) — 網は「丸ごと忘れられたパッケージ」を、明示宣言は「粒度の穴」を塞ぐ。
# ===========================================================================

FOUNDATIONAL = "FOUNDATIONAL"

#: 全 `tsumugin` サブパッケージ → LAYER1_FEATURES のキー or FOUNDATIONAL。
#: **新しいサブパッケージを足したら、ここへ 1 行足すこと** (足さないと下の網羅テストが fail)。
PACKAGE_COVERAGE: dict[str, str] = {
    # --- ③ 向け能力パッケージ (露出/未露出は LAYER1_FEATURES で管理) ---
    "autorietveld": "autorietveld (M7)",
    "joint": "joint (M4/FR-240)",
    "reference": "reference (M6)",
    "refine_loop": "refine_loop (M8)",
    "insitu": "insitu (M9)",  # insitu.anchor (M10) は同パッケージ内の能力として別途宣言
    "mem": "mem (M8-③)",  # mem.mpf (反復) は同パッケージ内の能力として別途宣言
    "chem": "chem (FR-412)",
    "oed": "oed (M5/FR-700)",
    "nested": "nested (M5/FR-500)",
    "interop": "interop (XND)",
    "operando": "echem sync (M3/FR-311)",  # ← Issue #99: これまで宣言リストに 1 行も無かった
    # --- 基盤 (③ に露出する独立能力ではない — 露出済みツールが内部で使うインフラ) ---
    "model": (FOUNDATIONAL, "不変 dataclass 群 (§4)。全層が共有する型であり単独能力ではない"),
    "backends": (FOUNDATIONAL, "RefinementBackend Protocol + Simulated (P7)。精密化の内部境界"),
    "refinement": (FOUNDATIONAL, "段階解放エンジン + ガードレール (FR-200)。autorietveld が内包"),
    "evidence": (FOUNDATIONAL, "BIC/AIC backend (FR-120)。M4 session 系 compare_hypotheses の裏方"),
    "store": (FOUNDATIONAL, "Ledger/Snapshot (P2/NFR-105)。全状態変更の追記基盤"),
    "search": (FOUNDATIONAL, "多仮説木探索 (FR-110)。M4 session 系 submit_analysis の裏方"),
    # ★ accept/revert に加え、**エスカレーション検出 (detect_escalations) も ② から到達する**
    #   (Issue #125 解決)。detect_escalations が走る入口は FinalSelectionEngine.decide() だけでなく
    #   なった: ② accept_hypothesis が委譲する FinalSelectionEngine.accept() 自体がエスカレーション
    #   成立時に Review Queue へ通知するよう修正され、decide() を迂回する経路でも検出結果が
    #   ledger/queue に残る。加えて ② list_hypotheses/accept_hypothesis の応答に "escalations" を
    #   直接含め、② list_review_queue/resolve_review_item で Review Queue 自体も ③ から読める。
    #   FR-403 の 4 条件 (all_high_r/unknown_phase/close_competitor/guard_escalated) は ③ から可視。
    "selection": (FOUNDATIONAL, "最終選択 + エスカレーション (M2)。accept/revert の裏方。"
                  "escalations は ② list_hypotheses/accept_hypothesis の応答・list_review_queue/"
                  "resolve_review_item 経由で ③ から到達可能 (Issue #125 解決)"),
    "sequential": (FOUNDATIONAL, "時系列基盤 (変化点/熱ベースライン, M2)。insitu/parametric が内包"),
    "export": (FOUNDATIONAL, "gpx 書き出し (FR-505)。export_gpx ツールの裏方"),
    "multistart": (FOUNDATIONAL, "マルチスタート大域最適確認 (FR-230)。autorietveld が内包・単独 ② 未露出は M-later"),
    "absorption": (FOUNDATIONAL, "平板透過吸収補正 (FR-317)。refinement/autorietveld が内部適用"),
    "mp": (FOUNDATIONAL, "Materials Project 供給元 (FR-101)。reference/insitu.phaseid が内部利用"),
    "mcp": (FOUNDATIONAL, "これ自体が ② 層。露出する能力ではなく露出する機構"),
    "webui": (FOUNDATIONAL, "WebUI は ③ skill ではなくブラウザ UI の別系統"),
    "workbench": (
        FOUNDATIONAL,
        "操作系デスクトップワークベンチ (GUI, docs/spec/gui-workbench)。webui と同じく③ skill 経由"
        "ではなく直接の operator UI 系統。① Ledger/Snapshot/ReviewQueue/FinalSelectionEngine を直接"
        "束ねる可変セッション + API であり、AUTO モードでも③=LLM は既存② MCP 36 ツールを叩く"
        "(本パッケージ自体は① の新規解析能力を追加しない)",
    ),
    # --- トップレベルモジュール (パッケージではないが ③ 向け能力/インフラを持ちうる) ---
    "pipeline": (FOUNDATIONAL, "単一パターン自動多相精密化 (M0)。submit_analysis の裏方"),
    "errors": (FOUNDATIONAL, "例外型の集約。全層が共有するインフラ"),
}


def test_every_subpackage_is_declared_in_package_coverage():
    """★全 `tsumugin` サブパッケージ + 非私有モジュールが `PACKAGE_COVERAGE` に現れること。

    非トートロジー: 表を grep せず `pkgutil.iter_modules` で実際のサブパッケージとモジュールを
    列挙する。新パッケージ/モジュールを足したら本テストが fail し、「③ 向け能力か / インフラか」
    の宣言を強制する。**これが Issue #99 の核心**: LAYER1_FEATURES/*_FIELDS は「宣言済みのもの」
    しか見ず、`operando` のように**丸ごと載っていない**パッケージは誰も見ていなかった。

    私有モジュール (`_` 始まり、例: `_json`) は内部実装として除外する — ③ 向け能力ではない。
    """
    import tsumugin

    actual = {
        m.name
        for m in pkgutil.iter_modules(tsumugin.__path__)
        if not m.name.startswith("_")
    }
    declared = set(PACKAGE_COVERAGE)
    assert actual == declared, (
        f"tsumugin サブパッケージ/モジュールと PACKAGE_COVERAGE が食い違う。"
        f"未宣言 (③ 向け能力か FOUNDATIONAL か決めること): {sorted(actual - declared)} / "
        f"実在しない宣言 (削除/改名された?): {sorted(declared - actual)}"
    )


def test_package_coverage_values_are_valid():
    """`PACKAGE_COVERAGE` の各値が実在の LAYER1_FEATURES キーか、理由付き FOUNDATIONAL であること。

    LAYER1_FEATURES のキーへ写像する宣言はタイポで無効な機能を指せない (存在確認)。
    FOUNDATIONAL は理由の明示を必須にする (黙ってインフラ扱いにしない = §4.5 規則④-3)。
    """
    for pkg, value in PACKAGE_COVERAGE.items():
        if isinstance(value, tuple):
            marker, why = value
            assert marker == FOUNDATIONAL, (
                f"{pkg}: tuple 宣言のマーカーは FOUNDATIONAL のみ (現在: {marker!r})"
            )
            assert why and len(why) > 15, f"{pkg}: FOUNDATIONAL の理由が書かれていない"
        else:
            assert value in LAYER1_FEATURES, (
                f"{pkg}: LAYER1_FEATURES に無い機能キー {value!r} を指している "
                f"(タイポか、機能宣言の追加漏れ)"
            )


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
# ③ が受け取れるのは Scale (`phase_fractions`) だけだった — 実測で **1.39-1.62 倍誤る**値である。
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
        "**定量相分析の出版値**。`phase_fractions` (Scale) は単位胞質量差で乖離する "
        "(実測 1.39-1.62 倍。フレーム毎に違うので換算係数は無い)",
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
    "atom_multiplicity": (
        UNEXPOSED,
        "意図的 (FR-318): サイト多重度は `insitu.charge` が x = Σ occ·mult/Z の算出と "
        "MobileSiteSpec 照合に消費する ① 内省フィールド。③ が見るのは畳んだ alkali_* "
        "(seq_result_to_dict 経由) であって生の多重度ではない",
    ),
    "atom_occupancy_esd": (
        UNEXPOSED,
        "意図的 (FR-318): 占有率 esd は `insitu.charge.frame_alkali_report` が x_XRD の esd 伝播に"
        "消費する ① 内省フィールド。③ へは alkali_x_xrd_esd として畳んで届く (生の per-atom esd を"
        "単体で出す価値は薄い)。None=未精密化 / >0=共分散由来 の 2 状態 (0.0 捏造なし)",
    ),
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

    実測 K2Mn[Fe(CN)6]: Scale 65.6% は重量分率では 47.2% (この点で **1.39 倍**の誤り;
    乖離はフレーム毎に違い系列全体で 1.39-1.62 倍 = **換算係数は無い**)。③ が Scale しか
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
    # ⚠ 「転移の追跡」は**この行から削除された** (Issue #96 レビュー第4巡 HIGH): 転移推定
    #   (`estimate_transition`) は**絶対レベル 0.50/0.10 の交差軸値**を返すため、Scale か wt% かで
    #   答えが動く = 相対比較ではない。転移は `parametric_fit` の既定 (重量分率基準) で取ること。
    "phase_fractions": (
        "phase_fractions",
        "**Scale**。新相の有意性・張り付き検出など**同一 basis 内の相対比較専用**。"
        "転移推定 (onset/midpoint) には使えない — 絶対レベル交差なので basis で答えが変わる",
    ),
    "phase_names": ("phase_names", "このフレームで有効な相"),
    "changepoint": ("changepoint", "変化点フラグ"),
    "changepoint_reasons": ("changepoint_reasons", "発火した指標"),
    "validity_passed": ("validity_passed", "物理妥当性ゲート"),
    "refine_failed": ("refine_failed", "精密化失敗フレーム"),
    "residual_report": ("residual_report", "残差分解 (① 側で畳んだ小さな報告)"),
    "phase_weight_fractions": (
        "phase_weight_fractions",
        "**定量相分析の出版値** (Scale との乖離は実測 1.39-1.62 倍・フレーム毎に違う)",
    ),
    "phase_weight_fraction_esd": ("phase_weight_fraction_esd", "重量分率 esd (出版に必須)"),
    "cell_esd": ("cell_esd", "格子 esd (出版に必須)"),
    # --- FR-318 電気化学制約の診断 (seq_result_to_dict が同名キーで出力) ---
    "alkali_x_echem": ("alkali_x_echem", "クーロメトリー由来の総アルカリ量目標 x_total(t)"),
    "alkali_x_xrd": ("alkali_x_xrd", "XRD 由来のモル平均アルカリ量 (FW 除算)"),
    "alkali_x_xrd_esd": ("alkali_x_xrd_esd", "x_XRD の esd (None=伝播不能, 0.0 捏造なし)"),
    "alkali_per_phase": ("alkali_per_phase", "相名→精密化占有率由来の xᵢ"),
    "alkali_residual": ("alkali_residual", "x_XRD − x_echem (不可逆容量/副反応の診断量)"),
    "alkali_constraint_applied": ("alkali_constraint_applied", "適用拘束 (''/soft/fix/lock_fractions)"),
    "alkali_feasibility": ("alkali_feasibility", "多相拘束の実行可能性 (infeasible=不可逆容量疑い)"),
    # --- 未露出 (宣言することで「忘れた」ではなく「既知の穴」であることを示す) ---
    "n_obs": (
        UNEXPOSED,
        "意図的: M10 `anchor.select.frame_bic` が相数抑制に使う ① 内省フィールド。anchor は "
        "② 露出済み (anchored_sequential) だが、bic は per-frame の生 n_obs でなく **区間総 bic** "
        "として `crossovers[].total_bic` に畳んで出す (③ が見るのは相数選定結果であって観測点数"
        "そのものではない)。raw n_obs を per-frame で出す価値は薄いので内省フィールドに留める",
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
# 修復後に Scale しか無ければ ③ は「1.39-1.62 倍誤って報告する」(skills/operando-diagnose の禁止事項)
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
    "tsumugin.mcp.compare_tools.compare_structure_models": (
        DIAGNOSTIC_ONLY,
        "意図的: scores[].phase_fractions は**モデル毎** (per-frame ではない) の Scale で、どの相集合で"
        "どのモデルが勝ったかの**文脈**。本ツールの決定値は BIC/delta_bic であって分率ではない。"
        "定量相分析 (wt% ± esd) が要るなら、選ばれた best モデルを auto_rietveld で精密化し直す "
        "(そちらは phase_weight_fractions を CARRIES_PUBLICATION として運ぶ)。モデル比較の出力に "
        "wt% を混ぜると『どのモデルの wt% か』が曖昧になり、確定前の値を出版値と取り違えさせる",
    ),
    "tsumugin.mcp.operando_diag_tools.check_phase_set": (
        DIAGNOSTIC_ONLY,
        "意図的: seed_pinned_frames/frozen_fraction_frames が返す分率は **Scale であることに意味が"
        "ある指紋** (等分 seed 1/n との厳密一致 / 直前フレームとの厳密一致で張り付きを検出する)。"
        "重量分率に換算すると 1/n との一致が壊れて検出器そのものが成立しない。加えて**flag された"
        "フレームは定義上壊れており出版対象ではない** (だから repair_frames へ送る)。"
        "出力は `fraction_basis='scale'` で label してある (下の消費者ネット参照)。"
        "なお入力の系列 dict を `_result_from_dict` で復元する経路であり、往復で **esd** "
        "(phase_weight_fraction_esd/cell_esd) は落ちる — 出版値が要るなら sequential_rietveld / "
        "repair_frames の出力を直接読むこと",
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

#: 監査対象キー (per-frame 相分率 = Scale)。
_FRACTION_KEY_NAME = "phase_fractions"

#: 系列結果 dict → `SequentialRietveldResult` の**唯一の入口**。これを呼ぶ関数は per-frame
#: 相分率を**消費する** (下の消費者ネットの捕捉条件)。
_DESERIALIZER_NAME = "_result_from_dict"


def _source_ast(func: Callable) -> ast.AST | None:
    """関数の source を AST へ (取得不能なら None)。"""
    try:
        src = textwrap.dedent(inspect.getsource(func))
    except OSError:  # pragma: no cover - 動的定義の保険
        return None
    return ast.parse(src)


def _iter_mcp_functions() -> Iterator[tuple[str, Callable, ast.AST]]:
    """`tsumugin.mcp` 配下 (**サブパッケージ・クラス本体含む**) の全関数 → (完全名, 関数, AST)。

    `iter_modules` でなく `walk_packages` を使う: 前者はサブパッケージへ再帰せず、`mcp` に
    サブパッケージが追加された途端に**網が黙って穴だらけになる** (現状 mcp はフラットなので
    実害は無いが、網の穴は「無いこと」が保証されて初めて網である)。

    **クラス本体も走査する** (第4巡 LOW): 旧実装は `vars(module)` の `inspect.isfunction` だけを
    見ており、`inspect.isfunction(SomeClass)` は False なので**クラスのメソッドは 1 つも
    列挙されなかった**。`tsumugin.mcp` に相分率を直列化するクラス (シリアライザ等) が生まれた
    瞬間、両方の網が黙って外れる。現状クラスメソッドの直列化点は無いが、それは**列挙した上で
    無い**のであって、見ていないから無いのではない。

    関数オブジェクト自体も返す: 消費者ネットが `_result_from_dict` を**名前でなく実体で**
    解決する (`__globals__` を引く) ために要る。
    """
    for mod_info in pkgutil.walk_packages(mcp_pkg.__path__, f"{mcp_pkg.__name__}."):
        module = importlib.import_module(mod_info.name)
        for name, obj in vars(module).items():
            if inspect.isclass(obj) and obj.__module__ == module.__name__:
                for meth_name, raw in vars(obj).items():
                    func = raw.__func__ if isinstance(raw, (classmethod, staticmethod)) else raw
                    if not inspect.isfunction(func):
                        continue
                    func = inspect.unwrap(func)  # デコレータ (@degrade_oserror 等) を貫通
                    tree = _source_ast(func)
                    if tree is not None:
                        yield f"{module.__name__}.{name}.{meth_name}", func, tree
                continue
            if not inspect.isfunction(obj) or obj.__module__ != module.__name__:
                continue
            # 【デコレータ貫通 (Issue #94)】: @degrade_oserror でラップされた実行系ツールは、
            #   getsource/__globals__ が wrapper (別モジュール) を指すため、unwrap しないと
            #   emitter/consumer 網から**黙って消える** (repair_frames が phase_fractions を出す・
            #   _result_from_dict を呼ぶ事実が見えなくなる)。unwrap で元関数の source と globals を見る。
            unwrapped = inspect.unwrap(obj)
            tree = _source_ast(unwrapped)
            if tree is not None:
                yield f"{module.__name__}.{name}", unwrapped, tree


def _emits_fraction_key(tree: ast.AST) -> bool:
    """dict のキーとして `phase_fractions` を**書き出している**か (AST 判定)。

    **正規表現をやめた理由** (第4巡 LOW): 旧実装の `r'"phase_fractions"\\s*:'` は dict リテラル中の
    キーしか見ておらず、``d["phase_fractions"] = ...`` の添字代入・キー定数・別クォート・
    行折り返しを**取りこぼす**。現行の 3 emitter が全てリテラル形なので実害は無かったが、
    「たまたま今の書き方に一致していただけ」の網であり、書き方を変えた瞬間に黙って外れる。

    AST なら**構文の形**で捕まえられる (書式・クォート・改行に非依存):
      (a) dict リテラルのキー   : ``{"phase_fractions": ...}``
      (b) 添字代入のターゲット  : ``d["phase_fractions"] = ...``
    ``fd.get("phase_fractions")`` (復元側の**読み取り**) や docstring 中の言及は**拾わない** —
    これらは直列化点ではないため (この区別は旧正規表現も意図して行っていた)。
    """
    for node in ast.walk(tree):
        # (a) dict リテラルのキー
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == _FRACTION_KEY_NAME:
                    return True
        # (b) 添字代入 (`d["phase_fractions"] = ...` / `d["phase_fractions"] += ...`)
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == _FRACTION_KEY_NAME
            ):
                return True
    return False


def _fraction_emitting_functions() -> dict[str, ast.AST]:
    """`tsumugin.mcp` 配下で per-frame 相分率を**直列化している**関数 → その AST。

    **ツール関数の source だけを見ない**: `sequential_rietveld` は `seq_result_to_dict` へ委譲する
    ため、ツール単位の grep では**素通りする** (実際に落ちた 3 経路のうち 1 つがこの形)。
    パッケージ内の全関数を走査して**直列化点そのもの**を捕まえる。
    """
    return {name: tree for name, _f, tree in _iter_mcp_functions() if _emits_fraction_key(tree)}


def _calls_the_series_deserializer(func: Callable, tree: ast.AST) -> bool:
    """`_result_from_dict` の呼び出しが **`insitu_tools` の実体**かを識別子解決で確かめる。

    **名前一致では足りない** (第4巡 LOW): `rietveld_tools` は**同名だが別物**の
    `_result_from_dict` (`AutoRietveldResult` を復元し、相分率を 1 つも読まない) を定義している。
    旧実装は `_calls(tree, "_result_from_dict")` と**名前だけ**を見ていたため、
    `propose_next_actions` を「per-frame 相分率の消費者」として捕まえていた — **偽陽性**である。
    その結果、宣言表に「相分率から数字を導出しない」という**空虚に真な**行が生まれ、
    そのカテゴリを**もっともらしく**見せてしまった (同じカテゴリを使った他の 2 行は偽だった)。
    網が「消費者」と言う以上、消費者だけを捕まえること。
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == _DESERIALIZER_NAME:
            if func.__globals__.get(_DESERIALIZER_NAME) is _series_deserializer:
                return True
        elif isinstance(f, ast.Attribute) and f.attr == _DESERIALIZER_NAME:
            # `mod._result_from_dict(...)` 形。モジュール別名までは解決しないので**安全側**
            # (消費者とみなす) に倒す — 見落とすより余分に宣言させる方が安い。
            return True
    return False


def _fraction_consuming_functions() -> dict[str, ast.AST]:
    """`tsumugin.mcp` 配下で系列結果を**復元する** (= per-frame 相分率を消費する) 関数 → その AST。

    **なぜ emitter ネットでは足りないか** (第4巡 HIGH): emitter ネットは
    ``"phase_fractions":`` を**再送出する**表面しか見つけない。`parametric_fit` は相分率を
    **消費して** onset/midpoint という**別の数字を導出**する — 自身のソースに
    `phase_fractions` は 1 度も現れず (`_result_from_dict` → `analyze_phase` へ委譲するだけ)、
    emitter ネットからは**完全に不可視**だった (実測: discovered? False)。
    そして導出される onset/midpoint こそが**論文に載る数字**である。

    捕捉条件は「**`insitu_tools._result_from_dict` の実体**を呼ぶこと」: 系列結果 dict を
    `SequentialRietveldResult` に戻す唯一の入口であり、相分率を消費する ② の関数は必ずここを
    通る。名前ベースの grep と違い、**委譲の先で読んでいても捕まる**。

    **網の限界 (正直に言う。第4巡 LOW で旧注記の誤りが判明した)**:

    (i) **`frames` を復元せず直接読む純粋な reader/deriver は両方の網をすり抜ける**。
        `fd["phase_fractions"]` を読んで midpoint を返すだけの関数は、`_result_from_dict` を
        呼ばないので本ネットに掛からず、`phase_fractions` を**書き出さない**ので emitter ネット
        (dict リテラルのキー / 添字**代入**) にも掛からない。旧注記は「emitter ネット側で
        捕まる」と書いていたが**偽**である — emitter ネットは書き出し位置しか見ておらず、
        読み取り (`.get(...)` / 添字ロード) は意図的に除外している。
    (ii) `tsumugin.mcp` の**外**に導出ロジックを置き、その結果だけを ② が返す形も、どちらの網
        にも掛からない (① 側の全 API を静的に追う call-graph 解析が要る)。

    どちらも机上の穴だが、**塞いでいないことを明示する**。実際の防御は網より手前にある:
    ① の `fraction_series` が basis を必須にし `FractionBasisUnavailableError` を投げるため、
    Scale への暗黙フォールバックは**型と例外で**不可能である。加えて下の basis 宣言テストは
    **ツールを実際に呼んで `fraction_basis` を読む**ので、導出経路がどこにあっても
    「basis を label しない ② 出力」は落ちる。

    (旧版で挙げていた「クラスメソッドが列挙から漏れる」は `_iter_mcp_functions` がクラス本体を
    走査するようになったため**解消済**。)
    """
    return {
        name: tree
        for name, func, tree in _iter_mcp_functions()
        if _calls_the_series_deserializer(func, tree)
    }


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


def test_the_ast_net_reaches_class_methods():
    """★網がクラス本体のメソッドまで届くこと (第4巡 LOW: 旧実装は module 直下の関数しか見ず)。

    `inspect.isfunction(SomeClass)` は False なので、旧 `_iter_mcp_functions` は**クラスの
    メソッドを 1 つも列挙しなかった**。`tsumugin.mcp` に相分率を直列化するクラス (シリアライザ等)
    が生まれた瞬間、emitter/consumer 両方の網が黙って外れる。

    **「今は該当クラスが無いから緑」を証拠にしない**: それは網を検査していないのと同じである
    (`tsumugin.mcp` の唯一のクラス `AnalysisSession` は dataclass 生成メソッドしか持たず
    `inspect.getsource` が OSError になるため、実在クラスでは網の到達を観測できない)。
    よって**合成のクラスを実際に mcp モジュールへ注入して**、網が捕まえることを確かめる。
    変異検査で実証済: `_iter_mcp_functions` からクラス走査を外すと本テストが fail する。
    """
    import tsumugin.mcp.insitu_tools as target

    class _CoverageProbeEmitter:
        def to_dict(self) -> dict[str, object]:
            return {"phase_fractions": {"probe": 1.0}}

    _CoverageProbeEmitter.__module__ = target.__name__
    setattr(target, "_CoverageProbeEmitter", _CoverageProbeEmitter)
    try:
        found = _fraction_emitting_functions()
    finally:
        delattr(target, "_CoverageProbeEmitter")

    assert f"{target.__name__}._CoverageProbeEmitter.to_dict" in found, (
        "クラス本体のメソッドが網に掛かっていない — module 直下の関数しか見ていないため、"
        "相分率を直列化するクラスが ② に入っても宣言を強制できない (網の穴は「無いこと」が"
        f"保証されて初めて網である)。実際に見えている直列化点: {sorted(found)}"
    )


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
        f"未宣言 (出版値も返すか決めること — Scale だけ返すと ③ は 1.39-1.62 倍誤る): "
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
                f"報告する定量値が 1.39-1.62 倍誤る (実測 K2Mn[Fe(CN)6]): {sorted(entry)}"
            )
            assert entry[key], (
                f"{emitter}: {key!r} が空 — プローブは値を持つ結果を渡しているので、"
                f"① → ② のどこかで落ちている (空 dict は「値が得られなかった」の意味であり、"
                f"値がある精密化で空になってはならない)"
            )


# ===========================================================================
# 粒度④: **相分率を消費する ② は「どの basis で判断したか」を出力に label する**
# ---------------------------------------------------------------------------
# 【第4巡 HIGH】上の emitter ネットは `phase_fractions` を **再送出する**表面しか見つけない。
# 第1〜3巡は「Scale を再送出する ② 表面」を全て監査したが、**Scale から出版値を導出する**表面
# (`parametric_fit` → 転移 onset/midpoint) を誰も見なかった。`estimate_transition` が返すのは
# 「曲線が**絶対レベル** 0.50 / 0.10 を横切る軸値」であり、y 軸が Scale か wt% かで**答えが動く**
# (実測 K2Mn[Fe(CN)6] tetra 充電域: 同じ精密化から Scale は「midpoint 9.515 h」を、wt% は
# 「**転移なし**」を出した。midpoint と呼んでいた点は実際には **34.0 wt%**)。
# 「Scale は相対比較なら安全」は**偽**である — 転移推定は相対比較ではない。
#
# 【第5巡 HIGH — 本節を作り直した理由】第4巡の網は消費者 4 つを**全て捕まえた**。それでも失敗した:
# 網が捕まえた後に人が書いた宣言が**事実に反していた**のに、ガードは「文字列が 20 字超」かつ
# 「『意図的』か『Issue #』を含む」しか見ておらず、**偽の理由を真の理由と区別できなかった**。
#
#   - `repair_frames`: 「相分率からは数字を導出しない (不連続の検出は Rwp/格子で行う)」→ **両方偽**。
#     `detect_discontinuities` の 3 基準の 1 つは `fraction_deviation` で **`phase_fractions`
#     (Scale) から発火**し、**格子基準は存在しない**。Rwp とセルを固定した系列で Scale
#     `[0.10,0.12,0.45,0.16,0.18]` は 3 フレームを、同じ系列の wt% は 1 フレームを選ぶ —
#     再精密化されるフレーム**集合**は ledger に残る状態変化であり、basis 依存である。
#   - `check_phase_set`: 「返すのは flag されたフレーム番号であって出版値ではない」→ 偽。
#     `phases: [{phase, turning_points, flagged, reason}]` を返す。`min_amplitude=0.1` は
#     **絶対**振幅フィルタなので、cubic Scale 0.02↔0.11 (振幅 0.09 < 0.1 ⇒ flagged=False) は
#     同じ系列の wt% では 0.042↔0.209 (振幅 0.167 ⇒ turning_points=5, flagged=True) になる。
#     `skills/operando-diagnose` は `flagged=True` を J7 のトリガにしているので、`flagged=False`
#     は ③ が**疑うのをやめる**許可である = CLAUDE.md が最悪と呼ぶ失敗様態。
#
# **逃げ口が検証されない散文であるガードは、現在の書式にしか一致しない正規表現と同じ欠陥**である。
#
# 【設計】「導出しない」という**逃げ口を廃止**した。系列の相分率を消費する ② は例外なく
#   (a) **どの basis で判断/導出したかを宣言し**、(b) **その basis を出力に label する**。
#   宣言は**実際にツールを呼んで `fraction_basis` を読む**ことで検証する (下の
#   `test_fraction_consumers_label_their_output_with_the_declared_basis`)。散文は「なぜその
#   basis が正しいか」を書く場所として残すが、**通過条件からは外す** — 散文は嘘をつけるが、
#   ツールの出力は嘘をつけない。
# ===========================================================================

#: 相分率の基準として宣言してよい値 (① `insitu.model.FractionBasis` と同じ語彙)。
_VALID_BASES = ("scale", "weight")

#: 系列結果を復元する (= per-frame 相分率を消費する) ② 関数 → (**既定の** basis, その basis が
#: 正しい理由)。basis は `_VALID_BASES` のいずれかで、**「使わない」という選択肢は無い**。
#: 選択可能な引数を持つツール (`parametric_fit(basis=)`) は **既定値**を宣言する — ② は JSON しか
#: 送れない LLM (③) が呼ぶ表面であり、既定がそのまま ③ にとっての実質的な振る舞いになる (§4.5)。
#: **`tsumugin.mcp` に新しい消費者を作ったら、ここへ 1 行足すこと** (足さないと網羅テストが fail)。
PER_FRAME_FRACTION_CONSUMERS: dict[str, tuple[str, str]] = {
    "tsumugin.mcp.insitu_tools.parametric_fit": (
        "weight",
        "相分率系列から転移 onset/midpoint±σ を**導出する** = 論文に載る数字を作る表面。"
        "`estimate_transition` は絶対レベル 0.50/0.10 の交差軸値を返すため basis で答えが変わる。"
        "**出版値は重量分率**なので既定は 'weight'。`basis='scale'` は明示要求時のみの診断用で、"
        "重量分率が無ければ error dict (Scale へも「転移なし」へも縮退しない)",
    ),
    "tsumugin.mcp.operando_diag_tools.check_phase_set": (
        "scale",
        "**Scale が正しい basis である** (第5巡で「導出しない」という偽の宣言から訂正): "
        "(a) J7 の病理は「計量の近い相が互いの**強度**を吸収し合う」ことであり、振動するのは"
        "その相へ割り付けられた散乱寄与 = Scale そのもの。wt% は Scale×単位胞質量の派生量で"
        "あって検出対象ではない。(b) `seed_pinned`/`fractions_frozen` は「等分 seed (1/n) との"
        "**厳密一致**」が指紋なので、wt% へ換算すると**検出器そのものが成立しない**。"
        "(c) 重量分率は共分散の無い精密化では空で、判定不能な系列が大量に出る。"
        "⚠ ただし `min_amplitude` は **Scale 単位の絶対閾値**であり、等価な wt% 感度は相の"
        "単位胞質量と分率レベルで変わる (重い相が低 Scale 域にあると wt% 振幅は最大で質量比倍)。"
        "よって `flagged=False` は「Scale 振幅が閾値未満」であって「相量が動いていない」では"
        "ない — ② は `phases[].fractions` に**判定した系列そのもの**を返し、③ が閾値際を"
        "見直せるようにしてある",
    ),
    "tsumugin.mcp.operando_diag_tools.repair_frames": (
        "scale",
        "**Scale が正しい basis である** (第5巡で「Rwp/格子で検出する」という偽の宣言から訂正 — "
        "`detect_discontinuities` の 3 基準は rwp_abs/rwp_local_median/**fraction_deviation** で"
        "あり、格子基準は存在しない): (a) 検出したいのは「そのフレームの**精密化**が近傍と食い違う "
        "(局所解にトラップされた)」ことで、Scale は GSAS が実際に動かすパラメータそのもの。"
        "(b) 修復側 `repair_isolated` は近傍の **Scale** を warm-start の種として GSAS へ戻す "
        "(`_warmstart.seed_fractions`) ため、**検出器と作動器が同じ座標で喋る**必要がある。"
        "(c) 重量分率は共分散の無い精密化では空で、wt% 基準の検出器は定義できない系列が多い。"
        "⚠ `frac_delta` は Scale 単位の絶対閾値であり、**再精密化されるフレーム集合は basis 依存** "
        "(ledger に残る状態変化)。修復後の**出版値**は `repairs[].phase_weight_fractions` で"
        "別途返す — その経路は上の PER_FRAME_FRACTION_EMITTERS 側で CARRIES_PUBLICATION として"
        "監査済み (`fraction_basis` は**検出**基準のラベルであって出版値には掛からない)",
    ),
}

#: 宣言した basis を**実物で**確かめるプローブ (grep でなく実際の出力の `fraction_basis` を読む)。
_FRACTION_CONSUMER_PROBES: dict[str, Callable[[], Mapping[str, object]]] = {
    # 既定呼び出し (basis 未指定) を見る: ③ にとっての実質的な振る舞いは既定である。
    "tsumugin.mcp.insitu_tools.parametric_fit": lambda: parametric_fit(
        _divergent_series_dict(), "tetra"
    ),
    "tsumugin.mcp.operando_diag_tools.check_phase_set": lambda: check_phase_set(
        _divergent_series_dict()
    ),
    "tsumugin.mcp.operando_diag_tools.repair_frames": _probe_repair_frames,  # type: ignore[dict-item]
}


def test_every_layer2_fraction_consumer_is_declared():
    """★系列結果を復元する**全ての** ② 関数が「どの basis で判断するか」を宣言していること。

    emitter ネット (`"phase_fractions":` の再送出) では `parametric_fit` は**捕まらなかった**
    — 自身のソースに `phase_fractions` が 1 度も現れないためである。しかしそれが出版値
    (転移温度) を作っていた。**再送出だけでなく消費を監査する**のがこの網の役目。
    """
    actual = set(_fraction_consuming_functions())
    declared = set(PER_FRAME_FRACTION_CONSUMERS)
    assert actual == declared, (
        f"② の per-frame 相分率 消費者と宣言が食い違う。"
        f"未宣言 (どの basis で判断するか決め、出力に fraction_basis を label すること — "
        f"basis を言わない分率由来の判断は ③ から検算できない): {sorted(actual - declared)} / "
        f"実在しない宣言 (削除/改名された?): {sorted(declared - actual)}"
    )


def test_fraction_consumer_basis_declarations_use_the_known_vocabulary():
    """宣言された basis が ① の `FractionBasis` 語彙であること (「導出しない」等の逃げ口を作らない)。

    第4巡はここに `NO_FRACTION_DERIVED_NUMBER` という逃げ口があり、その中身が**散文でしか
    検証されていなかった**ため、2 件の偽の宣言が緑のまま通った。語彙を閉じることで、
    下の振る舞いテスト (実際に `fraction_basis` を読む) を**全消費者に強制**する。
    """
    for consumer, (basis, why) in PER_FRAME_FRACTION_CONSUMERS.items():
        assert basis in _VALID_BASES, (
            f"{consumer}: basis 宣言 {basis!r} は {_VALID_BASES} のいずれかであること。"
            "「相分率から数字を導出しない」類の宣言は**廃止**した — 検証できない散文だったため、"
            "実際には導出/判断していた 2 件を通してしまった (第5巡 HIGH)"
        )
        assert why and len(why) > 20, f"{consumer}: その basis が正しい理由が書かれていない"


def test_every_fraction_consumer_is_probed():
    """全消費者に**実物プローブ**があること (宣言だけで緑にしない)。

    プローブが無ければ下の振る舞いテストはその消費者を黙って飛ばす = 宣言が実質無検査になる
    (`test_publication_carrying_emitters_are_all_probed` と同じ規律)。
    """
    assert set(PER_FRAME_FRACTION_CONSUMERS) == set(_FRACTION_CONSUMER_PROBES), (
        f"プローブ未整備: {sorted(set(PER_FRAME_FRACTION_CONSUMERS) - set(_FRACTION_CONSUMER_PROBES))} / "
        f"宣言に無いプローブ: {sorted(set(_FRACTION_CONSUMER_PROBES) - set(PER_FRAME_FRACTION_CONSUMERS))}"
    )


@pytest.mark.parametrize("consumer", sorted(_FRACTION_CONSUMER_PROBES))
def test_fraction_consumers_label_their_output_with_the_declared_basis(consumer):
    """★相分率を消費する ② は、**実際の出力**に宣言どおりの `fraction_basis` を載せること。

    **非トートロジー**: 散文を読まず、実際にツールを呼んで出力 dict の `fraction_basis` を見る。
    宣言を書き換えても、`fraction_basis` の直列化を落としても、値を変えても fail する
    (3 通りとも変異で実証済)。

    **これが第5巡 HIGH の核心**: 第4巡のガードは宣言の**文字列長と「意図的」の有無**しか見て
    いなかったため、`repair_frames`/`check_phase_set` の**事実に反する**宣言を素通りさせた。
    散文は嘘をつけるが、ツールの出力は嘘をつけない。basis を label させることで、
    ③ は「この数字はどちらの基準か」を**必ず**受け取る (§4.5 到達可能性の裏返し:
    ① が知っていて ② が言わない事実は、③ にとって存在しない)。
    """
    declared_basis, why = PER_FRAME_FRACTION_CONSUMERS[consumer]
    out = _FRACTION_CONSUMER_PROBES[consumer]()

    assert isinstance(out, Mapping) and "error" not in out, (
        f"{consumer}: プローブが error/非 dict を返した (プローブが陳腐化している): {out!r}"
    )
    assert "fraction_basis" in out, (
        f"{consumer}: 出力に `fraction_basis` が無い。相分率から判断/導出する ② は、その判断が"
        f"どちらの基準か **③ に言わなければならない** (basis で答えが変わるため)。宣言: {why}"
    )
    assert out["fraction_basis"] == declared_basis, (
        f"{consumer}: 宣言 basis={declared_basis!r} だが実際の出力は "
        f"{out['fraction_basis']!r} — 宣言が実態から遅れている (どちらかが誤り)"
    )


def _divergent_series_dict() -> dict:
    """★Scale と wt% で**答えが変わる**系列 (実測 K2Mn[Fe(CN)6] tetra fr96-126 の縮図)。

    Scale 0→0.656 は 0.50 を横切る (→ midpoint が出る) が、同じ fit の wt% は 0→0.472 で
    横切らない (→ 転移なし)。**両者が一致する系列でテストしても basis の取り違えは検出できない**。
    """
    rows = [(0.0, 0.0, 0.0), (1.0, 0.30, 0.19), (2.0, 0.50, 0.34), (3.0, 0.656, 0.472)]
    frames = tuple(
        FrameRietveldResult(
            frame_index=i, axis_value=ax, data_path=f"f{i}.xrdml", rwp=8.0, gof=1.0,
            refined_cells={"tetra": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
            phase_fractions={"tetra": s}, phase_names=("tetra",),
            phase_weight_fractions={"tetra": w}, phase_weight_fraction_esd={"tetra": 0.006},
            cell_esd={"tetra": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
        )
        for i, (ax, s, w) in enumerate(rows)
    )
    return seq_result_to_dict(SequentialRietveldResult(frames=frames, phase_names=("tetra",)))


def test_fraction_deriving_consumers_default_to_the_publication_basis():
    """★相分率から数字を導出する ② は、**既定で重量分率**を使い basis を明示すること。

    非トートロジー: Scale と wt% で答えが変わる系列を実際に流し、**どちらの答えが返るか**で
    判定する。`parametric_fit` の既定を "scale" に戻せば fail する (実証済)。

    既定が Scale だと ③ は「出版できる転移温度」だと信じて Scale 由来の数字を受け取る —
    それが本 HIGH の実害そのものである (skills/insitu が `parametric_fit` の onset/midpoint を
    「報告せよ」と ③ に指示している)。
    """
    assert PER_FRAME_FRACTION_CONSUMERS["tsumugin.mcp.insitu_tools.parametric_fit"][0] == "weight"
    seq = _divergent_series_dict()

    out = parametric_fit(seq, "tetra")
    assert out["fraction_basis"] == "weight", (
        "既定が重量分率でない — ③ は Scale 由来の転移温度を出版値と信じて報告する"
    )
    assert out["transition"] is None, (
        "既定で Scale 由来の midpoint が返っている (wt% は 0.50 に到達しないので転移なしが正)"
    )

    scale_out = parametric_fit(seq, "tetra", basis="scale")
    assert scale_out["fraction_basis"] == "scale"  # 明示要求時は Scale 由来と**明記**する
    assert scale_out["transition"]["midpoint"] == pytest.approx(2.0, abs=1e-6)


def test_fraction_deriving_consumers_never_silently_fall_back_to_scale():
    """★重量分率が無いとき、Scale へ**黙って落ちない**こと (落ちたらこのバグの再来)。

    「転移なし」を返すのも禁止 — 本物の「転移なし」と区別が付かない静かな嘘になる。
    ② は例外を送出しない契約なので error dict へ縮退する。
    """
    frames = tuple(
        FrameRietveldResult(
            frame_index=i, axis_value=float(i), data_path=f"f{i}.xrdml", rwp=8.0, gof=1.0,
            refined_cells={"tetra": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
            phase_fractions={"tetra": 0.3 * i}, phase_names=("tetra",),
        )
        for i in range(4)
    )
    seq = seq_result_to_dict(SequentialRietveldResult(frames=frames, phase_names=("tetra",)))

    out = parametric_fit(seq, "tetra")
    assert out.get("error_type") == "FractionBasisUnavailableError", (
        f"重量分率が無いのに数字が返っている (Scale へ落ちた?): {sorted(out)}"
    )
    assert "transition" not in out


# ===========================================================================
# 粒度⑤: **basis 依存なのは出力だけではない — ② の *入力* 閾値も basis を持つ**
# ---------------------------------------------------------------------------
# 【第5巡 MEDIUM】粒度④ の 2 つの網 (emitter / consumer) は**系列 dict を再送出・消費する**表面を
# 監査する。しかし `sequential_rietveld` はどちらの網にも掛からない — 受け取った閾値は ① の中で
# **live な GSAS Scale と直接**比較され、系列 dict を一度も経由しないためである。構造的に不可視。
#
#   - `instrument["auto_freeze_minor_cells"]` → `autorietveld.engine._should_refine_cell`
#     (`_phase_fraction_map` = 「先頭ヒストグラムの HAP **Scale**、和=1 正規化」と比較)。
#   - `phase_id["frac_min"]` → `insitu.engine._accept_new_phase` (`res.phase_fractions` = 同上)。
#
# **答えは basis で割れる**: 実測 K₂Mn[Fe(CN)₆] (cubic 1103.4 / tetra 517.8 amu) で
# `Scale {cubic .75, tetra .25}` は `wt% {cubic .865, tetra .135}`。文書化されている 0.2 は
# **Scale なら tetra を解放し、wt% なら凍結する**。同じ ③ ドキュメントが「本当の分率は wt%」
# 「Scale を wt% として報告するな」と教えているので、③ が「tetra は 13.5 wt% の少数相だから 0.15」
# と考えると**実際には Scale 0.15 を設定し tetra のセルは解放されたまま** = #80 の発散が進む。
# **これが F1 の原因でもある**: label されていない Scale 閾値が「どの相のセルが esd 無しになるか」
# を決めている。
#
# 【網の設計と限界 — 正直に言う】
#   (a) **できる**: ② の JSON spec dict (`instrument` / `phase_id`) が読むキーを AST で**発見**し、
#       basis の宣言を強制する。③ のツマミはこの 2 つの spec に集中しているので、新しい閾値が
#       spec に入れば必ずここに掛かる。宣言した basis 依存キーには ② docstring と ③ 3 文書での
#       label を実際のテキストで確かめる。
#   (b) **できない**: 「この float が ① で分率と比較されるか」の**自動判定**。比較は ②→① の
#       関数境界をまたぐ (`_apply_stage` → `_should_refine_cell(info, fraction, threshold)` は
#       Compare ではなく Call) ため、健全に解くには call-graph 解析が要る。名前ヒューリスティクス
#       (`*frac*` 等) は**現在の綴りにしか一致しない網** = このファイルが既に 2 度捨てた欠陥なので
#       採らない。よって「新しい spec キーが basis 依存か否か」の判断は人間が宣言する。
#   (c) **できない**: ツールの kwarg として直接足された閾値 (spec dict の外)。現状 0 件。
#
#   加えて**振る舞い側の固定**として `tests/autorietveld/test_auto_freeze.py` に
#   `test_documented_threshold_compares_scale_not_weight_fraction` を置き、実測の Scale/wt% ペアで
#   「0.2 が tetra を解放する (= Scale 基準)」を pin してある。宣言と実装が割れたらそちらが落ちる。
# ===========================================================================

#: 分率 basis を持たない入力 (装置設定・探索設定など)。
BASIS_FREE = "BASIS_FREE"

#: ② の JSON spec dict が読むキー → (basis or BASIS_FREE, 理由)。
#: **`instrument` / `phase_id` spec にキーを足したら、ここへ 1 行足すこと** (足さないと網羅テストが fail)。
SPEC_INPUT_BASIS: dict[str, tuple[str, str]] = {
    # --- instrument spec (`_runner_from_instrument` / `_instrument_path_resolver`) ---
    "instrument.auto_freeze_minor_cells": (
        "scale",
        "① `autorietveld.engine._should_refine_cell` が `_phase_fraction_map` (先頭ヒストグラムの "
        "HAP **Scale**・和=1 正規化) と比較する。wt% ではない: 実測 Scale{cubic .75,tetra .25} = "
        "wt%{cubic .865,tetra .135} なので閾値 0.2 は **Scale なら tetra を解放・wt% なら凍結** = "
        "答えが basis で割れる。Scale が正しい basis である — 凍結したいのは「計量が近い相同士の"
        "相関でセルが発散する」相であり、相関の強さは GSAS が実際に動かすパラメータ (Scale) の"
        "大きさで決まる (質量は無関係)",
    ),
    "instrument.path": (BASIS_FREE, "instprm ファイルパス (系列共通)。相分率と比較しない"),
    "instrument.paths": (BASIS_FREE, "instprm パス列 (frames と 1:1)。相分率と比較しない"),
    "instrument.radiation": (BASIS_FREE, "放射源 (Radiation enum の値)。相分率と比較しない"),
    "instrument.geometry": (BASIS_FREE, "測定幾何 (Geometry enum の値)。相分率と比較しない"),
    "instrument.max_cyc": (BASIS_FREE, "各段階の最大精密化サイクル数 (int)。相分率と比較しない"),
    "instrument.background_coeffs": (
        BASIS_FREE, "Chebyshev 背景項数 (int)。相分率と比較しない"
    ),
    "instrument.recipe": (
        BASIS_FREE,
        "Issue #114: 段階解放レシピの全置換 (`RefinementStage` の JSON 列, `_recipe_spec` 経由で "
        "make_gsas_runner(recipe=...) [Issue #52] へ渡す)。GSAS 解放フラグの宣言的記述であり "
        "相分率とは比較しない",
    ),
    # --- phase_id spec (`sequential_rietveld`) ---
    "phase_id.frac_min": (
        "scale",
        "① `insitu.engine._accept_new_phase` が `AutoRietveldResult.phase_fractions` (**Scale**) と"
        "比較する新相採用の下限。wt% ではない — 質量の重い相ほど Scale は wt% より小さく出るため、"
        "wt% の直感で決めた下限は同じ精密化で別の答えを出す。Scale が正しい basis である: 新相が"
        "「残差を説明しているか」の問いであり、説明しているのは散乱寄与 = Scale そのもの "
        "(重量分率は Scale×単位胞質量の派生量)。加えて重量分率は共分散の無い精密化では空で、"
        "wt% 基準の受理判定は定義できない試行が多い",
    ),
    "phase_id.elements": (BASIS_FREE, "相同定に許す元素系 (元素記号の列)。相分率と比較しない"),
    "phase_id.rwp_eps": (
        BASIS_FREE, "新相採用に要する最小 Rwp 改善 (%ポイント)。Rwp 基準であり相分率と比較しない"
    ),
    "phase_id.top_k": (BASIS_FREE, "各変化点で試す候補相の数 (int)。相分率と比較しない"),
    "phase_id.hull_cutoff_ev": (
        BASIS_FREE, "MP 安定性フィルタ (energy above hull, eV/atom)。相分率と比較しない"
    ),
    "phase_id.subtract_bg": (BASIS_FREE, "同定前の背景減算フラグ (bool)。相分率と比較しない"),
    "phase_id.trigger_rwp_ratio": (
        BASIS_FREE, "同定を起動する Rwp 比。Rwp 基準であり相分率と比較しない"
    ),
}

#: spec 名 → (spec dict を受ける変数名, その dict からキーを**読む** ② 関数群)。発見の網。
_SPEC_READERS: dict[str, tuple[str, tuple[Callable, ...]]] = {
    "instrument": ("spec", (_runner_from_instrument, _instrument_path_resolver)),
    "phase_id": ("phase_id", (sequential_rietveld,)),
}

#: spec 名 → その spec を ③ に**説明する** ② の表面。③ は ② の docstring しか仕様書を持たない
#: ので、キーを読む関数とは別に「どこに書いてあるか」を持つ (実運用の入口は tool 関数の docstring)。
_SPEC_DOC_SURFACES: dict[str, tuple[Callable, ...]] = {
    "instrument": (sequential_rietveld, _runner_from_instrument),
    "phase_id": (sequential_rietveld,),
}

#: basis を label しているべき ③ の手順書 (skill 2 種 + 非 Claude ハーネス用 PLAYBOOK)。
_LAYER3_DOCS = (
    Path("plugins/tsumugin/skills/insitu/SKILL.md"),
    Path("plugins/tsumugin/skills/operando-diagnose/SKILL.md"),
    Path("docs/tasks/operando-diagnosis/AGENT_PLAYBOOK.md"),
)


def _spec_keys_read(func: Callable, var: str) -> set[str]:
    """``<var>.get("key", ...)`` の形で読まれている spec キーを AST で列挙する。

    受け手の変数名で絞る (``spec``/``phase_id``) ため、同関数内の他 dict の ``.get`` は拾わない。
    """
    tree = _source_ast(func)
    if tree is None:  # pragma: no cover - 動的定義の保険
        return set()
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "get"):
            continue
        if not (isinstance(f.value, ast.Name) and f.value.id == var):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            keys.add(str(node.args[0].value))
    return keys


def _discovered_spec_inputs() -> set[str]:
    """② の JSON spec dict が実際に読むキーを ``<spec>.<key>`` 形で発見する。"""
    found: set[str] = set()
    for spec, (var, funcs) in _SPEC_READERS.items():
        for func in funcs:
            found |= {f"{spec}.{key}" for key in _spec_keys_read(func, var)}
    return found


def test_every_layer2_spec_input_declares_its_fraction_basis():
    """★② の JSON spec が読む**全ての**キーが分率 basis を宣言していること。

    非トートロジー: 表を grep せず、`_runner_from_instrument` / `_instrument_path_resolver` /
    `sequential_rietveld` のソースを AST で走査して ``spec.get("...")`` を発見する。
    新しい閾値を spec に足したら本テストが fail し、「これは分率と比較されるのか / どの basis か」
    を一度考えさせる。**出力の basis (粒度④) を全部 label しても、入力の basis は誰も見ていなかった**。
    """
    actual = _discovered_spec_inputs()
    declared = set(SPEC_INPUT_BASIS)
    assert actual == declared, (
        f"② の JSON spec 入力キーと宣言が食い違う。"
        f"未宣言 (分率と比較されるなら basis を決め、② docstring と ③ 3 文書に label すること): "
        f"{sorted(actual - declared)} / "
        f"実在しない宣言 (削除/改名された?): {sorted(declared - actual)}"
    )


def test_spec_input_basis_declarations_use_the_known_vocabulary():
    """宣言が `FractionBasis` 語彙か `BASIS_FREE` であり、理由が書かれていること。"""
    for key, (basis, why) in SPEC_INPUT_BASIS.items():
        assert basis in (*_VALID_BASES, BASIS_FREE), (
            f"{key}: basis 宣言 {basis!r} は {_VALID_BASES} か {BASIS_FREE!r} であること"
        )
        assert why and len(why) > 20, f"{key}: 理由が書かれていない"


@pytest.mark.parametrize(
    "key", sorted(k for k, (b, _) in SPEC_INPUT_BASIS.items() if b != BASIS_FREE)
)
def test_basis_dependent_spec_inputs_are_labelled_in_the_layer2_docstring(key):
    """★basis 依存の入力は ② の docstring で basis を label していること。

    ③ は ② の JSON しか持たない。① が知っていて ② が言わない事実は ③ にとって存在しない
    (§4.5 到達可能性)。閾値の basis を言わない ② は「呼べるが黙って間違う」を再導入する。
    """
    spec, name = key.split(".", 1)
    docs = {
        f.__name__: inspect.getdoc(f) or "" for f in _SPEC_DOC_SURFACES[spec]
    }
    describing = {n: d for n, d in docs.items() if name in d}
    assert describing, (
        f"{key}: ② の docstring ({sorted(docs)}) がこのキーを説明していない — "
        f"③ は ② の docstring しか仕様書を持たない"
    )
    labelled = [n for n, d in describing.items() if "Scale" in d]
    assert labelled, (
        f"{key}: {sorted(describing)} の docstring が basis (Scale) を label していない — "
        f"③ は wt% だと思って閾値を決める (出版値は wt% だと ① の model.py と ③ skill が教える)"
    )


@pytest.mark.parametrize(
    "key", sorted(k for k, (b, _) in SPEC_INPUT_BASIS.items() if b != BASIS_FREE)
)
@pytest.mark.parametrize("doc", _LAYER3_DOCS, ids=lambda p: p.name)
def test_basis_dependent_spec_inputs_are_labelled_in_every_layer3_doc(key, doc):
    """★basis 依存の入力は **③ の 3 文書すべて**で basis を label していること。

    非トートロジー: 実際のファイルを読み、**閾値名と `Scale` が同じ行に現れる**ことを求める。
    label を落とせば fail する。3 文書は「本当の分率は wt%」「Scale を wt% として報告するな」と
    教えているので、**閾値だけ Scale であることを言わないと積極的に誤らせる**。

    ⚠ 本テストは label の**有無**しか見ない (散文の正しさは検証できない)。実装が本当に Scale で
    比較していることは `tests/autorietveld/test_auto_freeze.py::
    test_documented_threshold_compares_scale_not_weight_fraction` が振る舞いで pin する。
    """
    _spec, name = key.split(".", 1)
    text = doc.read_text(encoding="utf-8")
    assert name in text, f"{doc}: {name} に言及していない (③ はこのツマミを知らない)"
    hits = [line for line in text.splitlines() if name in line and "Scale" in line]
    assert hits, (
        f"{doc}: {name} の basis (Scale) を label している行が無い。"
        f"③ は同じ文書で「出版値は wt%」と教わっているため、label が無い閾値は wt% だと解釈する "
        f"— 実測 Scale{{tetra .25}} = wt%{{tetra .135}} で 0.15 という指定は**答えが割れる**"
    )


def test_anchor_is_still_unexposed_or_the_note_is_stale():
    """M10 anchor の露出状況と宣言が一致すること (露出したら宣言を更新させる)。

    Issue #97 が解決して ② に anchor ツールが入ったら、このテストが fail して
    `LAYER1_FEATURES` の更新を強制する — **宣言が実態から遅れるのを防ぐ**。
    """
    # unwrap で @degrade_oserror 等のデコレータを貫通する (wrapper の source には "anchor" が無く、
    # unwrap しないと露出済みの anchored_sequential を見落として宣言と食い違う; Issue #94)。
    # `_code_without_docs` で docstring/コメントを落としてから見る — 生の `inspect.getsource` は
    # **説明文が "anchor" に言及しているだけで露出済みと誤判定**する (同型の欠陥を Issue #125 の
    # ガードで実測: 配線を全削除しても pass した)。実コードだけを根拠にする。
    exposed = [t for t in MCP_TOOLS if "anchor" in _code_without_docs(MCP_TOOLS[t]).lower()]
    declared_unexposed = LAYER1_FEATURES["insitu.anchor (M10/FR-330)"][0] == UNEXPOSED
    if exposed:
        assert not declared_unexposed, (
            f"anchor が ② に露出した ({exposed}) — LAYER1_FEATURES と "
            "skills/insitu・skills/operando-diagnose・AGENT_PLAYBOOK の更新も必要 (Issue #97)"
        )
    else:
        assert declared_unexposed, "anchor は ② 未露出のはずだが露出ありと宣言されている"


def _code_without_docs(fn: object) -> str:
    """関数ソースから docstring とコメントを除いた**コード本体**を返す。

    ★なぜ必要か (実測): `inspect.getsource` は docstring とコメントを含む。「そのキーが実際に
    配線されているか」を部分一致で見るガードは、**docstring がキー名に言及しているだけで通って
    しまう**。実際 `list_hypotheses` の配線行を削除する変異を当てても、docstring に
    "escalations" が残っているためガードが pass した = **トートロジーで、落ちないガード**だった。
    ast で往復すると docstring は明示的に除去でき、コメントは AST に存在しないため自動的に落ちる。
    """
    src = textwrap.dedent(inspect.getsource(inspect.unwrap(fn)))  # type: ignore[arg-type]
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_code_without_docs_strips_docstrings_and_comments():
    """★上のヘルパ自身が説明文を落とすこと (ガードのガード)。

    これが壊れると全ての「配線されているか」検査が静かにトートロジー化するため、
    ヘルパ単体を直接検査する。
    """

    def sample():
        """marker_in_docstring"""
        # marker_in_comment
        return {"marker_in_code": 1}

    code = _code_without_docs(sample)
    assert "marker_in_docstring" not in code, "docstring が落ちていない (ガードがトートロジー化)"
    assert "marker_in_comment" not in code, "コメントが落ちていない"
    assert "marker_in_code" in code, "コード本体まで落としている (検査が常に fail 側へ倒れる)"


def test_selection_escalation_is_now_reachable_or_the_note_is_stale():
    """★エスカレーション検出の ② 到達状況と宣言が一致すること (Issue #125 解決後・逆方向ガード)。

    **Issue #125 解決前の状態**: `detect_escalations` (FR-403 の 4 条件 + FR-212 の
    guard_escalated) が実際に走るのは `FinalSelectionEngine.decide()` の中だけだった。②
    `accept_hypothesis` は `selection.accept` を直接呼んで decide を迂回するため、
    `list_review_queue` を足すだけでは常に空を返す DOA になる懸念があった。

    **解決内容**: `FinalSelectionEngine.accept()` 自体がエスカレーション検出時に Review Queue へ
    通知するよう修正し (decide() 迂回でも検出結果が残る)、② `list_hypotheses`/`accept_hypothesis`
    の応答へ `escalations` を直接含めた。② `list_review_queue`/`resolve_review_item` で
    Review Queue 自体も ③ から読める。

    本テストは元の `test_selection_escalation_is_still_unreachable_or_the_note_is_stale`
    (Issue #125 前) の**逆方向**: 表を読まず `list_hypotheses`/`accept_hypothesis` の実ソースに
    `"escalations"` が実際に現れるかを見て、宣言 (もう「既知の穴」ではない) と食い違わないことを
    確認する。将来この配線が外れて ③ から再び不可視になったら本テストが fail し、
    `PACKAGE_COVERAGE["selection"]` の記述更新 (「既知の穴」へ書き戻す) を強制する —
    **塞がった穴が再び開いたのに気づかない、を防ぐ**。

    **限界**: ツール関数**自身の**コード本体の部分一致なので、ヘルパー関数を挟んだ間接的な
    "escalations" 生成は追えない。現状は両ツールとも関数本体に直接 `"escalations"` キーを書いて
    いるため偽陰性は無い。なお `_code_without_docs` で docstring/コメントを落としてから見る —
    生の `inspect.getsource` だと**説明文の言及だけで通る**トートロジーになる (変異テストで実証済)。
    振る舞い自体の検査は `tests/test_mcp_tools.py` の
    `test_list_hypotheses_includes_escalations_when_detected` が担う。
    """
    exposing_tools = [
        name
        for name in ("list_hypotheses", "accept_hypothesis")
        if "escalations" in _code_without_docs(MCP_TOOLS[name])
    ]
    declared_gap = "既知の穴" in PACKAGE_COVERAGE["selection"][1]
    if len(exposing_tools) == 2:
        assert not declared_gap, (
            f"エスカレーションは ② ({exposing_tools}) から到達可能になっているのに "
            "PACKAGE_COVERAGE['selection'] がまだ「既知の穴」と書いている — Issue #125 解決後の"
            "記述更新漏れ (陳腐化した宣言)"
        )
    else:
        assert declared_gap, (
            f"escalations を返す ② ツールが揃っていない ({exposing_tools}) = エスカレーションが"
            "再び ③ から不可視になった。PACKAGE_COVERAGE['selection'] を「既知の穴」に戻し、"
            "③ skill 手順 (hypothesis-search「エスカレーションを確認する」節) の整合も見直すこと"
        )
