# TASK-0014 store/persistent — PersistentSnapshotStore TDD要件定義書

**機能名**: store/persistent（拡張）— `PersistentSnapshotStore(path, ledger=None)`（snapshot の JSONL 永続 + 再オープン復元/revert）
**タスクID**: TASK-0014
**要件名**: m2-sequential
**タスクタイプ**: TDD / **推定工数**: 3h / **フェーズ**: Phase 1 - モデル/永続化基盤
**作成日**: 2026-07-03
**出力ファイル**: `docs/implements/m2-sequential/TASK-0014/persistent-snapshot-store-requirements.md`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M2 永続化基盤として、非破壊 revert 対応のスナップショットストア `SnapshotStore` の
  **JSONL 永続版** `PersistentSnapshotStore(path, ledger=None)` を新設する。インメモリ `SnapshotStore`
  （`store/snapshot.py`）と**同一契約**（`save` / `load` / `revert` / `snapshots` / `current_id`）を持ち、
  (a) `save` は `Snapshot(id, label, phases, parent_id)` を構築し `phases` を `serialization.phase_to_dict` で
  dict 化して 1 snapshot = 1 行の JSONL へ追記モード（`"a"`）で書き込み、(b) `__init__(path, ledger)` は既存
  JSONL を読込んで各行を `phase_from_dict` で復元し全 snapshot を再構築、(c) 再オープン後も任意 snapshot_id へ
  revert でき、snapshot ID 連番が再オープン跨ぎで継続する。ledger 注入時は `snapshot_save` / `snapshot_revert`
  を ledger に記録する。
- 🔵 **どのような問題を解決するか**: 現行 `SnapshotStore` はインメモリ `list` のみでプロセス再起動をまたいだ
  状態スナップショットの永続化・復元ができない。逐次解析（M2）で各フレーム/各段の確定 phases を保存し、
  プロセス再起動後も任意の過去状態へ非破壊 revert できるようにするため、追記専用 + 非破壊 revert の不変条件を
  保ったまま JSONL シリアライズ層を足す。phases の直列化は TASK-0012 の `serialization`（非有限 → None 純化）を
  共有し、決定論的な JSON round-trip を保証する。
- 🔵 **想定されるユーザー**: 直接のユーザーは後続タスク（TASK-0019 の `SequentialEngine` へのストア注入）と、
  `StagedRefinementEngine` / `HypothesisTreeSearch` に snapshot ストアを注入する解析経路（REQ-012）。研究者は
  「再起動後も過去状態へ戻せる非破壊スナップショット」を得る形で間接的に依存する。本クラス自体は内部の
  永続化基盤であり外部 UI を持たない。
- 🔵 **システム内での位置づけ**: `src/tsumugin/store/` レイヤ（永続化基盤、最下層）の**既存モジュール
  `persistent.py` を拡張**（TASK-0013 で `PersistentLedger` を実装済み。本タスクは同ファイルに
  `PersistentSnapshotStore` を追加）。上位レイヤ（search / refinement / evidence）には**依存してはならない**
  （レイヤ逆依存の禁止）。phases の dict 変換は同層 `serialization.py`（`phase_to_dict` / `phase_from_dict`）を
  **共有**する（単一情報源・D-Q5）。ledger 永続化には同ファイルの `PersistentLedger` を注入して使う。
  標準ライブラリ（`json` / `pathlib` / `os`）+ 同層 `serialization` / `snapshot` のみで完結。
- **参照したEARS要件**: REQ-011（SnapshotStore を永続化・再オープン後に任意 snapshot_id へ revert 可能）、
  REQ-012（in-memory と同一 IF・既存エンジンに無改変注入）、REQ-401（削除・上書き・改変 API 不在）
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L284-292
  （`PersistentSnapshotStore` 契約）、`docs/design/m2-sequential/design-interview.md` D-Q5
  （serialization 分業・単一情報源・共有）、`docs/spec/m2-sequential/note.md`（store 永続化基盤・非破壊制約節）、
  `docs/implements/m2-sequential/TASK-0014/note.md`（本タスクノート）

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 PersistentSnapshotStore.__init__（新設 / `src/tsumugin/store/persistent.py` 拡張）🔵

- 🔵 **署名**: `def __init__(self, path: str | os.PathLike[str], ledger: Ledger | None = None) -> None`
  （`interfaces.py` L287 は `path: str, ledger: Ledger | None = None`。`os.PathLike` 許容は `tmp_path` テスト
  利便のための 🟡 拡張、`PersistentLedger` と同方針）
- 🔵 **入力**: snapshot JSONL ファイルパス、任意の `ledger`（監査記録用。`Ledger` / `PersistentLedger` いずれも可）。
  存在すれば既存 snapshot を読込み、存在しなければ空ストアとして扱う。
- 🔵 **動作**:
  1. ファイルが存在すれば 1 行ずつ読み、各行を `json.loads` して
     `{"id","label","parent_id","phases":[...]}` を取り出し、`phases` を `phase_from_dict` で
     `PhaseInstance` へ復元し `Snapshot(id, label, phases=tuple(...), parent_id)` を再構築する。
  2. 内部状態 `self._snaps: list[Snapshot]` / `self._index: dict[str, Snapshot]` を復元する。
  3. snapshot ID 連番の起点を復元数から継続できるようにし、`self._current_id` を**最後に save された
     snapshot の id（=最新）**へ設定する（後続 save の parent_id 連結・ID 連番継続を成立させる）🟡。
  4. 末尾の空行・改行のみの行はスキップする（正常な追記の副産物として許容）🟡。
- 🟡 **出力（副作用）**: 復元時はファイルへの書き込みを行わない（読み取りのみ。新規パスの場合はこの時点で
  ファイルを作らず、初回 `save` で追記作成する方針 — `PersistentLedger` と同じ）。
- **参照した設計文書**: `interfaces.py` L287、`snapshot.py`（`Snapshot` / `SnapshotStore.__init__`）、
  `serialization.py`（`phase_from_dict`）、`persistent.py`（`PersistentLedger` の再オープンパターン）

### 2.2 PersistentSnapshotStore.save（新設）🔵

- 🔵 **署名**: `def save(self, phases: tuple[PhaseInstance, ...], *, label: str) -> Snapshot`
  （`interfaces.py` L288 は `-> object`。実体は `store/snapshot.py` の `Snapshot`）
- 🔵 **入力**: `phases`（当該状態の相タプル）、`label`（keyword-only。snapshot ラベル）。
- 🔵 **動作**（in-memory `SnapshotStore.save` と同一意味論 + 追記 I/O）:
  1. `snap_id = f"snap-{len(self._snaps):04d}"`、`parent_id = self._current_id`。
  2. `snap = Snapshot(id=snap_id, label=label, phases=tuple(phases), parent_id=parent_id)` を構築。
  3. snapshot 行 `{"id": snap_id, "label": label, "parent_id": parent_id, "phases": [phase_to_dict(p) for p in phases]}`
     を `open(path, "a", encoding="utf-8")` で `json.dumps(row) + "\n"` として**1 行追記**する
     （**`"a"` モードのみ**。`"w"` / `"r+"` / `seek`+write / `truncate` を使わない — NFR-203）。
  4. 内部 `self._snaps` / `self._index` に追加し、`self._current_id = snap_id` に更新する。
  5. `ledger` が注入されていれば `ledger.append("snapshot_save", {"snapshot_id","label","parent_id","n_phases"})`
     を呼ぶ（in-memory `SnapshotStore.save` と同一 payload）。
  6. `snap` を返す。
- 🔵 **出力**: 追記された `Snapshot`（`store/snapshot.py` の既存型を再利用）。
- 🔵 **副作用**: snapshot JSONL 末尾に 1 行が追加されるのみ。**既存バイト列は不変**（追記前の先頭バイト列が保存される）。
  ledger 注入時は ledger 側にも `snapshot_save` が 1 件追記される。
- **参照した設計文書**: `interfaces.py` L288、`snapshot.py` L30-48（`SnapshotStore.save`）、
  `serialization.py` L53-92（`phase_to_dict`）、requirements REQ-011 / NFR-203

### 2.3 PersistentSnapshotStore.load（新設）🔵

- 🔵 **署名**: `def load(self, snapshot_id: str) -> Snapshot`（`interfaces.py` L289 は `-> object`。実体は `Snapshot`）
- 🔵 **動作**: `self._index[snapshot_id]` を返す（in-memory `SnapshotStore.load` と同一。欠落は KeyError）。
- 🔵 **出力**: 復元済みの `Snapshot`（phases は `phase_from_dict` で型復元済み）。
- **参照した設計文書**: `interfaces.py` L289、`snapshot.py` L50-51

### 2.4 PersistentSnapshotStore.revert（新設）🔵

- 🔵 **署名**: `def revert(self, snapshot_id: str) -> tuple[PhaseInstance, ...]`
- 🔵 **動作**（in-memory `SnapshotStore.revert` と同一意味論・**非破壊**）:
  1. `snap = self._index[snapshot_id]`（未知 id は KeyError）。
  2. `self._current_id = snapshot_id` に「現在位置」を移すだけ（**前方履歴の Snapshot を消さない**）。
  3. **snapshot JSONL へは書き込まない**（revert は状態遷移でありデータ追加ではない）。
  4. `ledger` 注入時は `ledger.append("snapshot_revert", {"snapshot_id","label"})` を呼ぶ（監査記録）。
  5. `snap.phases`（`tuple[PhaseInstance, ...]`）を返す。
- 🔵 **出力**: 指定 snapshot の phases タプル。
- 🔵 **副作用**: snapshot JSONL は**無変更**（revert は追記もしない）。ledger 注入時は ledger 側に
  `snapshot_revert` が 1 件追記される。
- **参照した設計文書**: `interfaces.py` L290、`snapshot.py` L53-61（`SnapshotStore.revert`）、REQ-011 / P2

### 2.5 PersistentSnapshotStore.snapshots / current_id（property）🔵

- 🔵 **署名**: `@property def snapshots(self) -> tuple[Snapshot, ...]` / `@property def current_id(self) -> str | None`
- 🔵 **出力**: `snapshots` = 現在の全 Snapshot の不変タプル（`tuple(self._snaps)`）。`current_id` = 現在位置の
  snapshot id（未 save/未 revert なら None、または再オープン時は最新 save の id）。in-memory `SnapshotStore` と同一。
- 🔵 **注記**: `interfaces.py` L291-292 は `snapshots` のみ明示するが、TASK-0014.md タスク概要が
  「save/load/revert/snapshots/**current_id**」を同一契約に含めるため `current_id` プロパティも実装する
  （in-memory `SnapshotStore` L67-69 と完全一致）。
- **参照した設計文書**: `interfaces.py` L291-292、`snapshot.py` L63-69、TASK-0014.md（同一契約の明示）

### 2.6 snapshot JSONL 行スキーマ 🔵

- 🔵 **1 行 = 1 snapshot**: `{"id": str, "label": str, "parent_id": str | None, "phases": [phase_to_dict(p), ...]}`。
  `phases` 配列は `serialization.phase_to_dict` の固定スキーマ dict の並び（JSON-safe・非有限 → None 済み）。
- 🟡 **設計判断**: ledger（`LedgerEntry.to_dict`）とは別スキーマ（snapshot は hash を持たない）。行スキーマは
  TASK-0019 の再注入が依存するため固定する。

### 2.7 入出力の関係性・データフロー 🔵

- **直列化（save）**: `save(phases, label)` → `Snapshot` 構築 → 行 dict（phases を `phase_to_dict`）→
  `json.dumps` → JSONL 1 行を `"a"` 追記。ledger 注入時は `snapshot_save` を ledger へ。
- **復元/検証（reopen）**: JSONL 各行 → `json.loads` → phases を `phase_from_dict` で復元 → `Snapshot` 再構築 →
  `_snaps` / `_index` / `_current_id` 復元 → `load` / `revert` / `snapshots` で提供。
- **revert**: `revert(id)` → `_current_id` を移す（前方履歴を消さない・追記なし）→ `snap.phases` 返却。
  ledger 注入時は `snapshot_revert` を ledger へ。
- **参照したEARS要件**: REQ-011、REQ-012、REQ-401
- **参照した設計文書**: `docs/design/m2-sequential/dataflow.md`、`interfaces.py` L256-292、`serialization.py`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **追記モード（`"a"`）のみ / 非破壊（NFR-203 / P2 / NFR-101 / REQ-401）**: save の書き込みは
  `open(path, "a")` による 1 行追記のみ。既存バイト列を書き換える操作（`"w"` / `"r+"` / `seek`+write /
  `truncate`）を使わない。**削除・上書き・改変 API を一切実装しない**（`SnapshotStore` と同じく
  `save` / `load` / `revert` / `snapshots` / `current_id` のみ）。
- 🔵 **非破壊 revert（REQ-011 / P2）**: revert は前方履歴を消さず「現在位置」を移すだけ。**snapshot JSONL へ
  追記もしない**（監査は ledger 側の `snapshot_revert` で表現）。未知 id は KeyError（in-memory と同一縮退）。
- 🔵 **同一契約 / 無改変注入（REQ-012 / P7）**: `save(phases, *, label) -> Snapshot`（`.id` を持つ）/
  `load` / `revert(id) -> tuple` / `snapshots` / `current_id` の署名を in-memory `SnapshotStore` と一致させ、
  `StagedRefinementEngine(..., store=...)` / `HypothesisTreeSearch(..., snapshots=...)` /
  `SequentialEngine(..., snapshots=...)` へ**無改変で注入可能**にする。
- 🔵 **phases 等価復元（REQ-011 / TC-106-03）**: `phase_from_dict(phase_to_dict(p))` が有限値・全フィールド
  定義済みの phase で**値等価**（frozen dataclass `__eq__`）になることに依拠し、save → 再オープン → load/revert で
  phases を等価復元する。非有限（inf/NaN）→ None → 既定補完・欠損キー → 既定補完のため、**厳密等価は
  有限値 phase で成立**（M0 SimulatedBackend 経路は有限値で TC-106-06 が成立）。
- 🔵 **決定論（NFR-102 / REQ-402）**: 乱数不使用。snapshot ID は `snap-{i:04d}` 連番、phases 直列化は
  `serialization` の固定スキーマ（キー順固定）。同一入力で snapshot 行がビット同一になる。
- 🔵 **レイヤ制約（アーキテクチャ）**: `store/` は最下層。上位（search / refinement）を import しない。
  phases 変換は同層 `serialization.py` を共有し、ledger 永続化は同層 `persistent.py::PersistentLedger` を注入する。
- 🔵 **既存実装の挙動不変**: `snapshot.py` / `serialization.py` / `persistent.py::PersistentLedger` は
  共有/契約の範として使うのみで**改変しない**（既存 `tests/test_snapshot.py` / `test_serialization.py` /
  `test_persistent_store.py`（TASK-0013 分 14 件）が緑のまま）。
- 🟡 **破損検出は非スコープ**: snapshot JSONL はハッシュチェーンではない（Snapshot に hash なし）。
  `PersistentLedger` の `LedgerIntegrityError` 相当の改竄検出は本タスクのスコープ外（監査の完全性は注入 ledger が担保）。
  再オープンは行を読んで復元するのみ。破損 snapshot 行の頑健化は最小に留める（末尾空行スキップは許容してよい）。
- 🔵 **型注釈必須**: `tuple[PhaseInstance, ...]` / `tuple[Snapshot, ...]` / `str | None` を正しく付す。
  `from __future__ import annotations`。`any` 回避。
- 🔵 **命名規則 / Lint**: クラス PascalCase、内部ヘルパは `_` 接頭辞、snapshot ID は `snap-{i:04d}`。
  `uvx ruff check src tests`（line-length 100, target py312）準拠。
- 🔴 **git commit しない**（ユーザー判断。本セッション制約）。**質問しない**（自律実行）。

- **参照したEARS要件**: REQ-011 / REQ-012 / REQ-401 / REQ-402、NFR-101 / NFR-102 / NFR-203
- **参照した設計文書**: `interfaces.py`（L256-292）、`design-interview.md`（D-Q5）、
  `docs/spec/m2-sequential/note.md`（非破壊/レイヤ制約節）、`docs/spec/m2-sequential/requirements.md`、`CLAUDE.md`（不変条件）

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

- **永続保存 → 再オープン復元**: `st = PersistentSnapshotStore(path)` → `st.save(phases0, label="init")` /
  `st.save(phases1, label="stage")` を複数回 → プロセス再起動相当で `st2 = PersistentSnapshotStore(path)`（同一パス）→
  `st2.load("snap-0000").phases == phases0`・`st2.revert("snap-0000") == phases0`（等価復元）（TC-106-03）。
- **snapshot ID 連番の再オープン跨ぎ継続**: `st.save(...)` → `snap-0000` → 再オープン → `st2.save(...)` →
  `snap-0001`（復元数から連番継続）。`parent_id` も直前 snapshot に連結。
- **ledger 連携**: `PersistentSnapshotStore(path, ledger=pl)` で save → `snapshot_save`、revert → `snapshot_revert`
  が ledger（`PersistentLedger`）へ追記され、ledger 再オープンで `verify()` True。
- **エンジンへの注入（TC-106-06）**: `StagedRefinementEngine(SimulatedBackend(), store=PersistentSnapshotStore(path),
  ledger=Ledger())` を `.run(...)` → M0 経路が無改変で完走し、in-memory `SnapshotStore` 版と等価な `RefinementReport`。

### 4.2 データフロー 🔵

- 直列化: `save` → `Snapshot`（phases を `phase_to_dict`）→ `to row dict` → `json.dumps` → JSONL 1 行を `"a"` 追記。
- 復元: JSONL 各行 → `json.loads` → `phase_from_dict` で phases 復元 → `Snapshot` 再構築 → `load`/`revert`/`snapshots` 提供。

### 4.3 エッジケース 🔵🟡

- 🟡 **空/新規ファイル**: 存在しないパスで開く → 空ストア（`snapshots == ()`・`current_id is None`）→ 初回 `save` で
  ファイル新規作成（`"a"` は不在ファイルを作成する）。
- 🔵 **空 phases のスナップショット**: `save((), label="empty")` → `phases` 空タプルの Snapshot → 再オープンで
  空タプル復元（`n_phases=0` の境界）。
- 🔵 **1 件のみ / 多数件**: snapshot 0/1/多数のいずれでも復元・load・revert が一貫して機能する。
- 🟡 **末尾の空行・改行のみ**: 正常な追記の副産物としてスキップ（`PersistentLedger` と同じ許容）。
- 🔵 **revert 後の save**: revert で現在位置を過去へ戻した後の save も `snap-{len:04d}` で新規 ID を発番し
  前方履歴を消さない（分岐履歴が追記で保持される）。

### 4.4 エラーケース 🔵🟡

- 🔵 **存在しない snapshot_id**: `load`/`revert` に未知 id → KeyError（in-memory `SnapshotStore` と同一縮退。
  握り潰さない）。
- 🟡 **破損 snapshot 行（非スコープの縮退）**: 不正 JSON 行の扱いは最小（末尾空行スキップ以外の堅牢化は本タスクで
  深追いしない）。監査完全性は注入 ledger の `verify()` で担保する。
- 🔴 **注意（非スコープ）**: 並行書き込み時のファイルロック・アトミック追記（fsync 等）は本タスクでは扱わない
  （単一プロセス・逐次追記の前提。堅牢化は将来タスク）。

- **参照したEARS要件**: REQ-011 / REQ-012 / REQ-401、NFR-203
- **参照した設計文書**: `docs/design/m2-sequential/dataflow.md`、`interfaces.py`（L256-292）、
  `docs/spec/m2-sequential/acceptance-criteria.md`（TC-106-03/05/06）

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: m2-sequential 永続化・再現性（プロセス再起動をまたぐ状態スナップショットの
  復元・非破壊 revert, user-stories.md）
- **参照した機能要件**:
  - REQ-011（SnapshotStore を永続化。再オープン後に任意 snapshot_id へ revert 可能）
  - REQ-012（永続化ストアは in-memory と同一 IF、既存エンジンに無改変注入）
  - REQ-401（永続化ストアにも削除・上書き・改変 API を実装しない。追記 + revert のみ）
  - REQ-402（同一入力で全出力ビット同一 = 決定論）
- **参照した非機能要件**: NFR-101（追記/非破壊 P2）、NFR-102（決定論・ビット同一）、
  NFR-203（追記モード `"a"` のみ・既存バイト列不変）
- **参照したEdgeケース**: （snapshot 固有の Edge は acceptance-criteria に個別 ID なし。空/新規・空 phases・
  未知 id は M0/M1 の縮退規約を踏襲。EDGE-003 のファイル破損は ledger 側 = TASK-0013 のスコープ）
- **参照した受け入れ基準**（`docs/spec/m2-sequential/acceptance-criteria.md`）:
  - TC-106-03（PersistentSnapshotStore の save → 再オープン → revert で状態復元）
  - TC-106-05（削除・上書き API が存在しない。hasattr 否定、in-memory 版と同一検証）
  - TC-106-06（既存エンジンに Persistent 版を注入して M0/M1 経路が無改変で動く。REQ-012）
  - （TC-106-01/02/04/07 = PersistentLedger は TASK-0013 で実装済み。本タスク対象外）
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md`（store 永続化基盤層・レイヤ分離・設計 D4）
  - **データフロー**: `docs/design/m2-sequential/dataflow.md`（直列化/復元・revert パス）
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L284-292（`PersistentSnapshotStore`）、
    L237-249（`SequentialEngine` の snapshots 注入）、L261-262（`phase_to_dict` / `phase_from_dict`）
  - **設計ヒアリング**: `docs/design/m2-sequential/design-interview.md` D-Q5（serialization 独立モジュール・
    単一情報源・共有）
  - **既存実装**: `src/tsumugin/store/snapshot.py`（`Snapshot` / `SnapshotStore` の同一契約の範）、
    `src/tsumugin/store/serialization.py`（`phase_to_dict` / `phase_from_dict` 共有）、
    `src/tsumugin/store/persistent.py`（`PersistentLedger` の追記 I/O・再オープンパターン・注入先）、
    `src/tsumugin/refinement/staged.py`（`StagedRefinementEngine` の store 注入点 = TC-106-06）
  - **タスク定義**: `docs/tasks/m2-sequential/TASK-0014.md`
  - **コンテキストノート**: `docs/implements/m2-sequential/TASK-0014/note.md`
  - **先行 TDD 成果物（様式）**: `docs/implements/m2-sequential/TASK-0013/persistent-ledger-requirements.md`

---

## 完了条件（タスク定義より）

- [ ] save → 再オープン → load/revert で phases 等価復元 🔵 *TC-106-03*
- [ ] snapshot ID 連番が再オープン跨ぎで継続 🔵
- [ ] 削除・上書き API 不在 🔵 *TC-106-05*
- [ ] `StagedRefinementEngine` に注入して M0 経路が無改変で動く 🔵 *TC-106-06 / REQ-012*
- [ ] ledger 連携時 `snapshot_save` / `snapshot_revert` が記録される 🔵

## 信頼性レベルサマリー

- 🔵 青信号: 機能概要・システム内位置づけ・同一契約（save/load/revert/snapshots/current_id）・phases 等価復元・
  非破壊 revert・追記モード限定・決定論・エンジン注入・完了条件は interfaces.py（L284-292）/ requirements.md /
  既存 `snapshot.py` / `serialization.py` 実装に直接依拠。
- 🟡 黄信号: `os.PathLike` 許容・新規ファイル生成タイミング・再オープン時の current_id を最新 save に設定する挙動・
  末尾空行スキップ・破損行の頑健化を最小に留める点は設計文書からの妥当な具体化。
- 🔴 赤信号: git commit しない / 質問しない のセッション運用制約、並行書き込みロックを非スコープとする旨のみ。
- **品質判定**: 高品質 — 要件の曖昧さなし / 入出力定義完全（5 メソッド + 行スキーマの署名・動作確定）/ 制約条件明確
  （追記のみ・非破壊 revert・決定論・同一契約）/ 実装可能性確実（標準ライブラリ + 既存 `snapshot`/`serialization`/
  `persistent` の共有のみ）。

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m2-sequential TASK-0014` でテストケースの洗い出しを行います。
