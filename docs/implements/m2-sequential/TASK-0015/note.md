# TASK-0015 FrameSeries + changepoint 検出 — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク要約
`src/tsumugin/sequential/` パッケージ (新規) に時系列コンポーネントの基盤 2 モジュールを実装する (FR-303 / REQ-003 / REQ-006, AC: TC-102-04/06):

- **`sequential/series.py` — `FrameSeries`** (frozen dataclass): シーケンシャル入力の値オブジェクト。
  `two_theta` (共通グリッド `(n_points,)`) / `intensities` (`(n_frames, n_points)`) / `axis_values` (フレーム軸値、空なら index) /
  `axis_kind` (`"time"|"temperature"|"index"|"custom"`, 既定 `"index"`) / `channels` (`tuple[ExternalChannel, ...]`)。
  `n_frames` プロパティ + **形状検証** (`intensities` と `two_theta` / `axis_values` の不一致で明示エラー)。
- **`sequential/changepoint.py` — `ChangepointConfig` / `ChangepointSignal` / `detect_changepoint()`**:
  直近 `W=5` 窓の**中央値/MAD ロバスト z スコア** (閾値 5.0) を **3 指標 (Rwp 跳ね / 格子フレーム間差分ジャンプ / 新規未マッチピーク) の OR** で判定する
  **純関数・決定論**。warm-up (履歴 < 窓) はスキップ、MAD=0 縮退 (全同値履歴) で誤発火しない。
- **`sequential/__init__.py`** (新規): 上記シンボルの re-export。

- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 2 時系列コンポーネント
- **テスト**: `tests/test_sequential_series.py` (新規) / `tests/test_changepoint.py` (新規)。いずれも numpy のみ・GSAS-II 非依存
- **依存**: 前提 TASK-0011 (`model/channel.py::ExternalChannel` 実装済み) / 後続 TASK-0019 (`SequentialEngine` が両者を消費)
- **信頼性**: 🔵 3 / 🟡 3 — 統計式 (窓/中央値/MAD/閾値/OR) は D-Q3 で実装可能形に確定済み (🟡)、契約は interfaces.py に確定 (🔵)
- **参照元**: `docs/tasks/m2-sequential/TASK-0015.md`, `docs/tasks/m2-sequential/overview.md` (関連文書節)

---

## 1. 技術スタック
- **言語**: Python >= 3.12 (CPython)。コア依存は **numpy のみ** (scipy / GSAS-II 非依存 — 本タスクは統計計算とデータ保持で完結)。
- **パッケージマネージャー**: uv (src layout + hatchling)。テスト実行 `uv run pytest`、Lint `uvx ruff check src tests` (line-length 100, target py312)。
- **アーキテクチャ**: `sequential/` は M0/M1 資産と `model/channel.py::ExternalChannel` (TASK-0011) の上に立つ**新規パッケージ**。
  `FrameSeries` は不変値オブジェクト (frozen dataclass + `model` 既存規約)。`detect_changepoint` は **(入力履歴, 設定) → 結果の純関数**で
  乱数・外部状態・I/O を持たない (REQ-402 決定論 / 将来の逐次エンジンからの毎フレーム呼び出しを阻害しない)。
- **参照元**: `pyproject.toml`, `CLAUDE.md` (§技術スタック/コマンド), `docs/design/m2-sequential/architecture.md`

## 2. 開発ルール
- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしのコミット禁止。**git commit は本セッションでは行わない**。
- **frozen dataclass + 非破壊 (P2 / CLAUDE.md コーディング規約)**: `FrameSeries` は `@dataclass(frozen=True)`。
  更新は `dataclasses.replace` / `with_updates()` 相当の非破壊更新。削除・上書き API を持たない。
- **決定論 (REQ-402 / NFR-102)**: `detect_changepoint` は乱数不使用。numpy の `median` / MAD 計算は入力のみに依存し、
  同一入力の 2 回呼び出しで**ビット同一**の `ChangepointSignal` を返す (`==` 比較、`float` フィールドも一致)。
- **失敗/縮退の非例外化 (M0 規約 / P5 縮退)**: 統計計算の縮退 (warm-up・MAD=0) は例外でなく**安全側の縮退値** (triggered=False, z=0.0) へ一元化する。
  ただし `FrameSeries` の**構造的な形状不一致は明示エラー** (器の契約違反であり縮退では表現できないため。TASK-0011 の `value_for` 欠損 None 縮退とは区別する)。
- **説明可能性 (REQ-402 / FR-303)**: `ChangepointSignal.reasons` に発火した指標名 (`"rwp_jump"` / `"lattice_jump"` / `"new_peaks"`) を保持する。
- **命名/型**: snake_case / PascalCase。型注釈必須 (`any` 回避)。キーワード専用引数は `*` 区切り (`detect_changepoint(..., *, config=...)`)。
- **docstring**: 日本語可。FR/REQ 番号と 🔵🟡 信頼性レベルを紐づける慣習 (`model/channel.py` の書式を範とする)。
- **__init__.py re-export**: `sequential/__init__.py` に `FrameSeries` / `ChangepointConfig` / `ChangepointSignal` / `detect_changepoint` を
  アルファベット順で追加 (TASK-0006 note.md の re-export 慣習に準ずる)。
- **参照元**: `CLAUDE.md` (§実装上の不変条件/§コーディング規約), `docs/tasks/m2-sequential/TASK-0015.md` (完了条件),
  `docs/design/m2-sequential/design-interview.md` (D-Q3)

## 3. 関連実装

### 3.1 完了済み前提 (TASK-0011 — 本タスクが直接消費)
- **`src/tsumugin/model/channel.py`**: `ExternalChannel(kind, sync_map, label=None)` frozen 値オブジェクト。
  `kind: Literal["temperature","time","pressure","custom"]` / `sync_map: Mapping[int, float]` (frame_index → value) /
  `value_for(frame_index) -> float | None` (欠損は None 縮退、例外なし)。**`FrameSeries.channels` の要素型**。
- **`src/tsumugin/model/__init__.py`**: `ExternalChannel` を re-export 済み (`from tsumugin.model import ExternalChannel`)。
  `PhaseLifecycle` / `Hypothesis.frame_range` / `PhaseInstance.lifecycle` も TASK-0011 で追加済み (本タスクでは未使用だが同マイルストーン基盤)。

### 3.2 参考パターン (書式・構造の範)
- **`src/tsumugin/model/channel.py`**: frozen dataclass + 日本語 docstring + 【機能概要/実装方針/テスト対応】+ 🔵🟡 信頼性注記 + 縮退規約の書式の**直近の範**。
- **`src/tsumugin/model/phase.py`** (`LatticeParams` / `PhaseInstance`): `LatticeParams(a, b, c, ...)` — 格子定数の器。
  `detect_changepoint` の `lattice_history: Sequence[Mapping[str, float]]` は各フレームの `{"a":..., "b":..., "c":...}` 相当 (LatticeParams からの抽出は呼び出し側=TASK-0019 の責務)。
- **`src/tsumugin/model/__init__.py`**: パッケージ `__init__` の re-export + `__all__` アルファベット順維持の範。
- **`src/tsumugin/errors.py`**: `TsumuginError` 基底の例外階層。`FrameSeries` の形状エラーは `ValueError` か `TsumuginError` 派生かを Red で確定 (§6 参照)。
- **既存の入力検証**: `src/tsumugin/backends/base.py:61` (`raise ValueError(f"invalid parameter name: {name!r}")`) が「不正入力は `ValueError` + 明示メッセージ」の既存慣習。
- **参照元**: `src/tsumugin/model/channel.py`, `src/tsumugin/model/phase.py`, `src/tsumugin/model/__init__.py`, `src/tsumugin/errors.py`, `src/tsumugin/backends/base.py`

## 4. 設計文書 (series.py / changepoint.py の契約)

### 4.1 interfaces.py の契約 (`docs/design/m2-sequential/interfaces.py` L62-110)
```python
@dataclass(frozen=True)
class FrameSeries:
    two_theta: np.ndarray                     # 共通グリッド (n_points,) 🔵
    intensities: np.ndarray                   # (n_frames, n_points) 🟡
    axis_values: tuple[float, ...] = ()       # フレーム軸値 (空なら index) 🔵 §4 sequence_axis
    axis_kind: Literal["time","temperature","index","custom"] = "index"  # 🔵
    channels: tuple[ExternalChannel, ...] = ()  # 🔵 REQ-006
    @property
    def n_frames(self) -> int: ...

@dataclass(frozen=True)
class ChangepointConfig:
    window: int = 5           # ローリング窓 🟡
    z_threshold: float = 5.0  # ロバスト z 閾値 🟡
    min_new_peaks: int = 1    # 新規未マッチピークの下限 🟡

@dataclass(frozen=True)
class ChangepointSignal:
    frame_index: int
    triggered: bool
    z_rwp: float
    z_lattice: float
    new_unmatched: int
    reasons: tuple[str, ...]  # "rwp_jump"|"lattice_jump"|"new_peaks" 🔵

def detect_changepoint(
    rwp_history: Sequence[float],
    lattice_history: Sequence[Mapping[str, float]],
    new_unmatched: int,
    *, config: ChangepointConfig = ChangepointConfig(),
) -> ChangepointSignal:
    """直近窓のロバスト統計 (中央値/MAD) に対する現フレームの逸脱判定。純関数・決定論。🟡"""
```

### 4.2 D-Q3: changepoint 検出の統計 (`design-interview.md` L19-22)
> 直近 **W=5** フレームの**中央値/MAD ロバスト z スコア**、**閾値 5.0**、**3 指標の OR**。
> **warm-up (W 未満) は検出スキップ**。決定論 (乱数なし)。requirements interview Q5 の実装可能化 🟡。

### 4.3 複合指標フロー (`dataflow.md` L42-57「changepoint 複合指標」)
- **Rwp 指標**: `Rwp 系列の中央値/MAD` に対する現フレーム値の robust z → `z_rwp > 5` で `rwp_jump`。
- **格子指標**: `格子 a/b/c の フレーム間差分の中央値/MAD` に対する現フレーム差分の robust z → `z_lattice > 5` で `lattice_jump`。
  **重要**: 生の格子値ではなく**フレーム間差分**に対して判定する (線形熱膨張のような滑らかなトレンドを誤発火させないため。TC-102-04 の要)。
- **新規ピーク指標**: `new_unmatched >= config.min_new_peaks` で `new_peaks`。
- 3 指標を **OR** 結合 (どれか 1 つでも発火すれば `triggered=True`)。**各指標は独立に検出可能** (TC-102-06)。
- **warm-up**: 窓が W 未満の序盤は検出をスキップ (`triggered=False`, `reasons=()`)。

### 4.4 全体フロー中の位置 (`dataflow.md` L14-40「シーケンシャル解析の全体フロー」)
`frame i` の `backend.refine` 後、`F[フレーム指標計算: Rwp / 格子微分 / 新規未マッチピーク]` → `G{複合ロバスト z > 閾値?}` の判定部が本タスク。
`FrameSeries` は同フロー最上流の入力 `A[FrameSeries: 2θ + 強度行列 + 軸値 + channels]`。両者を束ねて駆動するのは後続 **TASK-0019 `SequentialEngine`**。

### 4.5 TASK-0019 とのスコープ境界
- 本タスク: `FrameSeries` (データ保持 + 形状検証) と `detect_changepoint` (純関数の複合指標判定) の**部品 2 点**のみ。
- スコープ外 (TASK-0019 以降): warm start 逐次精密化、changepoint 近傍の局所木探索、`LifecycleTracker`、`Trajectory`、`SequentialEngine`。
  `detect_changepoint` に渡す `rwp_history` / `lattice_history` の**組み立て**は呼び出し側 (エンジン) の責務。本関数は履歴を受け取るのみ。
- **参照元**: `docs/design/m2-sequential/interfaces.py` (L62-110), `docs/design/m2-sequential/design-interview.md` (D-Q3 L19-22),
  `docs/design/m2-sequential/dataflow.md` (複合指標 L42-57 / 全体フロー L14-40), `docs/tasks/m2-sequential/TASK-0019.md` (後続スコープ)

## 5. テスト関連情報
- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`)。
- **テストコマンド**: `uv run pytest tests/test_sequential_series.py tests/test_changepoint.py` / `uv run pytest --cov=tsumugin`。
- **配置/命名**: `tests/test_sequential_series.py` と `tests/test_changepoint.py` を**新規作成** (対象モジュール未作成 → Red で import 失敗し全 fail)。
- **backend 不要**: 本タスクは `RefinementBackend` を使わない (データ保持 + 純関数統計)。`@pytest.mark.gsas` 不要、`tests/conftest.py` の gsas 自動 skip に非該当。
- **書式の範**: `tests/test_model_m2.py` (TASK-0011) — frozen 検証は `dataclasses.FrozenInstanceError`、近似は `pytest.approx`、
  決定論は `==`、【テスト目的/内容/期待/信頼性レベル】コメント + 🔵🟡 注記。正常系/異常系/境界値の 3 区分見出し。
- **numpy 配列生成の範**: `np.arange` / `np.array` / `np.stack`。`intensities` は `(n_frames, n_points)` の 2D 配列。
- **カバーすべき受け入れ基準 / 完了条件** (`acceptance-criteria.md` TC-102 + TASK-0015 完了条件):
  - 🟡 **完了条件①**: `FrameSeries` の形状不一致 (`intensities` 行数 ≠ `axis_values` 長 / `intensities` 列数 ≠ `two_theta` 長) で**明示エラー**。
  - 🔵 **完了条件②/TC-102-06**: Rwp 跳ねのみ / 格子ジャンプのみ / 新規ピークのみ、各**単独で** `triggered=True` かつ対応 `reasons` が入る。
  - 🔵 **完了条件③/TC-102-04**: 滑らかな系列 (Rwp 一定 + 格子線形膨張 + 新規ピーク 0) で `triggered=False`。
  - 🟡 **完了条件④**: warm-up (履歴 < `window`) では検出しない (`triggered=False`)。
  - 🔵 **完了条件⑤**: `reasons` に発火指標名が入る (説明可能性)。
  - 🟡 **完了条件⑥**: MAD=0 縮退 (全同値履歴) で誤発火しない (`z=0.0`, `triggered=False`)。
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_model_m2.py` (TASK-0011 書式の範),
  `docs/spec/m2-sequential/acceptance-criteria.md` (TC-102-04 L33 / TC-102-06 L35)

## 6. 注意事項
- **形状検証のエラー型 (Red で確定)**: 「明示エラー」の型は `ValueError` (既存 `backends/base.py:61` 慣習) か `TsumuginError` 派生かを Red フェーズで確定し docstring に根拠を残す。
  frozen dataclass のため検証は `__post_init__` で行い、**属性設定は伴わない** (単に raise するだけなので `object.__setattr__` 不要)。空 `axis_values` は「index 軸」を意味し検証免除 (interfaces.py の既定 `()`)。
- **ロバスト z の定義 (Red で確定・🟡)**: 修正 z スコア `0.6745 * (x - median) / MAD` (Iglewicz-Hoaglin) を採用候補とする。
  MAD = `median(|x_i - median(x)|)`。スケール定数 (0.6745) の採否は閾値 5.0 とセットで Red の期待値計算に反映し docstring に固定する。
- **窓の包含境界 (Red で確定・🟡)**: 「直近 W 窓」に現フレームを含める解釈 (窓 = 末尾 W 要素、median/MAD を窓全体で計算し末尾要素の z を評価) を推奨。
  これにより「履歴 < window で warm-up スキップ」が `len(rwp_history) < config.window` と素直に一致する。格子指標は差分列 (`diff[i]=lat[i]-lat[i-1]`) に対して同様に窓評価する。
- **格子は差分で判定 (重要・TC-102-04)**: 生の格子値でなく**フレーム間差分**に robust z を適用する。線形熱膨張は差分が一定 → MAD≈0 → z≈0 で非発火。
  生値で判定すると膨張トレンドを毎フレーム誤検出してしまうため、差分ベースが TC-102-04 (滑らかな系列で triggered=False) を通す前提となる。
- **z_lattice の a/b/c 集約 (Red で確定・🟡)**: `z_lattice` は a/b/c 各軸の robust z の**最大 (絶対値)** を採る (最も鋭敏な軸で検出)。
  `lattice_history` の各 Mapping にどのキーが存在するかは可変 (立方晶は a のみ等) — 存在キーのみで集約し、キー欠如は該当軸スキップ。
- **MAD=0 縮退 (完了条件⑥)**: 窓内全同値 → MAD=0 → 0 除算。**z=0.0 に縮退**し発火させない (全同値履歴は「変化なし」を意味するため)。
  numpy の 0 除算 warning を出さないようガード (`MAD == 0` を先に判定)。inf/nan を `reasons` や `triggered` に漏らさない (M1 レビュー教訓)。
- **`new_peaks` 指標の「z 超過」注記 (🟡)**: `dataflow.md` の図に「new_peaks ≥ 1 かつ z 超過」とあるが、`ChangepointSignal` に new_peaks 用の z フィールドは無い。
  interfaces.py の `min_new_peaks` に従い **`new_unmatched >= config.min_new_peaks` の単純カウント閾値**を採用する (図の「z 超過」は Rwp/格子側の副次記述と解釈)。Red で確定し docstring に根拠化。
- **`frame_index` の由来 (Red で確定・🟡)**: `ChangepointSignal.frame_index` は履歴末尾のインデックス (`len(rwp_history) - 1`) を採る想定。空履歴時の扱い (負値回避) を境界テストで固定。
- **決定論 (REQ-402)**: numpy の `np.median` は決定論的。dict (Mapping) の反復順に依存しない集約 (キーを明示ソート or max 集約) にする。
- **スコープ外**: `SequentialEngine` / `LifecycleTracker` / `Trajectory` / 局所木探索 / warm start は TASK-0019 以降。本タスクは部品 2 点に限定。
- **参照元**: `CLAUDE.md` (§実装上の不変条件: 決定論/非破壊/非有限値を漏らさない), `docs/design/m2-sequential/design-interview.md` (D-Q3 / 残課題),
  `docs/design/m2-sequential/dataflow.md` (複合指標図の「z 超過」注記), `docs/spec/m2-sequential/requirements.md` (REQ-003/006/402)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m2-sequential/TASK-0015.md`, `docs/tasks/m2-sequential/TASK-0019.md` (後続スコープ確認), `docs/tasks/m2-sequential/overview.md`
- 仕様: `docs/spec/m2-sequential/requirements.md` (REQ-003/006/402, EDGE-102/103/104), `docs/spec/m2-sequential/acceptance-criteria.md` (TC-102)
- 設計: `docs/design/m2-sequential/interfaces.py` (FrameSeries/ChangepointConfig/ChangepointSignal/detect_changepoint L62-110),
  `docs/design/m2-sequential/design-interview.md` (D-Q3), `docs/design/m2-sequential/dataflow.md` (複合指標 L42-57 / 全体フロー L14-40),
  `docs/design/m2-sequential/architecture.md`
- 完了済み前提実装 (TASK-0011): `src/tsumugin/model/channel.py` (`ExternalChannel`), `src/tsumugin/model/__init__.py` (re-export)
- 参考実装/構造の範: `src/tsumugin/model/phase.py` (`LatticeParams`), `src/tsumugin/errors.py` (`TsumuginError` 階層),
  `src/tsumugin/backends/base.py` (入力検証 `ValueError` 慣習)
- テスト範/設定: `tests/test_model_m2.py` (TASK-0011 書式の範), `tests/conftest.py`, `pyproject.toml`
- (`AGENTS.md`, `docs/rule/` は不在 — 追加ルールは `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
