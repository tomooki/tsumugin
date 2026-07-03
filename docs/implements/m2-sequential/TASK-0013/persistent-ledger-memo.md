# TASK-0013 persistent-ledger TDD 開発メモ

**機能名**: store/persistent — PersistentLedger / **要件名**: m2-sequential

## 関連ファイル

- 要件定義: `docs/implements/m2-sequential/TASK-0013/persistent-ledger-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0013/persistent-ledger-testcases.md`
- 実装: `src/tsumugin/store/persistent.py`, `src/tsumugin/errors.py`, `src/tsumugin/store/ledger.py`, `src/tsumugin/store/__init__.py`
- テスト: `tests/test_persistent_store.py` (14 件)

## Red フェーズ

- テスト `tests/test_persistent_store.py` 作成済み (正常系 6 / 異常系 3 / 境界値 5)

## Green フェーズ (2026-07-03)

- **実装方針**: ハッシュ計算 `_compute_hash` を ledger.py と共有 (決定論)。検証は `verify_entries` を ledger.py に新設して単一化 (`Ledger.verify` は委譲・挙動不変)。オープン時は read のみで全チェーン検証、破損は `LedgerIntegrityError` (新設・TsumuginError 派生) で無修復送出。append は `"a"` モード 1 行追記のみ。
- **テスト結果**: 対象 21 passed / 全体 267 passed, 3 skipped (退行なし) / ruff All checks passed
- **課題・改善点** (Refactor 対象):
  - `_compute_hash` 私的横断 import の公開昇格検討 (D-Q5 任意)
  - 必須キー欠落行 (KeyError) の `LedgerIntegrityError` 化
  - 破損検出時の行番号付きメッセージ
- 詳細: `persistent-ledger-green-phase.md`

## Refactor フェーズ (2026-07-03)

- **現在のフェーズ**: 完了
- **判定**: ✅ 高品質 — コード変更なし (YAGNI により候補を全て要否判断・据え置き)
- **対象**: `store/persistent.py`・`store/ledger.py` の `verify_entries` 切り出し部 / Green レビュー向けコメント整理
- **結論**: Green で実施済みの `verify_entries` module-level 切り出し（`Ledger.verify`/`PersistentLedger.verify`/再オープン検証の単一情報源化）が既にリファクタ目標を達成。追加のコード変更は不要と判断。
- **候補の要否判断 (据え置き)**:
  - `_compute_hash` 公開昇格 → 同一 `store` パッケージ内の私的横断 import は慣用・公開面最小(P2)整合のため私的維持 (YAGNI)
  - 必須キー欠落行の `LedgerIntegrityError` 化 → テスト未要求 + 機能変更のため将来課題
  - 行番号付きエラーメッセージ → 診断装飾のみ・テスト未要求 (YAGNI)
- **検証結果**: 対象 21 passed in 0.84s / 遅いテストなし / ruff All checks passed / skip・一時ファイルなし
- **レビュー**: セキュリティ 重大脆弱性なし（インジェクション面なし・改竄検出 sha256・追記のみ）/ パフォーマンス 重大課題なし（O(n) 単一走査）
- 詳細: `persistent-ledger-refactor-phase.md`

## 完全性検証 (Verify-Complete) — 🎯 最終結果 (2026-07-03)

- **実装率**: 100% (14/14 テストケース — 正常系 6 / 異常系 3 / 境界値 5)
- **成功率**: 100% (スコープ内 `tests/test_persistent_store.py` 14 + 共有 `tests/test_ledger.py` 7 = 21 passed)
- **全体テスト**: 267 passed, 3 skipped in 11.12s (退行なし・スコープ外失敗なし)
- **要件網羅率**: 100% — 完了条件 5 項目すべて実装・テスト済み
  - ① append→再オープン→verify+全量一致 → `test_append_reopen_verify_and_entries_match` (TC-106-01)
  - ② 再オープン後 append チェーン連結 → `test_reopen_append_chain_links` (TC-106-02)
  - ③ 改竄検出+ファイル無変更 → `test_tampered_hash_raises_integrity_error` / `test_tampered_payload_raises_and_file_unchanged` (TC-106-04/EDGE-003)
  - ④ 破壊 API 不在+追記のみ → `test_no_destructive_methods` / `test_append_only_growth_prefix_unchanged` (TC-106-05/07)
  - ⑤ in-memory 同一 hash 列(決定論) → `test_deterministic_hashes_match_in_memory_ledger`
- **品質判定**: ✅ 合格（高品質・完全達成）
- **TODO 更新**: `docs/tasks/m2-sequential/TASK-0013.md` に ✅ 完了マーク + 完了条件 5 項目 checkbox 更新済み
- **備考**: 総実行 11.12s(<30s)。2s 超テスト 2 件 (`test_gsasii_backend` 2.27s / `test_m1_e2e` setup 1.78s) はスコープ外の GSAS-II 統合テスト（本タスク非関連・既存）

### 💡 技術学習 (再利用ポイント)
- **単一情報源パターン**: 検証ロジック `verify_entries` を module-level に切り出し、in-memory/永続の両実装 + 再オープン検証で共有。決定論(ハッシュ列ビット同一)と挙動不変を両立
- **非破壊性の構造保証**: 破壊的メソッドを「持たないこと」を `hasattr` で明示テスト (P2/REQ-401)
- **無修復の観測的証跡**: 破損検出時 `read_bytes()` 前後一致・追記時 `after.startswith(before)` でバイト列不変を検証
