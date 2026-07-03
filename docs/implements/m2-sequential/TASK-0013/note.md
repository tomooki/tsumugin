# TASK-0013 TDD 開発コンテキストノート

**タスク**: store/persistent — `PersistentLedger(path)`（JSONL 追記 + 再オープン検証）
**要件名**: m2-sequential / **タスクID**: TASK-0013 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 1 モデル/永続化基盤 / **信頼性**: 🔵 REQ-010/401・NFR-105/203・設計 D4/D-Q5
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨（最優先で守る不変条件）

`src/tsumugin/store/persistent.py` を**新規作成**し、`PersistentLedger(path)` を実装する。
インメモリの `Ledger`（`store/ledger.py`）と**同一契約**（`append` / `entries` / `verify`）を持つ
JSONL 永続版。ハッシュ計算は `ledger.py` の既存関数（`_canonical_json` / `_compute_hash` /
`GENESIS_HASH` / `LedgerEntry`）を**共有**する（D-Q5：必要なら私的関数を公開ヘルパへ昇格）。

- **オープン時**: 既存 JSONL を読込み**全チェーンを検証**。破損（ハッシュ不整合）を検出したら
  `LedgerIntegrityError`（**新設**）を送出し、**ファイルは修復・上書きしない**（EDGE-003）。
- **append**: 1 行を**追記モード（`"a"` のみ）**で書き込む（NFR-203）。既存バイト列を書き換えない。
- **削除・上書き・改変 API は実装しない**（P2 / NFR-101 / REQ-401）。追記のみ。

**🚨 絶対制約（完了条件と直結）**:
- append → 再オープン → `verify()` True + エントリ全量一致 🔵 *TC-106-01*
- 再オープン後の append でチェーン連結（index 連番継続・`verify()` True）🔵 *TC-106-02*
- ファイル 1 行改竄 → `LedgerIntegrityError` + **ファイル無変更** 🔵 *TC-106-04 / EDGE-003*
- 削除・上書き API 不在 + 追記のみ（先頭バイト列不変）🔵 *TC-106-05/07 / NFR-203*
- in-memory `Ledger` と同一 (kind, payload) 列で**同一 hash 列**（決定論）🔵 *NFR-102*
- **git commit しない**（ユーザー判断）。**質問しない**（自律実行）。

**参照元**: `docs/tasks/m2-sequential/TASK-0013.md`,
`docs/design/m2-sequential/interfaces.py`（L265-282: `LedgerIntegrityError` / `PersistentLedger`）,
`docs/design/m2-sequential/design-interview.md`（D-Q5）,
`docs/spec/m2-sequential/requirements.md`（REQ-010/012/401, NFR-201/203, EDGE-003）

---

## 1. 技術スタック

- **言語**: Python >= 3.12（uv 管理, src layout + hatchling）。本タスクは**標準ライブラリ
  （`json` / `pathlib` / `os`）のみ**で完結。numpy にも GSAS-II にも依存しない純粋な永続化 I/O。
- **アーキテクチャパターン**: 追記専用ハッシュチェーン台帳の永続化層。frozen dataclass
  `LedgerEntry`（`ledger.py` 既存）を JSONL の 1 行 = 1 エントリへ写像し、再構築する境界層。
  `store/` レイヤ（最下層の永続化基盤）に属し、上位（search / refinement / evidence）に依存しない。
- **モジュール配置**: `src/tsumugin/store/persistent.py`（新規）。同層に `ledger.py`・`snapshot.py`・
  `serialization.py`（TASK-0012 実装済み）が既存。例外は `src/tsumugin/errors.py`（既存ファイルに追記）。
- **JSONL 選定の根拠**: 仕様 §3 Data Layer（Project Store = HDF5 + SQLite）の**軽量案**として、
  M2 は追記専用 + ハッシュチェーンの不変条件を保ったまま JSON Lines でシリアライズ（requirements interview Q4）。
- **参照元**: `docs/spec/m2-sequential/note.md`（技術スタック節）, `pyproject.toml`, `CLAUDE.md`

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE。
  内部ヘルパは先頭 `_`（既存 `ledger.py::_canonical_json` / `_compute_hash` に倣う）。
- **型注釈必須**（`any` 回避）。docstring 日本語可、FR/NFR/REQ 番号を docstring に紐づける慣習。
- **フォーマット/Lint**: `uvx ruff check src tests`（line-length 100, target py312）。
- **データモデリング**: frozen dataclass 基本。`LedgerEntry` は無改変で再利用（新規生成のみ）。
- **git commit はユーザー判断**（本セッションでは commit 禁止）。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **公開 API**: `src/tsumugin/__init__.py::__all__` はアルファベット昇順必須
  （`test_m1_symbols_in_dunder_all_and_sorted` が固定）。`PersistentLedger` /
  `LedgerIntegrityError` を top-level 公開する場合は昇順を維持（最小構成は `store/__init__.py` re-export でも可・要判断）。
- **参照元**: `docs/spec/m2-sequential/note.md`（開発ルール節）, `CLAUDE.md`,
  `src/tsumugin/__init__.py`, `src/tsumugin/store/__init__.py`

---

## 3. 関連実装（拡張・参考パターン・共有先）

### 共有する既存実装（ledger.py — ハッシュチェーンの単一情報源）
- `src/tsumugin/store/ledger.py`:
  - `GENESIS_HASH = "0" * 64`（**公開済み定数**）。
  - `_canonical_json(payload) -> str`（L16-18）: `json.dumps(payload, sort_keys=True,
    separators=(",", ":"), default=str)`。辞書順差を吸収し決定論的ハッシュを保証。
  - `_compute_hash(index, kind, payload, prev_hash) -> str`（L21-23）:
    `sha256(f"{prev_hash}|{index}|{kind}|{_canonical_json(payload)}")`。**これを共有**することで
    in-memory `Ledger` と PersistentLedger の hash 列が一致する（決定論・完了条件⑤）。
  - `LedgerEntry(index, kind, payload, prev_hash, hash)` + `.to_dict()`（L26-41）:
    JSONL の 1 行へ直列化する既製の dict 変換。**PersistentLedger.entries はこの型を返す**（同一契約）。
  - `Ledger.verify()`（L69-79）: `index==i` かつ `prev_hash` 連結かつ `hash==_compute_hash(...)` を
    全エントリで検証するループ。**再オープン検証はこの検証ロジックと同一**（改竄検出の核）。
  - `Ledger.append(kind, payload)`（L50-63）: `index = len(entries)`、`prev_hash = 末尾.hash or GENESIS`、
    `payload = dict(payload)`（呼び出し側変更から隔離）。**PersistentLedger.append も同じ規約**に追記 I/O を足す。

### D-Q5 の「公開昇格」判断（本タスクの設計論点）
- `docs/design/m2-sequential/design-interview.md` D-Q5:
  「ハッシュ計算は ledger.py の既存私的関数を import して共有。M1 レビュー教訓（私的横断 import）を
  避けるため、実装時に `_canonical_json` を**公開ヘルパへ昇格させてよい**（任意）」。
- 選択肢:
  - (a) `persistent.py` から `ledger.py` の `_compute_hash` / `_canonical_json` を**私的 import**（最小変更）。
  - (b) `ledger.py` で `compute_hash` / `canonical_json`（公開名）へ昇格し、`Ledger` も新名を使う（挙動不変）。
  - (c) 検証ループを共有するため `ledger.py` に module-level `verify_entries(entries) -> bool` を新設し、
    `Ledger.verify` と PersistentLedger の再オープン検証が**単一ロジック**を呼ぶ（重複回避）。
- **タスク定義の指示**: 「必要なら公開ヘルパへ昇格（挙動不変）」。`LedgerEntry` の公開昇格も判断材料。
  → **推奨**: (a) または (b) でハッシュ関数を共有し、(c) で検証を単一化。いずれも `ledger.py` は**挙動不変**（既存 223 passed / 3 skipped を壊さない）。

### snapshot.py の ledger 連携パターン（後続 TASK-0014 が本 ledger を注入）
- `src/tsumugin/store/snapshot.py`: `SnapshotStore(ledger=None)` が `save`/`revert` 時に
  `ledger.append("snapshot_save"/"snapshot_revert", {...})` を呼ぶ。**PersistentLedger は
  この `append` 契約（`kind: str`, `payload: Mapping`）を満たせば無改変で注入可能**（REQ-012）。
  payload は `{"snapshot_id","label","parent_id","n_phases"}` 等の JSON-safe dict（後述の制約と整合）。

### serialization.py（TASK-0012 実装済み・payload の JSON 安全性の先例）
- `src/tsumugin/store/serialization.py`: `phase_to_dict` が `json.dumps(allow_nan=False)` 可能な
  素の dict を生成（非有限 → None）。**ledger の payload に相を載せる場合はこの出力を使う前提**なので、
  PersistentLedger 側は「payload が JSON round-trip 可能」を前提にしてよい（非有限純化は serialization 側の責務）。

- **参照元**: `src/tsumugin/store/{ledger,snapshot,serialization,__init__}.py`,
  `docs/design/m2-sequential/design-interview.md`（D-Q5）, `docs/design/m2-sequential/interfaces.py`（L256-282）

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py`
  - L265-267: `class LedgerIntegrityError(Exception): # 実装では TsumuginError 派生 🔵 EDGE-003`
    「永続 ledger の破損（ハッシュ不整合）を検出。修復・上書きはしない。」
  - L269-281: `class PersistentLedger`:
    - `__init__(self, path: str) -> None`: 既存ファイルを読込み全チェーン検証（破損で `LedgerIntegrityError`）
    - `append(self, kind: str, payload: Mapping) -> object`: in-memory 版と同一意味論・1 行追記（`"a"` のみ）
    - `entries -> tuple`（property） / `verify() -> bool`
    - 削除・上書き API は実装しない（P2）
  - L247-249: `SequentialEngine(..., ledger: Ledger | None = None)` — **Persistent 版を注入可能**（REQ-012）。
- **設計判断 D4**（永続化の位置づけ）/ **D-Q5**（永続化の分業・`_canonical_json` 共有・公開昇格の任意性）:
  `docs/design/m2-sequential/design-interview.md`（D-Q5 は L29-35）。
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-010（L53-54）: Ledger を追記専用 JSONL へ永続化。再オープンで (a) `verify()` True /
    (b) 続きから追記可能。🔵 *NFR-105（JSONL 形式は 🟡 interview Q4）*
  - REQ-012（L57-58）: 永続化ストアは in-memory と同一 IF、既存エンジンに無改変注入。🔵 *P7*
  - REQ-401（L94）: 永続化ストアにも削除・上書き・改変 API を実装しない（追記 + revert のみ）。🔵 *P2/NFR-101*
  - NFR-201（L105）: 永続 ledger は再オープン検証込みで `verify()` True。🔵
  - NFR-203（L107）: 書き込みは追記モード（`"a"`）のみ。既存バイト列を書き換えない。🔵 *P2*
  - EDGE-003（L116-117）: ファイル破損（ハッシュ不整合）→ 再オープン時に `verify()` False を検出し
    明示エラー。**修復・上書きしない**。🔵 *P2/NFR-105*
- **受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md`（TC-106-01/02/04/05/07）
  - TC-106-01（L62）: append → 再オープン → `verify()` True + エントリ全量一致。
  - TC-106-02（L63）: 再オープン後の append でハッシュチェーンが正しく連結（`verify()` True）。
  - TC-106-04（L65, EDGE-003）: 1 行改竄 → `verify()` False + 明示エラー、ファイル無変更。
  - TC-106-05（L66）: 削除・上書き API が存在しない（`hasattr` 否定、in-memory 版と同一検証）。
  - TC-106-07（L68, NFR-203）: JSONL が追記のみで成長（書き込み前後の先頭バイト列不変）。
  - （TC-106-03/06 = PersistentSnapshotStore は **TASK-0014 のスコープ**。本タスク対象外。）
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §3 Data Layer（HDF5 + SQLite。M2 は JSONL 軽量案）。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest tests/test_persistent_store.py`（本タスク単体）/ `uv run pytest`（全体回帰）/
  `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas`（プレーン `uv sync` は禁止）。
  本タスクは **GSAS-II 非依存**のためマーカー不要（`gsas` マーカーは付けない）。
- **本タスクのテストファイル**: `tests/test_persistent_store.py`（**新規**。TASK-0014 も同ファイルへ追加予定）。
  テスト対象 `src/tsumugin/store/persistent.py`（新規）+ `src/tsumugin/errors.py`（`LedgerIntegrityError` 追記）。
- **既存テスト構成（1:1 対応）**: `tests/` 直下に impl と対応する `test_*.py`（現状 19 ファイル）。
  `tests/conftest.py` に共通フィクスチャ。ledger のテストは `tests/test_ledger.py`（in-memory 契約の先例）。
- **一時ファイル**: `tmp_path`（pytest 組み込みフィクスチャ）を使い、JSONL パスを `tmp_path / "ledger.jsonl"` で確保。
  ファイル無変更検証（TC-106-07 / TC-106-04）は書き込み前後のバイト列 / 先頭 N バイトを read して比較する。
- **命名/記述パターン**（`tests/test_ledger.py` / M1 `test_clustering.py` に準拠）:
  - 関数名 `test_...`。docstring/コメントに【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
- **本タスクで書くべき代表テスト観点**（受け入れ基準・完了条件より）:
  - **永続 roundtrip**: append 複数 → 別インスタンスで再オープン → `verify()` True かつ `entries` が全量一致（TC-106-01）。
  - **再オープン後追記のチェーン連結**: 再オープン → append → index 連番継続・`prev_hash` 連結・`verify()` True（TC-106-02）。
  - **改竄検出（EDGE-003）**: JSONL の 1 行の `hash` または `payload` を書き換え → 再オープンで `LedgerIntegrityError`。
    かつ**送出後もファイルが無変更**（例外前後でバイト列一致）（TC-106-04）。
  - **API 不在（P2）**: `not hasattr(PersistentLedger, "delete")` 等。in-memory `Ledger` と同じ属性集合であること（TC-106-05）。
  - **追記のみ成長（NFR-203）**: append 前のファイル先頭バイト列 == append 後の先頭同数バイト（末尾に 1 行増えるだけ）（TC-106-07）。
  - **決定論（NFR-102）**: 同一 (kind, payload) 列を in-memory `Ledger` と PersistentLedger に流し、hash 列が完全一致。
  - **空/新規ファイル境界**: 存在しないパスで開く → 空 ledger・`verify()` True・append で新規作成。
- **回帰確認（完了ゲート）**: `uv run pytest` 全体で既存 **223 passed / 3 skipped を維持**（新規テスト分のみ増加）。
  `ledger.py` を公開昇格でリファクタする場合も**挙動不変**（`test_ledger.py` が緑のまま）。
- **参照元**: `pyproject.toml`, `tests/test_ledger.py`, `tests/conftest.py`,
  `docs/spec/m2-sequential/acceptance-criteria.md`（TC-106）

---

## 6. 注意事項

### 技術的制約
- **追記モード（`"a"`）のみ**（NFR-203 / P2）: append は必ず `open(path, "a", encoding="utf-8")` で
  1 行（`json.dumps(entry.to_dict()) + "\n"`）を書く。`"w"` / `"r+"` / `seek`+write・`truncate` を使わない。
  既存バイト列を書き換える API（削除・上書き・改変）を**一切実装しない**。
- **再オープン検証は「読込値をそのまま検証」**: ロード時は `LedgerEntry(index, kind, payload, prev_hash, hash)` を
  ファイルの値**そのまま**で再構築し（hash を再計算して埋め直さない）、その後 `verify()` で
  `_compute_hash` と突き合わせる。これにより 1 バイトの改竄でも `hash != _compute_hash(...)` で検出できる。
  **修復・上書きは禁止**（EDGE-003）: 検証 False → `LedgerIntegrityError` を送出して**終了**（ファイルに触れない）。
- **改竄・破損の扱い**: (1) hash 不整合・prev_hash 断裂・index 不連続 → `verify()` False → `LedgerIntegrityError`。
  (2) 行が壊れた JSON（`json.loads` 失敗）も破損として `LedgerIntegrityError` に包む（EDGE-003 の精神で
  「明示エラー・無修復」）。(3) 末尾の空行・改行のみの行はスキップ（正常な追記の副産物として許容）。
- **payload の JSON round-trip 前提（決定論の要）**: `_compute_hash` は `_canonical_json(payload)`（sort_keys）で
  ハッシュ化する。再オープンで hash を一致させるには payload が **JSON を往復しても同一**である必要がある
  （str キー・有限数・bool/None のみ）。ledger の payload は snapshot 連携等いずれも JSON-safe dict であり、
  相を載せる場合は `serialization.phase_to_dict`（非有限 → None 済み）を通す前提（TASK-0012 と整合）。
  int と float の区別も JSON 往復で保存される（`_canonical_json` の `default=str` は通常経路では発火しない）。
- **決定論（NFR-102 / REQ-402）**: 乱数不使用。`_compute_hash` / `_canonical_json` を in-memory `Ledger` と
  共有するため、同一 (kind, payload) 列に対し hash 列がビット同一になる（完了条件⑤）。
- **型注釈**: `PersistentLedger.__init__(self, path: str | os.PathLike[str]) -> None`（`str` 必須だが PathLike 許容は判断）、
  `append(self, kind: str, payload: Mapping[str, Any]) -> LedgerEntry`、`entries -> tuple[LedgerEntry, ...]`、
  `verify() -> bool`。`from __future__ import annotations` を付す。

### 例外設計（LedgerIntegrityError）
- **配置**: `src/tsumugin/errors.py` に `class LedgerIntegrityError(TsumuginError)` を追記
  （interfaces.py の注記「実装では TsumuginError 派生」に従う。既存 `GuardrailError` 等と同階層）。
  interfaces.py 上は素の `Exception` 継承に見えるが、**実装は `TsumuginError` 派生が正**（ドメイン例外階層の一貫性）。
- docstring に EDGE-003 / NFR-105 を紐づけ、「破損検出・修復しない」旨を明記。

### スコープ境界（やり過ぎ防止）
- 本タスクは **`PersistentLedger` のみ**。`PersistentSnapshotStore`（save/load/revert 永続化）は **TASK-0014**。
  本タスクは `persistent.py` を**新規作成**し PersistentLedger を置く（TASK-0014 が同ファイルを拡張）。
- `SequentialEngine` への実注入・E2E は **TASK-0019 系**。本タスクは ledger 単体の永続化契約に留める。
- `_canonical_json` / `_compute_hash` / `LedgerEntry` の**公開昇格は「必要なら」の任意**（D-Q5）。
  最小構成では私的 import で足りる。昇格する場合も `ledger.py` の**挙動を変えない**（テスト緑維持が絶対条件）。

### 後続タスクへの影響
- **後続**: TASK-0014（`persistent.py` に PersistentSnapshotStore を追加。本 PersistentLedger を注入して
  `snapshot_save`/`snapshot_revert` を記録）/ TASK-0019（エンジン注入・E2E）。
  → **クラス名・`append`/`entries`/`verify` の署名と JSONL 行スキーマ（`LedgerEntry.to_dict()` 準拠）を固定**すること。
- **JSONL 行スキーマ**: `{"index","kind","payload","prev_hash","hash"}`（`LedgerEntry.to_dict()` と一致）。
  この 1 行 = 1 エントリの形式を TASK-0014 の snapshot 永続化とも整合させる。

- **参照元**: `docs/spec/m2-sequential/note.md`（注意事項/非破壊制約節）,
  `docs/design/m2-sequential/design-interview.md`（D-Q5）, `docs/design/m2-sequential/interfaces.py`（L256-282）,
  `docs/spec/m2-sequential/requirements.md`（REQ-010/012/401, NFR-201/203, EDGE-003）,
  `CLAUDE.md`（不変条件）, `src/tsumugin/store/{ledger,snapshot,serialization}.py`, `src/tsumugin/errors.py`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m2-sequential/TASK-0013.md`（+ 後続 `TASK-0014.md` / 依存確認）
- 仕様/要件: `docs/spec/m2-sequential/{note,requirements,acceptance-criteria}.md`
- 設計: `docs/design/m2-sequential/{interfaces.py（L256-282）,design-interview.md（D-Q5）,architecture.md,dataflow.md}`
- 既存実装: `src/tsumugin/store/{ledger,snapshot,serialization,__init__}.py`, `src/tsumugin/errors.py`,
  `src/tsumugin/model/phase.py`, `src/tsumugin/__init__.py`（公開 API `__all__`）
- 先行 TDD 成果物（参考・様式）: `docs/implements/m2-sequential/TASK-0012/{note,serialization-requirements,serialization-testcases}.md`
- テスト参考: `tests/test_ledger.py`, `tests/conftest.py`, `pyproject.toml`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在**（規約は `CLAUDE.md` に集約）

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
