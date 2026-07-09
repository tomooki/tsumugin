# パラメータ物理拘束付き分解能抽出 タスク概要

**要件**: [requirements.md](../../spec/constrained-resolution-extraction/requirements.md) /
**設計**: [architecture.md](../../design/constrained-resolution-extraction/architecture.md)

## TDD タスク

- [ ] **TASK-0001**: `HistogramSpec.profile_bounds` フィールド (+ to_dict/from_dict) 🔵
- [ ] **TASK-0002**: `engine._apply_profile_bounds` (set_Controls parmMin/parmMax, `:{i}:{key}`) +
  setup 配線 🔵
- [ ] **TASK-0003**: `resolution.NONNEG_PROFILE_BOUNDS` + `extract_instrument_profile(constrain_nonneg=True)`
  + `extract_instrument_profile_from_standard` 透過 🔵
- [ ] **TASK-0004**: エクスポート整合 + CeO2 gated 検証 (拘束で X,Y≥0・全域 FWHM 正・Rwp~9%) 🔵

## 依存
```
TASK-0001 → TASK-0002 → TASK-0003 → TASK-0004
```

## 検証
- numpy: profile_bounds 場/roundtrip・_apply_profile_bounds 変数名 (mock gpx)・constrain_nonneg→bounds。
- gated: CeO2 拘束抽出で U,W,X,Y≥0・Rwp<12%。T1〜T4 非回帰 (bounds None)。
