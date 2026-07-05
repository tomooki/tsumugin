# M7 実データ検証 アーキテクチャ設計

## 1. 全体方針

**新モジュール `tsumugin.autorietveld`** を追加し、実 CIF/相ファイル + 実データ + 装置パラメータを
入力に GSAS-II を直接駆動する自動 Rietveld 経路を提供する。既存 `backends.gsasii` (格子同定用の
ダミー構造) と `refinement.staged` (抽象 RefinementModel) は破壊しない (P2 非破壊性)。

De-risk 済み: T1 fluoroapatite プロトタイプで段階解放レシピ (scale+bkg → cell+shift →
UVW+size+strain → coords+Uiso) がチュートリアル進行を再現し **Rwp 9.84% / GOF 1.76**
(チュートリアル 10.38% / 3.44) を自動達成。本設計はこのプロトタイプを production 化する。

## 2. モジュール構成

```
tsumugin/autorietveld/
├── __init__.py         # 公開シンボル
├── model.py            # 入力/出力データ構造 (frozen dataclass)
├── recipe.py           # 段階解放レシピ生成 (幾何/温度/多相アダプタ) — 純 numpy, GSAS 非依存
├── validity.py         # 物理的妥当性ゲート — 純 numpy, GSAS 非依存
└── engine.py           # GSAS-II 駆動エンジン (遅延 import, @pytest.mark.gsas)
```

### 2.1 model.py (純データ, テスト容易)

- `Radiation` (Enum): `XRAY_LAB` / `XRAY_SYNCHROTRON` / `NEUTRON_CW` / `NEUTRON_TOF`
- `Geometry` (Enum): `BRAGG_BRENTANO` / `DEBYE_SCHERRER`
- `HistogramSpec` (frozen): `data_path`, `instrument_path`, `radiation`, `geometry`,
  `data_format` ("GSAS"/"FXYE"/"XYE"), `bank`(TOF フレーム用), `two_theta_limits`
- `PhaseSpec` (frozen): `structure_path` (CIF/EXP), `phase_name`, `format_hint`,
  `mixed_occupancy_sites` (占有率制約対象), `temperature` (温度差吸収の要否判定)
- `RefinementStage` (frozen): `label`, `flags` (GSAS-II set_refinements 相当の宣言的記述)
- `StageResult` (frozen): `label`, `rwp`, `gof`, `n_params`, `converged`, `reverted`
- `AutoRietveldResult` (frozen): `stage_results`, `final_rwp`, `final_gof`, `refined_cells`,
  `validity`(ValidityReport), `gpx_path`

### 2.2 recipe.py (アルゴリズム中核 = 成果物1)

`build_recipe(histograms, phases) -> tuple[RefinementStage, ...]`:
普遍系列 + アダプタで段階列を生成する。

1. **S0 scale + 背景** (全ヒストグラム, Chebyshev 初期 3–6 項)
2. **S1 格子 + 幾何補正**: Bragg-Brentano → sample displacement (Shift)、
   Debye-Scherrer → ゼロ/試料 X,Y。多相なら相分率和=1 制約、混合占有なら等価/和制約を付随生成。
3. **S2 プロファイル UVW (+ size/microstrain)**
4. **S3 原子座標 (X)**
5. **S4 Uiso (U)**
6. **S5 占有率 (frac)** — 混合占有サイトのみ、制約下で
- 温度差ヒストグラム (`temperature` 差あり) は S1 で per-histogram 静水圧歪み Dij を追加。
- レシピは宣言的 (`flags`) なので GSAS 非依存にユニットテスト可能。

### 2.3 validity.py (物理妥当性ゲート = 達成目標判定)

`check_validity(result, references) -> ValidityReport`:
- 格子定数が参照 (CIF 初期値/文献) の ±tol% 以内
- Uiso ∈ (0, uiso_max] (既定 0.1 Å²)
- 占有率 ∈ [0, 1]
- 制約充足 (占有率和・相分率和 = 1 を許容誤差内)
- converged フラグ
`ValidityReport`: `passed`(bool), `checks`(項目別 pass/fail + 実測値), `warnings`

### 2.4 engine.py (GSAS-II 駆動, 遅延 import)

`run_auto_rietveld(histograms, phases, *, recipe=None, guard=...) -> AutoRietveldResult`:
1. `gpx = G2Project(newgpx=...)`
2. 各 `HistogramSpec` を format に応じて `add_powder_histogram` (fmthint 分岐)
3. 各 `PhaseSpec` を `add_phase` (CIF/EXP)、混合占有・相分率制約を GSAS-II 制約として登録
4. `recipe` (未指定なら `build_recipe`) の各段階を順に:
   - スナップショット (Rwp) → フラグ設定 → `do_refinements` → Rwp 取得
   - **Rwp 悪化時は当該段階フラグを解除して継続** (REQ-105, 既存 FR-202 の思想)
   - 失敗は chi2=inf 相当として StageResult(converged=False) に変換 (REQ-403)
5. `check_validity` で妥当性判定
6. 全段階の遷移を Ledger へ追記 (NFR-105 ハッシュチェーン維持)

## 3. データフロー

```
HistogramSpec[] ┐
PhaseSpec[]     � → build_recipe → RefinementStage[]
                                      │
                 engine.run_auto_rietveld (GSAS-II)
                    ├─ add histograms/phases + constraints
                    ├─ for stage: refine → guard(revert on worsen) → StageResult
                    ├─ check_validity → ValidityReport
                    └─ ledger append
                                      │
                                AutoRietveldResult (Rwp/GOF/cells/validity)
```

## 4. ローダー拡張 (reference.io)

- `load_fxye(path)` — 11BM .fxye (2θ, I, ESD)。ヘッダ BANK 行の対応。
- TOF `.gsa` は GSAS-II の `add_powder_histogram` に直接渡す (エンジン層で処理)。
- `.instprm` は GSAS-II が読むためエンジン層でパス渡し。
- 純 numpy で読む必要がある FXYE のみ `reference.io` に関数追加 (相同定にも再利用可)。

## 5. AI エージェント指示書 (AGENT_PLAYBOOK.md = 成果物2)

`docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md`:
- 入力の集め方 (データ/装置/構造ファイルの特定、放射源・幾何の判定基準)
- `run_auto_rietveld` の呼び出しパターン (単相/多相/joint)
- 結果の読み方 (Rwp/GOF 目標・妥当性レポートの解釈)
- 失敗時の対処 (発散 → 格子確認、未収束 → 段階追加、妥当性 fail → 制約見直し)
- T1–T4 を再現する具体レシピ例

## 6. 不変条件の維持

- コア import は numpy のみ。engine.py の GSAS-II は関数内遅延 import。
- model/recipe/validity は frozen dataclass + 純関数でビット再現可能 (NFR-102)。
- Ledger 追記専用・ハッシュチェーン (NFR-105)。バックエンド失敗は inf 変換 (REQ-403)。
