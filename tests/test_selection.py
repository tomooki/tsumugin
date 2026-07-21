"""TASK-0020 ReviewQueue + detect_escalations の失敗テスト (TDD Red)。

対象実装 (すべて未実装):
- ``src/tsumugin/selection/engine.py``: 純粋関数 ``detect_escalations`` (4 条件検出)
- ``src/tsumugin/selection/review_queue.py``: ``ReviewItem`` (frozen) / ``ReviewQueue`` (追記型)
- ``src/tsumugin/selection/__init__.py``: 上記 + ``EscalationReason`` の re-export

detect_escalations は ``SearchResult`` を非破壊で読み取り、エスカレーション 4 条件
((a) all_high_r / (b) unknown_phase / (c) close_competitor / (d) guard_escalated) を宣言順の
tuple で返す純粋関数。ReviewQueue は削除 API を持たない追記型キュー (P2 / NFR-101)。

書式は ``tests/test_model_m2.py`` を範とし、frozen 検証は ``dataclasses.FrozenInstanceError``、
テストダブルは要件定義のテストダブル設計方針 (実 SearchResult を最小フィールドで構築) に従う。
テストケース定義 (19 件: 正常系 10 / 異常系 3 / 境界値 6) に 1:1 対応する。

未実装のため ``tsumugin.selection`` の import が collection 時に失敗し、本ファイルの全テストが
エラー(=失敗)になる想定 (Red フェーズ)。
"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.evidence.base import EvidenceResult
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.model import Hypothesis, RefinementMetrics
from tsumugin.refinement.staged import RefinementReport
from tsumugin.search.matcher import UnmatchedPeakReport
from tsumugin.search.tree import SearchResult
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

# 【未実装 import】: selection パッケージは本タスクで新設。collection 時にここで失敗する (Red) 🔵
from tsumugin.selection import ReviewItem, ReviewQueue, detect_escalations


# ---------------------------------------------------------------------------
# テストダブルヘルパ (要件定義「テストダブル設計方針」に準拠)
# ---------------------------------------------------------------------------


def _ranked(hyp_id: str, rwp: float, close: bool) -> RankedHypothesis:
    # 【テストデータ準備】: rwp と close_competitor だけ意味を持つ最小 RankedHypothesis
    # 【初期条件設定】: detect_escalations が読むのは metrics.rwp と close_competitor のみ 🔵
    m = RefinementMetrics(rwp=rwp, gof=1.0, chi2=1.0, n_obs=100, n_params=5, evidence={"bic": 0.0})
    h = Hypothesis(id=hyp_id, phases=(), metrics=m, status="refined")
    ev = EvidenceResult(backend="bic", value=0.0)
    return RankedHypothesis(hypothesis=h, evidence=ev, probability=0.5, close_competitor=close)


def _result(ranked, *, unknown_phase: bool = False, final_reports=None) -> SearchResult:
    # 【テストデータ準備】: 木探索を回さず ranked / unmatched だけを最小構成した軽量 SearchResult
    # 【初期条件設定】: ledger/snapshots は空で純粋関数の非破壊検証に足りる 🔵
    led = Ledger()
    return SearchResult(
        ranked=tuple(ranked),
        hypotheses={r.hypothesis.id: r.hypothesis for r in ranked},
        good_cluster_ids=(),
        alternatives={},
        unmatched=UnmatchedPeakReport(
            unmatched_observed=(), extra_calculated=(), unknown_phase_flag=unknown_phase
        ),
        final_reports=final_reports or {},
        ledger=led,
        snapshots=SnapshotStore(ledger=led),
        warnings=(),
    )


def _report(escalated: bool) -> RefinementReport:
    # 【テストデータ準備】: escalated だけ意味を持つ最小 RefinementReport (FR-212 配線用)
    m = RefinementMetrics(rwp=10.0, gof=1.0, chi2=1.0, n_obs=100, n_params=5, evidence={"bic": 0.0})
    return RefinementReport(
        final_phases=(), metrics=m, stage_outcomes=(), escalated=escalated
    )


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_detect_all_high_r_single():
    # 【テスト目的】: 全 ranked 仮説の Rwp が閾値超過のとき ("all_high_r",) を返す (N-01)
    # 【テスト内容】: Rwp 45/50% (>30) の 2 仮説を detect_escalations に渡す
    # 【期待される動作】: (a) 全高 R のみ発火し他 3 条件は非発火
    # 🔵 信頼性: 要件定義 2.2 / D6 (a) / TC-107-06 / tree.py L855 の厳密比較

    # 【テストデータ準備】: どの仮説も観測を説明できていない高 R 状況
    # 【初期条件設定】: unknown_phase=False、2 位 close=False、staged=False で (a) のみ発火させる
    result = _result([_ranked("h0", 45.0, False), _ranked("h1", 50.0, False)], unknown_phase=False)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: 各 metrics.rwp が high_r_threshold=30.0 を厳密超過するか判定
    reasons = detect_escalations(result, staged_escalated=False, high_r_threshold=30.0)

    # 【結果検証】: all_high_r のみが返ること
    # 【期待値確認】: 全件閾値超過のときのみ (a) が単独発火する
    assert reasons == ("all_high_r",)  # 【確認内容】: 全高 R の単独検出 🔵


def test_detect_unknown_phase_single():
    # 【テスト目的】: unmatched.unknown_phase_flag=True のとき ("unknown_phase",) を返す (N-02)
    # 【テスト内容】: Rwp は低い (良好) が未知相フラグが立った SearchResult を渡す
    # 【期待される動作】: (b) 未知相のみ発火し他は非発火
    # 🔵 信頼性: 要件定義 2.2 / D6 (b) / TC-107-06

    # 【テストデータ準備】: Rwp 5/8% (良好) だが最良仮説で説明できない観測ピークが残る
    # 【初期条件設定】: unknown_phase=True、2 位 close=False、staged=False で (b) のみ発火させる
    result = _result([_ranked("h0", 5.0, False), _ranked("h1", 8.0, False)], unknown_phase=True)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: SearchResult 側の集約結果 unknown_phase_flag をそのまま (b) の真偽に使う
    reasons = detect_escalations(result, staged_escalated=False)

    # 【結果検証】: unknown_phase のみが返ること
    # 【期待値確認】: 集約済み未知相フラグを信頼して単独発火する
    assert reasons == ("unknown_phase",)  # 【確認内容】: 未知相フラグの単独検出 🔵


def test_detect_close_competitor_single():
    # 【テスト目的】: 2 位仮説が close_competitor=True のとき ("close_competitor",) を返す (N-03)
    # 【テスト内容】: 1-2 位ともに close=True の僅差競合 SearchResult を渡す
    # 【期待される動作】: (c) 僅差競合のみ発火し他は非発火
    # 🔵 信頼性: 要件定義 2.2 / D6 (c) / ranking.py rank / TC-107-06

    # 【テストデータ準備】: 最良と 2 位の ΔBIC が閾値未満 (両者 close=True) の僅差競合
    # 【初期条件設定】: Rwp 低・unknown False・staged False で (c) のみ発火させる
    result = _result([_ranked("h0", 5.0, True), _ranked("h1", 6.0, True)], unknown_phase=False)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: ranked[1] (2 位) の close_competitor フラグを読み取り (c) を判定
    reasons = detect_escalations(result, staged_escalated=False)

    # 【結果検証】: close_competitor のみが返ること
    # 【期待値確認】: 2 位のフラグで判定する (ranked[0] の close=True 単独では発火しない)
    assert reasons == ("close_competitor",)  # 【確認内容】: 2 位僅差の単独検出 🔵


def test_detect_guard_escalated_single():
    # 【テスト目的】: staged_escalated=True のとき ("guard_escalated",) を返す (N-04)
    # 【テスト内容】: ガード N 連続で escalated report が返された状況を bool 引数で与える
    # 【期待される動作】: (d) ガードエスカレーションのみ発火し他は非発火
    # 🔵 信頼性: 要件定義 2.2 / D6 (d) / staged.py escalated / TC-107-06

    # 【テストデータ準備】: Rwp 良好・単一仮説・unknown False で他 3 条件の材料を非発火にする
    # 【初期条件設定】: staged_escalated=True で (d) のみ発火させる
    result = _result([_ranked("h0", 5.0, False)], unknown_phase=False)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: 引数 staged_escalated の bool をそのまま (d) の真偽に使う
    reasons = detect_escalations(result, staged_escalated=True)

    # 【結果検証】: guard_escalated のみが返ること
    # 【期待値確認】: bool を受けるだけで staged 実装に依存しない
    assert reasons == ("guard_escalated",)  # 【確認内容】: ガードエスカレーションの単独検出 🔵


def test_detect_no_escalation_returns_empty_tuple():
    # 【テスト目的】: 4 条件すべて非該当のとき空タプル () を返す (N-05, 完了条件②)
    # 【テスト内容】: 良好 Rwp・未知相なし・僅差なし・ガード正常の自動 accept 相当を渡す
    # 【期待される動作】: エスカレーションなし = 空タプル (過検出しない)
    # 🔵 信頼性: 要件定義 4.3 / 完了条件② / dataflow.md L88-89

    # 【テストデータ準備】: 明確な最良仮説あり・Rwp 5/7% (良好)・2 位 close=False
    # 【初期条件設定】: unknown_phase=False、staged=False で全条件を非発火にする
    result = _result([_ranked("h0", 5.0, False), _ranked("h1", 7.0, False)], unknown_phase=False)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: (a)〜(d) すべて False になることを確認する
    reasons = detect_escalations(result, staged_escalated=False)

    # 【結果検証】: 空タプルが返ること
    # 【期待値確認】: agent 自動 accept 経路の前提 (過検出しない)
    assert reasons == ()  # 【確認内容】: 条件なしで空タプル 🔵


def test_detect_all_four_conditions_declaration_order():
    # 【テスト目的】: 4 条件同時発火時に宣言順のタプルを返す (N-06, TC-107-06 + NFR-102)
    # 【テスト内容】: 全高 R + 未知相 + 僅差 + ガード発動が同時に起きる最悪ケースを渡す
    # 【期待される動作】: all_high_r → unknown_phase → close_competitor → guard_escalated の固定順
    # 🔵 信頼性: 要件定義 2.2 返り値順序 / NFR-102 / interfaces.py L299-301 宣言順

    # 【テストデータ準備】: Rwp 45/50% (高 R) かつ 1-2 位 close=True の僅差
    # 【初期条件設定】: unknown_phase=True、staged_escalated=True で 4 条件を同時発火させる
    result = _result([_ranked("h0", 45.0, True), _ranked("h1", 50.0, True)], unknown_phase=True)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: 発火した reason を EscalationReason 宣言順に並べる
    reasons = detect_escalations(result, staged_escalated=True)

    # 【結果検証】: 宣言順の 4 要素タプルが返ること
    # 【期待値確認】: 返り値順序がビット同一で固定される (NFR-102 決定論)
    assert reasons == (
        "all_high_r",
        "unknown_phase",
        "close_competitor",
        "guard_escalated",
    )  # 【確認内容】: 4 条件同時発火時の宣言順タプル 🔵


def test_review_queue_add_creates_review_item():
    # 【テスト目的】: add(reason, ...) が item_id="rq-0000"・resolved=False の ReviewItem を返す (N-07)
    # 【テスト内容】: 僅差競合を全フィールド指定で Queue へ追記する
    # 【期待される動作】: 追加順連番 item_id を採番し全フィールドを保持して返す
    # 🔵 信頼性: 要件定義 2.3/2.4 / interfaces.py L304-323

    # 【テストデータ準備】: ledger 未注入の単体 ReviewQueue
    # 【初期条件設定】: 代表的な追記 (hypothesis_id/frame_index/detail をすべて指定)
    q = ReviewQueue()

    # 【実際の処理実行】: エスカレーションを Queue へ追記
    # 【処理内容】: item_id を採番し ReviewItem(resolved=False) を生成して内部列へ追記
    item = q.add("close_competitor", hypothesis_id="hyp-0003", frame_index=12, detail="ΔBIC=4.2")

    # 【結果検証】: 生成された ReviewItem の各フィールドと items への反映
    # 【期待値確認】: 初回 item_id は rq-0000、resolved 既定 False
    assert isinstance(item, ReviewItem)  # 【確認内容】: 返り値が ReviewItem 型 🔵
    assert item.item_id == "rq-0000"  # 【確認内容】: 追加順連番の起点 rq-0000 🔵
    assert item.reason == "close_competitor"  # 【確認内容】: reason を保持 🔵
    assert item.hypothesis_id == "hyp-0003"  # 【確認内容】: hypothesis_id を保持 🔵
    assert item.frame_index == 12  # 【確認内容】: frame_index を保持 🔵
    assert item.detail == "ΔBIC=4.2"  # 【確認内容】: detail を保持 🔵
    assert item.resolved is False  # 【確認内容】: resolved 既定 False 🔵
    assert q.items == (item,)  # 【確認内容】: items に追記された 1 件 🔵


def test_review_queue_resolve_marks_resolved_and_keeps_item():
    # 【テスト目的】: resolve 後、当該 item が items に残り resolved=True になる (N-08, 件数不変)
    # 【テスト内容】: 1 件 add → resolve し items 件数と resolved を確認する
    # 【期待される動作】: 解決は削除でなく resolved=True への状態遷移 (追記表現, P2)
    # 🔵 信頼性: 要件定義 2.4 / 完了条件③ / TC-107-07 / P2

    # 【テストデータ準備】: 全高 R を 1 件通知した Queue
    # 【初期条件設定】: 人間が Review Queue の 1 件を後追い解決する実運用フロー
    q = ReviewQueue()
    q.add("all_high_r")

    # 【実際の処理実行】: item_id="rq-0000" を解決する
    # 【処理内容】: dataclasses.replace(item, resolved=True) で件数を減らさず差し替える
    resolved = q.resolve("rq-0000", note="確認済み")

    # 【結果検証】: 返り値と items の状態
    # 【期待値確認】: items 件数は resolve で減らず resolved が True になる
    assert resolved.resolved is True  # 【確認内容】: 返り値が resolved=True 🔵
    assert resolved.item_id == "rq-0000"  # 【確認内容】: 対象 item_id が一致 🔵
    assert len(q.items) == 1  # 【確認内容】: 件数不変 (追記型) 🔵
    assert q.items[0].resolved is True  # 【確認内容】: items 上でも resolved=True 🔵


def test_review_queue_unresolved_returns_only_unresolved():
    # 【テスト目的】: unresolved が未解決の item のみを返す派生ビューであること (N-09)
    # 【テスト内容】: 2 件 add → 1 件 resolve し items と unresolved の件数差を確認する
    # 【期待される動作】: unresolved は items から resolved=False を絞り込む
    # 🔵 信頼性: 要件定義 2.4 / interfaces.py L323-325

    # 【テストデータ準備】: 2 件通知し 1 件 (rq-0000) を解決した状態
    # 【初期条件設定】: items は全件・unresolved は未解決のみ、で件数が食い違う
    q = ReviewQueue()
    q.add("all_high_r")
    q.add("unknown_phase")
    q.resolve("rq-0000")

    # 【実際の処理実行】: 全件ビューと未解決ビューを取得
    # 【処理内容】: items から resolved=False を絞り込んだ派生ビューを検証
    items = q.items
    unresolved = q.unresolved

    # 【結果検証】: 件数と未解決 item の同定
    # 【期待値確認】: items 2 件・unresolved 1 件、残るのは rq-0001
    assert len(items) == 2  # 【確認内容】: items は全件 (減らない) 🔵
    assert len(unresolved) == 1  # 【確認内容】: unresolved は未解決のみ 🔵
    assert unresolved[0].item_id == "rq-0001"  # 【確認内容】: 残る未解決は rq-0001 🔵
    assert unresolved[0].resolved is False  # 【確認内容】: 未解決 item は resolved=False 🔵


def test_review_queue_ledger_records_add_and_resolve():
    # 【テスト目的】: ledger 注入時に add→review_add / resolve→review_resolve が記録される (N-10)
    # 【テスト内容】: Ledger() を注入し add/resolve 後に ledger.entries の kind を検証する
    # 【期待される動作】: kind と追記順が記録され verify() が True を保つ
    # 🟡 信頼性: 要件定義 2.4 / D-Q7。kind 名 review_add/review_resolve は D-Q7 からの妥当な命名

    # 【テストデータ準備】: 実 Ledger を注入した ReviewQueue
    # 【初期条件設定】: add→resolve の順で操作し ledger 連携を検証
    led = Ledger()
    q = ReviewQueue(ledger=led)
    q.add("close_competitor", hypothesis_id="h1")
    q.resolve("rq-0000", note="ok")

    # 【実際の処理実行】: ledger のエントリ列を取得
    # 【処理内容】: kind 名・追記順・ハッシュチェーン整合性・payload 内容を確認
    kinds = [e.kind for e in led.entries]

    # 【結果検証】: kind 名と追記順、verify、payload
    # 【期待値確認】: review_add → review_resolve の順で記録され verify True を保つ
    assert kinds == ["review_add", "review_resolve"]  # 【確認内容】: kind 名と追記順 🟡
    assert led.verify() is True  # 【確認内容】: ハッシュチェーン整合性 🔵
    add_payload = led.entries[0].payload
    resolve_payload = led.entries[1].payload
    assert add_payload["item_id"] == "rq-0000"  # 【確認内容】: review_add に item_id 🔵
    assert add_payload["reason"] == "close_competitor"  # 【確認内容】: review_add に reason 🔵
    assert resolve_payload["item_id"] == "rq-0000"  # 【確認内容】: review_resolve に item_id 🔵
    assert resolve_payload["note"] == "ok"  # 【確認内容】: review_resolve に note 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング）
# ---------------------------------------------------------------------------


def test_review_item_is_frozen():
    # 【テスト目的】: frozen dataclass ReviewItem のフィールドへ再代入すると例外になる (E-01)
    # 【テスト内容】: add で得た ReviewItem の resolved へ直接代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError が送出される
    # 🔵 信頼性: 要件定義 2.3/3 frozen 制約 / test_model_m2.py の frozen 検証パターン

    # 【テストデータ準備】: Queue から取得した ReviewItem
    # 【初期条件設定】: frozen=True では属性再代入が禁止されている
    q = ReviewQueue()
    item = q.add("all_high_r")

    # 【実際の処理実行 & 結果検証】: 再代入で FrozenInstanceError を送出させる
    # 【期待値確認】: 状態変更は必ず replace 経由 (新インスタンス) に強制される
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.resolved = True  # 【確認内容】: frozen のため再代入不可 🔵


def test_review_queue_has_no_delete_api():
    # 【テスト目的】: ReviewQueue に削除系メソッドが存在しないこと (E-02, P2 構造的非破壊性)
    # 【テスト内容】: delete/remove/pop/clear の不在と add/resolve の存在を hasattr で確認する
    # 【期待される動作】: 削除系はすべて False、正規 API は True
    # 🔵 信頼性: 要件定義 3 P2 制約 / TC-107-07 / ledger.py の削除 API 不在パターン

    # 【テストデータ準備】: 空の ReviewQueue
    # 【初期条件設定】: 履歴が構造的に消せないことを担保する
    q = ReviewQueue()

    # 【結果検証】: 削除系 API の不在と正規 API の存在
    # 【期待値確認】: 追記性を破壊する API は一切生えていない
    assert not hasattr(q, "delete")  # 【確認内容】: delete 不在 🔵
    assert not hasattr(q, "remove")  # 【確認内容】: remove 不在 🔵
    assert not hasattr(q, "pop")  # 【確認内容】: pop 不在 🔵
    assert not hasattr(q, "clear")  # 【確認内容】: clear 不在 🔵
    assert hasattr(q, "add")  # 【確認内容】: add は存在 🔵
    assert hasattr(q, "resolve")  # 【確認内容】: resolve は存在 🔵


def test_resolve_unknown_item_id_raises():
    # 【テスト目的】: 存在しない item_id を resolve に渡すと防御的に例外になる (E-03)
    # 【テスト内容】: add せずに未知 item_id を resolve し、例外と ledger 非記録を確認する
    # 【期待される動作】: KeyError または ValueError を送出し review_resolve を追記しない
    # 🟡 信頼性: 要件定義 2.4/4.3 の縮退記述からの妥当な推測 (完了条件外の防御的挙動)

    # 【テストデータ準備】: ledger 注入済みだが item を一度も add していない Queue
    # 【初期条件設定】: item_id="rq-9999" は存在しない (誤操作シナリオ)
    led = Ledger()
    q = ReviewQueue(ledger=led)

    # 【実際の処理実行 & 結果検証】: 未知 item_id で例外を送出させる
    # 【期待値確認】: 存在しない解決を「解決した」と誤認させない
    with pytest.raises((KeyError, ValueError)):
        q.resolve("rq-9999")  # 【確認内容】: 未知 item_id は防御的に例外 🟡

    # 【追加検証】: 存在しない解決を ledger に記録しない
    assert all(e.kind != "review_resolve" for e in led.entries)  # 【確認内容】: 誤記録なし 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値、最大値、null等）
# ---------------------------------------------------------------------------


def test_empty_ranked_no_all_high_r_or_close_competitor():
    # 【テスト目的】: 空 ranked で all_high_r / close_competitor が発火しないこと (B-01)
    # 【テスト内容】: ranked=() の候補ゼロ経路を detect_escalations に渡す
    # 【期待される動作】: all() の真空的 True を回避し空タプルを返す
    # 🔵 信頼性: 要件定義 2.2 (a) 空ガード / 4.3 / tree.py 空縮退パターン

    # 【テストデータ準備】: 候補が枝刈りされ ranked が空になったフレーム
    # 【初期条件設定】: unknown_phase=False、staged=False で他条件も非発火にする
    result = _result([], unknown_phase=False)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: 空集合で all_high_r を誤って立てないこと・2 位不在で close も立てないこと
    reasons = detect_escalations(result, staged_escalated=False)

    # 【結果検証】: 空タプルが返ること
    # 【期待値確認】: 空 ranked で過検出しない (真空的 True 回避・2 位不在)
    assert reasons == ()  # 【確認内容】: 空 ranked での縮退挙動 🔵


def test_all_high_r_threshold_exact_no_fire():
    # 【テスト目的】: Rwp が閾値ちょうど (== threshold) では all_high_r が発火しないこと (B-02)
    # 【テスト内容】: Rwp=30.0 の 2 仮説に high_r_threshold=30.0 を適用する
    # 【期待される動作】: 厳密超過 `>` で判定し閾値ちょうどは高 R に含めない
    # 🔵 信頼性: 要件定義 3 境界の厳密比較 / tree.py L855

    # 【テストデータ準備】: Rwp がちょうど閾値のフレーム (>と>=の差が現れる唯一の境界点)
    # 【初期条件設定】: unknown False・2 位 close=False・staged False で (a) の境界のみ検証
    result = _result([_ranked("h0", 30.0, False), _ranked("h1", 30.0, False)])

    # 【実際の処理実行】: 閾値ちょうどでエスカレーション条件を検出
    # 【処理内容】: rwp > 30.0 は 30.0 で False になる
    reasons = detect_escalations(result, high_r_threshold=30.0)

    # 【結果検証】: all_high_r が発火せず空タプルになること
    # 【期待値確認】: 境界値でのオフバイワンを防ぐ (tree.py L855 と表現統一)
    assert reasons == ()  # 【確認内容】: 閾値ちょうどは高 R に含めない 🔵


def test_single_ranked_no_close_competitor():
    # 【テスト目的】: ranked 1 件のみでは close_competitor が発火しないこと (B-03)
    # 【テスト内容】: ranked[0].close=True だが 2 位不在の SearchResult を渡す
    # 【期待される動作】: len(ranked) >= 2 を満たさず (c) は非発火
    # 🔵 信頼性: 要件定義 2.2 (c) / D6 (c) / ranking.py rank ranked[0] は常に close=True

    # 【テストデータ準備】: 唯一の最良仮説 (ranked[0].close=True の罠を検証)
    # 【初期条件設定】: Rwp 良好・unknown False・staged False で (c) の境界のみ検証
    result = _result([_ranked("h0", 5.0, True)], unknown_phase=False)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: ranked[0] の close=True を無視し 2 位のフラグで判定する
    reasons = detect_escalations(result, staged_escalated=False)

    # 【結果検証】: 空タプルが返ること
    # 【期待値確認】: 単一最良仮説を僅差競合と誤検出しない (D6「1-2 位」の解釈)
    assert reasons == ()  # 【確認内容】: 2 位不在で close_competitor 非発火 🔵


def test_item_id_sequential_deterministic():
    # 【テスト目的】: 連続追加で item_id が rq-0000 → rq-0001 → rq-0002 と採番されること (B-04)
    # 【テスト内容】: 同一 Queue に 3 回 add し item_id 列を確認する
    # 【期待される動作】: 追加順に単調増加する一意 item_id (0 起点・4 桁ゼロ埋め)
    # 🔵 信頼性: 要件定義 2.4 / 完了条件⑤ / NFR-102

    # 【テストデータ準備】: 1 回の裁定で複数エスカレーションが同時に入る想定
    # 【初期条件設定】: 乱数不使用でビット同一の連番採番
    q = ReviewQueue()
    for _ in range(3):
        q.add("all_high_r")

    # 【実際の処理実行】: 追記された全 item の item_id 列を取得
    # 【処理内容】: "rq-{n:04d}" 形式で 0 起点連番になることを確認
    item_ids = [i.item_id for i in q.items]

    # 【結果検証】: item_id 列が期待どおりの連番であること
    # 【期待値確認】: 同一操作列で毎回同一 ID 列 (決定論)
    assert item_ids == ["rq-0000", "rq-0001", "rq-0002"]  # 【確認内容】: 連番採番の決定論 🔵


def test_high_r_threshold_custom_value():
    # 【テスト目的】: high_r_threshold 引数のカスタム値が判定に反映されること (B-05)
    # 【テスト内容】: 同じ Rwp=25 を閾値 20 と閾値 30 の 2 通りで判定する
    # 【期待される動作】: 25>20 で高 R、25<=30 で非高 R に切り替わる
    # 🔵 信頼性: 要件定義 2.2 引数仕様 / interfaces.py L341 / tree.py L90

    # 【テストデータ準備】: Rwp=25% の単一仮説 (閾値で判定が分かれる値)
    # 【初期条件設定】: 呼び出し側が SearchConfig の閾値等を渡すケースを模す
    result = _result([_ranked("h0", 25.0, False)])

    # 【実際の処理実行】: 2 通りの閾値で条件を検出
    # 【処理内容】: 引数 high_r_threshold が判定式に正しく渡ることを確認
    reasons_low = detect_escalations(result, high_r_threshold=20.0)
    reasons_high = detect_escalations(result, high_r_threshold=30.0)

    # 【結果検証】: 閾値ごとに判定が切り替わること
    # 【期待値確認】: 20 では発火 (25>20)、30 では非発火 (25<=30)
    assert reasons_low == ("all_high_r",)  # 【確認内容】: 閾値 20 で高 R 発火 🔵
    assert reasons_high == ()  # 【確認内容】: 閾値 30 で非発火 🔵


def test_detect_escalations_is_pure():
    # 【テスト目的】: detect_escalations が純粋関数であること (B-06, SearchResult 非破壊 + 冪等)
    # 【テスト内容】: 同一 result を 2 回渡し返り値ビット同一・入力不変・ledger 非追記を確認する
    # 【期待される動作】: 副作用ゼロ・冪等 (D6 純粋関数 / NFR-102 ビット同一)
    # 🔵 信頼性: 要件定義 3 純粋関数制約 / D6 / NFR-102 / REQ-402

    # 【テストデータ準備】: 4 条件同時発火の result (N-06 と同型)
    # 【初期条件設定】: 呼び出し前の入力状態と ledger 件数を記録する
    result = _result([_ranked("h0", 45.0, True), _ranked("h1", 50.0, True)], unknown_phase=True)
    before_ranked = result.ranked
    before_unmatched = result.unmatched
    before_entries = len(result.ledger.entries)

    # 【実際の処理実行】: 同一 result を 2 回呼ぶ
    # 【処理内容】: 返り値の等価性と入力・ledger の不変性を確認する
    first = detect_escalations(result, staged_escalated=True)
    second = detect_escalations(result, staged_escalated=True)

    # 【結果検証】: 冪等性と非破壊性
    # 【期待値確認】: 2 回の返り値が等価・入力不変・ledger に書かない
    assert first == second  # 【確認内容】: 同一入力でビット同一 🔵
    assert result.ranked == before_ranked  # 【確認内容】: ranked 非破壊 🔵
    assert result.unmatched == before_unmatched  # 【確認内容】: unmatched 非破壊 🔵
    assert len(result.ledger.entries) == before_entries  # 【確認内容】: ledger に書かない 🔵


# ===========================================================================
# TASK-0021: Decision / FinalSelectionEngine の失敗テスト (TDD Red / 17 件)
#
# 対象実装 (未実装): tsumugin.selection.Decision / FinalSelectionEngine。
# import はファイル冒頭でなく各テスト関数内で行う。冒頭 import で未実装シンボルを参照すると
# collection が失敗し TASK-0020 の既存 19 テストまで巻き込んで fail するため。関数内 import なら
# 新規 17 件のみ ImportError で fail し、既存 19 件は pass を維持できる (Red フェーズの分離)。
# 既存ヘルパ _ranked / _result を流用する (テストダブル方針)。
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. 正常系テストケース（基本的な動作）
# ---------------------------------------------------------------------------


def test_agent_clear_best_auto_accepts():
    # 【テスト目的】: agent + エスカレーションゼロ + best 非僅差で自動 accept される (N-01)
    # 【テスト内容】: decide が accepted_by="agent" の新 Hypothesis を返しレジストリへ登録する
    # 【期待される動作】: accepted!=None / status=="accepted" / escalations==() / provisional なし
    # 🔵 信頼性: TC-107-01 / REQ-102 / interview Q8 に直接対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: rwp 低め・close=False の 2 仮説で all_high_r/close を誤発火させない
    # 【初期条件設定】: agent モード + 注入 Ledger で自動 accept 経路を検証する
    led = Ledger()
    engine = FinalSelectionEngine(mode="agent", ledger=led)
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 12.0, False)])

    # 【実際の処理実行】: 単一 SearchResult に対し agent 裁定を実行
    # 【処理内容】: Q8 4 条件を満たすため best (ranked[0]) を by="agent" で自動 accept する
    d = engine.decide(result)

    # 【結果検証】: 自動 accept 成立と accepted_by / レジストリ登録を確認
    # 【期待値確認】: best が accepted 化され escalation なしで完了する
    assert d.accepted is not None  # 【確認内容】: 自動 accept 成立 🔵
    assert d.accepted.status == "accepted"  # 【確認内容】: 新 Hypothesis が accepted 状態 🔵
    assert d.accepted.accepted_by == "agent"  # 【確認内容】: 採択主体が agent 🔵
    assert d.accepted.id == "h1"  # 【確認内容】: 対象は best=ranked[0] 🔵
    assert d.escalations == ()  # 【確認内容】: エスカレーションなし 🔵
    assert d.provisional_id is None  # 【確認内容】: 暫定裁定でない 🔵
    assert engine.accepted["h1"].status == "accepted"  # 【確認内容】: レジストリに accepted 登録 🔵


def test_agent_close_competitor_provisional_and_queue():
    # 【テスト目的】: agent + 僅差でも例外なく provisional + Review Queue で完了する (N-02)
    # 【テスト内容】: 2 位 close=True でエスカレーション発火 → accept せず暫定裁定 + Queue 通知
    # 【期待される動作】: accepted is None / provisional_id==best / escalations 非空 / 例外なし
    # 🔵 信頼性: TC-107-02 / REQ-102 / FR-403 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: 2 位 close_competitor=True で detect_escalations が close_competitor を返す
    # 【初期条件設定】: queue を注入し暫定時に Queue へ通知されることを検証する
    queue = ReviewQueue()
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 10.0, True)])

    # 【実際の処理実行】: 僅差競合下で agent 裁定を実行 (ブロックしない)
    # 【処理内容】: Q8 (d) 欠如で自動 accept せず best を provisional として記録する
    d = engine.decide(result)

    # 【結果検証】: 暫定裁定・Queue 追加・非 accept・処理完了を確認
    # 【期待値確認】: ブロックせず best を暫定提示し escalation reason を Queue に積む
    assert d.accepted is None  # 【確認内容】: 自動 accept しない 🔵
    assert d.provisional_id == "h1"  # 【確認内容】: 暫定裁定は best 🔵
    assert "close_competitor" in d.escalations  # 【確認内容】: 僅差 escalation を検出 🔵
    assert len(queue.items) >= 1  # 【確認内容】: Review Queue へ通知された 🔵
    assert any(i.reason == "close_competitor" for i in queue.items)  # 【確認内容】: 該当 reason 追加 🔵
    assert len(engine.accepted) == 0  # 【確認内容】: accepted 化はしない 🔵


def test_human_decide_recommends_only():
    # 【テスト目的】: human モードの decide は推奨提示のみで自動 accept しない (N-03)
    # 【テスト内容】: decide が recommended_id=best を返し accepted は None のまま
    # 【期待される動作】: mode=="human" / recommended_id==best / accepted is None / レジストリ空
    # 🔵 信頼性: TC-107-03 前半 / REQ-103 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: 明確な最良仮説 1 件 (agent なら auto accept される条件)
    # 【初期条件設定】: human モードでは自動 accept が絶対に起きないことを検証する
    engine = FinalSelectionEngine(mode="human", ledger=Ledger())
    result = _result([_ranked("h1", 10.0, False)])

    # 【実際の処理実行】: human モードで裁定を実行
    # 【処理内容】: best を recommended_id に載せるのみで accepted 化しない
    d = engine.decide(result)

    # 【結果検証】: 推奨のみ・非 accept・レジストリ空を確認
    # 【期待値確認】: human は明示 accept 前に accepted を作らない
    assert d.mode == "human"  # 【確認内容】: 裁定モードは human 🔵
    assert d.recommended_id == "h1"  # 【確認内容】: 推奨は best 🔵
    assert d.accepted is None  # 【確認内容】: 自動 accept しない 🔵
    assert len(engine.accepted) == 0  # 【確認内容】: レジストリ空 🔵


def test_human_explicit_accept_sets_accepted_by_human():
    # 【テスト目的】: human 明示 accept API で accepted_by="human" になり登録される (N-04)
    # 【テスト内容】: decide 後に accept(result, id, by="human") を呼び新 Hypothesis を得る
    # 【期待される動作】: status=="accepted" / accepted_by=="human" / engine.accepted に登録
    # 🔵 信頼性: TC-107-03 後半 / REQ-013/014 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: N-03 と同じ human engine / result
    # 【初期条件設定】: 単一 accept API 経由で accepted 化することを検証する
    engine = FinalSelectionEngine(mode="human", ledger=Ledger())
    result = _result([_ranked("h1", 10.0, False)])
    engine.decide(result)

    # 【実際の処理実行】: 明示 accept API を human で呼ぶ
    # 【処理内容】: replace(hyp, status="accepted", accepted_by="human") の新インスタンスを返す
    h = engine.accept(result, "h1", by="human")

    # 【結果検証】: accepted_by と登録を確認
    # 【期待値確認】: accepted 化は単一 API 経由・accepted_by を仮説へ記録
    assert h.status == "accepted"  # 【確認内容】: accepted 状態 🔵
    assert h.accepted_by == "human"  # 【確認内容】: 採択主体が human 🔵
    assert h.id == "h1"  # 【確認内容】: 対象仮説 id 一致 🔵
    assert engine.accepted["h1"] == h  # 【確認内容】: レジストリに登録された 🔵


def test_set_mode_records_to_ledger():
    # 【テスト目的】: set_mode がモード切替を ledger に記録する (N-05)
    # 【テスト内容】: agent→human へ切替し ledger payload と切替後の振る舞いを確認する
    # 【期待される動作】: ledger に mode=="human" 記録 / verify True / 切替後は自動 accept しない
    # 🔵 信頼性: TC-107-04 / REQ-104 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: 注入 Ledger 付き agent engine
    # 【初期条件設定】: 実行中いつでも切替可能・切替は追記される
    led = Ledger()
    engine = FinalSelectionEngine(mode="agent", ledger=led)

    # 【実際の処理実行】: モードを human に切替
    # 【処理内容】: mode を更新し payload={"mode":"human"} 相当を ledger に追記する
    engine.set_mode("human")

    # 【結果検証】: ledger 記録・整合性・切替後の振る舞い
    # 【期待値確認】: 切替が素の型で追記され、以後 human として振る舞う
    assert any(e.payload.get("mode") == "human" for e in led.entries)  # 【確認内容】: mode 切替記録 🔵
    assert led.verify() is True  # 【確認内容】: ハッシュチェーン整合 🔵
    d = engine.decide(_result([_ranked("h1", 10.0, False)]))
    assert d.accepted is None  # 【確認内容】: 切替後は human で自動 accept しない 🔵
    assert d.mode == "human"  # 【確認内容】: 現在モードが human 🔵


def test_revert_marks_superseded_and_keeps_history():
    # 【テスト目的】: revert で status=superseded になり旧裁定履歴が ledger に残る (N-06)
    # 【テスト内容】: agent 自動 accept 済み仮説を revert し status と件数を確認する
    # 【期待される動作】: status=="superseded" / レジストリも superseded / ledger 件数が減らない
    # 🟡 信頼性: TC-107-05 (status 遷移詳細) / REQ-202 に準拠
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: agent で h1 を自動 accept 済みの engine
    # 【初期条件設定】: revert は削除でなく状態遷移 (P2) で表現する
    led = Ledger()
    engine = FinalSelectionEngine(mode="agent", ledger=led)
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 12.0, False)])
    engine.decide(result)  # h1 を自動 accept
    before = len(led.entries)

    # 【実際の処理実行】: 採択済み h1 を差し戻す
    # 【処理内容】: replace(hyp, status="superseded") の新インスタンスを返し revert を追記する
    h = engine.revert("h1", note="再検討")

    # 【結果検証】: 状態遷移と履歴保持を確認
    # 【期待値確認】: 削除せず superseded へ遷移し ledger は追記のみ (減らない)
    assert h.status == "superseded"  # 【確認内容】: 返り値が superseded 🟡
    assert engine.accepted["h1"].status == "superseded"  # 【確認内容】: レジストリも superseded 🟡
    assert len(led.entries) > before  # 【確認内容】: revert 追記 + accept 履歴保持 🔵
    assert led.verify() is True  # 【確認内容】: ハッシュチェーン整合 🔵


def test_accept_rationale_recorded_in_ledger():
    # 【テスト目的】: 裁定根拠 (rationale/by/hypothesis_id) が ledger に記録される (N-07)
    # 【テスト内容】: agent 自動 accept 後に Decision.rationale と accept payload を検査する
    # 【期待される動作】: rationale 非空で best.id を含む / payload に by・rationale・hypothesis_id
    # 🔵 信頼性: REQ-014 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: N-01 と同じ agent 自動 accept ケース
    # 【初期条件設定】: 根拠の追跡可能性 (payload は素の型のみ) を検証する
    led = Ledger()
    engine = FinalSelectionEngine(mode="agent", ledger=led)
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 12.0, False)])

    # 【実際の処理実行】: agent 裁定を実行し rationale と ledger を取得
    # 【処理内容】: rationale は best.id / 確率 / evidence 等を固定順で組んだ文字列
    d = engine.decide(result)

    # 【結果検証】: rationale の中身と accept payload の内容
    # 【期待値確認】: 根拠が Decision と ledger の双方から追跡できる
    assert isinstance(d.rationale, str) and d.rationale != ""  # 【確認内容】: rationale 非空 🔵
    assert "h1" in d.rationale  # 【確認内容】: rationale に best.id を含む 🔵
    accept_entries = [e for e in led.entries if e.payload.get("hypothesis_id") == "h1"]
    assert accept_entries  # 【確認内容】: accept が ledger に記録される 🔵
    payload = accept_entries[0].payload
    assert payload.get("by") == "agent"  # 【確認内容】: payload に採択主体 🔵
    assert "rationale" in payload  # 【確認内容】: payload に rationale 相当 🔵


def test_accepted_registry_is_append_only_mapping():
    # 【テスト目的】: accepted レジストリが追記型の読み取り専用 Mapping であること (N-08)
    # 【テスト内容】: human モードで別 result の h1/h2 を accept し keys と型を確認する
    # 【期待される動作】: keys=={"h1","h2"} / 各 status=="accepted" / Mapping インスタンス
    # 🔵 信頼性: REQ-013 / P2 に対応
    from collections.abc import Mapping

    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: 2 つの SearchResult から個別に accept する
    # 【初期条件設定】: 追記のみ・削除 API 不在 (P2) を検証する
    engine = FinalSelectionEngine(mode="human", ledger=Ledger())
    result_a = _result([_ranked("h1", 10.0, False)])
    result_b = _result([_ranked("h2", 10.0, False)])

    # 【実際の処理実行】: h1・h2 を順に accept
    # 【処理内容】: それぞれ accepted 化しレジストリへ追記する
    engine.accept(result_a, "h1", by="human")
    engine.accept(result_b, "h2", by="human")

    # 【結果検証】: keys・status・公開型を確認
    # 【期待値確認】: 複数 accept が追記され Mapping で読み取り専用公開される
    assert set(engine.accepted.keys()) == {"h1", "h2"}  # 【確認内容】: 2 件が追記された 🔵
    assert engine.accepted["h1"].status == "accepted"  # 【確認内容】: h1 accepted 🔵
    assert engine.accepted["h2"].status == "accepted"  # 【確認内容】: h2 accepted 🔵
    assert isinstance(engine.accepted, Mapping)  # 【確認内容】: 読み取り専用 Mapping で公開 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（エラーハンドリング）
# ---------------------------------------------------------------------------


def test_empty_ranked_no_accept_escalation_only():
    # 【テスト目的】: ranked 空 (裁定対象ゼロ) で accept せず処理が完了する (E-01)
    # 【テスト内容】: _result([]) を agent decide し accepted/provisional が None であること
    # 【期待される動作】: accepted is None / provisional_id is None / 例外なし / レジストリ空
    # 🟡 信頼性: EDGE-004 / TC-107-08 は 🟡
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: 候補が全滅し ranked が空になった縮退フレーム
    # 【初期条件設定】: best 不在で accept API を呼ばずエスカレーションのみに落とす
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger())
    result = _result([])

    # 【実際の処理実行】: 裁定対象ゼロで agent 裁定を実行 (落ちない)
    # 【処理内容】: best 不在のため自動 accept を試みず Decision を返す
    d = engine.decide(result)

    # 【結果検証】: 非 accept・非 provisional・レジストリ空を確認
    # 【期待値確認】: best が無い場合は accept を試みない (安全側)
    assert d.accepted is None  # 【確認内容】: accepted 化しない 🟡
    assert d.provisional_id is None  # 【確認内容】: best 不在で provisional なし 🟡
    assert len(engine.accepted) == 0  # 【確認内容】: accept API 未呼び 🟡


def test_accept_unknown_hypothesis_id_raises():
    # 【テスト目的】: 存在しない hypothesis_id を accept すると防御的に例外になる (E-02)
    # 【テスト内容】: result に無い "nope" を accept し例外と非登録を確認する
    # 【期待される動作】: KeyError/ValueError を送出し engine.accepted に登録されない
    # 🟡 信頼性: REQ-013 誤操作防御からの妥当な推測
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: h1 のみを含む result
    # 【初期条件設定】: 存在しない仮説を「採択した」と誤認させない
    engine = FinalSelectionEngine(mode="human", ledger=Ledger())
    result = _result([_ranked("h1", 10.0, False)])

    # 【実際の処理実行 & 結果検証】: 未知 id で例外を送出させる
    # 【期待値確認】: 誤操作は防御的に拒否しレジストリを汚さない
    with pytest.raises((KeyError, ValueError)):
        engine.accept(result, "nope", by="human")  # 【確認内容】: 未知 id は例外 🟡
    assert len(engine.accepted) == 0  # 【確認内容】: 登録されない 🟡


def test_revert_unknown_hypothesis_id_raises():
    # 【テスト目的】: 未 accept / 未知 id を revert すると防御的に例外になる (E-03)
    # 【テスト内容】: 何も accept していない engine で revert("h1") を呼ぶ
    # 【期待される動作】: KeyError/ValueError を送出する
    # 🟡 信頼性: REQ-202 誤操作防御からの妥当な推測
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: accepted レジストリが空の engine
    # 【初期条件設定】: 存在しない裁定を superseded にしない (履歴の一貫性)
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger())

    # 【実際の処理実行 & 結果検証】: 未 accept の id を revert し例外を送出させる
    # 【期待値確認】: レジストリに無い仮説の差し戻しは拒否する
    with pytest.raises((KeyError, ValueError)):
        engine.revert("h1")  # 【確認内容】: 未 accept id は例外 🟡


def test_decision_is_frozen():
    # 【テスト目的】: Decision が frozen で再代入すると例外になる (E-04)
    # 【テスト内容】: decide の返り値 Decision の accepted へ直接代入を試みる
    # 【期待される動作】: dataclasses.FrozenInstanceError を送出する
    # 🔵 信頼性: interfaces.py L328 で @dataclass(frozen=True) 明記
    from tsumugin.selection import Decision, FinalSelectionEngine

    # 【テストデータ準備】: decide で得た Decision インスタンス
    # 【初期条件設定】: 値オブジェクトの不変性を担保する
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger())
    result = _result([_ranked("h1", 10.0, False)])
    d = engine.decide(result)

    # 【実際の処理実行 & 結果検証】: frozen 再代入で FrozenInstanceError を送出させる
    # 【期待値確認】: 裁定結果は生成後に書き換えられない
    assert isinstance(d, Decision)  # 【確認内容】: 返り値が Decision 型 🔵
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.accepted = None  # 【確認内容】: frozen のため再代入不可 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（最小値、最大値、状態不変等）
# ---------------------------------------------------------------------------


def test_agent_best_close_only_provisional():
    # 【テスト目的】: agent + best.close_competitor=True のみ (detect 空) で暫定裁定になる (B-01)
    # 【テスト内容】: 単一 ranked (best.close=True) を decide し自動 accept が阻まれることを確認する
    # 【期待される動作】: accepted is None / provisional_id==best (detect は空でも Q8(b) 欠如)
    # 🔵 信頼性: interview Q8 (b) / note の detect と Q8 close の意味差に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: 単一 ranked かつ best.close=True (2 位不在で detect_escalations は空)
    # 【初期条件設定】: detect が空でも best 自身の close フラグが自動 accept を阻む境界
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger())
    result = _result([_ranked("h1", 10.0, True)])

    # 【実際の処理実行】: best が僅差扱いの単一候補で agent 裁定を実行
    # 【処理内容】: Q8 (b) `ranked[0].close_competitor is False` が偽 → 自動 accept しない
    d = engine.decide(result)

    # 【結果検証】: 非 accept・暫定裁定を確認
    # 【期待値確認】: detect_escalations が空でも Q8(b) 欠如で auto accept しない
    assert d.accepted is None  # 【確認内容】: best.close=True で自動 accept しない 🔵
    assert d.provisional_id == "h1"  # 【確認内容】: best を暫定裁定に載せる 🔵


def test_agent_unknown_phase_only_provisional():
    # 【テスト目的】: agent + unknown_phase_flag=True のみで暫定裁定 + unknown_phase reason (B-02)
    # 【テスト内容】: unknown_phase=True の result を decide し escalation と暫定を確認する
    # 【期待される動作】: accepted is None / "unknown_phase" in escalations / provisional_id==best
    # 🔵 信頼性: interview Q8 (c) / REQ-102 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: best は close=False だが unknown_phase フラグが立った result
    # 【初期条件設定】: 未知相フラグ単独で自動 accept を阻む境界を検証する
    queue = ReviewQueue()
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    result = _result([_ranked("h1", 10.0, False)], unknown_phase=True)

    # 【実際の処理実行】: 未知相フラグ下で agent 裁定を実行
    # 【処理内容】: detect_escalations が unknown_phase を返し Q8 (c) が欠ける → 暫定
    d = engine.decide(result)

    # 【結果検証】: escalation・暫定・Queue 通知を確認
    # 【期待値確認】: 未知相フラグが立つと保留し要確認へ回す
    assert d.accepted is None  # 【確認内容】: 未知相で自動 accept しない 🔵
    assert "unknown_phase" in d.escalations  # 【確認内容】: unknown_phase を検出 🔵
    assert d.provisional_id == "h1"  # 【確認内容】: best を暫定裁定に載せる 🔵
    assert any(i.reason == "unknown_phase" for i in queue.items)  # 【確認内容】: Queue に通知 🔵


def test_decide_and_accept_do_not_mutate_search_result():
    # 【テスト目的】: decide/accept が入力 SearchResult を変更しない (B-03, D5 非破壊)
    # 【テスト内容】: decide→accept 前後で ranked[0] の status/accepted_by と result.ledger を確認
    # 【期待される動作】: status=="refined" / accepted_by is None / result.ledger 件数不変
    # 🔵 信頼性: architecture.md D5 / CLAUDE.md P2 に直接対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: refined 状態の h1 を持つ result を保持する
    # 【初期条件設定】: accepted 化は engine 側の新 Hypothesis に反映し入力は汚さない
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger())
    result = _result([_ranked("h1", 10.0, False)])
    before_entries = len(result.ledger.entries)

    # 【実際の処理実行】: decide (自動 accept) と明示 accept を実行
    # 【処理内容】: いずれも dataclasses.replace の新インスタンスで表現する
    engine.decide(result)
    engine.accept(result, "h1", by="agent")

    # 【結果検証】: 入力 SearchResult の各要素と ledger が不変であること
    # 【期待値確認】: 共有された SearchResult を 1 バイトも変更しない
    assert result.ranked[0].hypothesis.status == "refined"  # 【確認内容】: status 不変 🔵
    assert result.ranked[0].hypothesis.accepted_by is None  # 【確認内容】: accepted_by 不変 🔵
    assert len(result.ledger.entries) == before_entries  # 【確認内容】: result.ledger 不変 🔵


def test_rationale_is_deterministic():
    # 【テスト目的】: 同一入力で rationale と escalations がビット同一 (B-04, NFR-102)
    # 【テスト内容】: 同一 result を独立 engine で 2 回 decide し文字列/タプルの一致を確認する
    # 【期待される動作】: rationale 完全一致 / escalations も順序含め一致
    # 🔵 信頼性: NFR-102 / REQ-402 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: エスカレーションを含む同一 result (rationale に escalations が載る)
    # 【初期条件設定】: 乱数・時刻不使用で固定順に rationale を組む
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 10.0, True)])
    engine1 = FinalSelectionEngine(mode="agent", ledger=Ledger())
    engine2 = FinalSelectionEngine(mode="agent", ledger=Ledger())

    # 【実際の処理実行】: 独立した 2 engine で同一 result を裁定
    # 【処理内容】: 同一入力なら分岐・rationale・返り値はビット同一になるはず
    d1 = engine1.decide(result)
    d2 = engine2.decide(result)

    # 【結果検証】: rationale と escalations の一致
    # 【期待値確認】: 再現性 (同一入力で同一出力) を担保する
    assert d1.rationale == d2.rationale  # 【確認内容】: rationale がビット同一 🔵
    assert d1.escalations == d2.escalations  # 【確認内容】: escalations も順序含め一致 🔵


def test_revert_ledger_count_never_decreases():
    # 【テスト目的】: revert 後も ledger 件数が減らない (B-05, 追記型)
    # 【テスト内容】: accept 済み仮説を revert した前後で led.entries 件数を比較する
    # 【期待される動作】: revert 後件数 > revert 前件数 / verify True
    # 🔵 信頼性: CLAUDE.md P2/NFR-105 / REQ-202 に対応
    from tsumugin.selection import FinalSelectionEngine

    # 【テストデータ準備】: agent で h1 を自動 accept 済みの engine
    # 【初期条件設定】: 削除・上書き不在で件数は単調増加する
    led = Ledger()
    engine = FinalSelectionEngine(mode="agent", ledger=led)
    result = _result([_ranked("h1", 10.0, False)])
    engine.decide(result)  # h1 auto accept
    before = len(led.entries)

    # 【実際の処理実行】: 採択済み h1 を revert
    # 【処理内容】: revert エントリが追記され元 accept エントリは残る
    engine.revert("h1")

    # 【結果検証】: 件数の単調増加とハッシュチェーン整合
    # 【期待値確認】: revert は削除でなく追記で表現される
    assert len(led.entries) > before  # 【確認内容】: 件数が減らず増える 🔵
    assert led.verify() is True  # 【確認内容】: ハッシュチェーン整合維持 🔵


# ---------------------------------------------------------------------------
# 6. FR-212 段階解放エスカレーションの自動配線
# ---------------------------------------------------------------------------
#
# 回帰の背景: StagedRefinementEngine の 3 連続失敗フラグ (RefinementReport.escalated) は
# search/tree.py で ledger に載るだけで、detect_escalations の staged_escalated には
# **実運用の呼び出し側から一度も渡されていなかった** (テストのみ手動指定)。結果、仕様
# FR-212「3 回失敗で Triage へ」が実質未発火だった。SearchResult.final_reports に情報は
# 既に届いているので、明示指定が無いときはそこから導出する。


def test_guard_escalation_derived_from_final_reports():
    # 【テスト目的】: 呼び出し側が staged_escalated を渡さなくても final_reports から拾う (FR-212)
    # 【期待される動作】: escalated=True の report が 1 つでもあれば guard_escalated が発火
    result = _result([_ranked("h1", 10.0, False)],
                     final_reports={"h1": _report(True)})

    reasons = detect_escalations(result)  # 明示引数なし = 実運用の呼ばれ方

    assert reasons == ("guard_escalated",)  # 【確認内容】: 自動導出で発火 🔵


def test_no_guard_escalation_when_no_report_escalated():
    # 【テスト目的】: escalated=False のみなら発火しない (偽陽性を出さない)
    result = _result([_ranked("h1", 10.0, False)],
                     final_reports={"h1": _report(False), "h2": _report(False)})

    assert detect_escalations(result) == ()  # 【確認内容】: 非発火 🔵


def test_explicit_staged_escalated_overrides_derivation():
    # 【テスト目的】: 明示指定は導出より優先する (既存呼び出しの後方互換)
    # 【期待される動作】: final_reports が escalated でも False 明示なら非発火
    result = _result([_ranked("h1", 10.0, False)],
                     final_reports={"h1": _report(True)})

    assert detect_escalations(result, staged_escalated=False) == ()  # 【確認内容】: 明示優先 🔵
    assert detect_escalations(result, staged_escalated=True) == ("guard_escalated",)


def test_decide_surfaces_derived_guard_escalation():
    # 【テスト目的】: FinalSelectionEngine.decide が導出済みエスカレーションを裁定に反映する
    # 【期待される動作】: guard_escalated 検出時は agent モードでも自動 accept しない (暫定裁定)
    from tsumugin.selection import FinalSelectionEngine

    led = Ledger()
    engine = FinalSelectionEngine(mode="agent", ledger=led)
    result = _result([_ranked("h1", 10.0, False)], final_reports={"h1": _report(True)})

    decision = engine.decide(result)

    assert "guard_escalated" in decision.escalations  # 【確認内容】: 裁定まで到達 🔵
    assert decision.accepted is None  # 【確認内容】: エスカレーション時は自動 accept しない 🔵
    assert decision.provisional_id == "h1"  # 【確認内容】: 暫定裁定として best を提示 🔵


# ---------------------------------------------------------------------------
# 4. Issue #125: review_queue プロパティ / accept() のエスカレーション通知
# ---------------------------------------------------------------------------


def test_review_queue_property_returns_injected_queue():
    # 【テスト目的】: review_queue プロパティが注入済み ReviewQueue をそのまま読み取り専用で返す
    # 【期待される動作】: 注入したインスタンスと同一オブジェクトが返る
    # 🔵 信頼性: Issue #125 — ② list_review_queue が到達する唯一の経路
    from tsumugin.selection import FinalSelectionEngine

    queue = ReviewQueue()
    engine = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)

    assert engine.review_queue is queue  # 【確認内容】: 注入したインスタンスと同一 🔵


def test_review_queue_property_none_when_not_injected():
    # 【テスト目的】: queue 未注入時は review_queue が None を返す (② の error 縮退判定に使う)
    from tsumugin.selection import FinalSelectionEngine

    engine = FinalSelectionEngine(mode="agent", ledger=Ledger())

    assert engine.review_queue is None  # 【確認内容】: 未注入は None 🔵


def test_accept_notifies_queue_when_escalation_present():
    # 【テスト目的】: accept() が明示 accept 時もエスカレーション成立中なら Queue へ通知する (Issue #125)
    # 【背景】: decide() を経由しない accept_hypothesis(MCP) 経路でも人間の後追い確認事項を蓄積する
    from tsumugin.selection import FinalSelectionEngine

    queue = ReviewQueue()
    engine = FinalSelectionEngine(mode="human", ledger=Ledger(), queue=queue)
    # 2 位 close_competitor=True で detect_escalations が "close_competitor" を発火する
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 10.0, True)])

    engine.accept(result, "h1", by="human")

    assert len(queue.items) >= 1  # 【確認内容】: Queue へ通知された 🔵
    assert any(i.reason == "close_competitor" for i in queue.items)  # 【確認内容】: 該当 reason 🔵
    assert any(i.hypothesis_id == "h1" for i in queue.items)  # 【確認内容】: accept 対象の id を運ぶ 🔵


def test_accept_does_not_notify_queue_when_no_escalation():
    # 【テスト目的】: エスカレーション不成立時は accept() が Queue へ何も追加しない
    from tsumugin.selection import FinalSelectionEngine

    queue = ReviewQueue()
    engine = FinalSelectionEngine(mode="human", ledger=Ledger(), queue=queue)
    result = _result([_ranked("h1", 10.0, False)])

    engine.accept(result, "h1", by="human")

    assert len(queue.items) == 0  # 【確認内容】: エスカレーション無しでは通知しない 🔵


def test_accept_notify_uses_frame_index_kwarg():
    # 【テスト目的】: accept() の frame_index キーワード引数が Queue 通知にそのまま渡る (decide() と対称)
    from tsumugin.selection import FinalSelectionEngine

    queue = ReviewQueue()
    engine = FinalSelectionEngine(mode="human", ledger=Ledger(), queue=queue)
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 10.0, True)])

    engine.accept(result, "h1", by="human", frame_index=7)

    assert any(i.frame_index == 7 for i in queue.items)  # 【確認内容】: frame_index が伝播する 🔵


def test_accept_without_frame_index_is_backward_compatible():
    # 【テスト目的】: 既存呼び出し (frame_index 無指定) が後方互換で動作し続ける
    from tsumugin.selection import FinalSelectionEngine

    led = Ledger()
    engine = FinalSelectionEngine(mode="human", ledger=led)
    result = _result([_ranked("h1", 10.0, False)])

    # 【処理内容】: 既存シグネチャのまま呼んでも例外にならず accepted 化される 🔵
    h = engine.accept(result, "h1", by="human")

    assert h.status == "accepted"  # 【確認内容】: 既存呼び出しが引き続き成立する 🔵
    assert h.accepted_by == "human"  # 【確認内容】: 既存挙動が変わらない 🔵
