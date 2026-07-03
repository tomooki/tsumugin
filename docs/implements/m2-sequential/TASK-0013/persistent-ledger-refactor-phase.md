# TASK-0013 PersistentLedger — Refactor フェーズ記録

**日時**: 2026-07-03 / **要件名**: m2-sequential / **タスク**: TASK-0013 (store/persistent)
**対象**: `src/tsumugin/store/persistent.py`・`src/tsumugin/store/ledger.py` (`verify_entries` 切り出し部)
**判定**: ✅ 高品質 — コード変更なし (YAGNI により候補を全て要否判断・据え置き)

## 結論サマリー

Green フェーズで実施済みの `verify_entries` module-level 切り出し（単一情報源化）が既に
リファクタ目標を達成しており、追加のコード変更は不要と判断した（YAGNI）。
Green で挙げた 3 候補はいずれも「テスト未要求・公開 API 面拡大・機能変更」に該当するため据え置く。
検証・レビュー・品質確認を再実行し、全 green・lint clean・重大リスクなしを確認した。

## リファクタ候補の要否判断

| # | Green 記載の候補 | 判定 | 理由 |
|---|---|---|---|
| 1 | `_compute_hash` を公開名 `compute_hash` へ昇格 (D-Q5 案(b)、任意) | **据え置き** 🔵 | `ledger.py`/`persistent.py` は同一 `store` パッケージ内。パッケージ内の私的横断 import は Python の慣用で外部 API を汚さない。現状の外部利用者がいないため公開昇格は YAGNI 違反。非破壊監査モジュールの「公開面最小 (P2)」方針とも整合するため私的のまま維持 |
| 2 | 必須キー欠落行 (KeyError) を `LedgerIntegrityError` に包む頑健化 | **据え置き** 🟡 | 対応するテストケースが存在せず、追記は未要求の頑健化 = YAGNI。かつ Refactor 原則「機能的変更は行わない」に抵触。将来 valid-JSON-but-missing-key の破損モードをテスト化する際に対応すべき将来課題 |
| 3 | 破損検出時の行番号付きエラーメッセージ | **据え置き** 🔵 | 診断性向上の装飾のみ。現行メッセージはパス・無修復方針を明示済みで要求充足。テスト未要求のため YAGNI |

## verify_entries 切り出し部レビュー (対象確認)

- **単一情報源**: `ledger.py::verify_entries(entries) -> bool` を `Ledger.verify` /
  `PersistentLedger.verify` / `PersistentLedger._load_and_verify` の 3 経路が共有。
  検証ロジックの重複なし（DRY 達成）🔵
- **決定論**: ハッシュ計算 `_compute_hash` / `_canonical_json` を共有し、in-memory 版と
  hash 列がビット同一（`test_deterministic_hashes_match_in_memory_ledger` で担保）🔵
- **挙動不変**: 既存 `tests/test_ledger.py` 7 件が緑維持（切り出しによる退行なし）🔵
- **コメント整理**: `verify_entries` / `PersistentLedger` の日本語コメント（【機能概要】
  【実装方針】【テスト対応】+ 信頼性マーカー）は tsumiki 規約準拠かつ内容正確。
  除去・改変を要する冗長・誤りコメントは検出されず、現状維持が最適と判断 🔵

## セキュリティレビュー

- 入力面: `_load_and_verify` は `read_text(encoding="utf-8")` + 行単位 `json.loads`。
  `JSONDecodeError` は捕捉し `LedgerIntegrityError` へ変換（握り潰しなし）。
  eval / SQL / シェル / テンプレート展開なし → インジェクション面なし 🔵
- 完全性: sha256 ハッシュチェーンで改竄検出。書き込みは `"a"` 追記のみで既存バイト列不変
  （`test_append_only_growth_prefix_unchanged` / `test_tampered_payload_raises_and_file_unchanged`）🔵
- 機密: 秘匿情報・認証情報の扱いなし。重大な脆弱性は検出されず

## パフォーマンスレビュー

- `_load_and_verify`: ファイル全読込 → 行分割 → list 構築 → `verify_entries` 単一走査。
  時間 O(n) / 空間 O(n)。監査台帳の規模で適切、ボトルネックなし 🔵
- `verify_entries`: GENESIS からの単一パスで prev_hash 連結・index 連番・hash 再計算突合。
  検証として計算量最適 O(n) 🔵
- `entries` プロパティ: `tuple(self._entries)` の O(n) コピーは不変性契約
  （in-memory Ledger と同一）を優先した意図的設計。重大な性能課題なし

## テスト・静的解析結果

- `uv run pytest tests/test_persistent_store.py tests/test_ledger.py` → **21 passed in 0.84s**
  （対象 14 + 既存 ledger 7、退行なし）
- 遅いテスト（2 秒以上）: なし（最遅 setup 0.01s、全 call < 0.005s）
- `uvx ruff@latest check` (persistent.py / ledger.py / errors.py) → **All checks passed!**
- skip / xfail マーカー: なし（テスト無効化による見かけ green なし）
- 一時・デバッグ生成ファイル: なし

## 品質判定

✅ **高品質**
- テスト: 全 green 継続（退行なし）
- セキュリティ: 重大脆弱性なし
- パフォーマンス: 重大課題なし
- リファクタ品質: `verify_entries` 単一情報源化で目標達成済み、YAGNI により追加変更不要
- コード品質: lint clean / 私的 API 面最小 / ファイル 118 行（500 行制限内）
- ドキュメント: 本ファイル + memo 更新済み

## 次のステップ

`/tsumiki:tdd-verify-complete m2-sequential TASK-0013` で完全性検証を実行する。
