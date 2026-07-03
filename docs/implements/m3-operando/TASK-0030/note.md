# TASK-0030 TDD 開発コンテキストノート

**タスク**: operando/cell_phases — セル固定相プリセット (`FixedPhaseSpec` / `CELL_PHASE_PRESETS` (Be/Al/graphite) / `fixed_free_suffixes` ヘルパ)
**要件名**: m3-operando / **タスクID**: TASK-0030 / **タイプ**: TDD / **推定 2h**
**フェーズ**: Phase 3 (operando 電池モード) / **信頼性**: 🔵 1 / 🟡 2 (FR-312 / REQ-009 / AC TC-203 系、格子値は 🟡)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

M3 operando のセル構成材料 (窓・集電体・活物質でない不活性相) を「構造固定・scale のみ解放で探索に常駐する固定相」
として供給する層を新設する。`src/tsumugin/operando/cell_phases.py` を新規作成し、以下 3 要素を実装する:

1. **`FixedPhaseSpec` frozen dataclass** — セル固定相の指定。フィールドは `phase: PhaseInstance` と `label: str` の 2 つ
   (interfaces.py L236-241 の契約どおり)。「構造固定・scale のみ解放・探索常駐」を表す値オブジェクト。
2. **`CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]`** — キー `"Be"` / `"Al"` / `"graphite"` の 3 プリセット。
   各値は文献格子定数の**直方 (orthorhombic) 近似** (SimulatedBackend の `_d_spacing` が 90° 直方系前提のため) を
   `LatticeParams` に格納した `PhaseInstance` を包む。**docstring に近似の注意 (直方近似・文献値の出典) を明記**する。
3. **`fixed_free_suffixes(spec: FixedPhaseSpec) -> tuple[str, ...]`** — 固定相の解放パラメータ suffix 展開ヘルパ。
   常に `("scale",)` を返す (構造固定 = lattice/occupancy は解放しない)。呼び側 (TASK-0032 discrimination /
   TASK-0033 segmentation) が `param_name(i, "scale")` で `free_params` を組む際の単一の真実源。

**プリセット格子定数 (文献値 → 直方近似)** — docstring に出典と近似方針を必ず記載:
- **Be (hcp)**: 文献 a=2.2858 Å, c=3.5843 Å。六方晶を直方近似する際は orthohexagonal セル `a'=a, b'=a·√3, c'=c`
  (b' ≈ 3.9591 Å) を採る。**近似のため実回折とはピーク位置がずれうる旨を docstring に明記**。🟡
- **Al (fcc)**: 文献 a=4.0495 Å。立方晶なので `a=b=c=4.0495`、直方近似の歪みなし。🟡
- **graphite (hexagonal)**: 文献 a=2.464 Å, c=6.711 Å。orthohexagonal `a'=a, b'=a·√3` (b' ≈ 4.2678 Å), `c'=c`。🟡

**🚨 絶対制約 (完了条件と直結)**:
- **プリセット 3 種取得** (TC-203-01): `CELL_PHASE_PRESETS["Be"|"Al"|"graphite"]` が `FixedPhaseSpec` を返す 🔵。
  ※ AC 原文は「PhaseCandidate として取得」だが、**interfaces.py L236-244 の確定契約は `FixedPhaseSpec`** であり本タスクは
  そちらを正典とする (下記「注意事項/契約の不一致」参照)。
- **scale のみ解放** (TC-203-02): 固定相は構造固定・探索常駐 (枝刈り対象外)。`fixed_free_suffixes(spec) == ("scale",)` で
  lattice/occupancy を解放しない 🟡 (design-interview の固定相方針・REQ-009 字義)。
- **固定相込み合成データで活物質相同定** (TC-203-03): 固定相 (scale のみ解放) を含めた精密化で活物質相が正しく精密化される 🔵。
- **格子値が文献値近傍** (完了条件3): プリセット `LatticeParams` の値が docstring 記載の文献値と一致 🟡。
- **既存 API 非破壊**: `PhaseInstance` / `LatticeParams` (model)、`param_name` (backends.base) を**利用のみ**。model は変更しない。
- **決定論 (NFR-102)**: プリセットはモジュールロード時に確定する固定定数。同一入力 → ビット同一。乱数不使用。
- **コア依存 numpy のみ** (REQ-403): 外部ライブラリ (pymatgen 等) 不使用。格子値はハードコード定数。
- **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。

**参照元**: `docs/tasks/m3-operando/TASK-0030.md`, `docs/design/m3-operando/interfaces.py` L232-244,
`docs/spec/m3-operando/requirements.md` REQ-009, `docs/spec/m3-operando/acceptance-criteria.md` TC-203-01〜03,
`docs/design/m3-operando/architecture.md` L38 (cell_phases 行)

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは **`dataclasses` / `typing` + 定数定義のみ**。
  格子近似の `√3` は `math.sqrt(3)` (stdlib) で足り、numpy すら実装本体では不要 (テスト側で numpy 使用)。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト (`FixedPhaseSpec`) + モジュールレベル定数テーブル
  (`CELL_PHASE_PRESETS`) + 純粋関数ヘルパ (`fixed_free_suffixes`)。M0〜M2 の値オブジェクト規約 (frozen・非破壊) と同型。
- **モジュール配置**: `src/tsumugin/operando/cell_phases.py` (**新規ファイル**、`operando/` は TASK-0029 で新設済)。
  `operando/__init__.py` に公開シンボルを re-export 追加 (`FixedPhaseSpec` / `CELL_PHASE_PRESETS` / `fixed_free_suffixes`)。
- **精密化との接続**: `FixedPhaseSpec.phase` は既存 `SimulatedBackend` (`backends/simulated.py`) がそのまま
  simulate/refine できる `PhaseInstance`。固定相の `free_params` は `param_name(i, "scale")` (backends.base) で構成する。
- **参照元**: `docs/spec/m3-operando/note.md` (技術スタック節), `pyproject.toml`, `CLAUDE.md`,
  `docs/design/m3-operando/architecture.md` L38/L114/L121

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: クラス/型 PascalCase (`FixedPhaseSpec`)、定数 UPPER_SNAKE (`CELL_PHASE_PRESETS`)、
  関数/フィールド snake_case (`fixed_free_suffixes` / `phase` / `label`)、ファイル snake_case (`cell_phases.py`)。
- **型注釈必須** (`any` 回避)。`Mapping[str, FixedPhaseSpec]` / `tuple[str, ...]` を正しく付す。
  `from __future__ import annotations` を冒頭に置く。
- **docstring 規約**: 日本語可、FR/REQ/TC 番号を紐づけ、信頼性レベル 🔵🟡🔴 を付す慣習。
  **格子値は文献出典と直方近似の注意を必ず docstring に記載** (完了条件・タスク指示)。
- **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- **決定論 (NFR-102)**: プリセットは不変定数。実行のたびに同一オブジェクト。乱数・環境依存なし。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。**質問しない**。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `CLAUDE.md`, `docs/spec/m3-operando/note.md` (開発ルール節)

---

## 3. 関連実装 (拡張・参考パターン)

### 依存する既存実装 (利用のみ・変更しない)

- `src/tsumugin/model/phase.py`:
  - `PhaseInstance(phase_ref, lattice, scale=1.0, wt_frac=None, occupancies={}, lifecycle=None)` (L48-62) —
    固定相はこれを包む。`with_updates` で非破壊更新。`FixedPhaseSpec.phase` に格納。
  - `LatticeParams(a, b, c, alpha=90, beta=90, gamma=90, sigma={})` (L10-30) — 直方近似は角 90° 既定のまま a/b/c を設定。
  - → **model は一切変更しない** (非破壊利用)。`from tsumugin.model import LatticeParams, PhaseInstance` で取り込む。
- `src/tsumugin/backends/base.py`:
  - `param_name(phase_index, key) -> "phase{i}.{key}"` (L56-58) — `fixed_free_suffixes` の結果を呼び側が
    `param_name(i, "scale")` へ組む。`parse_param` も対 (L61-74)。
- `src/tsumugin/backends/simulated.py`:
  - `SimulatedBackend`: `_d_spacing` が **直方 (orthorhombic) 近似** `1/d² = h²/a² + k²/b² + l²/c²` (L67-75) を用いる。
    → **プリセット格子を直方近似する理由がここにある** (六方晶をそのまま a=b で入れると b 方向反射が縮退する)。
    `simulate` / `refine` はプリセット `PhaseInstance` をそのまま処理でき、TC-203-03 の合成検証に使える。
  - `refine` は `_recognized` (L137-143) で `scale` を認識。固定相の `free_params` に `phase{i}.scale` のみ入れると
    scale だけが最適化され lattice は固定される (TC-203-02 の「scale のみ解放」が backend レベルで担保される)。

### 参考パターン (既存コードから踏襲)

- **frozen 値オブジェクト**: `PhaseCandidate` (`src/tsumugin/search/clustering.py` L26-33、`phase` / `delta_u` / `label`)
  が最も近い範。`FixedPhaseSpec` は `delta_u` を持たず `label` が必須 (`str`、`None` 不可) な点が差分。
- **モジュール定数テーブル**: `backends/simulated.py` の `_DEFAULT_HKL` / `_LATTICE_KEYS` (L20-32) がモジュール
  レベル不変タプル定数の範。`CELL_PHASE_PRESETS` は同様に読み取り専用 `Mapping` (`types.MappingProxyType` か
  素の dict リテラル。frozen 値のみ格納するため実務上不変)。
- **純粋関数ヘルパ**: `backends/base.py` `param_name` / `parse_param` のような副作用なし小関数が `fixed_free_suffixes` の範。
- **公開 re-export**: `operando/__init__.py` (TASK-0029) の `from .echem import ...` + `__all__` パターンを踏襲し
  `from .cell_phases import FixedPhaseSpec, CELL_PHASE_PRESETS, fixed_free_suffixes` を追加。

### 後続タスクの利用先

- **TASK-0032** (後続, discrimination): `discriminate_interval(..., fixed_phases: tuple[FixedPhaseSpec, ...] = ())`
  (interfaces.py L281) が固定相を受ける。両仮説の精密化で固定相の scale のみ解放して常駐させる。
  → `FixedPhaseSpec` フィールド名 (`phase` / `label`) と `fixed_free_suffixes` の戻り `("scale",)` を固定すること。
- **TASK-0033** (後続, segmentation): `segment_series(..., fixed_phases: tuple[FixedPhaseSpec, ...] = ())`
  (interfaces.py L319) も同契約で固定相を受ける。

- **参照元**: `src/tsumugin/model/phase.py`, `src/tsumugin/backends/base.py`, `src/tsumugin/backends/simulated.py`,
  `src/tsumugin/search/clustering.py` (PhaseCandidate 範), `src/tsumugin/operando/__init__.py` (re-export 範),
  `docs/design/m3-operando/interfaces.py` L232-321

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m3-operando/interfaces.py`
  - L236-241: `FixedPhaseSpec(phase: PhaseInstance, label: str)` — 「構造固定・scale のみ解放・探索常駐。🔵 FR-312 (粒度は 🟡 Q5)」
  - L244: `CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]` — 「"Be" | "Al" | "graphite" 🔵 (格子値 🟡)」
  - L281 / L319: `fixed_phases: tuple[FixedPhaseSpec, ...] = ()` — discrimination / segmentation の受け口 (後続)
- **要件**: `docs/spec/m3-operando/requirements.md`
  - REQ-009 (L45-47): セル固定相テンプレート (Be 窓・Al 集電体・グラファイト等) をプリセット提供。固定相は
    **探索候補に常時含まれつつ構造パラメータは固定 (scale のみ解放)** で扱えること 🔵 *FR-312 (固定の粒度は 🟡)*。
- **設計判断**: `docs/design/m3-operando/design-interview.md`
  - 固定相の「構造固定・scale のみ解放」方針は D-Q4 (二相端成分格子固定・scale/wt_frac のみ解放, L23-26) と同思想。
    interfaces.py L238 が「粒度は 🟡 Q5」と注記 (固定の粒度は設計裁量、本タスクは scale のみ解放で確定)。
- **データフロー**: `docs/design/m3-operando/dataflow.md`
  - L18-19: `セル固定相プリセット (Be/Al/graphite) → SequentialEngine 逐次解析 (固定相=scale のみ解放)`。
- **アーキテクチャ**: `docs/design/m3-operando/architecture.md`
  - L38: `operando/cell_phases.py` = セル固定相プリセット (Be/Al/graphite) + `FixedPhaseSpec` (REQ-009 🔵、格子値 🟡)。
  - L114: `operando/` 新規ディレクトリ。L121: テストは `tests/test_cell_phases.py`。
- **受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` L29-33 (REQ-009 節)
  - TC-203-01 (L31): プリセット (Be/Al/graphite) が取得できる 🔵 (原文 "PhaseCandidate" → 本タスクは `FixedPhaseSpec` 正典)。
  - TC-203-02 (L32): 固定相は探索で常駐 (枝刈り対象外)・構造固定 (scale のみ解放) 🟡。
  - TC-203-03 (L33): 固定相込みの合成データで活物質相が正しく同定される 🔵。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` FR-312 (セル固定相テンプレート)、§4 (PhaseInstance データモデル)。
- **参照元**: 上記各ファイル, `docs/tasks/m3-operando/{TASK-0030.md,overview.md}`

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest tests/test_cell_phases.py` (本タスク単体) / `uv run pytest` (全体回帰) /
  `uv run pytest --cov=tsumugin`。**依存導入は `uv sync --extra gsas`** (プレーン `uv sync` は禁止)。
  本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- **本タスクのテストファイル**: `tests/test_cell_phases.py` (**新規**、architecture.md L121 命名に一致)。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py`。`tests/conftest.py` に共通フィクスチャ。
  参考: `tests/test_simulated_backend.py` (SimulatedBackend で scale/lattice を精密化する範 — TC-203-03 の合成検証に流用可)、
  `tests/test_echem.py` (operando 層の frozen/等価/決定論テスト範)。
- **合成検証の範 (`tests/test_simulated_backend.py` より)**:
  - `_phase(a, scale, ref)` で `PhaseInstance` を作り、`SimulatedBackend(peak_fwhm=0.2)` で `simulate` → `refine`。
  - `RefinementModel(phases=(...,), free_params=frozenset({param_name(0, "scale")}), two_theta=tt, intensity=y)` で
    scale のみ解放。`result.phases[i].scale == pytest.approx(truth, rel=0.01)` を検証 (TC-203-03 の直接範)。
  - `two_theta = np.arange(15.0, 80.0, 0.02)` グリッド。
- **命名/記述パターン** (既存 `tests/test_*.py` に準拠):
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - 格子値の文献一致は `== pytest.approx(2.2858)` 等。等価は `==`。
  - docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
- **本タスクで書くべき代表テスト観点** (TC-203-01〜03 に対応):
  - `CELL_PHASE_PRESETS` に "Be"/"Al"/"graphite" の 3 キーがあり各値が `FixedPhaseSpec` (TC-203-01)。
  - 各プリセット `phase.lattice` の a/b/c が docstring 記載の文献値 (直方近似後) と一致 (完了条件3)。
  - `fixed_free_suffixes(spec) == ("scale",)` — 構造 (lattice/occ) を解放しない (TC-203-02)。
  - 固定相 (真の scale) + 活物質相の合成データを固定相の scale のみ解放して refine → 活物質相 scale が真値へ収束
    し固定相 lattice が不変 (TC-203-03 / TC-203-02 の backend レベル担保)。
  - `FixedPhaseSpec` が frozen・等価比較可。`label` が必須 str。
  - 決定論: `CELL_PHASE_PRESETS` を 2 回参照して同一 (`is` or `==`)。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で既存テストを無改変で維持 (既存 passed/skipped 件数を維持)。
- **参照元**: `pyproject.toml`, `tests/test_simulated_backend.py`, `tests/test_echem.py`, `tests/conftest.py`,
  `docs/spec/m3-operando/acceptance-criteria.md` TC-203-01〜03, `docs/design/m3-operando/architecture.md` L121

---

## 6. 注意事項

### 技術的制約
- **直方近似の必然性 (核心)**: `SimulatedBackend._d_spacing` は 90° 直方系 `1/d² = h²/a² + k²/b² + l²/c²`。六方晶 (Be/graphite)
  を `a=b` のまま入れると b 方向反射が a と縮退し実回折と乖離する。**orthohexagonal 近似 `b = a·√3`** を採り、
  **docstring に「直方近似・文献値出典・実回折とのずれ」を明記**する (完了条件・タスク指示の要)。
- **格子値の信頼性は 🟡**: 文献値そのもの (Be a=2.2858/c=3.5843、Al a=4.0495、graphite a=2.464/c=6.711) は 🟡。
  実装は docstring 記載値と**ビット一致**させ、テストで文献値と照合する (完了条件3)。
- **scale のみ解放は本タスクの契約点**: `fixed_free_suffixes` は常に `("scale",)`。将来 wt_frac 等を足す拡張余地はあるが
  本タスクでは**構造固定 (lattice/occupancy 非解放)** を厳守 (REQ-009 字義・interfaces.py L238)。
- **決定論 (NFR-102)**: プリセットはモジュールロード時定数。乱数・時刻・環境変数に依存しない。
- **コア依存 numpy のみ** (REQ-403): pymatgen/ASE 等の結晶構造ライブラリを**導入しない**。格子はハードコード定数。
- **既存 API 非破壊**: `PhaseInstance`/`LatticeParams`/`param_name` を利用のみ。model・backends は変更しない。

### 契約の不一致 (要確認・本タスクでの解決)
- **AC 原文 vs interfaces.py**: `acceptance-criteria.md` TC-203-01 は「**PhaseCandidate** として取得できる」と記すが、
  確定契約 `interfaces.py` L236-244 は「**FixedPhaseSpec**」。TASK-0030.md 完了条件も「FixedPhaseSpec として取得できる」。
  → **本タスクは interfaces.py / TASK-0030.md の `FixedPhaseSpec` を正典**とする (AC の "PhaseCandidate" は策定初期の
  呼称と判断)。両者の差: `PhaseCandidate` は `phase`/`delta_u`/`label?`、`FixedPhaseSpec` は `phase`/`label` (delta_u なし・
  label 必須)。固定相は探索メタ (ΔU) を持たず、探索常駐の意味論を `FixedPhaseSpec` として明示分離する設計意図に合致。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **プリセット定義 + `FixedPhaseSpec` + `fixed_free_suffixes` のみ**。以下は**後続スコープ**:
  - 固定相を探索/逐次解析へ実際に注入する処理 (`discriminate_interval` / `segment_series` = TASK-0032/0033)。
  - 固定相の探索常駐 (枝刈り対象外) を SearchEngine 側で保証する統合 (本タスクはヘルパと器のみ)。
  - CellConfig (窓/集電体の層構成) との自動連携・μt 計算 (absorption / TASK-0025/0026 側)。
- プリセットは **Be/Al/graphite の 3 種のみ**。他材料の追加・ユーザ定義固定相の登録 API は実装しない (器のみ提供)。
- 格子は **直方近似 (角 90°) のみ**。一般三斜・実 hkl 展開・構造因子計算はしない (SimulatedBackend の近似に合わせる)。

### 後続タスクへの影響
- **後続 TASK-0032/0033** が `FixedPhaseSpec` (フィールド `phase`/`label`) と `fixed_free_suffixes -> ("scale",)`、
  `CELL_PHASE_PRESETS` キー ("Be"/"Al"/"graphite") に依存。interfaces.py L236-244 の契約どおりに固定すること。
- `operando/__init__.py` の re-export に新シンボルを追加し、後続モジュールが `from tsumugin.operando import FixedPhaseSpec`
  等で取り込めるようにする (TASK-0029 の echem シンボルと整合)。

- **参照元**: `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/spec/m3-operando/{requirements,acceptance-criteria}.md`,
  `docs/design/m3-operando/{interfaces.py,architecture.md,dataflow.md,design-interview.md}`,
  `CLAUDE.md` (不変条件), `src/tsumugin/backends/simulated.py` (直方近似の根拠)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m3-operando/{TASK-0030.md,overview.md}`
- 仕様/要件: `docs/spec/m3-operando/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m3-operando/{interfaces.py,architecture.md,dataflow.md,design-interview.md}`
- 既存実装 (利用/参考): `src/tsumugin/model/phase.py` (PhaseInstance/LatticeParams),
  `src/tsumugin/backends/base.py` (param_name/parse_param/RefinementModel),
  `src/tsumugin/backends/simulated.py` (直方近似 _d_spacing / scale 精密化の範),
  `src/tsumugin/search/clustering.py` (PhaseCandidate = 固定相値オブジェクトの範),
  `src/tsumugin/operando/__init__.py` (re-export の範 / TASK-0029)
- テスト参考: `tests/test_simulated_backend.py`, `tests/test_echem.py`, `tests/conftest.py`, `pyproject.toml`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
