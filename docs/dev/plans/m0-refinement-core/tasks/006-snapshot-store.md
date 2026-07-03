---
id: "006"
title: "SnapshotStore（非破壊 revert）を実装"
status: done
priority: 2
dependencies: ["001", "005"]
estimated_complexity: medium
---

# Task: SnapshotStore（非破壊 revert）を実装

## Goal

任意時点の解析状態を保存し、任意スナップショットへ revert できるストア。revert は
前方履歴を削除せず、新しい状態を返すだけ(P2)。保存/復帰は ledger に記録する。

## Interfaces

```python
# tsumugin/store/snapshot.py
@dataclass(frozen=True)
class Snapshot:                                     # 🔵
    id: str                                         # 決定論 ID（連番 or 内容ハッシュ）
    label: str
    phases: tuple[PhaseInstance, ...]               # 保存された状態（frozen）
    parent_id: str | None

class SnapshotStore:                                # 🔵
    def __init__(self, ledger: Ledger | None = None) -> None: ...
    def save(self, phases: tuple[PhaseInstance, ...], *, label: str) -> Snapshot: ...  # 🔵 追記
    def load(self, snapshot_id: str) -> Snapshot: ...                                  # 🔵
    def revert(self, snapshot_id: str) -> tuple[PhaseInstance, ...]: ...  # 🔵 状態を返すのみ
    @property
    def snapshots(self) -> tuple[Snapshot, ...]: ...
    # delete/overwrite は定義しない ← P2
```

## Test Strategy

- [ ] `save` した Snapshot を `load(id)` で同一内容取得（phases 一致）
- [ ] `save` の ID が連番/決定論的（同じ内容列で同じ ID 列）
- [ ] `revert(古いID)` が古い phases を返し、その後も `snapshots` に全履歴が残る（前方も消えない）
- [ ] revert 後に新規 save すると parent が正しく連結される
- [ ] ledger 連携時: save/revert で ledger に "snapshot_save"/"snapshot_revert" が追記される
- [ ] 存在しない ID の load で `KeyError`（TsumuginError 派生でも可）
- [ ] delete/clear 等の破壊的メソッドが存在しない

## Implementation Notes

- Snapshot ID は `f"snap-{len(self._snaps):04d}"` の連番（決定論）。
- phases は frozen dataclass のタプルなのでディープコピー不要（不変）。
- ledger が渡された場合のみ append。payload には snapshot_id と label、phase 数を含める（生データは載せない）。

## Files

- 新規: src/tsumugin/store/snapshot.py
- テスト: tests/test_snapshot.py
