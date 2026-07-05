# 相同定ベンチマーク (実測データ検証)

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
