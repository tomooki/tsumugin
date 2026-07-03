# TASK-0013 store/persistent — PersistentLedger TDD要件定義書

**機能名**: store/persistent — `PersistentLedger(path)`（JSONL 追記 + 再オープン検証）
**タスクID**: TASK-0013
**要件名**: m2-sequential
**タスクタイプ**: TDD / **推定工数**: 3h / **フェーズ**: Phase 1 - モデル/永続化基盤
**作成日**: 2026-07-03
**出力ファイル**: `docs/implements/m2-sequential/TASK-0013/persistent-ledger-requirements.md`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M2 永続化基盤として、追記専用ハッシュチェーン台帳 `Ledger` の
  **JSONL 永続版** `PersistentLedger(path)` を新設する。インメモリ `Ledger`（`store/ledger.py`）と
  **同一契約**（`append` / `entries` / `verify`）を持ち、(a) `append` は 1 行を追記モード（`"a"`）で
  JSONL ファイルへ書き込み、(b) `__init__(path)` は既存ファイルを読込んで**全ハッシュチェーンを検証**し、
  破損（ハッシュ不整合）を検出したら `LedgerIntegrityError`（新設）を送出する（**修復・上書きしない**）。
- 🔵 **どのような問題を解決するか**: 現行 `Ledger` はインメモリ `list` のみでプロセス再起動をまたいだ
  永続化ができない。全状態遷移の監査ログ（P2 / NFR-105）をプロセス再起動後も検証可能・追記可能にするため、
  追記専用 + ハッシュチェーン + 非破壊の不変条件を保ったまま JSONL シリアライズ層を足す。破損したファイルは
  沈黙して読み進めず、明示エラーで検出する（改ざん・ビット腐敗を隠さない）。
- 🔵 **想定されるユーザー**: 直接のユーザーは後続タスク（TASK-0014 の `PersistentSnapshotStore`、
  TASK-0019 のエンジン注入）と、`SequentialEngine` / `StagedRefinementEngine` / `HypothesisTreeSearch`
  に ledger を注入する解析経路（REQ-012）。研究者は「再オープンで検証済みの監査ログ」を得る形で間接的に依存する。
  本クラス自体は内部の永続化基盤であり外部 UI を持たない。
- 🔵 **システム内での位置づけ**: `src/tsumugin/store/` レイヤ（永続化基盤、最下層）の新規モジュール
  `persistent.py`。上位レイヤ（search / refinement / evidence）には**依存してはならない**（レイヤ逆依存の禁止）。
  ハッシュ計算は同層 `ledger.py` の既存関数（`_canonical_json` / `_compute_hash` / `GENESIS_HASH` /
  `LedgerEntry`）を**共有**する（単一情報源・D-Q5）。標準ライブラリ（`json` / `pathlib` / `os`）のみで完結。
- **参照したEARS要件**: REQ-010（Ledger を追記専用 JSONL へ永続化・再オープンで verify()=True + 追記可能）、
  REQ-012（in-memory と同一 IF・無改変注入）、REQ-401（削除・上書き・改変 API 不在）
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L265-282
  （`LedgerIntegrityError` / `PersistentLedger` 契約）、`docs/design/m2-sequential/design-interview.md` D-Q5
  （永続化の分業・`_canonical_json` 共有・公開昇格の任意性）、
  `docs/spec/m2-sequential/note.md`（store 永続化基盤・非破壊制約節）

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 PersistentLedger.__init__（新設 / `src/tsumugin/store/persistent.py`）🔵

- 🔵 **署名**: `def __init__(self, path: str | os.PathLike[str]) -> None`
  （`interfaces.py` は `path: str`。`os.PathLike` 許容は `tmp_path` テスト利便のための 🟡 拡張）
- 🔵 **入力**: JSONL ファイルパス。存在すれば既存エントリを読込み、存在しなければ空 ledger として扱う。
- 🔵 **動作**:
  1. ファイルが存在すれば 1 行ずつ読み、各行を `json.loads` して
     `LedgerEntry(index, kind, payload, prev_hash, hash)` を**ファイルの値そのまま**で再構築する
     （hash を再計算して埋め直さない — 改竄検出のため）。
  2. 読込んだ全エントリに対し `verify()` を実行。
  3. `verify()` が False（ハッシュ不整合・prev_hash 断裂・index 不連続）、または行が壊れた JSON
     （`json.loads` 失敗）の場合、`LedgerIntegrityError` を送出する。**ファイルは修復・上書きしない**。
  4. 末尾の空行・改行のみの行はスキップする（正常な追記の副産物として許容）。
- 🟡 **出力（副作用）**: 検証成功時は内部状態 `self._entries: list[LedgerEntry]` を復元。ファイルへの書き込みは行わない
  （読み取りのみ。新規パスの場合もこの時点ではファイルを作らず、初回 `append` で追記作成する方針を推奨 🟡）。
- **参照した設計文書**: `interfaces.py` L277（`__init__(self, path: str)`）、
  `ledger.py`（`LedgerEntry` / `_compute_hash` / `Ledger.verify`）

### 2.2 PersistentLedger.append（新設）🔵

- 🔵 **署名**: `def append(self, kind: str, payload: Mapping[str, Any]) -> LedgerEntry`
- 🔵 **入力**: `kind`（エントリ種別文字列）、`payload`（JSON-safe な Mapping）。
- 🔵 **動作**（in-memory `Ledger.append` と同一意味論 + 追記 I/O）:
  1. `index = len(self._entries)`、`prev_hash = self._entries[-1].hash if self._entries else GENESIS_HASH`。
  2. `payload = dict(payload)`（呼び出し側の後続変更から隔離）。
  3. `hash = _compute_hash(index, kind, payload, prev_hash)`（`ledger.py` と**同一関数**を共有）。
  4. `LedgerEntry(index, kind, payload, prev_hash, hash)` を構築。
  5. `open(path, "a", encoding="utf-8")` で `json.dumps(entry.to_dict()) + "\n"` を**1 行追記**する
     （**`"a"` モードのみ**。`"w"` / `"r+"` / `seek`+write / `truncate` を使わない — NFR-203）。
  6. 内部 `self._entries` に追加し、`entry` を返す。
- 🔵 **出力**: 追記された `LedgerEntry`（`store/ledger.py` の既存型を再利用）。
- 🔵 **副作用**: JSONL ファイル末尾に 1 行が追加されるのみ。**既存バイト列は不変**（追記前の先頭バイト列が保存される）。
- **参照した設計文書**: `interfaces.py` L278（`append(self, kind: str, payload: Mapping) -> object`）、
  `ledger.py` L50-63（`Ledger.append`）、requirements REQ-010(b) / NFR-203

### 2.3 PersistentLedger.entries（property）🔵

- 🔵 **署名**: `@property def entries(self) -> tuple[LedgerEntry, ...]`
- 🔵 **出力**: 現在の全エントリの不変タプル（`tuple(self._entries)`）。in-memory `Ledger.entries` と同一。
- **参照した設計文書**: `interfaces.py` L279-280、`ledger.py` L65-67

### 2.4 PersistentLedger.verify（新設）🔵

- 🔵 **署名**: `def verify(self) -> bool`
- 🔵 **動作**: `prev_hash = GENESIS_HASH` から始め、各エントリで `index == i` かつ `prev_hash` 連結かつ
  `hash == _compute_hash(index, kind, payload, prev_hash)` を検証。1 つでも破れれば False、全通過で True。
  in-memory `Ledger.verify`（L69-79）と**同一ロジック**（重複回避のため `ledger.py` に module-level
  `verify_entries(entries)` を新設して共有してもよい — D-Q5 昇格の任意判断）。
- 🔵 **出力**: `bool`。
- **参照した設計文書**: `interfaces.py` L281、`ledger.py` L69-79、NFR-105 / NFR-201

### 2.5 LedgerIntegrityError（新設 / `src/tsumugin/errors.py`）🔵

- 🔵 **配置**: `class LedgerIntegrityError(TsumuginError)`（`errors.py` に追記。既存 `GuardrailError` 等と同階層）。
  `interfaces.py` L265 は素の `Exception` 継承に見えるが、注記「実装では TsumuginError 派生」に従い
  **`TsumuginError` 派生が正**（ドメイン例外階層の一貫性）。
- 🔵 **意味**: 永続 ledger の破損（ハッシュ不整合・不正 JSON 行）を検出したときに送出。**修復・上書きはしない**。
- **参照した設計文書**: `interfaces.py` L265-267、`src/tsumugin/errors.py`、EDGE-003

### 2.6 入出力の関係性・データフロー 🔵

- **直列化**: `append(kind, payload)` → `LedgerEntry`（`_compute_hash` で hash 付与）→ `to_dict()` →
  `json.dumps` → JSONL 1 行を `"a"` 追記。
- **復元/検証**: JSONL 各行 → `json.loads` → `LedgerEntry` 再構築（値そのまま）→ `verify()` で
  `_compute_hash` と突合 → 一致すれば `entries` として提供、不一致なら `LedgerIntegrityError`。
- **参照したEARS要件**: REQ-010、REQ-012、REQ-401
- **参照した設計文書**: `docs/design/m2-sequential/dataflow.md`、`interfaces.py` L256-282

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **追記モード（`"a"`）のみ / 非破壊（NFR-203 / P2 / NFR-101 / REQ-401）**: 書き込みは `open(path, "a")` による
  1 行追記のみ。既存バイト列を書き換える操作（`"w"` / `"r+"` / `seek`+write / `truncate`）を使わない。
  **削除・上書き・改変 API を一切実装しない**（`Ledger` と同じく `append` / `entries` / `verify` のみ）。
- 🔵 **再オープン検証（NFR-105 / NFR-201 / REQ-010(a)）**: `__init__` で全チェーンを `verify()` し、
  健全なら `verify()==True`。ロード値は**そのまま**検証に用い（hash 再計算で上書きしない）、
  1 バイトの改竄でも検出できる。
- 🔵 **破損検出・無修復（EDGE-003 / P2 / NFR-105）**: ハッシュ不整合・不正 JSON 行を検出したら
  `LedgerIntegrityError` を送出して終了し、**ファイルに一切書き込まない**（修復・上書き・切り詰めをしない）。
- 🔵 **決定論（NFR-102 / REQ-402）**: 乱数不使用。`_compute_hash` / `_canonical_json` を in-memory `Ledger` と
  **共有**するため、同一 (kind, payload) 列に対し hash 列がビット同一になる。
- 🟡 **payload の JSON round-trip 前提**: `_compute_hash` は `_canonical_json(payload)`（`sort_keys=True`）で
  ハッシュ化する。再オープンで hash を一致させるには payload が **JSON を往復しても同一**である必要がある
  （str キー・有限数・bool/None のみ）。相を載せる場合は `serialization.phase_to_dict`（非有限 → None 済み）を
  通す前提（TASK-0012 と整合）。int/float の区別も JSON 往復で保存される。
- 🔵 **同一契約 / 無改変注入（REQ-012 / P7）**: `append(kind, payload)` / `entries` / `verify()` の署名を
  in-memory `Ledger` と一致させ、`SnapshotStore(ledger=...)` や各エンジンへ**無改変で注入可能**にする。
- 🔵 **レイヤ制約（アーキテクチャ）**: `store/` は最下層。上位（search / refinement）を import しない。
  ハッシュ計算は同層 `ledger.py` の関数を共有する（`_canonical_json` の公開昇格は「必要なら」の任意 — D-Q5）。
- 🔵 **`ledger.py` 挙動不変**: `_canonical_json` / `_compute_hash` / `LedgerEntry` の公開昇格や
  検証ロジック共有化を行っても、`Ledger` の**挙動を変えない**（既存 `tests/test_ledger.py` 緑維持が絶対条件）。
- 🔵 **型注釈必須**: `Mapping[str, Any]` / `tuple[LedgerEntry, ...]` を正しく付す。`from __future__ import annotations`。`any` 回避。
- 🔵 **命名規則 / Lint**: クラス PascalCase、内部ヘルパは `_` 接頭辞。`uvx ruff check src tests`（line-length 100, target py312）準拠。
- 🔴 **git commit しない**（ユーザー判断。本セッション制約）。**質問しない**（自律実行）。

- **参照したEARS要件**: REQ-010 / REQ-012 / REQ-401 / REQ-402、NFR-101 / NFR-102 / NFR-105 / NFR-201 / NFR-203
- **参照した設計文書**: `interfaces.py`（L256-282）、`design-interview.md`（D-Q5）、
  `docs/spec/m2-sequential/note.md`（非破壊/レイヤ制約節）、`docs/spec/m2-sequential/requirements.md`、`CLAUDE.md`（不変条件）

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

- **永続追記 → 再オープン検証**: `pl = PersistentLedger(path)` → `pl.append("phase_accept", {...})` を複数回 →
  プロセス再起動相当で `pl2 = PersistentLedger(path)`（同一パス）→ `pl2.verify() == True` かつ
  `pl2.entries` が書き込み全量と一致（TC-106-01）。
- **再オープン後の追記でチェーン継続**: `pl2.append(...)` → 新エントリの `index` が連番継続・`prev_hash` が
  直前 hash に連結・`pl2.verify() == True`（TC-106-02）。
- **エンジンへの注入**: `SnapshotStore(ledger=pl)` や `SequentialEngine(..., ledger=pl)` に注入し、
  `snapshot_save` / `snapshot_revert` 等が JSONL に追記される（REQ-012。実注入 E2E は TASK-0014/0019）。

### 4.2 データフロー 🔵

- 直列化: `append` → `LedgerEntry`（hash 付与）→ `to_dict` → `json.dumps` → JSONL 1 行を `"a"` 追記。
- 復元: JSONL 各行 → `json.loads` → `LedgerEntry` 再構築 → `verify()` → `entries` 提供（または `LedgerIntegrityError`）。

### 4.3 エッジケース 🔵🟡

- 🟡 **空/新規ファイル**: 存在しないパスで開く → 空 ledger・`verify() == True`（GENESIS のみ）→ 初回 `append` で
  ファイル新規作成（`"a"` は不在ファイルを作成する）。
- 🔵 **改竄（EDGE-003 の核）**: JSONL の 1 行の `hash` または `payload` を書き換え → 再オープンで
  `verify()` が False を検出 → `LedgerIntegrityError` を送出。かつ**送出前後でファイルが無変更**。
- 🟡 **不正 JSON 行**: 行が壊れて `json.loads` 失敗 → 破損として `LedgerIntegrityError` に包む（EDGE-003 の精神
  「明示エラー・無修復」）。
- 🟡 **末尾の空行・改行のみ**: 正常な追記の副産物としてスキップ（破損扱いにしない）。
- 🔵 **1 件のみ / 多数件**: エントリ 0/1/多数のいずれでもチェーン検証が一貫して機能する。

### 4.4 エラーケース 🔵🟡

- 🔵 **破損は明示エラー（例外にする）**: serialization の「非有限 → None（例外にしない）」とは対照的に、
  ledger の**破損は握り潰さず `LedgerIntegrityError` を送出**する（監査ログの完全性が P2 の核心のため）。
- 🔵 **無修復の保証**: 検出時に修復・上書き・切り詰めをしない（ファイルを read しか触らない設計）。
- 🔴 **注意（非スコープ）**: 並行書き込み時のファイルロック・アトミック追記（fsync 等）は本タスクでは扱わない
  （単一プロセス・逐次追記の前提。堅牢化は将来タスク）。

- **参照したEARS要件**: REQ-010 / REQ-401、EDGE-003、NFR-203
- **参照した設計文書**: `docs/design/m2-sequential/dataflow.md`、`interfaces.py`（L256-282）、
  `docs/spec/m2-sequential/acceptance-criteria.md`（TC-106-01/02/04/05/07）

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: m2-sequential 永続化・再現性（プロセス再起動をまたぐ監査ログ ledger の復元・検証, user-stories.md）
- **参照した機能要件**:
  - REQ-010（Ledger を追記専用 JSONL へ永続化。再オープンで verify()=True + 続きから追記可能）
  - REQ-012（永続化ストアは in-memory と同一 IF、既存エンジンに無改変注入）
  - REQ-401（永続化ストアにも削除・上書き・改変 API を実装しない。追記 + revert のみ）
  - REQ-402（同一入力で全出力ビット同一 = 決定論）
- **参照した非機能要件**: NFR-101（追記/非破壊 P2）、NFR-102（決定論・ビット同一）、NFR-105（ハッシュチェーン・verify() 常時 True）、
  NFR-201（再オープン検証込みで verify() True）、NFR-203（追記モード `"a"` のみ・既存バイト列不変）
- **参照したEdgeケース**: EDGE-003（ファイル破損 → verify() False 検出・明示エラー・修復/上書きしない）
- **参照した受け入れ基準**（`docs/spec/m2-sequential/acceptance-criteria.md`）:
  - TC-106-01（append → 再オープン → verify() True + エントリ全量一致）
  - TC-106-02（再オープン後の append でハッシュチェーン連結・verify() True）
  - TC-106-04（EDGE-003: 1 行改竄 → verify() False + 明示エラー、ファイル無変更）
  - TC-106-05（削除・上書き API が存在しない。hasattr 否定、in-memory 版と同一検証）
  - TC-106-07（NFR-203: JSONL が追記のみで成長。書き込み前後の先頭バイト列不変）
  - （TC-106-03/06 = PersistentSnapshotStore は TASK-0014 のスコープ。本タスク対象外）
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md`（store 永続化基盤層・レイヤ分離・設計 D4）
  - **データフロー**: `docs/design/m2-sequential/dataflow.md`（直列化/復元・検証パス）
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L256-282（`LedgerIntegrityError` / `PersistentLedger` /
    `PersistentSnapshotStore`）、L247-249（`SequentialEngine` の ledger 注入）
  - **設計ヒアリング**: `docs/design/m2-sequential/design-interview.md` D-Q5（独立モジュール・単一情報源・
    `_canonical_json` 共有・公開昇格の任意性）
  - **既存実装**: `src/tsumugin/store/ledger.py`（`GENESIS_HASH` / `_canonical_json` / `_compute_hash` /
    `LedgerEntry` / `Ledger`）、`src/tsumugin/store/snapshot.py`（ledger 連携パターン）、
    `src/tsumugin/store/serialization.py`（payload の JSON 安全化の先例）、`src/tsumugin/errors.py`（`TsumuginError` 階層）
  - **タスク定義**: `docs/tasks/m2-sequential/TASK-0013.md`
  - **コンテキストノート**: `docs/implements/m2-sequential/TASK-0013/note.md`

---

## 完了条件（タスク定義より）

- [ ] append → 再オープン → `verify()` True + エントリ全量一致 🔵 *TC-106-01*
- [ ] 再オープン後の append でチェーン連結（index 連番継続・`verify()` True）🔵 *TC-106-02*
- [ ] 1 行改竄 → `LedgerIntegrityError` + ファイル無変更 🔵 *TC-106-04 / EDGE-003*
- [ ] 削除・上書き API 不在 + 追記のみ（先頭バイト列不変）🔵 *TC-106-05/07*
- [ ] in-memory `Ledger` と同一 (kind, payload) 列で同一 hash 列（決定論）🔵

## 信頼性レベルサマリー

- 🔵 青信号: 機能概要・システム内位置づけ・同一契約（append/entries/verify）・再オープン検証・破損無修復・
  追記モード限定・非破壊・決定論・完了条件は interfaces.py / requirements.md / 既存 `ledger.py` 実装に直接依拠。
- 🟡 黄信号: `os.PathLike` 許容・新規ファイル生成タイミング・不正 JSON 行を `LedgerIntegrityError` に包む方式・
  末尾空行スキップ・payload の JSON round-trip 前提は設計文書からの妥当な具体化。
- 🔴 赤信号: git commit しない / 質問しない のセッション運用制約、並行書き込みロックを非スコープとする旨のみ。
- **品質判定**: 高品質 — 要件の曖昧さなし / 入出力定義完全（4 メソッド + 例外の署名・動作確定）/ 制約条件明確
  （追記のみ・無修復・決定論）/ 実装可能性確実（標準ライブラリ + 既存 `ledger.py` 関数の共有のみ）。
