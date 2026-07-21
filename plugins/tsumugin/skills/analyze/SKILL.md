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
| `auto_rietveld` | 計器 (実行) | histograms/phases spec (JSON) → 段階別/最終 Rwp・格子・validity・**spec ハンドル**。任意で `stages` (追加段階, 下記) / `max_cyc` |
| `propose_next_actions` | 計器 (診断) | 直前結果 + 残差シグネチャ → `ActionProposal[]` (rationale/priority/**safe**) |
| `refine_with_revisions` | アクチュエータ | spec + あなたが決めた `AnalysisAction[]` → 改訂適用して再実行。`stages`/`max_cyc` も同様に渡せる |

閉ループ丸ごと (agentic_analyze) は MCP に**無い**。回すのはあなた。

## 手順

1. **入力を組み立てる** (AGENT_PLAYBOOK §1): データ/装置ファイルから `Radiation`・`Geometry`・
   `data_format` を判定し `HistogramSpec`/`PhaseSpec` の JSON を作る。CIF が無い相は
   `identify_phases` (元素一覧 → 単相ランキング) で候補構造を得る。
   - **相数が事前に分からない未知試料**は `identify_pattern` (M11 統一同定) を使う。1 相受理する
     ごとに残差からその寄与を減算し、**残差 S/N < 5σ になるまで**積み上げる (単相なら 1 相で停止、
     多相なら複数相)。`accepted[]` の各相の CIF/formula を `PhaseSpec` に配線して精密化へ進む
     (提案のみ・採否は ③)。外部形式の生データは手順 0 で `convert_pattern` して渡す。
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

## 精密化段階を追加する (`stages` / `max_cyc`)

`auto_rietveld`/`refine_with_revisions` は既定の 7 段階レシピ (`build_recipe`) の末尾に**追加段階**を
足せる (`stages` 引数, Issue #101)。既定レシピが試さない knob は ③ が明示的に足す必要がある:

```json
{"stages": [{"label": "S9 absorption", "flags": {"absorption": true}, "note": "弱吸収試料"}]}
```

| どの knob がいつ効くか | `flags` |
|---|---|
| X 線 (実験室/放射光) の残差が高止まり (CaTeO3 型: U,V,W だけでは形状に合わない) | `{"profile_lorentzian": true}` |
| TOF 中性子/放射光の残差が高止まり (XND T4 型) | `{"tof_profile": true}` |
| 選択配向が疑われる系統的 obs>calc | `{"preferred_orientation": 4}` (SH order) |
| 試料吸収が強い (透過配置の弱吸収試料) | `{"absorption": true}` |
| サイズ/微小歪みの型を変える (異方) | `{"size_strain": "uniaxial"}` / `"generalized"` (X 線限定) |

**追加段階も revert ガードが効く** — 悪化すれば当該段階だけ棄却され、他段階には影響しない
(既定レシピと同じ安全網)。まず 1 段だけ足して試し、`stages[*].reverted` で効いたか確認する。

`stages` は `auto_rietveld` が返す `specs` ハンドルにも同梱される (`specs["stages"]`) ので、
`refine_with_revisions` を反復するときは持ち回ること (省略すると追加段階が消える)。

`max_cyc` (既定 12) は各段階の最大精密化サイクル数。収束が遅い/振動する系で増やす。

## 構造改訂が要るとき → `mem-model-fix` skill

Rwp は収束したが **物理妥当性 fail・占有率発散・構造の誤りが疑われる**とき、残差だけでは「どこを
どう直すか」が一意に決まらない。**MEM (電子/核密度) で未モデル散乱を空間的に可視化して構造を修正
する** `mem-model-fix` skill (`plugins/tsumugin/skills/mem-model-fix/SKILL.md`, `/mem-fix`) へ引き継ぐ。
MCP `mem_density` → `propose_structure_revisions` → `edit_cif` → `refine_with_revisions` を駆動し、
欠損原子/分割サイト/占有率誤り/水素を判断する (構造編集はユーザー承認・Rwp 改善∧妥当性維持で受理)。
