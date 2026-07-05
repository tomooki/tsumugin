# M7 セルフレビュー記録 (/code-review)

対象: `milestone/m7-real-data-validation` (main...HEAD, 実装差分 src/tsumugin/autorietveld + reference/io)
レビュー: 独立サブエージェント (敵対的レビュー) + 自己レビュー。CLAUDE.md 準拠で HIGH/MEDIUM/LOW を修正、
見送りは理由を記録。

## 修正した指摘

| # | 重大度 | 箇所 | 内容 | 修正 |
|---|---|---|---|---|
| H1 | HIGH | engine.py 復帰ガード | 復帰時に `nvar` が失敗段階の値を記録 (BIC/母数比較を汚染) | `prev_gof`/`prev_nvar` を明示追跡し復帰時に巻き戻す |
| H2 | HIGH | engine.py 復帰ガード | 初段失敗時に復帰せず `prev_rwp=inf` が残り、以降のガードが劣化 | スナップショット (段階適用前状態) へ**常に**復帰。初段失敗でも健全プロジェクトへ戻す |
| M4 | MEDIUM | multistart `_grid_scales` | 偶数 n で非対称・開始点浪費 (n=2 が下側未探索) | `t=-1+2i/(n-1)` の対称グリッドに。奇数 n は中心 1.0 を厳密に含む |
| M5 | MEDIUM | multistart `select_best` | 全開始点失敗 (result=None) で `min([])` が crash | `best` を Optional 化、空プールで `(-1, None)` を返す。回帰テスト追加 |
| M6 | MEDIUM | engine 多相 validity | `phase_fractions=None` 固定で相分率和=1 検査が dead code | `_extract_phase_fractions` (HAP Scale) を多相時に抽出し検査 |
| L8 | LOW | multistart | 関数内 `import math` (lazy 境界でない) | モジュール先頭へ |
| L9 | LOW | validity Uiso | `u>0` で固定 0/数値ノイズ微小負を誤って非物理判定 | `uiso_neg_tol` (1e-4) 導入。明確な負・上限超過のみ弾く。回帰テスト追加 |

## 見送った指摘 (理由付き)

| # | 重大度 | 内容 | 見送り理由 |
|---|---|---|---|
| M3 | MEDIUM | 単調改善 revert が過渡的悪化を許さず局所解に留まり得る (許容帯提案) | **意図的設計** (FR-202 単調改善)。T1–T4 は実測で単調収束を確認済み。許容帯 (`rel_slack`) は将来のチューニング項目 (M-later)。`worsen_eps` で微小許容は既にある |
| L10 | LOW | 占有率を全原子抽出し厳格に [0,1] 判定 (規約差で >1 の恐れ) | 標準 CIF では誤検出なし (レビュアーも "no action" 判定)。混合占有は和=1 制約で担保 |
| L11 | LOW | io.py の 2 つの FXYE 経路 (engine=GSAS importer / parse_fxye=numpy) | レビュアーが「io.py に問題なし」と確認。centidegree 変換も正しい |

## 再レビュー (修正ループ)

修正後の差分を再度敵対的レビュー。Fix 1-3 は正しいと確認。ただし **M6 修正が新規の潜在不具合を導入**:

| # | 重大度 | 箇所 | 内容 | 修正 |
|---|---|---|---|---|
| R1 | LOW-MED | engine `_extract_phase_fractions` | 相分率抽出失敗を `continue` で捨て長さが縮み、check_validity の和検査が黙って skip → 偽 valid | 失敗相は `NaN` を入れ**長さを相数に保つ** (NaN で和検査が fail)。回帰テスト追加 |

再々レビュー相当の確認: R1 修正は局所的で、NaN → `check_validity` の `abs(nan-1)<=tol` が False → 明示 fail。
これ以上の新規指摘なし → **修正ループ収束**。

## 検証

- 純ロジックテスト green + 回帰テスト追加 (M4 対称グリッド / M5 全失敗 None / L9 Uiso 許容 / R1 NaN 相分率)。
- 実データ gsas テスト (T1–T4 + multistart T1) で修正後も回帰なしを確認。
- 全 1254 tests green (0 failed)。修正ループ収束。
