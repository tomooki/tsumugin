# TASK-0017 TDD 開発コンテキストノート

**タスク**: Trajectory + FrameRecord + to_csv (時系列トラジェクトリ出力)
**要件名**: m2-sequential / **タスクID**: TASK-0017 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 2 時系列コンポーネント / **信頼性**: 🔵 FR-306 / REQ-005 / REQ-402
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`src/tsumugin/sequential/trajectory.py` を新設し、以下 2 つの frozen dataclass を実装する:

### `FrameRecord` (トラジェクトリ 1 行 = 1 フレーム)
`docs/design/m2-sequential/interfaces.py` L141-153 に契約が固定されている (フィールド名・順序を変えない):

| フィールド | 型 | 意味 |
|---|---|---|
| `frame_index` | `int` | フレーム番号 |
| `axis_value` | `float \| None` | フレーム軸値 (index 軸なら None もあり得る) |
| `temperature` | `float \| None` | channel 由来。なければ None 🔵 |
| `phases` | `tuple[PhaseInstance, ...]` | 当該フレームの確定 phases 🔵 |
| `rwp` | `float \| None` | 失敗フレームは None (非有限を漏らさない) 🔵 M1 教訓 |
| `chi2` | `float \| None` | 同上 |
| `changepoint` | `bool` | changepoint 判定フラグ |
| `changepoint_reasons` | `tuple[str, ...]` | "rwp_jump"\|"lattice_jump"\|"new_peaks" |
| `refine_failed` | `bool` | EDGE-002 精密化失敗フラグ 🟡 |

### `Trajectory` (時系列出力)
interfaces.py L156-165:

| フィールド/メソッド | 型 | 意味 |
|---|---|---|
| `records` | `tuple[FrameRecord, ...]` | フレーム順の行 |
| `lifecycles` | `Mapping[str, PhaseLifecycle]` | 相ごとの birth/death/confidence |
| `to_csv(self, path: str) -> str` | メソッド | stdlib csv で書き出し、書き出したパスを返す。非有限値・None は空欄 🔵 |

**🚨 絶対制約 (完了条件と直結)**:
- 契約シグネチャは `docs/design/m2-sequential/interfaces.py` L141-165 に固定。フィールド名・引数名・戻り値 (`to_csv` は `str` を返す) を変えない。
- **CSV は stdlib `csv` のみ** (pandas/parquet 禁止。REQ-005 で parquet は M2 スコープ外)。
- **列順は決定論・テストで凍結** (REQ-402 / 完了条件④)。2 回出力でバイト同一になること。列は明示的な固定リストで生成し、dict のイテレーション順や集合順に依存しない。
- **非有限値・None は空欄** (完了条件③ / TC-104-03 / M1 レビュー教訓)。`rwp=None`・`chi2=inf`・`NaN` がファイルに文字列として漏れてはならない。空文字列セルで表現する。
- `PhaseInstance` / `PhaseLifecycle` は **既存の** `src/tsumugin/model/phase.py` の型 (TASK-0011 実装済) をそのまま再利用する。**新設しない**。
- `sequential/__init__.py` の `__all__` に `FrameRecord` / `Trajectory` を **アルファベット昇順維持**で追加 (挿入位置: `FrameRecord` は `FrameSeries` の前、`Trajectory` は末尾クラス群の適所)。
- **決定論 (REQ-402 / NFR-202)**: 乱数・時刻・環境依存を使わない。同一入力で `to_csv` 出力バイト列が同一。
- テストは `tests/test_trajectory.py` (**新規**) に `tmp_path` フィクスチャで書き出し先を確保する。
- **git commit しない** (ユーザー判断)。質問しない。

**参照元**: `docs/tasks/m2-sequential/TASK-0017.md`, `docs/design/m2-sequential/interfaces.py`(L141-165),
`docs/spec/m2-sequential/requirements.md`(REQ-005/402), `docs/spec/m2-sequential/acceptance-criteria.md`(TC-104 系)

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは **GSAS-II 非依存**・**numpy 不要** (標準 `csv` のみ)。
- **依存ライブラリ**: 標準ライブラリ `csv` (書き出し) + `math.isfinite` (非有限純化)。外部依存を増やさない。
- **アーキテクチャパターン**: 出力は frozen dataclass の不変値オブジェクト。`FrameRecord`/`Trajectory` はデータ器で、`to_csv` のみ副作用 (ファイル I/O) を持つ薄い書き出し層。
- **モジュール配置**: `src/tsumugin/sequential/` 配下 (既存 `changepoint.py` / `series.py` / `lifecycle.py` に `trajectory.py` を新設)。
- **参照元**: `docs/spec/m2-sequential/note.md`, `pyproject.toml`, `CLAUDE.md`, `docs/dev/context.md`

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE、CSV 列名は snake_case + ドット区切り (`phase.<ref>.a` 等) を推奨 (実装時に固定)。
- **型注釈必須** (`any` 回避)。docstring 日本語可、FR/NFR/REQ/TC 番号を docstring に紐づける
  (既存 `changepoint.py`/`lifecycle.py` の【機能概要】【実装方針】【テスト対応】+ 🔵/🟡 信頼性レベル記法に倣う)。
- **フォーマット/Lint**: `uvx ruff check src tests` (line-length 100, target py312)。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **CLAUDE.md 由来の該当不変条件**: 「NFR-102 再現性: 乱数種固定でビット同一」「非有限値を漏らさない」(changepoint.py docstring でも明記)。
- **参照元**: `docs/spec/m2-sequential/note.md`, `CLAUDE.md`, `src/tsumugin/sequential/changepoint.py`(docstring 様式)

---

## 3. 関連実装 (拡張・参考パターン)

### 依存する既存実装 (再利用する — 新設しない)
- `src/tsumugin/model/phase.py`:
  - `PhaseInstance(phase_ref, lattice: LatticeParams, scale=1.0, wt_frac: float|None=None, occupancies={}, lifecycle=None)` — CSV の相ごと列 (格子 a/b/c・scale・wt_frac) の源泉。`lattice.a/b/c/alpha/beta/gamma`、`lattice.sigma` (Mapping) を持つ。
  - `PhaseLifecycle(birth_frame: int|None, death_frame: int|None, confidence: float=1.0)` — `Trajectory.lifecycles` の値型。lifecycle 列 (birth/death/confidence) の源泉。
  - `LatticeParams` は `volume()` を持つ (CSV に含めるかは要件で判断。完了条件は abc 明記)。
  - import: `from tsumugin.model import PhaseInstance, PhaseLifecycle`。

### 🔑 非有限純化の既存パターン (M1 教訓 — 最重要の再利用対象)
- `src/tsumugin/store/serialization.py` L20-32 の `_finite_or_none(v)`:
  ```python
  def _finite_or_none(v: float | None) -> float | None:
      """有限 float はそのまま、非有限 (inf/-inf/NaN) と None は None を返す。"""
      if v is None:
          return None
      return v if math.isfinite(v) else None
  ```
  - コメント: 「model を import しないレイヤ制約を守り、非有限判定はローカル `_finite_or_none` で行う (M1 教訓)」。
  - **本タスクの CSV 化でも同様に、数値セルは "有限なら str(v)、None/非有限は空文字列 `''`" へ写す純化関数をローカル定義**するのが定石 (レイヤ横断 import を避け、trajectory.py 内に閉じたヘルパを置く)。
- `src/tsumugin/search/tree.py` L182-196: JSON 配信用 `_finite` (非有限/センチネル → None)。同じ思想の別実装。
- `src/tsumugin/sequential/changepoint.py` L56-58: 「MAD=0 の縮退は例外化せず 0.0 に縮退し非有限を漏らさない」— 同一 doctrine。
- **教訓**: 「非有限が最終成果物 (JSON/CSV) に文字列として漏れる」のが M1 レビュー指摘。CSV でも `inf`/`nan` の文字列化を必ず空欄へ落とす。

### 同一パッケージの参考パターン (`sequential/`)
- `src/tsumugin/sequential/changepoint.py`: frozen Config + docstring 様式 + 決定論・純化の姿勢。`ChangepointSignal.reasons` が `changepoint_reasons` の源 ("rwp_jump"|"lattice_jump"|"new_peaks")。
- `src/tsumugin/sequential/series.py`: `FrameSeries` (フレーム列・軸値・channels)。`axis_values`/`channels` (ExternalChannel) が `axis_value`/`temperature` 列の上流 (本タスクの入力は既に FrameRecord 化済みの想定で、series からの変換は後続 TASK-0019 SequentialEngine のスコープ)。
- `src/tsumugin/sequential/lifecycle.py`: `LifecycleTracker.finalize() -> Mapping[str, PhaseLifecycle]` が `Trajectory.lifecycles` を供給 (TASK-0016 実装済)。
- `src/tsumugin/sequential/__init__.py`: 現状 `__all__` = ChangepointConfig / ChangepointSignal / FrameSeries / LifecycleConfig / LifecycleTracker / detect_changepoint。→ `FrameRecord` / `Trajectory` を昇順位置へ挿入。

### 既存の書き出し層パターン (I/O 契約)
- `src/tsumugin/export/gpx.py` `export_gpx(path, ...) -> str`: **書き出したパスを `str` で返す**契約。`to_csv(path) -> str` も同一 (戻り値 == 入力 path)。

### CSV 列順の決定論設計 (実装判断メモ — 要件/テストで凍結すべき論点)
- **課題**: `phases` はフレームごとに異なり得るため、行ごとに列が変わると CSV にならない。→ 全 `records` の `phases` の `phase_ref` と `lifecycles` のキーの**和集合を決定論順 (sorted() の文字列昇順) で確定**し、全行で同じ列集合を使う。
- **列レイアウト案** (要件/テストケースで正式凍結):
  - フレーム共通列 (固定・先頭): `frame_index, axis_value, temperature, rwp, chi2, changepoint, changepoint_reasons, refine_failed`。
  - 相ごと列 (phase_ref 昇順で反復): 各 ref につき `<ref>.a, <ref>.b, <ref>.c, <ref>.scale, <ref>.wt_frac`, さらに lifecycle 由来 `<ref>.birth_frame, <ref>.death_frame, <ref>.confidence`。
  - `changepoint_reasons` (tuple) は決定論区切り (例 `|` 連結) で 1 セル化。
  - 当該フレームに存在しない相の列は空欄。
- **列名・区切り・α/β/γ や σ を含めるかは requirements/testcases で正式に凍結** (テストがバイト列 or ヘッダ順を assert して凍結する)。
- **参照元**: `docs/design/m2-sequential/interfaces.py`, `src/tsumugin/sequential/{changepoint,series,lifecycle,__init__}.py`,
  `src/tsumugin/model/phase.py`, `src/tsumugin/store/serialization.py`, `src/tsumugin/export/gpx.py`

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py`
  - L141-153: `FrameRecord`。L156-165: `Trajectory` + `to_csv`。L31-45: `PhaseLifecycle`。L44-54: `ExternalChannel` (temperature 源)。
- **アーキテクチャ / データフロー**: `docs/design/m2-sequential/architecture.md`, `docs/design/m2-sequential/dataflow.md`。
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-005 (L36-38): トラジェクトリ (フレーム軸値・相ごと scale/wt_frac・格子±σ・Rwp/GOF・changepoint フラグ・ライフサイクル) を構造化データで返し、**CSV へ書き出せる** (stdlib csv。parquet は M2 スコープ外)。
  - REQ-402 (L95): 同一入力・同一設定で全出力ビット同一。
  - REQ-009 (L48-49): CSV 出力を外部委譲出口として流用可能にする (JMAK 等は非スコープ)。
- **受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md` L44-48 (TC-104-01〜03) + サマリ「トラジェクトリ 3 件」。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §2 時系列 / FR-306。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest` (既定) / `uv run pytest tests/test_trajectory.py` (本タスク単体) / `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。
- **マーカー**: `gsas` (未導入は自動 skip)。本タスクは GSAS-II 非依存のためマーカー不要。
- **本タスクのテストファイル**: `tests/test_trajectory.py` (**新規**)。既存テストファイル (25 本) は無改変。書き出し先は pytest `tmp_path` フィクスチャを使用 (TASK-0017.md 明記)。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py`。同パッケージ参考は `tests/test_changepoint.py` / `tests/test_lifecycle.py` / `tests/test_sequential_series.py`。`tests/conftest.py` に共通フィクスチャ。
- **命名/記述パターン** (`tests/test_changepoint.py`/`test_lifecycle.py` に準拠):
  - 関数名 `test_...`、docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】+ 🔵/🟡 信頼性レベル。
  - frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`、近似は `pytest.approx`。
  - CSV 読み戻しは stdlib `csv.reader` / `csv.DictReader` を使う (完了条件② が明示: to_csv → csv.reader で読み戻す)。
- **本タスクで書く代表テスト観点** (TC-104 系 + 完了条件):
  - **TC-104-01 / 完了条件①**: 生成 CSV のヘッダに必須列 (軸値・相ごと格子 a/b/c・scale・wt_frac・Rwp・changepoint・lifecycle birth/death) が全て含まれる。
  - **TC-104-02 / 完了条件②**: `to_csv(path)` の戻り値がそのパスで、`csv.reader` で読み戻せる。**データ行数 == フレーム数 (len(records))**。ヘッダ行を除く。
  - **TC-104-03 / 完了条件③**: `rwp=None` / `chi2=float('inf')` / `float('nan')` の失敗フレームでも、該当セルが空文字列で、`inf`/`nan` 文字列がファイル全文に出現しない。
  - **REQ-402 / 完了条件④ (決定論)**: 同一 Trajectory を 2 回 `to_csv` → 2 ファイルのバイト列が同一。相集合が複数フレームでまたがっても列順が安定。
  - **frozen 検証**: `FrameRecord` / `Trajectory` が frozen (代入で FrozenInstanceError)。
  - **縮退 (推奨追加)**: 空 `records` → ヘッダのみ (or 空) で例外なし・行数 0。相が無いフレーム / lifecycles 空。
- **回帰確認ゲート**: `uv run pytest` 全体 green を維持 (既存 test に影響しないこと)。
- **参照元**: `pyproject.toml`, `tests/test_changepoint.py`, `tests/test_lifecycle.py`, `tests/conftest.py`, `docs/spec/m2-sequential/acceptance-criteria.md`(TC-104)

---

## 6. 注意事項

### 技術的制約
- **非有限を漏らさない (M1 教訓・最重要)**: 数値セルは `_finite_or_none` 相当のローカル純化を必ず通し、None/inf/-inf/NaN は空文字列 `''` にする。CSV に `inf`/`nan` 文字列を書かない (TC-104-03)。有限端点 (0.0 / 負値 / 極小) は保持する。
- **列順の完全決定論 (REQ-402)**: 列は明示リストで構築し、dict/set の反復順や `phases` 到来順に依存しない。相 ref は `sorted()` で文字列昇順に固定。`newline=''` を `open()` に付け改行の OS 差 (`\r\n` 二重化) を防ぐ (stdlib csv 定番)。エンコーディングは `utf-8` 固定でバイト同一を担保。
- **CSV 方言の固定**: `csv.writer` の既定方言 (`excel`) を使い、区切り・quoting を明示的に固定してテストで凍結。`changepoint_reasons` (tuple) の 1 セル化区切りは決定論文字 (`|` 等) を選び、CSV デリミタ (`,`) と衝突しないものにする。
- **相ごと列の欠損**: あるフレームに存在しない相の列は空欄。存在する相のうち `wt_frac=None` も空欄 (None と非有限を同一に空欄化)。
- **戻り値契約**: `to_csv(path)` は書き出した `path` を `str` で返す (`export_gpx` と同一契約)。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **FrameRecord / Trajectory / to_csv の器と CSV 書き出し単体**。以下は**扱わない**:
  - `FrameSeries` → `FrameRecord` への変換・実際の逐次精密化・changepoint 駆動・lifecycle 駆動 → **後続 TASK-0019 (SequentialEngine)**。
  - `SequentialResult` / `SequentialEngine` / `SequentialConfig` (interfaces.py 他セクション) には触れない。
  - parquet・DataFrame・JSON 出力は非スコープ (REQ-005: CSV 限定、parquet は M2 外)。
  - 転移温度推定・ThermalBaseline (TASK-0018 系) は非スコープ。

### 後続タスクへの影響
- **前提タスク**: TASK-0011 (model 拡張: PhaseInstance.lifecycle / PhaseLifecycle) / TASK-0016 (LifecycleTracker) — 実装済。
- **後続**: TASK-0018 (thermal), TASK-0019 (SequentialEngine が FrameRecord を組み立て Trajectory を構築)。`to_csv` の列順・空欄表現を固定することで後続 E2E (TC-108-01 の「CSV 出力まで完走」) が安定する。
- **参照元**: `docs/spec/m2-sequential/requirements.md`(REQ-005/402/009), `docs/spec/m2-sequential/acceptance-criteria.md`(TC-104/108),
  `docs/design/m2-sequential/interfaces.py`, `CLAUDE.md`(不変条件), `docs/implements/m2-sequential/TASK-0016/note.md`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m2-sequential/TASK-0017.md`, `docs/tasks/m2-sequential/overview.md`
- 仕様/要件: `docs/spec/m2-sequential/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m2-sequential/interfaces.py`(L141-165 = FrameRecord/Trajectory)
- 既存実装 (再利用): `src/tsumugin/model/phase.py`(PhaseInstance/PhaseLifecycle/LatticeParams),
  `src/tsumugin/sequential/{changepoint,series,lifecycle,__init__}.py`, `src/tsumugin/model/channel.py`(ExternalChannel)
- 非有限純化パターン (M1 教訓): `src/tsumugin/store/serialization.py`(_finite_or_none), `src/tsumugin/search/tree.py`(_finite)
- 書き出し I/O 契約: `src/tsumugin/export/gpx.py`(path 返却)
- テスト参考: `tests/test_changepoint.py`, `tests/test_lifecycle.py`, `tests/test_sequential_series.py`, `tests/conftest.py`, `pyproject.toml`
- 依存タスク記録: `docs/implements/m2-sequential/TASK-0016/note.md`, `docs/implements/m2-sequential/TASK-0011/`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
