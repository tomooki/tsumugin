# M9 高温 in situ 逐次 Rietveld — 実装 PLAN / タスク

設計 `docs/design/m9-insitu-sequential/architecture.md`・要件 `docs/spec/m9-insitu-sequential/
requirements.md`・指示書 `AGENT_PLAYBOOK.md`。M7 (単一フレーム) + M8 (3 層閉ループ) + M6 (相同定) の統合。

## Phase A — データ / ローダー ✅

- `reference.io`: `parse_xrdml`/`load_xrdml` (Panalytical XRDML) + `load_pattern` (形式ディスパッチャ)。
- M9 ベンチデータ整備 (`docs/benchmark/testdata/m9/`): CaTeO3 (XRDML 代表 2 + alpha/delta CIF)、
  CuCr₂O₄ (CIF×2 + prm + 先頭 fxye)。Jana `.m40/.m50`→CIF 変換 (P1 展開)。
- テスト: `tests/reference/test_io.py` (XRDML 5 件)。

## Phase B — コアモデル + パラメトリック ✅

- `insitu.model`: FrameSpec/PhaseIdConfig/SequentialConfig/FrameRietveldResult/PhaseAppearance/
  SequentialRietveldResult (numpy-only, frozen)。
- `insitu.parametric`: lattice_baseline/transition_from_fractions/pseudo_variable_series/analyze_phase
  (`sequential.thermal` 再利用)。
- テスト: `tests/insitu/test_model.py` (10)・`test_parametric.py` (6)。

## Phase C — 相同定→PhaseSpec 物質化ブリッジ (M6 ギャップ解消) ✅

- `insitu.phaseid`: `identify_new_phases` (identify→既知相除外→CIF 物質化→PhaseSpec) +
  `PhaseMaterializer` Protocol + `MPMaterializer` (遅延 pymatgen `CifWriter`)。
- `autorietveld.run_auto_rietveld`: `initial_cells` 引数追加 (ウォームスタート, 加算のみ)。
- `autorietveld.AutoRietveldResult`: `phase_fractions` 追加 (相分率露出, 加算のみ)。
- テスト: `tests/insitu/test_phaseid.py` (5, stub provider/materializer)。

## Phase D — 逐次エンジン ✅

- `insitu.engine`: `run_sequential_rietveld` (ウォームスタート・変化点トリガ・自動相追加・受理基準・
  可逆棄却・ledger) + `make_gsas_runner` (放射源/装置指定・XRDML→XYE 自己変換) + 既定 runner。
- テスト: `tests/insitu/test_engine.py` (8, stub runner/finder で制御ロジック)。

## Phase E — MCP 3 ツール + plugin + AGENT_PLAYBOOK ✅

- `mcp.insitu_tools`: `sequential_rietveld`/`identify_and_add_phase`/`parametric_fit` (SDK 非依存、
  素の型 dict、runner/finder 注入可)。MCP_TOOLS 13→16。
- plugin: `plugins/tsumugin/skills/insitu/SKILL.md` + `commands/insitu-analyze.md`。
- テスト: `tests/mcp/test_insitu_tools.py` (4)・`tests/test_m9_plugin.py` (4)・MCP レジストリ数更新。

## Phase F — 実データ検証 + code-review 🟡

- `tests/insitu/test_engine_gsas.py` (`@pytest.mark.gsas`): CaTeO3 2 フレーム逐次の end-to-end 配線
  (ウォームスタート・ledger verify) を回帰。全系列 delta 自動同定 (MP gate) は Rwp 調整後に有効化。
- **honest status**: end-to-end 配線は確認済 (GSAS 駆動・格子伝播・ledger)。Rwp 収束帯 (~9%) への
  締め上げは装置プロファイル/背景/真空間群 CIF の反復調整が残る (M7 が T1–T4 で示した収束作業)。
- /code-review ループ・CLAUDE.md/ベンチ README 更新。

## 主要な設計判断

- **per-frame オーケストレーション** (単一巨大 gpx でなく): M7 の確立したガードレール (段階解放・
  revert・崩壊ガード) を再利用でき、テスト容易。ウォームスタートは `initial_cells` で格子を伝播。
- **相追加の受理基準** = 相分率有意 ∧ Rwp 改善 ∧ 妥当性 (過剰適合ガード)。誤検出は可逆棄却。
- **相同定は残差説明力のみ判定** — 化学的妥当性は ③ (Claude/人間) が退ける (権限境界)。
- **XRDML は自己変換** (GSAS optional 依存 xmltodict を避け、自作 parse_xrdml で XYE 化)。
