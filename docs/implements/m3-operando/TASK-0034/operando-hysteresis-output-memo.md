# TDD開発メモ: operando-hysteresis-output (TASK-0034)

## 概要

- 機能名: operando/hysteresis + 結合出力 (FR-315 充放電ヒステリシス / FR-314 電気化学量結合出力)
- 開発開始: 2026-07-04
- 現在のフェーズ: 完了 (Refactor 完了)

## 関連ファイル

- 要件定義: `docs/implements/m3-operando/TASK-0034/operando-hysteresis-output-requirements.md`
- テストケース定義: `docs/implements/m3-operando/TASK-0034/operando-hysteresis-output-testcases.md`
- Red-phase 記録: `docs/implements/m3-operando/TASK-0034/operando-hysteresis-output-red-phase.md`
- タスクノート: `docs/implements/m3-operando/TASK-0034/note.md`
- 実装ファイル (未実装): `src/tsumugin/operando/hysteresis.py`, `src/tsumugin/operando/output.py`
- テストファイル: `tests/test_hysteresis_output.py`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-04

### テストケース

15 件 (正常系 7 / 異常系 3 / 境界値 5)。AC TC-205-01〜04 を全網羅 + 非有限漏洩/外部結合/決定論/frozen/縮退を補完。
一覧と各テストの信頼性レベルは red-phase.md §1 を参照。合成データは backend 不要の純データ
(`Trajectory`/`EchemData`/x_values 列) をテスト内ヘルパ (`_trajectory`/`_echem`/`_roundtrip`) で決定論構築。

### テストコード

`tests/test_hysteresis_output.py` (全文)。ruff line-length 100 pass。
未実装 2 モジュール (`operando.hysteresis` / `operando.output`) を import するため collection 時に失敗する。

### 期待される失敗

`uv run pytest tests/test_hysteresis_output.py -q`
→ `ModuleNotFoundError: No module named 'tsumugin.operando.hysteresis'` (collection error / 全 15 件エラー)。想定どおりの Red。

### 次のフェーズへの要求事項

- `hysteresis.py`: `BranchComparison`(frozen) / `split_branches` / `branch_differences`。
- `output.py`: `TransitionPoint`(frozen) / `combined_csv` / `transition_point`。
- 凍結した契約 (echem 列名 / 外部結合 / (b-1,b) 転移点補間 / dx 符号枝分離 / 全域グリッド枝間差分 /
  非有限→空欄・None 縮退 / 決定論) は red-phase.md §2 を厳守。
- `operando/__init__.py` `__all__` へ 5 シンボルをアルファベット順維持で非破壊追記。既存テスト green 維持。

## Refactor フェーズ（品質改善）

### 実施日時

2026-07-04

### 改善内容

非有限縮退の一貫性 (DRY / 単一情報源化) を実施。詳細は
`operando-hysteresis-output-refactor-phase.md` を参照。

1. `output.py` の私的 `_finite_or_none` 重複を削除し、共有 `_json.finite_or_none` へ委譲
   (TASK-0023 の統合方針と整合)。未使用 `import math` も除去。呼び出し 4 箇所を置換。
2. `hysteresis.py` `_interp_in_domain` の非有限縮退を `finite_or_none(value)` へ整合。

### セキュリティレビュー結果

重大な脆弱性なし (外部入力の実行/注入経路なし、CSV は stdlib 自動クオート)。

### パフォーマンスレビュー結果

重大な性能課題なし (純データ・小規模、対象 15 件 duration < 0.005s)。

### 品質評価

✅ 高品質: テスト 15 件全継続 pass / ruff pass (line-length 100) / DRY 目標達成 /
決定論・非破壊維持 / ファイル 500 行未満。

## Verify-Complete フェーズ（完全性検証）

### 検証日時

2026-07-04

### 🎯 最終結果

- **実装率**: 100% (15/15 テストケース) — 正常系 7 / 異常系 3 / 境界値 5
- **スコープ内テスト**: `tests/test_hysteresis_output.py` 15 件すべてグリーン
- **全体テスト**: **626 passed, 3 skipped** (22.48s / 無退行)。skip 3 は gsas マーカー
  (非導入環境で自動 skip)。スコープ外の失敗なし
- **Lint**: `uvx ruff@latest check src tests` → All checks passed! (line-length 100)
- **要件網羅率**: 100% — AC TC-205-01〜04 を全網羅 + 完了条件5 (非有限漏洩) / D9 外部結合 /
  NFR-102 決定論 / D-Q10 縮退 / frozen / 枝分離最小縮退を補完
- **品質判定**: 合格 (完全実装済み)
- **TODO更新**: ✅ 完了マーク追加 (TASK-0034.md 完了条件 5 項目すべて [x])

### 💡 重要な技術学習

- **実装パターン**: 非有限縮退は各層で私的 `_finite_or_none` を持たず、共有葉モジュール
  `_json.finite_or_none` へ下向き委譲するのが本リポの単一情報源方針 (TASK-0023)。新規出力層は
  最初からこれに委譲する。
- **テスト設計**: backend 不要の純データ (`Trajectory`/`EchemData`/x_values) を tmp_path + DictReader +
  frozen/warns/approx で検証する形が operando 出力層の定石。
- **品質保証**: CSV バイト同一 (N6) と純関数 `==` ビット同一 (N7) の二段で NFR-102 決定論を担保。

### スコープ外テスト失敗

なし (全 626 グリーン)。
