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

## T18 実データ検証の結果 (2026-07-19, K-10 実測)

**② MCP 経由の E2E 完走** (`alkali_budget` → `anchored_sequential(charge_constraint)`,
32 フレーム + 17 アンカー, diagnose モード, 33.9 分, ledger verified)。AC-6 達成。

- 物理量: Characteristic mass **19.628 mg** (`K-10_0p1C_re2.mps` 実入力; "Mass of active
  material 7000 mg" は EC-Lab 既定値の残骸 — **MPS を読むときの罠**)。M(x₀)=339.4 g/mol,
  x₀=1.944。検算 138.6 mAh/g → n_e=1.76 → 充電末 x=0.192 (ほぼ全 K 引き抜き)。
- **中間 SOC で x_XRD が x_echem を esd 内で追従** (充電 4.5–5.5 h: 残差 −0.011〜+0.041 /
  放電 11.5–12.5 h: +0.008〜−0.030)。回折の相分率とクーロメトリーの独立クロス検証が成立。
- **`infeasible` が fr92 で発火** (x_echem 0.601 < min xᵢ 0.70 of {mono, cubic}) —
  「この相集合ではこの K 量は保持できない = tetra (x=0) が出現しているはず」の独立シグナル。
  **BIC バケオフが確定した真の tetra onset fr91 と 1 フレーム差で一致** (情報量規準と
  クーロメトリーという独立な 2 手法の相互検証)。放電側は fr162 で対称に発火 (mono 出現予告)。
- **充電 7–10 h の残差 +0.30〜+0.38** = 旧アンカー相集合 (mono 過剰割当) の**クーロメトリー
  指紋**。BIC 訂正 (fr70–90 cubic 単相化) 後の相集合では大幅に縮小する見込み — J9 が
  Rwp 非依存に同じ誤りを検出できることの実証。
- アンカー A/B: fr173 (cubic 単相) で**制約側が Rwp −0.68 %pt 改善** (occ 0.35→seed 0.44) =
  cubic の K 占有率が SOC 依存 (固溶) で CIF 値が過小という示唆 (閾値 1.0 未満なので警告なし)。
  放電端 fr242/246 は Δ+0.03 で整合。不可逆容量 (x₀−x_end=0.051 ≈ 2.6%) を実測。
- **残る系統残差 (mean +0.105)** の主因: xᵢ 固定近似 (cubic は固溶で x が SOC 変化) +
  初期充電の副反応。per-phase x の SOC 依存化は M-later。

検証スクリプト: `scratchpad/kmnfe/scripts/fr318_validation.py` / `plot_fr318.py` (gitignore 域)。
