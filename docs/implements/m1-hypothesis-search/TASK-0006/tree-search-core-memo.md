# 木探索コア (tree-search-core) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m1-hypothesis-search/TASK-0006.md`
- `docs/implements/m1-hypothesis-search/TASK-0006/tree-search-core-requirements.md`
- `docs/implements/m1-hypothesis-search/TASK-0006/tree-search-core-testcases.md`

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (20/20 テストケース)
- **成功率**: 100% (スコープ内 20/20 green、全体 161 passed / 1 skipped)
- **品質判定**: 合格（高品質）
- **TODO更新**: ✅完了マーク追加 (TASK-0006.md 完了条件 8 項目すべて [x])

## 検証サマリー
- テストケース定義: 正常系 10 (TC-N01〜10) / 異常系 4 (TC-E01〜04) / 境界値 6 (TC-B01〜06) = 20 件
  → `tests/test_tree_search.py` に 20 関数すべて実装・1:1 対応。
- `uv run pytest` 全 green: `tests/test_tree_search.py` 20 passed。全体 161 passed, 1 skipped
  (skip は `@pytest.mark.gsas` の GSAS-II 依存テストで本タスクのスコープ外)。
- 完了条件 8 項目はすべて対応する green テストで裏付けられている。
- TASK-0007 スコープのスタブ (`good_cluster_ids` / `unmatched` / `final_reports` /
  `warnings` / `to_summary()`) は `src/tsumugin/search/tree.py` で空値/骨格スタブとして明示済み。

## 💡 重要な技術学習
### 実装パターン
- best-first 木探索 + 純関数ノード評価 (乱数不使用・安定ソート = 候補 index 順) で決定論を担保。
- ledger は kind 別 (match_score / cluster / prune_threshold / node_refine / branch_prune / ranking)
  に記録し、枝刈り・降格を「削除」でなく「非展開 + 理由付き記録」で表現 (非破壊性)。
- chi2=inf / 全滅ケースは例外化せず降格 + NaN ガードで縮退 (metrics は None にしない)。

### テスト設計
- SimulatedBackend を主軸に、Rwp/chi2 の厳密制御が要る境界値・失敗注入は FakeBackend、
  呼び出し契約 (D2) の観測は RecordingSpyBackend で担保。
- 決定論検証は `==` ビット同一、物理量近似は `pytest.approx` を使い分け。

### 品質保証
- SearchResult は frozen dataclass + 破壊系公開 API 不在を静的検証 (監査可能性の構造的担保)。

## ⚠️ 注意点・修正が必要な項目
- なし（スコープ内失敗ゼロ、スコープ外失敗ゼロ）。次段は TASK-0007 (good_cluster/final_reports/unmatched 実体化)。
