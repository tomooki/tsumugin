# 本気の XRD / ND / Joint Rietveld 解析フロー(一般化)

装置・試料由来の**初期パラメータ設定**と**パラメータ解放順**を、放射源・ジオメトリに依らず
一般化して整理する。今回の XND (NaCuHCF·nD₂O) 解析で確立した教訓と、M7 (T1–T4) / M9 (CaTeO3)
の実データ検証、および GSAS-II の全パラメータを踏まえる。実装は `tsumugin.autorietveld`
(`recipe.build_recipe` + `engine.run_auto_rietveld`) と `tsumugin.interop`。

## 0. 核心原理と 3 層モデル

### 核心原理: 「可能性があればトライ → ダメなら revert」

自動解析のエンジンはこの一点に尽きる。**特定の結論を焼き込まない**。あるパラメータ解放に
物理的な可能性があれば試し、Rwp が悪化すればその段階ごと revert して前段を保持する。したがって
本フローは「何が効くか」の結論表ではなく、「**どういう条件で何を別々に試し、どう観察して
採否を決めるか**」の手順で書く。個別材料で得た「A が効き B は効かない」は普遍則ではなく、
**試す順序を偏らせる事前分布(第2層)**に過ぎない — 検証は常に try→revert が行う。

> ⚠ アンチパターン(過度な一般化): 「非対称残差 = alpha であって Zero でない」。
> 正しい汎用形: 「非対称残差 → 非対称パラメータ(alpha/beta)と シフト(Zero)を**別々に解放して
> 観察**し、改善する方を採用・他を revert」。「TOF では alpha が効きやすい」は第2層のヒント。

### 3 層モデル

| 層 | 意味 | 自律性 | 実装の所在 |
|---|---|---|---|
| **第1層 Default(汎用・普遍フロー)** | 材料非依存で常に走る段階解放列。全段 try→revert。 | 完全自律 | `build_recipe` S0–Sn / engine 既定 + revert ガード |
| **第2層 Conditional(条件分岐・自動トライ)** | (a)装置/試料属性による決定論分岐 + (b)**診断トリガの自動トライ**(条件成立→候補を別々に解放→観察→採否)。経験則(priors)は**試す順序のヒント**としてここで使う(非拘束)。 | 完全自律 | `build_recipe` アダプタ / opt-in フラグ / `interop` / `refine_loop` |
| **第3層 Judgment(Agent/人間判断)** | 真に判断を要するもの: モデル選択(BIC)、停止基準、境界的な物理/化学妥当性の解釈、新相採否。 | 要判断 | `evidence`/`nested`/`chem` / 人間 |

**不変則**: 全ての適用は revert ガード下(悪化なら自動棄却, P2 非破壊 / NFR-102 再現性)。
最終判定は必ず物理妥当性ゲートを通す。第2層の自動トライも「試す→観察→revert」なので**人手不要**
— 第3層は本当に判断が要る所だけに絞る。

---

## 1. 装置・試料由来の初期パラメータ設定(解放前に「与える」もの)

解放順とは独立。精密化開始前に、**装置校正・試料情報から確定値として設定**する。ここを誤ると
以降の全段階が破綻する(例: TOF difC のズレ、放射光 λ の取り違え、データリミット未設定)。

### 1.1 装置パラメータ (Instrument Parameters)

| パラメータ | 放射源 | 由来・入手元 | 層 | 備考 / 教訓 |
|---|---|---|---|---|
| **λ (波長)** | X線 CW | 標準試料較正 (CeO₂/Si/LaB6) | Default | ⚠ **較正ファイルの見かけ値と実波長を混同しない** (SR_CeO2 の 0.5 は不使用、実 λ=0.79958)。ラボは Kα1/Kα2。 |
| Kα1/Kα2 比 | X線ラボ | 管球 (Cu/Mo/Co) | Conditional | **Kα2 除去データは Kα1 単色 instprm** (Kα2 phantom が最大の系統残差, CaTeO3)。 |
| **difC / difA / difB** | ND TOF | 標準試料較正 (Si/NAC/CeO₂) | Default | ベンダー校正ファイルから**直写** (`interop`: difC=c1/difA=c2/Zero=c0)。TOF=difC·d+difA·d²+difB/d+Zero。 |
| **Zero** | 全 | 較正 | Default (値) / Judgment (解放) | 位置ゼロ点。**cell/difC と縮退しやすい** — 単独解放は効かないことが多い (ND で −2.65→−20 動くが wRp 不変)。 |
| **U, V, W** | CW (X線/中性子) | 標準試料 (Caglioti) | Default (値=instprm) | Gaussian 幅の 2θ 依存。初期は装置 instprm。 |
| **X, Y** | X線 CW | 標準試料 or 0 初期 | Default (値) / Conditional (解放) | **Lorentzian 幅**。実験室/放射光は Lorentzian 支配 → 別段階で必ず解放 (CaTeO3 43→13%)。 |
| SH/L | X線 CW | ジオメトリ (軸発散) | Judgment | 低角非対称。分割擬 Voigt 相当の経験形状。常には効かない → 別段階 revert ガード。 |
| **alpha, beta-0/1** | ND TOF | モデレータ/較正 | Default (値=instprm) / Judgment (解放) | TOF ピーク**非対称** (立上り/減衰の指数)。**非対称残差の原因はここ** (Zero でない)。alpha 較正で僅少改善。 |
| **sig-0/1/2** | ND TOF | 較正 | Default (値) / Judgment (解放) | TOF Gaussian 幅。sig-1/sig-2 較正は安定に効く。 |
| Polarization | X線 | 放射光=偏光度 / ラボ=単色器角 | Conditional | 前方計算の Lorentz-偏光因子。 |
| fltPath, 2θ(bank) | ND TOF | バンク角 | Default | フライトパス長。バンク角から逆算 (`interop`)。 |

### 1.2 試料パラメータ (Sample Parameters)

| パラメータ | 由来・入手元 | 層 | 備考 / 教訓 |
|---|---|---|---|
| **Geometry (BB/DS)** | 装置構成 | Conditional | 反射(Bragg-Brentano)→`Shift`、透過/毛細管(Debye-Scherrer)→`DisplaceX/Y`。変位種別を自動選択。 |
| **Absorption (μR)** | 試料組成・密度・**キャピラリ径** | Conditional (自動トライ) | 物理計算可 (`absorption.neutron`: μ=Σnσ/V×充填率、X線 μ/ρ)。TOF は λ(=TOF) 依存。**自由精密化 / 物理値固定 / 0 を試し**、妥当性(μ≥0)+Rwp で採用(§6)。経験則: 弱吸収試料(D₂O 等)は自由精密化が負に振れやすい。 |
| Sample displacement | — | Default (値=0) | 初期 0、S1 で解放。 |
| **Temperature** | 測定条件 | Conditional | 複数ヒストグラム間の温度差 → per-hist 静水圧歪み Dij 判定。 |
| **Histogram weight (wtFactor)** | — | Judgment | joint の相対重み。既定 1.0。XRD 支配の joint で ND を上げ重み。 |

### 1.3 データ範囲・背景初期化

| 項目 | 層 | 教訓 |
|---|---|---|
| **two_theta_limits / TOF レンジ** | Judgment (必須確認) | **ノイズ領域を除外**。データリミット未設定は最小二乗が平坦化し非収束 (T4 の主因 51%高止まり)。 |
| Background type | Default (Chebyshev) | 11BM 等は項数を要す。 |
| **Background coeffs** | Conditional | X線 6→24–30。**ND(TOF) は正規化スペクトルで背景支配的 → 過剰項回避** (NaCuHCF: ND 18 項、>18 は過剰フィット wiggle)。per-histogram で別数 (`by_index`)。 |

---

## 2. パラメータ解放順(段階解放の普遍列)

**大原則**: 強い相関を持つパラメータを同時に解放しない。強度スケール系 → 位置系 → 幅系 →
占有/変位系 → 微細形状系、の順で相関を切りながら開く。各段は revert ガード付き。

```
S0  scale + background                      ← 全解析の起点
S1  cell + displacement (+ Dij if 温度差)   ← 格子と試料変位
     └[多相] phase_fractions を S1 の前に単独先行 (和=1)
S2  profile (U,V,W Gaussian) [+ size/strain]
     ├[X線]  + Lorentzian (X,Y,Zero)  ← 別段階 revert ガード
     ├[X線]  + asymmetry (SH/L)       ← 別段階 revert ガード
     └[TOF]  + tof_profile (sig/alpha/beta) ← opt-in 較正
S3  occupancy (混合/単独, 制約下)
S4  coords (一般位置のみ, 特殊位置除外)
S5  uiso (free_uiso_labels で限定)
S6  size/strain (多相は最後)
opt Absorption / Preferred orientation      ← Judgment, revert ガード
Sf  全パラメータ同時 (cell+coords+uiso+occ) ← 収束の締め
```

### 2.1 順序を切り替える分岐規則 (実測で確立)

| 条件 | 順序規則 | 根拠 |
|---|---|---|
| **混合占有あり** (中性子 garnet 型) | 占有率 → Uiso(等価) → プロファイル → 座標 | 占有率を先に固めないと Uiso と縮退 (T2) |
| **混合占有なし** (ラボX線 型) | プロファイル → 座標 → Uiso | 標準手順 (T1) |
| **多相** (T4 型) | 相分率を単独先行 → 格子 → 座標 → Uiso → **size/歪みを最後** | 相分率を格子と同時解放は噛まない。size を座標前に開くと座標段が悪化 revert |
| **中性子** | 占有率を Uiso より**先**に解放 | 散乱長コントラストが Na/O 分割を分離 (XND) |
| **温度差** | per-hist 静水圧歪み Dij | 格子共有のまま各ヒストに実効格子ずれ (M9) |
| **size/strain** | 低分解能 CW 中性子は joint 時**除外**、TOF/X線は張る | 低分解能 CW は幅が器械支配で試料情報乏しく希釈 (T3: 8.4→6.7%) |

---

## 3. XRD 単独フロー(本気)

```
[初期設定] λ(較正確認) / Kα1 単色化 / Geometry→変位種別 / データリミット / 背景型
[Default]  S0 scale+bg → S1 cell+displacement → S2 profile(U,V,W)
[Conditional] +Lorentzian(X,Y,Zero) 別段階  → coords → uiso
[Judgment] +asymmetry(SH/L) / +preferred orientation / +absorption(μR物理値)
           / 背景項数調整 / size-strain(結晶子サイズ・歪み)
[締め]     全パラメータ同時 → 物理妥当性ゲート
```
- **要点**: X線は Lorentzian が支配的。U,V,W だけで高止まりしたら X,Y を疑う。
  系統的な obs>calc ピーク強度は preferred orientation。低角非対称は SH/L。

## 4. ND 単独フロー(本気) — CW と TOF で分岐

### 4.1 CW 中性子
```
[初期設定] λ / U,V,W(較正) / 背景 / Geometry
[Default]  S0 → S1 cell+displacement → occupancy(コントラスト先行) → uiso → profile → coords
[Judgment] size/strain(単一 CW なら張る) / 吸収 / 背景
```
### 4.2 TOF 中性子 (J-PARC iMATERIA 等)
```
[初期設定] difC/difA/Zero(較正直写) / alpha,beta,sig(instprm) / バンク選択
           / **TOF レンジ制限(必須)** / **背景項数は控えめ**(正規化スペクトル)
           / **可変ビン幅の強度歪み補正**(GSAS は強度をビン幅で除算 → 前処理で×step)
[Default]  S0 → S1 cell → occupancy → uiso → coords
[Judgment] tof_profile 較正(sig-1/sig-2 → alpha 非対称) / size/mustrain(高分解能は張る)
           / 吸収(λ依存) / 背景項数
```
- **要点**: TOF profile (sig/alpha/beta) は既定で**解放しない**(較正依存)。非対称残差が出たら
  **非対称(alpha/beta)とシフト(Zero)を別々に解放して観察**し改善する方を採る(§6)。size/mustrain も
  試して悪化/発散なら revert。(経験則: TOF は alpha が効き Zero は cell と縮退しがち — 非拘束)

## 5. Joint (X線 + 中性子) フロー(本気)

```
[初期設定] 各ヒストを個別に 1.1/1.2/1.3 で設定 → HistogramSpec ペア (interop.prepare_histograms)
           / wtFactor で相対重み / 格子は全相で共有・温度差は Dij
[Default]  S0 → S1(格子共有+各変位) → profile(各放射源の適切キー; TOF はスキップ)
[Conditional] X線に Lorentzian/asymmetry / CW中性子は size/strain 除外 / 温度差 Dij
[Judgment] 占有率(**中性子コントラストで分割**先行) → uiso(限定) → coords
           / preferred orientation / 吸収(各ヒスト物理値) / tof_profile 較正
           / **モデル選択(BIC + 物理妥当性)** ← joint の主目的
[締め]     全パラメータ同時 → 妥当性ゲート → BIC でモデル序列化
```
- **要点**: joint の価値は**単独では縮退する自由度を分離**すること
  (中性子散乱長コントラストで Na/O 占有分割、D 位置)。相対重み wtFactor で
  情報の少ない側が埋もれないようにする。モデル競合は Rwp でなく **BIC**(相数増で
  Rwp は単調減少するため) + 物理妥当性で裁定。

---

## 6. 第2層: 診断トリガの自動トライ (try → observe → revert)

精密化中のメトリクス異常に対し、**候補パラメータを別々に解放して観察し、改善する方を採用・
他は revert** する自動手順。結論を焼き込まず「何を切り分けるか」を規定する(`refine_loop`
規則化候補)。「経験則ヒント」列は**試す順序を偏らせるだけの非拘束の事前分布**であり、
採否は必ず try→revert が決める。

| 診断シグナル | 別々に解放して観察する候補 | 採用/revert 基準 | 経験則ヒント(非拘束・第2層 prior) |
|---|---|---|---|
| ピーク位置が系統的にズレ / 非対称残差 | ① シフト(Zero/difA) ② 非対称(SH/L; TOF は alpha/beta) を**別段階で個別に** | 各段 Rwp 改善なら保持、悪化なら段ごと revert | TOF は alpha が効き Zero は cell と縮退しがち(要検証) |
| 系統的 obs>calc のピーク強度 | preferred orientation (SH order 2→4→6, March-Dollase) | 改善が頭打ちの次数で止める | 針状/層状晶癖・毛細管充填で出やすい |
| ピーク幅が合わない | ① Gaussian U,V,W ② Lorentzian X,Y ③ size/mustrain を段階的に | 各段 revert ガード。低分解能ヒストは決まりにくい | 実験室/放射光X線は Lorentzian 支配。低分解能 CW 中性子は size/strain が埋もれる |
| 背景プロファイルが過剰に wiggly | 背景項数を増減 (per-hist) | wiggle 過剰/過適合なら項数を戻す | 正規化 TOF スペクトルは背景支配的で少項でよい |
| Rwp 高止まり + データ端がノイズ | データ範囲を制限 (two_theta_limits / TOF レンジ) | ノイズ域除外で改善 | データリミット未設定は最小二乗を平坦化(要確認) |
| 占有率が >1 / <0 に発散 | 制約(和=1)/等値/対象サイト限定を試す。解けなければモデル選択へ | 妥当性ゲート(∈[0,1])で判定 | 共有サイトの GSAS 境界は和=1 制約と両立しにくい→第3層でモデル選択 |
| Uiso が発散/負 | 解放対象を重原子/可動イオン/水に限定 (free_uiso_labels) | 妥当性(Uiso 範囲)で判定 | 軽元素 framework・占有率0のゴースト原子で発散しやすい |
| 吸収の寄与が不明 | ① 自由精密化 ② 物理値固定(組成/径) ③ 0 を試す | 妥当性(μ≥0)+Rwp で採用 | 弱吸収試料は自由精密化が負に振れやすい |
| 格子が 0 近傍へ崩壊 | — | 格子崩壊ガードで即 revert | 過剰同時解放が主因 |

## 6b. 第3層: 真に判断を要する点 (Agent/人間)

try→revert で自動裁定**できない**もの。ここだけ第3層に残す。

| 判断 | 手法 |
|---|---|
| 僅差のモデル競合(相の有無・水の要否・同位体配置) | **BIC + 物理妥当性** (相数増で Rwp は単調減少するため Rwp 単独では不可)。僅差は nested 再裁定 |
| 停止基準(どこで追い込みを打ち切るか) | 全パラメータ解放で頭打ち + 妥当性維持 → 収束と判断 |
| 境界的な物理/化学妥当性の解釈 | `validity`(結合距離/配位数) + `chem`(化学的妥当性の事前分布, 降格のみ) |
| 新相の採否(逐次/operando) | 相分率有意 ∧ Rwp 改善 ∧ 妥当性維持 → 採用、外れれば可逆棄却 |

---

## 7. 実装マップ (宣言的フラグ ↔ GSAS-II 呼び出し ↔ 層)

`engine._apply_stage` が解釈する正準フラグ語彙。レシピはこの宣言的辞書列。

| フラグ | GSAS-II 呼び出し | 層 | 備考 |
|---|---|---|---|
| `background {coeffs, by_index, type}` | `hist.set_refinements({"Background":...})` | Default | per-hist 項数 |
| `scale` | (既定精密化, 単相 no-op) | Default | |
| `cell` | `ph.set_refinements({"Cell":True})` | Default | 全相共有 |
| `displacement {idx:[keys]}` | `hist.set_refinements({"Sample Parameters":...})` | Conditional | ジオメトリ別 |
| `profile ["U","V","W"]` | `hist.set_refinements({"Instrument Parameters":...})` | Default | TOF はスキップ |
| `profile_lorentzian` | `{"Instrument Parameters":["X","Y","Zero"]}` | Conditional | X線のみ, revert ガード |
| `profile_asymmetry` | `{"Instrument Parameters":["SH/L"]}` | Judgment | X線のみ, revert ガード |
| `tof_profile [keys]/True` | `{"Instrument Parameters": sig/alpha/beta}` | Judgment | TOFのみ, opt-in |
| `absorption` | `{"Sample Parameters":["Absorption"]}` | Judgment | opt-in, revert ガード |
| `preferred_orientation N` | `ph.HAPvalue("Pref.Ori.",N)` + HAP refine | Judgment | SH/March-Dollase |
| `size_strain` | `ph.set_HAP_refinements({"Size","Mustrain"})` | Conditional | CW中性子は joint 除外 |
| `hydrostatic_strain` | `ph.set_HAP_refinements({"HStrain":True})` | Conditional | 温度差 Dij |
| `phase_fraction_sum` | `ph.set_HAP_refinements({"Scale":True})` | Conditional | 多相和=1 |
| `coords` | per-atom `dAx/dAy/dAz` (一般位置のみ) | Default | 特殊位置除外 |
| `uiso` | per-atom `AUiso` (free_uiso_labels 限定) | Default | |
| `occupancy` | per-atom `Afrac` (制約下) | Conditional | 混合/単独/等値/和 |

**制約 (`_setup_constraints`)**: 混合占有=和1 `EqnConstr` + Uiso 等価 `EquivConstr` + 座標等値、
占有率等値 `EquivConstr` (Fe=C=N)、占有率和 `EqnConstr` (D+H=O)、位置等値。

---

## 8. ガードレール(不変条件・違反禁止)

- **revert ガード**: 各段で Rwp 悪化なら段階ごと破棄し前段を保持 (opt-in 段は特に)。
- **格子崩壊ガード**: 0 近傍セルは revert。
- **per-atom 累積フラグ**: GSAS-II は原子フラグを「置換」するため毎段で全原子マップを再設定。
- **物理妥当性ゲート** (`validity.check_validity`): 占有率∈[0,1]・Uiso 範囲・格子・
  (pymatgen 有れば)結合距離/配位数。最終判定に必ず通す。
- **P2/NFR-102**: 全状態変更は追記+revert、乱数種固定でビット同一、Ycalc 使用。
- **モデル選択は BIC + 妥当性**: Rwp 単独で相数を増やさない (過剰フィット防止)。

---

## 付録: 本フローの検証履歴

| 検証 | 放射源 | 確立した教訓 |
|---|---|---|
| T1 fluoroapatite | ラボX線 単相 | 標準順序 (profile→coords→uiso)、Rwp 9.83% |
| T2 garnet | CW中性子 混合占有 | 占有率先行、和=1+Uiso等価、Rwp 4.33% |
| T3 PbSO4 | X線+CW中性子 joint | CW中性子は size/strain 除外、Rwp 6.66% |
| T4 NAC+CaF2 | TOF+放射光 多相 | データリミット必須、相分率先行、size 最後、Rwp ~12.8% |
| M9 CaTeO3 | ラボX線 逐次 | Kα1 単色、Lorentzian 別段階、背景 24 項 |
| **XND NaCuHCF·nD₂O** | **放射光+TOF joint** | **可変ビン幅補正、中性子コントラストで占有分割、非対称/シフトを個別トライ(alpha 採用)、吸収を自由/物理/0 比較(最小が最良)、BIC でモデル選択** |
