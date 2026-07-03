# TASK-0018 開発コンテキストノート — thermal (熱膨張ベースライン + 転移温度推定)

**要件名**: m2-sequential / **タスクID**: TASK-0018 / **タスクタイプ**: TDD
**対象実装**: `src/tsumugin/sequential/thermal.py` / **テスト**: `tests/test_thermal.py`
**作成日**: 2026-07-03

> このノートは TDD 各フェーズ (requirements → testcases → red → green → refactor → verify) が
> 再探索なしで参照できるコンテキスト集約。全パスはプロジェクトルート相対。

---

## 1. 技術スタック

- **言語**: Python 3.12 (uv 管理、src layout + hatchling)
- **数値計算**: numpy (>=1.26)。ベースラインフィットは `numpy.polyfit` 使用可 (タスク明記)。
- **アーキテクチャパターン**: frozen dataclass (`@dataclass(frozen=True)`) + 純関数。
  境界は `typing.Protocol`。本タスクは Protocol 不要 (純関数 2 本 + 値オブジェクト 2 本)。
- **決定論**: 乱数・I/O・外部状態なし。同一入力 2 回でビット同一 (`==` 比較、`pytest.approx` 禁止箇所あり)。
- **テスト**: pytest (`uv run pytest`)。カバレッジ `uv run pytest --cov=tsumugin`。
- **Lint**: `uvx ruff check src tests` (line-length 100)。
- 参照元: `CLAUDE.md`, `pyproject.toml`

## 2. 開発ルール

- **frozen dataclass + 非破壊更新**。snake_case / PascalCase、日本語 docstring 可、型注釈必須 (`any` 回避)。
- **非有限値を漏らさない (M1 教訓)**: `inf`/`nan` を戻り値・下流に伝播させない。縮退は例外化せず安全側の値へ。
- **テストは実装ファイルと 1:1** (`tests/test_thermal.py`)。GSAS-II 依存なし → `@pytest.mark.gsas` 不要。
- **TDD 厳守**: Red(失敗テスト) → Green(最小実装) → Refactor。テストなしの実装コミット禁止。
- **モジュール実装後は `src/tsumugin/sequential/__init__.py` に re-export を追加** (既存の changepoint/lifecycle と同様)。
- **信頼性レベル注記**: コード/テストのコメントに 🔵(仕様依拠) / 🟡(妥当な推測) / 🔴(根拠なし) を付す慣習。
- 参照元: `CLAUDE.md`, `src/tsumugin/sequential/changepoint.py`, `src/tsumugin/sequential/__init__.py`

## 3. 関連実装 (参考パターン)

- **`src/tsumugin/sequential/changepoint.py`** — 本タスクの最良のスタイル手本:
  - モジュール docstring で仕様参照 (interfaces.py 行番号 / requirements §) と決定論保証を明記。
  - frozen dataclass のフィールド毎に `# 【名称】: 説明 🔵/🟡` インラインコメント。
  - ロバスト統計 (中央値/MAD の修正 z スコア `0.6745*(x-median)/MAD`)、MAD=0 縮退ガード (0 除算回避)。
  - 差分ベース判定 (線形トレンドを誤発火させない) — 本タスクの逸脱フレーム分離と同系の発想。
- **残差のロバスト z 超過による逸脱フレーム判定**: changepoint の `_robust_z` パターンを残差列へ適用する形が自然。
- 既存 sequential モジュール: `series.py` (FrameSeries), `lifecycle.py`, `trajectory.py`。
- 参照元: `src/tsumugin/sequential/changepoint.py`, `src/tsumugin/sequential/lifecycle.py`, `src/tsumugin/sequential/series.py`

## 4. 設計文書 (契約)

### 対象シンボル (`docs/design/m2-sequential/interfaces.py` L169-203)

```python
@dataclass(frozen=True)
class ThermalBaseline:
    parameter: str                     # "lattice.a" 等
    coefficients: tuple[float, ...]    # 低次から (numpy polyfit は高次からなので反転が必要) 🟡
    residuals: tuple[float, ...]
    outlier_frames: tuple[int, ...]    # ベースライン逸脱 (転移候補) 🔵

@dataclass(frozen=True)
class TransitionEstimate:
    phase_ref: str
    onset: float | None                # 10% 交差 🟡 interview Q6
    midpoint: float | None             # 50% 交差の線形補間 🟡
    sigma: float | None                # 隣接フレーム間隔ベース 🟡
    direction: Literal["appearing", "disappearing"]  # 🟡

def fit_thermal_baseline(
    temperatures: Sequence[float], values: Sequence[float], *, degree: int = 1
) -> ThermalBaseline: ...

def estimate_transition(
    temperatures: Sequence[float], fractions: Sequence[float], *, phase_ref: str
) -> TransitionEstimate | None:
    """遷移が無い場合は None。決定論 (補間ベース)。🔵 FR-323"""
```

### 要件 (`docs/spec/m2-sequential/requirements.md`)

- **REQ-007 (FR-322)**: 温度チャネル同期時、格子定数-温度曲線の**熱膨張ベースライン**を多項式
  (既定 1 次) でフィットし、ベースラインからの逸脱を分離できること。🔵 (次数既定は 🟡)
- **REQ-008 (FR-323)**: 相転移を検出し、転移温度を **onset / midpoint ± σ** で推定すること
  (相分率トラジェクトリのシグモイド遷移から推定)。🔵 (推定式は 🟡)

### 設計判断 (design-interview / タスク補足)

- **midpoint**: 分率が 50% 交差する点を隣接フレーム間で**線形補間**して求める。
- **onset**: 分率が 10% 交差する点 (onset < midpoint となる)。
- **σ**: 隣接フレーム間隔ベース (交差前後の温度間隔を散布度の代理とする)。
- **方向判定 (direction)**: 分率が増加基調なら `appearing`、減少基調なら `disappearing`。
- **遷移なし** (定数分率 / 交差が起きない) → `estimate_transition` は `None` を返す。
- **outlier_frames**: 多項式フィット残差のロバスト z (中央値/MAD) 超過フレーム = 転移候補。
- Debye-Grüneisen ベースライン・区間自動分割 (FR-316) は M-later でスコープ外。
- 参照元: `docs/design/m2-sequential/interfaces.py`, `docs/design/m2-sequential/design-interview.md` (D-Q6 は FinalSelectionEngine 用で本タスク無関係。thermal の onset/midpoint/σ 根拠は interfaces.py の "interview Q6" 注記), `docs/spec/m2-sequential/requirements.md`

## 5. テスト関連情報

- **フレームワーク**: pytest (`[tool.pytest.ini_options]` in `pyproject.toml`、`testpaths=["tests"]`, `addopts="-q"`)。
- **ディレクトリ / 命名**: `tests/test_<module>.py`。本タスクは `tests/test_thermal.py` (新規)。
- **テスト書式の範**: `tests/test_changepoint.py` (TASK-0015)。
  - モジュール docstring に対象実装・判定ロジック・書式方針・Red 期待を記載。
  - 各テスト関数の冒頭に `# 【テスト目的】/【テスト内容】/【期待される動作】/🔵🟡 信頼性レベル` コメントブロック。
  - `assert` 毎に `# 【確認内容】: ... 🔵/🟡` コメント。
  - **決定論テストは `==` (pytest.approx 禁止)**、係数/温度近似は `pytest.approx`、非有限漏洩は `math.isfinite`。
  - frozen 検証は `pytest.raises(FrozenInstanceError)`。
  - モジュールレベルで合成データ定数を一度だけ構築 (純関数のため状態レス)。
- **合成データ方針** (acceptance-criteria 冒頭): SimulatedBackend の合成シーケンス。本タスクは
  純関数なので numpy で直接合成: 線形膨張+ジャンプ (TC-105-03)、シグモイド分率遷移 (TC-105-04)。
- **未実装のため import が collection 時に失敗 → 全テスト Red** が Red フェーズの期待。
- **conftest**: `tests/conftest.py` は gsas マーカー skip のみ。本タスクに影響なし。
- 参照元: `tests/test_changepoint.py`, `tests/conftest.py`, `pyproject.toml`, `docs/spec/m2-sequential/acceptance-criteria.md`

## 6. 受け入れ基準 (完了条件) — 本タスクの検証対象

`docs/tasks/m2-sequential/TASK-0018.md` 完了条件 / `docs/spec/m2-sequential/acceptance-criteria.md`:

- [ ] **TC-105-03** 🔵: 線形膨張+ジャンプ合成データで係数が真値近傍・逸脱フレーム正しく分離。
- [ ] **TC-105-04** 🔵: シグモイド遷移で midpoint 真値 ±1 フレーム間隔、onset < midpoint、σ > 0。
- [ ] 遷移なし (定数分率) で `None` 🔵。
- [ ] appearing / disappearing の方向判定 🟡。
- [ ] **TC-105-05** 🔵: 決定論 — 転移温度推定が 2 回実行でビット同一。

信頼性サマリー: 🔵 4 / 🟡 1 — 高品質。

## 注意事項 (技術的制約)

- **numpy.polyfit の係数順**: polyfit は**高次→低次**で返す。`ThermalBaseline.coefficients` は
  **「低次から」** の契約なので `np.polyfit(...)[::-1]` で反転して格納すること。
- **residuals**: 各フレームの実測 - フィット値 (polyfit の SSR ではなく点毎残差) を想定。tuple 化。
- **outlier_frames**: 残差の中央値/MAD ロバスト z 超過 index。changepoint の `_robust_z` を踏襲。
  MAD=0 (完全フィット) は 0 除算回避で「逸脱なし ()」に縮退。
- **onset < midpoint**: 増加方向のとき onset(10%) は midpoint(50%) より低温側。減少方向では
  分率が下がるので交差の解釈に注意 (10% を「残存 10%」ではなく「変化 10% 進行」と一貫させる)。
- **決定論**: `Sequence` 入力を numpy 変換する際も順序保存。dict 反復順依存を作らない。
- **非有限を漏らさない**: σ / onset / midpoint に `nan`/`inf` を返さない。算出不能は `None`。
- **境界/縮退**: 空入力・点数 < degree+1・単調でないノイズ分率・交差が複数回等のエッジは
  testcases フェーズで洗い出す (例外化せず None / 空タプルへ縮退する方針)。
- 参照元: `docs/design/m2-sequential/interfaces.py`, `CLAUDE.md`, `src/tsumugin/sequential/changepoint.py`
