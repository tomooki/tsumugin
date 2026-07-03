# TASK-0027 TDD要件定義書 — multistart/perturb (決定論摂動列)

**機能名**: multistart-perturb (決定論的初期値摂動列生成)
**タスクID**: TASK-0027 / **要件名**: m3-operando / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 2 / **信頼性サマリー**: 🔵 FR-231 / 設計 D1 / REQ-001 / AC TC-201-01・07
**作成日**: 2026-07-04

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。
> **【信頼性凡例】** 🔵 EARS要件・設計文書に依拠しほぼ推測なし / 🟡 妥当な推測 (根拠記載) / 🔴 根拠なし推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: マルチスタート大域最適確認 (FR-230) の**初期値摂動列生成器**を提供する。
  候補仮説の相群 `phases` に対し、初期値を系統的に摂動した **N 組の摂動 phases 列**を、
  **乱数を一切使わない start index ベースの決定論列**として生成する (`generate_starts`)。
  摂動対象は **格子定数 (±設定幅の等間隔グリッド)・scale (対数一様グリッド)・占有率 (固定 LHS 表)** の 3 種。
  設定は `PerturbationSpec` (摂動幅) と `MultistartConfig` (本数・幅・basin/refine 既定) の 2 つの frozen dataclass。
- 🔵 **どのような問題を解決するか**: 単一初期値からの Rietveld 精密化は**局所最適に捕捉される**。
  系統摂動した複数初期値から独立に精密化すれば、多峰性 (固溶体 vs 二相の競合等) を検出でき、
  大域最適の傍証を得られる (FR-232)。本タスクはその**入口となる初期値列**を、再現性 (NFR-102) を
  完全に保証する形 (乱数不使用・index の純関数) で生成する。
- 🔵 **想定されるユーザー**: マルチスタート精密化を実行する後続コンポーネント
  (TASK-0028 `MultistartEngine.run` / `multistart/basin.py`) と、FR-313 判別で必須適用する
  TASK-0032。直接のエンドユーザーは自動エージェント/研究者だが、本関数は内部 API。
- 🔵 **システム内での位置づけ**: 新設 `multistart` 層 (FR-230〜234) の**純関数コア**。
  model 層 `PhaseInstance`/`LatticeParams` (TASK-0025 までに実装済) を入力に取り、摂動済み `phases` 列を
  返すだけの副作用なし関数。basin クラスタ (TASK-0028) がこの列を各 start として `backend.refine` に供給する。
- **参照したEARS要件**: REQ-001, REQ-402, REQ-403, REQ-404, EDGE-101
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D1 (L58-60) / モジュール表 L34,
  `docs/design/m3-operando/interfaces.py` L124-169

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 `PerturbationSpec` (frozen dataclass) — `multistart/perturb.py`

- 🔵 **摂動幅の設定値のみを保持**する不変値オブジェクト:
  | フィールド | 型 | 既定 | 意味 |
  |---|---|---|---|
  | `lattice_frac` | `float` | `0.02` | 格子定数の相対摂動幅 (±2%)。a/b/c に相対スケール適用 |
  | `scale_log_range` | `float` | `0.5` | scale の log10 空間での片側幅 (10^±0.5 = ×0.316〜×3.16) |
  | `occupancy_delta` | `float` | `0.1` | 占有率 LHS の摂動幅 (加算オフセットの絶対幅) |
- 🟡 既定値 (0.02 / 0.5 / 0.1) は interfaces.py L131-133 の注記どおり (幅の具体値は 🟡 チューニング既定)。
- **参照**: interfaces.py L126-133 / architecture.md D1 / REQ-001

### 2.2 `MultistartConfig` (frozen dataclass) — `multistart/perturb.py`

- 🔵 マルチスタート全体設定。本タスクで `generate_starts` が使うのは主に `n_starts` と `spec`:
  | フィールド | 型 | 既定 | 意味 | 本タスクでの用途 |
  |---|---|---|---|---|
  | `n_starts` | `int` | `8` | マルチスタート本数 (FR-231: 8-16) | 生成する start 組数 N |
  | `spec` | `PerturbationSpec` | `PerturbationSpec()` | 摂動幅 | 摂動値の算出に使用 |
  | `basin_rel_tol` | `float` | `1e-2` | basin クラスタの正規化距離閾値 (D3) | **器のみ** (TASK-0028 で消費) |
  | `ms_max_cycles` | `int` | `15` | 各 start の refine 上限 (D2) | **器のみ** (TASK-0028 で消費) |
- 🔵 `n_starts=8` は FR-231 に依拠。`basin_rel_tol`/`ms_max_cycles` は 🟡 (D2/D3 チューニング既定) だが
  本タスクは**正しい既定値で保持するのみ**で挙動には関与しない。
- **参照**: interfaces.py L135-141 / architecture.md D1〜D3 / FR-231

### 2.3 `generate_starts` — `multistart/perturb.py`

- 🔵 **シグネチャ** (interfaces.py L165-169 準拠、そのまま実装):
  ```python
  def generate_starts(
      phases: tuple[PhaseInstance, ...], *, config: MultistartConfig
  ) -> tuple[tuple[PhaseInstance, ...], ...]:
  ```
  - **入力**: `phases` = 基準となる相群 (1 相以上)、`config` = マルチスタート設定 (keyword-only)。
  - **出力**: 長さ `config.n_starts` の tuple。各要素は摂動済み `phases` (元と同じ相数・相順)。
    `result[i]` が start index `i` の初期値、`result[i][j]` が相 j の摂動済み `PhaseInstance`。
- 🔵 **start index → 摂動の対応 (D1)**:
  - **i=0 は無摂動**: `result[0]` は入力 `phases` と同値 (格子/scale/占有率とも基準)。
  - **i≥1 は index から一意に決まる決定論値**:
    - **格子 (等間隔グリッド)**: 各相の `a/b/c` に相対摂動 `a * (1 + δ_i)`、
      `δ_i ∈ [-lattice_frac, +lattice_frac]` の等間隔グリッド上の点。角度は非摂動。
    - **scale (対数一様グリッド)**: `scale * 10^(o_i)`、`o_i ∈ [-scale_log_range, +scale_log_range]` の
      log10 空間等間隔グリッド上の点。
    - **占有率 (固定 LHS 表)**: 各 site の占有率に `occupancy_delta` 幅の**固定ラテン超方格テーブル**由来の
      オフセットを加算し **[0,1] にクリップ**。表は乱数でなく index で一意に引く決定論版。
- 🔵 **N=1 縮退** (EDGE-101 / TC-201-07): `config.n_starts == 1` のとき `result` は基準 1 組のみ
  (`len == 1`、摂動なし)。分母 `N-1 == 0` の 0 除算を回避すること。
- 🟡 **多相の摂動一意性**: 相 index `j` を摂動式に織り込み、相ごとに異なるが決定論的な摂動を与える
  (LHS の意図は相ごと独立摂動)。全相同一摂動でも決定論は満たすが、D1 の LHS 的分散を優先。
  相ごとオフセットの具体式は設計裁量 🟡、tdd-testcases で確定。
- **出力例** (概念): `phases=(A,)`, `config=MultistartConfig(n_starts=3)` →
  `((A_base,), (A_pert1,), (A_pert2,))`。`A_base == A`、`A_pert1.lattice.a ≈ A.lattice.a*(1±δ)` 等。
- **参照**: interfaces.py L165-169 / architecture.md D1 (L58-60) / `src/tsumugin/model/phase.py` L48-62

### 2.4 データフロー

- 🔵 `phases` (基準相群) + `MultistartConfig(n_starts, spec)` → `generate_starts` →
  N 組の摂動 phases 列 → (後続 TASK-0028) 各 start を `backend.refine` へ → basin クラスタ →
  `MultistartResult`。本タスクは **`generate_starts` の出力まで**で閉じる。
- **参照**: architecture.md D1〜D3 / `docs/design/m3-operando/dataflow.md`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論・乱数不使用 (NFR-102 / REQ-402 / TC-201-01)**: `random`/`np.random` を **import しない**。
  摂動値は start index `i`・相 index `j`・パラメータ種別のみから純関数導出。
  **同一 `(phases, config)` で 2 回 `generate_starts` を呼ぶとビット同一** (格子・scale・占有率すべて `==`)。
  これは「乱数種固定でビット同一」(REQ-001) を、そもそも乱数を使わない index 列で達成する。
- 🔵 **摂動範囲が spec どおり (TC-201-01)**:
  - 格子: 各相の a/b/c は基準の `[1-lattice_frac, 1+lattice_frac]` 倍の範囲内。
  - scale: `log10(scale_pert / scale_base) ∈ [-scale_log_range, +scale_log_range]` (対数域内)。
  - 占有率: 各 site 値が `[0.0, 1.0]` 内 (**クリップ必須**)、摂動幅は `occupancy_delta` に収まる。
- 🔵 **i=0 無摂動・N=1 縮退 (TC-201-07 / EDGE-101)**: `result[0]` は基準と同値。`n_starts=1` で基準 1 組のみ。
- 🔵 **非破壊性 (P2 / REQ-404 / NFR-101)**: 入力 `phases` / `LatticeParams` / `occupancies` を変更しない。
  `PhaseInstance.with_updates()` / frozen 再構築 / 新 dict による**非破壊生成**のみ。
  返り値は入力から独立した新インスタンス群。既存 API・データモデルは無改変 (フィールド追加なし、純新規モジュール)。
- 🔵 **無退行 (完了ゲート)**: `uv run pytest` 全体で**ベースライン 505 collected を無退行維持**
  (502 passed + @gsas 3 skip、2026-07-04 計測)。既存テストファイルは 1 行も改変しない。
  新規 `tests/test_multistart_perturb.py` 分だけ collected 数が増える。
- 🔵 **コア依存 numpy のみ (REQ-403)**: 追加依存禁止。対数/等間隔グリッドは `numpy` (`np.linspace`/
  `np.logspace`) または標準 `math` で算出。xraylib 等の外部依存を持ち込まない。
- 🔵 **型注釈必須・Lint clean**: `uvx ruff check src tests` clean (line-length 100, py312)。
  `tuple[PhaseInstance, ...]` / `tuple[tuple[PhaseInstance, ...], ...]` / `float` / `int` /
  `PerturbationSpec` / `MultistartConfig`。新規ファイル冒頭に `from __future__ import annotations`。
- 🔵 **キーワード専用引数**: `generate_starts(phases, *, config)` — `config` は keyword-only (interfaces.py L165-167)。
- **参照**: `CLAUDE.md` (不変条件/コーディング規約), REQ-402/403/404, NFR-102, EDGE-101, architecture.md D1

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン

- 🔵 **単相・既定 N=8 の摂動列** (TC-201-01): `generate_starts((phase,), config=MultistartConfig())` →
  8 組。`[0]` は基準、`[1..7]` は格子±2%グリッド・scale 対数域・占有率 LHS の決定論摂動。2 回呼びビット同一。
- 🔵 **決定論の確認** (TC-201-01 / REQ-402): 同一入力で 2 回生成 → 全 start の格子/scale/占有率が `==`。
- 🔵 **多相 phases** (完了条件 4): `phases=(A, B)` で各 start の A/B 両相に摂動が適用される
  (i=0 で両相基準、i≥1 で両相摂動)。相数・相順は保存。
- 🔵 **範囲検証** (TC-201-01): 各摂動値が spec の範囲内 (格子 ±frac、scale 対数域、占有率 [0,1] クリップ)。

### 4.2 エッジ・エラーケース

- 🔵 **EDGE-101 / TC-201-07 (N=1 縮退)**: `MultistartConfig(n_starts=1)` → `len(result)==1`、
  `result[0]` は基準のみ (摂動なし、basin=1 相当)。0 除算を起こさない。
- 🔵 **i=0 の恒等性** (TC-201-07): 任意の N ≥ 1 で `result[0]` は入力 `phases` と同値。
- 🟡 **占有率の [0,1] 境界** (TC-201-01 派生): 基準占有率が 0 or 1 近傍のとき、LHS オフセット加算で
  範囲外に出る値は **[0,1] にクリップ**される (負や 1 超を返さない)。
- 🟡 **占有率が空 (`occupancies == {}`) の相**: 占有率摂動はスキップ (空のまま)、格子/scale のみ摂動。
  クラッシュしない。
- 🟡 **格子の縮退相** (立方晶で a=b=c 等): a/b/c 各々に摂動を掛けると対称性が崩れるが、本タスクは
  対称拘束を持たない汎用摂動 (対称拘束は精密化側の責務)。摂動自体は決定論的に適用。
- **参照**: acceptance-criteria.md TC-201-01 / TC-201-07 / requirements.md EDGE-101 / REQ-402

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m3-operando/user-stories.md` — マルチスタートで判別信頼性を
  担保するストーリー (FR-230 系: 局所最適を避け大域最適の傍証を得る)。
- **参照した機能要件**:
  - REQ-001 (L24-26): 初期値を系統摂動した N 本 (既定 8、8-16) の独立精密化。摂動は格子 ±設定幅・
    scale 対数一様・占有率ラテン超方格、**決定論的な固定列** (乱数種固定) 🔵 FR-231/NFR-102。
    → 本タスクは「摂動列生成」部分を担当 (独立精密化・basin は TASK-0028)。
  - REQ-402 (L106-107): マルチスタート等の全出力は同一入力でビット同一 (摂動列は決定論生成) 🔵。
  - REQ-403 (L108-109): コア依存 numpy のみ 🔵。
  - REQ-404 (L110-111): データモデル拡張は後方互換の非破壊追加 (本タスクは純新規モジュールで既存無改変) 🔵。
- **参照した非機能要件**: NFR-102 (決定論/ビット同一), NFR-201 (決定論・追記専用)。
- **参照したEdgeケース**: EDGE-101 (N=1 → 摂動なし 1 本、basin=1)。
  (EDGE-001 単一 basin 傍証は basin 判定側 = TASK-0028 の観点。)
- **参照した条件付き要件**: なし (REQ-102 発散除外は TASK-0028 の basin/engine 側)。
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md`
  - **TC-201-01** (L14): N=8 摂動列が決定論 (2 回生成でビット同一)、格子±幅/scale 対数一様/占有率 LHS の
    範囲内 🔵 (本タスク主対象)。
  - **TC-201-07** (L20): N=1 縮退 (摂動なし 1 本) 🟡 EDGE-101 (本タスク主対象)。
  - (TC-201-02〜06: 全 start 同一解収束 / 双峰 basin / 別仮説昇格 / 発散除外 / metrics 記録 は
    basin クラスタ・engine・metrics の観点で **TASK-0028 が主対象**。本タスクは摂動列生成に閉じ、
    これらの前提となる決定論初期値を供給する。)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md`
    - **D1 (L58-60)**: マルチスタート摂動は決定論列。乱数不使用。格子 ±frac 等間隔グリッド・
      scale 対数一様グリッド・占有率固定 LHS テーブルで start index から一意に決まる。i=0 無摂動 (NFR-102)。
    - モジュール表 L34 (`multistart/perturb.py`)、ディレクトリ構造 L108-123、決定論の実現 L129 (index 安定ソート)。
  - **型定義**: `docs/design/m3-operando/interfaces.py` L124-169
    (PerturbationSpec / MultistartConfig / generate_starts)。
  - **データフロー**: `docs/design/m3-operando/dataflow.md`。
  - **既存実装 (依存)**: `src/tsumugin/model/phase.py` (PhaseInstance/LatticeParams/with_updates)、
    `src/tsumugin/model/__init__.py` (re-export)。
  - **タスクノート**: `docs/implements/m3-operando/TASK-0027/note.md`。

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (摂動 3 種の対象・範囲・i=0 無摂動・N=1 縮退・決定論・非破壊が具体)
- 入出力定義: 完全 (PerturbationSpec / MultistartConfig の型・既定、generate_starts の
  シグネチャ・戻り値構造・start index → 摂動対応を明示)
- 制約条件: 明確 (乱数不使用・ビット同一・範囲/クリップ・非破壊・無退行 505・numpy のみ)
- 実装可能性: 確実 (frozen dataclass + index の純関数グリッド + with_updates 非破壊生成)
- 信頼性レベル: 🔵 が主 (骨格は FR-231/D1/interfaces.py/TC-201-01・07 に直依拠。
  🟡 は摂動幅の具体既定値・相ごとオフセット式・占有率境界の詳細に限定)
```

**信頼性分布**: 🔵 多数 (機能骨格・I/O・制約・受け入れ基準 TC-201-01/07) /
🟡 少数 (lattice_frac=0.02 等の幅既定値・相ごと摂動オフセット式・占有率クリップ境界・空 occupancies 挙動) /
🔴 なし。

**次のお勧めステップ**: `/tsumiki:tdd-testcases m3-operando TASK-0027` でテストケースの洗い出しを行います。
