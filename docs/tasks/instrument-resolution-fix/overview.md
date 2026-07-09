# 装置分解能 抽出・固定 タスク概要

**要件**: [requirements.md](../../spec/instrument-resolution-fix/requirements.md) /
**設計**: [architecture.md](../../design/instrument-resolution-fix/architecture.md)

## TDD タスク

- [ ] **TASK-0001**: `model.InstrumentProfile` + `HistogramSpec.instrument_profile` フィールド 🔵
- [ ] **TASK-0002**: `resolution.build_resolution_recipe` (numpy) + `extract_instrument_profile`
  (runner 注入・hist_profile 抽出) 🔵
- [ ] **TASK-0003**: `engine._fixed_profile_flags` + `_seed_instrument_profile` + `_apply_stage`
  固定 skip 配線 + run_auto_rietveld 統合 🔵
- [ ] **TASK-0004**: エクスポート + CeO2 gated 抽出検証 + 固定モード非回帰 🔵

## 依存
```
TASK-0001 → TASK-0002 → TASK-0003 → TASK-0004
```

## 検証
- numpy 決定論: InstrumentProfile・レシピ合成・固定判定・extract(stub runner)・skip ロジック。
- gated: CeO2 抽出で Rwp ~9.6% + 妥当な U,V,W,X,Y。固定モードで T1 非回帰。
