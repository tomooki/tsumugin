---
description: 未知試料の候補相集合から多仮説を木探索・evidence (BIC) で裁定し、化学的妥当性で非物理な相を降格し、僅差競合には判別測定 (OED) を情報利得順に提案し、最終選択を承認境界付きで確定する (tsumugin ③ 判断層)。降格は除外でなく確率補正・判別測定と最終採択はユーザー承認を挟む。
argument-hint: <pattern.xy | 2theta,intensity> --elements <K,Mn,Fe,C,N> [--phases <cif...>]
---

`hypothesis-search` skill を起動し、多仮説の相同定・裁定を進める。

対象: $ARGUMENTS

手順:
1. `hypothesis-search` skill (`plugins/tsumugin/skills/hypothesis-search/SKILL.md`) の手順に従う。
2. 候補相集合を `identify_phases`/`identify_pattern` (元素一覧) や既知相から組み、
   `submit_analysis` で探索を投入する (session を確立)。
3. `compare_hypotheses` で evidence/確率を読む。**化学的に非物理な相 (例 大気合成の単体アルカリ金属)
   は `chem_context` で降格する** — 相の組成 (formula/element_system) を同定結果から
   `phase_compositions` に供給する。**降格は除外ではない** (低スコア相も残す)。
4. 僅差競合 (`close_competitor=True` が複数) で決着しないときは
   `propose_discriminating_measurements` で判別測定を情報利得順に提案する
   (**提案のみ・非破壊**、どれを実施するかはユーザーに諮る)。
5. `accept_hypothesis` で最終選択を確定する。**human モードでは agent 採択が拒否される**ので
   推奨理由を提示してユーザーの採択を仰ぐ。誤採択は `revert` で取り消す (追記型)。
6. `export_gpx` で採択相を `.gpx` に書き出す (GSAS-II 未導入なら error dict)。
