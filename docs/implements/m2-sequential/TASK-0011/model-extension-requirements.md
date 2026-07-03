# TASK-0011 model 拡張 TDD要件定義書

**機能名**: model 拡張 (PhaseLifecycle / ExternalChannel / frame_range)
**タスクID**: TASK-0011
**要件名**: m2-sequential
**タスクタイプ**: TDD / **推定工数**: 3h / **フェーズ**: Phase 1 - モデル/永続化基盤
**作成日**: 2026-07-03
**出力ファイル**: `docs/implements/m2-sequential/TASK-0011/model-extension-requirements.md`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M2 シーケンシャル解析基盤で用いる 3 つのデータモデル拡張を、既存 API を一切壊さずに追加する。具体的には (1) 相ライフサイクル値オブジェクト `PhaseLifecycle` (birth_frame / death_frame / confidence) の新設と `PhaseInstance.lifecycle` フィールド追加、(2) `Hypothesis.frame_range` フィールド追加、(3) 外部チャネル同期値オブジェクト `ExternalChannel` (kind / sync_map / label + `value_for`) の新設、である。
- 🔵 **どのような問題を解決するか**: 時系列 (時間/温度軸) 逐次精密化において「相がいつ出現/消滅したか (ライフサイクル)」「仮説が有効なフレーム区間」「フレームと外部物理量 (温度等) の同期」を表現する器が現行モデルに存在しない。後続の LifecycleTracker / SequentialEngine / 高温モードが依存する土台を、非破壊で用意する。
- 🔵 **想定されるユーザー**: 直接のユーザーは後続タスク (TASK-0012, 0015〜0018, 0020) の実装コードおよびシーケンシャル解析を実行する研究者。本タスク自体は内部データモデル層であり外部 UI は持たない。
- 🔵 **システム内での位置づけ**: `src/tsumugin/model/` 配下の frozen dataclass 値オブジェクト層。M0/M1 で確立した「不変値オブジェクト + `with_updates()` / `dataclasses.replace()` 非破壊更新」パターン (P2) に完全準拠する純データ拡張であり、numpy・Protocol・backend には依存しない。
- **参照したEARS要件**: REQ-004 (相ライフサイクル)、REQ-006 (ExternalChannel)、REQ-404 (非破壊追加)
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L31-54 (PhaseLifecycle / ExternalChannel 定義、PhaseInstance.lifecycle / Hypothesis.frame_range 追記メモ)、`docs/design/m2-sequential/architecture.md`

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 PhaseLifecycle（新設 / `src/tsumugin/model/phase.py`）🔵

- 🔵 **入力パラメータ (フィールド)**:
  - `birth_frame: int | None = None` — 相の出現フレーム index (未確定/未追跡は None)
  - `death_frame: int | None = None` — 相の消滅フレーム index (未消滅/未追跡は None)
  - `confidence: float = 1.0` — 存在確信度 [0,1]。本タスクでは既定値 1.0 を保持するのみ (算出ロジックは後続 LifecycleTracker スコープ)
- 🔵 **出力/振る舞い**: `@dataclass(frozen=True)`。全フィールド既定値付きのため `PhaseLifecycle()` で生成可能。生成・等価比較 (`==`) 可能。フィールド再代入は `dataclasses.FrozenInstanceError`。
- 🔵 **例**: `PhaseLifecycle(birth_frame=3)` → `PhaseLifecycle(birth_frame=3, death_frame=None, confidence=1.0)`

### 2.2 PhaseInstance.lifecycle（拡張 / `src/tsumugin/model/phase.py`）🔵

- 🔵 **追加フィールド**: 既存フィールド末尾に `lifecycle: PhaseLifecycle | None = None` を追加。
- 🔵 **現行シグネチャ**: `PhaseInstance(phase_ref, lattice, scale=1.0, wt_frac=None, occupancies=field(default_factory=dict))`
- 🔵 **入出力関係**: 既定 None のため既存の位置引数生成 `PhaseInstance("x", LatticeParams(5,5,5))` が後方互換で動作。`with_updates(lifecycle=...)` (中身は `replace`) が追加フィールドで自動的に非破壊更新でき、元インスタンスは不変。
- 🔵 **例**: `p.with_updates(lifecycle=PhaseLifecycle(birth_frame=3))` → `lifecycle` のみ差し替えた新インスタンス。

### 2.3 Hypothesis.frame_range（拡張 / `src/tsumugin/model/hypothesis.py`）🔵

- 🔵 **追加フィールド**: 既存フィールド末尾に `frame_range: tuple[int, int] | None = None` を追加。
- 🔵 **現行シグネチャ**: `Hypothesis(id, phases, parent_id=None, metrics=None, status="candidate", accepted_by=None)`
- 🔵 **入出力関係**: 既定 None のため既存生成 `Hypothesis(id="h", phases=())` が後方互換で動作。frozen 維持。
- 🔵 **例**: `Hypothesis(id="h", phases=(), frame_range=(10, 20))` → 有効区間 [10,20] を持つ仮説。

### 2.4 ExternalChannel（新設 / `src/tsumugin/model/channel.py`）🔵

- 🔵 **入力パラメータ (フィールド)**:
  - `kind: Literal["temperature", "time", "pressure", "custom"]` — 位置必須。echem は M3 スコープ外のため Literal に含めない。
  - `sync_map: Mapping[int, float]` — 位置必須。frame_index → value の同期写像。
  - `label: str | None = None` — 任意ラベル (🟡 interfaces.py で 🟡 付与)
- 🔵 **メソッド `value_for(self, frame_index: int) -> float | None`**:
  - 存在フレーム → 対応値 (float) を返す
  - 🟡 欠損フレーム → `None` を返す (例外を出さない)。実装は `sync_map.get(frame_index)`。EDGE-102 の中核。
- 🔵 **出力/振る舞い**: `@dataclass(frozen=True)`。生成・等価比較 (`==`) 可能。frozen のため再代入は `FrozenInstanceError`。
- 🟡 **例**: `ExternalChannel(kind="temperature", sync_map={0: 300.0, 1: 310.0})` → `value_for(0)==300.0`、`value_for(5) is None`。

### 2.5 re-export（拡張 / `src/tsumugin/model/__init__.py`）🔵

- 🔵 `PhaseLifecycle`・`ExternalChannel` を import し `__all__` に追加。`from tsumugin.model import PhaseLifecycle, ExternalChannel` が解決可能となる。
- 🟡 top-level `src/tsumugin/__init__.py` への昇格は本タスクの必須スコープ外 (最小構成では model/__init__.py の re-export のみ)。昇格する場合は `__all__` の昇順必須制約を維持する必要がある。

- **参照したEARS要件**: REQ-004、REQ-006、REQ-404
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` L31-54、既存実装 `src/tsumugin/model/{phase,hypothesis,__init__}.py`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **後方互換 / 非破壊性 (REQ-404 / NFR-101 / P2)**: 追加は必ず既定値付きフィールドを既存フィールドの**末尾**に置く。既存フィールドの順序・型・既定を一切変えない。既存の位置引数生成・比較・生成を壊さない。
- 🔵 **既存テスト無改変 green (完了ゲート)**: 既存 226 テスト (223 passed / 3 skipped) が**無改変**で green を維持する。既存テストファイル (`tests/test_model.py` 等) は 1 行も変更しない。
- 🔵 **frozen dataclass 制約**: すべて `@dataclass(frozen=True)`。生成・等価比較可能。再代入不可。
- 🟡 **ハッシュ制約**: `ExternalChannel.sync_map` は `Mapping` (dict) のため frozen でも `__hash__` は非ハッシュ化型で失敗し得る。テストは等価比較 (`==`) と生成に留め、set/dict キー化はしない (既存 `LatticeParams.sigma` と同じ扱い)。
- 🔵 **例外を出さない制約 (EDGE-102)**: `value_for` は欠損 frame_index で `None` を返し、決して例外を送出しない。
- 🔵 **決定論 (NFR-202 / REQ-402)**: 乱数不使用。純データ構造のため自然に満たす。
- 🔵 **型注釈必須**: `Literal` / `Mapping` / `tuple[int, int] | None` / `int | None` / `float | None` を正しく付す。`any` 回避。既存ファイルに `from __future__ import annotations` があり前方参照可。
- 🔵 **命名規則**: クラス/型は PascalCase、フィールド/関数は snake_case、ファイルは snake_case (`channel.py`)。
- 🔵 **Lint/フォーマット**: `uvx ruff check src tests` (line-length 100, target py312) 準拠。
- 🔵 **アーキテクチャ制約**: `src/tsumugin/model/` 配下の純データモデル層。numpy・Protocol・backend 非依存。可変デフォルトは `field(default_factory=...)` で回避 (該当なしだが規約遵守)。
- 🔴 **git commit しない** (ユーザー判断。本セッション制約)。

- **参照したEARS要件**: REQ-404、NFR-101、NFR-202、REQ-402、EDGE-102
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py`、`docs/spec/m2-sequential/note.md` (差分表)、`CLAUDE.md` (不変条件)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

- **ライフサイクル付き相**: `PhaseInstance("A", lat).with_updates(lifecycle=PhaseLifecycle(birth_frame=10, death_frame=15))` — 後続 LifecycleTracker.finalize() の結果を相へ紐付ける。
- **区間付き仮説**: `Hypothesis(id="h1", phases=(...), frame_range=(10, 20))` — changepoint 後の局所探索で採択された仮説の有効フレーム区間を保持。
- **温度同期**: `ExternalChannel(kind="temperature", sync_map={i: T_i for ...})` → 各フレームで `channel.value_for(i)` により温度をトラジェクトリへ反映 (TC-105-01)。

### 4.2 データフロー 🔵

- SequentialEngine が FrameSeries の各フレームを処理 → LifecycleTracker が birth/death を確定 → `PhaseLifecycle` を生成 → 相へ `lifecycle` 付与 → Trajectory へ格納。
- 高温モードでは `ExternalChannel.value_for(frame_index)` の返値を FrameRecord.temperature に反映。

### 4.3 エッジケース 🔵🟡

- 🟡 **EDGE-102 (欠損チャネル)**: `value_for` が sync_map に無い frame_index を受けた場合 → `None` を返し例外を出さない。上位はこれを軸値 None + 警告として扱う。
- 🔵 **既定値縮退**: `PhaseLifecycle()` (全 None/1.0)、`PhaseInstance.lifecycle is None`、`Hypothesis.frame_range is None` が既定として成立し、既存経路に影響しない。
- 🔵 **後方互換 smoke**: 既存の位置引数生成 (`PhaseInstance("x", LatticeParams(5,5,5))` / `Hypothesis(id="h", phases=())`) が従来どおり構築でき比較できる。

### 4.4 エラーケース 🔵

- 🔵 **frozen 再代入**: 各 frozen dataclass のフィールドへ再代入 → `dataclasses.FrozenInstanceError`。
- 🟡 **注意 (非スコープのエラー)**: `confidence` の範囲 [0,1] のバリデーションは本タスクでは実装しない (器のみ)。算出・検証は後続スコープ。

- **参照したEARS要件**: EDGE-102、REQ-404
- **参照した設計文書**: `docs/design/m2-sequential/dataflow.md`、`docs/design/m2-sequential/interfaces.py` (FrameRecord / Trajectory / LifecycleTracker)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: m2-sequential 相ライフサイクル追跡・高温シーケンシャルモード (user-stories.md)
- **参照した機能要件**:
  - REQ-004 (相ライフサイクル birth/death/confidence + ヒステリシス。本タスクは器のみ)
  - REQ-006 (ExternalChannel kind=temperature 等 + frame_index→value 同期写像をモデルへ追加)
  - REQ-404 (データモデル拡張は既存 API 後方互換の非破壊追加でなければならない)
- **参照した非機能要件**: NFR-101 (追記/非破壊 P2)、NFR-202 (決定論)、REQ-402 (ビット同一)
- **参照したEdgeケース**: EDGE-102 (チャネル欠損フレーム → None + 警告、例外なし)
- **参照した受け入れ基準** (`docs/spec/m2-sequential/acceptance-criteria.md`):
  - TC-103 系 (ライフサイクル — 本タスクは PhaseLifecycle の器の生成/比較を担保)
  - TC-105-01 (ExternalChannel(temperature) の frame→T 同期)
  - TC-105-02 / EDGE-102 (欠損フレーム → None、例外なし)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md` (model 拡張層の位置づけ)
  - **データフロー**: `docs/design/m2-sequential/dataflow.md`
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L31-54 (PhaseLifecycle / ExternalChannel / lifecycle / frame_range)
  - **既存実装**: `src/tsumugin/model/phase.py`、`src/tsumugin/model/hypothesis.py`、`src/tsumugin/model/__init__.py`
  - **タスク定義**: `docs/tasks/m2-sequential/TASK-0011.md`
  - **コンテキストノート**: `docs/implements/m2-sequential/TASK-0011/note.md`

---

## 完了条件（タスク定義より）

- [ ] PhaseLifecycle / ExternalChannel が frozen dataclass で生成・比較可能 🔵
- [ ] value_for が欠損 frame_index で None (EDGE-102、例外なし) 🔵
- [ ] PhaseInstance / Hypothesis の新フィールド既定 None で後方互換 (既存全テスト green) 🔵 *REQ-404*
- [ ] with_updates(lifecycle=...) が機能する 🔵

## 信頼性レベルサマリー

- 🔵 青信号: 大多数 (機能概要・入出力・主要制約・完了条件は interfaces.py / requirements.md / 既存実装に直接依拠)
- 🟡 黄信号: 少数 (label フィールド、value_for の None 返却詳細、top-level 昇格の扱い、100 フレーム性能検証方法)
- 🔴 赤信号: git commit しない旨のセッション制約のみ (仕様外の運用指示)
- **品質判定**: 高品質 — 要件の曖昧さなし / 入出力定義完全 / 制約条件明確 / 実装可能性確実
