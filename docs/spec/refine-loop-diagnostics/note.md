# refine-loop-diagnostics コンテキストノート

## 技術スタック / 制約 (CLAUDE.md 由来)

- Python 3.12 (uv, src layout + hatchling)。テスト `uv run pytest`、高速ティア `-m "not gsas"`。
- Lint `uvx ruff check` (line-length 100)。frozen dataclass + `with_updates()`、境界は `typing.Protocol`。
- **numpy コア + GSAS 遅延 import**。決定論 (NFR-102 ビット同一)、追記専用 Ledger (NFR-105)。
- TDD 厳守 (Red→Green→Refactor、テストなし実装コミット禁止)。全エージェント Opus。

## 対象モジュール (実装済み・本要件で拡張)

`tsumugin.refine_loop` (M8 決定論 agentic 閉ループ):
- `action.py`: `AnalysisAction` 基底 + `SafeAction`/`ModelAction`。SafeAction=`AdjustBackground`/
  `ReleaseParams(label, flags)`/`Stop`。ModelAction=`SetLimits`/`AddPhase`/`RemovePhase`/
  `ReviseStructure`/`SetMixedOccupancy`。**`ReleaseParams` は任意 recipe flag を運べる汎用手**。
- `diagnostics.py`: `ResidualFeatures` (現状 signal: low_freq_bg_residual/fwhm_ratio/
  unindexed_peak_frac/edge_low_snr/n_background_coeffs) + `propose_next_actions` (決定論・安定順:
  safe 優先→優先度降順→型名昇順) + `propose_initial_limits` (setup 用保守的初期リミット)。
- `policy.py`: `AnalysisPolicy` Protocol + `RuleBasedPolicy` (SafeAction のみ・既試行除外・
  target/stall/max で Stop) + `PolicyBudget`。
- `orchestrator.py`: `run_refinement_loop` (baseline→diagnose→propose→policy→apply→`_accept`→
  revert/ledger)。**`_accept` = Rwp 改善 ∧ validity 維持** = 「トライ→ダメなら revert」の核心。
  `_default_diagnose` は背景のみの粗診断 (拡張対象)。runner/diagnose は注入可能。
- `serialization.py`: 台帳シリアライズ。

依存する `tsumugin.autorietveld`:
- `model.AutoRietveldResult`: stage_results/final_rwp/final_gof/refined_cells/validity/n_obs/
  phase_fractions/**residual_two_theta・residual_intensity・residual_sigma** (残差配列は既にある)。
  **per-atom Uiso/占有率・per-hist 吸収/プロファイル値は未露出** (本要件で追加)。
- `engine._apply_stage` が解釈するフラグ: background/cell/displacement/profile/absorption/
  tof_profile/preferred_orientation/profile_lorentzian/profile_asymmetry/size_strain/
  hydrostatic_strain/phase_fraction_sum/coords/uiso/occupancy。**opt-in 段は revert ガード付き**。
- `compare.compare_models`: BIC+妥当性でモデル序列化 (best は妥当性優先, best_is_valid)。

## 設計文書 (本要件の入力・正)

- `docs/design/refine-loop-diagnostics/GAP_ANALYSIS.md`: 3層↔refine_loop 対応 + 表B(ギャップと追加
  場所) + 表C(Action 在庫) + 前提工事 + ロードマップ P0–P4。**要件はこれを正式化する**。
- `docs/reference/serious-refinement-flow.md`: 一般化フロー (装置初期値+解放順+3層)。核心原理
  「可能性があればトライ→ダメなら revert」。第2層b=診断オートトライ、第3層=真の判断(BIC 等)。

## 注意事項 / 教訓

- **結論を焼き込まない**: 診断は「候補を別々に解放して観察→採否」を列挙。材料固有知見(例
  「TOF は alpha が効く」)は非拘束 prior (試す順序ヒント) に留める。
- 大半の新診断は**既存 `ReleaseParams` + engine flag で表現可**。新 Action は「限定/値固定」の
  `RestrictUiso`/`SetAbsorption` のみ。
- 決定論: 提案順序・タイブレークを固定。GSAS は runner 内遅延 import (コアは numpy)。
- P4 (BIC モデル選択) は単一モデル調律ループの**外** (`compare` 委譲) — 本要件の scope 境界に関わる。
