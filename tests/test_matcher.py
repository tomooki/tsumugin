"""TASK-0003 PeakMatcher の失敗テスト (TDD Red フェーズ)。

対象実装: ``src/tsumugin/search/matcher.py``（未実装）。
`MatchResult` / `match_score(candidate_peaks, observed_peaks, *, tol_deg=0.15, candidate_index=0)`、
`UnmatchedPeakReport` / `unmatched_peaks(match_results, observed_peaks, *, high_r_flag=False)` を検証する。
書式は `tests/test_peaks.py` / `tests/test_simulated_backend.py` を範とする
（モジュールレベルヘルパ + pytest.approx / frozen dataclass の値等価）。

本タスクは numpy のみで完結（scipy・GSAS-II 非依存）。テストケース定義 (19 件) に 1:1 対応する。
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定。
from tsumugin.search.matcher import (
    MatchResult,
    UnmatchedPeakReport,
    match_score,
    unmatched_peaks,
)
from tsumugin.search.peaks import Peak, find_peaks


# ---------------------------------------------------------------------------
# 共通テストヘルパ（tests/test_peaks.py / tests/test_simulated_backend.py 準拠）
# ---------------------------------------------------------------------------


# 【テストデータ準備】: 単相 PhaseInstance を最小構成で生成（既存テストの _phase を踏襲）
def _phase(a: float = 5.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


# 【初期条件設定】: 合成 2θ 軸（15〜80°, 0.02° 刻み）。既存テストの _grid と同一
def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)


# 【前提条件確認】: FWHM=0.2° 固定の決定論バックエンド（乱数不使用）
def _backend() -> SimulatedBackend:
    return SimulatedBackend(peak_fwhm=0.2)


# 【テストデータ準備】: peak_positions は位置のみ返すため一定 height で Peak に包む
# （候補 height はスコア計算に不使用 = requirements §7#4）
def _candidate(positions, height: float = 1.0) -> tuple[Peak, ...]:
    return tuple(Peak(position=float(p), height=height) for p in positions)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_matching_phase_score_greater_than_mismatch():
    # 【テスト目的】: 一致相の score が不一致相の score より厳密に大きいことを確認 (TC-N01/TC-002-01)
    # 【テスト内容】: 観測を生成した真相 a=5.0 の候補と、位置がずれた a=4.3 の候補で score を比較
    # 【期待される動作】: match_score(真相, 観測).score > match_score(不一致, 観測).score、両者 [0,1]
    # 🔵 信頼性レベル: 受け入れ基準 TC-002-01・完了条件1・note.md §5 に直接依拠

    # 【テストデータ準備】: 観測は a=5.0 単相の教師データ、候補は真相 a=5.0 と別相 a=4.3
    backend = _backend()
    tt = _grid()
    observed = find_peaks(tt, backend.simulate((_phase(a=5.0),), tt))
    match_cand = _candidate(backend.peak_positions(_phase(a=5.0), tt))
    mismatch_cand = _candidate(backend.peak_positions(_phase(a=4.3), tt))

    # 【実際の処理実行】: 一致相・不一致相それぞれで match_score を計算
    r_match = match_score(match_cand, observed)
    r_mismatch = match_score(mismatch_cand, observed)

    # 【結果検証】: 一致相スコアが不一致相スコアを上回り、両者が値域内
    assert r_match.score > r_mismatch.score  # 【確認内容】: 一致相 > 不一致相 (TC-002-01) 🔵
    assert 0.0 <= r_match.score <= 1.0  # 【確認内容】: 一致相スコアが [0,1] 🔵
    assert 0.0 <= r_mismatch.score <= 1.0  # 【確認内容】: 不一致相スコアが [0,1] 🔵


def test_matched_observed_returns_sorted_valid_indices():
    # 【テスト目的】: matched_observed が有効な観測 index を昇順・重複なしで返すことを確認 (TC-N02)
    # 【テスト内容】: 一致相を渡し、マッチ成立した観測ピーク index タプルの整合性を検証
    # 【期待される動作】: tuple[int, ...] が昇順・重複なし・範囲内 (0<=i<len(observed))・マッチ数>=1
    # 🔵 信頼性レベル: 完了条件3・interfaces.py の matched_observed 契約・FR-117 に依拠

    # 【テストデータ準備】: 観測と一致する真相 a=5.0 の候補
    backend = _backend()
    tt = _grid()
    observed = find_peaks(tt, backend.simulate((_phase(a=5.0),), tt))
    result = match_score(_candidate(backend.peak_positions(_phase(a=5.0), tt)), observed)

    # 【結果検証】: 型・昇順・重複なし・範囲内・非空
    matched = result.matched_observed
    assert isinstance(matched, tuple)  # 【確認内容】: tuple[int, ...] を返す 🔵
    assert len(matched) >= 1  # 【確認内容】: 一致相なのでマッチが 1 件以上 🔵
    assert list(matched) == sorted(matched)  # 【確認内容】: 観測 index が昇順 🔵
    assert len(set(matched)) == len(matched)  # 【確認内容】: index に重複なし (1:1 貪欲) 🔵
    assert all(0 <= i < len(observed) for i in matched)  # 【確認内容】: 有効な観測 index 範囲内 🔵


def test_unmatched_candidate_returns_extra_positions():
    # 【テスト目的】: 観測相手のない候補位置が unmatched_candidate に float 昇順で入ることを確認 (TC-N03)
    # 【テスト内容】: 観測 2 本に一致 + 観測に無い 1 本 (25.0) の候補を渡し extra を抽出
    # 【期待される動作】: unmatched_candidate == (25.0,)、マッチ済み候補位置は含まれない
    # 🔵 信頼性レベル: 完了条件3・interfaces.py の unmatched_candidate 契約・FR-117 に依拠

    # 【テストデータ準備】: 観測は主要反射 2 本、候補は「一致 2 本 + extra 1 本 (25.0)」
    observed = (Peak(position=20.0, height=10.0), Peak(position=30.0, height=8.0))
    candidate = _candidate([20.0, 30.0, 25.0])

    # 【実際の処理実行】: match_score で extra 候補位置を抽出
    result = match_score(candidate, observed)

    # 【結果検証】: 観測に相手が無い候補位置のみ、昇順 float タプル
    assert result.unmatched_candidate == (25.0,)  # 【確認内容】: extra は 25.0 のみ (昇順) 🔵


@pytest.mark.parametrize("kind", ["match", "mismatch", "partial"])
def test_score_within_unit_interval(kind):
    # 【テスト目的】: 一致・不一致・部分一致のいずれでも score が [0,1] に収まることを確認 (TC-N04)
    # 【テスト内容】: 3 種の候補で score を計算し、値域と NaN/inf 非発生を検証
    # 【期待される動作】: 0.0 <= score <= 1.0、NaN/inf を出さない
    # 🟡 信頼性レベル: 完了条件2・requirements §4.2「値域確認」からの妥当な推測

    # 【テストデータ準備】: 観測 a=5.0、候補は一致 / 不一致 / 部分一致 (半数) の 3 パターン
    backend = _backend()
    tt = _grid()
    observed = find_peaks(tt, backend.simulate((_phase(a=5.0),), tt))
    match_positions = backend.peak_positions(_phase(a=5.0), tt)
    if kind == "match":
        candidate = _candidate(match_positions)
    elif kind == "mismatch":
        candidate = _candidate(backend.peak_positions(_phase(a=4.3), tt))
    else:  # partial: 前半のみ一致させて中間スコアを狙う
        candidate = _candidate(match_positions[: len(match_positions) // 2])

    # 【実際の処理実行】: 各候補で match_score を計算
    result = match_score(candidate, observed)

    # 【結果検証】: 値域 [0,1] と数値健全性
    assert 0.0 <= result.score <= 1.0  # 【確認内容】: score が値域 [0,1] を逸脱しない 🟡
    assert not np.isnan(result.score)  # 【確認内容】: NaN が発生しない 🟡
    assert not np.isinf(result.score)  # 【確認内容】: inf が発生しない 🟡


def test_candidate_index_is_propagated():
    # 【テスト目的】: candidate_index がキーワード専用引数として MatchResult に伝搬することを確認 (TC-N05)
    # 【テスト内容】: 既定 (0) と明示指定 (3) の伝搬、および位置引数拒否 (キーワード専用) を検証
    # 【期待される動作】: 既定 0、指定 3 が反映。位置での第 3 引数は TypeError
    # 🟡 信頼性レベル: requirements §2.1・§7 確定事項#1 (interfaces に引数なし→推奨案で確定) の推測

    # 【テストデータ準備】: 手計算可能な最小の一致構成
    observed = (Peak(position=20.0, height=10.0),)
    candidate = _candidate([20.0])

    # 【結果検証】: 既定値・明示指定の伝搬、キーワード専用性
    assert match_score(candidate, observed).candidate_index == 0  # 【確認内容】: 既定は 0 🟡
    result = match_score(candidate, observed, candidate_index=3)
    assert result.candidate_index == 3  # 【確認内容】: 指定した 3 が MatchResult に反映 🟡
    with pytest.raises(TypeError):
        match_score(candidate, observed, 3)  # 【確認内容】: candidate_index は位置渡し不可 🟡


def test_deterministic_bit_identical():
    # 【テスト目的】: match_score / unmatched_peaks が同一入力で 2 回ビット同一になることを確認 (TC-N06)
    # 【テスト内容】: 同一入力で 2 回呼び出し、frozen dataclass の値等価で完全一致を検証
    # 【期待される動作】: r1 == r2 かつ report1 == report2 (score・タプル順まで一致)
    # 🔵 信頼性レベル: requirements §3 (NFR-102/REQ-403)・既存 test_deterministic に依拠

    # 【テストデータ準備】: 一致相 a=5.0 の観測・候補
    backend = _backend()
    tt = _grid()
    observed = find_peaks(tt, backend.simulate((_phase(a=5.0),), tt))
    candidate = _candidate(backend.peak_positions(_phase(a=5.0), tt))

    # 【実際の処理実行】: match_score・unmatched_peaks を各 2 回呼び出す
    r1 = match_score(candidate, observed)
    r2 = match_score(candidate, observed)
    rep1 = unmatched_peaks([r1], observed)
    rep2 = unmatched_peaks([r2], observed)

    # 【結果検証】: approx でなく == でビット同一
    assert r1 == r2  # 【確認内容】: match_score が決定論 (score・タプル順一致) 🔵
    assert rep1 == rep2  # 【確認内容】: unmatched_peaks が決定論 🔵


def test_unmatched_peaks_reports_unknown_phase():
    # 【テスト目的】: 候補に無い相を混ぜた観測で未マッチ観測を位置・強度付き報告 + flag True (TC-N07/TC-005-01)
    # 【テスト内容】: 観測 A+B、候補 A のみで unmatched_peaks を呼び B 由来ピークの残存を検証
    # 【期待される動作】: unmatched_observed が Peak 実体 (位置・強度保持)・位置昇順で非空、flag True
    # 🔵 信頼性レベル: 受け入れ基準 TC-005-01・interfaces.py の UnmatchedPeakReport 契約に直接依拠

    # 【テストデータ準備】: 観測は A(a=5.0)+B(a=4.3) の 2 相、候補は A のみ (B は未知相)
    backend = _backend()
    tt = _grid()
    observed = find_peaks(
        tt, backend.simulate((_phase(a=5.0, ref="A"), _phase(a=4.3, ref="B")), tt)
    )
    result_a = match_score(
        _candidate(backend.peak_positions(_phase(a=5.0, ref="A"), tt)), observed
    )

    # 【実際の処理実行】: 候補 A の結果 1 件で未マッチを集約
    report = unmatched_peaks([result_a], observed, high_r_flag=False)

    # 【結果検証】: B 由来の未説明ピークが Peak 実体・昇順・強度付きで残り、フラグが立つ
    assert len(report.unmatched_observed) > 0  # 【確認内容】: 未説明の観測ピークが存在 (B 由来) 🔵
    assert all(isinstance(p, Peak) for p in report.unmatched_observed)  # 【確認内容】: Peak 実体 🔵
    positions = [p.position for p in report.unmatched_observed]
    assert positions == sorted(positions)  # 【確認内容】: 位置昇順で報告 🔵
    assert all(p.height > 0.0 for p in report.unmatched_observed)  # 【確認内容】: 強度を保持 🔵
    assert report.unknown_phase_flag is True  # 【確認内容】: 未マッチ非空で未知相フラグ True 🔵


def test_unmatched_peaks_complete_explanation():
    # 【テスト目的】: 全候補で説明できる観測は未マッチ空・flag False になることを確認 (TC-N08/TC-005-02)
    # 【テスト内容】: 観測 A、候補 A のみ (完全説明) で unmatched_peaks を呼び空縮退を検証
    # 【期待される動作】: unmatched_observed == ()、unknown_phase_flag is False
    # 🔵 信頼性レベル: 受け入れ基準 TC-005-02・requirements §4.1 に直接依拠

    # 【テストデータ準備】: 観測 = 候補 A(a=5.0) で完全説明できる単相ケース
    backend = _backend()
    tt = _grid()
    observed = find_peaks(tt, backend.simulate((_phase(a=5.0),), tt))
    result_a = match_score(_candidate(backend.peak_positions(_phase(a=5.0), tt)), observed)

    # 【実際の処理実行】: 完全説明データで未マッチを集約
    report = unmatched_peaks([result_a], observed, high_r_flag=False)

    # 【結果検証】: 未マッチ空・誤警告なし
    assert report.unmatched_observed == ()  # 【確認内容】: 未説明ピークなし (空タプル) 🔵
    assert report.unknown_phase_flag is False  # 【確認内容】: 完全説明で未知相フラグ False 🔵


def test_results_are_frozen_dataclasses():
    # 【テスト目的】: MatchResult / UnmatchedPeakReport が frozen dataclass で不変であることを確認 (TC-N09)
    # 【テスト内容】: 型・不変タプルフィールド・属性再代入時の FrozenInstanceError を検証
    # 【期待される動作】: 各インスタンスが期待型・タプルフィールド、再代入で FrozenInstanceError
    # 🔵 信頼性レベル: interfaces.py の @dataclass(frozen=True)・REQ-402・既存不変性テストに依拠

    # 【テストデータ準備】: 最小の一致構成から MatchResult / UnmatchedPeakReport を得る
    observed = (Peak(position=20.0, height=10.0),)
    candidate = _candidate([20.0])
    result = match_score(candidate, observed)
    report = unmatched_peaks([result], observed)

    # 【結果検証】: 型・不変タプルフィールド・不変性
    assert isinstance(result, MatchResult)  # 【確認内容】: match_score は MatchResult を返す 🔵
    assert isinstance(report, UnmatchedPeakReport)  # 【確認内容】: unmatched_peaks は Report を返す 🔵
    assert isinstance(result.matched_observed, tuple)  # 【確認内容】: matched_observed は tuple 🔵
    assert isinstance(result.unmatched_candidate, tuple)  # 【確認内容】: unmatched_candidate は tuple 🔵
    assert isinstance(report.unmatched_observed, tuple)  # 【確認内容】: unmatched_observed は tuple 🔵
    assert isinstance(report.extra_calculated, tuple)  # 【確認内容】: extra_calculated は tuple 🔵
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.score = 0.0  # 【確認内容】: MatchResult は frozen で再代入不可 🔵
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.unknown_phase_flag = True  # 【確認内容】: Report も frozen で再代入不可 🔵


def test_score_matches_equal_weight_formula():
    # 【テスト目的】: score が 0.5·match_rate + 0.5·intensity_coverage の等重み平均式に一致することを確認 (TC-N10)
    # 【テスト内容】: 手計算可能な小規模入力で score・matched_observed・unmatched_candidate を検証
    # 【期待される動作】: match_rate=1/2=0.5, coverage=10/40=0.25 → score=0.375
    # 🟡 信頼性レベル: requirements §2.1 スコア定義・§7 確定事項#3(等重み)/#4(観測側 height) の推測

    # 【テストデータ準備】: 観測 height 合計 40、候補は 20.0(一致)+25.0(extra)。候補 height=1.0 は不使用
    observed = (Peak(position=20.0, height=10.0), Peak(position=30.0, height=30.0))
    candidate = (Peak(position=20.0, height=1.0), Peak(position=25.0, height=1.0))

    # 【実際の処理実行】: tol_deg=0.15 で match_score を計算
    result = match_score(candidate, observed, tol_deg=0.15)

    # 【結果検証】: 定義式どおりの数値・マッチ内容
    assert result.score == pytest.approx(0.5 * 0.5 + 0.5 * 0.25)  # 【確認内容】: score=0.375 🟡
    assert result.matched_observed == (0,)  # 【確認内容】: 観測 index 0 (20.0) がマッチ 🟡
    assert result.unmatched_candidate == (25.0,)  # 【確認内容】: 25.0 は extra 🟡


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング / EDGE-003 縮退）
# ---------------------------------------------------------------------------


def test_zero_candidate_degrades_to_score_zero():
    # 【テスト目的】: 候補ゼロで score=0.0・空タプル・例外なしに縮退することを確認 (TC-E01)
    # 【テスト内容】: candidate_peaks=() で match_rate の分母 0 縮退が安全に処理されるかを検証
    # 【期待される動作】: score==0.0、matched_observed==()、unmatched_candidate==()、例外送出なし
    # 🔵 信頼性レベル: requirements §4.2 EDGE (候補ゼロ)・完了条件2・note.md §6 に直接依拠

    # 【テストデータ準備】: 観測は非空、候補は空 (上流で範囲内反射ゼロのケース)
    observed = (Peak(position=20.0, height=10.0), Peak(position=30.0, height=8.0))

    # 【実際の処理実行】: 候補ゼロで match_score を適用 (例外が出れば失敗)
    result = match_score((), observed)

    # 【結果検証】: ゼロ除算せず 0.0 / 空タプルへ縮退
    assert result.score == 0.0  # 【確認内容】: 候補ゼロで score=0.0 (ゼロ除算回避) 🔵
    assert result.matched_observed == ()  # 【確認内容】: マッチなし (空タプル) 🔵
    assert result.unmatched_candidate == ()  # 【確認内容】: extra なし (空タプル) 🔵


def test_zero_observed_marks_all_candidates_extra():
    # 【テスト目的】: 観測ゼロで score=0.0・全候補 extra・例外なしに縮退することを確認 (TC-E02/EDGE-003)
    # 【テスト内容】: observed_peaks=() で intensity_coverage の分母 0 縮退と全 extra 扱いを検証
    # 【期待される動作】: score==0.0、matched_observed==()、unmatched_candidate に全候補位置 (昇順)
    # 🔵 信頼性レベル: 受け入れ基準 TC-E01/EDGE-003・requirements §4.2・完了条件2 に直接依拠

    # 【テストデータ準備】: 候補は 3 本、観測は空 (フラット/全ゼロパターンの上流縮退)
    candidate = _candidate([20.0, 25.0, 30.0])

    # 【実際の処理実行】: 観測ゼロで match_score を適用 (例外が出れば失敗)
    result = match_score(candidate, ())

    # 【結果検証】: 全候補が extra 扱いで安全縮退
    assert result.score == 0.0  # 【確認内容】: 観測ゼロで score=0.0 (ゼロ除算回避) 🔵
    assert result.matched_observed == ()  # 【確認内容】: マッチなし (空タプル) 🔵
    assert result.unmatched_candidate == (20.0, 25.0, 30.0)  # 【確認内容】: 全候補が extra (昇順) 🔵


def test_high_r_flag_forces_unknown_phase():
    # 【テスト目的】: high_r_flag=True で未マッチ空でも unknown_phase_flag=True を強制することを確認 (TC-E03/REQ-106)
    # 【テスト内容】: 完全説明データ (未マッチ空) に high_r_flag=True を渡しフラグ強制を検証
    # 【期待される動作】: unmatched_observed==() でも unknown_phase_flag is True
    # 🔵 信頼性レベル: 受け入れ基準 TC-E02・requirements §4.2 REQ-106・§7 確定事項#7 に直接依拠

    # 【テストデータ準備】: 完全説明できる単相 A のデータ (通常はフラグ False)
    backend = _backend()
    tt = _grid()
    observed = find_peaks(tt, backend.simulate((_phase(a=5.0),), tt))
    result_a = match_score(_candidate(backend.peak_positions(_phase(a=5.0), tt)), observed)

    # 【実際の処理実行】: high_r_flag=True で未マッチを集約
    report = unmatched_peaks([result_a], observed, high_r_flag=True)

    # 【結果検証】: 未マッチ空でも high_r_flag が優先されフラグが立つ
    assert report.unmatched_observed == ()  # 【確認内容】: 未マッチ観測は空 🔵
    assert report.unknown_phase_flag is True  # 【確認内容】: high_r_flag が優先されフラグ True 🔵


@pytest.mark.parametrize("high_r_flag,expected_flag", [(False, False), (True, True)])
def test_flat_pattern_empty_observed(high_r_flag, expected_flag):
    # 【テスト目的】: フラット (observed 空) で未マッチ空・フラグは high_r_flag に従うことを確認 (TC-E04/TC-005-03)
    # 【テスト内容】: observed=()・候補結果も無しで unmatched_peaks の縮退挙動を検証
    # 【期待される動作】: unmatched_observed==()・extra_calculated==()、flag は high_r_flag に一致、例外なし
    # 🟡 信頼性レベル: 受け入れ基準 TC-005-03・requirements §4.2 (フラットパターン) からの妥当な推測

    # 【実際の処理実行】: 観測空・候補結果空で unmatched_peaks を適用 (例外が出れば失敗)
    report = unmatched_peaks([], observed_peaks=(), high_r_flag=high_r_flag)

    # 【結果検証】: 空観測で誤フラグを立てず high_r_flag のみに従う
    assert report.unmatched_observed == ()  # 【確認内容】: 未マッチ観測は空 🟡
    assert report.extra_calculated == ()  # 【確認内容】: extra も空 🟡
    assert report.unknown_phase_flag is expected_flag  # 【確認内容】: フラグは high_r_flag に一致 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（tol_deg 境界 / 貪欲一致 / 集約）
# ---------------------------------------------------------------------------


def test_tol_deg_boundary_inside_matches():
    # 【テスト目的】: 位置差がちょうど tol_deg の候補が閉区間でマッチに含まれることを確認 (TC-B01)
    # 【テスト内容】: |Δ2θ|=0.15=tol_deg の候補で閉区間判定 (<=) を検証
    # 【期待される動作】: マッチ扱い → matched_observed==(0,)、unmatched_candidate==()、score>0
    # 🟡 信頼性レベル: requirements §4.2 tol_deg 境界・§7 確定事項#5 (閉区間) からの妥当な推測

    # 【テストデータ準備】: 観測 30.0、候補 30.15 (差 0.15 = tol_deg ちょうど)
    observed = (Peak(position=30.0, height=10.0),)
    candidate = (Peak(position=30.15, height=1.0),)

    # 【実際の処理実行】: tol_deg=0.15 で match_score を計算
    result = match_score(candidate, observed, tol_deg=0.15)

    # 【結果検証】: 境界値がマッチ側に確定分類
    assert result.matched_observed == (0,)  # 【確認内容】: 境界値 (0.15) はマッチ 🟡
    assert result.unmatched_candidate == ()  # 【確認内容】: extra なし 🟡
    assert result.score > 0.0  # 【確認内容】: マッチ成立で score>0 🟡


def test_tol_deg_boundary_outside_no_match():
    # 【テスト目的】: 位置差が tol_deg を僅かに超える候補が非マッチ (extra) になることを確認 (TC-B02)
    # 【テスト内容】: |Δ2θ|=0.16 > tol_deg=0.15 の候補で境界外の非マッチ分類を検証
    # 【期待される動作】: 非マッチ → matched_observed==()、unmatched_candidate==(30.16,)
    # 🟡 信頼性レベル: requirements §4.2 tol_deg 境界・§7 確定事項#5 からの妥当な推測

    # 【テストデータ準備】: 観測 30.0、候補 30.16 (差 0.16 = tol_deg 超過)
    observed = (Peak(position=30.0, height=10.0),)
    candidate = (Peak(position=30.16, height=1.0),)

    # 【実際の処理実行】: tol_deg=0.15 で match_score を計算
    result = match_score(candidate, observed, tol_deg=0.15)

    # 【結果検証】: 境界外が非マッチ (extra) に確定分類
    assert result.matched_observed == ()  # 【確認内容】: 境界外 (0.16) は非マッチ 🟡
    assert result.unmatched_candidate == (30.16,)  # 【確認内容】: 候補は extra へ 🟡


def test_tol_deg_boundary_deterministic():
    # 【テスト目的】: tol_deg 境界ちょうどの入力でも 2 回実行でビット同一になることを確認 (TC-B03)
    # 【テスト内容】: 境界近傍 (差=0.15) で決定論が破れないかを 2 回実行で検証
    # 【期待される動作】: match_score(...) == match_score(...) (score・matched・unmatched 全一致)
    # 🟡 信頼性レベル: 完了条件5・requirements §3 (NFR-102)・§4.2 からの妥当な推測

    # 【テストデータ準備】: TC-B01 と同一の境界入力 (差=0.15)
    observed = (Peak(position=30.0, height=10.0),)
    candidate = (Peak(position=30.15, height=1.0),)

    # 【実際の処理実行】: 同一境界入力で 2 回計算
    r1 = match_score(candidate, observed, tol_deg=0.15)
    r2 = match_score(candidate, observed, tol_deg=0.15)

    # 【結果検証】: 境界近傍でもビット同一
    assert r1 == r2  # 【確認内容】: 境界判定が決定論 (approx でなく ==) 🟡


def test_greedy_one_to_one_no_duplicate_match():
    # 【テスト目的】: 貪欲一致で 1 観測ピークが高々 1 候補にマッチ (1:1 重複防止) することを確認 (TC-B04)
    # 【テスト内容】: 2 候補が 1 観測の tol_deg 内に競合する構成で重複カウントと順序依存を検証
    # 【期待される動作】: matched_observed==(0,) (重複なし)、片方が extra、入力順を変えても本数不変
    # 🟡 信頼性レベル: requirements §3 (貪欲一致重複防止)・§7 確定事項#6 からの妥当な推測

    # 【テストデータ準備】: 観測 1 本 (30.0)、候補 2 本 (29.95, 30.05) はともに tol_deg 内
    observed = (Peak(position=30.0, height=10.0),)
    candidate = (Peak(position=29.95, height=1.0), Peak(position=30.05, height=1.0))

    # 【実際の処理実行】: 通常順・入力逆順の 2 通りで match_score を計算
    result = match_score(candidate, observed)
    swapped = (Peak(position=30.05, height=1.0), Peak(position=29.95, height=1.0))
    result_sw = match_score(swapped, observed)

    # 【結果検証】: 1 観測は 1 回のみ、片方 extra、順序非依存
    assert result.matched_observed == (0,)  # 【確認内容】: 観測 index 0 は 1 回のみ (重複防止) 🟡
    assert len(result.unmatched_candidate) == 1  # 【確認内容】: 競合の片方が extra 🟡
    assert result_sw.matched_observed == (0,)  # 【確認内容】: 入力順を変えても観測 1 回のみ 🟡
    assert len(result_sw.unmatched_candidate) == 1  # 【確認内容】: 入力順に依らず extra 1 本 🟡


def test_extra_calculated_aggregates_sorted_unique():
    # 【テスト目的】: 複数候補の extra を昇順・重複排除で集約することを確認 (TC-B05)
    # 【テスト内容】: 重複位置 (25.0) を含む 2 候補の unmatched_candidate を集約し規則を検証
    # 【期待される動作】: extra_calculated == (25.0, 40.0, 60.0) (昇順・25.0 は 1 回のみ)
    # 🔵 信頼性レベル: requirements §2.2 (extra_calculated 昇順・重複排除)・interfaces.py に直接依拠

    # 【テストデータ準備】: 25.0 が 2 候補で重複、40.0/60.0 は非重複の MatchResult 2 件
    r0 = MatchResult(
        candidate_index=0, score=0.0, matched_observed=(), unmatched_candidate=(25.0, 40.0)
    )
    r1 = MatchResult(
        candidate_index=1, score=0.0, matched_observed=(), unmatched_candidate=(25.0, 60.0)
    )

    # 【実際の処理実行】: 観測は任意 (空) で extra 集約のみ検証
    report = unmatched_peaks([r0, r1], observed_peaks=())

    # 【結果検証】: 重複排除と昇順整列が両立
    assert report.extra_calculated == (25.0, 40.0, 60.0)  # 【確認内容】: 昇順・25.0 は 1 回のみ 🔵
