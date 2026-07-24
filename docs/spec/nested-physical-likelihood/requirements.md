# Issue #76 要件整理 (nested 裁定への物理尤度・restraint 事前分布配線)

仕様書対応: `docs/tsumugin_spec_v0.3.md`

| ID | 要件 | 本実装での充足 |
|---|---|---|
| FR-122 | 階層的裁定 — bic 一次 + 僅差競合のみ nested 再裁定の 2 段構え | 発動条件・配線 (Issue #65/PR #75) は不変。再裁定の**裁定力**を獲得する (v1 は Σbic 定数尤度で数学的に解消不能) |
| FR-125 | nested 事前分布は精密化 restraint から自動構成・手動上書き可 | `restraints_from_state` が精密化状態 (格子シフト上限の発想) から `RestraintSpec` を組み、既存 `build_prior_from_restraints` へ接続 |
| FR-313 | 固溶体 vs 二相判別 — bic 一次 + 競合時 nested 裁定 | 判別の EvidenceProblem を区間 joint 物理尤度 (θ=フレーム別解放集合, logL=Σ-χ²/2) に置換 |
| NFR-102 | 決定論 (サンプラは seed 固定 + logZ 誤差併記) | priors 昇順・フレーム major の次元順固定。Laplace 経路はビット同一、nested 経路は seed 固定 + logz_err 併記 |
| NFR-103 | 計算資源上限・打ち切り | 既存 `run_with_fallback` の time_limit + Laplace 代替を不変に通す |

受け入れ基準 (Issue #76 本文):

1. 合成データで「bic 僅差だが nested/Laplace (実曲率) は判別可能」なケースを構成し、裁定が verdict を確定させる
2. 決定論 (seed 固定 + logZ 誤差併記)、NFR-103 打ち切り準拠
3. PR #75 の三重ガード (同一経路・有限・閾値) とメッセージングをそのまま通過する

スコープ (Issue #76 項目 4): 適用先は discrimination (FR-313) のみ。FR-316 区間分割・
M10 anchor crossover への一般化は動作実証後 (欠陥ごと API 化しない)。
