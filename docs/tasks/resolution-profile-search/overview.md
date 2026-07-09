# 分解能プロファイル物理候補探索 タスク概要

**要件**: [requirements.md](../../spec/resolution-profile-search/requirements.md) /
**設計**: [architecture.md](../../design/resolution-profile-search/architecture.md)

## TDD タスク

- [ ] **TASK-0001**: `profile_total_fwhm` / `profile_fwhm_min` (GSAS getFWHM 準拠 numpy) 🔵
- [ ] **TASK-0002**: `candidate_profiles` (アンカー周辺の grid 候補生成, numpy) 🔵
- [ ] **TASK-0003**: `search_instrument_profile` (アンカー→候補→FWHM 正フィルタ→固定評価→最良,
  runner/optimizer 注入) 🔵
- [ ] **TASK-0004**: `extract_instrument_profile_from_standard(search=)` 配線 + エクスポート +
  CeO2 gated 検証 (物理最良解・全域 FWHM 正) 🔵

## 依存
```
TASK-0001 → TASK-0002 → TASK-0003 → TASK-0004
```

## 検証
- numpy: getFWHM 港 (既知値)・候補生成の決定論/件数・search (stub runner で最良選定/物理フィルタ/フォールバック)。
- gated: CeO2 探索で総 FWHM 正の物理最良解・Rwp 妥当。T1〜T4 非回帰。
