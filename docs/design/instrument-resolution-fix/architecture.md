# 装置分解能 抽出・固定 アーキテクチャ設計

**作成日**: 2026-07-09 / **要件**: [requirements.md](../../spec/instrument-resolution-fix/requirements.md)

**【凡例】** 🔵 確実 / 🟡 妥当な推測

## 概要 🔵
2 部構成: (A) **抽出** — 標準試料 (CeO2) を専用レシピで精密化し `InstrumentProfile` を得る。
(B) **固定** — `HistogramSpec.instrument_profile` 指定時、engine が値を seed し段階解放で装置プロファイルを
解放しない (試料広がりは size/mustrain)。既存ステージフラグを再利用し、engine の変更は最小。

## CeO2 実測に基づく設計判断 🔵
- **抽出レシピは size/mustrain を含めない**: 標準は試料広がりが無く、size/mustrain を解放すると U,V,W と
  競合して負の局所解 (Rwp 20%) に落ちる。背景→cell→U,V,W→X,Y→SH/L の順で **Rwp 9.6%** 到達を確認。
- **装置プロファイル一式を固定** (Gaussian のみでなく): シャープ放射光ピークは Lorentzian 支配で、
  X,Y を試料側で自由にすると過剰補償が残るため。

## コンポーネント
| モジュール | 役割 | 依存 |
|---|---|---|
| `model.InstrumentProfile` | 分解能関数の不変データ型 | numpy |
| `model.HistogramSpec.instrument_profile` | 固定指定 (省略時 None) | numpy |
| `resolution.build_resolution_recipe` | 抽出用ステージ合成 (既存フラグ) | numpy |
| `resolution.extract_instrument_profile` | 標準精密化→分解能抽出 (runner 注入可) | run_auto_rietveld 経由 (GSAS 遅延) |
| `engine._fixed_profile_flags` | per-hist 固定判定 | numpy |
| `engine._seed_instrument_profile` | 値を instprm へ書込 | GSAS |
| `engine._apply_stage` (改) | 固定 hist の U,V,W/X,Y/SH·L 解放を skip | GSAS |

## データフロー
```
[抽出] standard+structure → build_resolution_recipe → run_auto_rietveld(recipe=)
        → result.hist_profile[0] → InstrumentProfile(values, source_rwp, wavelength)

[固定] HistogramSpec(instrument_profile=IP) → run_auto_rietveld
        → seed IP.values into instprm (ループ前)
        → _apply_stage(..., fixed_profile): profile/lorentzian/asymmetry で fixed hist を skip
        → size_strain は張る (試料広がり)
```

## 非回帰 🔵
`instrument_profile` 既定 None → `_fixed_profile_flags` 全 False → `_apply_stage` は従来と完全一致。
T1〜T4 構造的非回帰。抽出は `run_auto_rietveld(recipe=)` の既存経路 (recipe 引数は既存)。

## 決定論・境界 🔵
InstrumentProfile/レシピ合成/固定判定/seed マッピングは numpy 決定論。extract は runner 注入で
GSAS 非依存テスト、実 CeO2 は gated。部分キー・キー欠落は skip (EDGE-001/002)。
