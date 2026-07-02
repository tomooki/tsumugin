---
id: "002"
title: "RefinementBackend 抽象インターフェースを定義"
status: done
priority: 1
dependencies: ["001"]
estimated_complexity: low
---

# Task: RefinementBackend 抽象インターフェースを定義

## Goal

精密化バックエンドの交換可能性(P7)を担保する Protocol と、入出力の値オブジェクトを定義する。
これが SimulatedBackend / GSASIIBackend / 段階エンジンの契約書になる。

## Interfaces

```python
# tsumugin/backends/base.py
@dataclass(frozen=True)
class RefinementModel:                              # 🔵 精密化への入力
    phases: tuple[PhaseInstance, ...]
    free_params: frozenset[str]                     # 解放中パラメータ名 ("phase0.scale" 等)
    two_theta: "np.ndarray"                         # 観測 x
    intensity: "np.ndarray"                         # 観測 y
    weights: "np.ndarray" | None = None             # 統計重み(既定 1/y)

@dataclass(frozen=True)
class RefinementResult:                             # 🔵 精密化からの出力
    phases: tuple[PhaseInstance, ...]               # 更新後
    chi2: float
    rwp: float
    n_obs: int
    n_params: int                                   # = len(free_params)
    converged: bool
    n_cycles: int

class RefinementBackend(Protocol):                  # 🔵 P7 交換可能境界
    name: str
    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult: ...

# パラメータ名の正準化ヘルパ
def param_name(phase_index: int, key: str) -> str: ...   # 🟡 "phase{i}.{key}"
def parse_param(name: str) -> tuple[int, str]: ...       # 🟡 逆変換
```

## Test Strategy

- [ ] `param_name(0, "scale") == "phase0.scale"`、`parse_param` が逆変換で `(0,"scale")`
- [ ] `parse_param("phase2.lattice.a")` が `(2, "lattice.a")` を返す(ドット複数対応)
- [ ] `RefinementModel` / `RefinementResult` が frozen（属性代入で FrozenInstanceError）
- [ ] Protocol を満たすダミークラスが `isinstance(obj, RefinementBackend)` を通す
      (`runtime_checkable`)

## Implementation Notes

- `Protocol` は `typing.runtime_checkable` を付与し、テストで構造的部分型を検証。
- numpy 配列は型注釈のみ(実体は task 003 で使用)。import は `import numpy as np`。
- `parse_param`: 最初のドットで phase インデックス、残りをキーとして返す。

## Files

- 新規: src/tsumugin/backends/__init__.py, src/tsumugin/backends/base.py
- テスト: tests/test_backend_interface.py
