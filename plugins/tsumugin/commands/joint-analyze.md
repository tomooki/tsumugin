---
description: X線+中性子 (マルチヒストグラム) 同時 Rietveld 精密化を進める (tsumugin ③ 判断層)。中性子コントラストで占有率を決め、外部形式を変換して取り込み、サイトの有無 (Ow/D) を BIC で判定する。占有率は中性子を Uiso より先に、格子は共有し装置係数を別に精密化する。
argument-hint: <xray.xye> <neutron.fxye|.int|.histogramIgor> --phases <cif...> [--instprm <...>]
---

`joint` skill を起動し、X線+中性子を同時精密化する。

対象: $ARGUMENTS

手順:
1. `joint` skill (`plugins/tsumugin/skills/joint/SKILL.md`) の手順に従う。
2. 外部形式 (RIETAN `.int` / Z-Code Igor TOF) は `convert_pattern`、Z-Code `.zDiffractometer` は
   `write_instrument_params` で GSAS 形式にする。各ヒストグラムの `radiation` を正しく設定する。
3. `auto_rietveld(histograms=[X線, 中性子], phases=[...])` で精密化する
   (**histograms を複数渡すこと自体が joint**、格子共有・装置係数分離)。
4. **占有率は中性子コントラストで、Uiso より先に解放する** (X線単独で分離できない Na/O・混合占有を
   中性子 b で分ける)。
5. **サイトの有無 (Ow/D) は `compare_structure_models` で BIC 比較**する (Rwp 単独では母数増で必ず
   下がるため主張できない)。`delta_bic` と `best_is_valid` を読む。
6. 報告する。出版値は重量分率 ± esd・格子 ± esd。どのパラメータを X線/中性子どちらが決めたか明記し、
   **joint でも決まらないもの (水素位置等) は「決定不能」と正直に書く**。
