---
id: "007"
title: "ガードレール（発散検知）を実装"
status: done
priority: 2
dependencies: ["002"]
estimated_complexity: medium
---

# Task: ガードレール（発散検知）を実装

## Goal

FR-211 の発散検知を純粋関数として実装する。精密化結果とモデルから違反を検出し、
理由付きの `GuardViolation` を返す（例外は投げず結果で表現、FR-214 で ledger 記録可能に）。

## Interfaces

```python
# tsumugin/refinement/guardrails.py
GuardKind = Literal["chi2_divergence","negative_occupancy","lattice_runaway",
                    "negative_adp","phase_fraction_pinned"]                   # 🔵 FR-211

@dataclass(frozen=True)
class GuardViolation:                               # 🔵
    kind: GuardKind
    detail: str
    param: str | None = None                        # 原因パラメータ（固定戻し対象）

@dataclass(frozen=True)
class GuardConfig:                                  # 🟡 閾値
    chi2_worsen_ratio: float = 1.5                  # 前段比で chi2 が 1.5x 超で発散扱い
    lattice_shift_frac: float = 0.2                 # 格子が初期比 ±20% 超で暴走
    min_wt_frac: float = 1e-4                       # 相分率ゼロ張り付き閾値

def check_guards(prev: RefinementResult | None,
                 cur: RefinementResult,
                 *, config: GuardConfig = GuardConfig()) -> tuple[GuardViolation, ...]: ...  # 🔵
```

## Test Strategy

- [ ] chi2 が前段比 chi2_worsen_ratio 超で `chi2_divergence` を検出（param は None）
- [ ] いずれかの相の occupancy < 0 で `negative_occupancy`、param に該当名
- [ ] 格子 a が prev 比 +25%（閾値20%超）で `lattice_runaway`
- [ ] wt_frac が min_wt_frac 未満で `phase_fraction_pinned`
- [ ] 正常な改善（chi2 減少・全パラメータ物理範囲内）で違反ゼロ（空タプル）
- [ ] prev=None（初回段）では chi2 比較をスキップし、絶対条件のみ評価
- [ ] 複数違反が同時に起きたら全て返す（順序は kind 定義順で決定論的）

## Implementation Notes

- 純粋関数。副作用なし・乱数なし。ledger 記録は呼び出し側(task 008)。
- negative_adp は M0 では ADP 未実装のため occupancies に "adp_*" キーがあれば負値チェック（前方互換の枠）。
- lattice_runaway は prev があるときのみ（初期値基準は engine 側が prev に初期状態を渡す設計）。

## Files

- 新規: src/tsumugin/refinement/__init__.py, src/tsumugin/refinement/guardrails.py
- テスト: tests/test_guardrails.py
