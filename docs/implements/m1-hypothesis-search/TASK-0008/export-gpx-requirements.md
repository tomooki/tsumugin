# TASK-0008 .gpx 書き出し export_gpx — TDD 要件定義書

- **機能名**: .gpx 書き出し (`export_gpx` 新規実装 + `GSASIIBackend._build_project()` 抽出リファクタ)
- **タスクID**: TASK-0008
- **要件名**: m1-hypothesis-search
- **実装ファイル**: `src/tsumugin/export/gpx.py` (新規) / `src/tsumugin/backends/gsasii.py` (`_build_project()` 抽出) / `src/tsumugin/export/__init__.py` (re-export 追加)
- **テストファイル**: `tests/test_gpx_export.py` (新規、`@pytest.mark.gsas`)
- **公開 API**: `src/tsumugin/export/__init__.py` に `export_gpx` を re-export (`tsumugin/__init__.py __all__` への昇格は TASK-0010)
- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 3h / Phase 4 相互運用・UI・統合
- **信頼性サマリー**: 🔵 5 / 🟡 1 / 🔴 なし — 品質評価: 高品質

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 任意時点の相集合 (`Sequence[PhaseInstance]`) と観測パターン (`two_theta`, `intensity`) を
  受け取り、**GSAS-II GUI (`GSASIIscriptable`) で再オープン可能な `.gpx` プロジェクトファイル**をユーザ指定の
  永続パスへ書き出し、書き出したパス (`str`) を返す。`.gpx` にはヒストグラム (観測データ)・全相・計算パターン (Ycalc)
  が含まれる。(REQ-006, FR-505, 設計 D5)
- 🔵 **解決する問題**: 探索・精密化で得た仮説を、解析者が GSAS-II GUI で直接開いて目視検証・追加調整できる
  標準フォーマットに落とし込む。Tsumugin の解析結果と既存の結晶学ワークフロー (GSAS-II) を橋渡しし、
  ブラックボックス化を避ける。併せて M0 の `GSASIIBackend` に散在していた gpx 構築コードを `_build_project()`
  として**単一情報源**に統合し (D-Q8)、`refine` と `export_gpx` の重複実装を防ぐ。
- 🔵 **想定ユーザー**: 粉末 XRD 解析を行う研究者、および Tsumugin の解析結果を GSAS-II へ引き渡す後続パイプライン。
  直接の呼び出し元は公開 API 統合を行う TASK-0010、および解析結果を保存したい上位モジュール。
- 🔵 **システム内での位置づけ**: M0 の `GSASIIBackend` の gpx 構築経路を再利用する**薄い書き出し層**。
  バックエンド交換可能性 (P7) を保ちつつ、gpx 構築の唯一の実装を `gsasii.py` 側 (`_build_project()`) に集約する。
  本タスクは GSAS-II 依存が本質であり `SimulatedBackend` では代替不可 (`.gpx` 生成は `GSASIIscriptable` の
  プロジェクト保存 API に準拠する必要があるため)。
- **本タスクのスコープ境界**: `export/gpx.py::export_gpx()` の実装、`gsasii.py` の `_build_project()` 抽出リファクタ
  (挙動不変)、`export/__init__.py` への re-export まで。**スコープ外**: Web UI / FastAPI (TASK-0009)、公開 API 統合・
  E2E・ドキュメント (TASK-0010)、profile/texture 等の refinement 拡張 (M2+)、原子種/占有率の完全再現 (M1 は CIF 簡約モデル)。
- **参照したEARS要件**: REQ-006 (GSAS-II GUI で開ける .gpx 書き出し), REQ-105 (未導入で GSASUnavailableError)
- **参照した設計文書**: `architecture.md` D5 (.gpx 書き出し L116-122)、`design-interview.md` D-Q8 (コード共有 L57-63)、
  `interfaces.py` (`export_gpx` 契約 L207-218)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 入力（`export_gpx` の型契約 — interfaces.py L207-218） 🔵

| 引数 | 型 | 既定 | 説明・制約 |
|------|-----|------|-----------|
| `path` | `str` | (必須) | 出力 `.gpx` パス (永続)。書き出し先の親ディレクトリは存在する前提。🔵 FR-505 |
| `phases` | `Sequence[PhaseInstance]` | (必須) | 書き出す相集合。各 `PhaseInstance(phase_ref, lattice: LatticeParams, scale, wt_frac, occupancies)`。空でないこと。🔵 |
| `two_theta` | `np.ndarray` | (必須) | 観測 2θ グリッド (float)。`intensity` と同長。🔵 |
| `intensity` | `np.ndarray` | (必須) | 観測強度 (Yobs, float)。ヒストグラムの観測データとして埋め込む。🔵 |
| `weights` | `np.ndarray \| None` | `None` | 観測重み。`None` の場合は既存 `_write_xye` の既定挙動 (統計重み) に従う。kw-only。🔵 |
| `wavelength` | `float` | `1.5406` | 波長 (Å)。instprm の `Lam:` に反映。`GSASIIBackend._DEFAULT_WAVELENGTH` と同一既定。kw-only。🔵 |

- **キーワード専用引数**: `weights` / `wavelength` は `*` 区切りの kw-only (CLAUDE.md 規約)。

### 2.2 出力 🔵

- **戻り値** `str`: 書き出しに成功した `.gpx` の永続パス (入力 `path` と一致)。
- **副作用**: `path` に GSAS-II プロジェクトファイル (`.gpx`) を新規生成。`GSASIIscriptable.G2Project(<path>)` で
  再オープンでき、相数・格子定数 (a/b/c/角度)・ヒストグラム (観測 Yobs)・計算パターン (Ycalc) を含む。
- **例外** `GSASUnavailableError` (`tsumugin.errors`): GSAS-II 未導入環境で呼ばれた場合、**書き出し処理に入る前に
  副作用ゼロで送出** (REQ-105 / TC-006-03)。

### 2.3 処理フロー・入出力の関係性（D5 / note §3.2） 🔵

```
gsasii_available() False → GSASUnavailableError (早期・副作用ゼロ raise)
  ↓ 導入済み
GSASIIBackend(wavelength=wavelength) 生成
  ↓  (作業一時ディレクトリで instprm/xye/cif を用意)
self._build_project(gpx_path=Path(path), work_dir, phases, two_theta, intensity, weights)
  = _write_instprm + _write_xye + G2Project(newgpx=<永続 path>) + add_powder_histogram + _add_phases
  ↓  → (gpx, hist, g2phases)
gpx.data["Controls"]["data"]["max cyc"] = 0 → gpx.do_refinements([{}])  (計算パターン Ycalc 埋め込み)
  ↓
gpx.save()  (永続 path へ確定)
  ↓
return str(path)
```

- **`_build_project()` の共有契約 (D-Q8)**: `refine` は `gpx_path = work_dir/"refine.gpx"` (一時) を、`export_gpx` は
  `gpx_path = 永続 path` を渡す。両者は同一ヘルパで instprm 書き出し + xye 書き出し + `G2Project` 生成 +
  `add_powder_histogram` + `_add_phases` を実行する。`refine` はこの後に refinement フラグ設定 → `do_refinements` →
  読み戻しを続ける (**refine 固有処理は _build_project の外**)。
- **参照したREQ**: REQ-006 (ヒストグラム + 全相 + 計算パターン込みの .gpx), REQ-105 (未導入 raise)
- **参照した設計文書**: `interfaces.py` `export_gpx` (L207-218)、`architecture.md` D5 (L116-122)、
  `src/tsumugin/backends/gsasii.py` `refine()` (L167-233 の gpx 構築ブロック L177-186)

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

### 3.1 抽出リファクタの挙動不変性 (D-Q8 の核心 / 完了条件④) 🔵

- `_build_project()` 抽出は既存 `refine` / `simulate` の**振る舞いを一切変えない** Refactor (同一挙動のままコード移動)。
  `refine` の結果 (chi2/rwp/読み戻し/converged) が 1 ビットも変わらないこと。
- **既存 contract test (退行監視対象)** が全 green を維持: `tests/test_gsasii_backend.py` の @gsas 6 件
  (`test_simulate_produces_nontrivial_pattern` / `test_refine_noop_returns_metrics` / `test_refine_scale_improves_fit` /
  `test_refine_lattice_recovers_cell` / `test_pipeline_ranks_hypotheses_on_gsasii_backend` /
  `test_staged_engine_runs_on_gsasii_backend`) + 未導入経路 `test_backend_raises_when_unavailable`。
- 手順: 抽出前に既存 @gsas テストを green で確認 → 抽出 → 再度 green の順で安全網を張る (Green フェーズで既存テストも走らせる)。
- `simulate()` は別経路 (`add_simulated_powder_histogram`、観測データ無し) のため `_build_project` の共有対象外。
  `_add_phases()` / `_write_instprm()` / `_write_xye()` / `_write_cif()` は既存モジュール関数をそのまま流用。

### 3.2 非破壊性 (P2 / NFR-101 相当 / REQ-402) 🔵

- `export_gpx` は**書き出し専用**。生データ・既存ファイルの削除/改変 API を作らない。出力は新規 `.gpx` パスの生成のみ。
  削除・上書きメソッドを追加しない。
- 未導入経路は**書き出し処理に入る前に早期 raise** し、ファイルを作りかけて失敗する状態を残さない (非破壊・冪等性)。

### 3.3 失敗の扱い — 書き出しは明示的に例外化 (M0 規約の例外) 🟡

- M0 の精密化ループは失敗を非例外化 (chi2=inf 変換) するが、`export_gpx` の**未導入経路は明示的に
  `GSASUnavailableError` を送出**する (書き出しは精密化ループではないため。REQ-105 / TC-006-03)。
- `gsasii_available()` は `@lru_cache` かつ副作用なし (find_spec → 実 import 検証)。書き出し処理前に判定。
- 実装は `GSASIIBackend()` 生成を介す形にすれば、`__init__` の既存未導入 raise 経路を自然に利用できる。

### 3.4 一時ディレクトリと永続 gpx の分離 (最重要な実装上の制約) 🔵

- `refine` は gpx も一時ディレクトリ内に置くが、`export_gpx` は **gpx 本体だけユーザ指定の永続 `path`** に置く。
  instprm/xye/cif は作業一時ディレクトリで良い。
- `G2Project(newgpx=<永続 path>)` + `gpx.save()` が **`TemporaryDirectory` の with ブロックを抜けた後も
  ファイルとして残る**ことを保証する (save をブロック内で完了させる / 補助ファイル参照が gpx に埋め込まれても
  再オープンに支障ないかを TC-006-01 で検証)。

### 3.5 計算パターン (Ycalc) の埋め込み 🔵

- `.gpx` に Ycalc を含めるため `gpx.data["Controls"]["data"]["max cyc"] = 0` → `gpx.do_refinements([{}])` を
  1 度回してから `save()` する (`simulate`/`refine` の既存パターンと同じ手法)。回さないと Ycalc 未計算の gpx になる恐れ。

### 3.6 コーディング / 品質制約 (CLAUDE.md) 🔵

- Python >= 3.12 / frozen dataclass + `typing.Protocol` 境界。GSAS-II 2.x (`from GSASII import GSASIIscriptable as G2sc`)。
- 型注釈必須 (`any` 回避)、キーワード専用引数は `*` 区切り、snake_case / PascalCase / UPPER_SNAKE。
- docstring は日本語可、FR/REQ 番号 + 🔵🟡 信頼性レベルを紐づける (`gsasii.py` 既存の慣習を踏襲)。
- `wavelength` の既定 `1.5406` は `GSASIIBackend._DEFAULT_WAVELENGTH` と一致させる。
- Lint: `uvx ruff check src tests` (line-length 100, target py312)。依存導入 `uv sync --extra gsas`、テスト `uv run pytest`。
  TDD 厳守・**本セッションで git commit しない**。

### 3.7 CIF 簡約モデルの検証範囲 (M1 既知制約) 🔵

- 全相は P m m m・原点 Ni 1 原子に簡約される (`_write_cif`)。よって `.gpx` 再オープンで一致検証できるのは
  **相数・格子 a/b/c・角度**まで。原子種/占有率の完全再現は M1 スコープ外 (TC-006-01 は相数・格子で判定する契約)。

- **参照したNFR/REQ**: REQ-105 (未導入 raise), REQ-402 / P2 (非破壊), NFR-101 相当
- **参照した設計文書**: `architecture.md` D5、`design-interview.md` D-Q8、`CLAUDE.md`、
  `src/tsumugin/backends/gsasii.py` (simulate/refine の gpx 構築・CIF 簡約)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本パターン — 再オープンで相数・格子一致（TC-006-01） 🔵 @gsas

- `GSASIIBackend.simulate` (or `SimulatedBackend`) で合成パターン生成 →
  `export_gpx(tmp_path/"out.gpx", phases, tt, y)` → `G2sc.G2Project(<path>)` で再オープン →
  `len(project.phases()) == len(phases)`、各相の `get_cell()` の a/b/c が入力 `LatticeParams` と `pytest.approx` 一致。

### 4.2 ヒストグラム (観測データ) 埋め込み（TC-006-02） 🔵 @gsas

- 再オープンした project の `histograms()` が非空で、観測 Yobs (`hist.getdata("Yobs")` 相当) が
  入力 `intensity` と整合 (`add_powder_histogram` 経由の観測データ)。

### 4.3 未導入経路（TC-006-03 / REQ-105） 🟡 マーカー無し

- `if gsasii_available(): pytest.skip(...)` の後 `with pytest.raises(GSASUnavailableError): export_gpx(...)`
  (既存 `test_backend_raises_when_unavailable` L25-29 と同じパターン)。**導入済み環境では skip される** ため
  本環境では未実行だが、契約として定義。書き出し前に副作用ゼロで raise すること。

### 4.4 データフロー（D5 / note §3.2） 🔵

- §2.3 のフローに従う。永続 gpx 生成 → 0 サイクル `do_refinements` (Ycalc) → `save()` → パス返却。

### 4.5 エッジ / 整合ケース

- 🔵 **既存 contract 退行なし**: `_build_project` 抽出後も `tests/test_gsasii_backend.py` の全 @gsas 6 件 +
  unavailable 1 件が green (完了条件④)。
- 🔵 **単一情報源**: リファクタ後 `gsasii.py` の gpx 構築が `_build_project()` に統合され、`refine` / `export_gpx`
  が共有 (完了条件⑤ / D-Q8)。
- 🔵 **TemporaryDirectory 消滅後の永続性**: with ブロックを抜けた後も `.gpx` が有効に再オープン可能
  (§3.4、TC-006-01 で担保)。

- **参照したEDGE**: (M1 の EDGE-001〜103 は探索側。本タスクは未導入経路 REQ-105 が主なエラーケース)
- **参照した設計文書**: `architecture.md` D5、`acceptance-criteria.md` TC-006 系、
  `tests/test_gsasii_backend.py` (退行監視対象・書式の範)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 「解析者が Tsumugin の仮説を GSAS-II GUI で開いて目視検証する」
  (M1 概要 §「.gpx 書き出し保証 (FR-505)」)
- **参照した機能要件**: REQ-006 (GSAS-II GUI で開ける .gpx 書き出し / FR-505)
- **参照した条件付き要件**: REQ-105 (GSAS-II 未導入で `GSASUnavailableError`)
- **参照した非機能要件**: REQ-402 / P2 (非破壊・書き出し専用)、NFR-102 相当 (同一入力で再現的な gpx)
- **参照した Edge ケース**: 未導入経路 (REQ-105 / TC-006-03) — M1 探索側 EDGE とは別軸
- **参照した受け入れ基準** (acceptance-criteria.md L63-68):
  - TC-006-01 🔵 (@gsas) — 生成 .gpx が `GSASIIscriptable` で再オープンでき、相数・格子定数が保存時と一致
  - TC-006-02 🔵 (@gsas) — .gpx にヒストグラム (観測データ) が含まれる
  - TC-006-03 🟡 — GSAS-II 未導入環境で `GSASUnavailableError` (unavailable 経路、導入済みは skip)
  - 完了条件④ 🔵 — `GSASIIBackend` の既存 contract tests (@gsas 6 + unavailable 1) が退行しない
  - 完了条件⑤ 🔵 (D-Q8) — リファクタで gsasii.py の gpx 構築が単一実装に統合されている
- **参照した設計文書**:
  - **アーキテクチャ**: `architecture.md` D5 (.gpx 書き出し L116-122)
  - **設計判断**: `design-interview.md` D-Q8 (GSASIIBackend との .gpx コード共有 L57-63)
  - **データフロー**: `dataflow.md` (書き出し経路 — D5 相当)
  - **型定義**: `interfaces.py` `export_gpx` (L207-218)、`model/phase.py` `PhaseInstance` / `LatticeParams`
  - **データベース**: なし (M1 は永続 DB 非導入)
  - **API 仕様**: なし (公開 API 統合は TASK-0010)
- **抽出対象 / 前提実装**:
  - `src/tsumugin/backends/gsasii.py` — `refine()` の gpx 構築ブロック (L177-186) → `_build_project()` 抽出。
    参照シンボル: `gsasii_available()` (`@lru_cache`)、`GSASIIBackend.__init__(*, wavelength=1.5406)` (未導入 raise)、
    `_g2sc()`、`_add_phases()`、`_write_instprm()` / `_write_xye()` / `_write_cif()`、`_DEFAULT_WAVELENGTH = 1.5406`
  - `src/tsumugin/errors.py` — `GSASUnavailableError(TsumuginError)` (既存、新設不要)
  - `src/tsumugin/model/phase.py` — `PhaseInstance` / `LatticeParams`
  - `src/tsumugin/export/__init__.py` — 現状 `__all__ = []`。`from .gpx import export_gpx` を追加
  - `tests/conftest.py` — `@gsas` 自動 skip (`gsasii_available()` False 時)、`pyproject.toml` `markers`/`[tool.pytest.ini_options]`

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (_build_project の抽出シグネチャ・TemporaryDirectory と永続 gpx の分離のみ「TDD で確定」と明示)
- 入出力定義: 完全 (export_gpx の全引数を型・既定・制約付きで規定、戻り値・例外・副作用を特定)
- 制約条件: 明確 (挙動不変リファクタ / 非破壊 / 未導入 raise / 永続性 / Ycalc 埋め込み / lint を条番号付きで規定)
- 実装可能性: 確実 (抽出元コードブロック L177-186・参照シンボル・GSAS-II 保存 API 経路が特定済み)
- 信頼性レベル: 🔵 5 / 🟡 1 / 🔴 0 — 🔵 優勢
```

- **要改善点 (実装時に TDD で確定すべき事項)**:
  1. 🔵 `_build_project()` の最終シグネチャ (推奨: `_build_project(self, gpx_path: Path, work_dir: Path, phases, two_theta, intensity, weights) -> (gpx, hist, g2phases)`) — refine の既存挙動を保つ形を Green で確定
  2. 🔵 `TemporaryDirectory` の with ブロック内で `save()` を完了させ、ブロック脱出後も再オープン可能なことを TC-006-01 で検証 (補助ファイル参照が gpx に埋め込まれても支障ないか)
  3. 🟡 未導入 raise の実装経路 (推奨: `GSASIIBackend()` 生成を介して `__init__` の既存 raise を利用)

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m1-hypothesis-search TASK-0008` でテストケースの洗い出しを行います。
