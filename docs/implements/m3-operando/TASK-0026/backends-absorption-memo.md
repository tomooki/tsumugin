# TASK-0026 TDD 開発メモ — backends 拡張 (global パラメータ文法 + 吸収補正 v1)

**機能名**: backends-absorption / **タスクID**: TASK-0026 / **要件名**: m3-operando
**タイプ**: TDD / **フェーズ**: **完了 (verify-complete 合格)** / **ブランチ**: milestone/m3-operando

## 🎯 最終結果 (2026-07-04)
- **実装率**: 100% (28/28 テストケース = 定義 26 + Refactor 追加 2)
- **成功率**: 100% (test_absorption.py 28 passed / 全体 502 passed + 3 skipped, 505 collected)
- **要件網羅率**: 100% (完了条件 6/6 充足・REQ-017〜020/103・EDGE-006・TC-207-02〜07)
- **品質判定**: **合格 (完全実装済み)** / ruff clean / 既存テストファイル無改変・無退行
- **TODO更新**: ✅ 完了マーク追加 (`docs/tasks/m3-operando/TASK-0026.md` 完了条件 6 項目 checkbox [x])

## 概要

- 透過平板配置の実効 μt 吸収補正 v1。`parse_param("global.mu_t")` 文法拡張・`RefinementResult.globals/
  warnings`・`AbsorptionConfig`/`transmission_factor`・`SimulatedBackend(absorption=...)` を非破壊追加。

## Red / Green フェーズ (要旨)

- Red: `tests/test_absorption.py` に定義 26 ケース (正常系 13 / 異常系 5 / 境界値 8) を作成。
- Green: `absorption/model.py` 新設・`backends/base.py`・`simulated.py`・`gsasii.py` を非破壊拡張し全 green。
  restraint 幅超過警告 (REQ-103) は **rwp 閾値ベース** (`_CORRELATION_RWP_THRESHOLD`) のみで実装。

## Refactor フェーズ (2026-07-04)

### 改善内容

1. **REQ-103 字義の充足** (機能追加ではなく検出取りこぼしの是正):
   - `AbsorptionConfig.restraint_width: float = 0.3` を末尾追加 (許容逸脱幅、非破壊)。
   - `SimulatedBackend._deviation_warning` (一次シグナル): `|μt − μt_calc| > restraint_width` で警告。
   - `SimulatedBackend._residual_correlation_warning` (補完シグナル): rwp 閾値ベース (従来ロジック移設)。
   - `_build_warnings` を経験推定 → 字義逸脱 → rwp 乖離 の決定論順で組み立て、単一責任ヘルパへ分割。
2. **対応テスト追加**:
   - T-E06: 逸脱強制合成ケース (scale 固定・極弱 restraint → μt がデータ選好へ逸脱、rwp 極小)。
     字義シグナルが rwp 補完シグナル不発下でも単独発火することを検証。
   - T-B09: `restraint_width` 既定 0.3 と明示上書きの保持を検証。

### レビュー結果

- セキュリティ: 数値内部演算のみ。外部入力解釈・I/O なし。重大な脆弱性なし。
- パフォーマンス: 追加は精密化 1 回あたり O(1) スカラ比較。ホットパス外。遅いテストなし。

### テスト・品質

- `uv run pytest tests/test_absorption.py`: 28 passed (26 定義 + 2 追加)。
- `uv run pytest`: 502 passed, 3 skipped (505 collected)。既存無改変・無退行。
- `uvx ruff check src tests`: clean。
- ファイルサイズ: simulated.py 431 / model.py 91 (500 行未満)。

### 品質評価: ✅ 高品質 (テスト全成功・脆弱性なし・性能課題なし・字義充足・コード品質向上)

## 関連ファイル

- 実装: `src/tsumugin/absorption/model.py`, `src/tsumugin/backends/{base,simulated,gsasii}.py`
- テスト: `tests/test_absorption.py`
- ドキュメント: `docs/implements/m3-operando/TASK-0026/backends-absorption-{requirements,testcases,refactor-phase}.md`, `note.md`
