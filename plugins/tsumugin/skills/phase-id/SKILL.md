---
name: phase-id
description: 未知パターン + 元素一覧から相を同定する (③ 判断層)。MCP ツール (assess_data_quality / identify_phases / identify_phase_mixtures / identify_pattern) を駆動し、背景減算・単相ランキング・多相混合・逐次減算統一同定を使い分ける。同定した相の CIF/formula を PhaseSpec に配線して Rietveld 精密化 (analyze / hypothesis-search skill) へ引き継ぐ。同定は候補提示であり採否は ③、Dara スコアは計量縮退系では効かないことに注意する。
---

# tsumugin: Agentic 相同定 (③ 判断層)

あなた (Claude) が**判断者 ③** として、未知の粉末パターンと元素一覧から相を同定する。**「どの相が
在るか」を候補提示するのが本 skill で、精密化 (定量・格子) は次段** (`analyze` 単一フレーム /
`hypothesis-search` 多仮説裁定 / `insitu` 系列) が担う。同定は提案であり、採否は ③ が下す。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `assess_data_quality` | 前処理 | 観測ファイル → 背景減算検出 + 2θ 上限提案 |
| `identify_phases` | 単相ランキング | 2θ/intensity + elements → Dara スコア順の単相候補 + 未マッチ (unknown_phase_flag) |
| `identify_phase_mixtures` | 多相 (木探索) | 2θ/intensity + elements → 相集合の木探索結果 (相数が概ね既知の混合物) |
| `identify_pattern` | 統一 (逐次減算) | 2θ/intensity + elements → **相数を事前指定せず**残差 S/N < 5σ まで相を積み上げる |

②は候補を返すだけ。物質としての妥当性・採否は ③ が判断する。

## 手順

### 0. データ品質を先に問う

`assess_data_quality(path, excluded_regions=[...])` を掛ける。

- **`is_subtracted`**: 背景減算済みかを見る。同定ツールは既定で SNIP 背景減算 (`subtract_bg=True`)
  するので、**二重減算にならないよう**既に減算済みなら `subtract_bg=False` を渡す。
- `suggested_two_theta_limit` でノイズ域を除く。寄生ピーク窓は `excluded_regions` に入れる。

### 1. どの同定ツールを使うか

| 状況 | ツール |
|---|---|
| 単相が濃厚 / まず最有力候補が欲しい | `identify_phases` |
| **相数が事前に分からない未知試料** | `identify_pattern` (統一・推奨) |
| 相数が概ね分かっている混合物を木探索したい | `identify_phase_mixtures` |

いずれも `elements` に**想定する全元素**を渡す (元素系フィルタの単位)。多い分には安全側。

### 2. 結果を読む — **Dara スコアと計量縮退に注意**

- `identify_phases` の各候補は **Dara スコア** (matched/wrong/missing/extra の 4 分類 + extra 罰) で
  並ぶ。**peak-rich な低対称相は extra 罰で不当に沈む**ことがある。
- **⚠ 計量が縮退した系 (立方晶派生の多形など) では Dara/ピーク位置マッチングは原理的に効かない**。
  ピーク位置がほぼ一致し、区別が**分裂と強度比**にあるため、位置マッチングでは分離できない
  (実測 K₂Mn[Fe(CN)₆] の mono/cubic/tetra は 100% mono の frame でも mono を 1 位にできなかった)。
  この場合は同定に頼らず、既知の候補相を直接 Rietveld で比べる (`compare_structure_models`)。
- `unknown_phase_flag=True` / `identify_pattern` の残差に説明できないピークが残る = **未知相**。
  組成・格子を人間と検討する。安全弁として「同定できない」を正直に返す。

### 3. 精密化へ配線する — **同定 → PhaseSpec → Rietveld**

採用する候補の CIF/formula を `PhaseSpec` にして次段へ渡す:

- 単一フレーム定量・格子精密化 → `analyze` skill (`auto_rietveld`)。
- 複数候補の裁定・化学的妥当性の降格 → `hypothesis-search` skill。
- 系列 (operando/温度) で新相を追いながら → `insitu` skill (`identify_and_add_phase` が
  同定→CIF 物質化→PhaseSpec 配線まで自動)。

DFT (MP) 由来構造は格子が軸別にずれることがあり、精密化側で異方セル補正が入る (#20)。

## 権限境界

| 判断 | 決定論コア (自律) | ③ (あなた/ユーザー) |
|---|---|---|
| 背景減算検出・2θ 上限提案 | ✅ 提示 | 採否 |
| 候補相のランキング・スコアリング | ✅ 提示 (Dara) | **計量縮退系では鵜呑みにしない** |
| 未知相の判定 (unknown_phase_flag) | ✅ 提示 | 組成/格子を検討 |
| **どの相を採用し精密化へ渡すか** | ❌ 提案のみ | ✅ 判断 |

**なぜ同定を鵜呑みにしないか**: ピーク位置マッチングは計量が縮退した多形を分離できず、Dara スコアは
peak-rich 相を沈めうる。同定は「候補の入口」であって「答え」ではない — 最終判断は Rietveld
(強度・分裂を使う) と化学的妥当性で下す。

## 前提

- 相同定は相ライブラリ供給元 (Materials Project 等) を使う。未設定なら error dict が返るので、
  CIF を直接与える運用 (`analyze`/`hypothesis-search` に PhaseSpec を渡す) に切り替える。
- 外部形式の生データ (RIETAN/Z-Code) は `convert_pattern` で `.xye` にしてから渡す。
