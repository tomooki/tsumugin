---
id: "005"
title: "追記専用ハッシュチェーン Ledger を実装"
status: done
priority: 1
dependencies: ["001"]
estimated_complexity: low
---

# Task: 追記専用ハッシュチェーン Ledger を実装

## Goal

全状態遷移の単一記録先となる追記専用台帳。ハッシュチェーンで改竄検知(NFR-105)、
破壊的操作の API を一切持たない(P2 / NFR-101)。

## Interfaces

```python
# tsumugin/store/ledger.py
@dataclass(frozen=True)
class LedgerEntry:                                  # 🔵
    index: int
    kind: str                                       # "refine"|"guard"|"rollback"|"escalate"|"accept" 等
    payload: Mapping[str, Any]
    prev_hash: str
    hash: str
    def to_dict(self) -> dict: ...

class Ledger:                                       # 🔵 追記専用
    def __init__(self) -> None: ...
    def append(self, kind: str, payload: Mapping[str, Any]) -> LedgerEntry: ...  # 🔵 唯一の書き込み
    @property
    def entries(self) -> tuple[LedgerEntry, ...]: ...        # 🔵 読み取りは不変タプル
    def verify(self) -> bool: ...                            # 🔵 チェーン整合検証
    # 破壊的メソッド（delete/clear/update）は定義しない ← P2 の実装保証
```

## Test Strategy

- [ ] `append` 直後に `entries[-1]` が返り index が連番(0,1,2...)
- [ ] 各エントリの `prev_hash` が直前エントリの `hash` と一致（先頭は既知の genesis 値）
- [ ] `verify()` が正常チェーンで True
- [ ] 同一の (kind, payload) 列を同順で append すると hash 列がビット同一（決定論・NFR-102）
- [ ] payload の順序違い/値違いで hash が変わる（canonical JSON でキーソート）
- [ ] `Ledger` に delete/clear/pop 等の破壊的メソッドが存在しない（`hasattr` で否定確認）
- [ ] `entries` が返すタプルへの変更が内部状態に影響しない

## Implementation Notes

- hash = `sha256((prev_hash + canonical_json(payload) + kind + str(index)).encode()).hexdigest()`。
- canonical_json = `json.dumps(payload, sort_keys=True, separators=(",",":"), default=str)`。
- genesis prev_hash = "0"*64。
- 内部リストは private (`_entries`)、公開は `tuple(self._entries)`。

## Files

- 新規: src/tsumugin/store/__init__.py, src/tsumugin/store/ledger.py
- テスト: tests/test_ledger.py
