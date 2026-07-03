# TASK-0011 TDD 開発コンテキストノート

**タスク**: model 拡張 (PhaseLifecycle / ExternalChannel / frame_range)
**要件名**: m2-sequential / **タスクID**: TASK-0011 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 1 モデル/永続化基盤 / **信頼性**: 🔵 仕様 §4 / REQ-404
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`PhaseLifecycle`(birth/death/confidence) を `model/phase.py` に新設し `PhaseInstance.lifecycle`
(既定 `None`) を追加。`Hypothesis.frame_range`(既定 `None`) を追加。`model/channel.py` に
`ExternalChannel`(kind/sync_map/label, `value_for(frame_index) -> float | None`) を新設。
`model/__init__.py` で re-export。

**🚨 絶対制約 (完了条件と直結)**:
- **全フィールド既定値付きの非破壊追加** — 既存モデルの位置引数・比較・生成を一切壊さない (REQ-404)。
- **既存 226 テスト (223 passed / 3 skipped) が無改変で green**。既存テストファイルは 1 行も変更しない。
- frozen dataclass で生成・比較可能。`value_for` は欠損 `frame_index` で `None` (EDGE-102、例外を出さない)。
- `with_updates(lifecycle=...)` が機能する (既存 `PhaseInstance.with_updates` が `replace` 実装なので追加フィールドで自動的に動くことを確認)。
- **git commit しない** (ユーザー判断)。

**参照元**: `docs/tasks/m2-sequential/TASK-0011.md`, `docs/spec/m2-sequential/requirements.md`(REQ-404)

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。数値コアは numpy、GSAS-II は optional extra `gsas`。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト + `with_updates()` /
  `dataclasses.replace()` による非破壊更新 (P2)。型境界は `typing.Protocol`。
  本タスクは純粋なデータモデル拡張のみで、numpy にも Protocol にも依存しない。
- **モジュール配置**: `src/tsumugin/model/` 配下 (project.py / phase.py / hypothesis.py に channel.py を新設)。
- **参照元**: `docs/spec/m2-sequential/note.md`(技術スタック節), `pyproject.toml`, `CLAUDE.md`

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE。
- **型注釈必須** (`any` 回避)。docstring 日本語可、FR/NFR/REQ 番号を docstring に紐づける慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` (line-length 100, target py312)。
- **データモデリング**: frozen dataclass 基本。`Mapping` フィールドは `field(default_factory=dict)`
  で既定 (可変デフォルト共有を避ける既存パターン。`phase.py` の `sigma`/`occupancies` 参照)。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `docs/spec/m2-sequential/note.md`(開発ルール節), `CLAUDE.md`

---

## 3. 関連実装 (拡張・参考パターン)

### 拡張対象の既存実装 (現状のシグネチャ)
- `src/tsumugin/model/phase.py`:
  - `LatticeParams(a, b, c, alpha=90.0, beta=90.0, gamma=90.0, sigma=field(default_factory=dict))` + `.volume()`
  - `PhaseInstance(phase_ref, lattice, scale=1.0, wt_frac=None, occupancies=field(default_factory=dict))`
    + `.with_updates(**changes) -> PhaseInstance` (中身は `dataclasses.replace(self, **changes)`)
  - → **末尾に** `lifecycle: PhaseLifecycle | None = None` を追加。`PhaseLifecycle` も同ファイルに新設。
    既定引数の後ろに既定引数を足す形なので位置引数の後方互換 OK。
- `src/tsumugin/model/hypothesis.py`:
  - `Hypothesis(id, phases, parent_id=None, metrics=None, status="candidate", accepted_by=None)`
  - → **末尾に** `frame_range: tuple[int, int] | None = None` を追加。
  - `RefinementMetrics`, `HypothesisStatus` も同ファイル (本タスクでは非変更)。
- `src/tsumugin/model/channel.py`: **新規作成**。`ExternalChannel` を frozen dataclass で定義。
- `src/tsumugin/model/__init__.py`:
  - 現状 `__all__` に Dataset/Frame/HistogramRef/Hypothesis/HypothesisStatus/LatticeParams/
    PhaseInstance/Probe/Project/RefinementMetrics。
  - → `PhaseLifecycle`, `ExternalChannel` を import + `__all__` に追加。

### 設計契約 (interfaces.py 準拠、そのまま実装可)
```python
@dataclass(frozen=True)
class PhaseLifecycle:            # model/phase.py へ (§4 PhaseInstance.lifecycle / FR-305)
    birth_frame: int | None = None
    death_frame: int | None = None
    confidence: float = 1.0     # 存在確信度 [0,1]

# PhaseInstance に追加:  lifecycle: PhaseLifecycle | None = None
# Hypothesis に追加:     frame_range: tuple[int, int] | None = None

@dataclass(frozen=True)
class ExternalChannel:           # model/channel.py へ (§4 / REQ-006 / FR-321)
    kind: Literal["temperature", "time", "pressure", "custom"]
    sync_map: Mapping[int, float]        # frame_index -> value
    label: str | None = None
    def value_for(self, frame_index: int) -> float | None:
        # 欠損フレームは None を返す (EDGE-102、例外にしない) → sync_map.get(frame_index)
        ...
```
注: `sync_map` は位置必須引数だが `ExternalChannel` は新規型なので後方互換に無関係。
frozen dataclass で `Mapping` を持つ既存例は `LatticeParams.sigma`。ハッシュ不要なら問題なし
(比較は `==` で足りる。frozen + Mapping は `eq` は動くが `hash` は非ハッシュ化型で失敗するため、
テストは等価比較のみ想定)。

### top-level 公開面の扱い (要判断・後続タスク影響)
- `src/tsumugin/__init__.py` の `__all__` はアルファベット昇順必須で
  `tests/test_m1_e2e.py::test_m1_symbols_in_dunder_all_and_sorted` が固定。
- TASK-0011 の明記スコープは **`model/__init__.py` の re-export のみ**。top-level `tsumugin/__init__.py`
  への昇格は必須ではない。もし top-level にも公開する場合は `__all__` の昇順を維持すること
  (`ExternalChannel` は E、`PhaseLifecycle` は P の位置)。**最小構成では model/__init__.py だけで足りる。**

### 参考パターン
- 非破壊更新: `PhaseInstance.with_updates` が `replace` 実装のため、追加フィールドは自動対応
  → `p.with_updates(lifecycle=PhaseLifecycle(birth_frame=3))` がそのまま動く (完了条件④)。
- **参照元**: `src/tsumugin/model/{phase,hypothesis,__init__,project}.py`, `src/tsumugin/__init__.py`,
  `docs/design/m2-sequential/interfaces.py`

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py`
  (L31-54 が `PhaseLifecycle`/`ExternalChannel`、L40-41 に `PhaseInstance.lifecycle`/`Hypothesis.frame_range` 追記メモ)。
- **アーキテクチャ / データフロー**: `docs/design/m2-sequential/architecture.md`, `docs/design/m2-sequential/dataflow.md`。
- **spec §4 と現行実装の差分表**: `docs/spec/m2-sequential/note.md`(⚠️差分節) — 本タスクが埋める 3 要素
  (`Hypothesis.frame_range` / `PhaseInstance.lifecycle` / `ExternalChannel`) の対応方針が「非破壊追加」で明記。
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-004 (L34-35): 相ライフサイクル birth_frame/death_frame/confidence を追跡。
  - REQ-006 (L39-40): ExternalChannel(kind=temperature 等, frame_index→value 同期写像) をモデルに追加。
  - REQ-404 (L98-100): 拡張は既存 API 後方互換の非破壊追加 (既定値付きフィールド) でなければならない。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §4 (データモデル)、FR-305 / FR-321。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest` (既定) / `uv run pytest tests/test_model_m2.py` (本タスク単体) /
  `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。
- **マーカー**: `gsas` (GSAS-II 未導入は自動 skip)。本タスクは GSAS-II 非依存のためマーカー不要。
- **本タスクのテストファイル**: `tests/test_model_m2.py` (**新規**)。既存 `tests/test_model.py` は
  変更しない (パターン参照のみ)。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py`。現状 19 ファイル。
  `tests/conftest.py` に共通フィクスチャ。
- **命名/記述パターン** (`tests/test_model.py` に準拠):
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - 近似は `pytest.approx`。docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】と
    🔵/🟡 信頼性レベルを付す慣習 (M1 テスト群 test_clustering.py / test_m1_e2e.py 参照)。
  - 既定値検証の例: `test_defaults` (`Hypothesis(id=..., phases=())` の既定確認)。
- **本タスクで書くべき代表テスト観点** (受け入れ基準 `docs/spec/m2-sequential/acceptance-criteria.md` より):
  - `PhaseLifecycle` / `ExternalChannel` が frozen で生成・等価比較でき、再代入が `FrozenInstanceError`。
  - `ExternalChannel.value_for`: 存在フレーム→値、**欠損フレーム→None (例外なし)** (EDGE-102 / TC-105-02)。
  - `PhaseInstance` の `lifecycle` 既定 None + `with_updates(lifecycle=...)` が非破壊で機能 (完了条件④)。
  - `Hypothesis` の `frame_range` 既定 None で既存生成が後方互換。
  - **後方互換 smoke**: 既存の位置引数生成 `PhaseInstance("x", LatticeParams(5,5,5))` /
    `Hypothesis(id="h", phases=())` が従来どおり構築できる。
  - re-export: `from tsumugin.model import PhaseLifecycle, ExternalChannel` が解決し `__all__` に含まれる。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で **223 passed / 3 skipped を維持** (既存 226 が無改変 green)。
- **参照元**: `pyproject.toml`, `tests/test_model.py`, `tests/conftest.py`,
  `docs/spec/m2-sequential/acceptance-criteria.md`(TC-103/104/105)

---

## 6. 注意事項

### 技術的制約
- **非破壊性 (P2 / NFR-101 / REQ-404)**: 追加は必ず既定値付きフィールドを **末尾** に。既存フィールドの
  順序・型・既定を変えない。既存テストファイルは無改変。
- **frozen dataclass のハッシュ**: `ExternalChannel.sync_map` は `Mapping` (dict) のため、
  frozen でも `__hash__` は非ハッシュ化型で失敗し得る。テストは **等価比較 (`==`) と生成** に留め、
  set/dict キー化はしない (既存 `LatticeParams.sigma` と同じ扱い)。
- **`value_for` は例外を出さない**: 欠損は `None` (`sync_map.get(frame_index)`)。EDGE-102 の中核。
- **決定論 (NFR-202)**: 乱数不使用。純データ構造なので自然に満たす。
- **型注釈**: `Literal`, `Mapping`, `tuple[int, int] | None`, `int | None` を正しく付す。
  `from __future__ import annotations` は既存ファイルに存在 (前方参照可)。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **データモデルの器のみ**。`LifecycleTracker` / `FrameSeries` / `SequentialEngine` /
  熱膨張ベースライン等 (interfaces.py の他セクション) は **後続 TASK-0012/0015〜0020** のスコープ。
- `confidence` の**算出ロジックは実装しない** (フィールド既定 1.0 のみ。算出は lifecycle トラッカー側)。
- `echem` kind は M3。`ExternalChannel.kind` の Literal は temperature/time/pressure/custom に留める。

### 後続タスクへの影響
- **後続**: TASK-0012, 0015〜0018, 0020 が本モデル拡張に依存。フィールド名 (birth_frame/death_frame/
  confidence, sync_map, frame_range) と `value_for` シグネチャは interfaces.py の契約どおりに固定すること。

- **参照元**: `docs/spec/m2-sequential/note.md`(注意事項節), `docs/spec/m2-sequential/acceptance-criteria.md`(EDGE-102),
  `docs/design/m2-sequential/interfaces.py`, `CLAUDE.md`(不変条件)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m2-sequential/TASK-0011.md`
- 仕様/要件: `docs/spec/m2-sequential/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m2-sequential/{interfaces.py,architecture.md,dataflow.md,design-interview.md}`
- 既存実装: `src/tsumugin/model/{phase,hypothesis,__init__,project}.py`, `src/tsumugin/__init__.py`
- テスト参考: `tests/test_model.py`, `tests/test_m1_e2e.py`, `tests/conftest.py`, `pyproject.toml`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
