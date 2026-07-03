# PersistentSnapshotStore TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m2-sequential/TASK-0014.md`
- `docs/implements/m2-sequential/TASK-0014/persistent-snapshot-store-requirements.md`
- `docs/implements/m2-sequential/TASK-0014/persistent-snapshot-store-testcases.md`
- `docs/implements/m2-sequential/TASK-0014/persistent-snapshot-store-refactor-phase.md`

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (13/13 テストケース — N-01〜N-06 / E-01〜E-02 / B-01〜B-05)
- **要件網羅率**: 100%（完了条件 5 項目すべて実装・テスト済み）
- **テスト成功率**: 100%（スコープ内 `tests/test_persistent_store.py` 27 passed = PersistentLedger 14 + PersistentSnapshotStore 13）
- **全体回帰**: 280 passed / 3 skipped（skip はすべて GSAS-II 関連＝スコープ外）
- **Lint**: `uvx ruff check src tests` → All checks passed
- **品質判定**: ✅ 合格（高品質）
- **TODO更新**: ✅ 完了マーク追加

### 完了条件 ⇔ テストケース対応（すべて緑）
| 完了条件 | テスト | 実装関数 |
|---|---|---|
| ① save→再オープン→load/revert 等価復元 (TC-106-03) | N-01/N-02 | `test_snapshot_save_reopen_load_roundtrip` / `test_snapshot_reopen_revert_returns_phases_and_moves_current` |
| ② snapshot ID 連番が再オープン跨ぎで継続 | N-03 | `test_snapshot_id_sequence_continues_across_reopen` |
| ③ 削除・上書き API 不在 (TC-106-05) | B-01 | `test_no_destructive_methods_and_same_surface_as_in_memory` |
| ④ StagedRefinementEngine 無改変注入で M0 経路 (TC-106-06/REQ-012) | N-06 | `test_persistent_snapshot_store_injectable_into_staged_engine` |
| ⑤ ledger 連携で snapshot_save/revert 記録 | N-04/N-05 | `test_snapshot_save_records_ledger_snapshot_save` / `test_snapshot_revert_records_ledger_and_file_unchanged` |

## 💡 重要な技術学習
### 実装パターン
- **in-memory 版との同一契約 + 追記 I/O**: `SnapshotStore`（`store/snapshot.py`）の `save/load/revert/snapshots/current_id`
  をそのまま踏襲し、`open(path, "a")` の 1 行追記（NFR-203）と再オープン復元だけを足す構成。ダックタイプ互換により
  `StagedRefinementEngine` へ無改変注入できる（REQ-012）。
- **phases の JSON 相互変換の分業**: `serialization.phase_to_dict/phase_from_dict`（TASK-0012）を共有し、
  行スキーマ `{"id","label","parent_id","phases":[...]}` の 1 snapshot = 1 行で永続化。有限値 phase は roundtrip 値等価。
- **非破壊 revert**: revert は snapshot JSONL に追記せず `current_id` を移すだけ。監査は注入 ledger の `snapshot_revert` で表現。

### テスト設計
- `tmp_path` による隔離ファイル、`Path.read_bytes()` の前後比較で「追記のみ・無変更」を観測的に検証（NFR-203 / 非破壊 revert）。
- in-memory 版と永続版で `RefinementReport`（metrics/final_phases/escalated）を等価比較し無改変注入を裏取り（TC-106-06）。
- 破壊的 API 名の `hasattr` 否定で非破壊性を構造的に保証（P2 / TC-106-05）。

### 品質保証
- Refactor は YAGNI に基づく「変更不要」判断。`PersistentLedger` との JSONL 読み書き重複は、
  誤り処理が意図的に発散（整合性検証あり／なし）しており共通化は独立契約の結合になるため現状維持が最適。
  詳細は `persistent-snapshot-store-refactor-phase.md`。

## ⚠️ 注意点・修正が必要な項目
- **スコープ内の未完了・失敗: なし**。
- **スコープ外**: 全体回帰の 3 skip はすべて GSAS-II 導入環境での「未導入経路を通らない」意図的 skip（本タスク無関係・要対応なし）。
- 後続 TASK-0019（`SequentialEngine` へ Persistent 版注入・E2E）が本クラスの署名・行スキーマに依存 → 変更時は連動注意。
