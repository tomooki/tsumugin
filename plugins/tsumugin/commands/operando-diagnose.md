---
description: operando/in situ 系列 Rietveld の結果を疑い、モデルの誤り (欠落相・対称性低下・データ品質) を見つけて改訂する (tsumugin ③ 判断層)。Rwp が良好なまま物理的に誤っている描像を検出する。相集合の変更・構造改訂はユーザー承認を挟む。
argument-hint: <sequential-result.json | frame-files...> [--phases <cif...>] [--elements K,Mn,Fe,C,N]
---

`operando-diagnose` skill を起動し、operando/in situ 系列 Rietveld の結果を**疑う**。

対象: $ARGUMENTS

手順:
1. `operando-diagnose` skill (`plugins/tsumugin/skills/operando-diagnose/SKILL.md`) の手順に従う。
2. **精密化の前に** `assess_data_quality` でデータ品質を問う。`is_subtracted=True` なら
   生データの有無をユーザーに確認する (実測で最大のレバー: Rwp 26% → 6.7%)。
3. 系列結果が未取得なら `sequential_rietveld` で回す (`instrument` spec を明示すること)。
4. **疑う**:
   - `check_phase_set` → `is_complete=False` / `flagged=True` なら、計量の近い相が別相の強度を
     肩代わりしていないかを疑い、**和集合で再フィットして相分率を比較**する。**Rwp が良くても信じない**。
   - 各フレームの `residual_report.top_features` の + 残差 → 未説明ピーク → d 比から欠落相を仮説化。
     強度比のズレ・分裂 → 対称性低下 (部分群) を仮説化。
     `baseline_numerator_fraction` が大きければデータ側の問題 → 手順 2 へ戻る。
   - `repair_frames` → `repairs` は採用済。`needs_model_revision` は相集合/セル解放を再構成する。
5. 相の追加/除外・対称性変更・構造改訂は**ユーザー承認**を得てから適用し、
   **Rwp 改善 ∧ 物理妥当性維持**で受理・外れれば可逆棄却する (提案≠適用)。
6. 「直った」で終わらせず、**単一変数の統制実験**で真因を確定させる。
7. 報告する。**Rwp と併せて、相集合の完全性をどう確認したかを必ず書く**。未確定は未確定と書く。
