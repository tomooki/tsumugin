---
name: joint
description: X線+中性子 (マルチヒストグラム) 同時 Rietveld 精密化を進める (③ 判断層)。MCP ツール (auto_rietveld を histograms=[...] で複数ヒストグラム指定 / convert_pattern / write_instrument_params / compare_structure_models) を駆動し、中性子の散乱長コントラストで X 線単独では分離できない占有率 (軽元素/隣接元素) を決め、外部形式 (RIETAN/Z-Code) を変換して取り込み、サイトの有無 (ゼオライト水 Ow・重水素) を BIC で判定する。占有率解放は中性子を Uiso より先に、格子は共有し装置係数を別に精密化する。
---

# tsumugin: Agentic X線+中性子 joint 精密化 (③ 判断層)

あなた (Claude) が**判断者 ③** として、X 線と中性子 (放射光/TOF) を**同時に**精密化し、片方だけでは
決まらない構造パラメータ (占有率・軽元素・水素/重水素) を両者のコントラストで決める。

単一ヒストグラムの精密化・段階解放の一般手順は `analyze` skill、構造モデルの MEM 修正は
`mem-model-fix` skill を併用する。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `auto_rietveld` | joint 精密化 | **`histograms=[X線, 中性子, ...]`** (複数指定 = joint) + phases → 段階解放 + validity + 出版値 |
| `convert_pattern` | 取り込み | RIETAN `.int` / Z-Code Igor TOF → `.xye`/FXYE |
| `write_instrument_params` | 取り込み | Z-Code `.zDiffractometer` → `.instprm` (X線 PXC / TOF PNT) |
| `compare_structure_models` | モデル選択 | histograms + variants → BIC 序列 (サイトの有無・空間群の判定) |

②は返すだけ。解放順序・モデル判断は ③ がする。

**精密化成果物 (.gpx) は既定で全部保存される** (2026-08-20 規定; 詳細は `analyze` skill)。
joint も 1 精密化 = 1 ファイルで、`compare_structure_models` は**バリアントごとに 1 つ**残す
(`…_model_<名前>.gpx`) — 棄却モデルがどう壊れていたか (実測 NaCuHCF model5 は Na>1 / O<0 に
発散) を見ずに ΔBIC だけを報告しないこと。置き場所は既定で観測データ隣接、`gpx_dir` で変更可。

## 手順

### 1. ヒストグラムを揃える (外部形式は変換する)

X 線と中性子それぞれの `HistogramSpec` (data_path・instrument_path・radiation・geometry) を作る。

- **外部ソフト形式は先に変換する** (XND): RIETAN-FP `.int` / Z-Code Igor TOF は
  `convert_pattern` で `.xye`/FXYE に、Z-Code `.zDiffractometer` は `write_instrument_params` で
  `.instprm` にして、その `path` を `HistogramSpec` に渡す。
- `radiation` は各ヒストグラムで正しく (`xray_synchrotron`/`neutron_tof`/`neutron_cw`)。**波長/較正
  ファイルの取り違えに注意** (放射光の λ は較正ファイル値をそのまま使わないことがある — 実測 XND)。
- **装置ファイルが無い / 正しいか分からないときは `instrument` skill**。joint は放射源の異なる
  instprm を複数扱うので取り違えが起きやすい — 各ヒストグラムについて
  `inspect_instrument_params(path, radiation=..., geometry=...)` を**宣言する値で**呼び、
  `radiation_type_mismatch` が出ないことを確かめてから `auto_rietveld` に渡す。

### 2. joint で精密化する

`auto_rietveld(histograms=[X線dict, 中性子dict, ...], phases=[...])` を呼ぶ。**histograms を複数
渡すこと自体が joint** (格子は相間で共有、装置係数はヒストグラム毎)。

### 3. **占有率は中性子コントラストで・解放順序を守る**

- **X 線単独では散乱能の近い/軽い元素 (Na/O、混合占有) の分離が弱い**。中性子の散乱長
  (b: 元素で符号も違う) が**そのコントラストを与える** (実測 NaCuHCF: X 線では revert された
  Na/O 分割が、中性子 b [Na 3.63 / O 5.80 / D 6.67 fm] で分離できた)。
- **中性子では占有率を Uiso より先に解放する** (散乱長コントラストが効くうちに占有率を決める)。
  Uiso と同時/先行で Uiso を解放すると占有率と縮退して発散しうる。
- 混合占有は占有率和=1 拘束 + Uiso 等価拘束を使う (analyze skill の一般手順)。

### 4. **サイトの有無は BIC で判定する** (compare_structure_models)

「ゼオライト水 (Ow) は要るか」「重水素 (D) を入れるか」のような**サイトの有無そのもの**は、
Rwp 単独でなく `compare_structure_models` で BIC 比較する。Rwp は母数 (原子) を増やすほど下がるので、
「Ow を足したら Rwp が下がった」だけでは Ow の実在を主張できない。

```json
{"histograms": [X線, 中性子],
 "variants": [{"name": "model5", "phases": [...Ow なし...]},
              {"name": "model6", "phases": [...Ow あり...]}]}
```

`delta_bic` と `best_is_valid` を読む (実測 NaCuHCF: model6[+Ow] は model5 に **ΔBIC≈2.6e5** で
支持され、かつ model6 のみ物理妥当 [model5 は占有率が [0,1] 逸脱] → **Ow は必要**と結論)。

### 5. 報告する

出版値は重量分率 ± esd・格子 ± esd (`phase_weight_fractions`/`cell_esd`)。X 線と中性子どちらが
どのパラメータを決めたか (占有率は中性子・格子は joint 等) を明記する。**joint でも決まらないもの
(水素位置など) は正直に「決定不能」と書く** (実測: 水 H/D 位置は joint でも決められず、骨格/格子は
頑健だった)。

## 権限境界

| 判断 | 決定論コア (自律) | ③ (あなた/ユーザー) |
|---|---|---|
| 段階解放・格子共有・装置係数分離 | ✅ 自律 (Rwp∧validity) | 監督 |
| 占有率の解放順序 (中性子先行) | 🟡 recipe が調整 | 初期値・順序の指定 |
| **サイトの有無 (Ow/D) の判定** | ❌ compare で BIC を出すだけ | ✅ ΔBIC + 妥当性で判断 |
| 波長/較正の取り違えの是正 | ❌ | ✅ 実験条件から判断 |

## 前提

- GSAS-II 導入が要る。未導入なら auto_rietveld が error dict。
- 外部形式は `convert_pattern`/`write_instrument_params` で GSAS 形式にしてから渡す。
- D₂O の重水素配置など構造の細部は `mem-model-fix` skill (密度から) を併用する。
