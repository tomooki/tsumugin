# refine_loop 第2層b 診断オートトライ拡張 — ギャップ分析 (Kairo 入力)

`docs/reference/serious-refinement-flow.md` の3層フローと、現行 `tsumugin.refine_loop` 実装を
突き合わせ、**追加する機能と場所**を整理する。本ドキュメントは Kairo (requirements→design→tasks→
implement) の設計入力。

## 核心原理 (不変)

自動解析のエンジンは「**可能性があればトライ → ダメなら revert**」。現行 `orchestrator._accept`
(Rwp 改善 ∧ validity 維持) + 棄却時 revert が既にこれを体現している。**追加は第2層b(診断シグナル
とトライ候補)の拡張に集約**され、accept/revert エンジン自体は変えない。

## 3層 ↔ refine_loop 構造対応

| 層 | 内容 | 担当 | 状態 |
|---|---|---|---|
| 第1層 Default | S0–S6 普遍段階列 | `build_recipe` (runner 経由) | ✅ 委譲済 |
| 第2層a 条件分岐 | geometry/温度差/多相/混合占有/CW除外/Lorentzian | `build_recipe` アダプタ | ✅ 委譲済 |
| **第2層b 診断オートトライ** | §6 の8シグナル (try→observe→revert) | `diagnostics`+SafeAction+policy+`_accept` | ⚠ **2/8 のみ** |
| 第3層 Judgment | BIC/停止/妥当性/新相 | ModelAction→`open_proposals`; `PolicyBudget` | ⚠ 部分 |

## 表B: §6 診断オートトライ — ギャップと追加場所

| §6 シグナル | 必要な feature / action | 現状 | 追加場所 |
|---|---|---|---|
| 背景 wiggle 過剰 → 項数を戻す | overfit 検知(極値数) + bg 減項 | ⚠ `AdjustBackground` は増項のみ | `diagnostics`(signal+rule), diagnose |
| ピーク幅不一致 → U,V,W / X,Y / size を個別 | 3候補を別 `ReleaseParams` | ⚠ `fwhm_ratio`→size のみ | `diagnostics` rule (flag 既存) |
| **位置/非対称残差 → Zero と 非対称を個別** | asymmetry/position signal + `ReleaseParams(profile_lorentzian/profile_asymmetry/tof_profile)` | ❌ 未実装 | `diagnostics`+diagnose (flag 既存) |
| 系統 obs>calc → preferred orientation | intensity_bias signal + `ReleaseParams(preferred_orientation)` | ❌ 未実装 | `diagnostics`+diagnose (flag 既存) |
| Rwp高止まり + 端ノイズ → データリミット | 具体切り位置の自動充填 | ⚠ `SetLimits` は Model プレースホルダ | orchestrator (`propose_initial_limits` 配線) / 層判定 |
| 占有率 >1/<0 発散 → 制約/等値/限定 else モデル選択 | occupancy_oob signal | ⚠ validity fail→`ReviseStructure`(model) | `diagnostics` (制約はサイト知識要→一部L3) |
| Uiso 発散/負 → free_uiso 限定 | uiso_diverged signal + **新 SafeAction `RestrictUiso`** | ❌ 未実装 | `action.py`+`diagnostics`+result 露出 |
| 吸収不明 → free/physical/0 個別 | **新 SafeAction `SetAbsorption`** + 物理値源 | ❌ 未実装 | `action.py`+`diagnostics`+`absorption.neutron` |
| 格子崩壊 → revert | — | ✅ engine ガード | — |

## 表C: Action 在庫 (設計的含意)

| Action | 種別 | 汎用性 |
|---|---|---|
| `ReleaseParams(label, flags)` | Safe | **任意 recipe flag を運べる** → PO/Lorentzian/非対称/tof_profile/absorption(解放) は**新 Action 不要**、診断規則を足すだけ |
| `AdjustBackground` | Safe | 増減両対応に小改修 |
| `RestrictUiso` / `SetAbsorption` | 新 Safe | 「解放」でなく「限定/値固定」ゆえ新設 |
| `SetLimits`/`AddPhase`/`RemovePhase`/`ReviseStructure`/`SetMixedOccupancy` | Model | ③/人間、proposal のみ |

## 横断的前提工事 (これが無いと大半のシグナルが「見えない」)

1. **`AutoRietveldResult` に内省フィールド追加** (`autorietveld/model.py`) — per-atom Uiso/占有率、
   per-hist 吸収・プロファイル値、選択配向・幅の obs/calc 指標。現状は残差配列と cell/相分率/validity のみ。
2. **実残差解析 diagnose の実装** (新 `refine_loop/diagnose_residual.py`) — `_default_diagnose` は背景のみ。
   残差配列 + 新フィールドから fwhm比/非対称/位置/PO/端SN/Uiso発散/吸収不確実を算出。

## 実装ロードマップ (優先度順)

- **P0 前提**: 上記1(result 内省), 2(残差解析 diagnose)。
- **P1 診断規則追加** (`diagnostics.py`, Action は既存 `ReleaseParams`): 非対称/位置(Zero と SH·L/alpha 個別)、
  preferred orientation、幅(U,V,W/X,Y 個別)、背景 overfit 減項。
- **P2 新 SafeAction** (`action.py`): `RestrictUiso(labels)`、`SetAbsorption(hist_id, value, refine)`。
- **P3 データリミットのループ内配線** (`orchestrator.py`, `propose_initial_limits` 活用; 層判定要)。
- **P4 第3層** (別オーケストレータ): `compare.compare_models`/`evidence` で変種を BIC+妥当性裁定
  (単一モデル調律ループの外)。

## 不変則 (遵守)

全トライは `_accept` の revert ガード下 (悪化=自動棄却, P2/NFR-102)。診断は結論を焼き込まず「候補を
**別々に**解放して観察→採否」を列挙する。材料固有知見は非拘束 prior (試す順序ヒント) に留める。
決定論 (NFR-102): 提案は safe 優先→優先度降順→型名昇順。numpy コア + GSAS は runner 内遅延 import。
