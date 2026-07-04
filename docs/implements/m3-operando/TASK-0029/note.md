# TASK-0029 TDD 開発コンテキストノート

**タスク**: operando/echem — CSV マッパ (`EchemData` / `read_echem_csv` / `EchemLoader` Protocol + `BiologicMprLoader` スタブ)
**要件名**: m3-operando / **タスクID**: TASK-0029 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 3 (operando 電池モード) / **信頼性**: 🔵 4 / 🟡 1 (FR-311 / REQ-007/008 / EDGE-003 / AC TC-202 系)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

M3 operando の電気化学同期入力層を新設する。`operando/echem.py` を新規作成し、以下 4 要素を実装する:

1. **`EchemData` frozen dataclass** — フレーム同期済み電気化学量。`voltage` / `current` / `capacity` /
   `composition_x` の 4 tuple フィールド (要素は `float | None`、欠損は None)。`voltage` のみ位置必須、
   他 3 つは既定 `()`。`to_channels() -> tuple[ExternalChannel, ...]` で非空フィールドを対応 kind
   (voltage/current/capacity/composition) の `ExternalChannel` (sync_map: frame_index→値、None は不同期) へ変換。
2. **`read_echem_csv(path, *, column_map, capacity_to_x=None) -> EchemData`** — stdlib `csv` で CSV を読み、
   `column_map` ({"frame":"index", "voltage":"Ewe/V", "current":"I/mA", "capacity":"Q/mAh", ...}) に従い列抽出。
   数値変換は `float()` 明示 (**eval 不使用**)、変換失敗は列名を示す明示エラー。
   `capacity_to_x=(slope, intercept)` 指定時は容量→x を線形換算 `x = slope·Q + intercept` して `composition_x` を生成。
3. **列欠損 / 行数不一致ポリシー (D-Q7 確定)** — 要求列が CSV ヘッダに無い場合は**列名を示す `ValueError`**。
   列間で行数不一致の場合は**短い方に合わせ欠損を None + `warnings.warn` 警告** (M2 温度チャネル欠損政策と同一)。
4. **`EchemLoader` Protocol + `BiologicMprLoader` スタブ** — `load(path) -> EchemData` の交換境界 Protocol。
   `BiologicMprLoader.load` は M3 では **`NotImplementedError`** (Biologic .mpr バイナリは後続スコープ)。

**🚨 絶対制約 (完了条件と直結)**:
- **列マッピング読込 + V/I/Q 同期** (TC-202-01): frame/V/I/Q 列を `column_map` で読み、フレーム同期チャネル群が得られる 🔵。
- **容量→x 線形換算** (TC-202-02): `capacity_to_x=(a, b)` で `x = a·Q + b` が全フレームに適用される 🔵。
- **列欠損=明示エラー / 行数不一致=None+警告** (TC-202-03 / EDGE-003 / D-Q7): 列欠損は**列名入り ValueError**、
  行数不一致は**None+警告** 🟡。
- **BiologicMprLoader が NotImplementedError** (TC-202-04 / REQ-008): `.mpr` 未実装ローダが呼出で NotImplementedError 🔵。
- **数値変換失敗の明示エラー / eval 不使用** — `float()` で変換し失敗は列名付き例外。`eval`/`ast.literal_eval` を使わない 🔵。
- **stdlib csv 限定** (REQ-005 系踏襲) — pandas 等の外部 CSV パーサを使わない。コア依存は numpy のみ維持 (REQ-403)。
- **決定論 (NFR-102)** — 同一 CSV → ビット同一 `EchemData`。行順・列順で結果が揺れない。
- **既存 API 非破壊** — `ExternalChannel` / `ChannelKind` (TASK-0025 で 4 kind 拡張済) を利用のみ。model は変更しない。
- **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。

**参照元**: `docs/tasks/m3-operando/TASK-0029.md`, `docs/design/m3-operando/interfaces.py` L199-228,
`docs/spec/m3-operando/requirements.md` REQ-007/008/EDGE-003,
`docs/spec/m3-operando/acceptance-criteria.md` TC-202-01〜04, `docs/design/m3-operando/design-interview.md` D-Q7

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは **stdlib `csv` + `warnings` + `dataclasses` /
  `typing` のみ**。numpy にも GSAS-II にも xraylib にも依存しない (純入力 I/O 層)。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト (`EchemData`) + `typing.Protocol` 交換境界
  (`EchemLoader`)。M0/M1/M2 の Protocol 境界 (`RefinementBackend` / `EvidenceBackend`) と同型。
  未実装機種ローダは呼出時 `NotImplementedError` スタブ (`XraylibMuCalculator` / `GSASIIBackend` 未導入時と同パターン)。
- **モジュール配置**: `src/tsumugin/operando/` **新規ディレクトリ** (`__init__.py` + `echem.py`)。
  M3 で `cell_phases.py` / `discrimination.py` / `segmentation.py` / `output.py` が後続追加される最初のモジュール。
- **CSV 出力の既存範**: `src/tsumugin/sequential/trajectory.py` が `import csv` + `csv.writer` で決定論 CSV **書込**を実装。
  本タスクは **読込 (`csv.reader` or `csv.DictReader`)** で対をなす。
- **参照元**: `docs/spec/m3-operando/note.md` (技術スタック節), `pyproject.toml`, `CLAUDE.md`,
  `docs/design/m3-operando/architecture.md` L37/L114/L130

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: クラス/型 PascalCase (`EchemData` / `EchemLoader` / `BiologicMprLoader`)、関数/フィールド snake_case
  (`read_echem_csv` / `to_channels` / `column_map` / `capacity_to_x`)、ファイル snake_case (`echem.py`)。
- **型注釈必須** (`any` 回避)。`tuple[float | None, ...]` / `Mapping[str, str]` / `tuple[float, float] | None` を正しく付す。
  docstring 日本語可、FR/REQ/EDGE/TC 番号を紐づけ、信頼性レベル 🔵🟡🔴 を付す慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- **セキュリティ規約 (本タスク核心)**: CSV 数値は `float()` で明示変換。**`eval` / `exec` / `ast.literal_eval` 禁止**
  (architecture.md L130 / TASK-0029 完了条件)。信頼できない CSV を安全に読む。
- **警告出力**: stdlib `warnings.warn(..., UserWarning)` で行数不一致を通知 (戻り値にフィールドを増やさず Python 標準機構)。
  テストは `pytest.warns(UserWarning)` で捕捉。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。**質問しない**。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `CLAUDE.md`, `docs/spec/m3-operando/note.md` (開発ルール節), `docs/design/m3-operando/architecture.md` L130

---

## 3. 関連実装 (拡張・参考パターン)

### 依存する既存実装 (TASK-0025 で整備済み・利用のみ)

- `src/tsumugin/model/channel.py`:
  - `ChannelKind = Literal["temperature","time","pressure","custom","voltage","current","capacity","composition"]`
    (L9-18) — echem 4 kind は**拡張済み**。本タスクは新値 `"voltage"/"current"/"capacity"/"composition"` を利用のみ。
  - `ExternalChannel(kind: ChannelKind, sync_map: Mapping[int, float], label: str | None = None)`
    + `value_for(frame_index) -> float | None` (欠損 None、L35-43)。`to_channels` はこれを構築する。
  - → **model は一切変更しない** (非破壊利用)。`from tsumugin.model import ExternalChannel` で取り込む。

### 設計契約 (interfaces.py L199-228 準拠、そのまま実装可)

```python
@dataclass(frozen=True)
class EchemData:                                     # operando/echem.py (FR-311 / §4)
    voltage: tuple[float | None, ...]                # 位置必須
    current: tuple[float | None, ...] = ()
    capacity: tuple[float | None, ...] = ()
    composition_x: tuple[float | None, ...] = ()     # 換算済み x
    def to_channels(self) -> tuple: ...              # ExternalChannel 群へ 🟡

def read_echem_csv(
    path: str,
    *,
    column_map: Mapping[str, str],                   # {"frame":"index","voltage":"Ewe/V",...}
    capacity_to_x: tuple[float, float] | None = None,  # (slope, intercept): x = a·Q + b
) -> EchemData:
    """stdlib csv。列欠損は列名を示す ValueError、行数不一致は None+警告。REQ-007/EDGE-003"""
    ...

class EchemLoader(Protocol):                         # 機種別ローダの交換境界 (REQ-008)
    def load(self, path: str) -> EchemData: ...

class BiologicMprLoader:                              # M3 では NotImplementedError (REQ-008)
    ...
```

### 参考パターン (既存コードから踏襲)

- **stdlib csv 読込**: `src/tsumugin/sequential/trajectory.py` の `csv.writer` 決定論書込と対。読込は
  `csv.DictReader` でヘッダ→列名アクセスが `column_map` 値と自然対応 (ヘッダ欠損検知が容易)。
- **Protocol + 未実装スタブ**: `EchemLoader` / `BiologicMprLoader` は `MuCalculator` / `XraylibMuCalculator`
  (interfaces.py L69-76、TASK-0025 実装済) と同型。`BiologicMprLoader.load` は `raise NotImplementedError(...)`。
  Protocol は `@runtime_checkable` 不要 (静的境界のみ)。構造的準拠 (`load` メソッド) をテストで確認。
- **欠損の None 縮退**: `ExternalChannel.value_for` が `sync_map.get` で欠損を None に落とす思想と一貫。
  `to_channels` は None フレームを sync_map に**含めない** (frame_index キーの外部結合、欠損は捏造しない / dataflow.md L124)。
- **frozen + tuple フィールド**: `EchemData` の全フィールドは tuple のためハッシュ可 (frozen と両立)。
  等価比較 (`==`) と生成をテストする。
- **警告の同一政策**: 行数不一致 None+警告は「M2 の温度チャネル欠損 (None+警告)」と同一政策 (design-interview D-Q7)。

### 後続タスクの利用先

- **TASK-0034** (後続): 結合出力 `operando/output.py` の `combined_csv(trajectory, echem, path)` が
  `EchemData` の V/I/Q/x を frame_index で外部結合して CSV 化 (architecture.md L104-106)。
  → `EchemData` のフィールド名 (voltage/current/capacity/composition_x) と `read_echem_csv` 契約を固定すること。

- **参照元**: `src/tsumugin/model/channel.py`, `src/tsumugin/sequential/trajectory.py`,
  `src/tsumugin/model/cell.py` (Protocol スタブ範 / TASK-0025), `docs/design/m3-operando/interfaces.py` L199-228,
  `docs/implements/m3-operando/TASK-0025/` (Protocol+スタブの範)

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m3-operando/interfaces.py`
  - L199-208: `EchemData` (voltage/current/capacity/composition_x, `to_channels`)
  - L211-218: `read_echem_csv(path, *, column_map, capacity_to_x)` シグネチャ + docstring 契約
  - L221-224: `EchemLoader` Protocol / L227-228: `BiologicMprLoader` スタブ
- **要件**: `docs/spec/m3-operando/requirements.md`
  - REQ-007 (L40-42): 電気化学 CSV 汎用マッパで V/I/Q (+換算 x) を読み `ExternalChannel` (kind=echem 拡張) へ同期。
    容量→組成 x の線形換算則を設定可能。🔵 FR-311/§4 ExternalChannel。
  - REQ-008 (L43-44): Biologic .mpr 等バイナリローダは Protocol のみ定義、M3 では未実装エラー。🔵 FR-311。
  - EDGE-003 (L123): echem CSV の列欠損/行数不一致 → 明示エラー (列名を示す)、部分同期は警告。🟡。
- **設計判断**: `docs/design/m3-operando/design-interview.md`
  - **D-Q7 (L40-42, echem 同期の欠損政策 — 確定)**: 列欠損 = 明示エラー (列名提示)、行数不一致 = 短い方に合わせ
    欠損 None + 警告。根拠 EDGE-003。M2 の温度チャネル欠損 (None+警告) と同一政策 🔵。
- **データフロー**: `docs/design/m3-operando/dataflow.md`
  - L16-17: `FrameSeries + echem CSV → read_echem_csv (列マッピング + 容量→x 換算) → EchemData → ExternalChannel 群`。
  - L110: echem 列欠損 → 列名を示す明示エラー。L124: echem 同期は frame_index キーの外部結合、欠損は None (捏造しない)。
- **アーキテクチャ**: `docs/design/m3-operando/architecture.md`
  - L37: `operando/echem.py` = EchemData/read_echem_csv/EchemLoader Protocol/.mpr スタブ (REQ-007/008 🔵)。
  - L114: `operando/` 新規ディレクトリ。L121: テストは `tests/test_echem.py`。L130: 数値変換失敗は明示エラー (eval 不使用)。
- **受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` L22-27 (REQ-007/008 節)
  - TC-202-01 (L24): echem CSV (frame,V,I,Q 列) を列名マッピングで読み、フレーム同期チャネル群が得られる 🔵。
  - TC-202-02 (L25): 容量→x 換算則 (線形) が適用される 🔵。
  - TC-202-03 (L26): 列欠損で列名を示す明示エラー、行数不一致は欠損 None+警告 🟡 (EDGE-003)。
  - TC-202-04 (L27): EchemLoader Protocol の未実装ローダ (.mpr) が NotImplementedError 🔵 (REQ-008)。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` FR-311 (operando 電気化学同期)、§4 (ExternalChannel データモデル)。
- **参照元**: 上記各ファイル, `docs/tasks/m3-operando/{TASK-0029.md,overview.md}`

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest tests/test_echem.py` (本タスク単体) / `uv run pytest` (全体回帰) /
  `uv run pytest --cov=tsumugin`。**依存導入は `uv sync --extra gsas`** (プレーン `uv sync` は禁止)。
  本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- **本タスクのテストファイル**: `tests/test_echem.py` (**新規**、architecture.md L121 命名に一致)。
  CSV 入力は `tmp_path` フィクスチャで一時ファイルを生成 (pytest 標準)。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py`。`tests/conftest.py` に共通フィクスチャ。
  参考: `tests/test_trajectory.py` (CSV I/O + `tmp_path`)、`tests/test_model_m3.py`
  (`test_all_four_new_channel_kinds_constructible` 等、echem kind 生成の範 / L440-)。
- **命名/記述パターン** (既存 `tests/test_*.py` に準拠):
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - 明示エラーは `with pytest.raises(ValueError) as exc:` + `assert "列名" in str(exc.value)` で列名混入を確認。
  - 警告は `with pytest.warns(UserWarning):`。決定論/等価は `==`、近似は `pytest.approx`。
  - docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
- **本タスクで書くべき代表テスト観点** (TC-202-01〜04 に対応):
  - frame,V,I,Q 列 CSV を `column_map` で読み、`to_channels()` が voltage/current/capacity kind の
    `ExternalChannel` 群を返し `value_for(frame)` が正しい (TC-202-01)。
  - `capacity_to_x=(a, b)` 指定で `composition_x[i] == a·Q[i] + b`、`composition` kind チャネルが生成 (TC-202-02)。
  - 要求列がヘッダに無い → 列名を含む `ValueError` (TC-202-03a)。行数不一致 → 短い方に合わせ None + `UserWarning` (TC-202-03b)。
  - `BiologicMprLoader().load(path)` が `NotImplementedError` (TC-202-04)。
  - 数値でないセル (例 "abc") → 列名を含む明示エラー、`eval` を経由しない (境界/セキュリティ)。
  - `EchemData` が frozen・等価比較可、既定フィールド (current/capacity/composition_x=()) で最小生成。
  - 決定論: 同一 CSV を 2 回読み `read_echem_csv(...) == read_echem_csv(...)`。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で既存テストを無改変で維持 (既存 passed/skipped 件数を維持)。
- **参照元**: `pyproject.toml`, `tests/test_trajectory.py`, `tests/test_model_m3.py`, `tests/conftest.py`,
  `docs/spec/m3-operando/acceptance-criteria.md` TC-202-01〜04, `docs/design/m3-operando/architecture.md` L121

---

## 6. 注意事項

### 技術的制約
- **セキュリティ (核心)**: CSV 数値は `float()` 明示変換。**`eval`/`exec`/`ast.literal_eval` を使わない**
  (architecture.md L130 / 完了条件)。変換失敗は列名を示す明示エラー (`ValueError`) に変換。
- **stdlib csv 限定 / コア依存 numpy のみ**: pandas 等の外部パーサ不使用 (REQ-005 系・REQ-403)。
- **欠損は捏造しない (dataflow.md L124)**: frame_index キーの外部結合。行数不一致は短い方合わせで**欠損 None**、
  補間や 0 埋めをしない。`to_channels` は None フレームを `sync_map` に含めない (欠損は不同期として表現)。
- **警告 vs エラーの分離 (D-Q7)**: **列欠損 = エラー** (処理継続不能・列名提示)、**行数不一致 = 警告** (縮退継続)。
  この非対称を厳守。EDGE-003 の「明示エラー」と「部分同期は警告」を取り違えない。
- **決定論 (NFR-102)**: 乱数不使用。行順・列順は CSV 記載順で確定。同一入力 → ビット同一 `EchemData`。
- **型注釈**: `tuple[float | None, ...]` / `Mapping[str, str]` / `tuple[float, float] | None`。
  `from __future__ import annotations` を `echem.py` 冒頭に置く (前方参照 + Protocol)。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **echem CSV マッパ + Protocol/スタブのみ**。以下は**後続スコープ**:
  - Biologic .mpr の実バイナリパーサ (BiologicMprLoader は NotImplementedError で据え置き / REQ-008)。
  - 結合出力 `combined_csv` / 転移点 x/V±σ (`operando/output.py` = TASK-0034)。
  - `FrameSeries` との実結合・区間判別 (`discrimination.py`) / セグメンテーション。
- `capacity_to_x` は**線形 (slope, intercept) のみ**。非線形換算・多項式は実装しない (契約は tuple[float, float])。
- x の**物理妥当性検証 (0≤x≤1 等) はしない** (器と換算のみ。検証は上位/後続)。

### 後続タスクへの影響
- **後続 TASK-0034** が `EchemData` フィールド (voltage/current/capacity/composition_x) と
  `read_echem_csv` / `EchemLoader.load` 契約に依存。interfaces.py L199-228 の契約どおりに固定すること。
- `operando/__init__.py` を新設する場合、公開シンボル (`EchemData`/`read_echem_csv`/`EchemLoader`/`BiologicMprLoader`)
  の re-export 方針を後続モジュール (cell_phases/discrimination/...) と整合させる。

- **参照元**: `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/spec/m3-operando/{requirements,acceptance-criteria}.md`, `docs/design/m3-operando/{interfaces.py,dataflow.md,architecture.md,design-interview.md}`,
  `CLAUDE.md` (不変条件)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m3-operando/{TASK-0029.md,overview.md}`
- 仕様/要件: `docs/spec/m3-operando/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m3-operando/{interfaces.py,architecture.md,dataflow.md,design-interview.md}` (D-Q7)
- 既存実装 (利用/参考): `src/tsumugin/model/channel.py` (ChannelKind 拡張済 / ExternalChannel),
  `src/tsumugin/model/cell.py` (Protocol+スタブの範 / TASK-0025), `src/tsumugin/sequential/trajectory.py` (stdlib csv I/O)
- テスト参考: `tests/test_trajectory.py`, `tests/test_model_m3.py`, `tests/conftest.py`, `pyproject.toml`
- Protocol+スタブの範: `docs/implements/m3-operando/TASK-0025/` (note/requirements/testcases)
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
