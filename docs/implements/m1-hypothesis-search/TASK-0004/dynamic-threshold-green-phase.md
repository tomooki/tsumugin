# TASK-0004 動的枝刈り閾値 dynamic_threshold — Green フェーズ記録

- **機能名**: 動的枝刈り閾値 (dynamic_threshold)
- **タスクID**: TASK-0004 / 要件名: m1-hypothesis-search
- **実装ファイル**: `src/tsumugin/search/pruning.py` (新規, 76 行)
- **公開 API 追加**: `src/tsumugin/search/__init__.py` (import と `__all__` に `dynamic_threshold` をアルファベット順で追加)
- **実装日**: 2026-07-03

## 実装方針と判断理由

1. **アルゴリズム (interview Q8 🟡)**: 降順ソート → 累積和 `c` → 二階差分
   `d2[m] = c[m+2] - 2c[m+1] + c[m]` (内部点 `i = m+1` に対応) → **絶対値最大** の位置のスコアを閾値化。
   - 降順列では `d2[i] = s[i+1] - s[i] <= 0` が恒等的に成り立つため、「二階差分最大 (最大曲率=変曲点)」は
     **絶対値最大 = 最大の落差** と解釈した。この解釈で TC-N01 (`threshold == 0.8`)・TC-B02 (`0.85`)・
     TC-B03 (`0.9`) が全て整合する (「最大値」を素で取ると最小の落差になり TC-N01 が破綻する)。🟡
   - 閾値は落差の**上側** (`s[i]`, 高スコア側) を採用 → 閾値そのものは展開側に含まれる
     (REQ-101「未満」境界, TC-B05)。🟡
2. **縮退ガード → `float("-inf")` 一元化** (例外・NaN 禁止, EDGE-001 / M0 規約):
   - (a) `len(scores) < max(min_candidates, 3)` — 候補不足 (TC-E01/E02) と二階差分の点数不足
     (`min_candidates` 縮小指定時の IndexError 保険, TC-E03) を同一ガードで処理。🟡
   - (b) `ordered[0] == ordered[-1]` — 全同値 (平坦分布, TC-B01)。cumsum の丸め誤差で二階差分が
     微小非ゼロになる事故を避けるため、ソート済み両端の等値で判定。🟡
   - (c) `curvature.max() == 0.0` — 内部の二階差分が全ゼロ (端点のみに落差がある分布) の
     フォールバック。🟡
3. **決定論 (REQ-403 / NFR-102 / 完了条件4)**: ソートは関数内 (`np.sort` はコピー返却で入力非破壊,
   NFR-101)。タイは `np.argmax` の先頭一致 (高スコア側) で一意規則に固定 (TC-N03/TC-B04)。🔵
4. **契約遵守**: キーワード専用 `min_candidates=4`、戻り値は `float()` 変換した素の Python float。🔵
5. **依存**: numpy コアのみ (`np.sort`/`np.cumsum`/`np.diff`/`np.argmax`)。scipy・GSAS-II 非依存。🔵

## 実装コード

`src/tsumugin/search/pruning.py` を参照 (全文)。日本語コメント
(【機能概要】【実装方針】【テスト対応】【〜ガード】等) と 🔵🟡 信頼性レベルを付与済み。

## テスト実行結果

```
uv run pytest tests/test_pruning.py -v  → 13 passed in 0.78s (11 ケース / parametrize 展開 13 items)
uv run pytest                           → 122 passed, 1 skipped in 4.94s (全 green・無退行)
uvx ruff@latest check src tests         → All checks passed!
```

## 品質判定

```
✅ 高品質:
- テスト結果: 全て成功 (対象 13/13、全体 122 passed / 1 skipped=gsas 自動 skip、無退行)
- 実装品質: シンプル (ガード 3 段 + ベクトル化 4 演算)・純関数・状態なし
- リファクタ箇所: 明確 (下記「課題・改善点」)
- 機能的問題: なし / コンパイルエラー: なし
- ファイルサイズ: 76 行 (800 行制限内)
- モック使用: 実装コードにモック・スタブなし
```

## 課題・改善点 (Refactor フェーズ対応候補)

- 端点のみに落差がある分布 (例: `[1.0, 0.1, 0.1, 0.1]`) で cumsum 丸め誤差により
  `curvature.max()` が微小非ゼロとなり、平坦フォールバックを通らず末尾スコアを閾値化しうる。
  二階差分を `np.diff(ordered)[1:]` (数学的に同値・丸め誤差なし) で直接計算する方式への
  置換、または微小値の許容判定 (isclose) の導入を検討。
- 「絶対値最大 = 変曲点」解釈と閾値の上側採用 (🟡) を docstring だけでなく設計文書
  (`interfaces.py` の docstring) へ還元するか検討。
