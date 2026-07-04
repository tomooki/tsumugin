# TASK-0030 TDD要件定義: operando/cell_phases — セル固定相プリセット (FR-312)

**機能名**: cell-phase-presets / **タスクID**: TASK-0030 / **要件名**: m3-operando
**タイプ**: TDD / **フェーズ**: Phase 3 (operando 電池モード) / **信頼性**: 🔵 1 / 🟡 2
**出力ファイル**: `docs/implements/m3-operando/TASK-0030/cell-phase-presets-requirements.md`
**作成日時**: 2026-07-04

> 本書のすべてのパスはプロジェクトルートからの相対パス。信頼性レベル: 🔵 要件・仕様・設計に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: operando 電池セルを構成する不活性材料 (Be 窓・Al 集電体・グラファイト等) を、**構造固定・scale のみ
  解放で探索に常駐する「固定相」**として供給するプリセット層。固定相の指定を表す値オブジェクト `FixedPhaseSpec`、
  文献格子定数の直方近似を格納した 3 プリセット `CELL_PHASE_PRESETS` (Be/Al/graphite)、および固定相の解放パラメータ
  suffix を返すヘルパ `fixed_free_suffixes` を提供する。
- 🔵 **解決する問題**: operando 計測では活物質の回折ピークにセル材料の固定ピークが常に重畳する。これらを毎回ユーザに
  定義させると手間かつ誤差源となる。既知材料をプリセット化し、構造 (格子・占有率) を固定して scale のみ解放することで、
  活物質相の精密化を安定化しつつ枝刈りで固定相が失われないようにする (探索常駐)。
- 🔵 **想定ユーザー**: operando 電池計測を Rietveld 解析する研究者、および固定相を取り込む区間判別 (`discrimination.py` /
  TASK-0032) や区間分割 (`segmentation.py` / TASK-0033) の上位パイプライン。
- 🔵 **システム内での位置づけ**: `src/tsumugin/operando/cell_phases.py` (新規モジュール)。データフロー
  `セル固定相プリセット (Be/Al/graphite) → SequentialEngine 逐次解析 (固定相=scale のみ解放)` の供給源 (dataflow.md L18-19)。
  コア依存は numpy のみ維持し、本機能自体は stdlib (`dataclasses`/`typing`/`math`) で完結する。
- **参照したEARS要件**: REQ-009 (セル固定相テンプレート / 構造固定・scale のみ解放・探索常駐) 🔵
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` L38 (cell_phases 役割), `docs/design/m3-operando/dataflow.md` L18-19

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

契約は `docs/design/m3-operando/interfaces.py` L232-244。

### 2.1 `FixedPhaseSpec` (frozen dataclass) — 🔵

- フィールド:
  - `phase: PhaseInstance` — 固定相の相インスタンス (格子・scale を保持) 🔵
  - `label: str` — 固定相ラベル (必須。`None` 不可。例 `"Be window"` / `"Al collector"` / `"graphite"`) 🔵
- 意味論: 「構造固定・scale のみ解放・探索常駐」を表す値オブジェクト 🔵 (interfaces.py L238)。
- 🔵 frozen・等価比較 (`==`)・生成が可能。`phase` (frozen)・`label` (str) いずれもハッシュ可のためハッシュ可。
- 🟡 `PhaseCandidate` (`src/tsumugin/search/clustering.py`) との差: `FixedPhaseSpec` は探索メタ `delta_u` を持たず、
  `label` が必須。固定相は探索由来の hull エネルギーを持たないため意味論的に分離される。

### 2.2 `CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]` — 🔵 (格子値 🟡)

- キー: `"Be"` / `"Al"` / `"graphite"` の 3 種 (interfaces.py L244) 🔵。
- 各値: 文献格子定数の**直方 (orthorhombic) 近似**を `LatticeParams` に格納した `PhaseInstance` を包む `FixedPhaseSpec` 🟡。
- 直方近似の理由: `SimulatedBackend._d_spacing` (`src/tsumugin/backends/simulated.py` L67-75) が 90° 直方系
  `1/d² = h²/a² + k²/b² + l²/c²` を用いるため。六方晶を `a=b` で入れると b 方向反射が縮退する 🔵。
- **格子定数 (文献値 → 直方近似)** — docstring に出典・近似方針・実回折とのずれを必ず明記 🟡:
  - **Be (hcp)**: 文献 a=2.2858 Å, c=3.5843 Å → orthohexagonal `a'=2.2858, b'=a·√3≈3.9591, c'=3.5843` 🟡
  - **Al (fcc)**: 文献 a=4.0495 Å → 立方晶 `a=b=c=4.0495` (歪みなし) 🟡
  - **graphite (hexagonal)**: 文献 a=2.464 Å, c=6.711 Å → orthohexagonal `a'=2.464, b'=a·√3≈4.2678, c'=6.711` 🟡
- 🔵 決定論: モジュールロード時に確定する不変定数。同一入力 → ビット同一。
- 🟡 読み取り専用 `Mapping` として公開 (`types.MappingProxyType` か frozen 値のみ格納する dict。実務上不変)。

### 2.3 `fixed_free_suffixes(spec: FixedPhaseSpec) -> tuple[str, ...]` — 🟡

- **入力**: `spec: FixedPhaseSpec` 🔵
- **出力**: 固定相の解放パラメータ suffix。常に `("scale",)` を返す (構造固定 = lattice/occupancy を解放しない) 🟡
  (REQ-009「scale のみ解放」字義・interfaces.py L238)。
- 用途: 呼び側 (TASK-0032/0033) が `param_name(i, "scale")` (`src/tsumugin/backends/base.py` L56-58) で
  `RefinementModel.free_params` を構成する際の単一の真実源。suffix→正準名の組み立ては呼び側の責務。
- 🟡 引数 `spec` は将来の粒度拡張余地のため受けるが、本タスクでは spec 非依存に常に `("scale",)`。

### 2.4 入出力の関係性・データフロー — 🔵

- `CELL_PHASE_PRESETS[key]` → `FixedPhaseSpec` → (呼び側) `spec.phase` を `phases` へ加え、
  `fixed_free_suffixes(spec)` を `param_name(i, suffix)` で `free_params` に展開 → `SimulatedBackend.refine` で
  固定相の scale のみ最適化 (lattice 不変)。
- **参照したEARS要件**: REQ-009 (固定相は探索候補に常駐しつつ構造固定・scale のみ解放) 🔵
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L232-244, `docs/design/m3-operando/dataflow.md` L18-19

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **依存制約 (REQ-403)**: pymatgen/ASE 等の結晶構造ライブラリを**導入しない**。格子値はハードコード定数。
  コア依存は numpy のみ維持し、本機能実装本体は stdlib (`dataclasses`/`typing`/`math`) のみで完結する。
- 🔵 **決定論 (NFR-102 / REQ-402)**: プリセットはモジュールロード時に確定する不変定数。乱数・時刻・環境変数に依存しない。
  同一実行 → ビット同一のプリセットオブジェクト。
- 🔵 **後方互換 / 非破壊 (REQ-404)**: `PhaseInstance` / `LatticeParams` (model)、`param_name` (backends.base) を
  **利用のみ**。model・backends を変更しない。既存全テストを無改変で維持。
- 🔵 **アーキテクチャ制約**: 新規 `src/tsumugin/operando/cell_phases.py` (operando/ は TASK-0029 で新設済)。
  frozen dataclass の値オブジェクト + モジュール定数テーブル + 純粋関数ヘルパ。`operando/__init__.py` に re-export 追加。
- 🟡 **格子近似の制約 (完了条件・タスク指示の核心)**: 六方晶 (Be/graphite) は orthohexagonal 直方近似 (`b = a·√3`) を採り、
  **docstring に「直方近似・文献値出典・実回折とのずれ」を必ず明記**する。SimulatedBackend の直方 `_d_spacing` に合わせる。
- 🔵 **型注釈必須**: `Mapping[str, FixedPhaseSpec]` / `tuple[str, ...]`。`any` 回避。`from __future__ import annotations`
  を冒頭に置く。line-length 100・ruff clean。
- **参照したEARS要件**: REQ-009, REQ-402 (決定論), REQ-403 (コア依存 numpy), REQ-404 (非破壊), NFR-102 🔵
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` L38/L114/L121, `src/tsumugin/backends/simulated.py` L67-75,
  `CLAUDE.md` (不変条件・規約)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本使用パターン — 🔵

- **プリセット取得 (TC-203-01)**: `CELL_PHASE_PRESETS["Be"]` / `["Al"]` / `["graphite"]` が各々 `FixedPhaseSpec` を返し、
  `spec.phase` が `PhaseInstance`、`spec.label` が非空 str。
- **格子値検証 (完了条件3)**: 各プリセット `spec.phase.lattice.a/b/c` が docstring 記載の文献値 (直方近似後) と一致
  (`== pytest.approx(...)`)。
- **scale のみ解放 (TC-203-02)**: `fixed_free_suffixes(spec) == ("scale",)`。lattice/occupancy suffix を含まない。

### 4.2 データフロー — 🔵

- `セル固定相プリセット (Be/Al/graphite)` → `SequentialEngine 逐次解析 (固定相=scale のみ解放)` (dataflow.md L18-19)。
- 固定相の `phase` を `phases` タプルへ加え、`fixed_free_suffixes` の suffix を `param_name(i, suffix)` で
  `free_params` に展開 → 固定相の scale だけが最適化される。

### 4.3 エッジ・境界ケース — 🟡

- **合成データでの固定相込み精密化 (TC-203-03)**: 固定相 (真の scale) + 活物質相の合成データを、固定相の scale のみ解放
  (`param_name(fixed_idx, "scale")`) して `SimulatedBackend.refine` → 活物質相 scale が真値へ収束し、
  **固定相の lattice が精密化前後で不変** (構造固定の backend レベル担保)。
- **frozen 不変性**: `FixedPhaseSpec` のフィールド代入は `FrozenInstanceError`。
- **プリセット不変**: `CELL_PHASE_PRESETS` を 2 回参照して同一 (決定論)。読み取り専用として扱う。

### 4.4 スコープ外 (やり過ぎ防止) — 🟡

- 固定相を探索/逐次解析へ**実際に注入する処理** (`discriminate_interval` / `segment_series`) は後続 TASK-0032/0033。
- 探索常駐 (枝刈り対象外) を SearchEngine 側で保証する統合は本タスク外 (本タスクはヘルパと器のみ)。
- プリセットは Be/Al/graphite の 3 種のみ。ユーザ定義固定相の登録 API・他材料追加は実装しない。
- 一般三斜格子・実 hkl 展開・構造因子計算はしない (直方近似のみ)。
- **参照したEARS要件**: REQ-009 (探索常駐・構造固定・scale のみ解放) 🔵
- **参照した設計文書**: `docs/design/m3-operando/dataflow.md` L18-19, `docs/design/m3-operando/design-interview.md` D-Q4 (固定相方針の同思想)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m3-operando/user-stories.md` — operando 電池計測のセル材料固定相供給
- **参照した機能要件**: REQ-009 (セル固定相テンプレート / Be 窓・Al 集電体・グラファイト等をプリセット提供、
  固定相は探索候補に常時含まれつつ構造パラメータ固定・scale のみ解放) 🔵 *FR-312*
- **参照した非機能要件**: NFR-102 (再現性/決定論), REQ-402 (決定論), REQ-403 (コア依存 numpy), REQ-404 (非破壊拡張)
- **参照した Edge ケース**: 明示的な EDGE 番号は本要件に紐づかず (プリセットは器のため異常系が薄い)。境界は
  frozen 不変性・プリセット不変性・格子近似のずれに限定。
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` L29-33 (REQ-009 節)
  - TC-203-01 (プリセット Be/Al/graphite が取得できる) 🔵 — ※原文 "PhaseCandidate" だが本タスクは `FixedPhaseSpec` 正典 (下記)
  - TC-203-02 (固定相は探索常駐・構造固定・scale のみ解放) 🟡
  - TC-203-03 (固定相込みの合成データで活物質相が正しく同定される) 🔵
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` L38 (cell_phases.py 役割 / 格子値 🟡), L114 (operando/ 新規), L121 (test_cell_phases.py)
  - **データフロー**: `docs/design/m3-operando/dataflow.md` L18-19 (固定相=scale のみ解放)
  - **型定義**: `docs/design/m3-operando/interfaces.py` L236-241 (FixedPhaseSpec), L244 (CELL_PHASE_PRESETS)
  - **設計判断**: `docs/design/m3-operando/design-interview.md` D-Q4 (端成分格子固定・scale/wt_frac のみ解放 — 固定相方針の同思想), interfaces.py L238 (粒度は 🟡 Q5)
  - **データベース**: 該当なし (定数定義のみ・DB 非使用)
  - **API仕様**: 該当なし (ライブラリ内部 API / HTTP エンドポイント非使用)

### 契約の不一致 (本タスクでの解決)

- `acceptance-criteria.md` TC-203-01 は「**PhaseCandidate** として取得」と記すが、確定契約 `interfaces.py` L236-244 および
  `TASK-0030.md` 完了条件は「**FixedPhaseSpec**」。本タスクは **interfaces.py / TASK-0030.md の `FixedPhaseSpec` を正典**とする
  (AC の "PhaseCandidate" は策定初期の呼称と判断)。テストは `FixedPhaseSpec` で記述する。

---

## 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (型契約は interfaces.py L232-244 で確定、固定相方針は REQ-009 / D-Q4 で確定)
- 入出力定義: 完全 (FixedPhaseSpec/CELL_PHASE_PRESETS/fixed_free_suffixes の型・キー・戻り値・格子値を明記)
- 制約条件: 明確 (直方近似・docstring 注意明記・決定論・非破壊・コア依存 numpy)
- 実装可能性: 確実 (PhaseInstance/LatticeParams/param_name/SimulatedBackend は整備済、依存は stdlib のみ)
- 信頼性レベル: 🔵 1 / 🟡 2 — 🟡 は格子定数値 (文献値) と固定粒度 (scale のみ) の設計裁量に集中し要件へ遡及可能
```

**次のお勧めステップ**: `/tsumiki:tdd-testcases m3-operando TASK-0030` でテストケースの洗い出しを行います。
