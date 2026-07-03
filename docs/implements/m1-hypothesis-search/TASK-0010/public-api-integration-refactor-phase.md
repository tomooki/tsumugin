# TASK-0010 公開 API 統合 + E2E — Refactor フェーズ記録

- **機能名**: 公開 API 統合 + E2E テスト (public-api-integration)
- **タスクID**: TASK-0010 / **要件名**: m1-hypothesis-search
- **実施日時**: 2026-07-03
- **対象ファイル**: `src/tsumugin/__init__.py`, `src/tsumugin/model/phase.py`, `README.md`

## 1. リファクタリング方針

Green フェーズの実装は re-export + 既定値追加のみで最小のため、機能面の改善余地は無い。
本 Refactor はレビュー向けに付与した冗長コメント (【公開面】【既定値】) の整理に限定する。
方針: コードから自明な内容と PR レビュー向け正当化コメントを削除し、残す価値のある制約のみ簡潔に残す。
公開 API・テストの意味は一切変更しない。🔵

## 2. 改善内容

### 2.1 `src/tsumugin/__init__.py` — `__all__` 直前コメントの整理 🔵

- **Before**: 「M0 (PoC) + M1 の中核シンボルをトップレベルへ配線する」(コードそのものから自明) +
  「既存 M0 シンボルは削除・改名しない (後方互換 / 要件 §3.2)」(非変更の正当化=PR レビュー向け)。
- **After**: 昇順ソート維持という**残す価値のある制約**のみ 1 行へ集約
  (`test_m1_symbols_in_dunder_all_and_sorted` が固定していることを明示)。
- **理由**: 昇順ソートは新シンボル追記時の唯一の非自明な規約で、テストが強制するため保持価値がある。
  それ以外は re-export のコード自体・モジュール docstring で判る。

### 2.2 `src/tsumugin/model/phase.py` — `scale` 既定値コメントの整理 🔵

- **Before**: scale の意味 + 「単位スケール 1.0 を既定とする」(コードの `= 1.0` から自明) +
  「既存呼び出しは全て scale を明示するため後方互換 (要件 §3.2)」(非変更の正当化=PR レビュー向け)。
- **After**: `scale: float = 1.0  # 相スケール因子` — ドメイン上の意味のみ短いインラインに残す。
  自明な既定値説明と後方互換の正当化を削除。兄弟フィールド (`wt_frac` / `occupancies`) の無コメント慣習に整合。
- **理由**: 既定値 `= 1.0` はコードで自明、後方互換の根拠は PR/Green 記録に残っており実コードには不要。

### 2.3 `README.md` — 変更なし (M1 使用例の実行検証のみ)

- 使用例本文はそのまま。`uv run python` で M1 使用例を写経実行し、
  documented 出力 `best phases: ['A', 'B']` と `ledger.verify()` 成功を確認済み (TC-010-13 と同経路)。

## 3. セキュリティレビュー

- 本 Refactor はコメント整理のみで実行パスを変更しない。入力検証・認証・外部 I/O への影響なし。🔵
- re-export は既存実体への参照 (`is` 同一) であり、新たな攻撃面を追加しない。

## 4. パフォーマンスレビュー

- import 時のシンボル解決コストは不変 (シンボル数・依存グラフに変更なし)。遅延 import 契約 (D6) も不変。🔵
- 計算量・メモリに影響する変更なし。

## 5. テスト実行結果

```text
uvx ruff@latest check src tests: All checks passed!
uv run pytest: 218 passed, 3 skipped (GSAS-II 導入環境、@gsas 実行 / unavailable-path 3 件 skip)
README M1 使用例 (uv run python): best phases: ['A', 'B'] / ledger.verify() True
```

- Green フェーズと同一の 218 passed / 3 skipped を維持。公開 API・テスト契約に退行なし。

## 6. 品質判定

```
✅ 高品質:
- テスト結果: 218 passed / 3 skipped 継続、ruff clean
- セキュリティ: 重大な脆弱性なし (実行パス不変)
- パフォーマンス: 重大な性能課題なし (変更なし)
- リファクタ品質: レビュー向け冗長コメントを整理、残す価値のある制約のみ簡潔化 (YAGNI 遵守)
- コード品質: 適切 (兄弟フィールド/モジュール慣習と整合)
```

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-verify-complete m1-hypothesis-search TASK-0010` で完全性検証を実行します。
