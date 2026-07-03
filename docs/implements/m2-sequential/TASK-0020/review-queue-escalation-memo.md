# ReviewQueue + detect_escalations TDD開発完了記録

## 確認すべきドキュメント
- `docs/tasks/m2-sequential/TASK-0020.md`
- `docs/implements/m2-sequential/TASK-0020/review-queue-escalation-requirements.md`
- `docs/implements/m2-sequential/TASK-0020/review-queue-escalation-testcases.md`
- `docs/implements/m2-sequential/TASK-0020/review-queue-escalation-refactor-phase.md`

## 概要
- **要件名**: m2-sequential / **タスクID**: TASK-0020 / **タイプ**: TDD / REQ-015・FR-403・設計 D6/D-Q7
- **機能**: `selection/` パッケージ — `detect_escalations` (4 条件検出の純粋関数) +
  `ReviewQueue`/`ReviewItem` (追記型エスカレーション通知キュー)。
- **現在のフェーズ**: 完了（verify-complete 合格）

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (19/19 テストケース: 正常系 10 / 異常系 3 / 境界値 6)
- **テスト成功率**: 100%（スコープ内 19/19 green）
- **全体回帰**: `uv run pytest` → **389 passed, 3 skipped** in 12.78s（skip は既存の GSAS-II 依存テスト＝スコープ外・想定内）
- **品質判定**: 合格（✅ 高品質）
- **TODO更新**: ✅ 完了マーク追加（TASK-0020.md 完了条件 5 項目すべて [x]）

## 実装ファイル
- `src/tsumugin/selection/__init__.py`（4 シンボル re-export）
- `src/tsumugin/selection/engine.py`（`detect_escalations`。61 行）
- `src/tsumugin/selection/review_queue.py`（`EscalationReason`/`ReviewItem`/`ReviewQueue`。136 行）

## 完了条件 ↔ テスト対応
- ①4 条件単独検出 → N-01〜N-04 ✅ / ②条件なし空タプル → N-05・B-01〜B-03 ✅
- ③追記型・削除 API 不在 → N-08・E-02 ✅ / ④ledger 連携 review_add/review_resolve → N-10 ✅
- ⑤item_id 連番決定論 → B-04 ✅

## 💡 重要な技術学習
### 実装パターン
- 追記型コレクション (Ledger/Snapshot と同思想): 削除/上書き API を生やさず resolve は
  `dataclasses.replace(item, resolved=True)` の状態遷移で件数不変を保証（P2 構造的非破壊性）。
- 純粋関数 `detect_escalations`: SearchResult の `ranked` と `unmatched` のみ読み取り、
  副作用ゼロ・冪等。発火 reason は `EscalationReason` の Literal 宣言順に固定（NFR-102 決定論）。

### テスト設計
- 実 `SearchResult` を最小フィールド（ranked/unmatched）で構築する軽量テストダブルで木探索を回さず 4 条件を独立発火。
- 罠検証: 空 ranked の `all()` 真空的 True 回避（B-01）／閾値ちょうどは厳密比較 `>` で非発火（B-02）／
  `ranked[0]` は常に close=True のため 2 位で判定（B-03）。

### 品質保証
- Refactor は YAGNI に基づき **変更不要（no-change）判断**。ruff clean・500 行制限内・日本語コメント充実・
  skip/一時ファイル無し・遅いテスト無し（最遅 < 0.005s）。

## ⚠️ 注意点
- スコープ内の未完了項目・失敗テストなし。修正対象なし。
- スコープ外 skip 3 件は GSAS-II 依存の既存テストで想定内（本タスクと無関係、対応不要）。
