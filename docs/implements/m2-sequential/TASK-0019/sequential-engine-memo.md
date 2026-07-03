# TASK-0019 TDD 開発メモ — SequentialEngine

**要件名**: m2-sequential / **タスクID**: TASK-0019 / **機能名 (英)**: sequential-engine
**対象**: `src/tsumugin/sequential/engine.py` / **テスト**: `tests/test_sequential_engine.py`

## 概要
- **現在のフェーズ**: 完了 (Refactor 済み)
- オンライン逐次精密化 + 局所木探索エンジン (D1/D2/D3, FR-301〜306)。
- frame0 staged 確立 → 後続 warm start direct → changepoint 検出 → 発火時のみ局所木探索 →
  evidence 改善時のみ採択 → LifecycleTracker → Trajectory 組立。決定論・非有限非漏洩を保証。

## Refactor フェーズ (2026-07-03)
- **改善 1**: 6 桁量子化を `_HISTORY_QUANTIZE_DIGITS` 定数 + `_quantize_history()` ヘルパへ一元化
  (rwp 履歴 / `_lattice_map` の重複と rationale 二重記述を解消)。
- **改善 2**: `run()` の frame 精密化分岐 (D2 2 段構え) を `_FrameRefinement` dataclass +
  `_refine_frame()` メソッドへ抽出し `run()` を簡素化。
- **セキュリティ**: 新規脆弱性なし。**パフォーマンス**: 退行なし。
- **テスト**: 18 passed (決定論 SE-B02 含む)。ruff clean (line-length 100)。
- 詳細: `sequential-engine-refactor-phase.md`。

## 🎯 最終結果 (2026-07-03 / verify-complete)
- **実装率**: 100% (18/18 テストケース) — testcases.md の SE-N01〜SE-B07 を 1:1 実装。
- **完了条件網羅**: TASK-0019.md 9 項目すべて対応テストで充足 (checkbox 更新済 + ✅完了マーク付与)。
- **スコープ内テスト**: `tests/test_sequential_engine.py` → 18 passed (green)。
- **全体テスト**: `uv run pytest` → **370 passed / 3 skipped / 0 failed** (13.71s)。
  - skipped 3 件はスコープ外の既存条件付き skip (TASK-0019 とは無関係)。
- **品質判定**: 合格 (要件網羅率 100% / 成功率 100% / 未実装重要要件 0)。

## 💡 重要な技術学習
### 実装パターン
- 逐次ループの「フレーム精密化」を `_FrameRefinement` 束 + `_refine_frame()` に正規化し、
  staged/direct の 2 経路を同一形へ揃えると run 本体のフェーズ構造が読みやすくなる。
- ノイズフロア量子化は `_HISTORY_QUANTIZE_DIGITS` 定数 + ヘルパに集約 (履歴のみ量子化・記録は full precision)。
### テスト設計
- 決定論検証 (SE-B02, `==` ビット同一) がリファクタの挙動保存を強力に保証する回帰ネットになる。
- spy backend (refine 入力記録) で warm start 継承・木探索起動回数を挙動契約として明示検証。
### 品質保証
- 尺度不変な robust z + 完全適合合成データの組合せは偽 changepoint を生むため、履歴入力の量子化が必須。

## 品質評価
- ✅ 高品質 — 全テスト green・機能変更なし・DRY / 可読性向上・完了条件 9 項目全充足。
