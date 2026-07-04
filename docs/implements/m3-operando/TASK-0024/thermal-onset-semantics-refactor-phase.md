# TASK-0024 Refactor フェーズ記録: thermal onset 意味論修正 (Issue #4)

**機能名**: thermal-onset-semantics / **タスクID**: TASK-0024 / **要件名**: m3-operando
**実施日時**: 2026-07-04 / **フェーズ**: Refactor (品質改善)
**実装ファイル**: `src/tsumugin/sequential/thermal.py`
**テストファイル**: `tests/test_thermal.py` (無改変)

> すべてのパスはプロジェクトルートからの相対パス。

## リファクタリング方針

Green フェーズ実装は既に最小差分・純関数・全コメント整備済みで高品質 (231 行 / 500 行制限内)。
Green 記録で唯一挙げられた改善候補「`1.0 - _ONSET_LEVEL` の named 定数切り出し」のみを適用し、
それ以外は YAGNI に基づき**変更不要と判断**した (ロジック・API・テストは無改変)。

## 適用した改善 (1 点のみ)

### 可読性向上: disappearing onset レベルの named 定数化 🔵

- **Before**: `estimate_transition` 内で `onset_level = _ONSET_LEVEL if direction == "appearing" else 1.0 - _ONSET_LEVEL`
  とインライン算術 (`1.0 - _ONSET_LEVEL`) で 90% を導出していた。
- **After**: module 先頭に `_DISAPPEARING_ONSET_LEVEL = 1.0 - _ONSET_LEVEL` を追加し、
  呼び出し側を `onset_level = _ONSET_LEVEL if direction == "appearing" else _DISAPPEARING_ONSET_LEVEL` に置換。
- **改善効果**:
  - direction 別 onset レベル真理値表 (appearing=10% / disappearing=90%) が `_ONSET_LEVEL` /
    `_DISAPPEARING_ONSET_LEVEL` / `_MIDPOINT_LEVEL` として module 先頭に集約され自己文書化。
  - ホットロジックからインライン算術が消え、意図 (「90% = appearing の対称レベル」) がコメントで明示。
  - `_DISAPPEARING_ONSET_LEVEL = 1.0 - _ONSET_LEVEL` の定義式により 10%/90% の対称性が保たれ、
    `_ONSET_LEVEL` 変更時の一貫性 (DRY) も担保。
- **挙動変更**: なし (値は 0.90 で数学的に同一)。決定論・API 署名・onset 意味論はすべて不変。
- 🔵 信頼性: Green 記録の Refactor 候補 / requirements §2 真理値表に依拠 (推測なし)。

## 変更不要と判断した項目 (YAGNI)

- **ロジック**: midpoint 算出・direction 判定・σ 算出・点数不足縮退・`_interpolate_crossing` は無改変
  (最小修正の原則を維持、既存 Green 挙動を動かさない)。
- **ファイル分割**: 231 行で 500 行制限に余裕があり分割不要。
- **`_interpolate_crossing` の共通化**: 既に level 引数で appearing/disappearing/midpoint 全経路を再利用済み。追加抽象は過剰。
- **エラーハンドリング**: 交差なし → `None` 縮退、非有限漏洩なしが既存経路で担保済み。追加不要。

## セキュリティレビュー結果

- **入力検証・脆弱性**: 純関数 (乱数・I/O・外部状態・eval/exec・SQL/HTML 生成なし)。
  インジェクション・XSS・CSRF・データ漏洩の攻撃面なし。
- **非有限漏洩**: 交差なしは `None` へ縮退し inf/nan を下流へ漏らさない (M1 教訓 / CLAUDE.md 準拠)。
- **結論**: 重大な脆弱性なし。🔵

## パフォーマンスレビュー結果

- **計算量**: onset/midpoint 交差探索は各 O(n) 線形走査 (n = フレーム数、数十)。定数化で 1 回の減算が
  module ロード時定数へ移動し、ホットパスの演算が僅かに減少 (実質誤差)。
- **メモリ**: 追加の値オブジェクト・大配列なし。
- **結論**: 重大な性能課題なし。ホットパスでなく可読性優先で適切。🔵

## テスト実行結果

- `uv run pytest tests/test_thermal.py -q` → **25 passed** (Refactor 前後で不変・無退行)。
- `uvx ruff@latest check src tests` → **All checks passed!** (line-length 100 / py312)。
- テスト実行時間: thermal 単体は 2 秒未満 (遅いテストなし)。
- 全体回帰 (`uv run pytest`) は verify-complete フェーズで実施。

## コメント改善内容

- `_ONSET_LEVEL` 節を「direction 別 onset レベル表を named 定数へ集約」する設計方針コメントへ拡充。
- `_DISAPPEARING_ONSET_LEVEL` に「appearing の 10% と対称・両方向 onset < midpoint」の意図コメントを付与。
- `estimate_transition` の onset レベル選択コメントを新定数名へ更新 (インライン算術の記述を除去)。

## 品質判定

```
✅ 高品質:
- テスト結果: 25 passed (無退行) / ruff clean
- セキュリティ: 重大な脆弱性なし (純関数・非有限漏洩なし)
- パフォーマンス: 重大な性能課題なし (O(n) 線形・ホットパス外)
- リファクタ品質: 目標達成 (唯一の候補を適用、YAGNI で他は変更不要と判断)
- コード品質: 適切なレベル (231 行 / 500 行制限内・全コメント整備・DRY)
- ドキュメント: 完成
```
