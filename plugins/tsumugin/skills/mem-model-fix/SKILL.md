---
name: mem-model-fix
description: MEM (最大エントロピー法) 電子/核密度から構造モデルの誤りを見つけて修正する (③ R5 判断層)。収束済み Rietveld モデルに対し MCP ツール mem_density → propose_structure_revisions → edit_cif → refine_with_revisions を駆動し、未モデル密度ピーク (欠損原子/分割サイト/占有率誤り/水素) を結晶学的に解釈して構造を改訂する。構造編集は必ずユーザー承認を挟み、Rwp 改善 ∧ 物理妥当性維持で受理する。
---

# tsumugin: MEM 駆動の構造モデル修正 (③ R5 判断層)

あなた (Claude) が **判断者 ③** として、収束済み Rietveld モデルの **MEM 密度** を読み、点原子
モデルで説明できない未モデル散乱 (欠損原子・分割サイト・占有率誤り・水素位置) を突き止めて構造を
修正する。残差 (Rwp) は「どこが」を教えないが、**MEM 密度は未モデル散乱がどこにあるかを空間的に
可視化する**ため、構造判断 (R5) の決定的な材料になる。

前提: `analyze` で Rwp/GOF は収束済みだが **物理妥当性 fail・占有率発散・Rwp 停滞**が残る、または
より確かな構造が欲しいとき。設計: `docs/design/m8-agentic-loop/mem-model-fix.md`。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `mem_density` | 計器 (実 MEM) | gpx ハンドル (auto_rietveld 由来) → 密度 min/max・**未モデル密度ピーク[]** (frac/mag/最近接原子/距離)・.grd |
| `propose_structure_revisions` | 計器 (診断) | MEM ピーク + phase → `ReviseStructure` 候補 (具体 evidence: frac/suggested_edit) |
| `edit_cif` | アクチュエータ | CIF + `AtomEdit[]` (add/move/set_occupancy/set_uiso/remove) → 新 CIF ハンドル |
| `refine_with_revisions` | アクチュエータ | spec + `ReviseStructure(edits={"structure_path": 新CIF})` → 再精密化 |

Dysnomia バイナリ未導入なら `mem_density` は `{"error_type": "MEMUnavailableError"}` を返す。その旨と
導入先 (jp-minerals.org/dysnomia を `~/.GSASII/Dysnomia` 等へ) をユーザーに案内する。

## 手順

1. **収束モデルを用意する**: `analyze` (または `auto_rietveld`) で得た `gpx_path` と相の CIF パスを持つ。
2. **`mem_density` を呼ぶ**: probe に応じ密度種別が決まる (X線=電子密度 / 中性子=核密度)。joint は
   `density_kind` か `hist` で対象を指定 (X線/中性子の取り違え防止)。返る `peaks` を読む。
3. **`propose_structure_revisions`** に `peaks` + `density_kind` + `phase` を渡し、`ReviseStructure`
   候補を得る。各候補の `evidence` (frac・magnitude・nearest_atom・suggested_op・suggested_edit) を見る。
4. **密度を結晶学的に読む (R5 — あなたの判断)**:
   - **正の未モデル密度 (原子から離れた位置)** → **欠損原子**。密度の大きさと probe から元素を推定
     (X線=電子数 Z / 中性子=散乱長 b)。空隙/チャンネルなら**部分占有の格子水・イオン**を疑う。
   - **陽イオン近傍の 2 つのピーク** → **分割サイト** (静的無秩序)。両方に部分占有で置く。
   - **既存原子上の弱い/負の密度** → **占有率過大**。核密度が負なら **水素 (b=-3.74 fm) の未モデル**。
   - 化学的妥当性 (電荷中性・配位・結合距離) と矛盾しないかを必ず確認する。
5. **具体編集を決める**: `suggested_edit` テンプレ (op=add, frac 埋め) に **element・occ・uiso を
   あなたが埋める**。占有率は密度の大きさ ÷ その元素の散乱能から初期化し、精密化で詰める。
6. **ユーザー承認を得る (必須)**: 「どのピークを何と読んだか・追加/移動/占有変更の内容・根拠」を
   提示し、**承認を待ってから** `edit_cif` を呼ぶ。承認なしに構造は変えない。
7. **`edit_cif`** で新 CIF を作り、**`refine_with_revisions`** に
   `ReviseStructure(phase, {"structure_path": 新CIF})` を渡して再精密化する。
8. **受理判定**: **Rwp 改善 ∧ `validity.passed` 維持** なら採用。悪化・妥当性を壊すなら**棄却**し
   (元 CIF に戻す)、別の読み (分割/占有/水素) を試す。
9. 未モデル密度が閾値以下 (局在ピークが消える) か、改善が停滞したら終了し、確定モデル・組成・妥当性・
   残った未モデル密度 (説明できない残差) を報告する。

## 権限境界 (architecture.md §4.5 — 厳守)

| 判断 | 自律してよい | ユーザー承認を挟む |
|---|---|---|
| `mem_density` / `propose_structure_revisions` 実行 (計器) | ✅ | — |
| 密度の読み・元素/占有の推定 | ✅ (材料提示) | — |
| **`edit_cif` による構造編集・`ReviseStructure` 適用** | — | ✅ 内容と根拠を示し承認 |
| 相の追加/削除 (`AddPhase`/`RemovePhase`) | — | ✅ |

**なぜ**: MEM 密度は候補を示すが、同じ密度が複数の構造解釈と両立しうる (欠損原子 vs 占有 vs 水素)。
元素・占有・サイト割当は化学・事前知識の判断であり、残差だけからは一意に決まらない。**計器と
アクチュエータは自律・結晶学判断と適用承認は人間**。

## 受理基準

各改訂は **Rwp 改善 ∧ `validity.passed` 維持** のときのみ採用。Rwp が下がっても Uiso<0・占有率逸脱・
電荷破綻・非現実的な結合距離を生む編集は**過剰適合/誤モデル**として棄却する。局在した未モデル密度が
無い (差が背景/プロファイル律速) なら「修正不要」と正しく判定して終了する。

## 失敗・縮退

- Dysnomia 未導入 → `mem_density` がエラー dict。導入を案内し、代替として差フーリエ的な読みは
  行わず終了する (実 MEM が本スキルの前提)。
- 未モデル密度ピークが最近接原子に近い (既にモデル済み) → 候補ゼロ = 修正不要。
- 編集後に精密化が発散 → 元 CIF に戻し、より保守的な編集 (占有率のみ・座標固定) を試す。
