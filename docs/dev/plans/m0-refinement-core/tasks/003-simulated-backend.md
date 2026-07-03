---
id: "003"
title: "SimulatedBackend（合成パターンの実 LM フィット）を実装"
status: done
priority: 2
dependencies: ["002"]
estimated_complexity: high
---

# Task: SimulatedBackend（合成パターンの実 LM フィット）を実装

## Goal

GSAS-II 非導入環境で全パイプラインを動かすための、決定論的な合成回折パターン精密化エンジン。
相ごとのガウシアンピーク列を格子・scale から生成し、解放パラメータのみを Levenberg–Marquardt で最適化する。

## Interfaces

```python
# tsumugin/backends/simulated.py
class SimulatedBackend:                             # 🟡 RefinementBackend 実装
    name = "simulated"
    def __init__(self, *, peak_fwhm: float = 0.2, d_spacings: Mapping[str, Sequence[float]] | None = None): ...
    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult: ...
    def simulate(self, phases, two_theta) -> np.ndarray: ...   # 🟡 前方モデル(テスト/データ生成用)

# ピーク位置: Bragg 則の簡約。2θ_hkl = 2*asin(λ/(2 d_hkl))、d_hkl は格子体積の立方根に比例させる簡約模型
# 強度: I(2θ) = Σ_phase scale * Σ_hkl mult * Gaussian(2θ; 2θ_hkl, fwhm)
```

自由パラメータの扱い: `free_params` に含まれる名前(例 `phase0.scale`, `phase0.lattice.a`)のみを
最適化ベクトルに載せ、それ以外は固定。境界(scale>0)は soft に扱う。

## Test Strategy

- [ ] `simulate` が単相で 2θ 軸上にピーク本数分の極大を生成する（ピーク数一致）
- [ ] 真値からずらした初期 scale を `phase0.scale` 解放で精密化すると真値に ±1% 収束、converged=True
- [ ] lattice.a を解放するとピーク位置がフィットし chi2 が初期比で大幅減少
- [ ] 解放パラメータ 0 個なら 1 サイクルで converged（何も動かさない）、n_params==0
- [ ] 同一入力・同一乱数種で 2 回実行すると RefinementResult がビット同一（NFR-102 再現性）
- [ ] rwp が [0, ∞) の非負、chi2 も非負

## Implementation Notes

- LM は numpy で自前実装（数値ヤコビアン、λ の増減、最大 max_cycles）。scipy 非依存。
- 収束判定: |Δchi2|/chi2 < 1e-4 または パラメータ更新ノルム < 1e-6。
- 決定論のため乱数は使わない（データ生成側で seed 固定）。摂動が要る箇所は index ベース。
- d_spacings 未指定時は既定の hkl 集合を格子体積から生成（相ごとに 3–5 本）。
- rwp = 100 * sqrt( Σ w(y_o−y_c)² / Σ w y_o² )。chi2 = Σ w(y_o−y_c)²。

## Files

- 新規: src/tsumugin/backends/simulated.py
- テスト: tests/test_simulated_backend.py
