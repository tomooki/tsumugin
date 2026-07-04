# TDD開発メモ: operando-discrimination (TASK-0032)

## 概要

- 機能名: operando/discrimination — 固溶体 vs 二相判別 (FR-313 / 設計 D4)
- 開発開始: 2026-07-04
- 現在のフェーズ: 完了 (verify-complete 合格・17/17 green・全体 594 passed 無退行)

## 関連ファイル

- 元タスクファイル: `docs/tasks/m3-operando/TASK-0032.md`
- 要件定義: `docs/implements/m3-operando/TASK-0032/operando-discrimination-requirements.md`
- テストケース定義: `docs/implements/m3-operando/TASK-0032/operando-discrimination-testcases.md`
- Redフェーズ記録: `docs/implements/m3-operando/TASK-0032/operando-discrimination-red-phase.md`
- 実装ファイル: `src/tsumugin/operando/discrimination.py` (**未実装 / Green で作成**)
- テストファイル: `tests/test_discrimination.py` (**新規・17 件**)

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-04

### テストケース

正常系 8 (TC-N01〜N08) / 異常系 4 (TC-E01〜E04) / 境界値 5 (TC-BV01〜BV05) の計 17 件。
受け入れ基準 TC-204-01〜06 + TC-209-03 と完了条件 7 項目を全網羅 (詳細は red-phase.md §1)。

- テストダブルはテストファイル内に定義: `RecordingSpyBackend` (呼び出し観測) /
  `ControlledFakeBackend` (僅差/高R/全滅/閾値の決定論注入)。
- 合成データは `SimulatedBackend` (乱数なし) で固溶体系列 (格子連続変化) / 二相系列 (端成分分率漸移) を生成。

### テストコード

`tests/test_discrimination.py` (17 件、ruff line-length 100 準拠) を参照。

### 期待される失敗

`src/tsumugin/operando/discrimination.py` 未実装のため import が collection 時に失敗:

```
ERROR collecting tests/test_discrimination.py
E   ModuleNotFoundError: No module named 'tsumugin.operando.discrimination'
1 error in 0.79s
```

全 17 件がエラー(=失敗)。他 import はすべて解決 (構文/依存 API は健全)。

### 品質評価 (Red)

- テスト実行: ✅ 実行可能で失敗を確認済み (ModuleNotFoundError)。
- 期待値: ✅ 明確で具体的 (verdict 文字列 / ΔBIC 符号 / spy 呼び出し本数 / frozen / <30s)。
- アサーション: ✅ 適切 (== ビット同一 / raises / reason 突合 / 数値閾値)。
- 実装方針: ✅ 明確 (red-phase.md §5 に Green 実装項目を列挙)。
- 信頼性レベル: 🔵 12 / 🟡 5 (🟡 は B の free_suffixes・閾値閉境界・全滅 warnings 伝播・
  frame_range 検証・単一フレーム縮退・<30s 計測 — いずれも要件へ遡及可能)。
- **合成データの判別方向を SimulatedBackend で事前検証済み**: 固溶体 ΔBIC≈−84 / 二相 ΔBIC≈+37 /
  固定相込み ΔBIC≈−84・Al 格子ビット不変。Green で実装が同方向に収束すれば緑化する見込み。

### 次のフェーズへの要求事項

red-phase.md §5 参照。要点: `DiscriminationConfig`/`DiscriminationResult` (frozen) と
`discriminate_interval` (仮説A 単相 warm-start 逐次 / 仮説B 端成分固定 / 端点マルチスタート必須 /
ΔBIC 判定 / 僅差・高R エスカレーション / ledger 記録 / 決定論) を最小実装し、
`operando/__init__.py __all__` へ非破壊追記する。

## Greenフェーズ（最小実装）

（未着手）

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-04

### 改善内容

詳細は `operando-discrimination-refactor-phase.md`。要点:

1. **重複除去 (DRY)**: 両仮説 Hypothesis 構築を `_build_endpoint_hypothesis(...)` へ集約
   (near-duplicate 6 行 × 2 → 短い呼び出し 2 本 + 共通ヘルパ)。
2. **長大関数の分割 + 命名**: frame_range 検証を `_validate_frame_range(...)` へ抽出
   (本体先頭が意図明示的な段構成に)。
3. **特記事項の再確認 (変更不要)**: 仮説 B の wt_frac 不活性→scale のみ精密化 / BIC 設計 DOF 計上
   (ΔBIC 相殺)、および B 端成分格子=端点マルチスタート最良 basin 代表 (全滅時逐次端点フォールバック)
   は既存 docstring/コメントで十分明確と判断し変更せず。

### セキュリティ/パフォーマンスレビュー

- 純関数オーケストレータ。重大な脆弱性なし・重大な性能課題なし (端点のみマルチスタート、smoke <30 秒維持)。

### 決定論・非破壊の再確認

- 非破壊: 入力 series/phases を破壊しない。Ledger/ReviewQueue は追記のみ。
- 決定論: 乱数/時刻/集合反復順に依存する出力なし。`free_params` frozenset は
  `SimulatedBackend._recognized` の `sorted(...)` によりプロセス跨ぎでも順序不変。2 回実行ビット同一 green。

### 最終コード

`src/tsumugin/operando/discrimination.py` (546 行)。ヘルパ追加: `_validate_frame_range` /
`_build_endpoint_hypothesis`。

### 品質評価 (Refactor)

- テスト: ✅ 17 passed (無改変・Green 維持)。
- Lint: ✅ `uvx ruff@latest check` All checks passed。
- 機能変更: なし (振る舞い保存の構造改善のみ)。
- ファイルサイズ: 546 行 (コードベース許容ノルム内: engine.py 623 / tree.py 892)。

## 完全性検証 (verify-complete)

### 🎯 最終結果 (2026-07-04)

- **実装率**: 100% (17/17 テストケース: 正常系 8 / 異常系 4 / 境界値 5)
- **スコープ内テスト**: 17 passed (`tests/test_discrimination.py`) — 全グリーン
- **全体テスト**: **594 passed, 3 skipped** (17.89s) — 無退行 (3 skip は gsas マーカー自動 skip)
- **Lint**: `uvx ruff@latest check src tests` → All checks passed
- **品質判定**: ✅ 合格 (要件網羅率 100% / 成功率 100% / 未実装重要要件 0)
- **TODO更新**: ✅ TASK-0032.md に完了マーク追加・完了条件 7 項目チェック済み

### 完了条件 7 項目の充足 (すべて緑テストで担保)

1. 固溶体 → "solid_solution" (TC-204-01) → `test_solid_solution_series_yields_solid_solution_verdict` ✅
2. 二相 → "two_phase" (TC-204-02) → `test_two_phase_series_yields_two_phase_verdict` ✅
3. マルチスタート必須 + metrics.multistart (TC-204-03) →
   `test_multistart_is_mandatory_at_interval_endpoints` + `test_both_hypotheses_carry_metrics_multistart` ✅
4. 僅差 → undecided + Queue (非ブロック) (TC-204-04) →
   `test_close_competitor_yields_undecided_and_queue_notice_without_blocking` ✅
5. 両仮説高 R → エスカレーション・判別なし (TC-204-05/EDGE-005) →
   `test_both_high_r_escalates_without_verdict` ✅
6. 決定論 2 回ビット同一 (TC-204-06) → `test_discrimination_is_deterministic_bitwise_identical`
   + `test_single_frame_interval_degenerate_is_deterministic` ✅
7. 判別 1 区間 (N=8) < 30 秒 smoke (TC-209-03) →
   `test_single_interval_discrimination_under_thirty_seconds` ✅

補完テスト: D4 格子固定 (`test_two_phase_hypothesis_keeps_lattice_fixed`) / FR-312 固定相
(`test_fixed_phase_preserved_and_does_not_disturb_verdict`) / NFR-105 ledger
(`test_ledger_records_and_verifies`) / EDGE-002 全滅縮退
(`test_all_multistart_diverged_degrades_with_warning`) / TC-E04 不正区間 / TC-BV01 閉境界 /
TC-BV02 None ガード / TC-BV04 frozen も全通過。

### スコープ外テスト

- 失敗なし (全 594 passed)。auto-debug 対応不要。
