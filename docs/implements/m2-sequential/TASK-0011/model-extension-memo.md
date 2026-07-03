# TDD開発メモ: model 拡張 (PhaseLifecycle / ExternalChannel / frame_range)

## 概要

- 機能名: model 拡張 (PhaseLifecycle / ExternalChannel / frame_range)
- タスクID: TASK-0011 / 要件名: m2-sequential
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (Refactor まで完了。verify-complete で最終検証)

## 関連ファイル

- 元タスクファイル: `docs/tasks/m2-sequential/TASK-0011.md`
- 要件定義: `docs/implements/m2-sequential/TASK-0011/model-extension-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0011/model-extension-testcases.md`
- Redフェーズ記録: `docs/implements/m2-sequential/TASK-0011/model-extension-red-phase.md`
- 実装ファイル: `src/tsumugin/model/{phase,hypothesis,channel,__init__}.py` (未実装)
- テストファイル: `tests/test_model_m2.py`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

正常系 7 (N-01〜N-07) / 異常系 3 (E-01〜E-03) / 境界値 5 (B-01〜B-05) の計 15 件を
`tests/test_model_m2.py` に実装。テストケース定義に 1:1 対応。信頼性 🔵 13 / 🟡 2 / 🔴 0。

観点: PhaseLifecycle / ExternalChannel の frozen 生成・等価比較・FrozenInstanceError、
value_for の存在フレーム→値 / 欠損フレーム→None (EDGE-102)、
PhaseInstance.lifecycle の with_updates 非破壊付与、Hypothesis.frame_range 明示付与、
後方互換 smoke (位置引数生成で新フィールド既定 None)、model re-export と __all__ 収載。

### 期待される失敗

`uv run pytest tests/test_model_m2.py` → collection 時 ImportError
(`cannot import name 'ExternalChannel' from 'tsumugin.model'`) で全テストがエラー。
`PhaseLifecycle` / `ExternalChannel` 未実装かつ未 re-export が原因で、Red の正しい状態。
Lint は `uvx ruff check tests/test_model_m2.py` で clean (line-length 100)。

### 次のフェーズへの要求事項

Green フェーズで以下を実装 (全フィールド既定値付きの末尾追加 = REQ-404 非破壊):
1. `phase.py`: `PhaseLifecycle` 新設 + `PhaseInstance.lifecycle: PhaseLifecycle | None = None`
2. `hypothesis.py`: `Hypothesis.frame_range: tuple[int, int] | None = None`
3. `channel.py` (新規): `ExternalChannel` + `value_for`(欠損は None、例外なし)
4. `__init__.py`: `PhaseLifecycle` / `ExternalChannel` を import + `__all__` 追加

回帰ゲート: `uv run pytest` 全体で既存 226 (223 passed / 3 skipped) を無改変で維持。

## Greenフェーズ（最小実装）

### 実装内容

全フィールド既定値付きの末尾追加 (REQ-404 非破壊) を実装済み:
1. `phase.py`: `PhaseLifecycle`(birth_frame/death_frame/confidence) 新設 +
   `PhaseInstance.lifecycle: PhaseLifecycle | None = None` 追加。
2. `hypothesis.py`: `Hypothesis.frame_range: tuple[int, int] | None = None` 追加。
3. `channel.py` (新規): `ExternalChannel`(kind/sync_map/label) + `value_for`(欠損は None、例外なし)。
4. `__init__.py`: `PhaseLifecycle` / `ExternalChannel` を import + `__all__` 追加。

### テスト結果

`uv run pytest tests/test_model_m2.py` → 15 passed。既存回帰も維持 (verify-complete で全体確認)。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-03

### リファクタリング結論: 変更不要 (No change needed)

Green 実装は可読性/DRY/設計/ファイルサイズ/コード品質/セキュリティ/パフォーマンス/
エラーハンドリングの各観点をすでに満たしており、YAGNI 原則に従いコード変更なし。

### 改善内容

- コード変更: なし (既に docstring・日本語コメント・信頼性レベル・トレーサビリティ整備済み)。
- 一時ファイルのクリーンアップ: 対象ファイルなし。
- lint: `uvx ruff check` clean (line-length 100)。

### セキュリティレビュー結果

純データモデル層で外部入力/I-O/SQL/XSS 接点なし。`value_for` は `dict.get` で欠損を安全に
None 縮退 (EDGE-102、例外なし)。全て frozen で改竄不可。重大な脆弱性なし。

### パフォーマンスレビュー結果

`value_for` は O(1) の `dict.get`。frozen dataclass 生成のみで追加コストなし。重大な性能課題なし。

### 品質評価

✅ 高品質 — テスト 15/15 green (遅延テストなし) / セキュリティ・性能課題なし /
ruff clean / 500 行制限内 / ドキュメント整備済み。

詳細記録: `docs/implements/m2-sequential/TASK-0011/model-extension-refactor-phase.md`

## 検証フェーズ（完全性確認 / verify-complete）

### 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (15/15 テストケース — 正常系7/異常系3/境界値5、定義に 1:1 対応)
- **スコープ内テスト**: `tests/test_model_m2.py` 15 passed (0.68s、2秒超なし)
- **全体回帰**: `uv run pytest` → **238 passed / 3 skipped** (10.95s)。
  既存 223 passed を無改変で維持 (回帰ゲート充足、REQ-404 非破壊確認)。
- **品質判定**: ✅ 合格 (完全実装済み)。要件網羅率 100% / 成功率 100% / 未実装重要要件 0。
- **TODO更新**: ✅ 完了マーク追加 (`docs/tasks/m2-sequential/TASK-0011.md` 完了条件 4/4 チェック済み)。

### 完了条件の充足 (4/4)
1. PhaseLifecycle/ExternalChannel が frozen dataclass で生成・比較可能 → N-01〜N-04・E-01/E-02 ✅
2. value_for が欠損 frame_index で None (EDGE-102、例外なし) → E-03・B-04 ✅
3. 新フィールド既定 None で後方互換 (既存全テスト green) → B-02/B-03・既存 223 無改変 ✅
4. with_updates(lifecycle=...) が機能 → N-05 ✅

### 💡 技術学習ポイント
- **非破壊拡張パターン**: 既定値付きフィールドを末尾追加するだけで `dataclasses.replace`
  ベースの `with_updates` が新フィールドに自動対応 (完了条件④は追加実装不要)。
- **欠損縮退**: `dict.get` を `value_for` に用いることで EDGE-102 (欠損→None・例外なし) を
  1 行で満たせる。上位は軸値 None + 警告として扱う設計。
- **frozen + Mapping**: 等価比較は成立するがハッシュ化は不可。テストは生成・`==` に留める
  (既存 `LatticeParams.sigma` と同扱い)。

### ⚠️ スコープ外の観察 (本タスク対象外・修正しない)
- `tests/test_gsasii_backend.py::test_pipeline_ranks_hypotheses_on_gsasii_backend` が 2.16s と
  2秒超。GSAS-II backend の既存テストで TASK-0011 スコープ外。全体 10.95s (<30s) のため対応不要。
- 全体テストは全て green のためスコープ外の失敗はなし。
