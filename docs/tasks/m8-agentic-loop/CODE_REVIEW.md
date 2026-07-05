# M8 セルフレビュー記録 (/code-review)

PR #15。2 体の敵対的サブエージェント (refine_loop コア / MCP+adapter+model) による並行レビュー。

## Round 1 指摘と対応

| # | 重大度 | 指摘 | 対応 |
|---|---|---|---|
| H1 | HIGH | `propose_next_actions` の `SetLimits(NaN, NaN)` プレースホルダが `json.dumps(allow_nan=False)` (MCP server) を crash させる | `SetLimits.low/high` を `float\|None` 化。診断は `None` を出す。`apply` は None で ValueError (プレースホルダは ③ が値を入れてから適用)。シリアライズ None 対応。回帰テスト追加 |
| H-adapter | HIGH | `_result_to_dict` の `refined_cells` のみ `finite_or_none` 未適用 → 発散/崩壊で GSAS が NaN/Inf セルを返すと MCP crash | `finite_or_none` を各成分に適用。回帰テスト (NaN/Inf セル→None・json 安全) 追加 |
| M2 | MEDIUM | `RefinementLoopResult.best` がベースライン (validity 未検査) になりうるのに「受理された中で最良」と誤記 | docstring を実挙動に修正 (validity 不合格ベースラインは open_proposals の ModelAction で ③ が修復) |
| M3 | MEDIUM | `ReviseStructure` の相選択 `next(iter(refined_cells))` が Mapping 反復順依存で NFR-102 決定論に反する | `min(refined_cells, default="")` で相名ソート。順序独立の回帰テスト追加 |
| M-adapter | MEDIUM | `AutoRietveldBackend` の chi2/n_obs が `model.intensity` 長を使い、レンジ制限/joint で GSAS 実 Nobs と不一致 → 絶対 BIC がずれる | 既知制限として docstring 明記 (同一ヒスト集合内の序列比較は妥当、厳密 Nobs 通しは M-later) |
| L4 | LOW | `best` 更新の `<` が `accept_eps` 非一貫 | コメントで意図明記 (受理済み候補の生の最小 Rwp 追跡) |
| L-adapter | LOW | server.py の「8 tools」コメント陳腐化 (実 13) | コメント修正 |

## 見送り (理由付き)

- **session 非依存ツールの引数エラーが error dict でなく例外送出** (LOW, reviewer 2): 既存 10 ツール
  (submit_analysis 等) と同一の pre-existing 挙動。M8 で新規導入した差ではないため、一貫性維持のため
  現状維持。`_call_tool` 全体の error-dict 化は別 Issue 候補 (全ツール共通の振る舞い変更を伴う)。

## Round 2

Round 1 修正後の差分を再レビュー (下記)。新規指摘なしを確認して収束。
