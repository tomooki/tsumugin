---
id: "010"
title: "単一パターン自動多相精密化パイプラインを統合"
status: done
priority: 3
dependencies: ["003", "008", "009"]
estimated_complexity: medium
---

# Task: 単一パターン自動多相精密化パイプラインを統合

## Goal

M0 の受け入れ機能「単一パターン自動多相精密化」を 1 つの高レベル API に統合する。
複数の初期仮説を段階エンジンで精密化し、Evidence Engine でランキングして返す。
全過程が ledger で revert 可能であることを end-to-end で保証する。

## Interfaces

```python
# tsumugin/pipeline.py
@dataclass(frozen=True)
class AnalysisResult:                               # 🔵
    ranked: tuple[RankedHypothesis, ...]
    reports: Mapping[str, RefinementReport]         # hypothesis_id -> report
    ledger: Ledger
    snapshots: SnapshotStore

def analyze_single_pattern(
    two_theta, intensity,
    candidate_phase_sets: Sequence[tuple[PhaseInstance, ...]],
    *, backend: RefinementBackend | None = None,     # 既定 SimulatedBackend
    evidence: EvidenceBackend | None = None,         # 既定 BICBackend
    weights=None,
) -> AnalysisResult: ...                              # 🔵
```

## Test Strategy

- [ ] 2 相候補セットを与えると各々精密化され、ranked が確率降順で返る
- [ ] 真のモデル（データ生成に使った相構成）が最上位ランクになる合成ケース
- [ ] 全 hypothesis_id が reports と ranked の両方に現れる（整合）
- [ ] ledger.verify() が True、途中スナップショットへ revert して状態復元できる
- [ ] 同一入力で 2 回実行して AnalysisResult がビット同一（NFR-102）
- [ ] 候補ゼロで空の ranked を返す（例外を投げない）

## Implementation Notes

- 各候補セットに `Hypothesis` を採番（決定論 ID: "hyp-0000" 連番）。
- StagedRefinementEngine を候補ごとに走らせ、最終 metrics に evidence 値を格納して Hypothesis 化。
- backend/evidence を差し替え可能に（DI）。既定は Simulated + BIC。
- README にこの API の 10 行程度の使用例を追記する。

## Files

- 新規: src/tsumugin/pipeline.py
- 変更: README.md（使用例）, src/tsumugin/__init__.py（公開 API re-export）
- テスト: tests/test_pipeline.py
