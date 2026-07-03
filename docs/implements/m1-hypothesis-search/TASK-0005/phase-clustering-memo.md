# 相候補クラスタリング (phase-clustering) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m1-hypothesis-search/TASK-0005.md`
- `docs/implements/m1-hypothesis-search/TASK-0005/phase-clustering-requirements.md`
- `docs/implements/m1-hypothesis-search/TASK-0005/phase-clustering-testcases.md`

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (19/19 テストケース)
- **品質判定**: 合格 (高品質)
- **TODO更新**: ✅完了マーク追加

### テスト結果
- スコープ内 (`tests/test_clustering.py`): 19 passed
- 全体 (`uv run pytest`): 141 passed, 1 skipped (skip は gsas マーカー自動 skip でスコープ外・非該当)
- Lint: `uvx ruff check src/tsumugin/search/clustering.py tests/test_clustering.py` → All checks passed

### テストケース実装状況 (19/19)
| 区分 | 予定 | 実装 | ケース |
|------|------|------|--------|
| 正常系 | 7 | 7 | TC-N01〜N07 |
| 異常系 (縮退) | 6 | 6 | TC-E01〜E06 |
| 境界値 | 6 | 6 | TC-B01〜B06 |

### 受け入れ基準・完了条件トレーサビリティ (全充足)
- REQ-103 / FR-114 (等構造 FoM 代表選出・代替解保持): TC-N01/N03/N04/B01 ✅
- REQ-104 / FR-116 (Jenks 良好解抽出): TC-N05/E04/E05/B06 ✅
- TC-004-01 → TC-N01 / TC-004-02 → TC-N02 / TC-004-03 → TC-N05 / TC-004-04 → TC-B01 ✅
- 完了条件1〜6 すべて対応テストがグリーン ✅

## 💡 重要な技術学習
### 実装パターン
- **union-find の決定論化**: `union` で常に小 index を根に固定し、結合順非依存の一意なクラスタ分割を得る (`src/tsumugin/search/clustering.py` `_UnionFind`)。クラスタ出力は代表 index 昇順、members は昇順に正規化してビット同一性を担保。
- **FoM 同点タイ処理**: members を昇順ソート後に `max(..., key=fom)` を適用すると、Python の `max` が同点時に最初の要素を返す性質で index 小優先が自動確定 (完了条件6)。
- **Jenks 自前 DP**: prefix sum で区間 SDCM を O(1) 化し O(n_classes·n²) DP。境界は「下群 max と上群 min の中点」。numpy コアのみで jenkspy 非依存。

### テスト設計
- GSAS-II 非依存で `Peak` リスト + fits/delta_us を素の list 直接構築 (backend/fixture 不要)。
- `_cluster_signatures` で index 非依存の相 identity 署名を作り、入力順並べ替え前後のクラスタ構造同一性を検証 (TC-B04)。
- 数値は `pytest.approx` 相当の範囲判定、決定論は `==` ビット同一で使い分け。

### 品質保証
- 縮退の非例外化 (M0): 空入力→`()`、FoM 分母ゼロ→`inf`、空ピーク集合 Jaccard 0/0→0.0、Jenks 空/単一/過大 n_classes→縮退境界。すべて例外を投げず素の tuple/int/float を返し numpy スカラー非露出。
- `__init__.py` の import / `__all__` にアルファベット順で 4 シンボル追加済み。

## ⚠️ 注意点・修正が必要な項目
- なし。スコープ内・スコープ外ともに失敗なし。修正対象なし。

---
*既存のメモ内容から重要な情報を統合し、重複・詳細な経過記録は削除*
