# TASK-0008 .gpx 書き出し export_gpx + GSASIIBackend の _build_project() 抽出 — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク要約
`src/tsumugin/export/gpx.py` に **`export_gpx(path, phases, two_theta, intensity, *, weights=None, wavelength=1.5406) -> str`** を新規実装し、
任意時点の相集合 + 観測パターンを **GSAS-II GUI で開ける `.gpx`** として永続パスへ書き出す (FR-505 / REQ-006 / D5)。
併せて **`src/tsumugin/backends/gsasii.py` の一時 gpx 構築コードを `_build_project()` ヘルパへ抽出**し、`refine` と `export_gpx` で
**単一実装を共有**する (重複実装しない / D-Q8)。GSAS-II 未導入環境では **`GSASUnavailableError`** を送出 (REQ-105)。

- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 3h / Phase 4 相互運用・UI・統合
- **信頼性レベル**: 🔵 *FR-505, 設計 D5, D-Q8* (完了条件 5 件のうち 🔵 4 / 🟡 1 = REQ-105 未導入経路)
- **主要実装**:
  1. `src/tsumugin/export/gpx.py`: `export_gpx()` 🔵
  2. `src/tsumugin/backends/gsasii.py`: `_build_project()` 抽出リファクタ (refine / export_gpx で共有) 🔵
- **テスト**: `tests/test_gpx_export.py` (新規、`@pytest.mark.gsas`)
- **依存**: 前提 [TASK-0001](../../../tasks/m1-hypothesis-search/TASK-0001.md) (パッケージ骨格 + `export/__init__.py` 済) / 後続 TASK-0010 (公開 API 統合。TASK-0006 と並行可)
- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0008.md`, `docs/tasks/m1-hypothesis-search/overview.md`

---

## 1. 技術スタック
- **言語**: Python >= 3.12 (CPython)。frozen dataclass + `typing.Protocol` 境界 (CLAUDE.md 規約)
- **バックエンド**: GSAS-II 2.x (`from GSASII import GSASIIscriptable as G2sc`)。**本タスクは GSAS-II 依存が本質** (SimulatedBackend では代替不可 — .gpx 生成は GSASIIscriptable のプロジェクト保存 API に準拠する必要がある)
- **GSAS-II 環境 (導入済み)**: ソースツリー `C:\Users\tomoo\G2` + venv の `gsas2-source.pth` + バイナリ `~/.GSASII/GSASII-bin/win_64_p3.12_n2.2`。本環境は **contract test (`@gsas`) 実行可能**
- **パッケージマネージャー**: uv 0.9.x (src layout + hatchling)。依存導入は **`uv sync --extra gsas`** (プレーン `uv sync` は gsas extra が外れるので禁止)。テスト実行 `uv run pytest`
- **コア依存**: numpy >= 1.26 のみ。gsas は optional extra (scipy / pycifrw / requests)
- **アーキテクチャ**: `export/gpx.py` は M0 の `GSASIIBackend` の gpx 構築経路を再利用する薄い書き出し層。バックエンド交換可能性 (P7) を保ちつつ、gpx 構築の**単一情報源**を `gsasii.py` 側 (`_build_project()`) に集約する
- **参照元**: `pyproject.toml`, `CLAUDE.md`, `docs/spec/m1-hypothesis-search/note.md` (§技術スタック/§依存関係), `docs/design/m1-hypothesis-search/architecture.md`

## 2. 開発ルール
- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしのコミット禁止。**git commit は本セッションでは行わない (制約)**
- **リファクタの安全性 (D-Q8 の核心)**: `_build_project()` 抽出は既存 `refine` / `simulate` の**振る舞いを一切変えない**こと。抽出は「同一挙動を保ったままコードを移動」する Refactor であり、**既存の `test_gsasii_backend.py` の全テストが退行しないこと**を Green の合格条件に含める (完了条件④)
- **非破壊性 (P2 / NFR-101)**: `export_gpx` は**書き出し専用** — 生データ・既存ファイルの削除/改変 API を作らない。出力は新規 `.gpx` パスの生成のみ。削除・上書きメソッドを追加しない
- **失敗の非例外化 (M0 規約)**: ただし `export_gpx` の **未導入経路は明示的に `GSASUnavailableError` を送出する** (chi2=inf 変換とは別 — 書き出しは精密化ループでないため。REQ-105 / TC-006-03)
- **命名/型**: snake_case / PascalCase / UPPER_SNAKE。型注釈必須 (`any` 回避)。キーワード専用引数は `*` 区切り (`weights` / `wavelength` は kw-only)
- **docstring**: 日本語可。FR/REQ 番号と 🔵🟡 信頼性レベルを紐づける (`gsasii.py` 既存の慣習を踏襲)
- **Lint**: `uvx ruff check src tests` (line-length 100, target py312)
- **参照元**: `CLAUDE.md` (実装上の不変条件/規約), `docs/spec/m1-hypothesis-search/note.md` (§開発ルール/§技術的制約), `docs/tasks/m1-hypothesis-search/TASK-0008.md`

## 3. 関連実装

### 3.1 抽出リファクタの対象 (最重要) — `src/tsumugin/backends/gsasii.py`
`refine()` (L167-233) が一時ディレクトリ内で gpx を構築している。この**構築部** (下記) を `_build_project()` ヘルパへ抽出し、
`refine` と `export_gpx` の両方から呼ぶ。**`simulate()` は別経路** (`add_simulated_powder_histogram`、観測データ無し) なので共有対象外だが、
`_add_phases()` は 3 者共通で既に切り出し済み。

**現状 `refine()` の gpx 構築ブロック (抽出候補、L177-186)**:
```python
with tempfile.TemporaryDirectory(prefix="tsumugin-g2ref-") as tmp:
    tmp_path = Path(tmp)
    instprm = tmp_path / "inst.instprm"
    datafile = tmp_path / "pattern.xye"
    _write_instprm(instprm, self.wavelength)          # ← 共有
    _write_xye(datafile, two_theta, intensity, weights) # ← 共有 (観測データ書き込み)
    gpx = G2sc.G2Project(newgpx=str(tmp_path / "refine.gpx"))  # ← パスが可変点
    hist = gpx.add_powder_histogram(str(datafile), str(instprm)) # ← 共有 (観測ヒストグラム)
    g2phases = self._add_phases(gpx, hist, model.phases, tmp_path) # ← 共有 (相追加)
    # refine 固有: set_refinements / set_HAP_refinements / do_refinements / 読み戻し
```

**抽出方針 (実装時に TDD で確定、推奨形)**:
- `_build_project(self, gpx_path: Path, work_dir: Path, phases, two_theta, intensity, weights) -> (gpx, hist, g2phases)` を新設
- 中身 = instprm 書き出し + xye 書き出し + `G2Project(newgpx=gpx_path)` + `add_powder_histogram` + `_add_phases`
- `refine` は `gpx_path = work_dir/"refine.gpx"` (一時)、`export_gpx` は `gpx_path = 永続パス` を渡す
- `refine` は返った (gpx, hist, g2phases) に対し従来どおり refinement フラグ設定 → `do_refinements` → 読み戻し
- **モジュール関数 `_write_instprm` / `_write_xye` / `_write_cif` はそのまま流用**。CIF は簡約モデル (P m m m・Ni 1 原子、モジュール docstring 参照)

### 3.2 `export_gpx()` が組み立てる処理 (D5)
`export_gpx(path, phases, two_theta, intensity, *, weights=None, wavelength=1.5406)`:
1. `gsasii_available()` False → `GSASUnavailableError` を送出 (REQ-105 / TC-006-03) — **`GSASIIBackend()` 生成を介す実装なら同エラーが自然に出る** (`__init__` が未導入で raise する既存経路を利用可)
2. `GSASIIBackend(wavelength=wavelength)` を生成し `self._build_project(Path(path), work_dir, phases, two_theta, intensity, weights)` を呼ぶ
   (一時作業ディレクトリは instprm/xye/cif 置き場に使い、**gpx 本体だけは永続 `path`** に置く点に注意 — TemporaryDirectory 消滅後もファイル参照が壊れないか実装時に検証)
3. **計算パターン (Ycalc) を含めるため** `gpx.data["Controls"]["data"]["max cyc"] = 0` → `gpx.do_refinements([{}])` で 0 サイクル実行 (D5「計算パターン込み」)
4. `gpx.save()` (G2Project の保存 API) で `path` へ確定。**戻り値は書き出しパス `str`**
- **未導入判定は書き出し実行の前** (副作用ゼロで早期 raise)。`GSASUnavailableError` は `tsumugin.errors` から import

### 3.3 参照する既存シンボル
- **`src/tsumugin/backends/gsasii.py`**:
  - `gsasii_available() -> bool` (`@lru_cache`、副作用なしで find_spec → 実 import 検証) — 未導入判定に使用
  - `GSASIIBackend.__init__(*, wavelength=1.5406)` — 未導入なら `GSASUnavailableError` を送出 (メッセージ既存)
  - `_g2sc()` (遅延 import + `SetPrintLevel("none")`)、`_add_phases()`、`_write_instprm()` / `_write_xye()` / `_write_cif()`
  - `_DEFAULT_WAVELENGTH = 1.5406` (export_gpx の既定と一致させる)
- **`src/tsumugin/errors.py`**: `GSASUnavailableError(TsumuginError)` (既存、新設不要)
- **`src/tsumugin/model/phase.py`**: `PhaseInstance(phase_ref, lattice: LatticeParams, scale, wt_frac=None, occupancies)`、`LatticeParams(a,b,c,alpha,beta,gamma)`
- **`src/tsumugin/export/__init__.py`**: 現状 `__all__ = []`。**`export_gpx` を re-export** に追加する (`from .gpx import export_gpx`)
- **参照元**: `src/tsumugin/backends/gsasii.py`, `src/tsumugin/errors.py`, `src/tsumugin/model/{phase,__init__}.py`, `src/tsumugin/export/__init__.py`

## 4. 設計文書 (契約)

### 4.1 export_gpx の型契約 (interfaces.py L207-218)
```python
def export_gpx(
    path: str,                       # 出力 .gpx パス 🔵 FR-505
    phases: Sequence[PhaseInstance],
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    wavelength: float = 1.5406,      # 🔵 M0 GSASIIBackend と同一既定
) -> str:
    """GSAS-II GUI で開ける .gpx を書き出しパスを返す。
    未導入環境では GSASUnavailableError。🔵 REQ-006/105"""
```

### 4.2 D5 .gpx 書き出し (architecture.md L116-122, 🔵)
- `export_gpx(...)`: **GSASIIBackend の gpx 構築ヘルパを永続パスで実行し `gpx.save()`**。ヒストグラム + 全相 + 計算パターン込み
- GSASIIBackend 内の一時 gpx 構築コードを **`_build_project()` として抽出・共有** (単一情報源)

### 4.3 D-Q8 GSASIIBackend との .gpx コード共有 (design-interview.md L57-63, 🔵)
- **確定**: GSASIIBackend の一時 gpx 構築部を `_build_project()` ヘルパとして抽出し、**export_gpx と refine の両方から使う (重複実装しない)**
- **根拠**: M0 実装の再利用・単一情報源

### 4.4 完了条件 (TASK-0008.md、= 受け入れ基準の TC へ遡及)
- [ ] **TC-006-01** (@gsas) 🔵: 書き出した `.gpx` を `G2sc.G2Project(<path>)` で**再オープン**でき、**相数・格子定数**が保存時と一致
- [ ] **TC-006-02** (@gsas) 🔵: `.gpx` に**ヒストグラム (観測データ)** が含まれる (`add_powder_histogram` 経由の観測 Yobs)
- [ ] **TC-006-03** 🟡: **未導入経路で `GSASUnavailableError`** (REQ-105。導入済み環境では `test_backend_raises_when_unavailable` と同様に skip 分岐で担保)
- [ ] 🔵: **GSASIIBackend の既存 contract tests が退行しない** (下記 §5 の 6 @gsas + unavailable 経路)
- [ ] 🔵 *D-Q8*: リファクタで gsasii.py の gpx 構築が**単一実装に統合**されている
- **参照元**: `docs/design/m1-hypothesis-search/interfaces.py` (L207-218), `architecture.md` (D5 L116-122),
  `design-interview.md` (D-Q8 L57-63), `docs/spec/m1-hypothesis-search/requirements.md` (REQ-006 L40 / REQ-105 L57),
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-006-01/02/03 L63-68)

## 5. テスト関連情報
- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts="-q"`)
- **マーカー**: `gsas` (`markers` に定義済み: 「GSAS-II がインストールされている環境でのみ実行する contract test」)。
  **`tests/conftest.py::pytest_collection_modifyitems` が `gsasii_available()` False のとき `@gsas` を自動 skip** する (本環境は導入済みのため実行される)
- **テストコマンド**: `uv run pytest tests/test_gpx_export.py` / `uv run pytest -m gsas` / `uv run pytest --cov=tsumugin`
- **新規テストファイル**: **`tests/test_gpx_export.py`** (実装ファイルと 1:1)。`import numpy as np` + `from tsumugin.export.gpx import export_gpx` (または `from tsumugin.export import export_gpx`)
- **書くべきケース (最小)**:
  - **TC-006-01** `@gsas`: `SimulatedBackend` or `GSASIIBackend.simulate` で合成パターン生成 → `export_gpx(tmp_path/"out.gpx", phases, tt, y)` →
    `G2sc.G2Project(<path>)` で再オープン → `len(project.phases()) == len(phases)`、各相の `get_cell()` の a/b/c が入力 `LatticeParams` と `pytest.approx` 一致
  - **TC-006-02** `@gsas`: 再オープンした project の `histograms()` が非空で、観測 Yobs (`hist.getdata("Yobs")` 相当) が入力 intensity と整合
  - **TC-006-03** (**マーカー無し** — 未導入分岐): `if gsasii_available(): pytest.skip(...)` の後 `with pytest.raises(GSASUnavailableError): export_gpx(...)`
    (既存 `test_backend_raises_when_unavailable` L25-29 と同じパターン。導入済み環境では skip される)
- **既存の contract test (退行監視対象、`tests/test_gsasii_backend.py`)**: 全 8 関数 = @gsas 6 件
  (`test_simulate_produces_nontrivial_pattern` / `test_refine_noop_returns_metrics` / `test_refine_scale_improves_fit` /
  `test_refine_lattice_recovers_cell` / `test_pipeline_ranks_hypotheses_on_gsasii_backend` / `test_staged_engine_runs_on_gsasii_backend`)
  + 未導入経路 `test_backend_raises_when_unavailable` + `test_gsasii_available_returns_bool_without_raising`。
  **`_build_project()` 抽出後もこれらが全 green であること** (タスク完了条件④「7件」= @gsas 6 + unavailable 1 の実質 contract 群を指す)
- **テスト範/書式**: `tests/test_gsasii_backend.py` の `_phase(a, scale, ref)` / `_grid()` ヘルパと `@pytest.mark.gsas` の付け方、
  `pytest.approx` (格子定数近似) の使い分けを踏襲。合成データは `GRID = np.arange(20.0, 80.0, 0.05)` 級
- **参照元**: `pyproject.toml` (`[tool.pytest.ini_options]`, `markers`), `tests/conftest.py` (自動 skip), `tests/test_gsasii_backend.py` (範/退行対象),
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-006 系)

## 6. 注意事項
- **一時ディレクトリと永続 gpx の分離 (最重要)**: `refine` は gpx も一時ディレクトリ内に置くが、`export_gpx` は **gpx 本体だけユーザ指定の永続パス**へ置く。
  instprm/xye/cif は作業一時ディレクトリで良いが、`G2Project(newgpx=<永続 path>)` + `gpx.save()` が **TemporaryDirectory の with ブロックを抜けた後もファイルとして残る**ことを保証する
  (save をブロック内で完了させる / 補助ファイル参照が gpx に埋め込まれても再オープンに支障ないかを TC-006-01 で検証)
- **計算パターンの埋め込み**: `.gpx` に Ycalc を含めるため `max cyc = 0` で `do_refinements([{}])` を 1 度回してから `save()` する
  (`simulate`/`refine` の既存パターンと同じ手法)。回さないと Ycalc 未計算の gpx になる恐れ
- **抽出は「挙動不変」の Refactor**: `_build_project()` 導入で `refine` の結果 (chi2/rwp/読み戻し) が 1 ビットも変わらないこと。
  抽出前に既存 @gsas テストを green で確認 → 抽出 → 再度 green、の順で安全網を張る (Green フェーズで既存テストも必ず走らせる)
- **未導入経路の早期・副作用ゼロ raise**: `gsasii_available()` は `@lru_cache` かつ副作用なし。書き出し処理に入る前に判定し `GSASUnavailableError` を送出。
  ファイルを作りかけて失敗する状態を残さない (非破壊・冪等性)
- **CIF 簡約モデルの制約**: 全相は P m m m・原点 Ni 1 原子に簡約される (M0/M1 の既知制約)。よって `.gpx` 再オープンで一致検証できるのは
  **相数・格子 a/b/c・角度** まで。原子種/占有率の完全再現は M1 スコープ外 (TC-006-01 は相数・格子で判定する契約)
- **wavelength の一貫性**: `export_gpx` の既定 `1.5406` は `GSASIIBackend._DEFAULT_WAVELENGTH` と同一。instprm の `Lam:` に反映される
- **公開 API 露出**: 本タスクでは `export/__init__.py` に `export_gpx` を re-export するところまで。`tsumugin/__init__.py` の `__all__` への昇格 (公開 API 統合) は **TASK-0010 のスコープ**
- **cp932 警告は無害**: GSAS-II 起動時の `~/.GSASII/config.ini` 読込警告 (cp932) は upstream の表示バグで無害
- **スコープ外**: Web UI/FastAPI (TASK-0009)・公開 API 統合と E2E とドキュメント (TASK-0010)・profile/texture 等の refinement 拡張 (M2+)
- **参照元**: `docs/spec/m1-hypothesis-search/note.md` (§技術的制約/§注意事項 — .gpx は GSASIIscriptable 保存 API 準拠・`@gsas` skip),
  `src/tsumugin/backends/gsasii.py` (simulate/refine の gpx 構築・CIF 簡約), `docs/design/m1-hypothesis-search/architecture.md` (D5), `CLAUDE.md`

---

## 収集したファイル一覧
- **タスク**: `docs/tasks/m1-hypothesis-search/TASK-0008.md`, `docs/tasks/m1-hypothesis-search/overview.md`
- **仕様**: `docs/spec/m1-hypothesis-search/note.md`, `docs/spec/m1-hypothesis-search/requirements.md` (REQ-006/105),
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-006-01/02/03)
- **設計**: `docs/design/m1-hypothesis-search/interfaces.py` (export_gpx 契約 L207-218), `docs/design/m1-hypothesis-search/architecture.md` (D5 L116-122),
  `docs/design/m1-hypothesis-search/design-interview.md` (D-Q8 L57-63)
- **抽出対象/前提実装**: `src/tsumugin/backends/gsasii.py` (refine の gpx 構築 → `_build_project()` 抽出、`gsasii_available` / `_add_phases` / `_write_*`),
  `src/tsumugin/errors.py` (`GSASUnavailableError`), `src/tsumugin/model/phase.py` (`PhaseInstance` / `LatticeParams`),
  `src/tsumugin/export/{__init__,gpx}.py` (gpx.py は本タスクで新規作成)
- **テスト範/設定/退行対象**: `tests/test_gsasii_backend.py` (既存 contract 群・書式の範), `tests/conftest.py` (@gsas 自動 skip),
  `pyproject.toml` (`[tool.pytest.ini_options]` / `markers`)。新規 `tests/test_gpx_export.py`
- **前タスクノート (書式の範)**: `docs/implements/m1-hypothesis-search/TASK-0007/note.md`
- (`AGENTS.md`, `docs/rule/` は不在 — 追加ルールは `CLAUDE.md` / `docs/spec/m1-hypothesis-search/note.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
