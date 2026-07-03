# TDD開発メモ: frameseries-changepoint

## 概要

- 機能名: FrameSeries + changepoint 検出 (TASK-0015 / m2-sequential)
- 開発開始: 2026-07-03
- 現在のフェーズ: ✅ TDD 完了 (verify-complete 合格)

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (23/23 テストケース定義、実行 24 = TC-C-B03 parametrize 2 分岐)
- **今回タスクのテスト**: 24/24 green (スコープ内失敗 0)
- **全体テスト**: 304 passed / 3 skipped (GSAS-II 自動 skip = スコープ外・想定内) / 実行 10.63s
- **要件網羅率**: 100% (完了条件①〜⑥ + TC-102-04/06 + 決定論 REQ-402 + frozen/既定値契約を全カバー)
- **品質判定**: 合格
- **TODO 更新**: ✅ 完了マーク追加 (docs/tasks/m2-sequential/TASK-0015.md 完了条件 6 項目チェック済み)

## 関連ファイル

- 元タスクファイル: `docs/tasks/m2-sequential/TASK-0015.md`
- 要件定義: `docs/implements/m2-sequential/TASK-0015/frameseries-changepoint-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0015/frameseries-changepoint-testcases.md`
- Red 記録: `docs/implements/m2-sequential/TASK-0015/frameseries-changepoint-red-phase.md`
- Refactor 記録: `docs/implements/m2-sequential/TASK-0015/frameseries-changepoint-refactor-phase.md`
- 実装ファイル: `src/tsumugin/sequential/series.py` (75) / `changepoint.py` (179) / `__init__.py` (18)
- テストファイル: `tests/test_sequential_series.py` (9) / `tests/test_changepoint.py` (14)

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

23 件 (FrameSeries 9 / changepoint 14 = 正常系 9 / 異常系 6 / 境界値 8)。信頼性 🔵 15 / 🟡 8 / 🔴 0。
テストケース定義書の TC-S-N01〜B03 / TC-C-N01〜B05 に 1:1 対応。詳細は red-phase.md 参照。

### 期待される失敗

`ModuleNotFoundError: No module named 'tsumugin.sequential'` により両ファイルとも collection error (2 errors)。
対象モジュール 3 点が未実装のため全 23 件が失敗。Red として正当。`ruff check` (line-length 100) は両ファイル pass。

### 次のフェーズへの要求事項 (Green)

- 修正 z スコア `0.6745·(x−median)/MAD`、窓=末尾 window 要素、判定 `z > z_threshold` (strict)。
- z_lattice は a/b/c 各軸の**フレーム間差分** (np.diff) の robust z の**最大絶対値** (存在キーを sorted 集約 → 決定論)。
- new_peaks は `new_unmatched >= min_new_peaks` の単純カウント。
- warm-up (`len(rwp_history) < window`) と MAD=0 は例外化せず z=0.0 / triggered=False へ縮退 (inf/nan 非漏洩)。
- frame_index = `len(rwp_history) - 1`。reasons 順序は rwp→lattice→new_peaks。
- FrameSeries 形状不一致は `__post_init__` で `ValueError` (空 axis_values は検証免除)。
- 較正済み z 値: SPIKE_RWP≈201.68 / JUMP_LATTICE≈168.29 / FLAT・LINEAR_LATTICE=0.0 / TC-C-B02 境界 x=10.7412898… (z≈5 非発火).

## Greenフェーズ（最小実装）

実装済み (series.py / changepoint.py / __init__.py)。テスト 24 実行が全 green。詳細は各実装ファイル参照。

## Refactorフェーズ（品質改善）

### 実施日時
2026-07-03

### 改善内容
YAGNI 準拠で最小限。実装は Green 時点で既に高品質 (ヘルパー分割・日本語 docstring・信頼性注記・
frozen・MAD=0 ガード・決定論) のため、可読性/DRY/設計/ファイルサイズ/typing 規約は「変更不要」と判断。
唯一の改善は `_lattice_z` シグネチャの `ruff format` 準拠 1 行化 (数値ロジックは無変更で較正済み z 値を保存)。

### セキュリティレビュー結果
純関数・I/O なし・注入面なし。MAD=0 の 0 除算ガードで inf/nan 非漏洩。FrameSeries は形状不一致を
ValueError 明示化。重大な脆弱性なし。

### パフォーマンスレビュー結果
窓 W=5 の O(W log W) median と O(keys·frames) 差分計算。逐次呼び出し前提で軽量。重大な性能課題なし。

### 品質評価
✅ 高品質 — テスト 24 件全 green 継続、ruff check/format ともクリーン、全ファイル 500 行未満。
詳細は `frameseries-changepoint-refactor-phase.md` 参照。
