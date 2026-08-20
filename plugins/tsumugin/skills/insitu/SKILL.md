---
name: insitu
description: 高温/時間 in situ 粉末回折の逐次 (parametric sequential) 全自動 Rietveld 解析を閉ループで進める。MCP ツール (sequential_rietveld / identify_and_add_phase / parametric_fit) を反復駆動し、温度/時間フレーム列をウォームスタートで逐次精密化、相転移で出現する新相を Materials Project から自動同定して相集合に追加、格子 vs 温度・転移温度を抽出する。初期相のみ与えれば新相は自動発見する。データ品質 (背景減算) の確認と相集合の完全性検証 (check_phase_set) を必須手順として含む。**電気化学 operando (充放電) の系列も本 skill が進める** — 転移を含む operando は anchored_sequential (M10, bic で相数抑制) を既定にし、クーロメトリー拘束 (alkali_budget/charge_constraint, FR-318) と echem 同期 (align_echem) で診断/拘束する。
---

# tsumugin: Agentic in situ/operando 逐次 Rietveld 解析 (③ 判断層)

あなた (Claude) が**判断者 ③** として、温度/時間系列の粉末回折を逐次 Rietveld 精密化する閉ループ
解析を行う。M7 単一フレーム自動 Rietveld + M8 agentic 閉ループ + M6 相同定を統合した M9 の系列版。
**初期相のみ与えられ、系列途中で出現する新相 (例 CaTeO3 の脱水相 delta) は自動同定する**のが要点。
**高温/時間の温度系列だけでなく、電気化学 operando (充放電) の系列を「進める」のも本 skill である**
(手順 3′/3″)。

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
| `identify_and_add_phase` | 計器 (相同定) | 残差/生パターン + elements + workdir (+ **`known_phases`** = そのフレームの現行相 [`initial_phases` の dict + `refined_cell`] + `wavelength`) → 物質化した PhaseSpec 候補 (CIF パス) + 根拠 + `prealign_basis`。**`known_phases` を渡して初めて**既知相を引いた残差から少数相を探し、返る CIF に異方セル補正 (#20) が入る |
| `parametric_fit` | 計器 (解析) | 系列結果 + parameter/axis → 熱膨張多項式係数・転移 onset/midpoint±σ |
| `align_echem` | 計器 (電気化学突合) | BioLogic `.mpr` + フレーム時刻 (一定ケイデンス `offset_s`/`interval_s`/`n_frames` or 明示 `frame_epoch_s`) → per-frame の電位/状態 (rest/charge/discharge)。`alkali_budget` の `offset_s`/`interval_s` はここで XRD フレーム時刻と echem を同期して得る |
| `alkali_budget` | 計器 (クーロメトリー, FR-318) | MPR + 活物質質量 + 式量 + x₀ → per-frame 総アルカリ量目標 x_total(t) の表 (`targets[]`)。出力を `sequential_rietveld`/`anchored_sequential` の `charge_constraint.targets` へそのまま渡す |
| `write_sequential_csv` | 出力 (FR-504 トラジェクトリ CSV) | `sequential_rietveld`/`anchored_sequential` の結果 dict + 出力パス → フレーム毎の CSV (frame_index/rwp/gof/相ごとの格子±esd・scale・**wt_frac±esd**)。手順 8 の報告を人間/他ツールへ渡す成果物として使う (`get_trajectory` は使わない — session.trajectory を埋める ② ツールが無く到達不能, Issue #116) |

閉ループ丸ごとは MCP に**無い**。回すのはあなた。

## 精密化成果物 (.gpx) は**フレーム 1 枚ごとに全部保存される** (2026-08-20 規定)

**何もしなくても保存される。** 系列は run ディレクトリを**1 つ**共有し、その下に
**実際に GSAS を回した単位ごとに 1 ファイル**が並ぶ:

| ファイル名 | 何の fit か |
|---|---|
| `f0000_frame.gpx` | フレーム 0 の採用 fit (`sequential_rietveld`) |
| `f0180_trial_<候補相>.gpx` | 自動相同定の試行 — **棄却されたものも残る** |
| `f0032_consolidate_<相>.gpx` / `f0031_backward_<相>.gpx` | セル整合・onset 逆伝播の再精密化 |
| `f0005_anchor.gpx` / `f0005_anchor_ab.gpx` | M10 アンカー確定 / FR-318 の制約有無 A/B |
| `f0007_forward_a0005.gpx` / `f0007_backward_a0012.gpx` | M10 の前方/後方パス (**採られなかった側も**) |
| `f0042_repair_L.gpx` | `repair_frames` の修復試行 |
| `manifest.jsonl` | 索引 (1 行 1 成果物: 役割・番号・相・Rwp・GOF) |

- **どこに**: 既定は**先頭フレームのデータ隣接** `<data_dir>/tsumugin_gpx/run-<日時>/`。
  `gpx_dir="..."` で指定できる。実際の場所は返り値の **`gpx_dir`**。
- **どのフレームがどれか**: 返り値の **`frames[].gpx_path`**。任意のフレームへ
  `mem_density` を掛けるとき・fit を開き直すときはここを使う。
- **なぜ棄却された fit まで残すのか**: 相分率 ~0 の棄却が「残差を説明できない相」なのか
  「セルがずれて説明**できなかった**相」なのかは Rwp と相分率だけでは切れない。M10 の
  bic crossover も**採られなかった方向**が残っていないと検算できない。
- **容量**: 0.5-1.5 MB/フレーム (754 フレームで ~1 GB、双方向はその 2 倍前後)。
  容量が問題なら `save_gpx=false` — ただし**既定で止めない**。止めると上の検算が全部できなくなる。

## 手順

測定系によって手順 0-8 に加えて踏む節が変わる (**番号は振り直さない** — 3′/3″ は手順 3 に挟まる
枝であって、後続の手順 4-8 の番号はそのまま続く)。

| 測定系 | 踏む手順 |
|---|---|
| 高温/時間 in situ (温度変化・脱水等) | 手順 0-8 をそのまま |
| **電気化学 operando (充放電)** | 手順 0-8 に加え、**転移を含むなら 3′ が既定・echem 実測 (`.mpr`) があるなら 3″** を使う (3′ = `anchored_sequential`, 3″ = `charge_constraint`)。echem 同期 (`offset_s`/`interval_s`) は 3″ の (0) = `align_echem` で得る |

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
- **外部ソフト形式は先に変換する** (XND): 生の RIETAN-FP `.int` / Z-Code Igor TOF は
  `convert_pattern(input_path, out_path, input_format=...)` で `.xye`/FXYE にし、その `path` を
  `data_path` に渡す。Z-Code `.zDiffractometer` は `write_instrument_params(zdiff_path, out_instprm)`
  で `.instprm` にし、その `path` を上記 `instrument` spec の `path` に渡す (変換は前処理・提案のみ)。
- **装置ファイルが無い / 正しいか分からないときは `instrument` skill**。`create_instrument_params`
  で作り (`from_data_path` に系列の 1 フレームを渡せば波長・幾何・Kα2 の扱いが決まる)、
  `inspect_instrument_params` で検査してから `instrument` spec の `path` に渡す。
  **系列全体が同じ instprm を使う**ので、ここでの誤りは全フレームに波及する。
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
| `max_cyc` | 各段階の最大精密化サイクル数 (既定 12)。収束が遅い/振動する系で増やす |
| `recipe` | **段階解放レシピの全置換** (Issue #114)。`[{"label": str, "flags": {...}, "note": str}, ...]` の列。指定すると既定の `build_recipe` (7 段階) を**使わず**このレシピをそのまま使う (`analyze` skill の `auto_rietveld.stages` = 既定への**追加**とは違う — こちらは丸ごと差し替え)。operando 系列で不要な段階を省いた軽量レシピを注入する用途 (Issue #52)。省略 (既定) なら従来通り |
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
>
> `phase_id` の `frac_min` (新相採用の最小分率, 既定 0.02) も **Scale** 基準である。
> `check_phase_set` / `repair_frames` の分率系の閾値 (`min_amplitude` / `frac_delta`) も同じく
> Scale 基準である (各ツールの出力 `fraction_basis` がそれを明示する)。

### 2. 新相自動同定を設定する

`phase_id = {"elements": [既知+想定元素], "frac_min": 0.02, "top_k": 1}`。
これで系列途中の変化点/Rwp ジャンプで Materials Project から新相を探し、**受理基準 (相分率有意 ∧
Rwp 改善 ∧ 妥当性) を満たせば自動追加**する。`elements` を空にすると相追加を行わない。
`frac_min` は**新相の Scale の下限** (上の警告と同じ basis。wt% ではない)。

> **`min_identify_score` (既定 0.0) は下げるな。** 候補を試行精密化に回すために要する Dara
> スコアの下限で、負スコア = 「その相を入れると未説明強度がむしろ増える」= **残差を説明して
> いない**候補を Rietveld を回すまでもなく落とす。受理後の選択は「受理基準を満たす中で最小
> Rwp」だが Rwp は母数増で必ず下がるため、これが無いと**大分率で残差を舐める偽相が正解相に
> 勝つ** (実測 Ca-Te-O 系で Ca3TeO6/CaTe3O8 が正解の delta CaTeO3 に勝った)。
> 「相数を Rwp で決めない」規律 (手順 3′ の bic と同じ思想) を候補選択にも適用したもの。
> 足切りは ledger の `m9_phaseid_skipped` に候補名/スコア付きで残るので、**期待した相が
> 追加されない時はまずこれを読む** — スコアが負なら閾値ではなくモデル/セルの問題
> (`identify_pattern` で単体スコアを確認する)。`null` で無効化できるが、その場合は
> 偽相を自分で棄却する責任を負う。

> ### ⚠ `wavelength` — **Cu 以外の線源では必ず指定する**
>
> `phase_id.wavelength` (Å) は**異方セルプリアラインと候補再スコアの線源波長**であり、
> **既定は Cu Kα1 の 1.5406** である。放射光 (λ≈0.7-0.8 Å) や中性子の系列でこれを省くと、
> 同定側だけが Cu の波長で d↔2θ 変換を行う — **プリアライン後のセルも候補順位も系統的に誤る**。
>
> **例外も警告も出ない**。見えるのは「候補が当たらない」「新相を足しても Rwp が下がらない」
> だけなので、`instrument.radiation` を `xray_synchrotron` にしただけで安心しないこと
> (`instrument` は精密化側の設定であって、同定側の λ はこの `phase_id.wavelength` である)。
>
> ```json
> {"elements": ["K","Mn","Fe","C","N"], "wavelength": 0.800113, "frac_min": 0.02}
> ```

`phase_id` は `PhaseIdConfig` の**全フィールド**を受ける。既定で回して手応えが無いときに動かす
ツマミは以下 (未知キーは error dict が返るので綴りは黙って無視されない):

| キー | 既定 | いつ動かすか |
|---|---|---|
| `wavelength` | **1.5406 (Cu Kα1)** | **Cu 以外なら常に** (上記) |
| `elements` | `[]` (同定しない) | 既知相の構成元素 + 想定元素。**文字列のリスト** (`"CaTeO"` の裸文字列は拒否される) |
| `frac_min` | 0.02 | 新相採用の最小 **Scale** (wt% ではない — 上の basis 警告) |
| `refine_new_phase_cell` | `true` | 異方セルプリアラインの唯一の**切り札**。少数相フレームでは prealign が**支配相のピークにロック**して誤セルを返す (実測)。`appearances` の新相セルが明らかに不合理なら `false` にして素の CIF セルから精密化させる |
| `rerank_top_k` | 5 | 上位 K 候補を異方格子整合で再スコア (0 で無効)。DFT の軸別誤差で正解相が順位から落ちる系で増やす |
| `top_k` | 1 | 各変化点で試行精密化に回す候補数。候補が僅差で割れているとき増やす |
| `require_full_element_system` | `true` | 候補を**全元素系**の相に限定する化学ガード。副生成物 (二元分解相等) を許すときだけ `false` |
| `require_validity` | `false` | 受理に全相の物理妥当性を要求。**転移域では旧相のセルが急変して fail し新相を巻き添えで弾く**ので既定 off。安定域だけを解くなら `true` |
| `min_rwp_gain` | 0.01 | 受理に要する**相対** Rwp 改善 (1%)。junk 候補が通るなら上げる |
| `snr_trigger` | 20.0 | 残差 S/N の探索発火閾値。**データセット固有** — 純単相の残差でも未モデル分で ~17σ 出る系があった。常時発火するなら上げる (0 で無効) |
| `max_new_phases` | 0 (無制限) | 想定相数が厳密に既知で探索を打ち切りたいときだけ |
| `warm_start_known_phases` | `true` | 現行相を**精密化格子で**残差から先に減算してから新相を探す。少数新相の検出感度が上がる |
| `bic_acceptance` | `false` | 受理を bic で判定。**粉末では bic は相対 Rwp より寛容**で偽相も採るので通常は触らない (bic の実効は 3′ の区間比較側) |
| `min_identify_score` | **0.0** | **下げるな** (上の警告)。候補を試行に回すのに要する Dara スコアの下限。`null` で無効化できるが偽相を自分で棄却する責任を負う |
| `hull_cutoff_ev` | 0.1 | MP 安定性フィルタ (eV/atom)。`null` で無効 (準安定相を許す) |

**これらは「どのツールの出力から来るか」ではなく、あなたが判断層として置く policy 定数**である
(受理をどれだけ厳しくするか・探索をどれだけ広げるか)。例外は 2 つ: `elements` は化学
(既知相の CIF / `identify_phases` の結果) から、`wavelength` は**測定条件** (instprm/ビームライン
諸元 — `instrument.path` に渡す instprm と同じ線源のもの) から取る。

### 3. `sequential_rietveld` を呼ぶ

`warm_start_fractions=True` を検討する (既定 False)。相分率が初期値に張り付いて動かない
フレームを、直前フレームの分率で warm-start して是正する (#82)。
フレーム別 Rwp/格子/相分率・変化点・`appearances` (自動追加相) を読む。

自動追加相の Rwp が期待ほど下がらないときは `appearances[].evidence.prealign_basis` を見る
(異方セル補正 #20 の整合先)。`"residual"` = 既知相を引いた残差へ整合済 (正常)。`"skipped"` =
既知相を引けず補正を見送った = **DFT 格子のまま**なので、残差の説明力ではなく**相のセル誤差**を
第一容疑にする (MP(DFT) は軸別に数 % ずれ、Rietveld の収束半径 ~2% を超えると追えない)。
補正は必ず残差に対して行う — 生パターンへ整合させると FoM が支配相のピークに占められ、
少数相のセルはむしろ悪化する (実測 CaTeO3 delta: 最大軸誤差 3.4%→4.2%)。

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

**bic でも偽相が残るときは結合距離ゲートを足す** (FR-335)。bic は「相を増やせば残差が減る」ことは
罰するが、**増えた相の構造が物理的に有り得るか**は見ない。転移域で新相のセルが崩壊したまま僅差で
勝つ場合 (原子間距離が元素半径和を大きく割る) は `anchor_config` で結合妥当性を要求する:

```json
{"anchor_config": {"require_bond_validity": true, "bond_tol_lo": 0.7, "bond_tol_hi": 1.3}}
```

- **既定は OFF**。常時 ON にしない — 高温/転移で正当に歪んだ構造を偽陽性で弾く恐れがあるため、
  「`crossovers` の onset が物理的に早すぎる / 新相が転移前から湧く」と疑ったときだけ足す。
- 効いたかどうかは `crossovers[].bond_gate` で読む: `"moved"` = ゲートが bic 最良を棄却して
  crossover を動かした / `"kept"` = bic 最良が既に結合妥当 / `"no_valid_candidate"` = **僅差帯に
  結合妥当な経路が 1 つも無い** (= 相集合そのものが疑わしい。手順 5 の `check_phase_set` へ戻る)。
- pymatgen 不在の環境では自動 skip される (ゲートを課さず bic のまま)。

### 3″. 電気化学 operando では**クーロメトリーを独立測定として使う** (FR-318)

定電流充放電では反応電気量 Q(t) が電極中の可動アルカリ量の**独立した化学量測定**になる。
X 線単独の占有率精密化は Uiso 縮退で不安定なので、これを診断/制約に使う。

**手順**: (0) `offset_s`/`interval_s` は `align_echem` で XRD フレーム時刻と echem を同期して得る
(一定ケイデンス取得が operando では普通なので既定経路。個別フレームの POSIX 時刻列があるなら
`frame_epoch_s` で明示してもよい) → (1) `alkali_budget(mpr_path, active_mass_mg, formula_weight,
x0=…, offset_s=…, interval_s=…, n_frames=…)` で per-frame 目標表を作る → (2) その `targets` を
`charge_constraint` spec に入れて系列ツールへ渡す:

```json
{"charge_constraint": {
   "config": {"mobile_sites": [{"phase_name": "mono", "site_labels": ["K"], "multiplicities": [4.0]}],
              "z_formula": {"mono": 2.0}, "formula_weights": {"mono": 678.8},
              "mode": "diagnose"},
   "targets": "← alkali_budget の出力 targets をそのまま",
   "per_phase_content": {"mono": 1.944, "cubic": 1.0}}}
```

- **モードは `diagnose` 既定で始める** (拘束せず per-frame の `alkali_x_xrd` vs `alkali_x_echem`
  乖離を出力)。`alkali_residual` の系統的ドリフト = 不可逆容量/副反応の診断量 — これ自体が
  出版価値のある閉ループ検証図になる。
- **`lock_fractions` は明示 opt-in・あなたの判断事項**: 2 相では相分率和=1 と合わせ**相分率が
  完全決定され、XRD は分率に寄与しなくなる** (Rwp が一致度の検定量に変わる)。採用するのは
  「XRD 単独で分率が決まらない (計量縮退が深い) 系」に限る。
- **`soft` (ChemComp restraint) は使わない** — 現行 GSAS-II の headless 精密化では restraint
  penalty が最小二乗に取り込まれない (実測バグ; 自動で diagnose に縮退し警告が出る)。
- **`per_phase_content` (相ごと xᵢ) は単相アンカーの精密化結果から取る** (要件: 多相域では各相の
  x を単相域の値に固定して総量を拘束する)。`anchored_sequential` の `anchors[].alkali` を参照。
- **sign は自分で正しく選ぶ — データからは検証できない** (state は積算電荷由来のため電極
  取り違えの自動検出は原理的に不可能)。既定 +1 = 正極規約 (充電でアルカリ減)。回折側電極が
  負極なら sign=-1 (明示確認の警告が出る)。
- **`x_total` が null のフレーム (echem 範囲外) は拘束されない** (外挿値の捏造禁止 — 仕様)。
- Na/K ハイブリッド電解液では**電子数 = 総アルカリ挿入量 (Na+K 和)** しか拘束できない。
  `site_labels` に両元素のサイトを列挙し合算で扱う。Na/K 分配は XRD 側の精密化に任せる。
- **U/Uiso は精密化しない** (占有率と縮退し導出組成を汚染する)。初期 Uiso が妥当帯
  [1e-3, 0.05] Å² を外れると精密化前に警告が出る — 値を直すか根拠を持って帯を緩める。

**アンカー A/B (自動)**: `anchored_sequential` に `charge_constraint` を渡すと、単相アンカーで
制約有無の 2 精密化を自動比較し、ΔRwp が `anchor_ab_threshold` (既定 1.0%pt) を超えると
**不可逆容量疑いの警告 + x₀ 校正の提案** (`fr318_x0_calibration_proposal`, applied=False) が出る。
**提案≠適用** — x₀ を精密化値へ校正して再実行するかは**あなたがユーザーと合意して**決める。

- ⚠ **x₀ 校正の提案は、アンカーの占有率が実際に精密化された (esd 付き) ときのみ出る**。
  既定 (占有率グループ非宣言) では占有率は CIF 固定値なので `ab_check` の x は `x_model`
  (モデル値) と報告され、校正提案は出ない — 校正したいならアンカー相の PhaseSpec に
  `free_occupancy_labels` を設定して占有率を解放すること (Uiso は固定のまま)。

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

**⚠ `known_phases` を必ず渡す** — そのフレームに既に居る相を渡さないと、(1) 支配相の陰にいる
少数相は生パターンから拾えず候補ゼロになり、(2) 返る CIF が **DFT 格子のまま**になる
(異方セル補正 #20 は既知相を引いた残差に対してしか行えないため)。
`sequential_rietveld` の出力からそのまま組める (`initial_phases` に精密化格子を足すだけ):

```python
cells = result["frames"][i]["refined_cells"]          # 対象フレームの精密化格子
known = [dict(p, refined_cell=cells[p["phase_name"]])
         for p in initial_phases if p["phase_name"] in cells]
identify_and_add_phase(two_theta, intensity, elements, workdir,
                       known_phases=known, wavelength=<実波長>)
```

- **`wavelength` は実波長を渡す** (既定 Cu Kα1 = 1.5406 Å)。放射光/中性子で既定のままだと
  既知相のピーク位置が全て狂い、減算残差もセル補正も壊れる。
- **波長が判らない/存在しないときは `wavelength=None` を明示的に渡す (省略しない)**。
  該当するのは **TOF 中性子** (単一波長を持たない)・instprm が読めない・`Lam` 系のキーが無い場合。
  `None` は「不明」の意味で、ツールが波長依存の段を**両方**止める (既知相の残差減算 +
  異方 re-score) → `prealign_basis="skipped"`。**省略すると既定 Cu Kα1 が使われてしまう** —
  波長は hkl→2θ に直接効くので、λ=0.7996 の放射光を 1.5406 として扱うと 2θ が数度ずれ、
  照合許容 0.15° を大きく超えて**候補の順位付けそのものが壊れる**。
  代表波長を**でっち上げて渡さない** — 補正を諦める方が安全側。
- 返り値の **`prealign_basis`** を読む。`"residual"` = 既知相減算残差へ整合済 (正常)。
  **`"skipped"`** = 補正せず = **DFT 格子のまま**返した (既知相を渡していない / その CIF が
  読めなかった)。`n_known_phases_used` が 0 ならこちら。
- **`"skipped"` の候補で Rwp が下がらないときは、残差の説明力ではなく相の*セル誤差*を第一容疑に
  する**。MP(DFT) 格子は軸別に数 % ずれ (実測 CaTeO3 delta: c 軸 +3.42%)、Rietveld の収束半径
  (~2%) を超えると追えない。`known_phases` を付けて呼び直すか、実測 CIF を使う。
- 各候補の `refined_cell` が補正後の絶対格子 (未補正なら `null`)。

**既知相を渡せないからといって「補正なし」を生パターン整合で埋めることはしない** (ツール側も
そう作ってある): プリアラインの FoM は観測ピーク基準なので、少数相のセルを生パターンへ合わせると
支配相のピークに引っ張られ、出発点の DFT 格子より**悪化**する。実測 (CaTeO3 frame180, delta 2 相目):

| 整合先 | delta 最大軸誤差 | 二相 Rwp |
|---|---|---|
| 補正なし (DFT のまま) | 3.42 % | 32.24 |
| 生パターン | 4.21 % | 27.58 |
| **既知相減算残差** | **0.51 %** | **10.65** (実測 CIF は 10.70) |

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
**成果物の置き場所 (`gpx_dir`) も書く** — フレーム 1 枚ごとの fit がそこに残っており
(索引は `manifest.jsonl`)、報告した数字を人間が開いて確認できる唯一の経路である。

CSV で成果物を残す/他ツールへ渡すときは `write_sequential_csv(result, path)` を使う
(FR-504)。`result` は `sequential_rietveld`/`anchored_sequential` の戻り値をそのまま渡す。
出す列は M9 が実際に持つ値のみ (フレーム共通列 + 相ごとの a/b/c/a_esd/b_esd/c_esd/
scale/wt_frac/wt_frac_esd) + **`gpx_path`** (そのフレームの fit) — `scale` は Scale であって
重量分率ではない (上表と同じ注意)。CSV を渡された人が数字を疑ったときに**その数字を出した
精密化そのもの**へ辿れるようにするため、成果物パスを列に入れてある。
`get_trajectory` は使わない: M2 逐次 simulate 系の出力アクセサで、`session.trajectory` を
設定する ② ツールが無く実データ経路からは到達不能 (Issue #116)。

**定量値は Scale ではなく重量分率で報告する**。`phase_fractions` は HAP Scale の正規化値であり、
**単位胞質量が相間で異なると重量分率と乖離する**。

> 実測 (K₂Mn[Fe(CN)₆]): cubic 1103.4 amu vs tetra 517.8 amu → **同じ fit で 65.6 Scale% が
> 実際には 47.2 wt%** (この点で 1.39 倍の誤り)。「tetra ドーム頂点 65.6%」と報告した数値は誤りだった。
>
> **乖離の大きさはフレーム毎に違う** (実測: fr112 1.62 / fr120 1.48 / fr124 1.41 / fr126 1.39 倍)。
> 大きさを決めるのは相の**単位胞質量比** (ここでは 2.13 倍) と**そのフレームの分率**である。
> ⚠ **単一の換算係数は存在しない — Scale に係数を掛けて wt% を作ってはならない**。
> 必ず `phase_weight_fractions` を読むこと。

| キー | 何か | 使いどころ |
|---|---|---|
| `phase_fractions` | **Scale** の正規化値 | **同一 basis 内の相対比較のみ** (新相の有意性・張り付き検出)。**転移の追跡には使えない** — 転移推定は絶対レベル 0.50/0.10 の交差なので basis で答えが変わる (手順 7) |
| `phase_weight_fractions` | **重量 (質量) 分率** (GSAS `calcMassFracs` が精密化占有率込みで算出) | **出版値・定量相分析はこちら**。転移温度もこちら基準 (`parametric_fit` の既定) |
| `phase_weight_fraction_esd` | 重量分率の esd (共分散から伝播) | **出版には esd 必須** |
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
| **電気化学制約のモード選択** (diagnose/fix/lock_fractions) | ✅ diagnose の乖離出力・実行不能の縮退+警告は自律 | ✅ **lock_fractions の採用** (2相=分率が完全決定・XRD は分率に寄与しなくなる) と **占有率精密化スコープ** (可動イオンのみ/フレームワーク込み) はあなたの判断 |
| **x₀ 校正** (アンカー A/B の ΔRwp 超過時) | ✅ 提案 + ledger 記録のみ (`applied=False`) | ✅ **採用はあなた + ユーザー合意** (提案≠適用; 不可逆容量の解釈が要る) |

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
