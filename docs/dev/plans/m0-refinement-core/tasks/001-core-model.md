---
id: "001"
title: "コアデータモデルとエラー型を定義"
status: done
priority: 1
dependencies: []
estimated_complexity: medium
---

# Task: コアデータモデルとエラー型を定義

## Goal

仕様 §4 の主要エンティティを frozen dataclass で定義し、以後の全モジュールが共有する
不変データモデルと例外階層を確立する。

## Interfaces

```python
# tsumugin/errors.py
class TsumuginError(Exception): ...                 # 🔵 基底
class GuardrailError(TsumuginError): ...            # 🔵 FR-210
class EscalationRequired(TsumuginError): ...        # 🔵 FR-212 3回失敗

# tsumugin/model/phase.py
@dataclass(frozen=True)
class LatticeParams:                                # 🔵 §4 lattice{...}±σ
    a: float; b: float; c: float
    alpha: float = 90.0; beta: float = 90.0; gamma: float = 90.0
    sigma: Mapping[str, float] = field(default_factory=dict)
    def volume(self) -> float: ...                  # 🟡 立方近似でなく一般三斜式

@dataclass(frozen=True)
class PhaseInstance:                                # 🔵 §4 PhaseInstance
    phase_ref: str
    lattice: LatticeParams
    scale: float
    wt_frac: float | None = None
    occupancies: Mapping[str, float] = field(default_factory=dict)
    def with_updates(self, **changes) -> "PhaseInstance": ...  # 🔵 P2 非破壊更新

# tsumugin/model/hypothesis.py
@dataclass(frozen=True)
class RefinementMetrics:                            # 🔵 §4 metrics
    rwp: float; gof: float; chi2: float
    n_obs: int; n_params: int
    evidence: Mapping[str, float] = field(default_factory=dict)

HypothesisStatus = Literal["candidate","refined","accepted","rejected","superseded"]  # 🔵

@dataclass(frozen=True)
class Hypothesis:                                   # 🔵 §4 Hypothesis
    id: str
    phases: tuple[PhaseInstance, ...]
    parent_id: str | None = None
    metrics: RefinementMetrics | None = None
    status: HypothesisStatus = "candidate"

# tsumugin/model/project.py  (§4 Project/Dataset/Frame/HistogramRef)
Probe = Literal["xray","neutron_cw","neutron_tof"]  # 🔵
@dataclass(frozen=True)
class HistogramRef:  probe: Probe; data_ref: str; instprm_ref: str | None = None
@dataclass(frozen=True)
class Frame:         id: str; index: int; histograms: tuple[HistogramRef, ...] = ()
@dataclass(frozen=True)
class Dataset:       id: str; kind: Literal["single","sequence"]; frames: tuple[Frame, ...] = ()
@dataclass(frozen=True)
class Project:       id: str; datasets: tuple[Dataset, ...] = (); \
                     final_selection_mode: Literal["agent","human"] = "agent"
```

## Test Strategy

- [ ] `LatticeParams.volume()` が立方(a=b=c=5, 角90°)で 125.0 を返す
- [ ] `LatticeParams.volume()` が既知の三斜格子で解析式と一致する
- [ ] `PhaseInstance.with_updates(scale=2.0)` が新インスタンスを返し、元は不変(scale 据え置き)
- [ ] frozen dataclass への属性代入が `FrozenInstanceError` を送出する
- [ ] `Hypothesis` の既定 status が "candidate"、`Project` の既定 mode が "agent"
- [ ] 例外階層: `GuardrailError`/`EscalationRequired` が `TsumuginError` のサブクラス

## Implementation Notes

- `from __future__ import annotations` を各モジュール先頭に。
- `Mapping` の既定値は `field(default_factory=dict)`。frozen なので更新は `with_updates` 経由。
- volume は一般式: V = abc√(1−cos²α−cos²β−cos²γ+2cosαcosβcosγ)。

## Files

- 新規: src/tsumugin/__init__.py, src/tsumugin/errors.py,
        src/tsumugin/model/__init__.py, src/tsumugin/model/phase.py,
        src/tsumugin/model/hypothesis.py, src/tsumugin/model/project.py
- テスト: tests/test_model.py
