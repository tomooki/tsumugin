# TDD開発メモ: dynamic_threshold

## 概要

- 機能名: 動的枝刈り閾値 (dynamic_threshold)
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (Refactor: 変更不要と判断)

## 関連ファイル

- 元タスクファイル: `docs/tasks/m1-hypothesis-search/TASK-0004.md`
- 要件定義: `docs/implements/m1-hypothesis-search/TASK-0004/dynamic-threshold-requirements.md`
- テストケース定義: `docs/implements/m1-hypothesis-search/TASK-0004/dynamic-threshold-testcases.md`
- 実装ファイル: `src/tsumugin/search/pruning.py` (Green で新規作成)
- テストファイル: `tests/test_pruning.py` (新規作成)

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

テストケース定義 (11 件) に 1:1 対応。正常系 3 (TC-N01〜03) / 異常系 3 (TC-E01〜03) /
境界値 5 (TC-B01〜05)。TC-E03 は縮退 3 ケース (`([],4)`, `([0.5,0.5],4)`, `([0.9,0.5],2)`) を
`@pytest.mark.parametrize` で集約。決定論検証 (TC-N03/TC-B04) は `pytest.approx` でなく `==`
でビット同一を確認。書式は `tests/test_matcher.py`/`tests/test_peaks.py` に準拠、各テストに
【テスト目的/内容/期待/信頼性レベル】の日本語コメントを付与。

### テストコード

`tests/test_pruning.py` を参照 (全文)。対象 API は未実装の
`from tsumugin.search.pruning import dynamic_threshold`。

### 期待される失敗

- `uv run pytest tests/test_pruning.py` → `ModuleNotFoundError: No module named
  'tsumugin.search.pruning'` により collection 時に全テストがエラー (=失敗)。
- `uvx ruff check tests/test_pruning.py` → All checks passed! (line-length 100 準拠)。

### 次のフェーズへの要求事項

- `src/tsumugin/search/pruning.py` に `dynamic_threshold(scores, *, min_candidates=4) -> float`
  を実装 (降順ソート → 累積和 → 二階差分最大位置のスコアを閾値化、numpy コア可)。
- 縮退 (候補不足 / 点数不足 / 二階差分全ゼロ) は `float("-inf")` に一元化 (例外・NaN 禁止)。
- ソートは関数内・入力非破壊、タイは一意規則で固定 (決定論)、戻り値は素の `float`。
- `src/tsumugin/search/__init__.py` の import・`__all__` に `dynamic_threshold` を追加。

## Greenフェーズ（最小実装）

### 実装日時

2026-07-03

### 実装方針

- 降順ソート (関数内・非破壊) → 累積和 → 二階差分 `d2[m]=c[m+2]-2c[m+1]+c[m]` の
  **絶対値最大** (降順列では `d2<=0` のため絶対値最大=最大の落差=最大曲率) の内部点
  スコアを閾値化。閾値は落差の上側 (高スコア側) を採用し「未満」枝刈り境界と整合 (TC-B05)。
- 縮退は `-inf` に一元化: (a) `len < max(min_candidates, 3)` (候補不足+点数不足保険)、
  (b) ソート済み両端の等値 = 全同値、(c) 二階差分全ゼロのフォールバック。
- タイは `np.argmax` 先頭一致 (高スコア側) で固定し決定論を確保。戻り値は素の `float()`。
- `src/tsumugin/search/__init__.py` の import・`__all__` に `dynamic_threshold` を追加
  (アルファベット順維持)。

### 実装コード

`src/tsumugin/search/pruning.py` (76 行)。詳細は
`docs/implements/m1-hypothesis-search/TASK-0004/dynamic-threshold-green-phase.md` を参照。

### テスト結果

- `uv run pytest tests/test_pruning.py -v` → **13 passed** (11 ケース / 13 items 全 green)
- `uv run pytest` → **122 passed, 1 skipped** (全体無退行、skip は gsas マーカー自動 skip)
- `uvx ruff@latest check src tests` → **All checks passed!**

### 課題・改善点

- 端点のみに落差がある分布で cumsum 丸め誤差により平坦フォールバックを通らない可能性
  → Refactor で `np.diff(ordered)[1:]` 直接計算 or isclose 判定を検討。
- 「絶対値最大=変曲点」解釈 (🟡) の設計文書への還元を検討。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-03

### 判定: 変更不要

可読性・docstring・型注釈の観点で `src/tsumugin/search/pruning.py` (73 行) を精査した結果、
YAGNI を厳守したうえで有益な変更点はなく **変更不要** と判断した。

- 型注釈は完備 (`scores: Sequence[float], *, min_candidates: int = 4) -> float`)。
- docstring は【機能概要/実装方針/テスト対応】+ Args/Returns + 信頼性レベルを備え、
  `peaks.py` / `matcher.py` のハウススタイルに整合済み。
- ガード 3 段 + ベクトル化はコメントと `_MIN_POINTS_FOR_SECOND_DIFF` 定数で明快。500 行制限内。
- Green で挙がった「cumsum 丸め誤差 → `np.diff(ordered)[1:]` 直接計算」案は、
  (a) 縮退エッジで出力が変わる**機能的変更**でありリファクタ原則「機能的な変更は行わない」に反する、
  (b) cumsum/二階差分形は仕様 (FR-112 / REQ-101「累積分布の変曲点(二階差分)」) と字面で対応し
  トレーサビリティを保つ、の 2 点から本フェーズでは**採用せず** (別途バグ修正タスクの検討事項)。

### 検証

- `uv run pytest` → **122 passed, 1 skipped** (無退行)
- `uvx ruff@latest check src tests` → **All checks passed!**

## 検証フェーズ（完全性確認 / tdd-verify-complete）

### 🎯 最終結果 (2026-07-03)

- **実装率**: 100% (11/11 テストケース、13 items)
- **成功率**: 100% (`tests/test_pruning.py` → 13 passed / 全体 122 passed, 1 skipped)
- **要件網羅率**: 100% (REQ-101 / TC-002-02〜04 / 完了条件4 決定論を全カバー)
- **品質判定**: 合格（高品質・スコープ外失敗なし）
- **TODO更新**: ✅ 完了マーク追加（`docs/tasks/m1-hypothesis-search/TASK-0004.md` チェックボックス4件 [x]）

### 受け入れ基準トレーサビリティ

| 完了条件 / 基準 | テスト | 結果 |
|---|---|---|
| TC-002-02 (二群分離で境界が両群の間) | TC-N01 `test_threshold_between_high_and_low_groups` / TC-B05 `test_threshold_is_inclusive_on_expand_side` | ✅ |
| TC-002-03 (候補3以下で -inf) | TC-E01 `test_fewer_than_min_candidates_returns_neg_inf` | ✅ |
| TC-002-04 (全同値で -inf) | TC-B01 `test_all_equal_scores_falls_back_to_neg_inf` | ✅ |
| 完了条件4 (入力順非依存 決定論) | TC-N03 `test_deterministic_regardless_of_input_order` / TC-B04 `test_tie_in_second_difference_is_deterministic` | ✅ |

### 💡 学習ポイント

- 降順累積和の二階差分は降順列で `d2<=0` になるため、変曲点は「絶対値最大」で取ると高スコア側の落差を捉えられる（`np.abs(np.diff(cumsum, n=2))` + `argmax`）。
- 縮退値を `float("-inf")` に一元化する設計は、呼び出し側 (TASK-0006) の `score < threshold` 比較で「全展開」を NaN 混入なしに一意表現できる。
- 候補数ガードを `max(min_candidates, 3)` にすることで `min_candidates` 縮小指定時の点数不足 IndexError を同一縮退経路で防げる。
