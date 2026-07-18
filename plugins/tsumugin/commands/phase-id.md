---
description: 未知の粉末パターン + 元素一覧から相を同定する (tsumugin ③ 判断層)。背景減算・単相ランキング・多相混合・逐次減算統一同定を使い分け、同定した相を Rietveld 精密化へ配線する。同定は候補提示であり採否は ③、Dara スコアは計量縮退系では効かないことに注意する。
argument-hint: <pattern.xy | pattern.int> --elements <K,Mn,Fe,C,N> [--multi]
---

`phase-id` skill を起動し、未知パターンから相を同定する。

対象: $ARGUMENTS

手順:
1. `phase-id` skill (`plugins/tsumugin/skills/phase-id/SKILL.md`) の手順に従う。
2. **精密化の前に** `assess_data_quality` で背景減算 (二重減算回避) と 2θ 上限を確認する。
   外部形式の生データは `convert_pattern` で `.xye` にする。
3. 同定ツールを選ぶ: **相数が分からなければ `identify_pattern`** (統一・推奨) /
   単相なら `identify_phases` / 相数既知の混合物なら `identify_phase_mixtures`。
   `elements` に想定する全元素を渡す。
4. 結果を読む。**計量が縮退した多形 (立方晶派生など) ではピーク位置マッチングは効かない** ので
   Dara スコアを鵜呑みにせず、既知候補を直接 Rietveld で比べる (`compare_structure_models`)。
   `unknown_phase_flag` / 残差の未説明ピークは**未知相**として正直に扱う。
5. 採用する候補の CIF/formula を PhaseSpec にして精密化へ配線する
   (`analyze` 単一フレーム / `hypothesis-search` 多仮説裁定 / `insitu` 系列)。同定は提案・採否は ③。
