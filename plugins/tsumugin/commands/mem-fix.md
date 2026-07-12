---
description: 収束済み Rietveld モデルの MEM (電子/核密度) を読んで構造モデルの誤り (欠損原子/分割サイト/占有率/水素) を修正する。mem_density → propose_structure_revisions → edit_cif → refine_with_revisions を駆動し、構造編集はユーザー承認、Rwp 改善∧妥当性維持で受理する。
argument-hint: <gpx-path> <phase-cif> [--probe electron|nuclear]
---

`mem-model-fix` skill を起動し、指定の収束済みモデルを MEM 密度で見直して構造を修正する。

対象: $ARGUMENTS

手順:
1. `mem-model-fix` skill (`plugins/tsumugin/skills/mem-model-fix/SKILL.md`) の手順に従う。
2. `mem_density` で MEM 密度と未モデル密度ピークを取得する (probe/hist で対象を指定)。
3. `propose_structure_revisions` で `ReviseStructure` 候補を得て、密度を結晶学的に読む
   (欠損原子/分割サイト/占有率誤り/水素)。
4. 元素・占有・座標を決め、**内容と根拠を提示してユーザー承認を得てから** `edit_cif` で新 CIF を作る。
5. `refine_with_revisions` に `ReviseStructure(structure_path=新CIF)` を渡して再精密化し、
   **Rwp 改善 ∧ 物理妥当性維持** なら採用・さもなくば棄却する。
6. 未モデル密度が消えるか停滞で終了し、確定モデル・組成・妥当性・残差を報告する。

Dysnomia 未導入なら `mem_density` がエラーを返す。導入先 (jp-minerals.org/dysnomia) を案内する。
MCP サーバ未接続なら、その旨と接続方法を案内する。
