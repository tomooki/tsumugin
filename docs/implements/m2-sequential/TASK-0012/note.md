# TASK-0012 TDD 開発コンテキストノート

**タスク**: store/serialization — PhaseInstance の dict 相互変換 (`phase_to_dict` / `phase_from_dict`)
**要件名**: m2-sequential / **タスクID**: TASK-0012 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 1 モデル/永続化基盤 / **信頼性**: 🟡 設計 D5 (JSON 可換の詳細は推測)
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`src/tsumugin/store/serialization.py` を**新規作成**し、`phase_to_dict(phase: PhaseInstance) -> dict` と
`phase_from_dict(data: Mapping) -> PhaseInstance` を実装する。lattice / sigma / occupancies / wt_frac /
lifecycle を含む**完全 roundtrip**。`json.dumps` 可能な素の型 (str / int / float / bool / None / dict) のみを
出力し、将来の PersistentLedger / PersistentSnapshotStore (TASK-0014) と Project Store (M3+) が共有する。

**🚨 絶対制約 (完了条件と直結)**:
- **全フィールド入り PhaseInstance の roundtrip 等価** — `phase_from_dict(phase_to_dict(p)) == p` (`==` 比較) 🔵
- **縮退 roundtrip** — `lifecycle=None` / `sigma` 空 / `occupancies` 空でも等価 roundtrip 🔵
- **JSON 安全性** — 出力 dict が `json.dumps(obj, allow_nan=False)` 可能。**非有限値 (inf/NaN) は None 化** 🟡 *M1 教訓*
- **前方互換** — `phase_from_dict` は**未知キーを無視**し、欠損 optional キーは既定で補完する 🟡
- **非破壊 / 純関数**: 2 関数とも副作用なし・決定論。既存 model / store の API は無改変 (削除・上書き API を足さない, P2)。
- **git commit しない** (ユーザー判断)。**質問しない** (自律実行)。

**参照元**: `docs/tasks/m2-sequential/TASK-0012.md`, `docs/design/m2-sequential/interfaces.py` L261-262,
`docs/design/m2-sequential/design-interview.md` D-Q5

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは**標準ライブラリ (`json` / `math` / `dataclasses`) のみ**で完結し、
  numpy にも GSAS-II にも依存しない純データ変換。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト (P2) を JSON ネイティブ型へ写像/復元する境界層。
  `store/` レイヤ (最下層の永続化基盤) に属し、上位レイヤ (search / refinement) に依存してはならない。
- **モジュール配置**: `src/tsumugin/store/serialization.py` (新規)。同層に `ledger.py`・`snapshot.py` が既存。
- **参照元**: `docs/spec/m2-sequential/note.md`(技術スタック節), `pyproject.toml`, `CLAUDE.md`

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE。
  内部ヘルパは先頭 `_` (既存 `ledger.py::_canonical_json` / `search/tree.py::_finite_or_none` に倣う)。
- **型注釈必須** (`any` 回避)。docstring 日本語可、FR/NFR/REQ 番号を docstring に紐づける慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` (line-length 100, target py312)。
- **データモデリング**: frozen dataclass 基本。復元は `PhaseInstance(...)` / `LatticeParams(...)` / `PhaseLifecycle(...)`
  のコンストラクタ経由 (`with_updates` ではなく新規生成)。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `docs/spec/m2-sequential/note.md`(開発ルール節), `CLAUDE.md`

---

## 3. 関連実装 (拡張・参考パターン)

### 変換対象の既存モデル (TASK-0011 で拡張済み・現状シグネチャ)
- `src/tsumugin/model/phase.py`:
  - `LatticeParams(a, b, c, alpha=90.0, beta=90.0, gamma=90.0, sigma=field(default_factory=dict))` + `.volume()`
  - `PhaseLifecycle(birth_frame: int|None=None, death_frame: int|None=None, confidence: float=1.0)` — **TASK-0011 新設**
  - `PhaseInstance(phase_ref, lattice, scale=1.0, wt_frac=None, occupancies=field(default_factory=dict), lifecycle: PhaseLifecycle|None=None)`
    + `.with_updates(**changes)` (中身は `dataclasses.replace`) — **`lifecycle` は TASK-0011 で末尾追加済み**
  - → **serialize 対象フィールド**: phase_ref / lattice(ネスト) / scale / wt_frac / occupancies / lifecycle(ネスト)

### 既存のシリアライズ / JSON 参考パターン (踏襲すべき先例)
- **非有限値 → None の JSON 契約 (M1 レビュー教訓)** — `src/tsumugin/search/tree.py::_finite_or_none` (L181-192):
  ```python
  def _finite_or_none(value: float) -> float | None:
      v = float(value)
      if not math.isfinite(v) or v >= _EVIDENCE_SENTINEL:
          return None
      return v
  ```
  同関数は `webui/app.py` が `chi2=inf` (EDGE-004 の正常経路) を JSON 配信する際にも利用。
  **注意 (レイヤ依存)**: `search/tree.py` は `store/` より**上位レイヤ**のため、`store/serialization.py` から
  `_finite_or_none` を import すると**逆方向依存**になる。→ serialization.py に**ローカルな `_finite_or_none` を定義**するのが安全
  (センチネル `_EVIDENCE_SENTINEL` は evidence 固有なので不要。単純な `math.isfinite` 判定で足りる)。
  将来 store 共有ユーティリティへ昇格するのは可 (D-Q5 の `_canonical_json` 昇格議論と同種の判断)。
- **正準 JSON / ハッシュ (D-Q5 の共有先)** — `src/tsumugin/store/ledger.py::_canonical_json` (L16-18):
  `json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)`。
  本タスクの `phase_to_dict` 出力は**この `_canonical_json` にそのまま渡せる素の dict** であることが要件
  (PersistentLedger/Snapshot が payload をハッシュチェーンに載せる前提)。D-Q5: 実装時に `_canonical_json` を
  公開ヘルパへ昇格させてよい (本タスクでは serialization が生成する dict の JSON 安全性を担保するに留める)。
- **既存 to_dict の粒度** — `store/ledger.py::LedgerEntry.to_dict` (L34-41) / `webui/app.py` の dict 生成 — 素の型のみ・
  `dict(mapping)` でコピーし呼び出し側変更から隔離する慣習。

### 本タスクの成果物を使う後続 (契約固定の理由)
- **TASK-0014** (`store/persistent.py`): PersistentLedger / PersistentSnapshotStore が `phase_to_dict`/`phase_from_dict`
  で phases を JSONL 1 行へ直列化。**REQ-010/011/012** (再オープンで verify()=True / revert 復元 / in-memory と同一 IF)。
- **M3+ Project Store**: 同関数を共有 (D-Q5 単一情報源)。
- → **関数名・dict スキーマ (キー名・ネスト構造) は interfaces.py L261-262 の契約どおりに固定すること。**

- **参照元**: `src/tsumugin/model/phase.py`, `src/tsumugin/search/tree.py`(L181-192),
  `src/tsumugin/store/{ledger,snapshot}.py`, `docs/design/m2-sequential/interfaces.py`(L256-292)

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py`
  - L261-262: `def phase_to_dict(phase: PhaseInstance) -> dict: ...  # 🟡 JSON 可換` /
    `def phase_from_dict(data: Mapping) -> PhaseInstance: ...  # 🟡 roundtrip 保証`
  - L256-292: `store/serialization.py + store/persistent.py` セクション (PersistentLedger/Snapshot が利用)。
- **設計判断 D-Q5** (`docs/design/m2-sequential/design-interview.md` L30-35):
  「`store/serialization.py` (phase の dict 相互変換) を**独立モジュール**にし、persistent.py と将来の Project Store が共有。
  ハッシュ計算は ledger.py の既存私的関数を import して共有 (私的横断 import を避けるため `_canonical_json` を公開昇格してよい)。
  単一情報源。JSONL 選定は requirements interview Q4。」
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-010/011/012 (L53-58): 永続化 (JSONL) と in-memory 同一 IF。本タスクはその**シリアライズ基盤**を先行実装する位置づけ。
- **受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md`
  - TC-104-03 (L48): 非有限値が漏れない (M1 レビュー教訓) — 本タスクの「非有限 → None」と同根の契約。
  - TC-106-01〜07 (L62-68): 永続化ストア (TASK-0014) が本タスクの roundtrip 上に成立。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §3 Data Layer (Project Store = HDF5 + SQLite。M2 は JSONL 軽量案でシリアライズ層を先行)。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest` (既定) / `uv run pytest tests/test_serialization.py` (本タスク単体) /
  `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。
  本タスクは **GSAS-II 非依存**のためマーカー不要 (`gsas` マーカーは付けない)。
- **本タスクのテストファイル**: `tests/test_serialization.py` (**新規**)。テスト対象 `src/tsumugin/store/serialization.py` (新規)。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py`。現状 19 ファイル。`tests/conftest.py` に共通フィクスチャ。
- **命名/記述パターン** (`tests/test_model.py` / M1 `test_clustering.py` に準拠):
  - 関数名 `test_...`。近似比較は `pytest.approx` (ただし roundtrip は原則 `==` で厳密比較 — 完了条件が `==`)。
  - docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
  - JSON 安全性は `json.dumps(d, allow_nan=False)` が**例外を出さない**ことで検証 (allow_nan=False は inf/NaN で `ValueError`)。
- **本タスクで書くべき代表テスト観点** (受け入れ基準・完了条件より):
  - **完全 roundtrip 等価**: 全フィールド入り `PhaseInstance` → dict → `PhaseInstance` が `==` (完了条件①)。
  - **縮退 roundtrip**: `lifecycle=None` / `sigma={}` / `occupancies={}` の最小相 → `==` (完了条件②)。
  - **JSON 安全性 (非有限 → None)**: `scale`/`lattice`/`sigma`/`occupancies`/`wt_frac`/`confidence` に `inf`/`nan` →
    dict では `None`、`json.dumps(allow_nan=False)` 成功 (完了条件③ / M1 教訓 / TC-104-03 と同根)。
  - **前方互換 (未知キー無視)**: 余分キー入り dict を `phase_from_dict` → 例外なし・baseline と `==` (完了条件④)。
  - **欠損 optional キー補完**: `lifecycle`/`occupancies`/`wt_frac` 欠落 dict → 既定 (None/{}/None) で補完 (旧スキーマ後方互換)。
  - **決定論 (NFR-102/402)**: 同一相の `phase_to_dict` 2 回が等価 dict + `_canonical_json` 文字列一致。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で既存 **223 passed / 3 skipped を維持** (新規テスト追加分のみ増加)。既存テストファイルは無改変。
- **参照元**: `pyproject.toml`, `tests/test_model.py`, `tests/conftest.py`,
  `docs/spec/m2-sequential/acceptance-criteria.md`(TC-104-03 / TC-106)

---

## 6. 注意事項

### 技術的制約
- **JSON 素の型のみ**: 出力は `str` / `int` / `float` / `bool` / `None` / それらの `dict` のみ。`tuple`・dataclass・numpy スカラは残さない
  (`occupancies`/`sigma` は `dict(mapping)` で素の dict にコピー)。→ `json.dumps(..., allow_nan=False)` が通る。
- **非有限 → None (M1 教訓の中核)**: `math.isfinite` が False の float は `None` へ写像。**store より上位の `search/tree.py::_finite_or_none`
  を import しない** (レイヤ逆依存回避)。serialization.py にローカル `_finite_or_none` を定義する。
  非有限は「精密化失敗の縮退状態」なので**roundtrip 値保存は非有限入力では保証しない** (完了条件①②は有限値が対象。③は JSON 安全性のみを要求)。
  → `phase_from_dict` は `None` を受けても壊れないこと (scale=None は既定 1.0 へフォールバック等、下記の from_dict 契約を testcases で確定)。
- **前方/後方互換の from_dict**: (a) **未知キーは無視** (`data[k]` を明示キーだけ拾う。`**data` 展開はしない)。
  (b) **欠損 optional キーは既定** (`data.get("lifecycle")` 等)。→ スキーマ進化に強い。
- **決定論 (NFR-102/402 / REQ-402)**: 乱数不使用・辞書順は `_canonical_json` の `sort_keys=True` が吸収。純関数。
- **型注釈**: `phase_to_dict(phase: PhaseInstance) -> dict[str, Any]` / `phase_from_dict(data: Mapping[str, Any]) -> PhaseInstance`。
  `from __future__ import annotations` を付す。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **phase 単体の 2 関数のみ**。`PersistentLedger` / `PersistentSnapshotStore` / JSONL ファイル I/O・
  ハッシュチェーン永続化は **TASK-0014** のスコープ (本タスクは in-memory の dict 変換までに留める)。
- `_canonical_json` の**公開ヘルパ昇格は本タスクでは必須でない** (D-Q5 は「昇格してよい」= 任意)。TASK-0014 実装時に判断で足りる。
  本タスクは「serialization の出力 dict が `_canonical_json` に渡せる素の型である」ことをテストで担保するに留める。
- `Hypothesis` / `Snapshot` / `LedgerEntry` の直列化はスコープ外 (phase の roundtrip が土台。上位は後続タスク)。

### 後続タスクへの影響
- **後続**: TASK-0014 (persistent store) が本 2 関数と dict スキーマに直接依存。**関数名・dict のキー名/ネスト構造を固定**すること
  (`phase_ref` / `lattice{a,b,c,alpha,beta,gamma,sigma}` / `scale` / `wt_frac` / `occupancies` / `lifecycle{birth_frame,death_frame,confidence}|None`)。
- **公開 API**: `src/tsumugin/__init__.py::__all__` はアルファベット昇順必須 (`test_m1_symbols_in_dunder_all_and_sorted` が固定)。
  もし `phase_to_dict`/`phase_from_dict` を top-level 公開する場合は昇順を維持。最小構成では `store/__init__.py` からの re-export で足りる (要判断)。

- **参照元**: `docs/spec/m2-sequential/note.md`(注意事項/非破壊制約節), `docs/design/m2-sequential/design-interview.md`(D-Q5),
  `docs/design/m2-sequential/interfaces.py`, `CLAUDE.md`(不変条件), `src/tsumugin/search/tree.py`(非有限契約)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m2-sequential/TASK-0012.md`
- 仕様/要件: `docs/spec/m2-sequential/{note,requirements,acceptance-criteria}.md`
- 設計: `docs/design/m2-sequential/{interfaces.py(L256-292),design-interview.md(D-Q5),architecture.md,dataflow.md}`
- 既存実装: `src/tsumugin/model/phase.py`(TASK-0011 拡張済み), `src/tsumugin/store/{ledger,snapshot,__init__}.py`,
  `src/tsumugin/search/tree.py`(`_finite_or_none`), `src/tsumugin/webui/app.py`(非有限 JSON 配信例)
- 先行 TDD 成果物 (参考): `docs/implements/m2-sequential/TASK-0011/{note,model-extension-requirements,model-extension-testcases}.md`
- テスト参考: `tests/test_model.py`, `tests/conftest.py`, `pyproject.toml`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
