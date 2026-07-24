# Issue #76 実装タスク (Fable 主導 TDD)

設計は `docs/design/nested-physical-likelihood/architecture.md`。仕様根拠:
FR-122 (階層的裁定) / FR-125 (restraint 由来事前分布) / FR-313 (固溶体 vs 二相判別) /
NFR-102 (決定論) / NFR-103 (打ち切り)。

各タスクは Red→Green→Refactor、green ごとに 1 コミット。

- [x] **T1 曲率公開**: `Curvature` dataclass + `RefinementResult.curvature` (additive 既定 None) +
      SimulatedBackend 充填 (最終 p の jac を σ 導出と共有)。
      テスト: 充填の有無 (解放ゼロ=None)・列順=names+mu_t・JᵀJ の有限差分照合・決定論ビット同一。
- [x] **T2 Laplace 高精度化**: `PriorSpec.log_pdf` + LaplaceBackend の事前密度項
      (priors+MAP+H 揃い・次元一致時のみ)。
      テスト: uniform 事前の解析解 (線形ガウスモデルで logZ 厳密値と一致)・従来経路の不変・
      次元不一致/priors 空の従来式維持。
- [x] **T3 physical.py 新設**: `restraints_from_state` / `FrameState` / `build_physical_problem`。
      テスト: logL(map_point)=Σ-χ²/2 (backend 評価一致)・priors 昇順/フレーム major・
      ブロック対角 H・MAP が事前台内 (構成的)・決定論。
- [x] **T4 discrimination 配線**: `PhysicalProblemConfig` オプトイン (既定 ON)・
      `_IntervalOutcome.results` 全フレーム保持・実効経路 3 値検出・BIC 等価スケール (×2)・
      サロゲート縮退 warning。
      テスト: 経路混在 (実 laplace vs bic_fallback) が undecided に留まる**変異実証**・
      bic_fallback 同士の従来挙動保存・escape hatch (=None) で v1 完全互換。
- [x] **T5 受け入れ** (実測: ΔΣbic=0.35 の僅差 → 実曲率 Laplace が ΔBIC_nested=+23 で two_phase (真実) を確定。実 dynesty 5s で同符号): 合成データで bic 僅差 → 実曲率 Laplace が verdict 確定。
      dynesty gated テスト (importorskip) で nested 経路の同符号確定 + seed 再現。
- [ ] **T6 露出宣言 + 文書**: LAYER1_FEATURES の nested 非露出理由を更新 (callable 障壁解消・
      残る障壁は FR-313 の ② spec 設計)・② 露出の新 Issue 起票・CLAUDE.md 追記。

スコープ外 (宣言): GSASIIBackend の Curvature 充填 (コスト予算検討と一体, M-later)・
FR-316/M10 crossover への一般化 (動作実証後)・full_nested 運転の較正。
