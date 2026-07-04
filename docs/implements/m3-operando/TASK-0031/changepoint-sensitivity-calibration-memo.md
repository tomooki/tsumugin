# TDD開発メモ: changepoint-sensitivity-calibration (TASK-0031)

## 概要

- 機能名: changepoint 感度較正 (Issue #3 / REQ-015 / 設計 D7)
- 開発開始: 2026-07-04
- 現在のフェーズ: 検証完了 (Verify-Complete / TDD 完了)

## 🎯 最終結果 (2026-07-04)

- **実装率**: 100% (TC-CP 定義 16 件を全網羅 — 新規/修正タグ付きテスト 13 件 + 既存無改変 green で担保 3 件 (R01/R04/B05))
- **要件網羅率**: 100% (完了条件 4 項目の code/test 条件を検証済み。5 項目目「コミット Closes #3」はユーザー commit 時付与予定)
- **全体テスト**: `uv run pytest` → **577 passed, 3 skipped** (スコープ内失敗 0 / スコープ外失敗 0)
- **Lint**: `uvx ruff@latest check` → All checks passed!
- **品質判定**: 合格 (高品質)
- **TODO更新**: ✅ TASK-0031.md タイトルへ完了マーク + 完了条件 checkbox 更新 (commit 条件のみ pending)

### TC-CP 定義 16 件の検証マッピング
- 直接 (新規/修正テスト): N01, N02, N03, E01, E02, E03, B01, B02, B03, B04, B06, R02, R03
- 既存無改変 green で担保: R01 (test_changepoint.py 全件), R04 (既存 engine テスト群), B05 (既存決定論テスト test_deterministic_bit_identical*)

## 💡 重要な技術学習
### 実装パターン
未マッチ観測ピークの「抽出 (`_unmatched_observed_peaks`)」と「強度/持続ゲート (`_gate_new_unmatched`)」を
分離し、逐次状態 `persistence_counter` を不変スタイル (前 dict を mutate せず新 dict を返す) で更新することで
NFR-102 決定論を保った。位置は `_position_bin` で 2θ 量子化しビンキー化。

### テスト設計
後方互換条件 (R01/R04) は「新規テストを足さず既存テスト群の無改変 green で担保」、決定論 (B05) も既存
determinism テスト再利用で担保。純関数 `detect_changepoint` のシグネチャ/判定式を不変に保ち、較正ロジックを
engine 側 (`new_unmatched` 組み立て段階) に閉じたことで純関数層を完全後方互換にできた。

### 品質保証
持続ゲートと既存「即発火」テスト (相 B 出現) の相互作用は避けられないため、TC-CP-R03 を唯一の合意例外
(frame10→11 の期待値最小修正) として明示。失敗フレームはカウンタ据え置きで非有限漏洩なし。

## ⚠️ 注意点
- 完了条件「コミットに "Closes #3"」は本セッション制約 (git commit しない) により未実施。ユーザーが commit する際に
  メッセージへ "Closes #3" を付与すること。それ以外の完了条件は検証済み。
- `src/tsumugin/sequential/engine.py` は 623 行で 500 行ガイドライン超過 (本タスク範囲外・将来の責務分割候補)。

## 関連ファイル

- 元タスクファイル: `docs/tasks/m3-operando/TASK-0031.md`
- 要件定義: `docs/implements/m3-operando/TASK-0031/changepoint-sensitivity-calibration-requirements.md`
- テストケース定義: `docs/implements/m3-operando/TASK-0031/changepoint-sensitivity-calibration-testcases.md`
- 実装ファイル (Green で拡張): `src/tsumugin/sequential/changepoint.py` / `src/tsumugin/sequential/engine.py`
- テストファイル: `tests/test_sequential_engine.py` / `tests/test_changepoint.py`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-04

### テストケース

新規 12 件 + 既存 1 件の期待値最小修正 (相互作用の合意例外 TC-CP-R03)。

- `tests/test_sequential_engine.py` (新規 10 件): 単発ノイズ非発火 (N01)・持続発火 (N02)・探索起動限定 (N03)・
  強度閾値未満非計上 (E01)・失敗フレーム決定論 (E02)・フラット縮退 (E03)・持続境界 (B01)・強度境界 (B02)・
  persistence=1 縮退 (B03)・非連続リセット (B06)。ヘルパ `_clean_a_series` / `_inject_peak` / `_gaussian_bump` を新設。
- `tests/test_changepoint.py` (新規 2 件): 新規 config フィールド既定値 (B04)・後方互換コンストラクタ (R02)。
- 既存 `test_phase_b_emergence_triggers_changepoint`: 期待発火フレーム 10→11 へ理由コメント付き最小修正。

### 期待される失敗

- 現行 `src/` では未マッチ 1 件で即 new_peaks 発火するため、持続/単発/非連続/境界テストが frame10 で発火して失敗。
- `ChangepointConfig` に新規 2 フィールドが無いため config テストが `AttributeError` で失敗。
- R03 修正後 assert (frame11 発火) は現行 (frame10 発火) に対して失敗。

実行結果: `uv run pytest tests/test_sequential_engine.py tests/test_changepoint.py` → **10 failed, 36 passed**。
(通過 3 新規テスト E01/E02/E03 は既存の安全側縮退を担保する意図的 green。)

### 次のフェーズへの要求事項

Green フェーズ (最小実装, src/):
1. `ChangepointConfig` に `new_peak_min_height_frac=0.05` / `new_peak_persistence=2` を既定値付き末尾追加
   (frozen 維持・純関数 `detect_changepoint` の判定式/シグネチャ不変)。
2. `SequentialEngine` に未マッチ観測ピークの位置 (2θ)/相対高さ抽出 + 位置ビンごと連続出現カウンタ + 強度/持続
   ゲートを追加し、`>= new_peak_persistence` のビン数を `new_unmatched` として `detect_changepoint` へ渡す。
3. 失敗フレームで持続カウンタ据え置き・ビンキー化 2θ 量子化で決定論 (NFR-102) を維持、非有限漏洩なし。

## Greenフェーズ（最小実装）

### 実装日時

2026-07-04

### 実装方針

純関数 `detect_changepoint` の判定式・シグネチャは不変に保ち、強度/持続ゲートは engine 側 (`new_unmatched`
組み立て段階) に閉じた (設計 D7)。

### 実装コード (要点)

- `changepoint.py`: `ChangepointConfig` に `new_peak_min_height_frac=0.05` / `new_peak_persistence=2` を
  既定値付き末尾追加 (frozen 維持)。
- `engine.py`:
  - `_count_unmatched(...) -> int` を `_unmatched_observed_peaks(...) -> tuple[Peak, ...]` へ拡張 (位置/高さ保持)。
  - `_gate_new_unmatched(...)`: 強度ゲート (相対高さ >= 閾値) → `_position_bin` で 2θ 量子化 (`_NEW_PEAK_BIN_WIDTH_DEG=0.15`) →
    継続ビン +1 / 非継続リセット → 連続 >= persistence のビン数を new_unmatched に計上。
  - `run()` 逐次状態に `persistence_counter: dict[int, int]` を追加。失敗フレームは `continue` で据え置き。

### テスト結果

- `uv run pytest tests/test_changepoint.py tests/test_sequential_engine.py` → 46 passed。
- `uv run pytest` → 577 passed, 3 skipped。
- `uvx ruff@latest check src tests` → All checks passed!

### 課題・改善点 (Refactor 候補)

- `_unmatched_observed_peaks` と tree.py の未マッチ算出の共通化余地。
- ビン幅定数と `match_tol_deg` の関係、強度ゲートと `find_peaks` 閾値の二重適用の整理。
詳細は green-phase.md を参照。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-04

### 改善内容

**持続カウンタ周りは変更不要 (YAGNI) と判断し無改変**。Green 実装の
`_unmatched_observed_peaks` / `_gate_new_unmatched` / `_position_bin` + 逐次状態
`persistence_counter` は既に単一責任・決定論 (不変カウンタ更新)・十分な日本語コメントを備え、
機能変更を伴わない安全な改善余地が乏しい。Green 提示の 3 改善候補 (tree.py 共通化 / ビン幅
定数結合 / 強度ゲート二重適用整理) はいずれも後方互換 green を脅かす波及・投機的結合・設計 D7
の意図的役割分担のため据え置き。engine.py 623 行の 500 行超過は本タスク範囲外の構造変更のため
将来タスクへ記録。

### セキュリティレビュー結果

数値配列処理に閉じ SQLi/XSS/CSRF 非該当。`max_height > 0.0` ガードで 0 除算回避。失敗フレームは
持続カウンタ据え置きで非有限漏洩なし。**重大な脆弱性なし**。

### パフォーマンスレビュー結果

`_gate_new_unmatched` は O(k log k)。`persistence_counter` は非継続ビン脱落で有界 (リークなし)。
探索起動は「発火フレーム数 == 探索回数」に較正され計算量制御 P5 維持。遅いテスト (2 秒超) なし。
**重大な性能課題なし**。

### テスト結果

- `uv run pytest tests/test_changepoint.py tests/test_sequential_engine.py` → 46 passed (無改変維持)。
- `uvx ruff@latest check src/tsumugin/sequential/engine.py src/tsumugin/sequential/changepoint.py`
  → All checks passed!

### 品質評価

✅ 高品質 (テスト継続 green / 脆弱性なし / 性能課題なし / 高凝集につき無改変が最適 / lint clean /
ドキュメント完成)。詳細は refactor-phase.md を参照。
