---
name: instrument
description: 装置パラメータファイル (.instprm) が無い / 正しいか分からないときに、作る・直す・検査する (③ 判断層)。MCP ツール (read_pattern_metadata / list_instrument_presets / create_instrument_params / inspect_instrument_params / calibrate_instrument / write_instrument_params / convert_pattern) を駆動し、観測データ自身が持つ測定条件・GSAS-II 同梱プリセット・標準試料 (CeO2/Si) の実測から instprm を用意する。auto_rietveld / sequential_rietveld / anchored_sequential の instrument_path はここから来る。
---

# tsumugin: 装置パラメータファイルを用意する (③ 判断層)

`auto_rietveld` / `sequential_rietveld` / `anchored_sequential` はいずれも装置パラメータ
ファイル (`.instprm`) を要求する。**利用者がこれを持っていない、または正しいか自信が無い**のは
最も普通の状況であり、粉末回折解析で最初に詰まる場所でもある。この skill はその一点だけを扱う。

精密化そのものの手順は `analyze` skill、joint は `joint` skill、operando は `insitu` /
`operando-diagnose` skill を使う。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `read_pattern_metadata` | 材料集め | 観測データ → そのファイルが持つ波長 / Kα2 の扱い / 反射透過 |
| `list_instrument_presets` | 材料集め | (なし) → GSAS-II 同梱の既定装置パラメータ一覧 ⚠ GSAS-II 導入が要る |
| `create_instrument_params` | **作る** | 波長 or プリセット or 観測データ → `.instprm` を書き出す |
| `inspect_instrument_params` | **検査** | `.instprm` → 指摘 (放射源の取り違え・Kα2 整合・必須キー欠落) |
| `calibrate_instrument` | **実測** | 標準試料 (CeO2/Si) の生データ → 実測分解能を焼き込んだ `.instprm` ⚠ 重い |
| `write_instrument_params` | 取り込み | Z-Code `.zDiffractometer` → `.instprm` |
| `convert_pattern` | 取り込み | RIETAN `.int` / Z-Code Igor TOF → `.xye` / FXYE |

②は返すだけ。どの経路を採るか・作った値を信じてよいかは ③ が判断する。

## 手順

### 1. **まず観測データに聞く** (read_pattern_metadata)

装置ファイルを作る前に、**手元のデータが何を知っているか**を確認する。

```json
{"data_path": "frame_030.xrdml"}
```

Panalytical XRDML は波長・Kα2 の扱い・反射/透過を**ファイル自身に持っている**。返り値の
`wavelength` / `kalpha2_stripped` / `geometry` / `radiation` はそのまま次の手順の引数になる。

⚠ **FXYE / GSAS / XYE / INT / IGOR は波長を構造的に持たない** (それを外部ファイルに置くのが
装置パラメータファイルの役目)。`source_format` だけが返る — これは失敗ではない。その場合は
手順 2 か 3 へ進む。**波長を勝手に Cu Kα と決めないこと** (放射光データを黙って壊す)。

### 2. 作る (create_instrument_params)

3 通りの与え方がある。**上から順に試す** (情報の確かさの順)。

| 状況 | 呼び方 |
|---|---|
| XRDML など**データが測定条件を持っている** | `{"out_path": "x.instprm", "from_data_path": "frame_030.xrdml"}` |
| 波長が分かっている | `{"out_path": "x.instprm", "radiation": "xray_synchrotron", "wavelength": 0.79958}` |
| TOF の変換係数が分かっている | `{"out_path": "n.instprm", "radiation": "neutron_tof", "tof": {"difC": 10060.51, "difA": -1.13, "Zero": -2.65, "two_theta": 90.0}}` |
| 装置がありふれていて何も分からない | `list_instrument_presets` → `{"out_path": "x.instprm", "preset": "CuKa lab data"}` |
| Z-Code `.zDiffractometer` がある | `write_instrument_params` を使う (この skill の表の下段) |
| 標準試料 (CeO2/Si) を測ってある | 手順 4 の `calibrate_instrument` を使う |

返り値の `path` を、そのまま次へ渡す:

- `auto_rietveld` の `histograms[].instrument_path`
- `sequential_rietveld` / `anchored_sequential` / `repair_frames` の `instrument` spec の `path`

⚠ **プロファイル (U,V,W,X,Y,SH/L) は「とりあえず動く既定値」**であり、その装置の実測値ではない。
精密化の段階解放で解かれるので出発点としては十分だが、**装置分解能を固定して試料の広がり
(size/mustrain) を分離したいなら手順 4 が要る**。

### 3. **必ず検査する** (inspect_instrument_params)

作った場合も、もらった場合も、精密化を始める前に一度検査する。**解析で宣言するのと同じ
`radiation` / `geometry` を渡すこと** — 検査の主目的が両者の整合だから。

```json
{"path": "x.instprm", "radiation": "xray_lab", "geometry": "bragg_brentano"}
```

`findings[].severity` の読み方:

| severity | 意味 | ③ がすること |
|---|---|---|
| `error` | このままでは解析が壊れる | **精密化を始めない**。`hint` に従って直す |
| `question` | ファイルだけでは決まらない | **利用者に聞く** (推測で進めない) |
| `warning` / `info` | 承知した上でなら進めてよい | `message` を報告に残す |

とくに重要な 2 件:

- **`kalpha2_consistency_question`** — instprm が Kα1+Kα2 の二重線モデルのとき。**観測データが
  Kα2 除去済み (単色化済み) なら、二重線 instprm は最大の系統残差になる** (実測: 実験室 X 線
  CaTeO3 で、Kα2 の phantom ピークが残差の最大要因だった)。データが除去済みかを確認し、
  除去済みなら `create_instrument_params` に **Kα1 だけ**を渡して作り直す。
  `read_pattern_metadata` の `kalpha2_stripped` が答えを持っていることがある。
- **`radiation_type_mismatch`** — 別の測定の装置ファイルを渡している。これは `error`。

### 4. 装置分解能を実測する (calibrate_instrument) — 標準試料があるとき

⚠ **GSAS-II で実際に精密化を回すので数十秒〜数分かかる**。以下のいずれかに当てはまるときだけ使う。

- 試料の結晶子サイズ / 微小歪みを**定量したい** (装置由来の広がりと分離する必要がある)
- 装置プロファイルを自由精密化したら非物理な値 (負の FWHM など) に発散した

```json
{"data_path": "CeO2.dat", "out_path": "beamline.instprm",
 "wavelength_init": 0.79958, "standard": "CeO2", "two_theta_limits": [2.0, 60.0]}
```

判断のポイント:

- **`two_theta_limits` を必ず与える** — 直接ビーム/低角ノイズが最小二乗を支配して平坦化する。
- **波長は精密化されない** (既定)。強反射が低角に偏ると波長は試料変位と縮退して分離できない
  (CeO2 実測: 変位固定 +67 ppm・変位解放 +1172 ppm で同じ Rwp)。**標準試料から波長を較正した
  と主張しないこと**。波長はモノクロメータのエネルギー較正値を使う。
- **非負拘束は既定で入る** (`constrain_nonneg`)。**転写可能な分解能には非負拘束が必須** —
  無拘束の解はその標準試料にはよく合うが、他の試料に移すと高角で総 FWHM が負になり破綻する。
- `source_rwp` を報告に残す (その分解能値がどれだけ信用できるかの出所)。

### 5. 報告する

装置パラメータの**出所**を必ず書く。`create_instrument_params` の返り値 `source`
(`data` / `preset:<名前>` / `explicit`) と、`calibrate_instrument` の `source_rwp` がその根拠になる。
プリセットや既定プロファイルで済ませた場合は、**「装置分解能は実測していない」と明記する**
(結晶子サイズ・微小歪みの値を出すなら特に)。

## 権限境界

| 判断 | 決定論コア (自律) | ③ (あなた/ユーザー) |
|---|---|---|
| 波長からの instprm 生成・書式 | ✅ 自律 | — |
| ファイルの検査と指摘の列挙 | ✅ 自律 | — |
| 標準試料からの分解能抽出 (段階解放/非負拘束) | ✅ 自律 (Rwp∧物理性) | 標準試料とレンジの指定 |
| **データが Kα2 除去済みか** | ❌ (XRDML の宣言がある場合のみ判る) | ✅ 測定条件から判断 |
| **どの波長が真か** (較正ファイルと実効値の食い違い) | ❌ | ✅ ビームライン諸元から判断 |
| **プリセットで済ませてよいか** | ❌ | ✅ 求める精度から判断 |

## 前提

- `create_instrument_params` / `inspect_instrument_params` / `read_pattern_metadata` は
  **GSAS-II 無しで動く**。`list_instrument_presets` (と `preset` 指定) と `calibrate_instrument`
  だけが GSAS-II 導入を要する — 未導入なら error dict が返るので、波長を明示する経路へ切り替える。
- 装置パラメータの由来 (どの値がどこから来るか) の一覧は
  `docs/reference/serious-refinement-flow.md` §1.1。
