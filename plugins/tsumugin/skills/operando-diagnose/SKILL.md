---
name: operando-diagnose
description: operando/in situ 系列 Rietveld の結果を疑い、モデルの誤り (欠落相・対称性・データ品質) を見つけて改訂する。MCP ツール (assess_data_quality / check_phase_set / repair_frames / sequential_rietveld の residual_report) を駆動し、Rwp が良好なまま物理的に誤っている描像を検出する。insitu skill が「進める」のに対し本 skill は「疑う」。相集合の変更・対称性変更・構造改訂はユーザー承認を挟む。
---

# tsumugin: operando 系列の診断・モデル改訂 (③ 判断層)

あなた (Claude) が**判断者 ③** として、**得られた系列結果を疑う**。
`insitu` skill が「回して新相を足す」のに対し、本 skill は
**「モデルの誤りを見つけて改訂する」**。両者は併用し、`insitu` の結果を本 skill に渡すのが標準動線。

設計: `docs/design/operando-diagnosis/architecture.md`。

## なぜこの skill があるか — **Rwp では原理的に検出できない誤りが実在した**

実データ (K₂Mn[Fe(CN)₆] 放射光電気化学 operando, 247 フレーム) で最も重大だった失敗は、
**フィット統計がすべて良好なまま物理的に誤った描像**を得たことだった:

- 充電域を cubic+tetra の 2 相に限定した (「放電相 mono は充電時に存在しない」という**一見妥当な**判断)。
- 転移端に残る monoclinic の強度を、**計量の近い tetragonal が肩代わり**した。
- 結果:「tetragonal が増減を繰り返す」非物理な描像 (`0.42→0.17→0.70→0.04→0.63`)。
- **Rwp は終始 ~8% と良好**。GOF も validity も警告を出さない。
- 全 3 相を入れ直すと単一ドーム (`0→0.58→0`) に収束 = 正解。
- **発見者は人間の物理的直感**だった (「一度増えてから減るのは妥当か?」)。

計量が近い相 (本系は mono/cubic/tetra が全て cubic 派生) は**互いの強度を吸収し合う**。
**だから ③ が要る**。この失敗を再現可能な形で埋め込むのが本 skill の目的である。

## 使う MCP ツール (②)

| ツール | 役割 | 出力 |
|---|---|---|
| `assess_data_quality` | データ品質 | `is_subtracted`/`confidence`/`reasons`/`suggested_two_theta_limit` |
| `sequential_rietveld` | 系列実行 | フレーム別 Rwp/格子/相分率 + **`residual_report`** + **出版値** (`phase_weight_fractions`±`phase_weight_fraction_esd`/`cell_esd`) をフレーム毎に同梱 |
| `check_phase_set` | 相集合 | `is_complete`/`union`/`frames_with_missing` + 相ごとの `turning_points`/`flagged` + `seed_pinned`/`seed_pinned_frames` + `fractions_frozen`/`frozen_fraction_frames` |
| `repair_frames` | 不連続の修復 | `repairs` (採用のみ; **修復後の出版値** `phase_weight_fractions`±`phase_weight_fraction_esd`/`cell_esd` を修復フレーム毎に同梱)/`needs_model_revision`/`ledger_entries`。`target_frames` で対象を明示指定 (張り付き/凍結フレームはこれでしか到達できない) |
| `identify_and_add_phase` | 相同定 | 物質化した PhaseSpec 候補 (CIF パス) + 根拠 |
| `auto_rietveld` | 単一フレーム再フィット | `residual_report` + 出版値 (重量分率 ± esd・`cell_esd`) 同梱 |

**②は判断しない・返すだけ**。判断はあなたがする。

## 手順

### 1. データ品質を先に問う (J1) — **精密化を始める前に**

`assess_data_quality(path, data_format=..., excluded_regions=[...])`。

**`is_subtracted=True` なら、系列を回す前に生データの有無をユーザーに確認する**。
背景減算済 + esd=√I はノイズ底を過大重みし、**同一モデルで Rwp 26% → 生+背景精密化 6.7%**
になった。**fit ではなく重み付けの問題**である。ここが最大のレバーで、気づかず回すと
全フレームの Rwp が無意味に高いまま「収束しない」と延々誤診する。

`suggested_two_theta_limit` を得る際は**寄生ピーク窓を `excluded_regions` で必ず渡す**
(渡さないとセル由来の反射を信号終端と拾い上限が押し出される — 実測 38.1°)。

### 2. 系列を回す

`sequential_rietveld` (`insitu` skill と同じ)。**`instrument` spec を明示する**
(省略すると**実験室 X 線 Bragg-Brentano・背景 6 項**の便宜既定になり、放射光データは扱えない)。

```python
sequential_rietveld(
    frames=[{"data_path": f, "axis_value": i, "data_format": "XYE",
             "two_theta_limits": [2.4, 18.0],
             "excluded_regions": [[6.6, 7.6]]} for i, f in enumerate(files)],
    initial_phases=[{"structure_path": "mono.cif", "phase_name": "mono", "refine_cell": False}, ...],
    instrument={"path": "kmnfe.instprm", "radiation": "xray_synchrotron",
                "geometry": "debye_scherrer", "background_coeffs": 18,
                "auto_freeze_minor_cells": 0.2},
    warm_start_fractions=True, two_theta_limits=[2.4, 18.0],
)
```

| `instrument` キー | 意味 |
|---|---|
| `path` / `paths` | 装置ファイル (系列共通 / フレーム毎に 1:1) |
| `radiation` | `xray_lab` / `xray_synchrotron` / `neutron_cw` / `neutron_tof` |
| `geometry` | `bragg_brentano` / `debye_scherrer` |
| `background_coeffs` | 背景項数 (既定 6)。実測で **18 が最良** の系があった (26%→6.7% の一部) |
| `auto_freeze_minor_cells` | **相分率の閾値 (float, 例 0.2)。bool ではない** — 分率が閾値未満の相のセルを自動凍結する (解放すると計量相関で発散・分率崩壊)。`True` は `float(True)==1.0` = 全相凍結になるため ② が拒否する。**`instrument` の中に置く** (tool の kwarg ではない) |

> `refine_cell=False` は **`PhaseSpec` のキー** (相ごとの手動凍結。手動が自動に優先)。
> `auto_freeze_minor_cells` とは階層が違うので混同しないこと。

### 3. 疑う — **ここからが本 skill の主眼**

#### J5 相集合の完全性 ★最重要

`check_phase_set(result)`:

- **`is_complete=False`** → 「**除外した相の強度を、計量の近い別の相が肩代わりしていないか**」
  を疑う。**和集合で再フィットし、相分率を比較する**。**Rwp が良くても信じない**。
- **`flagged=True` (分率が非単調に振動)** → **J7**: 物理的に妥当かを問う。
  単調な転移 (A→B→C) が自然な系で分率が増減を繰り返すなら、**まず artifact を疑う**。
  実データではこれが唯一の手がかりだった。
- **分率が動かなかったフレーム (2 つの指紋)** → **そのフレームの分率を報告に使わない**。
  どちらも「分率精密化がそのフレームで一度も動いていない」ことを意味し、**Rwp は平凡なまま**
  (実測 8.4-8.5%) で `is_complete` にも非単調フラグにも出ない (**張り付きは「平坦」であって
  振動ではない**)。**厳密な一致だけが指紋**である。実測 (K2Mn[Fe(CN)6] 247 フレーム) では
  9 フレームが張り付き、**うち 6 連続が転移ドーム頂点の直前**にあったため、報告したドームの
  位置と高さが信用できなくなった。**両方を見ること**:

  | フラグ | 意味 | いつ出るか |
  |---|---|---|
  | `seed_pinned` / `seed_pinned_frames` | 分率が等分 seed (1/相数; 2 相なら 0.500/0.500) に厳密一致 | **分率ウォームスタートが効いていない** (`warm_start_fractions=False`・フレーム 0・種が渡らなかった) |
  | `fractions_frozen` / `frozen_fraction_frames` | 分率が**直前フレームの値**に厳密一致 | ウォームスタート下で**そのフレームの分率精密化が死んでいる** (種の値をそのまま返した)。値が 1/n でないので `seed_pinned` には**出ない** |

  → **両方のフレーム番号を集めて 1 回の `repair_frames` 呼び出しで修復する** (`target_frames`):

  ```python
  cps = check_phase_set(result)
  suspect = sorted({f["frame"] for f in cps["seed_pinned_frames"]}
                   | {f["frame"] for f in cps["frozen_fraction_frames"]})
  repair_frames(result, frames, phases,
                target_frames=suspect,          # ★これが無いと張り付きには到達できない
                instrument={...},               # 系列と同じ装置設定
                two_theta_limits=[2.4, 18.0])   # ★系列を精密化したのと同じレンジ
  ```

  - **`target_frames` は必須**。省略すると `repair_frames` は Rwp/分率の**ジャンプ**を探すが、
    張り付きは定義上「平坦」なので**どの閾値でも拾えない** — `discontinuities=[]`/`repairs=[]`
    = 「直すものは無い」が返る。**直前に「信用するな」と言われたフレームに対して、である**。
  - **疑わしいフレームは 1 回の呼び出しで全て渡す**。指定フレームは互いに warm-start 元から
    除外されるため、**1 つずつ呼ぶと両隣も張り付いた区間 (実測 125-130 の 6 連続) で欠陥を
    持つ隣から種を貰い**、欠陥を引き継いだまま「修復成功」になる。
  - **張り付いたフレームを黙って捨てない** — 可視化して物理的解釈の対象から外す判断を
    ユーザーに示すこと。

#### J2/J3 残差から欠落相・対称性低下を仮説化

各フレームの `residual_report`:

- **`top_features` の + 残差** (obs > calc) = **未説明ピーク** = 欠落相の候補。
  2θ から d 値を出し、**d 比**で格子型を推定する (実データでは 5.7°/10.9° の +残差 →
  d=5.258/3.729/2.640 の比から **cubic Fm-3m を独立同定**できた)。
- **強度比のズレ・ピーク分裂** → **対称性低下**の候補 (実データでは深充電の (220)/(400) 比
  ズレ → **Mn³⁺ Jahn-Teller 正方晶**。実 CIF で c/a_pc=1.054 = 5.4% 伸長)。
  部分群の候補を提示し**承認を得る**。
- **`baseline_numerator_fraction` が大きい** → 「モデルでは下げられない」= **データ側の問題**。
  **手順 1 に戻る** (相を足して誤魔化さない)。

#### J6 系統ブロックの再構成

```python
repair_frames(result, frames, phases,
              instrument={...},              # 系列と同じ装置設定
              two_theta_limits=[2.4, 18.0])  # ★系列を精密化したのと同じレンジ
```

- **`two_theta_limits` は必ず系列と同じ値を渡す**。省略すると修復試行だけが全域で走り、採用規則
  `rwp_after < rwp_before - rwp_tol` が**異なるデータ域の Rwp を比較**する。**エラーは出ず、
  無効な比較のまま「修復成功」が採用される**。「呼べるが黙って間違う」は「呼べない」より悪い。
- **`phases` には系列で使われている全相を渡す** (`appearances` の自動追加相を含む)。
  欠けるとツールがエラーにする — 黙って相を落として「修復成功」にしないため。
- `repairs` は Rwp 改善時のみ採用済 (規則なので自律)。
- **`needs_model_revision` はモデルの欠陥**。近傍 warm-start では直らない (両隣も同欠陥)。
  相集合/セル解放を**再構成**する (実データ: pure-mono ブロックは単相 mono+セル解放で
  9.1-10.7% → **6.5-8.1%**)。

#### J4 参照構造の供給

**手組みモデルを信用しない**。実データでは手組み正方晶の**歪み方向が逆**で、
実験 tetra CIF (I4/mmm) の投入が決定打だった。MP かユーザー提供 CIF を優先する。

#### J8 電気化学との突合

分率の振動が多段酸化還元か artifact かは **dQ/dV 無しでは決まらない**。
未確定なら**未確定と書く**。必要なら V-t / dQ/dV をユーザーに要求する。

### 4. 改訂は必ず承認を挟む (ModelAction)

相の追加/除外・対称性変更・セル解放方針の変更は**ユーザー承認後に適用**し、
**Rwp 改善 ∧ 物理妥当性維持**で受理、外れれば**可逆棄却** (P2 非破壊・ledger 追記)。
**提案≠適用**。

### 5. 因果を確定させる

「直った」で終わらせない。**単一変数の統制実験**で真因を特定する。

> 実例: Rwp 66% を「プロファイル初期値のせい」と誤診し W=180 を入れた (68% — 効いていない
> 手がかりを無視した)。統制実験で真因は **CIF 空間群設定バグ**と判明:
> 正しい CIF は W=1→19.94% / W=180→26.14%、壊れた CIF は W=1→75.10% / W=180→72.48%。
> **手で入れた W=180 はむしろ悪化させていた**。

### 6. 報告

**Rwp と併せて、相集合の完全性をどう確認したかを必ず書く**。未確定は未確定と書く。

> ⚠ **`phase_fractions` は Scale であって重量分率 (wt%) ではない** — 出版値・定量相分析には
> **`phase_weight_fractions` ± `phase_weight_fraction_esd`** を使う (手順 7)。

### 7. 定量値を報告する — **`phase_fractions` は wt% ではない**

**`phase_fractions` は Scale (HAP Scale を和=1 に正規化した値) であって重量分率ではない**。
Scale は単位胞の散乱能に対する比例係数であり、**単位胞質量が相間で異なると重量分率と乖離する**。

> 実測 (K₂Mn[Fe(CN)₆]): cubic 1103.4 amu vs tetra 517.8 amu → **同じ fit で 65.6 Scale% が
> 実際には 47.2 wt%。2.1x の差**である。「tetra ドーム頂点 65.6%」と報告した数値は誤りだった。

| キー | 何か | 使いどころ |
|---|---|---|
| `phase_fractions` | **Scale** の正規化値 | 相対比較のみ (新相の有意性・転移の追跡) |
| `phase_weight_fractions` | **重量 (質量) 分率** (GSAS `calcMassFracs` が精密化占有率込みで算出) | **出版値・定量相分析はこちら** |
| `phase_weight_fraction_esd` | 重量分率の esd (共分散から伝播) | **出版には esd 必須** |
| `cell_esd` | 格子 esd (a,b,c,α,β,γ) | 同上 (esd 無しの格子は出版できない) |

これらを返すツール (**どれも同じキー名**):

| ツール | どこに |
|---|---|
| `sequential_rietveld` | `result["frames"][i]` (フレーム毎) |
| `repair_frames` | `out["repairs"][j]` (**修復したフレーム毎**) |
| `auto_rietveld` | 結果直下 |

> **修復したフレームは `repairs[]` の値で置き換えて報告する** — `result["frames"][i]` は
> **修復前**の値のままである (`repair_frames` は非破壊で元の系列を書き換えない)。
> `target_frames` で名指しするのは `check_phase_set` が「信用するな」と言ったフレームであり、
> 実測ではそれが**転移ドーム頂点の直前 (125-130) = 報告の主要値そのもの**だった。

空 dict = その精密化から値が得られなかった (共分散なし/未収束) の意味で、**esd=0 ではない**。

## 禁止事項

- **Rwp が良いことを根拠に相集合を正しいと結論しない** (J5/J7 の失敗は Rwp 8% で起きた)。
- **`phase_fractions` (Scale) を wt% として報告しない** (実測 2.1x 誤る)。定量相分析の出版値は
  `phase_weight_fractions` ± `phase_weight_fraction_esd`。
- **閾値を「期待した数字」に合わせて調整しない**。②/① の助言器は提案のみ、実測値を報告する。
- **系統ブロックを近傍 warm-start で「直そう」としない** (両隣も同欠陥 = 無効)。
- **「対策を入れたら直った」で因果を確定させない**。
- **残差を説明するためだけに相を足さない**。`baseline_numerator_fraction` が大きいときは
  データ側の問題であり、相追加は誤魔化しになる。

## 権限境界

| 判断 | 決定論コア (自律) | ③ (あなた/ユーザー) |
|---|---|---|
| データ品質の検出・2θ 上限の提案 | ✅ 提示のみ | ✅ 生データの要求はユーザーへ |
| 不連続フレームの近傍 warm-start 修復 | ✅ 自律 (Rwp 改善時のみ採用・ledger) | `needs_model_revision` を判断 |
| **新相の自動追加** (`phase_id` 有効時) | 🟡 **受理基準で自律採用する** (frac∧Rwp∧validity) | ✅ **`appearances` を監査**し化学妥当性を確認・疑わしきはユーザー承認 |
| 相集合の完全性 (相の**欠落**) | ❌ **原理的に不可** | ✅ **あなたが疑う** |
| **③ が判断して**相を追加/除外・対称性変更・構造改訂 | ❌ | ✅ **ユーザー承認必須** |

> **注意**: `sequential_rietveld` に `phase_id` を渡すと、**コアは承認なしに相を追加する**
> (受理基準を満たす場合のみ・可逆棄却つき — `insitu` skill と同じ挙動)。「相集合は自分が
> 変えない限り不変」と思い込まないこと。**`appearances` を必ず読み**、追加された相が化学的に
> 妥当か・未指数ピークを説明するかを ③ が判断する。承認が要るのは**あなたが判断して行う**
> 改訂 (相の追加/除外・対称性変更・構造改訂) である。

**なぜ相の欠落は自律検出できないか**: 受理基準は「**追加された相が残差を説明するか**」しか見ない。
欠落相は**その視野の外**にあり、しかも欠けた相の強度は計量の近い別相が肩代わりして Rwp を保つ。
**統計量では検出できない。③ が疑う以外に手段が無い。**

## 前提

- GSAS-II (GSASIIscriptable) が導入されていること。未導入なら該当ツールが error を返す。
- 相同定は Materials Project キーを使う (`.env` の `MATERIALS_PROJECT_API` を自動読込, #51)。
  無い場合は CIF を直接指定する運用に切り替える。
