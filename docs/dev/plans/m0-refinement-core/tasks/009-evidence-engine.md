---
id: "009"
title: "Evidence Engine（bic/aic + softmax 確率）を実装"
status: done
priority: 2
dependencies: ["001"]
estimated_complexity: medium
---

# Task: Evidence Engine（bic/aic + softmax 確率）を実装

## Goal

FR-120/121/124 の EvidenceBackend 抽象と bic(既定)/aic 実装、仮説集合の softmax+温度較正確率、
ΔBIC<10 の僅差競合フラグ(FR-122 一次判定)を提供する。

## Interfaces

```python
# tsumugin/evidence/base.py
@dataclass(frozen=True)
class EvidenceResult:  backend: str; value: float; logz_err: float | None = None   # 🔵 §4 evidence

class EvidenceBackend(Protocol):                    # 🔵 P7/FR-121
    name: str
    def score(self, metrics: RefinementMetrics) -> EvidenceResult: ...

# tsumugin/evidence/ic.py
class BICBackend:   name = "bic"                     # 🔵 既定。value = chi2 + k*ln(n)
class AICBackend:   name = "aic"                     # 🔵 value = chi2 + 2k

# tsumugin/evidence/ranking.py
@dataclass(frozen=True)
class RankedHypothesis:                             # 🔵
    hypothesis: Hypothesis
    evidence: EvidenceResult
    probability: float                              # softmax(−value/2 / T)
    close_competitor: bool                          # ΔBIC<threshold の僅差

def rank(hypotheses, backend: EvidenceBackend, *, temperature: float = 1.0,
         close_threshold: float = 10.0) -> tuple[RankedHypothesis, ...]: ...  # 🔵 FR-122/124
```

## Test Strategy

- [ ] BIC: chi2=100,k=5,n=1000 で value == 100 + 5*ln(1000) を厳密一致
- [ ] AIC: chi2=100,k=5 で value == 110.0
- [ ] `rank` の確率が総和 1.0（±1e-9）、value 最小の仮説が最大確率
- [ ] 温度 T を上げると確率分布が平坦化（最大確率が下がる）
- [ ] ΔBIC<10 の 2 仮説が両方 close_competitor=True、離れた仮説は False
- [ ] 出力は value 昇順（＝良い順）にソート済み
- [ ] metrics が None の仮説は評価対象外 or ValueError（設計選択を明記）

## Implementation Notes

- softmax は overflow 回避で `x = -value/(2T); x -= x.max(); p = exp(x)/sum(exp(x))`。
- close_competitor は BIC 値基準（backend が aic でも比較は value 差でよい。名称は close_competitor 汎用）。
- 最良仮説自身も close 判定に含める（最良と僅差の相手が居れば両方フラグ）。

## Files

- 新規: src/tsumugin/evidence/__init__.py, src/tsumugin/evidence/base.py,
        src/tsumugin/evidence/ic.py, src/tsumugin/evidence/ranking.py
- テスト: tests/test_evidence.py
