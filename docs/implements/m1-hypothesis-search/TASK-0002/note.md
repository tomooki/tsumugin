# TASK-0002 観測ピーク検出 find_peaks — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク概要
`Peak` frozen dataclass と `find_peaks(two_theta, intensity, *, min_height_frac=0.05)` を
**numpy のみ**で実装する（TDD, 推定 3h, Phase 2 探索コンポーネント）。
局所極大 + 最大強度比の高さ閾値でピークを検出し、`tuple[Peak, ...]` を返す。
EDGE-003（フラット/全ゼロパターン → 空タプル・例外なし）を含む。

- 対象実装: `src/tsumugin/search/peaks.py`（新規）
- テスト: `tests/test_peaks.py`（新規）
- 参照元: `docs/tasks/m1-hypothesis-search/TASK-0002.md`, `docs/tasks/m1-hypothesis-search/overview.md`

---

## 1. 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12（uv 管理, src layout + hatchling）
- **コアライブラリ**: numpy >= 1.26 のみ（本タスクは scipy 不使用・GSAS-II 非依存 = プレーン環境で完結）
- **テスト**: pytest >= 8 + pytest-cov（`uv run pytest`）
- **Lint**: `uvx ruff check src tests`（line-length 100, target py312）

### アーキテクチャパターン
- レイヤ分離（Interfaces / Agent / Orchestrator / Workers / Data）。境界は `typing.Protocol` で抽象化
- 値オブジェクトは **frozen dataclass** による不変表現（`Peak(position, height)` もこれに準拠）
- 決定論優先（同一入力 → 同一出力, NFR-102）。乱数を一切使わない

- 参照元: `CLAUDE.md`, `docs/spec/m1-hypothesis-search/note.md`, `pyproject.toml`

## 2. 開発ルール

### プロジェクト固有ルール（必須）
- **TDD 厳守**: Red（失敗テスト）→ Green（最小実装）→ Refactor。テストなしの実装コミット禁止
- **タスク毎コミット**: テスト green ごとに 1 コミット（※本ノート生成では commit しない）
- **モデル指定**: kairo/dev の全エージェントを Opus で実行
- **成果物の保存先**: 要件・設計・タスクは `docs/` 配下

### コーディング規約
- 命名: 変数/関数 `snake_case`、クラス/型 `PascalCase`、定数 `UPPER_SNAKE`、ファイル `snake_case`
- **型注釈必須**（`any` 回避）。frozen dataclass 基本、更新は非破壊（`with_updates()` / `replace()`）
- 日本語 docstring 可。FR/NFR/REQ 番号を docstring に紐づける慣習
- 公開シンボルは `src/tsumugin/__init__.py` の `__all__` と各パッケージ `__init__.py` に集約
  （`src/tsumugin/search/__init__.py` は現状 `__all__ = []` — `Peak`/`find_peaks` を追加）

- 参照元: `CLAUDE.md`（開発ワークフロー/規約/不変条件）, `docs/spec/m1-hypothesis-search/note.md`

## 3. 関連実装

### テストデータ生成の主力: SimulatedBackend
本タスクのテストは **既知ピークとの照合**で行う。`SimulatedBackend` が決定論的な合成パターンと
真のピーク位置の両方を提供するため、これを教師データに使う。

- `SimulatedBackend.simulate(phases, two_theta) -> np.ndarray`
  相ごとにガウシアンピーク列（FWHM 既定 0.2°, `peak_fwhm` で可変）を重ね合わせた強度を生成。
  ピーク中心は `2θ = 2·asin(λ / 2d)`、`d` は直方近似（1/d² = h²/a² + k²/b² + l²/c²）。
- `SimulatedBackend.peak_positions(phase, two_theta) -> list[float]`
  指定 2θ 範囲内に現れる反射の 2θ 位置（度）を返す。**find_peaks の期待値（正解位置）**として使う。
- 既定反射 `_DEFAULT_HKL` = (100),(110),(111),(200),(210),(211)。既定波長 λ=1.5406Å（Cu Kα1）。

### 既存テストが示す「局所極大」検出パターン（find_peaks 実装の直接の手本）
`tests/test_simulated_backend.py::_count_local_maxima` が numpy だけで内部点の局所極大を数える式:
```python
interior = (y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)
```
- `test_simulate_produces_one_maximum_per_in_range_reflection` は
  `min_height = 0.1 * y.max()`（最大強度比の閾値）で局所極大数 == `peak_positions` 数を検証。
  → **find_peaks の主アルゴリズム（局所極大 + `min_height_frac`×max 閾値）とテスト戦略の両方の雛形**。

### モデル型（照合対象の入力）
- `PhaseInstance(phase_ref, lattice: LatticeParams, scale, wt_frac=None, occupancies)` + `with_updates()`
- `LatticeParams(a, b, c, alpha=90, beta=90, gamma=90, sigma)` + `volume()`

- 参照元: `src/tsumugin/backends/simulated.py`（simulate / peak_positions / _d_spacing / _DEFAULT_HKL）,
  `tests/test_simulated_backend.py`, `src/tsumugin/model/phase.py`, `src/tsumugin/model/__init__.py`

## 4. 設計文書

### 契約（interfaces.py の Peak / find_peaks）
```python
@dataclass(frozen=True)
class Peak:
    position: float  # 2θ (deg)  🔵 FR-111 のマッチング単位
    height: float    # 強度        🔵

def find_peaks(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    min_height_frac: float = 0.05,  # 最大強度に対する検出下限 🟡（実装式は推測）
) -> tuple[Peak, ...]:
    """局所極大 + 高さ閾値による観測ピーク検出。numpy のみ。"""
```
- キーワード専用引数 `min_height_frac`（既定 0.05 = 最大強度の 5%）。閾値 = `min_height_frac * intensity.max()`
- 戻り値は不変タプル。順序は決定論（位置昇順が自然）
- `min_peak_height_frac` は `SearchConfig` 既定 0.05 と一致（下流の木探索設定と整合）
- 後続の `search/matcher.py::match_score(candidate_peaks, observed_peaks, *, tol_deg=0.15)` が
  `find_peaks` の出力（観測 `Peak` 列）を消費する（REQ-002/FR-111）。設計上の下流契約として意識する。

- 参照元: `docs/design/m1-hypothesis-search/interfaces.py`（search/peaks.py 節, search/matcher.py 節,
  SearchConfig.min_peak_height_frac）

### 要件・受け入れ基準の対応
- REQ-002（FR-111）: 候補相のシミュレートピークと観測ピークのマッチングスコア計算。
  find_peaks はその**前段（観測ピーク抽出）**。
- 完了条件（TASK-0002.md）:
  1. simulate 合成パターンからピーク数・位置（±1 グリッド）を正しく検出 🔵
  2. フラット/全ゼロ強度で空タプル・例外なし 🔵（EDGE-003）
  3. 閾値未満の微小ピークは検出しない 🟡
  4. 決定論（同一入力 → 同一出力）🔵 REQ-403
- EDGE-003 は acceptance-criteria の TC-005-03「フラットパターンで例外なく空の良好解 + 警告」に連なる
  基盤挙動（本タスクでは find_peaks が空タプルを返すこと）。

- 参照元: `docs/spec/m1-hypothesis-search/requirements.md`（REQ-002）,
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md`（TC-002 系 / TC-005-03=EDGE-003）,
  `docs/tasks/m1-hypothesis-search/TASK-0002.md`

## 5. テスト関連情報

- **フレームワーク/設定**: pytest。設定は `pyproject.toml [tool.pytest.ini_options]`
  （`testpaths = ["tests"]`, `addopts = "-q"`, marker `gsas`）。本タスクは gsas マーカー不要（純 numpy）。
- **ディレクトリ/命名**: 実装ファイルと 1:1 の `tests/test_*.py`。本タスクは `tests/test_peaks.py` を新規作成。
- **既存テストの書式**（`tests/test_simulated_backend.py` を範とする）:
  - モジュールレベルのヘルパ（`_phase()`, `_grid()`, `_count_local_maxima()`）
  - `_grid()` = `np.arange(15.0, 80.0, 0.02)`（本タスクの合成 2θ 軸に流用可）
  - 数値比較は `pytest.approx(..., rel=/abs=)`、決定論テストは同一入力の 2 回実行で完全一致を確認
- **推奨テストケース**（TDD Red で作る）:
  - 単相合成: `len(find_peaks(tt, y)) == len(backend.peak_positions(phase, tt))`、位置が ±1 グリッド以内
  - 多相合成でピーク数増加を確認
  - フラット（全ゼロ / 一定値）→ 空タプル・例外なし（EDGE-003）
  - `min_height_frac` を上げると微小ピークが落ちる（閾値挙動）
  - 決定論（2 回呼んで同一）
- **conftest**: `tests/conftest.py` あり（共有フィクスチャ確認先。現状 find_peaks 専用の準備は不要）。
- E2E/UI 設定: 本タスクでは対象外。

- 参照元: `pyproject.toml`, `tests/test_simulated_backend.py`, `tests/conftest.py`

## 6. 注意事項

### 技術的制約
- **numpy のみ**で実装（scipy.signal.find_peaks 等は使わない — TASK/interfaces の明示制約）。
  局所極大は `(y[1:-1] > y[:-2]) & (y[1:-1] > y[2:])` 型のベクトル比較で求める（端点の扱いに注意）。
- **決定論必須（NFR-102/REQ-403）**: 乱数不使用、戻り順序を固定（位置昇順推奨）。
- **境界/エッジ**:
  - 全ゼロ・フラット・単調配列 → 空タプル（`max()==0` や内部極大なしを安全に処理、ゼロ除算回避）。
  - `intensity.max() <= 0` のとき閾値計算で例外を出さない。
  - 隣接サンプルが等値のプラトー頂点、配列長 < 3 の極小入力。
- **入力**: `two_theta` と `intensity` は同長 np.ndarray 前提。`np.asarray(..., dtype=float)` で正規化。
- **失敗は例外でなく空/縮退結果に変換**する M0 由来の設計原則（find_peaks はフラットで raise しない）。

### パフォーマンス/セキュリティ（非破壊）上の注意
- ベクトル化で O(N) 走査。ソートは検出ピーク数程度で軽微。
- P2 非破壊性: 本タスクは純関数 + frozen dataclass のみで、削除・上書き API を作らない方針に自然に合致。

- 参照元: `CLAUDE.md`（実装上の不変条件）, `docs/design/m1-hypothesis-search/interfaces.py`,
  `docs/tasks/m1-hypothesis-search/TASK-0002.md`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m1-hypothesis-search/TASK-0002.md`, `docs/tasks/m1-hypothesis-search/overview.md`
- 仕様: `docs/spec/m1-hypothesis-search/note.md`, `.../requirements.md`, `.../acceptance-criteria.md`
- 設計: `docs/design/m1-hypothesis-search/interfaces.py`
- ルール: `CLAUDE.md`（`AGENTS.md` / `docs/rule/` は不在）
- 実装（土台）: `src/tsumugin/backends/simulated.py`, `src/tsumugin/model/phase.py`,
  `src/tsumugin/search/__init__.py`, `src/tsumugin/model/__init__.py`
- テスト: `tests/test_simulated_backend.py`, `tests/conftest.py`, `pyproject.toml`

**注意**: 本ノート内のファイルパスはすべてプロジェクトルートからの相対パスで記載。
