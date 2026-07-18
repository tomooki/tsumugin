---
name: insitu
description: 高温/時間 in situ 粉末回折の逐次 (parametric sequential) 全自動 Rietveld 解析を閉ループで進める。MCP ツール (sequential_rietveld / identify_and_add_phase / parametric_fit) を反復駆動し、温度/時間フレーム列をウォームスタートで逐次精密化、相転移で出現する新相を Materials Project から自動同定して相集合に追加、格子 vs 温度・転移温度を抽出する。初期相のみ与えれば新相は自動発見する。データ品質 (背景減算) の確認と相集合の完全性検証 (check_phase_set) を必須手順として含む。
---

# tsumugin: Agentic 高温 in situ 逐次 Rietveld 解析 (③ 判断層)

あなた (Claude) が**判断者 ③** として、温度/時間系列の粉末回折を逐次 Rietveld 精密化する閉ループ
解析を行う。M7 単一フレーム自動 Rietveld + M8 agentic 閉ループ + M6 相同定を統合した M9 の系列版。
**初期相のみ与えられ、系列途中で出現する新相 (例 CaTeO3 の脱水相 delta) は自動同定する**のが要点。

設計: `docs/design/m9-insitu-sequential/architecture.md`。
系列結果を**疑う**側 (相集合の誤り・モデル改訂) は `operando-diagnose` skill が担当し、本 skill と併用する
(`docs/design/operando-diagnosis/architecture.md`)。

> **この skill の最重要点**: **Rwp だけで収束を判定しない**。Rwp は**相集合の誤りに盲目**である。
> 実データ (K2Mn[Fe(CN)6] 放射光 operando) で、**Rwp 8% (目標帯内) のまま**、計量の近い tetragonal 相が
> 転移端の残留 monoclinic の強度を**肩代わり**し、「tetra が増減を繰り返す」非物理な描像を生成した。
> どの統計量でも拾えず、発見は**人間の物理的直感**だった。手順 0 と手順 5 は必須である。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `assess_data_quality` | 計器 (データ品質) | 観測ファイル → 背景減算検出 + 2θ 上限提案 |
| `sequential_rietveld` | 計器+アクチュエータ (前方単一パス) | frames + initial_phases spec (JSON) → フレーム別 Rwp/格子/相分率/残差レポート/**出版値 (重量分率±esd・格子 esd)**・変化点・自動出現相 |
| `anchored_sequential` | 計器+アクチュエータ (M10 双方向) | frames + phases catalog + `anchor_table` {frame_index: [phase]} + instrument → アンカー起点の双方向精密化。`crossovers[].total_bic` で相集合を **Rwp でなく bic** で選定 (相数を抑制し偽相を全域に広げない)。**転移を含む operando の既定**。出力は sequential_rietveld と同型 + `anchors`/`crossovers` |
| `check_phase_set` | 計器 (相集合) | 系列結果 → 相集合の完全性 + 相分率の非単調 (zigzag) フラグ + seed 張り付き + 分率凍結 |
| `repair_frames` | 計器+アクチュエータ | 系列結果 + frames + phases (+ `target_frames` で対象明示) → 不連続/張り付きフレームの近傍 warm-start 修復。`repairs[]` に**修復後の出版値** (重量分率 ± esd・`cell_esd`) を同梱 |
| `identify_and_add_phase` | 計器 (相同定) | 残差/生パターン + elements + workdir → 物質化した PhaseSpec 候補 (CIF パス) + 根拠 |
| `parametric_fit` | 計器 (解析) | 系列結果 + parameter/axis → 熱膨張多項式係数・転移 onset/midpoint±σ |

閉ループ丸ごとは MCP に**無い**。回すのはあなた。

## 手順

### 0. データ品質を先に問う (**精密化の前に**)

`assess_data_quality(path, data_format=..., excluded_regions=[...])` を代表フレームに掛ける。

- **`is_subtracted=True` なら、系列を回す前に生データの有無をユーザーに確認する**。
  背景減算済データは esd=√I がノイズ底を過大重みし、**同一モデルで Rwp 26% → 生データ+背景精密化
  6.7%** になった (実測)。これは fit の問題ではなく**重み付けの問題**で、気づかずに回すと
  全フレームの Rwp が無意味に高いまま「収束しない」と誤診する。**本解析で最大のレバーだった**。
- `suggested_two_theta_limit` を手順 1 に使う。**寄生ピーク窓を `excluded_regions` で必ず渡す**
  (渡さないとセル由来の反射を信号終端と拾い、上限が押し出される — 実測 38.1°)。

### 1. 入力を組み立てる

各温度/時間点の観測ファイルを `FrameSpec` (`data_path`・`axis_value`=温度/時間・`data_format`
["XRDML"/"FXYE"/"GSAS"/"XYE"/"XY"]・`two_theta_limits`・`excluded_regions`) の列に、初期既知相を
`PhaseSpec` (CIF) にする。

- **`two_theta_limits` を必ず設定する**。ノイズ域は最小二乗を支配して遅く不正確になる
  (**30°→18° で 369s→8s** かつ収束改善)。
- **`excluded_regions`** に寄生ピーク (セル/装置由来) を入れる。
- **`instrument` spec を渡す** (下記)。省略すると**実験室 X 線 Bragg-Brentano・背景 6 項**の
  便宜既定が使われる。放射光データでは必ず明示すること。

```json
{"path": "kmnfe.instprm", "radiation": "xray_synchrotron", "geometry": "debye_scherrer",
 "background_coeffs": 18, "auto_freeze_minor_cells": 0.2}
```

| キー | 意味 |
|---|---|
| `path` / `paths` | 装置ファイル (系列共通 / フレーム毎に 1:1) |
| `radiation` | `xray_lab` / `xray_synchrotron` / `neutron_cw` / `neutron_tof` |
| `geometry` | `bragg_brentano` / `debye_scherrer` |
| `background_coeffs` | 背景項数 (既定 6)。実測で **18 が最良** の系があった (12/24 は劣る) |
| `auto_freeze_minor_cells` | **`phase_fractions` (= Scale) 基準の閾値 (float, 例 0.2)。bool ではない** — **Scale** が閾値未満の相のセルを自動凍結する。少数相のセルを解放すると計量相関で発散し分率が崩壊する (#80)。個別に凍結するなら `PhaseSpec.refine_cell=False` (手動が自動に優先)。⚠ **wt% ではない → 下記** |

> ### ⚠ 分率の閾値は**すべて Scale 基準** — wt% で考えて数字を決めない
>
> `auto_freeze_minor_cells` と `phase_id.frac_min` が比較する相分率は `phase_fractions`
> (**HAP Scale の Σ=1 正規化値**) であり、**`phase_weight_fractions` (wt%) ではない**。
> 出版値は wt% なので、あなたが系を wt% で考えているとき**閾値だけが別の座標系にある**。
>
> 実測 K₂Mn[Fe(CN)₆] (cubic 1103.4 / tetra 517.8 amu):
> `Scale {cubic 0.75, tetra 0.25}` は `wt% {cubic 86.5, tetra 13.5}` である。
> 「tetra は 13.5 wt% で少数相だから `auto_freeze_minor_cells=0.15`」と決めると、
> 実際に比較されるのは **Scale 0.25 ≥ 0.15** なので **tetra のセルは解放されたまま**になり、
> #80 の発散がそのまま起きる (凍結したいなら Scale 基準で 0.3 等)。
>
> **閾値を決める前に `result["frames"][i]["phase_fractions"]` (Scale) を実際に見ること。**
> 質量の重い相ほど Scale は wt% より小さく出る。

### 2. 新相自動同定を設定する

`phase_id = {"elements": [既知+想定元素], "frac_min": 0.02, "top_k": 1}`。
これで系列途中の変化点/Rwp ジャンプで Materials Project から新相を探し、**受理基準 (相分率有意 ∧
Rwp 改善 ∧ 妥当性) を満たせば自動追加**する。`elements` を空にすると相追加を行わない。
`frac_min` は**新相の Scale の下限** (上の警告と同じ basis。wt% ではない)。

### 3. `sequential_rietveld` を呼ぶ

`warm_start_fractions=True` を検討する (既定 False)。相分率が初期値に張り付いて動かない
フレームを、直前フレームの分率で warm-start して是正する (#82)。
フレーム別 Rwp/格子/相分率・変化点・`appearances` (自動追加相) を読む。

### 3′. **転移を含む operando は `anchored_sequential` を既定にする** (M10)

前方単一パス (`sequential_rietveld`) は **初期フレーム依存 + 転移域のセル汚染**で脆い。相が現れ
消える operando (充放電・脱水・相変態) では、以下を理由に `anchored_sequential` を既定にする:

- **相数は Rwp でなく bic で抑制される**。Rwp は自由パラメータ (相) を増やすほど単調に減るので、
  「全域を多相で解く」と偽相が必ず勝って全フレームに湧く (実測 K₂Mn[Fe(CN)₆] で per-frame 3 相固定は
  充電初期に偽 tetra を 20-30 wt% 生成した)。M10 は**相集合の違う前方/後方を区間総 bic で比較**し、
  相数の少ない側が有利になるよう罰する。結果は `crossovers[].total_bic` で読める。
- **アンカー**(信頼できるフレーム) の相集合で区間内を双方向 warm-start するので、`{mono}` アンカー
  近傍は mono のみで解かれ、**0 に張り付く相が存在しない** = esd が発散しない。

呼び方: `phases` は登場しうる全相の catalog、`anchor_table` は信頼フレーム→相集合の指定
(前回の綺麗な per-frame 結果の最小 Rwp フレーム等を選ぶ; 相同定が計量縮退で効かない系では手で選ぶ)。

```json
{"anchor_table": {"0": ["mono"], "124": ["cubic", "tetra"], "246": ["mono"]},
 "instrument": {"path": "kmnfe.instprm", "radiation": "xray_synchrotron",
                "geometry": "debye_scherrer", "background_coeffs": 18},
 "two_theta_limits": [2.4, 18.0]}
```

- **`instrument` と `two_theta_limits` は必ず渡す** (前方パスと同じ理由)。省略すると
  `anchored_sequential` は無音のラボ X 線既定に落とさず error dict を返す (operando は放射光/中性子が
  主戦場なので既定に落とすと系統的に誤る)。
- `anchor_table` を省略すると M9 単一アンカー fallback = 前方単一パス相当に縮退する。
- 出力の `anchors` (確定アンカー) と `crossovers` (区間選定・onset・total_bic) を読み、相の出現/消失
  フレームと相数の変化が物理的に妥当かを確認する。以降の手順 4〜8 は前方パスと同じ結果 dict に適用できる。

### 4. 不連続を修復する

`repair_frames(result, frames, phases, instrument={...}, two_theta_limits=[...])` で Rwp/相分率が
不連続なフレームを両隣から warm-start し直す。

- **`two_theta_limits` は系列と同じ値を必ず渡す**。省略すると修復試行だけが全域で走り、採用規則
  が**異なるデータ域の Rwp を比較**する (エラーは出ず、無効な比較のまま採用される)。
- **`phases` には系列で使われている全相を渡すこと** — `appearances` の自動追加相を
  含め忘れると相が黙って落ちる (ツールが検出してエラーにするが、意味を理解して渡すこと)。

**`target_frames` で対象を明示指定する** (手順 5 の張り付き/凍結フレームはこれでしか直せない):

```python
cps = check_phase_set(result)
suspect = sorted({f["frame"] for f in cps["seed_pinned_frames"]}
                 | {f["frame"] for f in cps["frozen_fraction_frames"]})
repair_frames(result, frames, phases,
              target_frames=suspect,          # ★省略すると張り付きには到達できない
              instrument={...}, two_theta_limits=[2.4, 18.0])
```

- 既定 (指定なし) の検出は Rwp/分率の**ジャンプ**しか見ない。**張り付き/凍結は「平坦」**なので
  どの閾値でも拾えず、`repairs=[]` = 「直すものは無い」が返る — 直前に「信用するな」と
  言われたフレームに対して、である。
- **疑わしいフレームは 1 回の呼び出しで全て渡す**。指定フレームは互いに warm-start 元から
  除外されるため、1 つずつ呼ぶと**両隣も張り付いた区間で欠陥を持つ隣から種を貰う**。

- `repairs` は Rwp 改善時のみ採用済 (自己検証可能な規則なので自律)。
- **`needs_model_revision` はモデルの欠陥**であり、近傍 warm-start では直らない
  (両隣も同じ欠陥を持つため)。手順 5 と `operando-diagnose` skill へ回す。

### 5. **相集合の完全性を疑う (必須・Rwp では代替できない)**

`check_phase_set(result)` を読む。

- **`is_complete=False`**: 「**除外した相の強度を、計量の近い別の相が肩代わりしていないか**」を疑う。
  和集合で再フィットして**相分率を比較**する。**Rwp が良くても信じない**。
- **`flagged=True` (相分率が非単調に振動)**: 物理的に妥当かを問う。単調な転移
  (A → B → C) が自然な系で分率が増減を繰り返すなら、**まず artifact を疑う**。
- **`seed_pinned=True` / `fractions_frozen=True`**: そのフレームの分率精密化が一度も動いていない。
  **Rwp は平凡なまま**なので他のどの指標にも出ない (実測: 247 フレーム中 9 フレームが Rwp
  8.4-8.5% のまま張り付き、うち 6 連続が転移ドーム頂点の直前だった)。2 つは**同じ欠陥の別の指紋**:

  - **`seed_pinned`**: 分率が等分 seed (2 相なら 0.500/0.500) に**厳密に一致** =
    **分率ウォームスタートが効いていない** (手順 3 の `warm_start_fractions` 参照)。
  - **`fractions_frozen`**: 分率が**直前フレームの値**に**厳密に一致** = ウォームスタート下で
    分率精密化が死んでいる。値が 1/n でないので `seed_pinned` には**出ない**。

  → **両方のフレーム番号を集めて 1 回で修復する** (手順 4 の `target_frames`)。
  **張り付いたままの分率は報告に使わない**。
- 各フレームの `residual_report.top_features` の **+ 残差**位置は未説明ピーク = 欠落相の候補
  (実データではここから d 比で cubic 相を独立同定できた)。`baseline_numerator_fraction` が
  大きければ「モデルでは下げられない」= データ側の問題 → **手順 0 に戻る**。

**これは飛ばしてよい手順ではない。この確認を欠いたことが本解析の唯一の重大な失敗だった。**

### 6. 必要なら手動で相を探す

自動追加が起きなかったが未指数ピークが残る変化点で、そのフレームのパターンを
`identify_and_add_phase` に渡し、返る PhaseSpec 候補を `initial_phases` に足して
`sequential_rietveld` を再実行する (相追加は**あなたの判断 + ユーザー承認**を挟む)。
DFT (MP) 由来の構造は格子が軸別にずれることがあり、異方セル補正が自動で入る (#20)。

### 7. パラメトリック解析 — **転移温度は重量分率基準で取る**

`parametric_fit(result, phase, component)` で格子 vs 温度の熱膨張係数、相分率シグモイドの
転移温度 (onset/midpoint±σ) を抽出し報告する。b/c 比等の擬変数で 2 次転移も追う。

**転移温度は `basis` で答えが変わる。既定 (`basis="weight"` = 重量分率) のまま使うこと。**
転移推定は「曲線が**絶対レベル** 0.50 (midpoint) / 0.10 (onset) を横切る軸値」を返すので、
y 軸が Scale か wt% かで交差位置そのものが動く。**`phase_fractions` (Scale) は転移の追跡に
使えない** — 「相対比較だから安全」は転移推定には当てはまらない (絶対レベルを使うため)。

> 実測 (K₂Mn[Fe(CN)₆] tetra 充電域): **同じ精密化**から Scale は「midpoint 9.515 h」を出し、
> wt% は「**転移なし**」を出した (Scale 0→0.656 は 0.50 を横切るが wt% は 0→0.472 で届かない)。
> Scale が midpoint と呼んだ点は実際には **34.0 wt%** であって「半分」ではない。

- 返り値の **`fraction_basis`** にどちらで出したかが必ず入る。**`"weight"` でなければ報告しない**。
- `basis="scale"` は**診断専用** (相対的な立ち上がりの目視)。その数値は出版・報告に使わない。
- `{"error_type": "FractionBasisUnavailableError"}` が返ったら、その系列には重量分率が無い
  (スタブ/非 GSAS 経路)。**Scale で代用して報告しない** — 実データを `sequential_rietveld` で
  精密化し直す。どうしても相対比較が要るなら `basis="scale"` を明示し、Scale 由来と明記する。

### 8. 報告 — **`phase_fractions` は wt% ではない**

全フレーム収束・転移特性・最良結果・相の出現/消失・転移温度・申し送り。
**Rwp と併せて、相集合の完全性をどう確認したかを必ず書く**。

**定量値は Scale ではなく重量分率で報告する**。`phase_fractions` は HAP Scale の正規化値であり、
**単位胞質量が相間で異なると重量分率と乖離する**。

> 実測 (K₂Mn[Fe(CN)₆]): cubic 1103.4 amu vs tetra 517.8 amu → **同じ fit で 65.6 Scale% が
> 実際には 47.2 wt%** (この点で 1.39 倍の誤り)。
>
> **乖離の大きさはフレーム毎に違う** (実測: fr112 1.62 / fr120 1.48 / fr124 1.41 / fr126 1.39 倍)。
> 大きさを決めるのは相の**単位胞質量比** (ここでは 2.13 倍) と**そのフレームの分率**である。
> ⚠ **単一の換算係数は存在しない — Scale に係数を掛けて wt% を作ってはならない**。
> 必ず `phase_weight_fractions` を読むこと。

| キー | 何か | 使いどころ |
|---|---|---|
| `phase_fractions` | **Scale** の正規化値 | **同一 basis 内の相対比較のみ** (新相の有意性・張り付き検出)。**転移の追跡には使えない** — 転移推定は絶対レベル 0.50/0.10 の交差なので basis で答えが変わる (手順 7) |
| `phase_weight_fractions` | **重量 (質量) 分率** (GSAS `calcMassFracs`) | **出版値・定量相分析はこちら**。転移温度もこちら基準 (`parametric_fit` の既定) |
| `phase_weight_fraction_esd` | 重量分率の esd | **出版には esd 必須** |
| `cell_esd` | 格子 esd (a,b,c,α,β,γ) | 同上 (esd 無しの格子は出版できない)。**3 状態を区別する → 下記** |

`sequential_rietveld` は `result["frames"][i]` に、`repair_frames` は `out["repairs"][j]` に
(**修復したフレーム毎**)、`auto_rietveld` は結果直下に、同じキー名で返す。
**修復したフレームは `repairs[]` の値で報告する** — `result["frames"][i]` は修復前のままである
(`repair_frames` は非破壊で元の系列を書き換えない)。

空 dict = その精密化から値が得られなかった (共分散なし/未収束)。**esd=0 の意味ではない**。

#### `cell_esd` の 3 状態 — `0.0` と `null` は**意味が違う**

```json
"cell_esd": {"mono":  [0.0133, 0.0177, 0.0109, 0.0, 0.1300, 0.0],
             "cubic": [null, null, null, null, null, null]}
```

| 値 | 意味 | どう報告するか |
|---|---|---|
| `>0` | 解放して精密化した項の su | `a = 10.0316(133)` |
| `0.0` | **対称拘束で厳密に固定** (monoclinic の α/γ = 90° 等) | 90° は定義値。esd を付けない |
| `null` | **そのフレームで格子を解放していない** — `refine_cell=False` / `auto_freeze_minor_cells` による凍結・セル段の revert・未精密化 | 「参照値に固定 (not refined)」と書く。**esd を付けてはならない** (値は入力 CIF 由来であってこのデータから決まっていない) |
| 相ごと欠落 | 抽出できなかった (共分散構造の異常) | 出版せず原因を調べる |

⚠ **「0 なら固定」と推論しないこと** — 解放した相の中にも真の `0.0` (対称拘束) がある。
凍結は `null` でしか判らない。`auto_freeze_minor_cells` は**あなたが相を名指ししなくても**
分率が閾値未満の相を凍結するので、**どの相が凍結されたかは `cell_esd` の `null` で読む**
(`auto_rietveld` の `stages[].note` の `auto_frozen_cells=` にも出る)。

## 禁止事項

- **Rwp が良いことを根拠に相集合を正しいと結論しない**。実データの失敗は Rwp 8% で起きた。
- **`phase_fractions` (Scale) を wt% として報告しない** (実測 1.39-1.62 倍誤る。**倍率はフレーム
  毎に違うので換算係数で直せない**)。出版値は
  `phase_weight_fractions` ± `phase_weight_fraction_esd`。
- **閾値を「期待した数字」に合わせて調整しない**。②/① の助言器は提案のみ、実測値を報告する。
- **系統ブロックを近傍 warm-start で「直そう」としない** (両隣も同欠陥 = 無効)。
- **「対策を入れたら直った」で因果を確定させない**。**単一変数の統制実験**で真因を特定する
  (実例: Rwp 66% をプロファイル初期値のせいと誤診 → 統制実験で真因は CIF 空間群設定バグと判明。
  手で入れたプロファイル初期値はむしろ悪化させていた)。

## 権限境界 (M8 §4.5 継承)

| 判断 | 決定論コア (自律) | ③ (あなた/ユーザー) |
|---|---|---|
| ウォームスタート・背景/母数解放・段階解放 | ✅ 自律 (Rwp∧validity で自己検証) | 監督 |
| 変化点検出・相同定候補の提示 | ✅ 提示 | — |
| 不連続フレームの近傍 warm-start 修復 | ✅ 自律 (Rwp 改善時のみ採用・ledger 追記) | `needs_model_revision` を判断 |
| **新相の採否** (相追加) | 🟡 受理基準で自律採用も可 (frac∧Rwp∧validity) | ✅ 化学妥当性を確認・疑わしきはユーザー承認 |
| **相集合の完全性** (相の**欠落**) | ❌ **原理的に不可** | ✅ **あなたが `check_phase_set` で疑う** |
| 構造改訂・空間群・データリミット精密化 | ❌ | ✅ 判断・実行 |

**なぜ受理基準で自動採用が許されるか**: 相追加は「未指数ピークを説明し ∧ 相分率が有意 ∧ 全体 Rwp を
改善し ∧ 妥当性を壊さない」ときのみ受理し、外れれば可逆に棄却される (提案≠適用)。ただし化学的に
不自然な相 (元素系外・準安定すぎ) は ③ が退けるべき — 受理基準は残差の説明力しか見ないため。

**なぜ相集合の完全性は受理基準で担保できないか**: 受理基準は「**追加された相が残差を説明するか**」
しか見ない。本解析の失敗は相が追加された誤りではなく**相が欠けている誤り**であり、欠落相は
**受理基準の視野の外**にある。しかも欠けた相の強度は計量の近い別相が肩代わりして Rwp を保つため、
**統計量では検出できない**。**③ が疑う以外に検出手段が無い**。

## 前提

- GSAS-II (GSASIIscriptable) が導入されていること。未導入なら該当ツールが error を返す。
- 新相自動同定は Materials Project キーを使う。**`.env` に `MATERIALS_PROJECT_API` があれば
  自動読込される** (#51)。環境変数でも可。どちらも無い場合のみ `identify_and_add_phase` が
  error を返すので、CIF を直接 `initial_phases` に足す運用に切り替える。
