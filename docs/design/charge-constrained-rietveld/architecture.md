# 電気化学制約付き operando Rietveld — 設計 (FR-318)

3 層構成 (M8 準拠): ① 決定論コア / ② MCP / ③ skill。

## データフロー

```
MPR ─parse_mpr→ EchemCurve ─align_frames→ FramePoint(charge_mah, state, in_span)
                                              │
              operando/coulometry.py          ▼
  electron_count(Q, m, M, z) ──→ alkali_targets(points, x0, sign) → per-frame x_total(t)
                                              │
                                              ▼ (TargetComposition として FrameSpec に搭載)
  insitu runner ─→ run_auto_rietveld(…, initial_occupancies / chem_comp_restraints /
                                        content_constraint)   ← モードで分岐
                                              │
                                              ▼
  FrameRietveldResult(alkali_content_*, x_echem, x_xrd, coulometric_residual, …)
```

## ① コア設計

### `operando/coulometry.py` (新規, numpy-only)

- `electron_count(charge_mah, active_mass_mg, formula_weight, z=1) -> float | ndarray`
  n_e = Q/m × M / F_MAH (F_MAH = 26801.5 mAh/mol)。
- `alkali_targets(frame_points, x0, *, sign, x0_source, esd) -> tuple[FrameTarget, ...]`
  x_total(t) = x0 − sign·n_e(t)。in_span=False → target なし。state と sign の整合検証
  (充電区間で x が増えていたら警告)。
- `MobileSiteSpec(phase, site_labels, multiplicity)` — **site_labels は複数元素対応**
  (同一サイトの Na/K 等を合算)。`content_from_occupancies(occ_map, sites, z_formula)` と
  逆写像 `occupancies_for_content` (等比配分)。
- `x_xrd_from_weight_fractions(weights, formula_weights, x_per_phase, weight_esd=None)`
  φᵢᵐᵒˡ = (wᵢ/FWᵢ)/Σ(wⱼ/FWⱼ)。**FW で割る (セル質量ではない — Z 二重計上禁止)**。
  esd は ∂x/∂wᵢ の一次伝播。
- `feasibility(x_total, x_per_phase, tol)` → in-range / degenerate (xᵢ 等値) / infeasible。

### `autorietveld` 拡張

| 機構 | 実装 | 鋳型 |
|---|---|---|
| 占有率シーダー | `run_auto_rietveld(initial_occupancies={phase:{label:val}})` — 原子行 col cx+3 に設定。fix では refine フラグも off (sum=1 制約と衝突させない) | `_apply_initial_fractions` (931-966) |
| soft 拘束 | `_apply_chem_comp_restraints`: `gpx.data['Restraints'][phase]['ChemComp']['Sites']` へ `[ranIds, factors, value, esd]` 直接注入 (ranId = col cia+8)。scriptable 未露出のため gpx.data 直接 — revert 生存は Restraints 共通性質 | `_apply_bond_restraints` (644-683) |
| hard 拘束 | `content_constraint`: `add_EqnConstr(0.0, [Scaleᵢ], [Zᵢ(xᵢ−x_total)])` — Scale について線形 (モル量 ∝ Scale·Z)。相 id 混在 EqnConstr は分率和=1 (640) が前例 | `_setup_constraints` |
| atom_occupancy 配線 | `_extract_state` 由来の値をラベルキーで `AutoRietveldResult.atom_occupancy/atom_uiso` に格納 (既存フィールド、未配線だった) + 共分散から esd | 構築部 1280 |
| 初期 Uiso 警告 | 精密化前に妥当帯 [1e-3, 0.05] Å² 検査 + 「占有率と Uiso 同時精密化」警告 | validity.py |
| mult/Z 照合 | GSAS 原子行 (mult = col cs+1) / General から自動抽出し spec と照合 | — |

### モード意味論 (4 値, 既定 diagnose)

| mode | 単相 | 多相 |
|---|---|---|
| diagnose | 占有率自由 + 乖離出力 | Scale 自由・xᵢ アンカー凍結・乖離出力 |
| soft | ChemComp (単相はネイティブ表現可) | 相間 soft 非ネイティブ → diagnose 縮退+警告 |
| fix | 占有率を x₀ に凍結 | xᵢ をアンカー値に凍結・Scale 自由 |
| lock_fractions | n/a | EqnConstr で分率拘束 (2相=完全決定を警告) |

### スレッディング (第5引数を作らない)

per-frame 値は **`FrameSpec.target_composition: TargetComposition | None`** に載せる。
runner は FrameSpec を受け取るため、`_warmstart.call_runner` の拡張も bare `runner(...)` 3 箇所
(engine.py:396,420 / anchor/extract.py:65) の追配線も**不要** (Issue #96 型の罠を構造的に回避)。
系列レベル定数 (sites, Z, FW, sign, mode) は `SequentialConfig.charge_constraint:
ChargeConstraintConfig` + `make_gsas_runner` closure。

`TargetComposition` (frozen): `total: float / per_phase: Mapping[str,float] / mode: str /
esd: float`。to_dict/from_dict (② JSON 境界を跨ぐ)。

### アンカー A/B (REQ-318-006)

`anchor/extract.py::_refine_anchor` を拡張: charge_constraint 有効時、
(A) 制約なし / (B) soft 制約 の 2 回精密化 → ΔRwp > 閾値で警告 +
`x0_calibration_proposal` payload (精密化 x, 現 x₀, 差)。適用はしない。

## ② MCP

- `alkali_budget(mpr_path, active_mass_mg, formula_weight, *, z=1, x0, sign, offset_s,
  interval_s, n_frames | frame_epoch_s, reason)` → per-frame `{frame, time_h, voltage_v,
  charge_mah, state, in_span, n_e, x_total}` 表。`align_echem` と同居 (echem_tools.py)。
- `sequential_rietveld` / `anchored_sequential` に `charge_constraint` spec (JSON):
  `{targets: {frame_index: {total, esd}}, per_phase_content: {phase: x_i}, mode,
  mobile_sites: {phase: {labels, multiplicity}}, z_formula: {phase: Z}, formula_weights,
  anchor_ab_threshold}`。targets は **alkali_budget の出力から作れる** (§4.5 到達可能性)。
- `seq_result_to_dict` が新フィールドを出力。

## ③ skill (第3層判断の明示)

権限境界表に追加する判断:
- mode 選択 (diagnose 既定 / lock は「XRD が相分率に寄与しなくなる」旨を理解した上での明示判断)
- 占有率精密化スコープ (可動イオンのみ / フレームワーク込み) — REQ-318-002
- x₀ 校正の採用 (A/B 警告後) — 提案≠適用
- sign の確認 (state 照合警告が出たら停止して確認)

## 設計上の三大リスク

1. **FW 除算** (x_XRD 換算) — 非対称 FW/Z テストでピン留め (AC-2)。
2. **Na/K 複数元素サイト** — MobileSiteSpec を初日から合算設計。
3. **2相 lock_fractions の自由度ゼロ** — 既定にしない。警告必須。
