# TDD開発メモ: thermal-onset-semantics (TASK-0024)

## 概要

- 機能名: thermal onset 意味論修正 (disappearing の onset を 90% 交差=遷移開始側へ / Issue #4)
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (完全性検証 合格)

## 🎯 最終結果 (2026-07-04)

- **実装率**: 100% (テストケース定義 13 件 = TC-T-N01〜N03 / E01〜E03 / B01〜B04 / R01〜R03 を全網羅)
- **テスト成功率**: 100% (thermal 25 passed / 全体 453 passed, 3 skipped、スコープ内・外とも失敗なし)
- **品質判定**: 合格 (要件網羅率 100% / 未実装重要要件 0 / ruff clean)
- **TODO 更新**: ✅ 完了マーク追加 (`docs/tasks/m3-operando/TASK-0024.md` 完了条件 checkbox 更新済み)
- **完了条件補足**: 「disappearing onset>midpoint」は 90% 交差メカニズムと矛盾するため AC 訂正済みの
  「遷移開始側 (昇温では onset<midpoint)」で読み替え、タスクファイルも訂正済み。"Closes #4" コミットのみ
  本セッション対象外 (git commit しない)。

## 💡 重要な技術学習

### 実装パターン
- direction 依存の閾値選択は「共通ヘルパ (`_interpolate_crossing`) + 呼び出し側で level 定数を選ぶ」形が
  最小差分。ヘルパ署名を変えずに appearing/disappearing/midpoint 全経路を再利用できる。
- 対称レベル (10% / 90%) は `_DISAPPEARING_ONSET_LEVEL = 1.0 - _ONSET_LEVEL` と定義式で結び、DRY と真理値表の
  自己文書化を両立 (Refactor 適用)。

### テスト設計
- 仕様文書の不等号 (onset>midpoint) がメカニズム (90% 交差) と矛盾する場合、数値検証 (366.46 K < 400 K) を
  根拠にテストを「メカニズム忠実」で固定し、上流へ差し戻す判断が有効だった。
- 具体値固定 (onset≈366.46 かつ ≠433.54) で「10%→90% 切替」を値レベルで回帰防止。対称データで onset 値が
  偶然一致する罠は direction assertion と併用で回避。

### 品質保証
- 純関数の非有限漏洩なし (交差なし→None) を both-direction parametrize で担保。決定論は `==` ビット同一で検証。

## 関連ファイル

- 元タスクファイル: `docs/tasks/m3-operando/TASK-0024.md`
- 要件定義: `docs/implements/m3-operando/TASK-0024/thermal-onset-semantics-requirements.md`
- テストケース定義: `docs/implements/m3-operando/TASK-0024/thermal-onset-semantics-testcases.md`
- 実装ファイル: `src/tsumugin/sequential/thermal.py` (Green で修正予定・本フェーズ未改変)
- テストファイル: `tests/test_thermal.py`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

7 件を `tests/test_thermal.py` に反映 (1 修正 + 6 追加):

- **修正**: `test_transition_sigmoid_down_direction_disappearing` (TC-T-N02)
  — 既存の direction/midpoint/sigma assertion は無改変のまま、理由コメント付きで
  `onset is not None` / `onset < midpoint` / `math.isfinite(onset)` を追加。
- **追加**: `test_transition_disappearing_onset_is_ninety_pct_value` (TC-T-N03, 具体値 366.46 / 旧 433.54 でない)
- **追加**: `test_transition_disappearing_shallow_below_ninety_returns_none` (TC-T-E01, 縮退)
- **追加**: `test_transition_disappearing_ninety_pct_on_grid_point` (TC-T-B01, 90% 端点一致 onset=350)
- **追加**: `test_transition_direction_tie_is_appearing_with_ten_pct_onset` (TC-T-B02, direction 等号境界)
- **追加**: `test_transition_disappearing_deterministic_bit_identical` (TC-T-B03, 決定論)
- **追加**: `test_transition_no_nonfinite_leak_both_directions` (TC-T-B04, 非有限漏洩なし・parametrize 2)

### 期待される失敗

現行実装は direction 非依存に 10% 交差を onset とするため、disappearing の onset=433.54 K (>midpoint)。
中核の意味論テスト 3 件が失敗:

- N02: `onset < midpoint` が 433.54 < 400 で False
- N03: onset が 366.46 でなく 433.54
- B01: グリッド 90% 端点で onset が 350 でなく 450

実行結果: `uv run --extra gsas python -m pytest tests/test_thermal.py` → **3 failed, 22 passed**。
E01/B02/B03/B04 は修正前後で不変であるべきガードのため現行実装でも green (設計意図どおり)。
ruff (line-length 100) clean。

### 次のフェーズへの要求事項

`estimate_transition` の onset 推定を direction 依存化 (appearing=10% / disappearing=90% 交差) する
1 点の最小修正。midpoint/direction/σ/縮退/`_interpolate_crossing`・公開 API 署名 (`onset` 名) は無改変。
詳細は `thermal-onset-semantics-red-phase.md` の Green フェーズ節を参照。

## Greenフェーズ（最小実装）

### 実装日時

2026-07-03

### 実装方針

Red フェーズ記録の指示どおり `estimate_transition` の onset レベルを direction 依存化する 1 点の最小修正。
midpoint/direction/σ/縮退/`_interpolate_crossing`・公開 API 署名 (`onset` 名) は無改変。
docstring (モジュール / `estimate_transition` / `TransitionEstimate.onset` / `_ONSET_LEVEL`) に
「onset は direction に依らず遷移開始側 (低温側)、両方向とも onset < midpoint」の意味論を明記。

### 実装コード (挙動変更点)

```python
onset_level = _ONSET_LEVEL if direction == "appearing" else 1.0 - _ONSET_LEVEL
onset_hit = _interpolate_crossing(temperatures, fractions, onset_level)
onset = onset_hit[0] if onset_hit is not None else None
```

### テスト結果

- `uv run pytest tests/test_thermal.py` → **25 passed** (Red で失敗の TC-T-N02/N03/B01 含め全 green)
- `uv run pytest` (全体) → **453 passed, 3 skipped** (無退行)
- `uvx ruff@latest check src tests` → All checks passed!

### 課題・改善点

- Refactor 候補: `1.0 - _ONSET_LEVEL` を named 定数へ切り出す余地 (現状 1 箇所のみで許容範囲)。→ Refactor で適用済み。
- 上流文書 (TASK-0024.md / TC-208-01) の「onset > midpoint」誤記差し戻しは本タスク範囲外。
- 詳細は `thermal-onset-semantics-green-phase.md` を参照。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-04

### 改善内容

Green 記録で唯一挙げた候補「disappearing onset レベルの named 定数化」1 点のみを適用 (YAGNI・他は変更不要)。

- module 先頭に `_DISAPPEARING_ONSET_LEVEL = 1.0 - _ONSET_LEVEL` を追加し、direction 別 onset レベル表
  (`_ONSET_LEVEL` 10% / `_DISAPPEARING_ONSET_LEVEL` 90% / `_MIDPOINT_LEVEL` 50%) を module 先頭へ集約。
- `estimate_transition` の onset レベル選択からインライン算術 (`1.0 - _ONSET_LEVEL`) を除去し新定数へ置換。
- 挙動変更なし (値 0.90 で数学的に同一)。ロジック・API 署名・onset 意味論・テストは無改変。

### セキュリティ / パフォーマンスレビュー

- セキュリティ: 純関数 (乱数・I/O・eval なし)、非有限漏洩なし。重大な脆弱性なし。
- パフォーマンス: O(n) 線形走査・ホットパス外。重大な性能課題なし。

### テスト結果

- `uv run pytest tests/test_thermal.py -q` → **25 passed** (無退行)。
- `uvx ruff@latest check src tests` → All checks passed!
- 全体回帰は verify-complete フェーズで実施。

### 品質評価

✅ 高品質: テスト無退行 / セキュリティ・性能課題なし / 231 行 (500 行制限内) / DRY・全コメント整備。
詳細は `thermal-onset-semantics-refactor-phase.md` を参照。
