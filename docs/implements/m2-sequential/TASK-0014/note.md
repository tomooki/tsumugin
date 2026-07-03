# TASK-0014 TDD 開発コンテキストノート

**タスク**: store/persistent（拡張）— `PersistentSnapshotStore(path, ledger=None)`（snapshot の JSONL 永続 + 再オープン復元/revert）
**要件名**: m2-sequential / **タスクID**: TASK-0014 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 1 モデル/永続化基盤 / **信頼性**: 🔵 REQ-011/012/401・NFR-203・設計 D4/D-Q5・interfaces.py L284-292
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨（最優先で守る不変条件）

`src/tsumugin/store/persistent.py` を**拡張**し（TASK-0013 で新規作成済み・`PersistentLedger` が同居）、
`PersistentSnapshotStore(path, ledger=None)` を実装する。インメモリの `SnapshotStore`
（`store/snapshot.py`）と**同一契約**（`save` / `load` / `revert` / `snapshots` / `current_id`）を持つ
JSONL 永続版。phases は `store/serialization.py`（TASK-0012 実装済み）の `phase_to_dict` /
`phase_from_dict` で dict 化して 1 snapshot = 1 行の JSONL に追記する。再オープンで全 snapshot を
復元し、任意 snapshot_id へ revert できる。

- **save**: `Snapshot(id, label, phases, parent_id)` を構築し、`{"id","label","parent_id","phases":[phase_to_dict(p),...]}`
  を**追記モード（`"a"` のみ）**で JSONL へ 1 行書き込む（NFR-203）。snapshot ID は `snap-{連番:04d}`。
- **オープン時**: 既存 JSONL を読込み、各行を `phase_from_dict` で復元して `Snapshot` を再構築。
  snapshot ID 連番と `current_id` を復元し、続きから save/revert 可能にする（TC-106-03）。
- **revert**: 前方履歴を消さず「現在位置」を移すだけ（非破壊 revert）。snapshot ファイルへは**追記しない**
  （revert は状態遷移で、ledger 注入時のみ `snapshot_revert` を ledger へ記録）。
- **削除・上書き・改変 API は実装しない**（P2 / NFR-101 / REQ-401）。追記 + revert のみ。

**🚨 絶対制約（完了条件と直結）**:
- save → 再オープン → load/revert で phases が**等価復元** 🔵 *TC-106-03*
- snapshot ID 連番が**再オープン跨ぎで継続**（reopen 後の save が `snap-000N` を継続）🔵
- 削除・上書き API 不在（`hasattr` 否定・in-memory `SnapshotStore` と同一表面積）🔵 *TC-106-05*
- `StagedRefinementEngine` に**無改変注入**して M0 経路が動く（in-memory 版と同結果）🔵 *TC-106-06 / REQ-012*
- ledger 連携時に `snapshot_save` / `snapshot_revert` が記録される 🔵
- **git commit しない**（ユーザー判断）。**質問しない**（自律実行）。

**参照元**: `docs/tasks/m2-sequential/TASK-0014.md`,
`docs/design/m2-sequential/interfaces.py`（L284-292: `PersistentSnapshotStore`）,
`docs/design/m2-sequential/design-interview.md`（D-Q5: serialization 分業・共有）,
`docs/spec/m2-sequential/requirements.md`（REQ-011/012/401, NFR-203, EDGE 群）,
`docs/spec/m2-sequential/acceptance-criteria.md`（TC-106-03/05/06）

---

## 1. 技術スタック

- **言語**: Python >= 3.12（uv 管理, src layout + hatchling）。本タスクは**標準ライブラリ
  （`json` / `pathlib` / `os`）+ 同層の `serialization` / `snapshot` のみ**で完結。numpy にも GSAS-II にも
  依存しない純粋な永続化 I/O。
- **アーキテクチャパターン**: 追記専用 snapshot ストアの永続化層。frozen dataclass `Snapshot`
  （`snapshot.py` 既存）を JSONL の 1 行 = 1 snapshot へ写像し、phases は `phase_to_dict`/`phase_from_dict`
  で JSON 可換 dict へ相互変換して再構築する境界層。`store/` レイヤ（最下層の永続化基盤）に属し、
  上位（search / refinement / evidence）に依存しない。
- **モジュール配置**: `src/tsumugin/store/persistent.py`（**既存を拡張**。`PersistentLedger` に
  `PersistentSnapshotStore` を追加）。同層に `ledger.py`・`snapshot.py`・`serialization.py` が既存。
- **JSONL 選定の根拠**: 仕様 §3 Data Layer（Project Store = HDF5 + SQLite）の**軽量案**として、
  M2 は追記専用 + 非破壊 revert の不変条件を保ったまま JSON Lines でシリアライズ（requirements interview Q4 / D-Q5）。
  ledger（TASK-0013）と同じ 1 行 = 1 レコードの行指向で統一。
- **参照元**: `docs/spec/m2-sequential/note.md`（技術スタック節）, `pyproject.toml`, `CLAUDE.md`,
  `docs/implements/m2-sequential/TASK-0013/note.md`（JSONL 永続化の先例）

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE。
  内部ヘルパは先頭 `_`（既存 `persistent.py`/`snapshot.py` に倣う）。snapshot ID は `snap-{i:04d}`（`snapshot.py` と同一）。
- **型注釈必須**（`any` 回避）。docstring 日本語可、FR/NFR/REQ/TC 番号を docstring に紐づける慣習。
- **フォーマット/Lint**: `uvx ruff check src tests`（line-length 100, target py312）。
- **データモデリング**: frozen dataclass 基本。`Snapshot`/`PhaseInstance` は無改変で再利用（新規生成のみ）。
- **git commit はユーザー判断**（本セッションでは commit 禁止）。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **公開 API**: `src/tsumugin/__init__.py::__all__` はアルファベット昇順必須
  （`test_m1_symbols_in_dunder_all_and_sorted` が固定）。`PersistentSnapshotStore` を top-level 公開する場合は
  昇順を維持（最小構成は `store/__init__.py` re-export でも可・要判断。`PersistentLedger` の公開方針に合わせる）。
- **参照元**: `docs/spec/m2-sequential/note.md`（開発ルール節）, `CLAUDE.md`,
  `src/tsumugin/__init__.py`, `src/tsumugin/store/__init__.py`

---

## 3. 関連実装（拡張・共有先・注入先）

### 拡張対象 / 同一契約の範（snapshot.py — SnapshotStore の単一契約）
- `src/tsumugin/store/snapshot.py`:
  - `Snapshot(id, label, phases: tuple[PhaseInstance,...], parent_id: str|None)`（frozen, L15-20）。
    **PersistentSnapshotStore.save/load はこの型を返す**（同一契約）。
  - `SnapshotStore.save(phases, *, label) -> Snapshot`（L30-48）:
    `snap_id = f"snap-{len(self._snaps):04d}"`、`parent_id = self._current_id`、`_current_id = snap_id` に更新。
    ledger 注入時は `append("snapshot_save", {"snapshot_id","label","parent_id","n_phases"})`。
    **PersistentSnapshotStore.save も同じ規約**に JSONL 追記 I/O を足す。
  - `SnapshotStore.load(snapshot_id) -> Snapshot`（L50-51）: `self._index[snapshot_id]`（欠落は KeyError）。
  - `SnapshotStore.revert(snapshot_id) -> tuple[PhaseInstance,...]`（L53-61）: `_current_id = snapshot_id` に移すだけ
    （前方履歴を消さない）。ledger 注入時は `append("snapshot_revert", {"snapshot_id","label"})`。
  - `snapshots -> tuple[Snapshot,...]`（L63-65） / `current_id -> str|None`（L67-69）。
  - **注**: interfaces.py L284-292 は `current_id` を明示しないが、TASK-0014.md が「save/load/revert/snapshots/**current_id**」を
    同一契約に含めるため `current_id` プロパティも実装する（in-memory `SnapshotStore` と完全一致させる）。

### 共有する既存実装（serialization.py — phase の JSON 相互変換）
- `src/tsumugin/store/serialization.py`（TASK-0012 実装済み）:
  - `phase_to_dict(phase) -> dict`（L53-92）: `json.dumps(allow_nan=False)` 可能な素の dict を生成。
    非有限（inf/NaN）→ None 純化。固定スキーマ（`phase_ref`/`lattice{a,b,c,alpha,beta,gamma,sigma}`/`scale`/
    `wt_frac`/`occupancies`/`lifecycle`）。**snapshot 行の phases 配列にこの出力を並べる**。
  - `phase_from_dict(data) -> PhaseInstance`（L95-140）: dict から `PhaseInstance` を型復元
    （lattice→`LatticeParams`、lifecycle→`PhaseLifecycle`）。未知キー無視・欠損既定補完。
    **再オープン時に snapshot 行の phases を復元**する。
  - **roundtrip 等価性**: 有限値・全フィールド定義済みの phase は `phase_from_dict(phase_to_dict(p)) == p`
    （frozen dataclass の値等価）。非有限や欠損は既定補完されるため、テストは有限値 phase で等価を確認する
    （M0 SimulatedBackend 経路は有限値のため TC-106-06 で等価が成立）。

### 共有する既存実装（persistent.py — 追記 I/O・再オープンの範）
- `src/tsumugin/store/persistent.py`（TASK-0013 実装済み・**本タスクが拡張**）:
  - `PersistentLedger.__init__` の**既存ファイル読込パターン**（`self._path.exists()` → `read_text().splitlines()` →
    空行スキップ → 各行 `json.loads`）を snapshot 復元にも踏襲。
  - `PersistentLedger.append` の**追記 I/O パターン**（`open(path, "a", encoding="utf-8")` で
    `json.dumps(...) + "\n"` を 1 行追記）を snapshot save にも踏襲（NFR-203）。
  - ledger 注入時は**このクラス（PersistentLedger）を snapshot ストアの ledger 引数へ渡す**ことで、
    `snapshot_save`/`snapshot_revert` も JSONL 永続化される（ledger ファイルと snapshot ファイルは別パス）。

### 注入先（TC-106-06 — StagedRefinementEngine への無改変注入）
- `src/tsumugin/refinement/staged.py`:
  - `StagedRefinementEngine(backend, store: SnapshotStore, ledger: Ledger, ...)`（L65-83）。
  - `.run(...)` 内で `self.store.save(current, label=stage.name)`（L131）→ 戻り値 `snap` の `snap.id` を使い、
    ガード違反/悪化時に `self.store.revert(snap.id)`（L171/L197）で phases tuple を取り戻す。
  - **PersistentSnapshotStore が `save(...).id` と `revert(id) -> tuple` を満たせば、engine を一切改変せず
    差し替え可能**（ダックタイピング / REQ-012 / P7）。TC-106-06 はこの差し替えで M0 経路が壊れないことを確認。

### snapshot ファイルと ledger ファイルの関係（2 ファイル構成）
- PersistentSnapshotStore は**自身の snapshot JSONL（save の phases 本体）**を `path` に持ち、
  監査 ledger は注入された `ledger`（`PersistentLedger(別パス)`）に記録する。両者は独立ファイル。
  完全永続監査は `PersistentSnapshotStore(snapshots.jsonl, ledger=PersistentLedger(ledger.jsonl))` で構成する。

- **参照元**: `src/tsumugin/store/{snapshot,serialization,persistent,ledger,__init__}.py`,
  `src/tsumugin/refinement/staged.py`, `src/tsumugin/model/{phase}.py`,
  `docs/design/m2-sequential/interfaces.py`（L284-292）

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py`
  - L284-292: `class PersistentSnapshotStore`（`SnapshotStore と同一契約の JSONL 永続版。🔵 REQ-011/012/401`）:
    - `__init__(self, path: str, ledger: Ledger | None = None) -> None`
    - `save(self, phases: tuple[PhaseInstance, ...], *, label: str) -> object`（実体は `Snapshot`）
    - `load(self, snapshot_id: str) -> object`（実体は `Snapshot`）
    - `revert(self, snapshot_id: str) -> tuple[PhaseInstance, ...]`
    - `snapshots -> tuple`（property） / （+ `current_id` — TASK-0014.md の同一契約に含む）
  - L237-249: `SequentialEngine(..., snapshots: SnapshotStore | None = None)` — **Persistent 版を注入可能**（REQ-012）。
- **設計判断 D4**（永続化の位置づけ）/ **D-Q5**（serialization 分業・単一情報源・共有）:
  `docs/design/m2-sequential/design-interview.md`（D-Q5 は L29-35）。
  「`store/serialization.py`（phase の dict 相互変換）を独立モジュールにし、persistent.py と将来の Project Store が共有」。
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-011（L55-56）: SnapshotStore を永続化し、再オープン後に任意 snapshot_id へ revert 可能。🔵 *P2*
  - REQ-012（L57-58）: 永続化ストアは in-memory と同一 IF、既存エンジンに無改変注入。🔵 *P7*
  - REQ-401（L94）: 永続化ストアにも削除・上書き・改変 API を実装しない（追記 + revert のみ）。🔵 *P2/NFR-101*
  - REQ-402（L95）: 同一入力・同一設定で全出力ビット同一（決定論）。🔵 *NFR-102*
  - NFR-203（L107）: 書き込みは追記モード（`"a"`）のみ。既存バイト列を書き換えない。🔵 *P2*
- **受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md`
  - TC-106-03（L64）: PersistentSnapshotStore の save → 再オープン → revert で状態復元。
  - TC-106-05（L66）: 削除・上書き API が存在しない（`hasattr` 否定、in-memory 版と同一検証）。
  - TC-106-06（L67）: 既存エンジンに（Persistent 版を）注入して M0/M1 経路が無改変で動く（REQ-012）。
  - （TC-106-01/02/04/07 = PersistentLedger は **TASK-0013 で実装済み**。本タスク対象外だが同ファイル同ノリ。）
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §3 Data Layer（HDF5 + SQLite。M2 は JSONL 軽量案）。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest tests/test_persistent_store.py`（本タスク単体）/ `uv run pytest`（全体回帰）/
  `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas`（プレーン `uv sync` は禁止）。
  本タスクは **GSAS-II 非依存**のためマーカー不要（`gsas` マーカーは付けない）。
- **本タスクのテストファイル**: `tests/test_persistent_store.py`（**既存に追加**。TASK-0013 の `PersistentLedger` テスト
  14 件が既に在る。`PersistentSnapshotStore` のテストを同ファイルへ追記する — TASK-0014.md 明記）。
  テスト対象 `src/tsumugin/store/persistent.py`（拡張）。
- **import**: `from tsumugin.store.persistent import PersistentLedger, PersistentSnapshotStore`、
  `from tsumugin.store.snapshot import Snapshot, SnapshotStore`、`from tsumugin.model import PhaseInstance, LatticeParams`、
  `from tsumugin.refinement.staged import StagedRefinementEngine`、`from tsumugin.backends.simulated import SimulatedBackend`。
- **既存テスト構成（1:1 対応）**: `tests/` 直下に impl と対応する `test_*.py`。snapshot の in-memory テストは
  `tests/test_snapshot.py`（SnapshotStore 契約の先例）。ledger 永続テストは `tests/test_persistent_store.py`（TASK-0013）。
- **一時ファイル**: `tmp_path`（pytest 組み込みフィクスチャ）。snapshot JSONL は `tmp_path / "snapshots.jsonl"`、
  ledger は `tmp_path / "ledger.jsonl"` で分離確保。ファイル無変更検証は書き込み前後のバイト列 read 比較。
- **命名/記述パターン**（`tests/test_persistent_store.py`（TASK-0013）/ `tests/test_snapshot.py` に準拠）:
  - 関数名 `test_...`。docstring/コメントに【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
- **本タスクで書くべき代表テスト観点**（受け入れ基準・完了条件より）:
  - **永続 roundtrip（TC-106-03）**: save 複数 → 別インスタンスで再オープン → `load(id)` の phases 等価・
    `revert(id)` の phases tuple 等価。`PhaseInstance` の値等価（frozen dataclass `__eq__`）で確認。
  - **snapshot ID 連番継続**: save で `snap-0000` → 再オープン → save で `snap-0001`（再オープン跨ぎで連番継続）。
  - **ledger 連携**: `ledger` 注入で save → `snapshot_save` エントリ、revert → `snapshot_revert` エントリが記録され、
    payload（snapshot_id 等）が in-memory `SnapshotStore` と一致（PersistentLedger 注入時は再オープン verify も可）。
  - **エンジン注入（TC-106-06）**: `StagedRefinementEngine(SimulatedBackend(), store=PersistentSnapshotStore(...), ledger=...)`
    を `.run(...)` し、in-memory `SnapshotStore` で走らせた結果と**等価**（`RefinementReport` の final_phases/metrics 一致・
    `ledger.verify()` True）。M0 経路が無改変で完走することを確認。
  - **API 不在（P2 / TC-106-05）**: `not hasattr(store, "delete")` 等。in-memory `SnapshotStore` と同じ属性集合
    （save/load/revert/snapshots/current_id）であること。
  - **追記のみ成長（NFR-203）**: save 前後で snapshot JSONL の先頭バイト列が不変（末尾に 1 行増えるだけ）。
  - **非破壊 revert**: revert は snapshot JSONL へ追記しない（revert 前後で行数/バイト列不変）。前方履歴を消さない。
  - **新規/空パス境界**: 不在パスで開く → `snapshots == ()`・初回 save でファイル新規作成。
  - **存在しない id**: `load`/`revert` に未知 id → KeyError（in-memory と同一縮退）。
- **回帰確認（完了ゲート）**: `uv run pytest` 全体で既存テスト（M0/M1/M2 TASK-0011〜0013）を**壊さない**
  （新規テスト分のみ増加）。`persistent.py` 拡張・`serialization`/`snapshot` 共有は既存挙動不変。
- **参照元**: `pyproject.toml`, `tests/test_persistent_store.py`, `tests/test_snapshot.py`, `tests/conftest.py`,
  `docs/spec/m2-sequential/acceptance-criteria.md`（TC-106）

---

## 6. 注意事項

### 技術的制約
- **追記モード（`"a"`）のみ**（NFR-203 / P2）: save は必ず `open(path, "a", encoding="utf-8")` で
  1 行（`json.dumps(snapshot_row) + "\n"`）を書く。`"w"` / `"r+"` / `seek`+write・`truncate` を使わない。
  既存バイト列を書き換える API（削除・上書き・改変）を**一切実装しない**。
- **revert は非破壊で追記もしない**: revert は「現在位置」を移すだけ（`_current_id = snapshot_id`）。前方履歴の
  Snapshot を消さない。**snapshot JSONL へは書き込まない**（監査は ledger 側の `snapshot_revert` で表現）。
  revert 対象が未知 id なら KeyError（in-memory `SnapshotStore.revert` と同一：`self._index[snapshot_id]`）。
- **snapshot 行スキーマ**: `{"id": str, "label": str, "parent_id": str|None, "phases": [phase_to_dict(p), ...]}`。
  1 行 = 1 snapshot。phases は `serialization.phase_to_dict` の出力（JSON-safe・非有限 → None 済み）を並べる。
  再オープンは各行を `json.loads` → `phase_from_dict` で phases 復元 → `Snapshot` 再構築。
- **snapshot ID 連番と current_id の復元**: 再オープン時は復元した snapshot 数から `snap-{len:04d}` を継続し、
  `current_id` を**最後に save された snapshot の id**（=最新）に設定する（後続 save の parent_id 連結・ID 連番継続を成立させる）🟡。
  revert のみ行われた位置は snapshot 行に残らないため復元されない（current_id は最新 save 位置から再開）— 🟡 設計判断（TDD で確定）。
- **phases 等価の前提（roundtrip）**: `phase_from_dict(phase_to_dict(p))` は有限値・全フィールド定義済みの phase で
  値等価になる。非有限（inf/NaN）→ None → 既定補完、欠損キー → 既定補完のため、**厳密等価は有限値 phase で成立**。
  M0 SimulatedBackend 経路の phases は有限値であり TC-106-06 の等価が成立する（M1 教訓の JSON 純化と整合）。
- **決定論（NFR-102 / REQ-402）**: 乱数不使用。snapshot ID は `snap-{i:04d}` 連番、JSON 直列化は
  `serialization` の固定スキーマ（キー順固定）。同一入力で snapshot 行がビット同一になる。
- **型注釈**: `PersistentSnapshotStore.__init__(self, path: str | os.PathLike[str], ledger: Ledger | None = None) -> None`
  （`interfaces.py` は `path: str`。`os.PathLike` 許容は `tmp_path` テスト利便の 🟡 拡張、`PersistentLedger` と同方針）、
  `save(self, phases: tuple[PhaseInstance, ...], *, label: str) -> Snapshot`、
  `load(self, snapshot_id: str) -> Snapshot`、`revert(self, snapshot_id: str) -> tuple[PhaseInstance, ...]`、
  `snapshots -> tuple[Snapshot, ...]`、`current_id -> str | None`。`from __future__ import annotations` を付す。

### 破損・整合の扱い（ledger との違い）
- snapshot JSONL は**ハッシュチェーンではない**（Snapshot に hash フィールドなし）。よって PersistentLedger の
  `LedgerIntegrityError` 相当の**改竄検出は本タスクのスコープ外**（監査の完全性は注入 ledger 側が担保する）。
  再オープンは行を読んで復元するのみ。破損 snapshot 行の頑健化（不正 JSON のスキップ/例外）は最小に留める
  （末尾空行スキップは PersistentLedger と同じく許容してよい）— 🟡。

### スコープ境界（やり過ぎ防止）
- 本タスクは **`PersistentSnapshotStore` の追加のみ**。`PersistentLedger`（TASK-0013）は実装済みで**改変しない**。
- `SequentialEngine` への実注入・シーケンシャル E2E は **TASK-0019 系**。本タスクは snapshot ストア単体の
  永続化契約 + StagedRefinementEngine 注入スモークに留める。
- `store/serialization.py`（TASK-0012）・`store/snapshot.py` は**共有/契約の範として使うのみ・改変しない**
  （既存テスト緑維持が絶対条件）。

### 後続タスクへの影響
- **後続**: TASK-0019（`SequentialEngine` へ Persistent 版 ledger/snapshot を注入して逐次解析を永続化・E2E）。
  → **クラス名・`save`/`load`/`revert`/`snapshots`/`current_id` の署名と snapshot JSONL 行スキーマを固定**すること。
- **前提**: TASK-0012（serialization）/ TASK-0013（PersistentLedger）は完了済み。両者の契約に依存する。

- **参照元**: `docs/spec/m2-sequential/note.md`（注意事項/非破壊制約節）,
  `docs/design/m2-sequential/design-interview.md`（D-Q5）, `docs/design/m2-sequential/interfaces.py`（L284-292）,
  `docs/spec/m2-sequential/requirements.md`（REQ-011/012/401, NFR-203）,
  `CLAUDE.md`（不変条件）, `src/tsumugin/store/{snapshot,serialization,persistent}.py`,
  `src/tsumugin/refinement/staged.py`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m2-sequential/TASK-0014.md`（+ 前提 TASK-0012/0013・後続 TASK-0019 依存確認）
- 仕様/要件: `docs/spec/m2-sequential/{note,requirements,acceptance-criteria}.md`（TC-106-03/05/06）
- 設計: `docs/design/m2-sequential/{interfaces.py（L284-292）,design-interview.md（D-Q5）,architecture.md,dataflow.md}`
- 既存実装（必読）: `src/tsumugin/store/{snapshot,serialization,persistent,ledger,__init__}.py`,
  `src/tsumugin/refinement/staged.py`, `src/tsumugin/backends/simulated.py`, `src/tsumugin/model/phase.py`,
  `src/tsumugin/__init__.py`（公開 API `__all__`）
- 先行 TDD 成果物（参考・様式）: `docs/implements/m2-sequential/TASK-0013/{note,persistent-ledger-requirements,persistent-ledger-testcases}.md`,
  `docs/implements/m2-sequential/TASK-0012/{note,serialization-requirements,serialization-testcases}.md`
- テスト参考: `tests/test_persistent_store.py`, `tests/test_snapshot.py`, `tests/conftest.py`, `pyproject.toml`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在**（規約は `CLAUDE.md` に集約）

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
