---
name: analyze
description: 粉末回折 (X線/中性子) の全自動 Rietveld 解析を閉ループで進める。MCP 3 ツール (auto_rietveld / propose_next_actions / refine_with_revisions) を反復駆動し、SafeAction (背景/母数解放) は自律適用、ModelAction (データリミット/相追加削除/構造改訂/混合占有) は判断してユーザー承認を挟む。Rwp/GOF と物理妥当性でチュートリアル同等を目指す。
---

# tsumugin: Agentic Rietveld 解析 (③ 判断層)

あなた (Claude) が**判断者 ③** として、tsumugin の MCP 3 ツールを反復駆動し、フィット結果を
観測して次手を決め再実行する閉ループ解析を行う。ライブラリは決定論コア (①) と薄い MCP (②) を
提供し、**開放的判断 (R3) と構造改訂・事前知識 (R5) はあなたが担う**。

設計: `docs/design/m8-agentic-loop/architecture.md` / 手順詳細: M7 `AGENT_PLAYBOOK.md` §8。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `auto_rietveld` | 計器 (実行) | histograms/phases spec (JSON) → 段階別/最終 Rwp・格子・validity・**spec ハンドル** |
| `propose_next_actions` | 計器 (診断) | 直前結果 + 残差シグネチャ → `ActionProposal[]` (rationale/priority/**safe**) |
| `refine_with_revisions` | アクチュエータ | spec + あなたが決めた `AnalysisAction[]` → 改訂適用して再実行 |

閉ループ丸ごと (agentic_analyze) は MCP に**無い**。回すのはあなた。

## 手順

1. **入力を組み立てる** (AGENT_PLAYBOOK §1): データ/装置ファイルから `Radiation`・`Geometry`・
   `data_format` を判定し `HistogramSpec`/`PhaseSpec` の JSON を作る。CIF が無い相は
   `identify_phases` (元素一覧) で候補構造を得る。
2. **`auto_rietveld` を呼ぶ**。返る `specs` ハンドルを保持する。
3. **結果を読む**: `final_rwp`/`final_gof`、`validity.passed` と項目別 `checks`、`stages[*].reverted`。
   目標に届いていれば終了。
4. **`propose_next_actions` を呼ぶ** (残差シグネチャは結果と観測から見積もる)。各提案の `safe` を見る。
5. **次手を判断する** (権限境界):
   - **`safe=True` (SafeAction)** — 背景増項 `AdjustBackground` / 母数追加解放 `ReleaseParams` は
     採用してよい。適用後 Rwp が改善せず・validity を壊すなら**戻す** (過剰適合ガード)。
   - **`safe=False` (ModelAction)** — 下表の判断を要する手。**あなたが結晶学・化学の文脈で決め**、
     **構造改訂 (`ReviseStructure`)・相追加 (`AddPhase`) は必ずユーザー承認を挟む**。
6. **`refine_with_revisions`** に採った Action を渡して再実行。`specs` を持ち回り 3 へ戻る。
7. 目標 Rwp 到達 / 改善停滞 / 反復上限で終了し、最良結果と申し送り (未適用 ModelAction) を報告する。

## 権限境界 (architecture.md §4.5 — 厳守)

| 判断 | 自律してよい | ユーザー承認を挟む |
|---|---|---|
| 背景増項・母数追加解放・停止 | ✅ | — |
| 保守的初期リミット (setup) | ✅ (提案を採用) | 大きく切るなら確認 |
| データリミット精密化 | — | 🟡 切り位置を提示して確認 |
| 相の追加/削除・混合占有割当 | — | ✅ 候補と根拠を示し承認 |
| 構造改訂 (空間群/原子/原点)・事前知識 | — | ✅ 変更内容を示し承認 |

**なぜ**: 残差からは原因が一意に決まらない (同じ残差が複数原因と両立)。パラメトリックで
自己検証可能な手だけ自律し、構造・相・事前知識に踏み込む手は人間の承認下で行う。

## 受理基準

各改訂は **Rwp 改善 ∧ `validity.passed` 維持** を満たすときのみ採用する。Rwp が下がっても
Uiso<0・占有率逸脱・格子逸脱を生む手は過剰適合として棄却する。データリミット変更は観測集合が
変わり Rwp 比較不能なので、別に妥当性で評価する。

## 失敗時 (AGENT_PLAYBOOK §6)

Rwp 停滞→構造/空間群を確認 (ReviseStructure 候補)、占有率発散→混合占有制約 (SetMixedOccupancy)、
座標段階でセル発散→特殊位置の座標解放を避ける、TOF/放射光の高止まり→データリミット、
未指数ピーク→相追加 (AddPhase, 相同定へ)。いずれも ModelAction はユーザー承認を挟む。
