# パラメータ物理拘束付き分解能抽出 アーキテクチャ設計

**作成日**: 2026-07-09 / **要件**: [requirements.md](../../spec/constrained-resolution-extraction/requirements.md)

**【凡例】** 🔵 確実 / 🟡 妥当な推測

## 概要 🔵
標準試料の分解能抽出で装置パラメータを非負拘束し、**転写可能 (全域 FWHM 正)** な分解能を得る。
GSAS `set_Controls("parmMin"/"parmMax", value, variable=":{h}:{key}")` を用いる (既存 `_bound_occupancy`
と同機構)。engine の変更は「拘束の適用」1 関数と setup での呼び出しのみ。

## 設計判断
- **DD-1 (拘束対象)**: U, W, X, Y ≥ 0。V は Caglioti 交差項で負が正常 (`H_G²` の下に凸を作る)、SH/L は
  非対称なので**拘束しない**。実測で U,W,X,Y≥0 が転写可能解を与えることを確認 🔵
- **DD-2 (既定 True)**: `extract_instrument_profile(constrain_nonneg=True)`。分解能は「転写して使う」ものなので
  物理拘束が既定であるべき。無拘束が必要なら明示 False 🔵
- **DD-3 (per-hist フィールド)**: `HistogramSpec.profile_bounds` を追加 (instrument_profile と同様)。
  汎用の per-hist 装置パラメータ境界。extract は `constrain_nonneg` から本フィールドを生成 🔵
- **DD-4 (変数名)**: `:{i}:{key}` (i = ヒストグラム追加順 index = GSAS hId)。実測 `:0:X` で拘束が効くことを確認 🔵

## コンポーネント
| モジュール | 役割 | 依存 |
|---|---|---|
| `model.HistogramSpec.profile_bounds` | per-hist 装置パラメータ境界 {key:(min,max)} (省略時 None) | numpy |
| `resolution.NONNEG_PROFILE_BOUNDS` | 非負拘束定数 {U,W,X,Y:(0,None)} | numpy |
| `resolution.extract_instrument_profile(constrain_nonneg=True)` | 非負 bounds を standard hist に付与 | numpy |
| `engine._apply_profile_bounds(gpx, g2hists, histograms)` | parmMin/parmMax を set_Controls 登録 | GSAS |

## データフロー
```
extract_instrument_profile(constrain_nonneg=True)
  → standard' = replace(standard, profile_bounds = NONNEG ∪ 既存)   # numpy
  → run_auto_rietveld([standard'], ...)
      → _apply_profile_bounds: 各 (key,(lo,hi)) に set_Controls(:i:key, parmMin=lo/parmMax=hi)  # GSAS
      → 拘束下で精密化 → hist_profile 抽出
```

## 非回帰 🔵
`profile_bounds` 既定 None → `_apply_profile_bounds` は何もしない → T1〜T4/joint 完全非回帰。
`extract_instrument_profile` の `constrain_nonneg` 既定 True は挙動を変えるが、extract は PR #39 で
新規追加され本番未使用 + 転写可能解が正しい既定なので許容 (無拘束は明示 False)。

## 決定論・境界 🔵
profile_bounds 場・NONNEG 定数・constrain_nonneg→bounds 写像・変数名組立は numpy 決定論。
実際の set_Controls は GSAS gated。非存在キー・parmMin 未対応は try で継続 (REQ-403/EDGE-001)。
