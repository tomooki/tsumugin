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

### 既知の限界 (スコアが 1.0 に達しない理由)
実データには背景・統計ノイズ・Cu Kα2 二重線が含まれるが、現状の `XRDCalculator` 生成ピークは
単一波長・背景なしのため、Kα2 サテライトや背景由来の未マッチピークが残り `unknown_phase_flag`
が立ちやすい。背景減算・Kα2 モデル化は将来の精度向上項目 (相対ランキングは実データで機能する)。

再現: `PYTHONIOENCODING=utf-8 uv run pytest tests/reference/test_realdata.py -m mp`
