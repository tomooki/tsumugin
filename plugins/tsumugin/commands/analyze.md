---
description: 粉末回折データを全自動 Rietveld 解析する (tsumugin agentic 閉ループ)。データ/装置/相ファイルを指定すると、MCP 4 ツールを反復駆動して Rwp/GOF と物理妥当性を最適化する。SafeAction は自律、構造改訂・相追加はユーザー承認を挟む。
argument-hint: <data-file> [instrument-file] [structure-file...]
---

`analyze` skill を起動し、指定された粉末回折データを全自動 Rietveld 解析する。

対象: $ARGUMENTS

手順:
1. `analyze` skill (`plugins/tsumugin/skills/analyze/SKILL.md`) の手順に従う。
2. 入力ファイルから `HistogramSpec`/`PhaseSpec` を組み立てる (放射源/ジオメトリ/形式を判定)。
3. まず `propose_data_preprocessing` でデータレンジ/背景項数/除外領域候補を測る
   (**除外領域は提案のみ** — 適用はユーザー承認)。続いて MCP ツール `auto_rietveld` →
   `propose_next_actions` → `refine_with_revisions` を反復駆動する。
4. SafeAction (背景/母数解放) は自律適用。ModelAction (データリミット/相追加削除/構造改訂/混合占有)
   は判断し、構造変更・相追加はユーザーに承認を求める。
5. 目標 Rwp 到達 / 停滞 / 上限で終了し、最良結果・格子・妥当性・申し送りを報告する。

MCP サーバ未接続なら、その旨と接続方法を案内する。
