# AI エージェント operando 系列 診断・モデル改訂 指示書 (AGENT_PLAYBOOK)

対象: **非 Claude ハーネス** (Codex 等) を含む任意の ③ 判断層。Claude Code は
`plugins/tsumugin/skills/operando-diagnose/SKILL.md` を使う (内容は本書と同一)。
**MCP (②) が共有ポータブル核**であり、③ の実体が何であっても駆動手順は変わらない。

設計: `docs/design/operando-diagnosis/architecture.md`。
根拠データ: K₂Mn[Fe(CN)₆] 放射光電気化学 operando (247 フレーム, λ=0.501345 Å)。
実測値はすべて当該解析で取得したもの。

## 0. この指示書の存在理由 — **Rwp では原理的に検出できない誤り**

実解析で最も重大だった失敗は、**フィット統計がすべて良好なまま物理的に誤った描像**を得たこと:

- 充電域を cubic+tetra の 2 相に限定 (「放電相 mono は充電時に存在しない」という一見妥当な判断)。
- 転移端に残る monoclinic の強度を、計量の近い **tetragonal が肩代わり**。
- 結果:「tetragonal が増減を繰り返す」非物理な描像 (`0.42→0.17→0.70→0.04→0.63`)。
- **Rwp は終始 ~8% と良好**。GOF も validity も警告を出さない。
- 全 3 相を入れ直すと単一ドーム (`0→0.58→0`) に収束 = 正解。
- **発見者は人間の物理的直感**だった。

計量が近い相 (本系は mono/cubic/tetra が全て cubic 派生) は**互いの強度を吸収し合う**。
① の統計量では検出できない。**だから ③ が要る**。

## 1. 前提

- GSAS-II (GSASIIscriptable) 導入済。未導入なら該当ツールが error dict を返す。
- ② の全ツールは**例外を送出せず** `{"error", "error_type"}` へ縮退する。error dict は
  読んで直すこと (存在しないファイルパスも `{"error_type": "FileNotFoundError"}` へ縮退する
  — Issue #94 解決済。`error_type` で「入力ファイルが無い」と他の失敗を区別できる)。
- 相同定は MP キー (`.env` の `MATERIALS_PROJECT_API` を自動読込, #51)。無ければ CIF 直接指定。

## 2. 手順

### 2.1 データ品質を先に問う (**精密化の前に**)

```python
assess_data_quality(path, data_format="XYE",
                    excluded_regions=[[6.6, 7.6], [23.89, 23.97], [30.0, 41.4]])
# -> {"is_subtracted": true, "confidence": 1.0, "reasons": [...],
#     "suggested_two_theta_limit": 20.5, "recommendation": "..."}
```

- **`is_subtracted=True` → 系列を回す前に生データの有無を人間に問う**。背景減算済 + esd=√I は
  ノイズ底を過大重みし、**同一モデルで Rwp 26% → 生+背景精密化 6.7%**。**fit でなく重み付けの
  問題**であり、気づかず回すと全フレームの Rwp が無意味に高いまま「収束しない」と誤診する。
  **本解析で最大のレバーだった**。
- `suggested_two_theta_limit` を取る際は**寄生ピーク窓を `excluded_regions` で必ず渡す**
  (渡さないとセル由来の反射を信号終端と拾い上限が押し出される — 実測 38.1°)。

### 2.2 系列を回す

```python
sequential_rietveld(
    frames=[{"data_path": f, "axis_value": i, "data_format": "XYE",
             "two_theta_limits": [2.4, 18.0],
             "excluded_regions": [[6.6, 7.6], [12.36, 12.50]]} for i, f in enumerate(files)],
    initial_phases=[{"structure_path": "mono.cif", "phase_name": "mono", "refine_cell": False},
                    {"structure_path": "cubic.cif", "phase_name": "cubic"},
                    {"structure_path": "tetra_real.cif", "phase_name": "tetra", "refine_cell": False}],
    instrument={"path": "kmnfe.instprm", "radiation": "xray_synchrotron",
                "geometry": "debye_scherrer", "background_coeffs": 18,
                "auto_freeze_minor_cells": 0.2},   # ← instrument spec の中。tool の kwarg ではない
    warm_start_fractions=True,
    two_theta_limits=[2.4, 18.0],
)
```

**`instrument` を省略すると実験室 X 線 Bragg-Brentano・背景 6 項の便宜既定になる**
(放射光データでは必ず明示)。実測で効いた設定:

| 設定 | 効果 (実測) |
|---|---|
| 生データ + `background_coeffs=18` | Rwp 26% → **6.7%** (12/24 項は劣る) |
| `two_theta_limits=[2.4, 18.0]` | 30°→18° で **369s→8s** かつ収束改善 |
| 少数相のセル凍結 (`PhaseSpec.refine_cell=False` / `instrument["auto_freeze_minor_cells"]=0.2`) | 解放すると計量相関で発散・分率崩壊 |
| `warm_start_fractions=True` (tool の kwarg) | 分率が初期値に張り付くフレームを是正 (#82) |

> **置き場所に注意** (2 つは階層が違う):
> - `refine_cell` は **`PhaseSpec` のキー** (相ごとの手動凍結。手動が自動に優先する)。
> - `auto_freeze_minor_cells` は **`instrument` spec のキー** (tool のトップレベル kwarg ではない
>   — 直接渡すと `TypeError` が MCP 境界を越える)。サーバが runner を組むときにのみ効く。
>
> `auto_freeze_minor_cells` は**`phase_fractions` (= Scale) 基準の閾値であり float。bool ではない**
> — `True` は `float(True)==1.0` = 全相凍結になる (② が bool を拒否する)。例 0.2。
>
> ### ⚠ 分率の閾値は**すべて Scale 基準** — wt% で考えて数字を決めない
>
> `auto_freeze_minor_cells` (`instrument` spec) と `phase_id.frac_min` が比較する相分率は
> `phase_fractions` (**HAP Scale の Σ=1 正規化値**) であり、**`phase_weight_fractions` (wt%) では
> ない**。本 PLAYBOOK は「出版値は wt%・Scale を wt% として報告するな」と言うが、
> **閾値の座標系だけは Scale のまま**である。
>
> 実測 K₂Mn[Fe(CN)₆] (cubic 1103.4 / tetra 517.8 amu):
> `Scale {cubic 0.75, tetra 0.25}` = `wt% {cubic 86.5, tetra 13.5}`。
> 「tetra は 13.5 wt% で少数相だから `auto_freeze_minor_cells=0.15`」と決めると、実際の比較は
> **Scale 0.25 ≥ 0.15** → **tetra のセルは解放されたまま**で #80 の発散が起きる。
> **答えが basis で割れる**ので、閾値を決める前に `frames[i]["phase_fractions"]` (Scale) を見ること。
> `phase_id` の `frac_min` (新相採用の最小分率, 既定 0.02) も **Scale** 基準である。
> `check_phase_set` / `repair_frames` の分率閾値 (`min_amplitude` / `frac_delta`) も同じく Scale 基準
> (各ツールの出力 `fraction_basis` がそれを明示する)。

#### `phase_id` — 新相自動同定のツマミ (`PhaseIdConfig` の全フィールドを受ける)

> ### ⚠ `wavelength` は**既定 Cu Kα1 (1.5406 Å)** — 放射光/中性子では必ず指定する
>
> `phase_id.wavelength` は**異方セルプリアラインと候補再スコアの線源波長**である。
> `instrument.radiation="xray_synchrotron"` は**精密化側**の設定であって、同定側の λ はこちら。
> 省くと同定だけが Cu の波長で d↔2θ 変換を行い、**プリアライン後のセルも候補順位も系統的に誤る**。
>
> **例外も警告も出ない**。症状は「候補が当たらない」「新相を足しても Rwp が下がらない」だけで、
> ③ は「この系では新相同定が効かない」と誤って学習する。実測 K₂Mn[Fe(CN)₆] は 0.800113 Å。

```python
phase_id={"elements": ["K", "Mn", "Fe", "C", "N"],
          "wavelength": 0.800113,          # ← Cu 以外なら必須
          "frac_min": 0.02,                # ← Scale 基準 (上の警告)
          "refine_new_phase_cell": True,   # ← プリアラインの on/off (唯一の escape hatch)
          "require_full_element_system": True}
```

| キー | 既定 | いつ動かすか |
|---|---|---|
| `wavelength` | **1.5406 (Cu Kα1)** | **Cu 以外なら常に** (上記) |
| `elements` | `[]` (同定しない) | 既知相の元素 + 想定元素。**文字列のリスト** (裸の `"CaTeO"` は拒否) |
| `frac_min` | 0.02 | 新相採用の最小 **Scale** (wt% ではない) |
| `refine_new_phase_cell` | `true` | 少数相フレームでは prealign が**支配相のピークにロック**して誤セルを返す。`appearances` の新相セルが不合理なら `false` |
| `rerank_top_k` / `top_k` | 5 / 1 | 候補順位が DFT の軸別誤差で崩れる系で増やす |
| `require_full_element_system` | `true` | 全元素系に限定する化学ガード。副生成物を許すときだけ `false` |
| `require_validity` | `false` | 転移域では旧相のセル急変で新相を巻き添えに弾くため既定 off |
| `min_rwp_gain` | 0.01 | 受理に要する**相対** Rwp 改善。junk が通るなら上げる |
| `snr_trigger` | 20.0 | 探索発火の残差 S/N。**データセット固有** (常時発火するなら上げる・0 で無効) |
| `max_new_phases` | 0 (無制限) | 想定相数が既知で探索を打ち切りたいときだけ |
| `warm_start_known_phases` | `true` | 現行相を精密化格子で残差から先に減算 (少数新相の検出感度が上がる) |
| `bic_acceptance` | `false` | 粉末では bic は相対 Rwp より**寛容**で偽相も採るので通常は触らない |
| `hull_cutoff_ev` | 0.1 | MP 安定性フィルタ (eV/atom)。`null` で無効 |

**出所**: `elements` は化学 (既知相 CIF / `identify_phases` の結果) から、`wavelength` は**測定条件**
(instprm/ビームライン諸元) から。**残りはすべて ③ が置く policy 定数**であり、他ツールの出力から
導くものではない。未知キーは error dict になるので、綴り誤りが黙って無視されることはない。

### 2.3 疑う (**本書の主眼**)

#### J5 相集合の完全性 ★最重要

```python
check_phase_set(result)
# -> {"is_complete": false, "union": [...], "frames_with_missing": [...],
#     "phases": [{"phase": "tetra", "turning_points": 4, "flagged": true}],
#     "seed_pinned": true,
#     "seed_pinned_frames": [{"frame": 125, "rwp": 8.4, "n_phases": 2, "seed_value": 0.5,
#                             "phase_fractions": {"cubic": 0.5, "tetra": 0.5}}],
#     "fractions_frozen": true,
#     "frozen_fraction_frames": [{"frame": 126, "previous_frame": 125, "rwp": 8.5, "n_phases": 2,
#                                 "phase_fractions": {"cubic": 0.42, "tetra": 0.58}}]}
```

- **`is_complete=False`** → 「**除外した相の強度を、計量の近い別の相が肩代わりしていないか**」
  を疑う。**和集合で再フィットし相分率を比較**する。**Rwp が良くても信じない**。
- **`flagged=True` (分率が非単調に振動)** → 物理的に妥当かを問う。単調な転移 (A→B→C) が
  自然な系で分率が増減を繰り返すなら、**まず artifact を疑う**。実データではこれが唯一の手がかり。
- **分率が動かなかったフレーム (2 つの指紋)** → **そのフレームの分率を報告に使わない**。
  いずれも分率精密化がそのフレームで一度も動いていないことを意味し、**Rwp は平凡なまま**
  (実測 8.4-8.5%) で `is_complete` にも非単調フラグにも出ない (**張り付きは「平坦」であって
  振動ではない**) — **厳密な一致だけが指紋**。実測 (K2Mn[Fe(CN)6] 247 フレーム) で 9 フレームが
  張り付き、**うち 6 連続が転移ドーム頂点の直前**にあったため報告したドームの位置と高さが
  信用できなくなった。**両方を見る**:

  | フラグ | 意味 | いつ出るか |
  |---|---|---|
  | `seed_pinned` / `seed_pinned_frames` | 分率が等分 seed (1/相数) に厳密一致 | **分率ウォームスタートが効いていない** |
  | `fractions_frozen` / `frozen_fraction_frames` | 分率が**直前フレームの値**に厳密一致 | ウォームスタート下で**分率精密化が死んでいる**。1/n でないので `seed_pinned` には出ない |

  → **両方のフレーム番号を集めて 1 回の `repair_frames` 呼び出しで修復する** (`target_frames`):

  ```python
  cps = check_phase_set(result)
  suspect = sorted({f["frame"] for f in cps["seed_pinned_frames"]}
                   | {f["frame"] for f in cps["frozen_fraction_frames"]})
  repair_frames(result, frames, phases, target_frames=suspect,
                instrument={...}, two_theta_limits=[2.4, 18.0])
  ```

  - **`target_frames` 必須**: 省略時の自動検出は Rwp/分率の**ジャンプ**しか見ず、張り付きは
    「平坦」なので**どの閾値でも拾えない** → `repairs=[]` = 「直すものは無い」が返る。
  - **1 回の呼び出しで全て渡す**: 指定フレームは互いに warm-start 元から除外される。1 つずつ
    呼ぶと両隣も張り付いた区間 (実測 125-130 の 6 連続) で**欠陥を持つ隣から種を貰う**。
  - **黙って捨てない** (可視化して解釈対象から外す判断をユーザーに示す)。

#### J2/J3 残差から欠落相・対称性低下を仮説化

`sequential_rietveld` / `auto_rietveld` の出力には**フレーム毎に `residual_report` が同梱**される
(残差配列は MCP を跨がない — 実測 135KiB/frame・247 frame で 32.6MiB になるため ① 側で畳む)。

```python
result["frames"][i]["residual_report"]
# -> {"rwp":…, "peak_only_rwp":…, "baseline_numerator_fraction":…,
#     "angular_rwp":[[lo,hi,v],…], "top_features":[{"two_theta":5.69,"residual":39.7,"obs":…},…]}
```

- **`top_features` の + 残差** (obs > calc) = **未説明ピーク** = 欠落相の候補。2θ → d 値 →
  **d 比**で格子型を推定 (実データ: 5.7°/10.9° の +残差 → d=5.258/3.729/2.640 の比から
  **cubic Fm-3m を独立同定**)。→ `identify_and_add_phase` かユーザー CIF。
- **強度比のズレ・ピーク分裂** → **対称性低下** (実データ: 深充電の (220)/(400) 比ズレ →
  **Mn³⁺ Jahn-Teller 正方晶**, 実 CIF で c/a_pc=1.054 = 5.4% 伸長)。部分群候補を提示し**承認を得る**。
- **`baseline_numerator_fraction` が大きい** → 「モデルでは下げられない」= **データ側の問題** →
  **2.1 に戻る**。**相を足して誤魔化さない**。

#### J6 系統ブロックの再構成

```python
repair_frames(result, frames, phases, instrument={...}, two_theta_limits=[2.4, 18.0])
# -> {"repairs":[…採用済…], "needs_model_revision":[…], "ledger_entries":[…]}
```

- **`phases` には系列で使われている全相を渡す** (`appearances` の自動追加相を含む)。欠けると
  ② がエラーにする — **黙って相を落として「Rwp 15→7 の修復成功」と報告させないため**。
- `repairs` は Rwp 改善時のみ採用済 (自己検証可能な規則 → ①/② に置ける安全部分集合)。
- **`needs_model_revision` はモデルの欠陥**。近傍 warm-start では直らない (**両隣も同欠陥**)。
  相集合/セル解放を**再構成**する (実データ: pure-mono ブロックは単相 mono+セル解放で
  9.1-10.7% → **6.5-8.1%**)。
- **系全体が前方単一パス由来の系統ブロックで汚染 (偽相が全域に湧く・分率 0 近傍で esd 発散・
  `check_phase_set` が全相 flagged) されているときは、フレーム単位修復でなく `anchored_sequential`
  (M10) で解き直す**。

```python
anchored_sequential(frames, phases,
                    anchor_table={"0": ["mono"], "124": ["cubic", "tetra"], "246": ["mono"]},
                    instrument={...}, two_theta_limits=[2.4, 18.0])
# -> 系列結果 + "anchors" + "crossovers" (crossovers[].total_bic で相数を bic 選定)
```

  前方単一パスは初期フレーム依存 + 転移域セル汚染で脆く、上記病理は**その脆さの帰結**である。M10 は
  信頼フレーム (アンカー) 起点の双方向精密化 + **相集合の違う区間を Rwp でなく bic で選定** (相数を
  抑制) して根治する。`anchor_table` は信頼フレーム→相集合。`instrument`/`two_theta_limits` は必須
  (省略時は無音の既定に落とさず error dict)。実データで per-frame 3 相固定が Rwp 8% のまま生成した
  「tetra が増減する」偽描像は、当時 M10 が ② 未露出 (Issue #97) で使えなかったことが原因だった。

- **bic でも偽相が残るなら結合距離ゲートを足す** (FR-335)。bic は「相を増やせば残差が減る」ことは
  罰するが、**増えた相の構造が物理的に有り得るか**は見ない。転移域で新相のセルが崩壊したまま僅差で
  勝つ場合 (原子間距離が元素半径和を大きく割る) に効く。`crossovers[].onset_frame` が物理的に
  早すぎる / 新相が転移前から湧くときだけ足す — **常時 ON にしない** (高温/転移で正当に歪んだ構造を
  偽陽性で弾く恐れがあるため既定 OFF)。

```python
anchored_sequential(frames, phases, anchor_table={...},
                    instrument={...}, two_theta_limits=[2.4, 18.0],
                    anchor_config={"require_bond_validity": True,
                                   "bond_tol_lo": 0.7, "bond_tol_hi": 1.3})
# -> crossovers[].bond_gate で効きを読む:
#    "moved"              = ゲートが bic 最良を棄却し crossover を動かした
#    "kept"               = bic 最良が既に結合妥当
#    "no_valid_candidate" = 僅差帯に結合妥当な経路が 1 つも無い
#                           → 相集合そのものが疑わしい。J5 (check_phase_set) へ戻る
```

  pymatgen 不在の環境では自動 skip される (ゲートを課さず bic のまま)。

#### J4 参照構造の供給

**手組みモデルを信用しない**。実データでは手組み正方晶の**歪み方向が逆**で、実験 tetra CIF
(I4/mmm) の投入が決定打だった。MP かユーザー提供 CIF を優先する。DFT (MP) 由来は格子が軸別に
ずれるため異方セル補正が自動で入る (#20)。

#### J8 電気化学との突合

BioLogic `.mpr` があるなら **`align_echem`** で回折フレームを充放電曲線へ整列し、転移点 (`parametric_fit`
の onset/midpoint) を電気化学イベントと突合する (相転移が充放電と整合するかが物理的妥当性の傍証。
実測: tetra JT ドーム頂点 = 充電カットオフ 2.100 V のフレームと一致)。

```python
align_echem("K-10.mpr", offset_s=22.1, interval_s=283.0, n_frames=247)
# -> frames[]{frame, time_h, voltage_v, state, in_span} + curve 概要
```

フレーム時刻は `frame_epoch_s` (POSIX 秒明示) か一定ケイデンス `offset_s`+`interval_s`+`n_frames`。
**`.mpr` が無い**とき、分率の振動が多段酸化還元か artifact かは **dQ/dV 無しでは決まらない**ので
**未確定と書き**、V-t / dQ/dV を人間に要求する (電圧を捏造しない)。

#### J9 クーロメトリー整合 (FR-318) — **アルカリ量収支で相集合と分率を検算する**

`alkali_budget` (MPR + 活物質質量 + 式量 + x₀) で per-frame の総アルカリ量目標を作り、
`charge_constraint` spec を系列ツール (`sequential_rietveld`/`anchored_sequential`) に渡すと、
各フレームに `alkali_x_xrd` (XRD 由来モル平均)・`alkali_x_echem` (クーロメトリー目標)・
`alkali_residual` (差) が付く。**電気量は独立測定**なので:

- **`alkali_residual` の系統的ドリフト** = 不可逆容量/副反応の兆候。Rwp には出ない誤りの独立検出器。
- **`alkali_feasibility="infeasible"`** = 目標が相組成の凸包の外 = **相集合か x₀ が誤っている**強い
  シグナル (J5 の相欠落仮説と突合する)。
- アンカー `ab_check.delta_rwp` の超過警告 → x₀ 校正の**提案** (`fr318_x0_calibration_proposal`,
  applied=False) が ledger に出る。**採用は人間の承認** (提案≠適用)。
- **`soft` (ChemComp restraint) モードは使わない** — 現行 GSAS-II の headless 精密化では restraint
  penalty が最小二乗に取り込まれない (実測バグ; 自動で diagnose に縮退し警告が出る)。
- **lock_fractions は明示 opt-in**: 2 相では相分率が完全決定され XRD は分率に寄与しなくなる
  (Rwp が一致度の検定量に変わる)。採用判断は人間と合意する。
- `alkali_x_xrd` の basis は**重量分率を式量で割ったモル平均** (Scale でも wt% 単純平均でもない)。

#### J10 固溶体 vs 二相判別 (FR-313) — **転移域の描像を確定する前に**

ある区間で格子が動く/相分率が動くように見えるとき、それが**固溶体** (単相の格子が連続変化)
か**二相反応** (端成分 2 相の分率変化) かは Rwp を見比べても決まらない (両モデルが近い Rwp =
僅差)。`discriminate` に判定させる:

```
discriminate(series={"data_paths": [...]} または {two_theta, intensities},
             initial_phases=[{"phase_ref": "...", "lattice": {...}, "structure_ref": "<CIF>"}],
             frame_range=[start, end], data_format="XYE",
             config={"nested_arbitration": {}})   # 僅差を nested 物理尤度で再裁定 (#76) するとき
```

- **`structure_ref`** (実 CIF) を各相に入れる (`identify_and_add_phase`/`convert_pattern` の出力)。
  無いと格子/scale のみの判別 (プレースホルダ構造)。端成分 2 相は**同構造・別格子**が前提
  (`phase_ref` 共有)、異構造 2 相はスコープ外。
- `verdict` が `undecided` のとき**確定を主張しない** — `escalations` に理由 (僅差/両仮説高 R/
  比較不能)。僅差なら `config.nested_arbitration` を付けて再裁定を試し、`adjudicated_by` が
  `nested`/`laplace` になり `nested_delta_evidence` (BIC 等価スケール) で解消できたか読む。
  それでも undecided なら人間の確認を要求する (**提案≠適用**)。

### 2.4 改訂は承認を挟む

相の追加/除外・対称性変更・セル解放方針の変更は**人間の承認後に適用**し、
**Rwp 改善 ∧ 物理妥当性維持**で受理、外れれば**可逆棄却** (P2 非破壊・ledger 追記)。**提案≠適用**。

### 2.5 因果を確定させる

「直った」で終わらせない。**単一変数の統制実験**で真因を特定する。

> 実例: Rwp 66% を「プロファイル初期値のせい」と誤診し W=180 を入れた (68% — 効いていない
> 手がかりを無視)。統制実験で真因は **CIF 空間群設定バグ (#48)** と判明:
> 正しい CIF は W=1→**19.94%** / W=180→26.14%、壊れた CIF は W=1→75.10% / W=180→72.48%。
> **手で入れた W=180 はむしろ悪化させていた**。→ Issue #79 は前提否定で close。

### 2.6 定量値を報告する — **`phase_fractions` は wt% ではない**

**`phase_fractions` は Scale (HAP Scale の正規化値) であって重量分率ではない**。Scale は単位胞の
散乱能に対する比例係数で、**単位胞質量が相間で異なると重量分率と乖離する**。

> 実測 (K₂Mn[Fe(CN)₆]): cubic 1103.4 amu vs tetra 517.8 amu → **同じ fit で 65.6 Scale% が
> 実際には 47.2 wt%** (この点で 1.39 倍の誤り)。「tetra ドーム頂点 65.6%」の報告は誤りだった。
>
> **乖離の大きさはフレーム毎に違う** (実測: fr112 1.62 / fr120 1.48 / fr124 1.41 / fr126 1.39 倍)。
> 大きさを決めるのは相の**単位胞質量比** (ここでは 2.13 倍) と**そのフレームの分率**である。
> ⚠ **単一の換算係数は存在しない — Scale に係数を掛けて wt% を作ってはならない**。
> 必ず `phase_weight_fractions` を読むこと。

```python
result["frames"][i]["phase_weight_fractions"]      # -> {"cubic": 0.472, "tetra": 0.528}  出版値
result["frames"][i]["phase_weight_fraction_esd"]   # -> {"cubic": 0.006, "tetra": 0.006}  esd 必須
result["frames"][i]["cell_esd"]                    # 格子 esd。0.0 と None は意味が違う (下記)
# -> {"mono":  [0.0133, 0.0177, 0.0109, 0.0, 0.1300, 0.0],   解放: >0 = su / 0.0 = 対称拘束
#     "cubic": [None, None, None, None, None, None]}          凍結: 決まっていない = esd 無し

# 修復したフレームは repairs[] の値で置き換える (frames[i] は修復前のまま = 非破壊)
rep = repaired["repairs"][j]
rep["frame"], rep["phase_weight_fractions"], rep["phase_weight_fraction_esd"], rep["cell_esd"]
```

| キー | 何か | 使いどころ |
|---|---|---|
| `phase_fractions` | **Scale** の正規化値 | **同一 basis 内の相対比較のみ** (新相の有意性・張り付き検出)。**転移の追跡には使えない** (下記) |
| `phase_weight_fractions` | **重量 (質量) 分率** (GSAS `calcMassFracs`) | **出版値・定量相分析はこちら**。転移温度もこちら基準 |
| `phase_weight_fraction_esd` | 重量分率の esd | **出版には esd 必須** |
| `cell_esd` | 格子 esd (a,b,c,α,β,γ) | 同上。**3 状態を区別する → 下記** |

#### `cell_esd` の 3 状態 — `0.0` と `null` は**意味が違う**

| 値 | 意味 | どう報告するか |
|---|---|---|
| `>0` | 解放して精密化した項の su | `a = 10.0316(133)` |
| `0.0` | **対称拘束で厳密に固定** (monoclinic の α/γ = 90° 等) | 90° は定義値。esd を付けない |
| `null` | **そのフレームで格子を解放していない** — `refine_cell=False` / `auto_freeze_minor_cells` による凍結・セル段の revert・未精密化 | 「参照値に固定 (not refined)」と書く。**esd を付けてはならない** |
| 相ごと欠落 | 抽出できなかった (共分散構造の異常) | 出版せず原因を調べる |

⚠ **「0 なら固定」と推論しないこと** — 解放した相の中にも真の `0.0` (対称拘束) がある。
凍結は `null` でしか判らない。`auto_freeze_minor_cells` は相を名指ししなくても Scale が閾値未満の
相を凍結するので、**どの相が凍結されたかは `cell_esd` の `null` で読む**。

**転移温度を Scale から出さない**: `parametric_fit` の onset/midpoint は「曲線が**絶対レベル**
0.50 / 0.10 を横切る軸値」であり、y 軸が Scale か wt% かで**答えが動く**。「Scale は相対比較なら
安全」は転移推定には当てはまらない。

> 実測 (K₂Mn[Fe(CN)₆] tetra 充電域): **同じ精密化**から Scale は「midpoint 9.515 h」を、wt% は
> 「**転移なし**」を出した (Scale 0→0.656 は 0.50 を横切るが wt% は 0→0.472 で届かない)。
> Scale が midpoint と呼んだ点は実際には **34.0 wt%**。

```python
# 転移温度は既定 (basis="weight" = 重量分率) のまま取る。fraction_basis を必ず確認する。
pf = parametric_fit(result=seq, phase="tetra", component="a")
assert pf["fraction_basis"] == "weight"   # "weight" でなければ報告しない
# 重量分率が無い系列は error dict ("FractionBasisUnavailableError") -> Scale で代用しない
# basis="scale" は診断専用 (相対的な立ち上がりの目視)。その数値は出版しない
```

同じキー名を `sequential_rietveld` は `frames[i]` に、**`repair_frames` は `repairs[j]` に
(修復したフレーム毎)**、`auto_rietveld` は結果直下に返す。空 dict = 値が得られなかった
(共分散なし/未収束) の意味で、**esd=0 ではない**。

> **修復フレームの出版値を落とさない**: `target_frames` で名指しするのは `check_phase_set` が
> 「信用するな」と言ったフレームであり、実測ではそれが**転移ドーム頂点の直前 (125-130) =
> 報告の主要値そのもの**だった。`repairs[]` を読まずに `frames[i]` を報告すると、
> **修復前の (張り付いた) 値**を出版することになる。

## 3. 禁止事項

- **Rwp が良いことを根拠に相集合を正しいと結論しない** (失敗は Rwp 8% で起きた)。
- **閾値を「期待した数字」に合わせて調整しない**。②/① は提案のみ。実測値を報告する。
- **系統ブロックを近傍 warm-start で「直そう」としない** (両隣も同欠陥 = 無効)。
- **「対策を入れたら直った」で因果を確定させない**。
- **残差を説明するためだけに相を足さない** (`baseline_numerator_fraction` 大 = データ側の問題)。
- **`phase_fractions` (Scale) を wt% として報告しない** (実測 1.39-1.62 倍誤る。**倍率はフレーム
  毎に違うので換算係数で直せない**)。出版値は
  `phase_weight_fractions` ± `phase_weight_fraction_esd`。

## 4. 権限境界

| 判断 | 決定論コア (自律) | ③ (あなた/人間) |
|---|---|---|
| データ品質の検出・2θ 上限の提案 | ✅ 提示のみ | ✅ 生データの要求は人間へ |
| 不連続フレームの近傍 warm-start 修復 | ✅ 自律 (Rwp 改善時のみ採用・ledger) | `needs_model_revision` を判断 |
| **新相の自動追加** (`phase_id` 有効時) | 🟡 **受理基準で自律採用する** (frac∧Rwp∧validity) | ✅ **`appearances` を監査**し化学妥当性を確認 |
| **相集合の完全性** (相の**欠落**) | ❌ **原理的に不可** | ✅ **③ が疑う** |
| **③ が判断して**相を追加/除外・対称性変更・構造改訂 | ❌ | ✅ **人間の承認必須** |

> `sequential_rietveld` に `phase_id` を渡すと**コアは承認なしに相を追加する** (受理基準を満たす
> 場合のみ・可逆棄却つき)。「相集合は自分が変えない限り不変」と思い込まず、**`appearances` を
> 必ず読む**こと。人間の承認が要るのは **③ が判断して行う**改訂である。

**なぜ相の欠落は自律検出できないか**: 受理基準は「**追加された相が残差を説明するか**」しか
見ない。欠落相は**その視野の外**にあり、しかも欠けた相の強度は計量の近い別相が肩代わりして
Rwp を保つ。**統計量では検出できない。③ が疑う以外に手段が無い。**

## 5. 再現ベンチマーク (K₂Mn[Fe(CN)₆] K-10 0.1C)

| | 解析フレーム | Rwp |
|---|---|---|
| 学生の手動解析 (RIETAN, 単相) | frame-1 のみ (1/247) | 16.24% |
| **本フロー (3 相)** | **63/247 (stride 4 の間引き)** | **6.02–8.96% (mean 7.47%), 9% 超ゼロ** |

> ⚠ **間引きである点に注意**。系列は 247 フレームだが、上の Rwp 統計は
> `range(0, 247, 4) + [246]` = **63 フレーム (25.5%)** に対するもの (`scripts/full_3phase.py` の
> 既定 `step=4`)。**全フレーム解析は未実施**であり、間引きで見えない短寿命の中間相・
> 転移端の挙動が残っている可能性がある。全 247 フレームの結果が要る場合は `step=1` で回すこと。
> (本表は当初「全 247 フレーム」と誤記していた — 実測は 63 フレームだった。)

**結論**: monoclinic P2₁/n (K-rich, 放電) → cubic Fm-3m (充電) → **tetragonal I4/mmm (深充電,
Mn³⁺ Jahn-Teller)** → cubic → monoclinic の**完全可逆な 3 相転移**。tetragonal は**単一ドーム**
(peak 0.58 @ frame 124)。frame0 ≈ frame246 で可逆性を構造から確認。
