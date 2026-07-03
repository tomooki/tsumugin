# TASK-0029 TDD Refactorフェーズ記録: operando/echem — CSV マッパ + Loader Protocol (FR-311)

**機能名**: echem-csv-loader / **タスクID**: TASK-0029 / **要件名**: m3-operando
**実施日**: 2026-07-04 / **対象**: `src/tsumugin/operando/echem.py`, `tests/test_echem.py`

---

## 1. リファクタリング方針 (YAGNI 適用)

Green フェーズの実装は既に以下を満たしており、大規模な構造変更は**不要**と判断した:

- ファイルサイズ 193 行 (< 500 行制限)、単一責任 (echem 入力 I/O 層のみ)
- 日本語コメント (【機能概要】/【実装方針】/【テスト対応】+ 🔵🟡 信頼性レベル) 完備
- モジュール定数 (`_FIELD_KINDS` / `_DATA_LOGICALS`) による DRY・決定論的走査順の明示
- `from typing import Mapping` はプロジェクト支配的慣行 (model/channel.py, sequential/trajectory.py 等) と整合 → 変更不要

## 2. 適用した改善 (1 件)

### 改善1: `EchemData.composition_x` の既定値表記の統一 🔵

- **Before**: `composition_x: tuple[float | None, ...] = field(default=())` (+ `from dataclasses import dataclass, field`)
- **After**: `composition_x: tuple[float | None, ...] = ()` (+ `from dataclasses import dataclass`)
- **改善内容**: 同一 dataclass 内の他 3 フィールド (`current` / `capacity` が `= ()`) と表記を統一し、
  不要になった `field` import を除去。tuple は不変オブジェクトのため `field(default=...)` は冗長。
- **設計方針**: `docs/design/m3-operando/interfaces.py` L206 の契約表記
  (`composition_x: tuple[float | None, ...] = ()`) と一字一句一致させ、後続 TASK-0034 の参照時の混乱を防止。
- 🔵 信頼性レベル: interfaces.py L199-208 の契約表記に直接依拠 (推測なし)。

### 見送った変更 (YAGNI 判断)

- `ruff format` 適用: プロジェクト全体で 49 ファイルが未適用 (format は慣行として強制されていない)。
  規約 (note.md §2) は `uvx ruff check src tests` clean のみを要求 → 差分を作らない。
- IDE の E501 (79 桁) 診断: プロジェクト規約は ruff line-length **100** のため非該当。
- 非線形換算・.mpr パーサ・combined_csv: 後続スコープ (TASK-0034 以降) のため実装しない。

## 3. セキュリティレビュー結果: ✅ 重大な脆弱性なし

- **eval 不使用** 🔵: 数値変換は `float()` のみ。`eval(` / `exec(` / `literal_eval` が実装ソースに
  存在しないことをテスト (TC-A02) がソース走査で機械的に担保 (任意コード実行経路なし)。
- **入力検証** 🔵: 列欠損は列名 + CSV ヘッダを提示する `ValueError` で停止 (沈黙しない / dataflow.md L110)。
  数値変換失敗も列名 + 問題値 (`{cell!r}`) を提示する `ValueError` (`raise ... from exc` で原因保持)。
- **ファイル読込** 🔵: `open(path, newline="", encoding="utf-8")` — エンコーディング明示・csv 規約準拠。
  stdlib `csv` のみ使用 (外部パーサ依存なし / REQ-403)。
- **データ完全性** 🔵: 欠損は None で明示 (0 埋め・補間・捏造なし)。不完全な EchemData を沈黙して返さない。

## 4. パフォーマンスレビュー結果: ✅ 重大な性能課題なし

- **計算量**: 読込 O(rows × 4 列)・`to_channels` O(フィールド数 × frames) — 単一パス、最適。
- **メモリ**: `rows = list(reader)` は全行保持だが、echem CSV は数千フレーム規模でありボトルネックにならない。
  決定論 (CSV 記載順保持) のための意図的設計。
- **テスト実行時間**: 15 テストで 0.77s、最遅 setup 0.01s — 2 秒超の遅いテストなし。

## 5. テスト実行結果 (リファクタ後)

```
uv run pytest tests/test_echem.py  →  15 passed in 0.77s
uvx ruff check src/tsumugin/operando tests/test_echem.py  →  All checks passed!
```

- テストケース定義 15 件 (正常系 7 / 異常系 4 / 境界値 4) すべて green を維持。
- 開発時一時ファイル (debug-*/temp-*/*.bak 等): 検出なし。skip されたテスト: なし。

## 6. 品質判定: ✅ 高品質

- テスト結果: 全 15 件継続成功 / セキュリティ: 重大な脆弱性なし / パフォーマンス: 重大な性能課題なし
- リファクタ品質: 契約表記統一を達成、YAGNI により不要変更を回避 / ファイルサイズ: 193 行 (< 500)
- 日本語コメント: 信頼性レベル付きで完備
