---
id: "008"
title: "段階的パラメータ解放エンジン（ガード+ロールバック統合）を実装"
status: done
priority: 2
dependencies: ["003", "006", "007"]
estimated_complexity: high
---

# Task: 段階的パラメータ解放エンジン（ガード+ロールバック統合）を実装

# Goal

FR-200/201/202 のステージテンプレートを駆動し、各段で snapshot→refine→guard を回す。
悪化/違反時は revert して原因を固定し再試行、3 回失敗で `EscalationRequired`。
全遷移を ledger に理由付きで記録(FR-214)。単一パターン自動多相精密化の中核。

## Interfaces

```python
# tsumugin/refinement/staged.py
@dataclass(frozen=True)
class Stage:                                        # 🔵 FR-201 各段
    name: str                                       # "scale_bg"|"lattice_zero"|"profile"|...
    param_keys: tuple[str, ...]                     # この段で追加解放するキー(相非依存の suffix)

DEFAULT_STAGE_TEMPLATE: tuple[Stage, ...] = (...)   # 🔵 FR-201 既定テンプレート

@dataclass(frozen=True)
class StageOutcome:                                 # 🔵
    stage: str
    accepted: bool
    result: RefinementResult
    violations: tuple[GuardViolation, ...]
    retries: int

@dataclass(frozen=True)
class RefinementReport:                             # 🔵
    final_phases: tuple[PhaseInstance, ...]
    metrics: RefinementMetrics
    stage_outcomes: tuple[StageOutcome, ...]
    escalated: bool

class StagedRefinementEngine:                       # 🔵
    def __init__(self, backend: RefinementBackend,
                 store: SnapshotStore, ledger: Ledger,
                 *, template: tuple[Stage, ...] = DEFAULT_STAGE_TEMPLATE,
                 config: GuardConfig = GuardConfig(),
                 max_retries: int = 3,               # 🔵 FR-212 3回失敗
                 rwp_improve_pct: float = 2.0): ...  # 🔵 FR-115/202 改善閾値
    def run(self, phases, two_theta, intensity, *, weights=None) -> RefinementReport: ...
```

## Test Strategy

- [ ] クリーンな合成データで全段が accepted、最終 rwp が初期段より改善、escalated=False
- [ ] ある段が改善閾値未満なら固定戻し（前段の phases を保持）で次段へ進む
- [ ] ガード違反を注入するバックエンド（scripted）で revert が起き、原因パラメータが固定される
- [ ] 同一段で 3 回連続違反すると `EscalationRequired` 送出 or report.escalated=True（設計選択を明記）
- [ ] 各 stage につき snapshot が最低1つ保存され、ledger に refine/guard/rollback が記録される
- [ ] 解放キーが段ごとに累積する（lattice 段では scale も自由のまま）
- [ ] 同一入力で 2 回実行し RefinementReport がビット同一（決定論・NFR-102）

## Implementation Notes

- テンプレート既定: scale_bg → lattice_zero → profile → texture → occupancy → coordinates → adp。
  M0 の SimulatedBackend が実際に動かすのは scale/lattice.*、他段は「解放しても no-op で通過」でよい。
- param_keys は suffix（例 "scale","lattice.a"）。engine が全相へ展開して `phase{i}.{suffix}` に。
- 各段: `store.save(...)` → `backend.refine(model_with_freed)` → `check_guards(prev,cur)`。
  違反あり → `store.revert` して原因 param を free から外し retry。max_retries 到達で escalate。
- escalate は例外送出ではなく report.escalated=True で返し、ledger に "escalate" 記録（処理ブロックしない、FR-403）。
- scripted backend テストダブルは tests 側に定義（本体には置かない）。

## Files

- 新規: src/tsumugin/refinement/staged.py
- テスト: tests/test_staged_engine.py
