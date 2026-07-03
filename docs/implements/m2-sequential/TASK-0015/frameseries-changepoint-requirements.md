# TASK-0015 FrameSeries + changepoint 検出 — TDD 要件定義書

- **機能名**: FrameSeries + changepoint 検出 (frameseries-changepoint)
- **タスクID**: TASK-0015
- **要件名**: m2-sequential
- **実装ファイル**: `src/tsumugin/sequential/series.py` (新規) / `src/tsumugin/sequential/changepoint.py` (新規) / `src/tsumugin/sequential/__init__.py` (新規)
- **テストファイル**: `tests/test_sequential_series.py` (新規) / `tests/test_changepoint.py` (新規)
- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 2 時系列コンポーネント
- **信頼性サマリー**: 🔵 契約 (interfaces.py) / 🟡 統計式の実装細部 (窓包含・z 定義・a/b/c 集約) — D-Q3 で実装可能形に確定済み / 🔴 なし

> **【信頼性レベル凡例】**
> - 🔵 **青信号**: EARS要件定義書・設計文書 (`interfaces.py` / `design-interview.md` / `dataflow.md` / `acceptance-criteria.md`) を参考にほぼ推測していない
> - 🟡 **黄信号**: 要件・設計から妥当な推測
> - 🔴 **赤信号**: 要件・設計にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 時系列 (時間/温度軸) の粉末回折フレーム列を保持する不変値オブジェクト **`FrameSeries`** と、
  1 フレームごとに相構成の**変化点 (changepoint) を複合指標で検出する純関数 `detect_changepoint`** を提供する。
  `detect_changepoint` は直近 `W=5` 窓の**中央値/MAD ロバスト z スコア**を **3 指標 (残差 Rwp の跳ね / 格子定数のフレーム間差分ジャンプ / 新規未マッチピーク数) の OR** で判定する。(REQ-003 / FR-303)
- 🔵 **解決する問題**: operando・高温シーケンシャル解析で、相転移や新相出現の「起きたフレーム」を機械的・決定論的に特定する。
  これにより後続の逐次エンジンが**変化点近傍だけで局所木探索**を走らせられ (REQ-101)、全フレーム総当りの計算コストを避けつつ相構成の誤り伝播を抑える。(§14 逐次解析の誤り伝播 / D-Q1)
- 🔵 **想定ユーザー**: シーケンシャル解析を駆動する上位モジュール (後続 **TASK-0019 `SequentialEngine`**)。
  `FrameSeries` を入力として受け、毎フレーム `detect_changepoint(rwp_history, lattice_history, new_unmatched)` を呼ぶ。
- 🔵 **システム内での位置づけ**: `sequential/` パッケージ (新規) の最下層基盤。M0/M1 資産と TASK-0011 の `model/channel.py::ExternalChannel` の上に立ち、
  `SequentialEngine` (TASK-0019) / `LifecycleTracker` / `Trajectory` が消費する**部品層**。`detect_changepoint` は (入力履歴, 設定) → 結果の**純関数**で乱数・I/O・外部状態を持たない (REQ-402 決定論)。
- **本タスクのスコープ境界**: `FrameSeries` (保持 + 形状検証) と `detect_changepoint` (複合指標判定) の**部品 2 点のみ**。
  warm start 逐次精密化・局所木探索・`LifecycleTracker`・`Trajectory`・`SequentialEngine` は **TASK-0019 以降**。`rwp_history` / `lattice_history` の**組み立て**は呼び出し側の責務。
- **参照したEARS要件**: REQ-003 (複合指標 changepoint), REQ-006 (ExternalChannel 紐付け), REQ-402 (決定論)
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` (L62-110)、`docs/design/m2-sequential/design-interview.md` (D-Q3)、
  `docs/design/m2-sequential/dataflow.md` (複合指標 L42-57 / 全体フロー L14-40)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 `FrameSeries` (frozen dataclass) 🔵 — `sequential/series.py`

```python
@dataclass(frozen=True)
class FrameSeries:
    two_theta: np.ndarray                       # 共通グリッド (n_points,) 🔵
    intensities: np.ndarray                     # (n_frames, n_points) 🟡
    axis_values: tuple[float, ...] = ()         # フレーム軸値 (空なら index) 🔵 §4 sequence_axis
    axis_kind: Literal["time","temperature","index","custom"] = "index"  # 🔵
    channels: tuple[ExternalChannel, ...] = ()  # 🔵 REQ-006
    @property
    def n_frames(self) -> int: ...              # intensities.shape[0]
```

| フィールド | 型 | 意味 | 信頼性 |
|---|---|---|---|
| `two_theta` | `np.ndarray` (1D, `(n_points,)`) | 全フレーム共通の 2θ グリッド | 🔵 interfaces.py L68 |
| `intensities` | `np.ndarray` (2D, `(n_frames, n_points)`) | フレーム×測定点の強度行列 | 🟡 interfaces.py L69 |
| `axis_values` | `tuple[float, ...]` (既定 `()`) | フレーム軸値。空なら index 軸 | 🔵 interfaces.py L70 |
| `axis_kind` | `Literal[...]` (既定 `"index"`) | 軸種別 | 🔵 interfaces.py L71 |
| `channels` | `tuple[ExternalChannel, ...]` (既定 `()`) | 外部チャネル (温度等) | 🔵 REQ-006 / interfaces.py L72 |

- 🔵 **`n_frames` プロパティ**: `intensities.shape[0]` を返す (フレーム数)。
- 🟡 **形状検証 (完了条件①)**: `__post_init__` で以下を検証し、不一致は**明示エラー**を送出する:
  1. `intensities` は 2D で `intensities.shape[1] == len(two_theta)` (測定点数一致)。
  2. `axis_values` が非空なら `len(axis_values) == intensities.shape[0]` (フレーム数一致)。
  - 空 `axis_values` は「index 軸」を意味し検証免除 (interfaces.py の既定 `()`)。
  - エラー型は `ValueError` (既存 `backends/base.py:61` の入力検証慣習) を第一候補とし、Red で確定して docstring に根拠を残す (🟡)。

### 2.2 `ChangepointConfig` (frozen dataclass) 🔵/🟡 — `sequential/changepoint.py`

```python
@dataclass(frozen=True)
class ChangepointConfig:
    window: int = 5           # ローリング窓 W 🟡
    z_threshold: float = 5.0  # ロバスト z 閾値 🟡
    min_new_peaks: int = 1    # 新規未マッチピークの下限 🟡
```

| フィールド | 既定値 | 意味 | 信頼性 |
|---|---|---|---|
| `window` | 5 | 直近ローリング窓のフレーム数 W | 🟡 D-Q3 (W=5) |
| `z_threshold` | 5.0 | robust z の発火閾値 | 🟡 D-Q3 (閾値 5.0) |
| `min_new_peaks` | 1 | `new_peaks` 指標の発火下限 | 🟡 interfaces.py L88 |

### 2.3 `ChangepointSignal` (frozen dataclass) 🔵 — `sequential/changepoint.py`

```python
@dataclass(frozen=True)
class ChangepointSignal:
    frame_index: int
    triggered: bool
    z_rwp: float
    z_lattice: float
    new_unmatched: int
    reasons: tuple[str, ...]  # "rwp_jump"|"lattice_jump"|"new_peaks" 🔵
```

- 🔵 `reasons` は発火した指標名のみを保持 (説明可能性、REQ-402 / 完了条件⑤)。発火なしなら `()`。
- 🔵 `triggered == (len(reasons) > 0)` (3 指標の OR)。

### 2.4 `detect_changepoint()` の入出力 🔵/🟡 — `sequential/changepoint.py`

```python
def detect_changepoint(
    rwp_history: Sequence[float],
    lattice_history: Sequence[Mapping[str, float]],
    new_unmatched: int,
    *, config: ChangepointConfig = ChangepointConfig(),
) -> ChangepointSignal
```

- 🔵 **入力**:
  - `rwp_history`: 直近フレームまでの Rwp 値の並び (末尾が現フレーム)。
  - `lattice_history`: 各フレームの格子定数マッピング `{"a":..., "b":..., "c":...}` の並び (末尾が現フレーム)。存在キーは相系により可変 (立方晶は `a` のみ等)。
  - `new_unmatched`: 現フレームの新規未マッチピーク数 (非負整数)。
  - `config`: 窓/閾値/下限 (キーワード専用)。
- 🔵 **出力**: `ChangepointSignal` (現フレーム 1 件の判定結果)。
- 🟡 **判定ロジック (D-Q3 / dataflow.md 複合指標)**:
  1. **warm-up**: `len(rwp_history) < config.window` なら検出スキップ → `triggered=False, reasons=(), z_rwp=0.0, z_lattice=0.0`。
  2. **z_rwp**: 直近 `window` 個の Rwp に対する現フレーム値の robust z (modified z-score `0.6745·(x−median)/MAD`)。`z_rwp > z_threshold` で `"rwp_jump"`。
  3. **z_lattice**: 格子 a/b/c 各軸の**フレーム間差分**列に対する現フレーム差分の robust z を取り、**各軸の最大絶対 z** を `z_lattice` とする。`z_lattice > z_threshold` で `"lattice_jump"`。
     - **重要**: 生の格子値でなく差分に適用する (線形熱膨張の滑らかなトレンドを誤発火させない — TC-102-04 の要)。
  4. **new_peaks**: `new_unmatched >= config.min_new_peaks` で `"new_peaks"`。
  5. **OR 結合**: いずれか発火で `triggered=True`。`reasons` に発火指標名を発生順で格納。
  6. **MAD=0 縮退**: 窓内全同値で MAD=0 のとき、当該指標の z を `0.0` に縮退させ発火させない (完了条件⑥)。
- 🟡 **`frame_index`**: 履歴末尾インデックス `len(rwp_history) - 1` を採る想定 (Red で確定)。

- **参照したEARS要件**: REQ-003 (複合指標), REQ-006 (channels), REQ-402 (決定論)
- **参照した設計文書**: interfaces.py `FrameSeries` / `ChangepointConfig` / `ChangepointSignal` / `detect_changepoint` (L62-110)、
  dataflow.md 複合指標フロー (L42-57)、design-interview.md D-Q3 (L19-22)

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (REQ-402 / NFR-102)**: `detect_changepoint` は乱数不使用。同一入力・同一設定の 2 回呼び出しで `ChangepointSignal` が**ビット同一** (`==`、`float` フィールド含む)。
  Mapping (格子) の反復順に結果が依存しないよう、キー集約は明示規則 (ソート or max) を用いる。
- 🔵 **純関数・副作用なし (REQ-404 / 全体フロー毎フレーム呼び出し)**: `detect_changepoint` は I/O・外部状態・グローバルを持たず、将来の並列 map 置換を阻害しない。
- 🔵 **非破壊・不変性 (P2 / CLAUDE.md)**: `FrameSeries` / `ChangepointConfig` / `ChangepointSignal` は `@dataclass(frozen=True)`。フィールド再代入は `FrozenInstanceError`。削除・上書き API を持たない。
- 🔵 **非有限値を漏らさない (M1 レビュー教訓 / CLAUDE.md)**: MAD=0・warm-up・空履歴などの縮退で `inf` / `nan` を `z_rwp` / `z_lattice` / `triggered` に漏らさない。0 除算は先行ガードで回避。
- 🟡 **縮退の非例外化 vs 形状の明示エラー (M0 規約 / P5)**: 統計計算の縮退 (warm-up・MAD=0) は例外でなく安全側縮退値へ。
  一方 `FrameSeries` の**構造的形状不一致は明示エラー** (器の契約違反であり縮退では表現できない。TASK-0011 の `value_for` 欠損 None 縮退とは区別)。
- 🔵 **技術スタック**: Python >= 3.12 / **numpy のみ** (scipy・GSAS-II 非依存)。型注釈必須 (`any` 回避)、キーワード専用引数は `*` 区切り。
  Lint `uvx ruff check src tests` (line-length 100, py312)。**本セッションで git commit しない**。
- 🔵 **依存関係**: `FrameSeries.channels` の要素型は `tsumugin.model.ExternalChannel` (TASK-0011 実装済み) を import して用いる。
- 🟡 **パフォーマンス**: 毎フレーム呼び出しのため軽量 (窓 O(W) の median/MAD)。厳密な数値目標は本タスクでは課さない (逐次全体の NFR-103 は TASK-0019 スコープ)。
- **参照したEARS要件**: REQ-402 (決定論/ビット同一), REQ-404 (並列化配慮), REQ-003/006
- **参照した設計文書**: `CLAUDE.md` (§実装上の不変条件/§コーディング規約)、design-interview.md D-Q3、interfaces.py

---

## 4. 想定される使用例（Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵
- **FrameSeries 構築**: `FrameSeries(two_theta=tt, intensities=mat, axis_values=(300.0, 310.0, ...), axis_kind="temperature", channels=(ExternalChannel("temperature", {...}),))`。`n_frames` が行数を返す。
- **単独指標検出 (TC-102-06)**: Rwp 跳ねのみ / 格子ジャンプのみ / 新規ピークのみのシナリオで、それぞれ**単独で** `triggered=True` かつ対応 `reasons` が 1 件入る。
- **滑らかな系列 (TC-102-04)**: Rwp 一定 + 格子線形膨張 + 新規ピーク 0 の系列で `triggered=False`、`reasons=()`。

### 4.2 データフロー 🔵
- `dataflow.md` 全体フロー: `backend.refine` → `F[フレーム指標計算: Rwp / 格子微分 / 新規未マッチピーク]` → `G{複合ロバスト z > 閾値?}`。この `F`→`G` の判定が `detect_changepoint`。
- `dataflow.md` 複合指標: `A[直近 W=5 窓]` → {`B[Rwp 中央値/MAD]`, `C[格子 a/b/c 差分 中央値/MAD]`, `D[新規未マッチピーク数]`} → 各 z 判定 → OR → `H[changepoint!]`。

### 4.3 決定論 🔵
- 同一の `rwp_history` / `lattice_history` / `new_unmatched` / `config` に対する 2 回呼び出しで `ChangepointSignal` がビット同一。

### 4.4 エッジケース / 縮退ケース 🔵/🟡
- 🟡 **warm-up (完了条件④)**: 履歴長が `window` 未満 (例 3 フレーム, window=5) → 検出しない (`triggered=False`)。
- 🟡 **MAD=0 縮退 (完了条件⑥ / 全同値履歴)**: 窓内 Rwp が全同値 → MAD=0 → `z_rwp=0.0`、発火しない。格子差分が全同値でも同様。
- 🟡 **形状不一致 (完了条件①)**: `intensities.shape[1] != len(two_theta)` または `axis_values` 非空で長さ ≠ `n_frames` → 明示エラー。
- 🟡 **空 `axis_values`**: index 軸として検証免除・`n_frames` は `intensities` から算出。
- 🟡 **格子キー可変**: `lattice_history` の各 Mapping が `a` のみ (立方晶) でも動作し、存在軸のみで `z_lattice` を集約する。
- 🟡 **new_peaks 単純カウント**: dataflow 図の「new_peaks ≥ 1 かつ z 超過」注記に対し、`ChangepointSignal` に new_peaks 用 z が無いため `new_unmatched >= min_new_peaks` の単純閾値を採用 (Red で docstring 根拠化)。

- **参照したEARS要件**: EDGE-102 (channel 欠損は上位で None+警告), EDGE-103 (全フレーム changepoint でも完走), EDGE-104 (changepoint ゼロ)
- **参照した設計文書**: dataflow.md (複合指標 L42-57 / 全体フロー L14-40)、acceptance-criteria.md TC-102-04/06

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 高温/operando シーケンシャル解析での相転移フレーム特定 (シーケンシャル解析基盤)
- **参照した機能要件**:
  - REQ-003 (changepoint を複合指標 — (a) Rwp の跳ね / (b) 格子フレーム間微分 / (c) 新規未マッチピーク — で検出) *FR-303*
  - REQ-006 (ExternalChannel をデータモデルに追加しフレームへ紐付け — `FrameSeries.channels`) *§4/FR-321*
  - REQ-402 (同一入力でシーケンシャル出力がビット同一 — `detect_changepoint` の決定論) *NFR-102*
- **参照した非機能要件**: NFR-102 (決定論/ビット同一 = REQ-402), NFR-103 (非探索区間 ≤10秒/フレーム = 軽量判定の背景, 検証は TASK-0019)
- **参照したEdgeケース**: EDGE-102 (channel 欠損), EDGE-103 (全フレーム changepoint), EDGE-104 (changepoint ゼロ → 木探索なし)
- **参照した受け入れ基準** (`docs/spec/m2-sequential/acceptance-criteria.md`):
  - TC-102-04 (変化のない滑らかなシーケンスで changepoint ゼロ)
  - TC-102-06 (複合指標 — 格子ジャンプのみ/残差跳ねのみ/未マッチピークのみ、それぞれ単独で検出)
- **参照した設計文書**:
  - **型定義**: `docs/design/m2-sequential/interfaces.py` (`FrameSeries` L62-73 / `ChangepointConfig` L81-87 / `ChangepointSignal` L90-99 / `detect_changepoint` L102-110)
  - **データフロー**: `docs/design/m2-sequential/dataflow.md` (複合指標 L42-57 / 全体フロー L14-40)
  - **設計判断**: `docs/design/m2-sequential/design-interview.md` (D-Q3 changepoint 統計 L19-22)
  - **既存実装**: `src/tsumugin/model/channel.py` (`ExternalChannel`, TASK-0011)、`src/tsumugin/model/phase.py` (`LatticeParams`)、`src/tsumugin/errors.py`
  - **スコープ境界**: `docs/tasks/m2-sequential/TASK-0019.md` (`SequentialEngine` が `FrameSeries` + `detect_changepoint` を消費)

---

## 6. 品質判定

- ✅ **要件の曖昧さ**: 小 (完了条件がすべて acceptance-criteria の TC / 完了条件に遡及、統計式は D-Q3 で確定)
- ✅ **入出力定義**: 完全 (interfaces.py の frozen dataclass 契約に一致、判定ロジックを 6 ステップで明記)
- ✅ **制約条件**: 明確 (決定論・非破壊・非有限値非漏洩・縮退の非例外化を数式/閾値で規定)
- ✅ **実装可能性**: 確実 (前提 TASK-0011 完了、numpy のみで完結、外部依存なし)
- **残る 🟡 (Red → Green で挙動を確定させ docstring に根拠を残す)**:
  1. `FrameSeries` 形状エラーの型 (`ValueError` vs `TsumuginError` 派生)
  2. ロバスト z の定義 (modified z-score `0.6745·(x−median)/MAD`) とスケール定数の採否
  3. 窓の包含境界 (現フレームを窓に含める / 格子差分列の窓境界)
  4. `z_lattice` の a/b/c 集約規則 (最大絶対 z)
  5. `new_peaks` の単純カウント閾値解釈 (dataflow 図「z 超過」注記との整合)
  6. `frame_index` の由来 (`len(history)-1`)
- **総合判定**: 高品質 (契約は 🔵 で確定、🟡 は統計式のチューニング細部に集中し要件へ遡及可能、🔴 なし)
