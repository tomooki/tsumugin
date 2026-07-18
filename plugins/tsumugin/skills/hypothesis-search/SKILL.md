---
name: hypothesis-search
description: 多仮説の相同定・裁定を進める (③ 判断層)。MCP ツール (submit_analysis / list_hypotheses / compare_hypotheses / propose_discriminating_measurements / accept_hypothesis / revert / export_gpx) を駆動し、候補相集合から仮説を木探索・evidence (BIC) でランキングし、化学的妥当性 (chem_context) で非物理な相を降格し、僅差競合には判別測定 (OED) を情報利得順に提案し、最終選択を承認境界付きで確定して gpx に書き出す。降格は除外でなく確率補正であり、判別測定・最終採択はユーザー承認を挟む。
---

# tsumugin: Agentic 多仮説 相同定・裁定 (③ 判断層)

あなた (Claude) が**判断者 ③** として、未知試料の候補相集合から仮説を立て、evidence で裁定し、
僅差なら追加測定を提案し、最終選択を確定する M4 フローを駆動する。**相の物質としての妥当性
(化学) と、測定計画 (OED) を人間の判断と噛み合わせる**のが要点。

系列 (operando/温度) は `insitu`/`operando-diagnose`、単一フレーム精密化は `analyze`、未知パターン
からの相同定候補生成は `identify_phases`/`identify_pattern` (analyze skill 手順 1) を併用する。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `submit_analysis` | 探索+裁定 | 観測 (2θ/intensity) + 候補相集合 → 木探索 → evidence ランキング (session 確立) |
| `list_hypotheses` | 一覧 | session の探索結果 → ranked/unknown_phase_flag/未マッチ |
| `compare_hypotheses` | 裁定 (+化学降格) | hypothesis_ids (+ `chem_context`) → evidence/確率/close_competitor。`chem_context` で非物理相を**降格** |
| `propose_discriminating_measurements` | 測定計画 (OED) | (session) → 僅差競合を判別する測定を**情報利得順**に提案 (非破壊・提案のみ) |
| `accept_hypothesis` | 最終選択 | hypothesis_id + by (agent/human) → 採択。human モードは agent 採択を拒否し推奨に留める |
| `revert` | 取消 | hypothesis_id → 採択を superseded 化 (追記型・削除しない) |
| `export_gpx` | 書き出し | hypothesis_id + path → 採択相を GSAS-II .gpx に |

②は判断しない・返すだけ。裁定と承認はあなた/ユーザーがする。

## 手順

### 1. 探索を投入する

`submit_analysis(two_theta, intensity, candidate_phase_sets)` を呼ぶ。候補相集合は
`identify_phases`/`identify_pattern` の同定結果や既知相から組む。返る session で以降の裁定を行う。

### 2. 裁定する — **化学的妥当性で降格する** (chem_context)

`compare_hypotheses(hypothesis_ids, chem_context=...)` で evidence (BIC) と確率を読む。

**`chem_context` を渡すと非物理な相を降格できる** (FR-412)。例: 大気合成で単体アルカリ金属
(Li/Na/K) が候補にあると、それは酸化してしまうので非妥当 → 確率を下げる。

```json
{"atmosphere": "air",
 "phase_compositions": {"Na": {"formula": "Na", "element_system": ["Na"]},
                        "NaCl": {"formula": "NaCl", "element_system": ["Na","Cl"]}}}
```

- **相の組成 (formula/element_system) は ③ が供給する**。Hypothesis の相は phase_ref 文字列しか
  持たず組成を運ばないため、`identify_phases`/`identify_pattern` の `formula` を
  `phase_compositions` に入れる。**未供給の相は降格が静かに効かない**ので、降格を効かせたい相は
  必ず組成を渡す。
- **降格は除外ではない (Dara 教訓)**。低スコア相・仮説も `compared` に残り件数は不変。
  「化学的に不自然だから確率を下げる」だけで、候補から消しはしない。最終判断は evidence と化学の
  両方を見て ③ が下す。`chem_demotion_applied` で降格を配線したかを確認する。

### 3. 僅差なら判別測定を提案する (OED)

`compare_hypotheses` で `close_competitor=True` の仮説が複数あり evidence で決着しないとき、
`propose_discriminating_measurements(close_threshold=...)` を呼ぶ。**僅差競合を最もよく分離する
追加測定を情報利得順に提案**する (例: 中性子回折の追加・特定温度点)。

- **提案のみ・非破壊**。測定の実行やデータ変更はしない。`proposals[].rationale` と
  `estimated_information_gain` を読み、**どの測定を実施するかはユーザーに諮る**。
- 僅差競合が無ければ空提案 = 「evidence で既に決着」のシグナル。

### 4. 最終選択を確定する — **承認境界**

`accept_hypothesis(hypothesis_id, by=...)` で採択する。

- **human モードでは `by="agent"` の採択は拒否**され `{"status": "recommend_only"}` が返る
  (最終選択は人間が握る運用)。その場合は推奨理由を提示し、ユーザーに `by="human"` の採択を仰ぐ。
- agent モードなら自律採択できるが、**化学的に不自然な相を含む仮説・僅差で決着していない仮説は
  採択せず、手順 2/3 に戻る**。
- 誤採択は `revert(hypothesis_id)` で取り消せる (追記型・履歴は消えない)。

### 5. 書き出す

`export_gpx(hypothesis_id, path)` で採択仮説の相を GSAS-II `.gpx` に書き出す。GSAS-II 未導入なら
`{"status": "error", "error": "gsas_unavailable"}` が返るので、その旨をユーザーに伝える。

## 権限境界

| 判断 | 決定論コア (自律) | ③ (あなた/ユーザー) |
|---|---|---|
| 木探索・evidence ランキング | ✅ 自律 | 監督 |
| 化学的妥当性の**降格** (chem_context) | ✅ 提案 (降格のみ・除外しない) | 組成を供給・最終判断 |
| 判別測定の**提案** (OED) | ✅ 情報利得順に提案 (非破壊) | どれを実施するか諮る |
| **最終採択** (accept) | 🟡 agent モードのみ自律 | ✅ human モードは承認必須 |
| 測定の実行・データ変更 | ❌ しない | ✅ 実験者が実施 |

**なぜ降格は除外でないか**: 化学ルールは経験則で、稀な準安定相・特殊雰囲気を誤って弾きうる。
候補を消すと evidence がそれを取り戻せない。降格 (確率補正) なら evidence が強ければ生き残る —
化学と回折の両方の証拠を統合する。

## 前提

- `submit_analysis` で session を確立してから他ツールを呼ぶ (探索結果が無いと空応答)。
- `export_gpx` は GSAS-II 導入が要る。未導入なら error dict。
- `chem_context` の降格を効かせるには相の組成 (formula/element_system) の供給が要る。
