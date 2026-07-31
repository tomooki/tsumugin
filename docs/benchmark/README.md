# 実測データベンチマーク (相同定 M6 + 自動 Rietveld 検証 M7)

> **公開リポジトリの規約 — 成果物を足す前に読むこと**
>
> 1. `docs/benchmark/` 直下の各エントリは **由来を `provenance.toml` に宣言する**
>    (`public` / `synthetic` / `private`)。宣言が無いと
>    `tests/test_docs_provenance.py` が落ちる。
> 2. **未公開データの測定値は追跡しない**。出力先 `*/results/` は既定で gitignore。
>    公開したい成果物だけ `git add -f` で明示的に上げる。
> 3. **設計文書 (`docs/design/`・`docs/spec/`) に測定値の表を置かない**。根拠として 1 値を
>    引くのは可だが、一覧はここに置いてリンクする。混ざると由来を追えなくなる。
>
> v0.1 公開時、未公開データの Rwp・占有率が public になった (`.gitignore` が拡張子スコープ
> だったため csv/log が漏れた)。生データは守れていたので気づきにくかった。

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

Jana2020 Cookbook の *Example 02.5.2 CandAt* — CaCO3 の 2 多形 (calcite R-3c + aragonite; 真の空間群は Pmcn だが同梱 CIF は P1)
の混合を JANA2020 で簡易シミュレーションした X線パターン (Cu Kα1, capillary)。**同一組成・異構造の
多相同定** という難しいケース。

配置 (`docs/benchmark/testdata/jana/`):
| ファイル | 内容 | 取得元 |
|---|---|---|
| `CandAt.xy` | calcite + aragonite 混合パターン (2 列 XY, Cu Kα1, 10–120°, 7333 点) | Jana2020 Cookbook Example 02.5.2 Data.zip |
| `calcite.cif` | Calcite (CaCO3, R-3c, ICDD PDF-4) | 同上 |
| `aragonite_mp-4626.cif` | Aragonite (CaCO3)。⚠ **ファイルは `P 1` (対称操作 `x,y,z` のみ・40 原子)** — 相同定には十分だが **Rietveld のベンチマークには使えない** (60 座標が無拘束に なり、~27 本のピークしかない模擬パターン上で手順ごとに別の対称性破れ最小点へ落ちる)。使うなら対称性付きで再生成すること | Materials Project mp-4626 (`MPRester().search(["Ca","C","O"])` → CifWriter, symprec なし) |

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

## 確率較正ベンチ (仕様 §12-5, Issue #72 前半)

`bic` / `nested` の**予測確率がどれだけ当たっているか** (reliability / ECE) を評価する。合成の
多仮説選択問題 (主相 + 微弱な副相を見落とす偽仮説) を決定論生成し、温度 T=1 (較正前) と
in-sample ECE 最小化でフィットした T (較正後) を `nested.calibration.calibrate_by_backend` で比較する。

```bash
uv run python -u docs/benchmark/calibration/run_calibration_bench.py
```

GSAS-II 非依存 (numpy コアのみ)・**乱数種固定でビット同一** (NFR-102)。スモークテストは
`tests/test_calibration_bench.py` (高速ティア)。出力は `docs/benchmark/calibration/results/`
(`summary.csv` / `meta.csv` / `reliability_bins.csv`)。

### 較正結果 (200 問題)

| 系列 | backend | 温度 T | ECE |
|---|---|---|---|
| bic_raw | bic | 1.000 | 0.4097 |
| bic_calibrated | bic | 35.130 | 0.1005 |
| nested_raw | nested | 1.000 | 0.1563 |
| nested_calibrated | nested | 3.985 | 0.0461 |

- **温度較正は両 backend で ECE を大きく下げる** (bic 0.410→0.100、nested 0.156→0.046)。
- **素の bic 確率は極端に過信** (T≈35 を要する)。`softmax(-BIC/2)` は僅差でも確率を 0/1 へ張り付か
  せるため、**未較正の bic 確率をそのまま「この相である確率」として読んではいけない** (FR-124 が
  backend 間で確率の意味が違うことのレポート明記を求める理由)。
- nested は素でも bic より較正が良い (T≈4)。ただし v1 の evidence が定数尤度サロゲートである
  制約 (Issue #76) は本ベンチの外にあり、**ここで測っているのは確率の較正であって裁定力ではない**。

## joint 占有率ベンチ (仕様 §12-6, Issue #72 後半)

X線単独 vs SXRD+ND joint で占有率の **±σ** を比較し、中性子コントラストによる占有率決定精度の
向上を定量する。併せて FR-244 (`joint.contrast.recommend_occupancy_release`) が joint データで
のみ発火することを確認する。

```bash
uv run python -u docs/benchmark/joint/run_joint_occupancy_bench.py
```

入力は `docs/benchmark/testdata/xnd/` (**未公開の実験データ**・ローカル限定・非再配布)。実 GSAS-II
精密化 (~405 s) を伴うため **gated テスト化していない** — 実行は手動。

> **実測値は本リポジトリに載せていない** (未公開データのため)。スクリプトを手元で実行すると
> `docs/benchmark/joint/results/` に生成される (同ディレクトリは gitignore 対象)。

設計上の知見 (データに依らず成立する部分):

- **joint は占有率の σ を縮める**。中性子の Na/O コントラスト (b: Na 3.63 / O 5.80 fm) は
  X線 (Z: Na 11 / O 8) では分離できない Na/O 分割を決める — FR-240/244 の設計意図どおり。
- **joint の Rwp が単独より高くても劣化ではない**。中性子ヒストグラムを加えて同じ構造で同時に
  説明しているので、比較対象として意味を持つのは Rwp ではなく σ と GOF。
- **2 モードの bic は比較してはならない** — 観測データ自体が違う (n_obs が異なる)。
- **FR-244 は probe 種別が 1 種のとき発火しない** (提案のみ・非破壊)。
