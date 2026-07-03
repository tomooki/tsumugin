# TASK-0004 動的枝刈り閾値 dynamic_threshold — Red フェーズ記録

- **機能名**: 動的枝刈り閾値 (dynamic_threshold)
- **タスクID**: TASK-0004 / 要件名: m1-hypothesis-search
- **対象実装 (未作成)**: `src/tsumugin/search/pruning.py` の `dynamic_threshold()`
- **テストファイル**: `tests/test_pruning.py` (新規)
- **作成日**: 2026-07-03

## 契約 (Green で満たすべきシグネチャ)

```python
def dynamic_threshold(scores: Sequence[float], *, min_candidates: int = 4) -> float:
    """スコア降順の累積分布の変曲点 (二階差分最大) で枝刈り閾値を返す。
    縮退時 (候補不足・全同値・点数不足) は float("-inf") (全展開)。🔵 FR-112 (実装式は 🟡)"""
```

## 作成したテストケース一覧 (11 件 / テストケース定義に 1:1 対応)

| # | テスト関数 | 対応 | 分類 | 検証内容 |
|---|-----------|------|------|---------|
| 1 | `test_threshold_between_high_and_low_groups` | TC-N01 | 正常系 | 二群分離で `0.2 < t <= 0.8`、低群 `< t`・高群 `>= t` |
| 2 | `test_returns_finite_python_float_in_range` | TC-N02 | 正常系 | `type(result) is float`・`isfinite`・値域内 |
| 3 | `test_deterministic_regardless_of_input_order` | TC-N03 | 正常系 | 並べ替えで `==` ビット同一 (決定論) |
| 4 | `test_fewer_than_min_candidates_returns_neg_inf` | TC-E01 | 異常系 | `len=3 < 4` で `-inf`・非例外 |
| 5 | `test_empty_input_returns_neg_inf_without_exception` | TC-E02 | 異常系 | `[]` で `-inf`・非例外 |
| 6 | `test_degenerate_cases_unify_to_neg_inf` | TC-E03 | 異常系 | 縮退 3 ケース parametrize で `-inf` 一元化・非 NaN |
| 7 | `test_all_equal_scores_falls_back_to_neg_inf` | TC-B01 | 境界値 | 全同値 (二階差分全ゼロ) で `-inf` |
| 8 | `test_exactly_min_candidates_computes_threshold` | TC-B02 | 境界値 | `len==4` ちょうどで算出 (オフバイワン) |
| 9 | `test_min_candidates_three_with_three_points_computes_threshold` | TC-B03 | 境界値 | `min_candidates=3`+3 点 (最小点数) で算出 |
| 10 | `test_tie_in_second_difference_is_deterministic` | TC-B04 | 境界値 | タイでも一意規則で `==` 同一 |
| 11 | `test_threshold_is_inclusive_on_expand_side` | TC-B05 | 境界値 | 閾値そのものは展開側 (「未満」で枝刈り) |

- parametrize 展開により pytest 収集アイテム数は 13 (TC-E03 が ×3)。

## 期待される失敗内容 (Red 確認)

```
uv run pytest tests/test_pruning.py
E   ModuleNotFoundError: No module named 'tsumugin.search.pruning'
1 error in 0.77s
```

- `src/tsumugin/search/pruning.py` が未作成のため、`from tsumugin.search.pruning import dynamic_threshold` が
  collection 時に失敗し、全テストがエラー (=失敗) になる。これは Red フェーズの期待挙動。
- `uvx ruff check tests/test_pruning.py` は **All checks passed!** (line-length 100 準拠)。

## Green フェーズで実装すべき内容

1. `src/tsumugin/search/pruning.py` に `dynamic_threshold(scores, *, min_candidates=4) -> float` を新規作成。
2. アルゴリズム (interview Q8 🟡): 降順ソート → 累積和 `c` → 二階差分 `d2[i]=c[i+1]-2c[i]+c[i-1]` → 最大位置のスコアを閾値化。
3. 縮退ガード → `float("-inf")`: (a) `len(scores) < min_candidates`、(b) 点数不足 (実質 3 点未満)、(c) 二階差分最大が 0 (全同値・平坦分布)。
4. 決定論: ソートは関数内 (入力非破壊)、タイは一意規則で固定。戻り値は素の `float()` に変換。
5. `src/tsumugin/search/__init__.py` の import と `__all__` に `dynamic_threshold` を追加 (アルファベット順維持)。
