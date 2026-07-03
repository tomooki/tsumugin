# TASK-0024 Green フェーズ記録: thermal onset 意味論修正 (Issue #4)

**機能名**: thermal-onset-semantics / **タスクID**: TASK-0024 / **要件名**: m3-operando
**実装日時**: 2026-07-03 / **フェーズ**: Green (最小実装)
**実装ファイル**: `src/tsumugin/sequential/thermal.py`
**テストファイル**: `tests/test_thermal.py` (無改変 — Red フェーズで作成済みの 25 件をそのまま使用)

> すべてのパスはプロジェクトルートからの相対パス。

## 実装方針

Red フェーズ記録 (`thermal-onset-semantics-red-phase.md` Green 節) の最小差分方針をそのまま採用:

- **ロジック変更は onset レベルの direction 依存化 1 点のみ** (`estimate_transition` 内)。
  - appearing → `_ONSET_LEVEL` (0.10)、disappearing → `1.0 - _ONSET_LEVEL` (0.90)。
- midpoint 算出・direction 判定・σ 算出・点数不足縮退・`_interpolate_crossing` は**無改変**。
- `TransitionEstimate` の署名 (`onset` フィールド名含む)・`estimate_transition` の引数署名は**不変** (P2 / REQ-404)。
- docstring/コメントを「onset は direction に依らず遷移開始側 (低温側)、両方向とも onset < midpoint」へ更新。

## 実装したコード (差分)

### 1. onset レベル選択の direction 依存化 (ロジック変更・唯一の挙動変更)

`estimate_transition` 内 (旧 L204-206):

```python
# 【onset レベル選択】: onset は遷移開始側 (低温側) — appearing は 10% 交差、disappearing は
#   90% 交差 (= 1 - _ONSET_LEVEL) を採る。direction 依存化はこの 1 点のみの最小修正 (Issue #4) 🔵
onset_level = _ONSET_LEVEL if direction == "appearing" else 1.0 - _ONSET_LEVEL
# 【onset 推定】: 選択レベルを最初に横切る温度 (交差が無ければ None へ縮退し非有限を漏らさない) 🔵
onset_hit = _interpolate_crossing(temperatures, fractions, onset_level)
onset = onset_hit[0] if onset_hit is not None else None
```

### 2. 意味論の明文化 (docstring/コメント更新のみ・挙動変更なし)

- **モジュール docstring** (L7-10): onset は direction に依らず「遷移開始側 (低温側・先行するエッジ)」、
  appearing=10% 交差 / disappearing=90% 交差、いずれの方向でも onset < midpoint (Issue #4 / REQ-021) を明記。
- **`_ONSET_LEVEL` 定数コメント** (L29-31): direction 別 onset レベル真理値表への依拠を明記し 🔵 へ更新。
- **`TransitionEstimate.onset` フィールドコメント** (L62-64): 遷移開始側・onset < midpoint の不変条件を明記。
- **`estimate_transition` docstring**: 【onset 意味論】節を追加し、TC-T-N02〜B04 へのテスト対応を追記。

## 実装の判断理由 (信頼性レベル)

- 🔵 onset レベル選択式: requirements §2 の真理値表 / D-Q8 / interfaces.py L372-373 / Red フェーズ記録の
  実装指示に完全一致 (推測なし)。
- 🔵 縮退動作: 90% 交差が無い場合の onset=None は既存 `_interpolate_crossing` の None 経路を透過
  (非有限漏洩なし / M1 教訓)。
- 仕様との差異: なし (要件定義 §⚠️ で「onset < midpoint」に確定済みの矛盾も Red フェーズで解決済み。
  ユーザ確認は不要と判断)。

## テスト実行結果

- 対象テスト: `uv run pytest tests/test_thermal.py -v` → **25 passed** (Red で失敗していた
  TC-T-N02 / TC-T-N03 / TC-T-B01 の 3 件を含め全件 green)。
- 全体回帰: `uv run pytest` → **453 passed, 3 skipped** (無退行。`tests/test_m2_e2e.py` の
  appearing 経路含め既存テスト全 green)。
- Lint: `uvx ruff@latest check src tests` → **All checks passed!**

## 品質判定

```
✅ 高品質:
- テスト結果: 全 25 件成功 + 全体 453 passed / 3 skipped (無退行)
- 実装品質: シンプル (条件式 1 行 + コメント更新のみの最小差分)
- リファクタ箇所: onset_level の導出を定数/ヘルパへ寄せる余地はあるが現状 1 箇所のみで許容
- 機能的問題: なし (決定論・非有限漏洩なし・API 非破壊を維持)
- ファイルサイズ: thermal.py 231 行 (800 行制限内)
- モック使用: 実装コードにモック・スタブなし (純関数)
```

## 課題・改善点 (Refactor フェーズ候補)

- `1.0 - _ONSET_LEVEL` の導出式を named 定数 (`_ONSET_LEVEL_DISAPPEARING` 等) に切り出すと意図がさらに明瞭。
  ただし現状 1 箇所のみの使用で最小実装としては十分。
- 上流文書 (`docs/tasks/m3-operando/TASK-0024.md` / `acceptance-criteria.md` TC-208-01) の
  「disappearing: onset > midpoint」誤記の差し戻しは本タスク範囲外 (note §⚠️ 参照)。
