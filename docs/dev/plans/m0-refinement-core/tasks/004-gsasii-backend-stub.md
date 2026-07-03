---
id: "004"
title: "GSASIIBackend 薄いラッパと contract test スケルトン"
status: done
priority: 3
dependencies: ["002"]
estimated_complexity: low
---

# Task: GSASIIBackend 薄いラッパと contract test スケルトン

## Goal

GSAS-II (`GSASIIscriptable`) を将来差し込むための薄いラッパを定義し、未導入環境では明示的に
無効化する。contract test は GSAS-II 導入環境でのみ走る skip 条件付きにする。

## Interfaces

```python
# tsumugin/backends/gsasii.py
def gsasii_available() -> bool: ...                 # 🔵 import 可否を返す（副作用なし）

class GSASIIBackend:                                # 🟡 RefinementBackend 実装（薄いラッパ）
    name = "gsasii"
    def __init__(self, *, project_path: str | None = None): ...
    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult: ...
    # M0: 未導入時は __init__ で GSASUnavailableError を送出。
    #     導入時の refine 実体は最小(scale+lattice のみ)で可、詳細は M1+。

# tsumugin/errors.py に追加
class GSASUnavailableError(TsumuginError): ...      # 🔵
```

## Test Strategy

- [ ] `gsasii_available()` が bool を返し、例外を投げない（未導入でも False で正常終了）
- [ ] 未導入環境で `GSASIIBackend()` を生成すると `GSASUnavailableError`
- [ ] `@pytest.mark.gsas` 付き contract test は、未導入環境で自動 skip（収集エラーにならない）
- [ ] contract test（導入時のみ）: SimulatedBackend と同じ `RefinementModel` を受け、
      `RefinementResult` の形（converged: bool, rwp>=0）を満たす

## Implementation Notes

- `gsasii_available`: `importlib.util.find_spec("GSASIIscriptable") is not None` で判定（実 import しない）。
- conftest.py に `gsas` マーカーの自動 skip フック:
  `if item.get_closest_marker("gsas") and not gsasii_available(): pytest.skip(...)`。
- 未導入時に contract test 本体が import エラーで収集失敗しないよう、GSAS-II の import は関数内で遅延。

## Files

- 新規: src/tsumugin/backends/gsasii.py, tests/conftest.py
- 変更: src/tsumugin/errors.py（GSASUnavailableError 追加）
- テスト: tests/test_gsasii_backend.py
