# TASK-0016 TDD 開発コンテキストノート

**タスク**: LifecycleTracker (ヒステリシス付き birth/death)
**要件名**: m2-sequential / **タスクID**: TASK-0016 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 2 時系列コンポーネント / **信頼性**: 🔵 FR-305 / REQ-004 / REQ-201
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`src/tsumugin/sequential/lifecycle.py` を新設し、以下を実装する:

- `LifecycleConfig` (frozen dataclass): `hysteresis: int = 3`, `presence_wt_frac: float = 1e-3`。
- `LifecycleTracker` (通常クラス。内部に可変状態を持つ):
  - `__init__(self, *, config: LifecycleConfig = LifecycleConfig()) -> None`
  - `observe(self, frame_index: int, present_refs: Sequence[str]) -> None` — 毎フレーム呼ぶ。
  - `finalize(self) -> Mapping[str, PhaseLifecycle]` — `{phase_ref: PhaseLifecycle}` を返す。

**ヒステリシスの意味論 (中核ロジック)**:
- **birth 確定**: ある相が連続 N (=hysteresis) フレーム存在したら、その連続の**最初のフレーム**を `birth_frame` とする。
- **death 確定**: birth 済みの相が連続 N フレーム不在になったら、その不在連続の**最初のフレーム**を `death_frame` とする。
- **死の取り消し (REQ-201)**: death 判定後でもヒステリシス窓内に再出現したら death を取り消し、連続扱いに戻す。
- **点滅抑制 (TC-103-03)**: 1 フレームだけ (< N) の偽出現は birth と認定しない。
- `confidence` = **存在フレーム率** (観測期間内で present だったフレーム数 / 総観測フレーム数)。実装時に確定し、docstring に算出根拠を明記する。

**🚨 絶対制約 (完了条件と直結)**:
- 契約シグネチャは `docs/design/m2-sequential/interfaces.py` L118-133 に固定 (フィールド名・引数名を変えない)。
- `PhaseLifecycle` は**既存の** `src/tsumugin/model/phase.py` の型 (TASK-0011 実装済) をそのまま再利用する。**新設しない**。
- `sequential/__init__.py` の `__all__` に `LifecycleConfig` / `LifecycleTracker` を追加 (アルファベット昇順維持)。
- **決定論 (REQ-402 / NFR-202)**: 乱数不使用・安定な走査順。同一入力で `finalize()` 出力がビット同一。
- **git commit しない** (ユーザー判断)。質問しない。

**参照元**: `docs/tasks/m2-sequential/TASK-0016.md`, `docs/design/m2-sequential/interfaces.py`(L118-133),
`docs/spec/m2-sequential/requirements.md`(REQ-004/201), `docs/spec/m2-sequential/acceptance-criteria.md`(TC-103 系)

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。GSAS-II は optional extra `gsas` (本タスクは **非依存**)。
- **アーキテクチャパターン**: 設定は frozen dataclass の不変値オブジェクト。`LifecycleTracker` は
  `observe()` で内部状態を蓄積し `finalize()` で結果を返す**ステートフルなトラッカー**
  (純関数 `detect_changepoint` とは異なり、可変状態を持つ数少ないクラス)。
- **依存**: 標準ライブラリのみで実装可能 (numpy 不要。フレーム存在の集合/カウントで足りる)。
- **モジュール配置**: `src/tsumugin/sequential/` 配下 (既存 `changepoint.py` / `series.py` に `lifecycle.py` を新設)。
- **参照元**: `docs/spec/m2-sequential/note.md`, `pyproject.toml`, `CLAUDE.md`, `docs/dev/context.md`

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE。
- **型注釈必須** (`any` 回避)。docstring 日本語可、FR/NFR/REQ 番号を docstring に紐づける慣習
  (既存 `changepoint.py` の【機能概要】【実装方針】【テスト対応】+ 🔵/🟡 信頼性レベル記法に倣う)。
- **フォーマット/Lint**: `uvx ruff check src tests` (line-length 100, target py312)。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `docs/spec/m2-sequential/note.md`, `CLAUDE.md`, `src/tsumugin/sequential/changepoint.py`(docstring 様式)

---

## 3. 関連実装 (拡張・参考パターン)

### 依存する既存実装 (TASK-0011 で実装済 — 再利用する)
- `src/tsumugin/model/phase.py`:
  - `PhaseLifecycle(birth_frame: int | None = None, death_frame: int | None = None, confidence: float = 1.0)`
    — frozen dataclass。**本タスクはこれを生成して返すだけ** (型は変更しない)。
  - `from tsumugin.model import PhaseLifecycle` で解決可能 (`model/__init__.py` で re-export 済)。

### 同一パッケージの参考パターン (`sequential/`)
- `src/tsumugin/sequential/changepoint.py`:
  - frozen `ConfigConfig`(既定値付き) + docstring 様式 (【機能概要】【実装方針】【テスト対応】+ 信頼性レベル)。
  - 決定論・I/O なしの実装姿勢 (REQ-402)。**本タスクの Config はこの様式を踏襲**。
- `src/tsumugin/sequential/series.py`: `FrameSeries` (フレーム列保持)。lifecycle は series の
  各フレーム present 判定から駆動される想定 (ただし本タスクの API は `present_refs` を直接受け取る疎結合設計)。
- `src/tsumugin/sequential/__init__.py`: `__all__` にアルファベット昇順で export
  (現状 ChangepointConfig / ChangepointSignal / FrameSeries / detect_changepoint)。
  → `LifecycleConfig` / `LifecycleTracker` を昇順位置に挿入。

### 設計契約 (interfaces.py L118-133 準拠、そのまま実装可)
```python
@dataclass(frozen=True)
class LifecycleConfig:
    hysteresis: int = 3            # 連続 N フレームで birth/death 確定 🔵 FR-305 (N は 🟡)
    presence_wt_frac: float = 1e-3 # 存在判定の下限 🟡

class LifecycleTracker:
    """相ごとの出現/消滅をヒステリシス付きで追跡する (REQ-004/201)。🔵"""
    def __init__(self, *, config: LifecycleConfig = LifecycleConfig()) -> None: ...
    def observe(self, frame_index: int, present_refs: Sequence[str]) -> None: ...
    def finalize(self) -> Mapping[str, PhaseLifecycle]: ...
```

### `present_refs` と `presence_wt_frac` の関係 (実装判断メモ)
- `observe()` は既に「存在する相の ref 集合」(`present_refs`) を受け取る疎結合設計。
  存在判定 (wt_frac が `presence_wt_frac` 以上か) は**呼び出し側** (後続 TASK-0019 SequentialEngine) が行い、
  present な ref のみ渡すのが基本線。`presence_wt_frac` は Config に保持され、判定の下限として文書化する。
- **参照元**: `docs/design/m2-sequential/interfaces.py`, `src/tsumugin/sequential/{changepoint,series,__init__}.py`,
  `src/tsumugin/model/phase.py`

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py`
  (L118-133 が `LifecycleConfig` / `LifecycleTracker`、L31-45 が `PhaseLifecycle`)。
- **アーキテクチャ / データフロー**: `docs/design/m2-sequential/architecture.md`, `docs/design/m2-sequential/dataflow.md`。
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-004 (L34-35): 相ライフサイクル (birth_frame/death_frame/confidence) を追跡し、
    ヒステリシス (連続 N フレーム存在/不在で確定、既定 N=3) で点滅抑制。
  - REQ-201 (L87-88): death 判定後、ヒステリシス窓内に再出現したら death 取り消し・連続扱い。
- **受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md` L37-42 (TC-103-01〜04)。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §2 時系列 / FR-305。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest` (既定) / `uv run pytest tests/test_lifecycle.py` (本タスク単体) /
  `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。
- **マーカー**: `gsas` (未導入は自動 skip)。本タスクは GSAS-II 非依存のためマーカー不要。
- **本タスクのテストファイル**: `tests/test_lifecycle.py` (**新規**)。既存 24 テストファイルは無改変。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py`。同パッケージ参考は
  `tests/test_changepoint.py` (14 test) / `tests/test_sequential_series.py`。`tests/conftest.py` に共通フィクスチャ。
- **命名/記述パターン** (`tests/test_changepoint.py` に準拠):
  - 関数名 `test_...`、docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】+ 🔵/🟡 信頼性レベル。
  - frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`、近似は `pytest.approx`。
- **本タスクで書く代表テスト観点** (TC-103 系 + 完了条件):
  - frame 10 から連続出現 → `birth_frame == 10` (TC-103-01)。
  - frame 15 から連続不在 → `death_frame == 15` (TC-103-02)。
  - 1 フレーム点滅は birth 非認定 (TC-103-03、N=3 ヒステリシス)。
  - death 後の窓内再出現で death 取り消し (TC-103-04 / REQ-201)。
  - 全フレーム存在 → birth=最初の frame / death=None / confidence=1.0 (🟡)。
  - `LifecycleConfig` の既定値 (hysteresis=3 / presence_wt_frac=1e-3) と frozen 性。
  - 決定論・空観測などの縮退 (`finalize()` を observe なしで呼ぶ → 空 Mapping)。
- **回帰確認ゲート**: `uv run pytest` 全体 green を維持 (既存テストに影響しないこと)。
- **参照元**: `pyproject.toml`, `tests/test_changepoint.py`, `tests/conftest.py`,
  `docs/spec/m2-sequential/acceptance-criteria.md`(TC-103)

---

## 6. 注意事項

### 技術的制約
- **決定論 (REQ-402 / NFR-202)**: 乱数不使用。相 ref の走査は安定順序 (初出順 or ソート) で行い、
  同一入力で `finalize()` 出力がビット同一になること。
- **ヒステリシス境界の一貫性**: birth は「連続 N 到達時に**遡って連続開始フレーム**を記録」する点に注意
  (N フレーム目で birth を立てるが `birth_frame` は連続の 1 フレーム目)。death も同様に不在連続の 1 フレーム目。
  → 実装では各相の連続 present/absent ランの開始 frame_index を保持する必要がある。
- **death 取り消し (REQ-201)**: death を「確定」ではなく「暫定」として保持し、窓 (N フレーム) 内の
  再出現で取り消す設計。窓を超えて不在が続いて初めて death 確定。実装順序に依存するため慎重にテスト。
- **confidence の算出式は実装時確定 (🟡)**: 「存在フレーム率」を採用し docstring に根拠明記。
  全フレーム存在なら 1.0 になる (完了条件⑤の検証点)。分母 (総観測フレーム or birth〜death 区間) の
  取り方はテストで固定する。
- **`PhaseLifecycle` を新設しない**: model 側の既存型を import して使う (TASK-0011 の成果物)。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **lifecycle トラッキング単体**。`present_refs` の wt_frac 存在判定・実際のフレーム駆動・
  `SequentialEngine` 統合・トラジェクトリ出力は **後続 TASK-0019 / 0017 系** のスコープ。
- `Trajectory` / `FrameRecord` / `SequentialResult` (interfaces.py 他セクション) には触れない。

### 後続タスクへの影響
- **後続**: TASK-0019 (SequentialEngine) が `LifecycleTracker` を driver として利用。
  `observe(frame_index, present_refs)` / `finalize() -> Mapping[str, PhaseLifecycle]` の契約を固定すること。
- **参照元**: `docs/spec/m2-sequential/requirements.md`(REQ-201/402), `docs/spec/m2-sequential/acceptance-criteria.md`,
  `docs/design/m2-sequential/interfaces.py`, `CLAUDE.md`(不変条件)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m2-sequential/TASK-0016.md`, `docs/tasks/m2-sequential/overview.md`
- 仕様/要件: `docs/spec/m2-sequential/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m2-sequential/{interfaces.py,architecture.md,dataflow.md,design-interview.md}`
- 既存実装: `src/tsumugin/model/phase.py`(PhaseLifecycle), `src/tsumugin/sequential/{changepoint,series,__init__}.py`
- テスト参考: `tests/test_changepoint.py`, `tests/test_sequential_series.py`, `tests/conftest.py`, `pyproject.toml`
- 依存タスク記録: `docs/implements/m2-sequential/TASK-0011/note.md`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
