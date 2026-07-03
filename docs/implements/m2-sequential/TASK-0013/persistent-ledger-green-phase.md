# TASK-0013 PersistentLedger — Green フェーズ記録

**日時**: 2026-07-03 / **要件名**: m2-sequential / **タスク**: TASK-0013 (store/persistent)

## 実装ファイル

| ファイル | 変更 | 内容 |
|---|---|---|
| `src/tsumugin/store/persistent.py` | 新規 (117 行) | `PersistentLedger(path)` — append / entries / verify の同一契約。オープン時 `_load_and_verify()` で全チェーン検証、append は `"a"` モード 1 行追記のみ |
| `src/tsumugin/errors.py` | 追記 | `LedgerIntegrityError(TsumuginError)` 新設 (EDGE-003 / NFR-105、無修復を docstring 明記) |
| `src/tsumugin/store/ledger.py` | リファクタ (挙動不変) | module-level `verify_entries(entries) -> bool` を新設し `Ledger.verify` が委譲 (D-Q5 案(c))。`_compute_hash` / `GENESIS_HASH` / `LedgerEntry` は私的 import 共有 (案(a))。`Sequence` import 追加 |
| `src/tsumugin/store/__init__.py` | 追記 | `PersistentLedger` re-export (`__all__` 昇順維持) |

## 実装方針

- **決定論 (完了条件⑤)**: ハッシュ計算は `ledger.py::_compute_hash` を共有 → in-memory と hash 列ビット同一 🔵
- **検証の単一情報源**: `verify_entries` を ledger.py に切り出し、`Ledger.verify` / `PersistentLedger.verify` / 再オープン検証が同一ロジックを呼ぶ。既存 `Ledger` は挙動不変 🔵
- **無修復 (EDGE-003)**: `__init__` は read のみ。破損 (hash 不整合 / 不正 JSON 行) は `LedgerIntegrityError` を送出しファイルに書き込まない 🔵 (不正 JSON を包む方式・末尾空行スキップは 🟡)
- **追記のみ (NFR-203)**: 書き込みは `open(path, "a")` + `json.dumps(entry.to_dict()) + "\n"` のみ。新規パスはオープン時にファイルを作らず初回 append で作成 🟡
- **非破壊 API 面 (P2 / REQ-401)**: append / entries / verify のみ。破壊的メソッドなし 🔵

## テスト実行結果

- `uv run pytest tests/test_persistent_store.py tests/test_ledger.py` → **21 passed** (対象 14 + 既存 ledger 7)
- `uv run pytest` (全体回帰) → **267 passed, 3 skipped**、退行なし
- `uvx ruff@latest check src tests` → **All checks passed!**

## 品質判定

✅ **高品質**: 全テスト成功 / 実装シンプル (117 行、モック・スタブなし、標準ライブラリのみ) / 機能的問題なし / 800 行制限内

## リファクタ候補 (Refactor フェーズ)

- `_compute_hash` の私的横断 import → 公開名 `compute_hash` への昇格検討 (D-Q5 案(b)、任意)
- `_load_and_verify` で行に必須キー欠落 (KeyError) 時のエラーも `LedgerIntegrityError` に包む頑健化
- 行番号付きエラーメッセージ (破損行の特定容易化)
