# TDD開発メモ: public-api-integration (公開 API 統合 + E2E + ドキュメント)

## 概要

- 機能名: 公開 API 統合 + E2E テスト + ドキュメント (M1 総仕上げ統合)
- 開発開始: 2026-07-03
- 現在のフェーズ: **verify-complete 完了 (TASK-0010 クローズ / M1 全 10 タスク完了)**

## 🎯 最終結果 (verify-complete, 2026-07-03)

- **実装率**: 100% (13/13 テストケース TC-010-01〜13 を `tests/test_m1_e2e.py` に実装・全 green)
- **テスト**: 全体 218 passed / 3 skipped、`test_m1_e2e.py` 13 passed、@gsas 経路 17 passed
  (skip 3 件は GSAS-II 導入済のため「未導入時例外」経路の正常 skip = スコープ外失敗ゼロ)
- **カバレッジ**: 96% (>= 90%) / **ruff**: `check src tests` clean
- **完了条件**: 6/6 充足 (公開API / E2E summary / @gsas / green+cov+ruff / README+context.md / verification.md)
- **品質判定**: ✅ 高品質 (要件網羅率 100% / スコープ内・外とも失敗なし)
- **TODO更新**: TASK-0010.md・overview.md にチェックボックス + ✅完了マーク追加
- **検証レポート**: `docs/tasks/m1-hypothesis-search/reports/verification.md` (M1 全 10 タスクのサマリ、M0 の範に準拠)

## 関連ファイル

- 元タスクファイル: `docs/tasks/m1-hypothesis-search/TASK-0010.md`
- 要件定義: `docs/implements/m1-hypothesis-search/TASK-0010/public-api-integration-requirements.md`
- テストケース定義: `docs/implements/m1-hypothesis-search/TASK-0010/public-api-integration-testcases.md`
- タスクノート: `docs/implements/m1-hypothesis-search/TASK-0010/note.md`
- 実装ファイル: `src/tsumugin/__init__.py` (Green で M1 re-export を追加予定)
- テストファイル: `tests/test_m1_e2e.py`
- Red フェーズ記録: `docs/implements/m1-hypothesis-search/TASK-0010/public-api-integration-red-phase.md`

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

テストケース定義書の全 13 件 (TC-010-01〜13) を `tests/test_m1_e2e.py` に 1:1 実装。

- 正常系 7: 公開シンボル re-export / `__all__` 昇順 / SimulatedBackend E2E ({A,B} 1 位・
  summary JSON 化・ledger.verify) / @gsas E2E (search 完走・export_gpx 再オープン)
- 異常系 3: D6 遅延 import 契約 (optional extra 遮断下の import 成功) / 候補ゼロ縮退 /
  未知相フラグ + 未マッチ報告
- 境界値 3: 決定論ビット同一 / 候補 1 相 (深さ 1) / README 使用例の実行可能性
- 信頼性: 🔵 12 / 🟡 1 / 🔴 0。@gsas 2 件は未導入環境で conftest が自動 skip。

### テストコード

`tests/test_m1_e2e.py` (詳細は red-phase.md 参照)。Red の失敗機構はモジュール冒頭の
`from tsumugin import HypothesisTreeSearch, SearchConfig, SearchResult, PhaseCandidate,
UnmatchedPeakReport, export_gpx` — トップレベル未 re-export のため collection 時に失敗。

### 期待される失敗

```text
E ImportError: cannot import name 'HypothesisTreeSearch' from 'tsumugin'
  (src/tsumugin/__init__.py)
!!!! Interrupted: 1 error during collection !!!!
```

実測 (2026-07-03): 上記のとおり collection エラーで全 13 件失敗。
`uvx ruff check tests/test_m1_e2e.py` clean。
既存スイート (`uv run pytest --ignore=tests/test_m1_e2e.py`) は exit 0
(205 passed / 3 skipped) で無退行。

### 次のフェーズへの要求事項

1. `src/tsumugin/__init__.py` へ M1 シンボル 6 件を re-export
   (`HypothesisTreeSearch` / `SearchConfig` / `SearchResult` / `PhaseCandidate` /
   `UnmatchedPeakReport` / `export_gpx`)。`__all__` は昇順ソート維持・M0 分の削除禁止。
2. D6 遅延 import 契約の維持 (fastapi / uvicorn / GSASII 非導入でも `import tsumugin` 成功)。
3. README「使い方 (M1)」節 (10-15 行、TC-010-13 と同等コード) + アーキテクチャ表更新、
   `docs/dev/context.md` 更新、`docs/tasks/m1-hypothesis-search/reports/verification.md` 新規
   (完了条件⑤⑥ — テスト外検証は verify-complete で担保)。
4. 品質ゲート: 全テスト green / カバレッジ 90% 以上 / ruff clean (完了条件④)。
   @gsas E2E は実 GSAS-II 精密化を含むため実行時間に注意 (fixture 共有済み)。

### 品質判定

```
✅ 高品質:
- テスト実行: 実行可能で失敗することを確認済み (collection ImportError で全 13 件失敗)
- 期待値: 明確で具体的 (相集合 / スキーマキー / verify() / フラグ / ビット同一)
- アサーション: 適切 (全 expect に日本語コメント + 信頼性レベル付与)
- 実装方針: 明確 (re-export 6 件 + __all__ 昇順維持のみで green 化できる見込み)
- 信頼性レベル: 🔵 12 / 🟡 1 — 🔵 優勢
```

## Greenフェーズ（最小実装）

### 実装日時

2026-07-03

### 実装方針

re-export のみで green 化する当初想定に加え、TC-010-13 (README 使用例) が `scale` 省略で
`PhaseInstance` を構築するため、`PhaseInstance.scale` に既定値 1.0 を付与 (後方互換)。

### 実装コード

- `src/tsumugin/__init__.py`: M1 シンボル 7 件 (`HypothesisTreeSearch` / `SearchConfig` /
  `SearchResult` / `PhaseCandidate` / `Peak` / `UnmatchedPeakReport` / `export_gpx`) を re-export、
  `__all__` を昇順維持で 26 件へ拡張。M0 分は非破壊。
- `src/tsumugin/model/phase.py`: `scale: float` → `scale: float = 1.0`。
- `README.md`: 「使い方 (M1): 多仮説木探索」節 + アーキテクチャ表 3 行 + 状態更新。
- `docs/dev/context.md`: Overview / Project Structure / 公開 API / Notes を M1 反映。

### テスト結果

`tests/test_m1_e2e.py` 13 passed / 全体 218 passed, 3 skipped /
カバレッジ 96% (>= 90%) / `uvx ruff@latest check src tests` clean。

### 課題・改善点

Refactor 候補は小。詳細は `public-api-integration-green-phase.md` を参照。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-03

### 改善内容

Green の実装は re-export + 既定値追加のみで最小のため、機能改善はなし。レビュー向けに付与した
冗長コメント (【公開面】【既定値】) の整理に限定 (YAGNI / 公開 API・テストの意味は不変)。

- `src/tsumugin/__init__.py`: `__all__` 直前コメントを、残す価値のある制約 (昇順ソート維持、
  `test_m1_symbols_in_dunder_all_and_sorted` が固定) のみの 1 行へ集約。配線の自明説明・後方互換の
  正当化 (PR レビュー向け) を削除。
- `src/tsumugin/model/phase.py`: `scale: float = 1.0  # 相スケール因子` へ短縮。自明な既定値説明と
  後方互換の正当化を削除 (兄弟フィールドの無コメント慣習に整合)。
- `README.md`: 変更なし。M1 使用例を `uv run python` で写経実行し `best phases: ['A', 'B']` /
  `ledger.verify()` True を確認。

### レビュー結果

- セキュリティ: コメント整理のみで実行パス不変、脆弱性なし。
- パフォーマンス: import コスト・依存グラフ・遅延 import (D6) すべて不変、性能課題なし。

### テスト結果

`uv run pytest` 218 passed / 3 skipped 維持、`uvx ruff@latest check src tests` clean。

### 品質評価

✅ 高品質 (テスト継続 green / ruff clean / 冗長コメント整理 / 公開 API・テスト契約に退行なし)。
詳細は `public-api-integration-refactor-phase.md` を参照。
