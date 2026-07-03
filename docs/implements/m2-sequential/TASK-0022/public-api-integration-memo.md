# TDD開発メモ: 公開 API 統合 + E2E (TASK-0022)

## 概要

- 機能名: 公開 API 統合 + 統合 E2E テスト + ドキュメント (M2 総仕上げ)
- タスクID: TASK-0022 / 要件名: m2-sequential
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (Red → Green → Refactor → Verify 完了)

## 🎯 最終結果 (2026-07-03 verify-complete)

- **実装率**: 100% (19/19 テストケース TC-022-01〜19、正常系 11 / 異常系 3 / 境界値 5)
- **要件網羅率**: 100% (完了条件 5 項目すべて充足 — ①公開 API ②TC-108-01 8 段 ③@gsas smoke
  ④全 green/cov 90%+/ruff ⑤README+context+検証レポート)
- **全体テスト**: 425 passed / 3 skipped (428 collected)・カバレッジ 97% (`__init__.py` 100%)・ruff clean
- **スコープ内失敗**: 0 / **スコープ外失敗**: 0
- **品質判定**: ✅ 合格 (完全実装済み)
- **TODO 更新**: ✅ 完了マーク追加 (`docs/tasks/m2-sequential/TASK-0022.md` + `overview.md`)
- **検証レポート**: `docs/tasks/m2-sequential/reports/verification.md` (M2 全 12 タスク総括)

## 💡 重要な技術学習

- **実装パターン**: 純粋 re-export モジュール (`__init__.py`) はモジュール別 import グルーピング +
  `__all__` 昇順維持。M0/M1 の 26 件を非破壊で維持し M2 の 26 件を昇格追加 (計 52 件、REQ-404)。
- **テスト設計**: module スコープ fixture `warming_run` で一気通貫 E2E を 1 回だけ実行し、正常系 8 ケースで
  frozen 結果を読み取り専用共有 → 実行時間抑制。決定論は `==` ビット同一 / 物理量は `approx` / 非有限は `isfinite`。
- **品質保証**: 統合タスクは「ロジックを持たない re-export + doc + test」のため YAGNI で Refactor 変更なし。
  README 使用例は TC-022-18 で実行を green 担保し文面と実装の乖離を構造的に防止。

## 関連ファイル

- 要件定義: `docs/implements/m2-sequential/TASK-0022/public-api-integration-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0022/public-api-integration-testcases.md`
- タスクノート: `docs/implements/m2-sequential/TASK-0022/note.md`
- Red フェーズ記録: `docs/implements/m2-sequential/TASK-0022/public-api-integration-red-phase.md`
- 実装ファイル (Green 対象): `src/tsumugin/__init__.py`
- テストファイル: `tests/test_m2_e2e.py`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

TC-022-01〜19 (全 19 件、正常系 11 / 異常系 3 / 境界値 5、`@gsas` 1 件)。公開シンボル re-export・
`__all__` 昇順 + 後方互換、TC-108-01 一気通貫 8 段 (完走 / changepoint / 新相採択 / lifecycle /
転移温度 / agent 裁定 / 永続 ledger verify + 再オープン / CSV)、@gsas 3 フレーム smoke、
縮退 (空 series / 破損 ledger / 裁定対象ゼロ)、決定論 / 単一フレーム / 非発火 / README 例 / 性能。

### テストコード

`tests/test_m2_e2e.py` (新規)。module スコープ fixture `warming_run` で一気通貫を 1 回だけ実行し
TC-022-03〜10 で共有。合成データは `_warming_transition_series` (A 熱膨張 + B 転移 + 温度チャネル)
と `_expansion_series` (相構成不変・非発火)。`test_sequential_engine.py` / `test_m1_e2e.py` の慣習を踏襲。

### 期待される失敗

冒頭 `from tsumugin import (ChangepointConfig, ...)` が collection 時 `ImportError`
(`cannot import name 'ChangepointConfig' from 'tsumugin'`) → 全 19 テスト失敗。実行確認済み。
ruff clean (line-length 100)。既存スイートは `--ignore` 下で全 green (無影響)。

### 次のフェーズへの要求事項

`src/tsumugin/__init__.py` に M2 昇格シンボル 26 件を re-export し `__all__` を昇順維持で更新
(M0/M1 の 26 件は非破壊)。トップレベル `is` 同一実体を担保。→ 全 19 テスト green を目指す。

## Greenフェーズ（最小実装）

### 実装日時

2026-07-03

### 実装方針

`src/tsumugin/__init__.py` に M2 昇格シンボルをモジュール別 (sequential / selection /
store) に re-export し、`__all__` をアルファベット昇順維持で更新 (M0/M1 の既存 26 件は非破壊)。
README「使い方 (M2)」節と `docs/dev/context.md` 実装済みモジュール表を追記。

### 実装結果

TC-022-01〜19 (@gsas 1 件含む) が全 green。トップレベル `import tsumugin` で M2 API が解決し、
一気通貫 E2E (TC-108-01) 8 段 + @gsas 3 フレーム smoke (TC-108-02) + 縮退/決定論/性能まで担保。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-03

### リファクタリング内容

対象 (`__init__.py` / README / test) はいずれもロジックを持たない re-export + doc + test であり、
Green 完了時点で品質基準を満たしていたため **YAGNI に基づき変更不要** と判断。
詳細は `public-api-integration-refactor-phase.md` を参照。

### 品質評価

✅ 高品質 — 425 passed / 3 skip (正しい skip) / カバレッジ 97% (`__init__.py` 100%) /
ruff clean / セキュリティ・パフォーマンス重大課題なし。
