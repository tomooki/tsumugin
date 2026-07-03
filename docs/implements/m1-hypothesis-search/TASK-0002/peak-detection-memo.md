# 観測ピーク検出 find_peaks TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m1-hypothesis-search/TASK-0002.md`
- `docs/implements/m1-hypothesis-search/TASK-0002/peak-detection-requirements.md`
- `docs/implements/m1-hypothesis-search/TASK-0002/peak-detection-testcases.md`

## 🎯 最終結果 (2026-07-03)

- **実装率**: 100% (15/15 テストケース、parametrize 込み 17 項目)
- **テスト成功率**: 100% (`tests/test_peaks.py` 17 passed / 全体 87 passed, 1 skipped=gsas 環境依存)
- **品質判定**: 合格（高品質 — 要件網羅率 100%、スコープ外失敗なし）
- **TODO更新**: ✅ 完了マーク追加（`docs/tasks/m1-hypothesis-search/TASK-0002.md`）

### 要件充足の対応表

| 要件/完了条件 | 検証テスト | 結果 |
|--------------|-----------|:----:|
| 完了条件1: ピーク数・位置 ±1 グリッド (REQ-002/FR-111) | N01, N02 | ✅ |
| 完了条件2: フラット/全ゼロ → 空タプル・例外なし (EDGE-003) | E01, E02, E03 | ✅ |
| 完了条件3: 閾値未満の微小ピーク不検出 | B03, B04 | ✅ |
| 完了条件4: 決定論 (REQ-403/NFR-102) | N06 | ✅ |
| 型契約: tuple[Peak,...] 昇順・frozen (interfaces.py) | N04, N05 | ✅ |
| 端点除外・プラトー・極小入力の縮退 | E04, B01, B02, B05 | ✅ |

## 💡 重要な技術学習

### 実装パターン

- 局所極大は numpy ベクトル比較 `(y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)`
  （端点除外・厳密不等号）。`np.flatnonzero(interior) + 1` で元配列 index へ昇順復元。
- 縮退ガードの順序: `size < 3` → `max <= 0` を先に返すことで空配列 `max()` 例外・
  ゼロ/負閾値の比較破綻を回避（例外化せず空タプル `()` に縮退、M0 規約）。
- 入力は `np.asarray(..., dtype=float)` で正規化。`two_theta` 昇順前提 + flatnonzero 昇順出力で
  position 昇順を追加ソートなしで自動保証。

### テスト設計

- 決定論バックエンド `SimulatedBackend(peak_fwhm=0.2)` + `peak_positions` を教師データとする
  オラクル方式が有効（真のピーク数・位置と照合）。
- 閾値境界は「副ピーク高さ=閾値ちょうど」の合成データで `>` / `>=` の実装差を切り分け（B04）。
- プラトー・一定値・単調配列で厳密不等号の保守的挙動（過検出なし）を担保。

### 品質保証

- `_count_local_maxima`（tests/test_simulated_backend.py）と式は同一だが、テスト独立性維持のため
  意図的に共通化しない（Refactor フェーズの判断。YAGNI）。
- 公開シンボルは `src/tsumugin/search/__init__.py` の `__all__ = ["Peak", "find_peaks"]` で管理。
- `uvx ruff check src tests`: All checks passed（peaks.py 69 行 / 500 行制限内）。

## ⚠️ 注意点・修正が必要な項目

なし（スコープ内・スコープ外とも失敗テストなし。総実行時間 5.09 秒で 30 秒未満、遅いテストなし）。

- 補足: `two_theta` と `intensity` の長さ不一致は同長前提の前提違反でありテスト対象外（要件定義 4 章）。
- 補足: pytest 起動時の「Error reading {cfgfile}」は GSAS-II 設定読込みの警告でテスト結果に影響なし。

---
*既存のメモ内容（Red/Refactor フェーズ経過）から重要な情報を統合し、詳細な経過記録は削除*
