# TASK-0021 Refactor フェーズ記録 — FinalSelectionEngine

**要件名**: m2-sequential / **タスクID**: TASK-0021 / **機能名**: final-selection-engine
**対象実装**: `src/tsumugin/selection/engine.py`
**実施日時**: 2026-07-03

> パスはプロジェクトルート相対。信頼性: 🔵 資料準拠 / 🟡 妥当な推測 / 🔴 資料外推測。

---

## 1. リファクタ前提 (Green 完了状態)

- `src/tsumugin/selection/engine.py` に `Decision` (frozen dataclass) と
  `FinalSelectionEngine` (`mode` / `set_mode` / `decide` / `accept` / `revert` / `accepted`) が実装済み。
- `selection/__init__.py` に `Decision` / `FinalSelectionEngine` を re-export 済み。
- リファクタ前テスト: `uv run pytest tests/test_selection.py` → **36 passed** (既存 19 + 新規 17)。
- 全テストとも実行時間 < 0.005s。**遅いテスト (2秒以上) なし**。

---

## 2. コード品質確認結果

| 観点 | 結果 |
|---|---|
| ruff check (line-length 100) | ✅ All checks passed! |
| ファイルサイズ | ✅ 317 行 < 500 行制限 |
| テスト除外 (skip/xfail) | ✅ なし (test_selection.py に skip マーカーなし) |
| 開発時生成ファイル (debug-*/temp-*/*.bak 等) | ✅ 検出なし |
| 日本語コメント | ✅ 全メソッドに機能概要/実装方針/テスト対応/信頼性を付与済み |

---

## 3. 改善計画と実施内容

### 3.1 適用: フォーマット正規化 (ruff format) 🔵

- **改善観点**: リファクタ観点 5「フォーマットの統一」。
- **内容**: `decide` のシグネチャと `can_auto_accept` 述語式が、実際には line-length 100 内に
  収まるにもかかわらず複数行に折り返されていた。`uvx ruff format` により 1 行へ正規化。
  - `def decide(self, result: SearchResult, *, frame_index: int | None = None) -> Decision:`
  - `can_auto_accept = not escalations and best.close_competitor is False and unknown is False`
- **効果**: `decide` の分岐可読性が向上 (自動 accept 述語が 1 行で一望できる)。機能変更なし。
- **リスク**: なし (純粋な整形。ロジック・トークン列は不変)。

### 3.2 判断: decide 分岐構造は変更不要 (YAGNI) 🔵

- **評価対象**: `decide` の 4 分岐 (human / best 不在 / 自動 accept / 暫定裁定)。
- **現状評価**: すべてガード節 (early return) で表現され、自動 accept 条件は
  `can_auto_accept` の名前付き述語に抽出済み。各分岐に日本語コメント + 信頼性マーカー付き。
  分岐表 (mode × best 有無 × Q8 条件) が明快で、これ以上の抽象化 (Decision ファクトリ抽出等) は
  間接層を増やし可読性を下げる。
- **判断**: **変更不要**。YAGNI に従い、不要な抽象化を導入しない。

---

## 4. セキュリティレビュー結果 🔵

- **入力検証**: `_lookup` は未知 `hypothesis_id` に対し `KeyError` を送出しレジストリを汚さない。
  `revert` も未 accept id を `KeyError` で拒否 (誤操作防御)。
- **副作用**: `decide` / `accept` は入力 `SearchResult` を非破壊 (D5)。accepted 化は
  `dataclasses.replace` の新インスタンスで表現。共有された `SearchResult` を書き換えない。
- **インジェクション類**: SQL / eval / 外部コマンド実行なし。ledger payload は素の型 (str/bool/None) のみで
  canonical JSON 制約を満たし、dataclass を混入させない。
- **結論**: **重大な脆弱性なし**。

---

## 5. パフォーマンスレビュー結果 🔵

- `decide`: `detect_escalations` が ranked を O(n) 走査、`_build_rationale` は O(1)。全体 O(n)。
- `accept`: `next(...)` による ranked 線形走査 O(n) 1 回のみ。想定候補数 (数〜数十) で問題なし。
- メモリ: `_accepted` dict への追記のみ。`MappingProxyType` で読み取り専用ビューを返却 (コピーなし)。
- **結論**: **重大な性能課題なし**。乱数・時刻不使用で決定論 (NFR-102) を維持。

---

## 6. リファクタ後テスト実行結果

```
uv run pytest tests/test_selection.py
=> 36 passed in 0.75s
```

- ruff check: All checks passed! / ruff format --check: already formatted。
- 全 36 件継続成功。機能破綻なし。

---

## 7. 品質判定

```
✅ 高品質:
- テスト結果: 36 passed (継続成功)
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: 重大な性能課題なし
- リファクタ品質: フォーマット正規化を適用、分岐構造は YAGNI により変更不要と判断
- コード品質: ruff clean / 317 行 / 日本語コメント完備
- ドキュメント: 完成
```

判定: **高品質**。次フェーズ `/tsumiki:tdd-verify-complete` で完全性検証を実施する。
