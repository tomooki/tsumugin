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
| `sequential_rietveld` | 計器+アクチュエータ | frames + initial_phases spec (JSON) → フレーム別 Rwp/格子/相分率/残差レポート/**出版値 (重量分率±esd・格子 esd)**・変化点・自動出現相 |
| `check_phase_set` | 計器 (相集合) | 系列結果 → 相集合の完全性 + 相分率の非単調 (zigzag) フラグ + seed 張り付き + 分率凍結 |
| `repair_frames` | 計器+アクチュエータ | 系列結果 + frames + phases (+ `target_frames` で対象明示) → 不連続/張り付きフレームの近傍 warm-start 修復 |
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
| `auto_freeze_minor_cells` | **相分率の閾値 (float, 例 0.2)。bool ではない** — 分率が閾値未満の相のセルを自動凍結する。少数相のセルを解放すると計量相関で発散し分率が崩壊する (#80)。個別に凍結するなら `PhaseSpec.refine_cell=False` (手動が自動に優先) |

### 2. 新相自動同定を設定する

`phase_id = {"elements": [既知+想定元素], "frac_min": 0.02, "top_k": 1}`。
これで系列途中の変化点/Rwp ジャンプで Materials Project から新相を探し、**受理基準 (相分率有意 ∧
Rwp 改善 ∧ 妥当性) を満たせば自動追加**する。`elements` を空にすると相追加を行わない。

### 3. `sequential_rietveld` を呼ぶ

`warm_start_fractions=True` を検討する (既定 False)。相分率が初期値に張り付いて動かない
フレームを、直前フレームの分率で warm-start して是正する (#82)。
フレーム別 Rwp/格子/相分率・変化点・`appearances` (自動追加相) を読む。

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

### 7. パラメトリック解析

`parametric_fit(result, phase, component)` で格子 vs 温度の熱膨張係数、相分率シグモイドの
転移温度 (onset/midpoint±σ) を抽出し報告する。b/c 比等の擬変数で 2 次転移も追う。

### 8. 報告 — **`phase_fractions` は wt% ではない**

全フレーム収束・転移特性・最良結果・相の出現/消失・転移温度・申し送り。
**Rwp と併せて、相集合の完全性をどう確認したかを必ず書く**。

**定量値は Scale ではなく重量分率で報告する**。`phase_fractions` は HAP Scale の正規化値であり、
**単位胞質量が相間で異なると重量分率と乖離する**。

> 実測 (K₂Mn[Fe(CN)₆]): cubic 1103.4 amu vs tetra 517.8 amu → **同じ fit で 65.6 Scale% が
> 実際には 47.2 wt%。2.1x の差**である。

| キー | 何か | 使いどころ |
|---|---|---|
| `phase_fractions` | **Scale** の正規化値 | 相対比較のみ (新相の有意性・転移の追跡) |
| `phase_weight_fractions` | **重量 (質量) 分率** (GSAS `calcMassFracs`) | **出版値・定量相分析はこちら** |
| `phase_weight_fraction_esd` | 重量分率の esd | **出版には esd 必須** |
| `cell_esd` | 格子 esd (a,b,c,α,β,γ) | 同上 (esd 無しの格子は出版できない) |

空 dict = その精密化から値が得られなかった (共分散なし/未収束)。**esd=0 の意味ではない**。

## 禁止事項

- **Rwp が良いことを根拠に相集合を正しいと結論しない**。実データの失敗は Rwp 8% で起きた。
- **`phase_fractions` (Scale) を wt% として報告しない** (実測 2.1x 誤る)。出版値は
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
