# 電気化学制約付き operando Rietveld — タスク一覧 (FR-318)

ブランチ: `milestone/charge-constrained-rietveld`。TDD (Red→Green)、タスク毎コミット。
numpy-only は高速ティア、GSAS 依存は `@pytest.mark.gsas`。

| # | タスク | 規模 | テスト |
|---|---|---|---|
| T0 | docs 三点セット | S | — |
| T1 | `electron_count` (26801.5 ピン留め) | S | test_coulometry.py |
| T2 | `alkali_targets` (in_span/rest/state 分岐 + sign 照合) | M | 〃 |
| T3 | `MobileSiteSpec` 複数元素合算 + content 変換 | M | 〃 |
| T4 | `x_xrd_from_weight_fractions` (FW 除算) + feasibility | M | 〃 (非対称 FW/Z ピン) |
| T5 | `TargetComposition` + `FrameSpec.target_composition` 往復 | S | test_m9_model.py 系 |
| T6 | `ChargeConstraintConfig` + `make_gsas_runner` 配線 | S | 〃 |
| T7 | `atom_occupancy`/`atom_uiso` ラベルキー配線 + esd | M | test_charge_constraint_gsas.py |
| T8 | `initial_occupancies` シーダー (fix でフラグ off) | M | 〃 |
| T9 | 初期 Uiso 妥当性の事前警告 + 同時精密化警告 | S | 〃 + numpy |
| T10 | `_apply_chem_comp_restraints` (ChemComp 直接注入) | L | 〃 |
| T11 | mult/Z 自動抽出 + spec 照合警告 | M | 〃 |
| T12 | `lock_fractions` 相間 EqnConstr + 実行可能性ゲート | L | 〃 (2相合成) |
| T13 | runner モード分岐 + `FrameRietveldResult` alkali_* 拡張 | L | numpy スタブ + gsas |
| T14 | アンカー A/B + x₀ 校正提案 | M | numpy スタブ |
| T15 | ② `alkali_budget` ツール | M | test_alkali_budget_tool.py |
| T16 | ② `charge_constraint` spec (sequential/anchored) | M | test_mcp_insitu 系 |
| T17 | ③ skill×2 + PLAYBOOK×2 + ガードテスト | M | test_m9_plugin.py 等 |
| T18 | K-10 実データ E2E 検証 + 重ね図 | L | @gsas + scratchpad |

ガード更新: LAYER1_FEATURES (`alkali_budget`) / FRAME_RESULT_FIELDS (alkali_*) /
AUTORIETVELD_RESULT_FIELDS (atom_occupancy 配線後の出力キー)。
