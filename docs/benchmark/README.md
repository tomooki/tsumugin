# 実測データベンチマーク (相同定 M6 + 自動 Rietveld 検証 M7)

M6 相同定パイプラインを **実測** 粉末回折データで検証する。データファイルは容量とライセンスの
都合で gitignore 対象 (`docs/benchmark/testdata/`)。取得すると `tests/reference/test_realdata.py`
の統合テストが自動で有効化される (未取得時は skip)。

## データ取得: GSAS-II チュートリアル PbSO4

GSAS-II tutorial *"Running a GSAS-II Refinement from the Command Line"* の PbSO4 実測 CuKα
ラボデータと構造 CIF を使う。

```bash
mkdir -p docs/benchmark/testdata
BASE="https://advancedphotonsource.github.io/GSAS-II-tutorials/PythonScript/data"
for f in PbSO4-Wyckoff.cif PBSO4.XRA INST_XRY.PRM; do
  curl -sSL -o "docs/benchmark/testdata/$f" "$BASE/$f"
done
```

| ファイル | 内容 |
|---|---|
| `PBSO4.XRA` | 実測 X線粉末パターン (Cu Kα, GSAS CONST/STD, 6001 点, 2θ 10–160°) |
| `PbSO4-Wyckoff.cif` | PbSO4 (anglesite, Pnma) の構造 (原子座標付き) |
| `INST_XRY.PRM` | 装置パラメータ (Cu Kα1=1.5405, Kα2=1.5443 Å) |

## 検証結果 (2026-07-04)

`docs/benchmark/testdata/` 配置後、以下を確認済み:

- **ローダー** (`load_gsas_powder`): `PBSO4.XRA` を `(two_theta, intensity)` に正しく読む
  (6001 点、2θ 10.00–160.00°、強度 67–15702 counts)。
- **CIF 自己整合** (`UserCIFProvider` → `identify_phases`): 実測パターンに対し PbSO4 CIF
  (Pnma, 364 反射) が最良マッチ (score ≈ 0.54)。
- **MP 判別** (`MPReferenceProvider` → `identify_phases`, Pb-S-O 系): 実測パターンに対し
  Materials Project の実候補群 (S 同素体・Pb5SO8 等) の中から **PbSO4 (mp-3472) が score ≈ 0.52
  で 1 位**に同定される。

## データ取得: Jana2020 Cookbook CandAt (Calcite + Aragonite 二相混合)

Jana2020 Cookbook の *Example 02.5.2 CandAt* — CaCO3 の 2 多形 (calcite R-3c + aragonite Pnma)
の混合を JANA2020 で簡易シミュレーションした X線パターン (Cu Kα1, capillary)。**同一組成・異構造の
多相同定** という難しいケース。

配置 (`docs/benchmark/testdata/jana/`):
| ファイル | 内容 | 取得元 |
|---|---|---|
| `CandAt.xy` | calcite + aragonite 混合パターン (2 列 XY, Cu Kα1, 10–120°, 7333 点) | Jana2020 Cookbook Example 02.5.2 Data.zip |
| `calcite.cif` | Calcite (CaCO3, R-3c, ICDD PDF-4) | 同上 |
| `aragonite_mp-4626.cif` | Aragonite (CaCO3, Pnma) | Materials Project mp-4626 (`MPRester().search(["Ca","C","O"])` → CifWriter) |

### 多相同定結果 (2026-07-05)

**元素情報 (Ca, C, O) のみから全 MP 候補 (169 相) を経て calcite + aragonite を同定**
(Dara スコア + Dara 事前フィルタ + 背景減算):

| 仮説 | Rwp |
|---|---|
| **calcite (R-3c) + aragonite (Pnma) — 2 相** | **94.4** ← 最良 |
| calcite (単相) | 96.6 |
| aragonite (単相) | 97.7 |

169 相の全 MP 候補を Dara スコア上位 8 相に絞る (`prefilter_top_k=8`) ことで炭素・シュウ酸塩等の
無関係相を除外し、木探索が 2 多形混合を正しく組み上げる。**信頼構造 (実験 CIF) に絞らなくても、
元素情報だけから多相同定が成立する** (キャッシュ済み MP 候補でのオフライン再現テストあり)。

**背景減算が必須**: CandAt.xy は構造化ベースラインを持ち、無処理では `find_peaks` が 735 本の偽ピークを
拾い被覆率が希釈される。SNIP 背景減算で 27 本の実ピークに絞られ同定が成立する。Rwp が高いのは
MP の DFT 緩和格子とのピーク位置ずれ (Issue #11) が残るため (ランキングは正しい)。

再現: `pytest tests/reference/test_realdata.py::test_element_only_multiphase_from_full_mp_candidates`
(キャッシュ利用でネットワーク/pymatgen 不要)

## Dara 式ピークマッチングスコア (2026-07-05)

Fei et al. *"Dara: Automated Multiple-Hypothesis Phase Identification"* (Chem. Mater. 2026,
38, 1364) の式(1) を実装 (`reference.scoring.dara_peak_score`)、`identify_phases` の既定スコアに採用:

`Score = (I_matched + I_wrong_intensity − 0.1·I_missing − 0.5·I_extra) / I_exp`

旧 `match_score` (候補ピーク数で正規化 → peak-rich 相を希釈) と異なり、**実測強度で正規化**して
候補のピーク数では罰せず、余剰計算ピーク (extra) のみ強く罰する (−0.5)。これで peak-rich な
正解相が不利になる問題が解消し、**判別マージンが大幅改善**:

| 実測 PbSO4 全 MP Pb-S-O | 1 位 | 2 位以降との差 |
|---|---|---|
| 旧 coverage | PbSO4 ✓ | +0.010 (S 同素体が僅差) |
| **Dara (式1)** | **PbSO4 ✓** | **+0.36** (誤相は extra 罰で負スコア) |

Dara スコアは間違った相 (硫黄・PbS 等) が予測する未観測ピークを extra として強く罰するため、
正解相に明確なリードを与える。多相同定の候補事前フィルタ (`prefilter_top_k`) にも使う。

## 背景減算 + Kα2 モデル化の効果 (2026-07-05)

実データには背景・統計ノイズ・Cu Kα2 二重線が含まれる。`identify_phases` / `identify_phase_mixtures`
にオプトインの前処理を追加した:
- `subtract_bg=True` — SNIP 法で遅変化背景を減算 (`reference.background`)。
- `kalpha2=KAlpha2()` — 参照ピークに Kα2 サテライト (高角側・半強度) を付加 (`reference.kalpha`)。

### 単相 (UserCIF 自己整合) — 未知相フラグの改善

| 前処理 | score | unknown_phase_flag | 未マッチ観測 |
|---|---|---|---|
| baseline | 0.541 | **True (誤検出)** | 7 |
| 背景のみ | 0.544 | True | 3 |
| Kα2 のみ | 0.539 | **False** ✓ | **0** |
| 背景 + Kα2 | 0.532 | **False** ✓ | **0** |

Kα2 モデルで 7 本の未マッチ観測 (= Kα2 二重線の片割れ) が解消し、**単相サンプルの
「未知相あり」誤検出が正される**。

### 多相判別 (MP Pb-S-O 実候補群) — 検出感度との相互作用

| 前処理 | 1位 | PbSO4 リード margin |
|---|---|---|
| baseline | PbSO4 ✓ | +0.0125 |
| 背景のみ | PbSO4 ✓ | +0.0098 |
| Kα2 のみ | S ✗ | +0.0024 |
| 背景 + Kα2 | S ✗ | +0.0020 |
| 背景 + Kα2 + 高感度 (`min_peak_height_frac=0.02`) | **PbSO4 ✓** | **+0.0193** |

**重要な相互作用**: Kα2 は参照ピークを倍増させるが、既定検出閾値 (0.05) では観測側の弱い Kα2
ピークが拾われず、サテライトが「余剰計算ピーク」化して `match_score` のピーク数が多い相
(PbSO4=364 反射) を不利にする → 硫黄 (少ピーク) に逆転され得る。**検出閾値を下げて
(`min_peak_height_frac=0.02`) 観測 Kα2 も拾うと解消し、baseline より良いマージンになる**。

### 推奨と限界
- Kα2 モデルは単相の未知相判定を確実に改善する。多相判別で使うときは検出感度
  (`min_peak_height_frac`) を下げて観測 Kα2 も拾うこと。
- `match_score` はピーク数の大きく異なる相間で頑健でない (peak-rich 相が不利)。
  Rachinger 補正 (観測側 Kα2 除去) や peak-count 正規化した類似度は将来の改善項目。

再現: `PYTHONIOENCODING=utf-8 uv run pytest tests/reference/test_realdata.py -m mp`

## データ取得: M7 GSAS-II チュートリアル (Rietveld refinement セクション T1–T4)

M7 (自動 Rietveld 解析の実データ検証) の対象データ。出典は GSAS-II 公式チュートリアル
リポジトリ (https://github.com/AdvancedPhotonSource/GSAS-II-tutorials)。目標値・合格基準・
レシピは `docs/tasks/m7-real-data-validation/PLAN.md` §2/§4。

```bash
BASE="https://raw.githubusercontent.com/AdvancedPhotonSource/GSAS-II-tutorials/main"
D=docs/benchmark/testdata/m7
mkdir -p $D/labdata $D/cwneutron $D/cwcombined $D/tofcw
for f in FAP.XRA INST_XRY.PRM FAP.EXP; do curl -sfSL -o "$D/labdata/$f" "$BASE/LabData/data/$f"; done
for f in garnet.raw inst_d1a.prm; do curl -sfSL -o "$D/cwneutron/$f" "$BASE/CWNeutron/data/$f"; done
for f in PBSO4.XRA PBSO4.CWN INST_XRY.PRM inst_d1a.prm; do curl -sfSL -o "$D/cwcombined/$f" "$BASE/CWCombined/data/$f"; done
TOF="TOF-CW%20Joint%20Refinement/data"
for f in 11BM_NAC.fxye 11bm_gsas.prm PG3_22048.gsa PG3_22049.gsa POWGEN_1066.instprm \
         POWGEN_2665.instprm NAC.cif CaF2.cif NAC-2015A.EXP; do
  curl -sfSL -o "$D/tofcw/$f" "$BASE/$TOF/$f"; done
```

| ディレクトリ | Tutorial | 内容 | チュートリアル最終値 |
|---|---|---|---|
| `m7/labdata/` | LabData | fluoroapatite 実験室 X 線 CuKα (GSAS STD) + PRM + EXP | Rwp 10.38% / GOF 3.44 |
| `m7/cwneutron/` | CWNeutron | Y-Fe garnet CW 中性子 D1a λ=1.909Å + PRM | Rwp 5.18% / GOF 3.79 |
| `m7/cwcombined/` | CWCombined | PbSO4 X 線 + CW 中性子 joint + 両 PRM | 合計 wR 6.71% / GOF 2.27 |
| `m7/tofcw/` | TOF-CW Joint | NAC+CaF2: 11BM (.fxye) + POWGEN TOF×2 (.gsa) + instprm×3 + CIF×2 + EXP | Rw 6.83% (75 params) |

- PbSO4 の CIF は既存 `testdata/PbSO4-Wyckoff.cif` を使用。
- fluoroapatite / garnet の CIF は Phase A/B で MP または COD から取得して固定する。

## 較正ベンチ (§12-5, Issue #72 前半)

reliability diagram / ECE で `bic` と `nested` の確率較正を **別々に** 評価する (仕様 §12-5)。
既存の較正評価ユーティリティ `tsumugin.nested.calibration.calibrate_by_backend` は「予測確率+正解
フラグ」のサンプル列から reliability ビン表と ECE を返す評価専用関数であり、温度較正 (T のフィット)
自体は行わない。ベンチスクリプト `docs/benchmark/calibration/run_calibration_bench.py` が
(1) 合成の多仮説選択問題を決定論的に生成し、(2) bic/nested それぞれの predicted probability を得て、
(3) 較正前 (T=1) と in-sample ECE 最小化でフィットした T (較正後) の双方を `calibrate_by_backend` で
評価する。

### 実行

```bash
uv run python docs/benchmark/calibration/run_calibration_bench.py
# オプション: 問題数・乱数種・ビン数・出力先を指定
uv run python docs/benchmark/calibration/run_calibration_bench.py --n-problems 200 --seed 0 --n-bins 10
```

乱数は `np.random.default_rng(seed)` で固定した決定論実行 (NFR-102)。GSAS-II 不要・numpy コアのみ
(`SimulatedBackend` で合成データを生成)。既定 N=200 で約 4 分 (このリポジトリの実行環境実測)。

### ベンチ設計の要約

各問題は「主相 (常に存在) + 微弱な副相 (存在するか未知)」を真の構造として合成回折パターンを作り、
真仮説 (主相+副相) と偽仮説 (副相を見落とした主相単独) を候補にする 2〜4 択の仮説選択問題。副相の
強さ (難易度) を対数一様に振ると BIC の `n_params·ln(n_obs)` 罰則が離散的に効くため予測確率が
0/1 近傍に偏ってしまうことが実測でわかった。そこで各問題の「予測確率がちょうど 0.5 になる副相強度
(決定境界)」を二分探索で特定し、その境界からの対数正規オフセットで難易度を選ぶ (境界を直接ねらう
のは中立的な基準点探索であり正解を強制しない — オフセット次第で真仮説が勝つことも負けることも
自然に起こる)。bic の決定境界と nested (Laplace) の決定境界は一致しない (Laplace の Occam 因子
`-0.5·ln|H|` は BIC の罰則よりずっと弱く効くため nested の方が僅かな副相でも存在を確信しやすい)
ため、問題の一部 (既定 30%) は nested 自身の境界を中心にし、両系列とも予測確率が 0.5〜1.0 に
分布するようにしている。

nested 系列は `nested.arbitration.arbitrate` と同じ 2 段構え (bic 一次 → ΔBIC<10 の僅差競合のみ
再裁定) を `nested.laplace.LaplaceBackend.score_problem` で直接評価する形で再現する。本環境には
実サンプラ dynesty が導入済みだが、較正ベンチは「決定論・数分以内の実行」を優先し既定では起動しない
— Laplace 経路 (`tsumugin.nested.laplace`) が既定 (仕様上も nested 裁定は Laplace 代替が既定路線、
実 dynesty はコスト次第のオプション)。実 dynesty で裁定したい場合は
`tsumugin.nested.sampler.NestedBackend` + `tsumugin.nested.arbitration.arbitrate(nested=...)` を
直接使うこと。

温度較正は `rank()`/`arbitrate()` と同じ `softmax(-value/(2T))` を用い、T は top-1 の判定
(argmax) を変えない (順序不変) ため top-1 確率の大きさのみを対象に、reliability diagram 上の ECE
を直接最小化する T をグリッドサーチで求める (in-sample 較正。T=1 も探索点に含むため較正後 ECE は
較正前 ECE を超えない)。

### 実測結果 (2026-07-14, N=200, seed=0)

| series | backend | temperature | ECE | n | probability_semantics |
|---|---|---|---|---|---|
| bic_raw | bic | 1.00 | **0.410** | 200 | BIC 近似事後確率 (softmax(-BIC/2)) |
| bic_calibrated | bic | 35.13 | **0.100** | 200 | BIC 近似事後確率 (softmax(-BIC/2)) |
| nested_raw | nested | 1.00 | **0.156** | 200 | logZ ベース事後確率 (softmax(-(-logZ))) |
| nested_calibrated | nested | 3.98 | **0.046** | 200 | logZ ベース事後確率 (softmax(-(-logZ))) |

生データ: `docs/benchmark/calibration/results/{summary,reliability_bins,meta}.csv`
(`n_close_competitor_problems=167/200` = nested 系列で実際に Laplace 再評価が発動した問題数)。

reliability 表の要約 (`reliability_bins.csv` より抜粋、較正前):

- **bic_raw**: 予測確率が 0.5〜1.0 の 5 ビンに分布 (0.5〜0.9 帯は概ね妥当な較正 — 例
  [0.7,0.8) は予測 0.74 に対し実正解率 0.68)。ただし最高確信ビン [0.9,1.0) (75/200 件, 平均予測
  0.986) の実正解率はわずか **0.027** — BIC が「副相なし」を確信しても副相が実在するケースを
  大幅に見誤る、明確な過信を示す。
- **nested_raw**: 200/200 件が [0.9,1.0) の 1 ビンに集中 (平均予測 0.991, 実正解率 0.835)。bic
  ほど極端ではないが依然過信気味。
- 較正後はいずれも ECE が大きく改善し (bic: 0.41→0.10, nested: 0.16→0.046)、bic_calibrated は
  [0.4,0.6) 帯に、nested_calibrated は [0.6,0.9) 帯に予測確率が集約され実正解率とよく一致する。

### 確率の意味の注記

`bic` と `nested` は評価している対象が異なる (`probability_semantics`, `calibrate_by_backend` が
返す説明文をそのまま採用):

- **bic**: `softmax(-BIC/2)` — BIC (chi2 + n_params·ln(n_obs)) を用いた近似事後確率。サンプル数
  n_obs が大きいほど罰則が強く効く漸近近似 (Schwarz 1978)。
- **nested**: `softmax(-(-logZ))` — 周辺尤度 (evidence) の対数 logZ に基づく事後確率。本ベンチは
  実 nested sampling (dynesty) でなく Laplace 近似 (`logZ_laplace ≈ logL_map + (k/2)ln(2π) −
  (1/2)ln|H|`) で `-logZ` を近似する。BIC は n→∞ での Laplace evidence の粗い漸近近似 (`-2 logZ
  ≈ BIC + O(1)`) にあたるため、両者は理論上関連するが本ベンチの有限 n_obs・非漸近領域では大きく
  異なる値・異なる較正挙動を示す — 上記の実測 ECE 差 (bic 過信がより深刻) はその現れ。

### 決定論スモークテスト

`tests/test_calibration_bench.py` が縮小版 (N=20) で決定論 (同一 seed で 2 回実行しビット同一) と
「較正後 ECE ≤ 較正前 ECE」を検証する (GSAS-II 不要・数秒)。
