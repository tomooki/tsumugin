---
description: 高温/時間 in situ 粉末回折の系列を全自動で逐次 Rietveld 解析する (tsumugin agentic 閉ループ)。温度/時間フレーム列と初期相を指定すると、ウォームスタート逐次精密化・相転移での新相自動同定 (Materials Project)・格子 vs 温度の抽出を行う。新相追加はユーザー承認を挟む。
argument-hint: <frame-files...> --initial <structure-file> [--elements Ca,Te,O]
---

`insitu` skill を起動し、指定された温度/時間系列の粉末回折を全自動で逐次 Rietveld 解析する。

対象: $ARGUMENTS

手順:
1. `insitu` skill (`plugins/tsumugin/skills/insitu/SKILL.md`) の手順に従う。
2. フレームファイルから `FrameSpec` 列 (data_path・axis_value=温度/時間・data_format) を、初期相から
   `PhaseSpec` を組み立てる。`--elements` があれば `phase_id` の元素系に用いる。
3. MCP ツール `sequential_rietveld` を駆動し、フレーム別 Rwp/格子/相分率・変化点・自動出現相を得る。
4. 系列途中で出現する新相は受理基準 (相分率有意 ∧ Rwp 改善 ∧ 妥当性) で自動追加されるが、
   化学的妥当性を確認し、疑わしければユーザーに承認を求める。自動追加が起きず未指数ピークが残る
   変化点は `identify_and_add_phase` で候補を探し、承認の上で相を足して再実行する。
5. `parametric_fit` で格子 vs 温度の熱膨張・相分率シグモイドの転移温度 (onset/midpoint±σ) を抽出する。
6. 全フレーム収束・相の出現/消失・転移特性・申し送りを報告する。

MCP サーバ未接続なら、その旨と接続方法を案内する。新相自動同定には Materials Project キー
(`MATERIALS_PROJECT_API`) が必要で、未設定時は CIF を直接 initial 相に足す運用を案内する。
