"""TASK-0010 公開 API 統合 + E2E (M1 総仕上げ) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/__init__.py`` への M1 公開シンボル re-export
(``HypothesisTreeSearch`` / ``SearchConfig`` / ``SearchResult`` / ``PhaseCandidate`` /
``UnmatchedPeakReport`` / ``export_gpx``) と、公開 API 経由の E2E 結線検証。

Red の失敗機構: 本モジュール冒頭の ``from tsumugin import HypothesisTreeSearch, ...`` は
トップレベル未 re-export (現状 M0 分のみ) のため collection 時に ImportError となり、
全 13 テストが失敗する (テストケース定義書 §4 テスト実装方針)。

方針:
- E2E は実バックエンドを使う (SimulatedBackend=マーカー無し / GSASIIBackend=@gsas)。
  FakeBackend 等の単体スタブは使わない (要件定義 §3.5)。
- 観測グリッドは 15–60° / step 0.02 (test_tree_search.py と同一)。step 0.02 は
  clustering の bin 較正上変更禁止 (note §6)。
- @gsas 2 件は GSAS-II 未導入環境で conftest.py が自動 skip。探索は module スコープの
  fixture で 1 回だけ実行し実行時間を抑える。
- 決定論 (TC-010-11) は ``==`` ビット同一、物理量は ``pytest.approx``。

書式の範: ``tests/test_tree_search.py`` / ``tests/test_gpx_export.py``。
テストケース定義 (13 件, TC-010-01〜13) に 1:1 対応する。
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pytest

import tsumugin
import tsumugin.export
import tsumugin.search

# 【Red の失敗点】: M1 シンボルはトップレベル未 re-export のため、この import が
#   collection 時に ImportError となり本ファイルの全テストが失敗する想定。🔵
from tsumugin import (
    HypothesisTreeSearch,
    LatticeParams,
    PhaseCandidate,
    PhaseInstance,
    SearchConfig,
    SearchResult,
    SimulatedBackend,
    UnmatchedPeakReport,
    export_gpx,
)

# ---------------------------------------------------------------------------
# 共通テストデータ・前提 (tests/test_tree_search.py の慣習を踏襲)
# ---------------------------------------------------------------------------

# 【観測グリッド】: 全候補ピークが収まる 15–60° / step 0.02。step 0.02 は clustering の
#   bin 較正上必須 (変更禁止)。範囲を絞って E2E の実行時間を抑える。🔵
GRID = np.arange(15.0, 60.0, 0.02)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンスを作る (格子定数 a を変えるとピーク位置が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


# 【候補相】: A/B は真の相、C/D は無関係相 (ピーク位置が合わず低スコアに較正済み)。🔵
PHASE_A = _phase(5.0, "A")  # 真の相 1 🔵
PHASE_B = _phase(6.0, "B")  # 真の相 2 (2 相合成は A+B を重ねる) 🔵
PHASE_C = _phase(4.5, "C")  # 無関係相 🔵
PHASE_D = _phase(7.0, "D")  # 無関係相 🔵


def _refs(hypothesis) -> set[str]:
    """仮説の相集合 (phase_ref の集合) を返す。"""
    return {p.phase_ref for p in hypothesis.phases}


# 【スキーマ契約】: to_summary() トップレベルの必須キー集合 (api-endpoints.md /api/result)。🔵
_SUMMARY_TOP_KEYS = {
    "ranked",
    "unknown_phase_flag",
    "unmatched_observed",
    "extra_calculated",
    "warnings",
    "n_hypotheses",
}

# 【スキーマ契約】: to_summary()["ranked"][i] の必須キー集合 (要件定義 §2.2)。🔵
_SUMMARY_RANKED_KEYS = {
    "id",
    "rank",
    "probability",
    "close_competitor",
    "rwp",
    "gof",
    "evidence",
    "phases",
    "parent_id",
    "in_good_cluster",
}

# 【後方互換契約】: 既存 M0 公開シンボル (削除・改名禁止 / 要件定義 §3.2)。🔵
_M0_PUBLIC_SYMBOLS = {
    "AICBackend",
    "AnalysisResult",
    "BICBackend",
    "Hypothesis",
    "LatticeParams",
    "Ledger",
    "PhaseInstance",
    "Project",
    "RankedHypothesis",
    "RefinementBackend",
    "RefinementMetrics",
    "RefinementModel",
    "RefinementReport",
    "RefinementResult",
    "SimulatedBackend",
    "SnapshotStore",
    "StagedRefinementEngine",
    "analyze_single_pattern",
    "rank",
}

# 【昇格契約】: 本タスクでトップレベルへ昇格する M1 シンボル (要件定義 §2.1 推奨案)。🔵
_M1_PROMOTED_SYMBOLS = {
    "HypothesisTreeSearch",
    "PhaseCandidate",
    "SearchConfig",
    "SearchResult",
    "UnmatchedPeakReport",
    "export_gpx",
}


@pytest.fixture(scope="module")
def ab_result() -> SearchResult:
    """A+B 合成・候補 [A,B,C,D] の標準 E2E 探索 (module スコープで 1 回だけ実行)。

    【テスト前準備】: 公開 API (from tsumugin import ...) 経由でフルパイプラインを実行し、
    frozen な SearchResult を正常系 3 ケース (TC-010-03/04/05) で読み取り専用共有する。🔵
    """
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)
    return HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])


@pytest.fixture(scope="module")
def gsasii_ab_search():
    """GSASIIBackend による A+B 探索 (module スコープ、@gsas ケースのみが要求する)。

    【テスト前準備】: 実 GSAS-II 精密化を伴う探索は高コストのため 1 回だけ実行し、
    観測強度 y と SearchResult を @gsas 2 ケース (TC-010-06/07) で共有する。🔵
    """
    from tsumugin.backends.gsasii import GSASIIBackend

    backend = GSASIIBackend()
    y = backend.simulate([PHASE_A, PHASE_B], GRID)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])
    return y, result


# ---------------------------------------------------------------------------
# 1. 正常系テストケース (TC-010-01〜07)
# ---------------------------------------------------------------------------


def test_m1_public_symbols_are_reexported():
    # 【テスト目的】: M1 公開シンボル 6 件が from tsumugin import ... で解決する (TC-010-01)
    # 【テスト内容】: モジュール冒頭 import 済みの各シンボルが期待の型 (クラス/dataclass/関数) か検証
    # 【期待される動作】: トップレベル tsumugin 名前空間から M1 中核シンボルへ到達できる (完了条件①)
    # 🔵 信頼性レベル: 要件定義 §2.1 / 完了条件① / test_export_gpx_is_reexported の範に直接依拠

    # 【結果検証】: 各シンボルの種別が要件定義 §2.1 の表と一致すること
    assert inspect.isclass(HypothesisTreeSearch)  # 【確認内容】: 探索エンジンはクラス 🔵
    assert dataclasses.is_dataclass(SearchConfig)  # 【確認内容】: 探索設定は dataclass 🔵
    assert dataclasses.is_dataclass(SearchResult)  # 【確認内容】: 探索結果は dataclass 🔵
    assert dataclasses.is_dataclass(PhaseCandidate)  # 【確認内容】: 候補相は dataclass 🔵
    assert dataclasses.is_dataclass(UnmatchedPeakReport)  # 【確認内容】: 未マッチ報告は dataclass 🔵
    assert callable(export_gpx)  # 【確認内容】: .gpx 書き出しは呼び出し可能な関数 🔵
    assert not inspect.isclass(export_gpx)  # 【確認内容】: export_gpx は関数でありクラスでない 🔵

    # 【期待値確認】: トップレベルはサブパッケージ実体の re-export (コピーや別実装でない) 🔵
    assert HypothesisTreeSearch is tsumugin.search.HypothesisTreeSearch  # 【確認内容】: 同一実体 🔵
    assert export_gpx is tsumugin.export.export_gpx  # 【確認内容】: 同一実体 🔵


def test_m1_symbols_in_dunder_all_and_sorted():
    # 【テスト目的】: 昇格シンボルが tsumugin.__all__ に含まれ昇順ソートが維持される (TC-010-02)
    # 【テスト内容】: __all__ の包含関係・ソート順・M0 分の後方互換 (削除なし) を検証
    # 【期待される動作】: __all__ が M0 + M1 を統合しアルファベット昇順のまま (完了条件①)
    # 🔵 信頼性レベル: 要件定義 §2.1/§3.2 / 既存 __init__.py の __all__ 慣習に直接依拠

    exported = set(tsumugin.__all__)

    # 【結果検証】: 昇格 6 シンボルが公開面 (__all__) に配線されていること
    assert _M1_PROMOTED_SYMBOLS <= exported  # 【確認内容】: M1 シンボルが __all__ に包含 🔵
    # 【後方互換】: 既存 M0 シンボルが 1 つも削除・改名されていないこと (要件 §3.2)
    assert _M0_PUBLIC_SYMBOLS <= exported  # 【確認内容】: M0 公開面の非破壊 (後方互換維持) 🔵
    # 【規約遵守】: __all__ がアルファベット昇順ソートを維持していること
    assert list(tsumugin.__all__) == sorted(tsumugin.__all__)  # 【確認内容】: 昇順ソート維持 🔵
    # 【実体整合】: __all__ の全名称が実際に属性として解決できること
    for name in tsumugin.__all__:
        assert hasattr(tsumugin, name)  # 【確認内容】: __all__ と実属性の乖離が無い 🔵


def test_e2e_simulated_two_phase_ranks_ab_first(ab_result: SearchResult):
    # 【テスト目的】: SimulatedBackend E2E で真の 2 相構成 {A,B} が 1 位になる (TC-010-03)
    # 【テスト内容】: 公開 API 経由の search() フルパイプライン (find_peaks→match→cluster→
    #   prune→best-first→BIC→rank→後処理) が完走しランキング先頭が真の構成になるか検証
    # 【期待される動作】: ranked[0] の相集合 == {"A", "B"} (完了条件② / TC-001-01 の E2E 版)
    # 🔵 信頼性レベル: 完了条件② / 受け入れ基準 TC-001-01 / test_two_phase_truth_ranks_ab_first に依拠

    # 【結果検証】: ランキング先頭が真の 2 相構成であること
    assert ab_result.ranked  # 【確認内容】: ランキングが非空 🔵
    assert _refs(ab_result.ranked[0].hypothesis) == {"A", "B"}  # 【確認内容】: {A,B} が 1 位 🔵
    top_id = ab_result.ranked[0].hypothesis.id
    assert top_id in ab_result.hypotheses  # 【確認内容】: 先頭 ID が hypotheses に存在 (整合) 🔵


def test_e2e_summary_is_json_serializable_with_schema(ab_result: SearchResult):
    # 【テスト目的】: to_summary() が json.dumps 可能な純 dict でスキーマ準拠 (TC-010-04)
    # 【テスト内容】: /api/result スキーマの必須キー (トップ + ranked 行) と JSON 直列化を検証
    # 【期待される動作】: summary が素の型のみで構成され契約キーを全て備える (完了条件②)
    # 🔵 信頼性レベル: 完了条件② / 要件定義 §2.2 / api-endpoints.md GET /api/result に直接依拠

    summary = ab_result.to_summary()

    # 【結果検証】: JSON 直列化が例外なく成功し往復で同値になること
    assert json.loads(json.dumps(summary)) == summary  # 【確認内容】: 純 dict の JSON 往復同値 🔵
    # 【スキーマ検証】: トップレベル必須キーを全て備えること
    assert _SUMMARY_TOP_KEYS <= set(summary)  # 【確認内容】: /api/result 必須トップキー包含 🔵
    assert summary["n_hypotheses"] == len(ab_result.hypotheses)  # 【確認内容】: 仮説総数が一致 🔵
    # 【行スキーマ検証】: ranked 先頭行が契約キーを全て備えること
    assert summary["ranked"]  # 【確認内容】: ranked が非空 list 🔵
    assert _SUMMARY_RANKED_KEYS <= set(summary["ranked"][0])  # 【確認内容】: 行の必須キー包含 🔵
    # 【決定論との連動】: 同一 result からの直列化が 2 回とも同一文字列 (TC-010-11 と連動)
    dumped1 = json.dumps(ab_result.to_summary(), sort_keys=True)
    dumped2 = json.dumps(ab_result.to_summary(), sort_keys=True)
    assert dumped1 == dumped2  # 【確認内容】: canonical JSON 直列化が安定 🔵


def test_e2e_ledger_verify_true(ab_result: SearchResult):
    # 【テスト目的】: 公開 API 経由の探索実行後 ledger.verify() が True (TC-010-05)
    # 【テスト内容】: 追記専用ハッシュチェーンが E2E 統合経路でも無傷であることを検証
    # 【期待される動作】: verify() is True かつ entries 非空 (空 ledger の自明 True でない)
    # 🔵 信頼性レベル: 受け入れ基準 TC-008-01 / NFR-105/201 / REQ-402 に直接依拠

    assert ab_result.ledger.verify() is True  # 【確認内容】: ハッシュ連鎖が無傷 (改竄なし) 🔵
    assert len(ab_result.ledger.entries) > 0  # 【確認内容】: 空 ledger の自明 True でない 🔵


@pytest.mark.gsas
def test_e2e_gsasii_search_completes(gsasii_ab_search):
    # 【テスト目的】: GSASIIBackend での search E2E が完走しランキングを返す (TC-010-06)
    # 【テスト内容】: 実 GSAS-II 精密化を用いた探索が破綻せず SearchResult を返すことを検証
    # 【期待される動作】: ranked 非空・ledger.verify() True・refined 仮説の evidence に "bic" キー
    # 🔵 信頼性レベル: 完了条件③ / tests/test_gsasii_backend.py の @gsas パターンに直接依拠

    _, result = gsasii_ab_search

    # 【結果検証】: バックエンド交換 (P7) しても探索パイプラインが同契約で完走すること
    assert result.ranked  # 【確認内容】: 実バックエンドでもランキングが非空 🔵
    assert result.ledger.verify() is True  # 【確認内容】: 統合経路でも ledger 連鎖が無傷 🔵
    # 【期待値確認】: 全 refined 仮説が BIC 一次評価を保持すること (GSAS-II 特有の失敗は
    #   chi2=inf に変換され探索全体をクラッシュさせない)
    for h in result.hypotheses.values():
        assert h.metrics is not None  # 【確認内容】: metrics 欠落ノードが無い 🔵
        assert "bic" in h.metrics.evidence  # 【確認内容】: BIC 評価が格納される 🔵


@pytest.mark.gsas
def test_e2e_gsasii_search_then_export_gpx_reopenable(gsasii_ab_search, tmp_path):
    # 【テスト目的】: search → export_gpx → 再オープンの連携で相数が一致する (TC-010-07)
    # 【テスト内容】: 探索結果の代表仮説の相を export_gpx で .gpx へ書き出し、
    #   G2Project で再オープンして相数を照合する (探索→書き出しの結線検証)
    # 【期待される動作】: 戻り値パスが実在し再オープンした phases() 長が書き出した相数と一致
    # 🔵 信頼性レベル: 完了条件③ / 受け入れ基準 TC-006-01 / test_gpx_export.py の再オープン検証に依拠

    y, result = gsasii_ab_search

    # 【テストデータ準備】: 探索で得た最良仮説の相集合をそのまま export_gpx の入力にする
    # 【初期条件設定】: tmp_path フィクスチャで .gpx をテストごとに隔離する
    phases = result.ranked[0].hypothesis.phases
    path = str(tmp_path / "m1.gpx")

    # 【実際の処理実行】: 探索結果 (PhaseInstance 群) を export_gpx の入力契約へ橋渡しする
    written = export_gpx(path, phases, GRID, y)

    # 【結果検証】: 書き出しの完全性と GSAS-II ワークフローへの橋渡し可能性
    assert written == path  # 【確認内容】: 戻り値が書き出しパスと一致 🔵
    assert Path(written).exists()  # 【確認内容】: 永続 .gpx がファイルとして実在 🔵
    from tsumugin.backends.gsasii import _g2sc

    project = _g2sc().G2Project(written)
    assert len(project.phases()) == len(phases)  # 【確認内容】: 再オープン後の相数一致 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (TC-010-08〜10)
# ---------------------------------------------------------------------------


class _BlockOptionalImports:
    """optional extra (fastapi / uvicorn / GSASII) の import を人為的に失敗させる meta_path フック。

    D6 遅延 import 契約の検証用: 導入済み環境でも「未導入」状態を決定論的に再現する。
    """

    _BLOCKED = ("fastapi", "uvicorn", "GSASII")

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in self._BLOCKED:
            raise ImportError(f"blocked for D6 lazy-import test: {fullname}")
        return None


def test_import_tsumugin_does_not_require_optional_extras():
    # 【テスト目的】: import tsumugin が web/gsas extra 非依存で成功する (TC-010-08 / D6)
    # 【テスト内容】: fastapi/uvicorn/GSASII の import を meta_path フックで遮断した縮退環境を
    #   再現し、tsumugin 本体と M1 シンボル・tsumugin.webui の import が成功することを検証
    # 【期待される動作】: コア (numpy のみ) 利用者でも公開 API の import が失敗しない
    # 🔵 信頼性レベル: 要件定義 §3.4 (D6 遅延 import 契約) / note §1 に直接依拠

    # 【テストデータ準備】: optional extra とその配下 + tsumugin 系のモジュールを退避・除去し、
    #   import 遮断フックを最優先で仕込む (テスト後に必ず復元する)
    roots = set(_BlockOptionalImports._BLOCKED) | {"tsumugin"}
    saved = {n: m for n, m in sys.modules.items() if n.split(".")[0] in roots}
    for name in saved:
        del sys.modules[name]
    blocker = _BlockOptionalImports()
    sys.meta_path.insert(0, blocker)
    try:
        # 【実際の処理実行】: 未導入相当の環境で公開面を import する
        mod = importlib.import_module("tsumugin")

        # 【結果検証】: 公開面の import がオプション依存に汚染されないこと
        assert inspect.isclass(mod.HypothesisTreeSearch)  # 【確認内容】: M1 シンボル解決 🔵
        assert callable(mod.export_gpx)  # 【確認内容】: export_gpx は import 時 GSAS-II 不要 🔵
        webui = importlib.import_module("tsumugin.webui")
        # 【確認内容】: tsumugin.webui の import 自体は FastAPI 不要 (app 内遅延 import) 🔵
        assert "create_app" in webui.__all__
    finally:
        # 【テスト後処理】: フックを除去し、遮断中に作られたモジュールを破棄して元の
        #   sys.modules を復元する (他テストへ影響させない)
        sys.meta_path.remove(blocker)
        for name in [n for n in sys.modules if n.split(".")[0] in roots]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_e2e_empty_candidates_degrades_gracefully():
    # 【テスト目的】: 候補ゼロで例外なく空 SearchResult へ縮退する (TC-010-09 / EDGE-001)
    # 【テスト内容】: candidates=[] の E2E で空ランキング・健全な ledger・JSON 化可能な
    #   summary が返ることを検証 (回帰防止)
    # 【期待される動作】: ranked==() / verify() True / n_hypotheses==0 で例外なし
    # 🔵 信頼性レベル: 受け入れ基準 TC-E01 / EDGE-001 / note §3 (空 SearchResult 縮退) に直接依拠

    # 【テストデータ準備】: 観測は任意 (単相 A の合成) — 候補ゼロの縮退経路のみを観測する
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)

    # 【実際の処理実行】: 探索空間が空でも例外化せず縮退する
    result = HypothesisTreeSearch(backend).search(GRID, y, [])

    # 【結果検証】: 空入力でも summary/ledger が健全な状態を保つこと
    assert result.ranked == ()  # 【確認内容】: 空ランキング (例外を出さない契約) 🔵
    assert result.ledger.verify() is True  # 【確認内容】: 空でも ledger 実体が健全 🔵
    summary = result.to_summary()
    json.dumps(summary)  # 【確認内容】: 空スキーマの summary が JSON 化可能 🔵
    assert summary["n_hypotheses"] == 0  # 【確認内容】: 仮説総数 0 🔵


def test_e2e_unknown_phase_flag_and_unmatched_report():
    # 【テスト目的】: 候補にない相の混入で未知相フラグ + 未マッチ報告が立つ (TC-010-10)
    # 【テスト内容】: 観測 = A+B の 2 相合成、候補 = [A,C,D] (真の相 B を除外) の E2E で
    #   summary の unknown_phase_flag と unmatched_observed を検証
    # 【期待される動作】: フラグ True + 位置・強度付きの未マッチ配列 (例外でなく構造化出力)
    # 🔵 信頼性レベル: 受け入れ基準 TC-005-01 / REQ-005 / 要件定義 §4.5 に直接依拠

    # 【テストデータ準備】: B(a=6.0) を候補から除外し「相ライブラリに無い相」を模擬する
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A, PHASE_B], GRID)

    # 【実際の処理実行】: 候補集合が観測を完全説明できない不足状態で探索する
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_C, PHASE_D])
    summary = result.to_summary()

    # 【結果検証】: 説明不能ピークを黙殺せず summary で明示すること (FR-117)
    assert summary["unknown_phase_flag"] is True  # 【確認内容】: 未知相フラグが立つ 🔵
    assert summary["unmatched_observed"]  # 【確認内容】: 未マッチ観測が非空で報告される 🔵
    for row in summary["unmatched_observed"]:
        assert {"position", "height"} <= set(row)  # 【確認内容】: 位置・強度付きの dict 🔵
        assert type(row["position"]) is float  # 【確認内容】: 位置は素の float 🔵
        assert row["height"] > 0.0  # 【確認内容】: 強度は正値 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース (TC-010-11〜13)
# ---------------------------------------------------------------------------


def test_e2e_deterministic_summary_bitwise_identical():
    # 【テスト目的】: 同一入力の 2 回実行で to_summary() がビット同一 (TC-010-11 / REQ-403)
    # 【テスト内容】: 独立にエンジン・バックエンドを 2 回生成して探索し、canonical JSON
    #   文字列 (sort_keys=True) とランキング列を == で比較する (pytest.approx を使わない)
    # 【期待される動作】: 浮動小数の非決定性・辞書順の揺れが混入せず完全再現される
    # 🔵 信頼性レベル: 受け入れ基準 TC-001-05 / REQ-403 / NFR-102 / note §6 に直接依拠

    def once() -> SearchResult:
        # 【初期条件設定】: バックエンド・エンジンとも毎回独立に生成する (状態共有を排除)
        backend = SimulatedBackend(peak_fwhm=0.2)
        y = backend.simulate([PHASE_A, PHASE_B], GRID)
        return HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A, PHASE_B, PHASE_C, PHASE_D])

    r1, r2 = once(), once()

    # 【結果検証】: canonical JSON 化した summary が文字列として完全一致すること
    dumped1 = json.dumps(r1.to_summary(), sort_keys=True)
    dumped2 = json.dumps(r2.to_summary(), sort_keys=True)
    assert dumped1 == dumped2  # 【確認内容】: summary がビット同一 (決定論) 🔵
    # 【期待値確認】: ランキングの id/rank/probability 列も == で完全一致すること
    order1 = [(rk.hypothesis.id, rk.probability, rk.evidence.value) for rk in r1.ranked]
    order2 = [(rk.hypothesis.id, rk.probability, rk.evidence.value) for rk in r2.ranked]
    assert order1 == order2  # 【確認内容】: ランキング・確率・evidence がビット同一 🔵


def test_e2e_single_candidate_single_hypothesis():
    # 【テスト目的】: 候補 1 相で深さ 1・単一仮説のランキングを返す (TC-010-12 / EDGE-102)
    # 【テスト内容】: 探索空間の最小非空ケース (N=1) の E2E で組合せ展開なしに単一仮説が
    #   評価・ランクされることを検証 (候補数の下限境界)
    # 【期待される動作】: len(ranked)==1・相集合 {"A"}・ledger.verify() True
    # 🔵 信頼性レベル: 受け入れ基準 TC-E04 / EDGE-102 / 要件定義 §4.5 に直接依拠

    # 【テストデータ準備】: 単相 A の合成データと候補 [A] のみ (prune_min_candidates 未満)
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([PHASE_A], GRID)

    # 【実際の処理実行】: 最小候補数で探索する (枝刈りが単相探索を阻害しないこと)
    result = HypothesisTreeSearch(backend).search(GRID, y, [PHASE_A])

    # 【結果検証】: 候補ゼロ (TC-010-09) と候補複数 (TC-010-03) の中間で連続的に動作すること
    assert len(result.ranked) == 1  # 【確認内容】: 単一仮説のランキング (深さ 1 の木) 🔵
    assert _refs(result.ranked[0].hypothesis) == {"A"}  # 【確認内容】: 相集合は {A} のみ 🔵
    assert result.ranked[0].probability == pytest.approx(1.0)  # 【確認内容】: 単独 softmax 🔵
    assert result.ledger.verify() is True  # 【確認内容】: 最小構成でも ledger 健全 🔵


def test_readme_m1_example_executes():
    # 【テスト目的】: README「使い方 (M1)」節の最小使用例と同等のコードが動作する (TC-010-13)
    # 【テスト内容】: 公開 import → SimulatedBackend で合成 → HypothesisTreeSearch(...).search
    #   → to_summary() の README 記載予定コード (10-15 行) を写経実行し完走を検証
    # 【期待される動作】: 使用例が例外なく実行され json.dumps 可能な summary dict が得られる
    # 🟡 信頼性レベル: 完了条件⑤ / 要件定義 §2.3 からの妥当な推測 (README 文面は Green で確定)

    # --- ここから README 使用例と同等のコード (公開 API のみ使用) ---
    # 【テストデータ準備】: 既知の 2 相 (立方 A/B) を重ねた合成観測パターンを作る
    backend = SimulatedBackend(peak_fwhm=0.2)
    two_theta = np.arange(15.0, 60.0, 0.02)
    candidates = [
        PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0)),
        PhaseInstance(phase_ref="B", lattice=LatticeParams(6.0, 6.0, 6.0)),
    ]
    intensity = backend.simulate(candidates, two_theta)

    # 【実際の処理実行】: 公開 API で多仮説木探索を実行し summary を取り出す
    engine = HypothesisTreeSearch(backend, config=SearchConfig())
    result = engine.search(two_theta, intensity, candidates)
    summary = result.to_summary()
    # --- ここまで README 使用例と同等のコード ---

    # 【結果検証】: 使用例の出力が公開 API の実シグネチャ・契約に追従していること
    assert isinstance(result, SearchResult)  # 【確認内容】: search は SearchResult を返す 🟡
    assert isinstance(summary, dict)  # 【確認内容】: to_summary は素の dict を返す 🟡
    json.dumps(summary)  # 【確認内容】: 使用例の最終出力が JSON 化可能 🟡
    assert summary["ranked"]  # 【確認内容】: ランキングが得られる (使用例の実効性) 🟡
    best = summary["ranked"][0]
    assert {p["phase_ref"] for p in best["phases"]} == {"A", "B"}  # 【確認内容】: 真の 2 相同定 🟡
