# TASK-0026 TDD要件定義書 — backends 拡張 (global パラメータ文法 + 吸収補正 v1)

**機能名**: backends-absorption (global パラメータ文法 + 実効 μt 吸収補正 v1)
**タスクID**: TASK-0026 / **要件名**: m3-operando / **タイプ**: TDD / **推定 5h**
**フェーズ**: Phase 2 / **信頼性サマリー**: 🔵 FR-317 / 設計 D8 / REQ-017〜020/103
**作成日**: 2026-07-04

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。
> **【信頼性凡例】** 🔵 EARS要件・設計文書に依拠しほぼ推測なし / 🟡 妥当な推測 (根拠記載) / 🔴 根拠なし推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 粉末回折の**透過平板配置における実効 μt (吸収の厚み積) を 1 パラメータとして
  精密化する吸収補正 v1** を提供する。前方モデルに透過吸収因子 A(θ; μt) = exp(−μt/cosθ) を乗算し、
  CellConfig 由来の計算 μt (提供時) を **restraint (許容幅付き soft bound)** として作用させる。あわせて、
  相に属さない大域パラメータを扱うための**パラメータ文法拡張** `"global.mu_t"` と、結果に大域値・警告を
  載せる `RefinementResult.globals` / `.warnings` を非破壊で追加する。
- 🔵 **どのような問題を解決するか**: operando 電池セル等の**厚い透過セルでは低角ほど吸収が強く、強度比が
  歪む**。μt を明示的にフィット + restraint することで、格子・分率・scale との相関による誤収束
  (§14 相関リスク) を抑えつつ強度歪みを補正し、FR-313 判別 / 区間分割の信頼性を担保する。
- 🔵 **想定されるユーザー**: operando 解析を回す研究者/自動エージェント (SimulatedBackend 経由で検証)、
  および本補正を利用する後続機能 (TASK-0028 判別・区間精密化、TASK-0032 M3 E2E)。
- 🔵 **システム内での位置づけ**: `backends` 層 (P7 RefinementBackend 境界) の前方モデル・精密化拡張と、
  新設 `absorption` 層 (吸収の設定 dataclass + 透過因子関数) から成る。model 層 `CellConfig` (TASK-0025)
  を入力に取り、後続 operando 機能へ吸収補正済み精密化を供給する。
- **参照したEARS要件**: REQ-016〜020, REQ-103, REQ-403, REQ-404, EDGE-006
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D8 (L93-101),
  `docs/design/m3-operando/interfaces.py` L88-118

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 パラメータ文法拡張 — `backends/base.py`

- 🔵 **`parse_param(name: str) -> tuple[int, str]`**:
  - 入力: 正準パラメータ名 `str`。
  - 追加仕様: `head == "global"` かつ `tail` が非空のとき **`(-1, tail)`** を返す
    (例: `"global.mu_t" -> (-1, "mu_t")`)。相インデックス `-1` は「大域 (どの相にも属さない)」の標識。
  - 既存仕様 (**不変**): `"phase{i}.{suffix}" -> (i, suffix)` (suffix はドットを含みうる)。
    `"phase"` で始まらず `"global"` でもない、または tail 空は従来どおり `ValueError`。
  - 🟡 **`param_name`** は本タスクでは phase 用のまま (global 名の生成関数が要れば別途 `global_param_name`
    等を足すが、必須ではない。テストは文字列直値 `"global.mu_t"` で足りる)。
- **参照**: interfaces.py L93 / architecture.md D8 L94 / `src/tsumugin/backends/base.py` L57-62

### 2.2 `RefinementResult` 拡張 — `backends/base.py`

- 🔵 既存フィールド (**不変・順序保持**): `phases, chi2, rwp, n_obs, n_params, converged, n_cycles,
  free_params=frozenset()`。
- 🔵 **末尾追加フィールド 1**: `globals: Mapping[str, float] = field(default_factory=dict)`。
  fitted 大域値を `{"mu_t": <値>}` で記録。既定 空 dict。
- 🔵 **末尾追加フィールド 2**: `warnings: tuple[str, ...] = ()`。経験推定モード明示・逆算 μt 提示・
  restraint 幅超過の相関疑いを文字列で保持。既定 空 tuple。
  - 🟡 warnings をフィールドで持つのは house style (`search/tree.py` `SearchResult.warnings` /
    `sequential/engine.py` の結果 dataclass) に準拠。Python の `warnings.warn` は使わない。
- 🔵 frozen 不変・既定生成の後方互換 (既存 7〜8 引数生成が無改変で通る) を保つ。
- **参照**: interfaces.py L95 / architecture.md D8 L98 / `src/tsumugin/backends/base.py` L28-39

### 2.3 `absorption/model.py` (新設)

- 🔵 **`transmission_factor(two_theta_deg: np.ndarray, mu_t: float) -> np.ndarray`**:
  - 入力: 2θ (度) の配列、実効 μt (`float`, ≥0)。
  - 出力: 各点の吸収因子 **A(θ; μt) = exp(−μt / cos θ)**、`θ = radians(two_theta_deg / 2)`。
    形状は入力と同一の `np.ndarray`。
  - **μt=0 → 全域 1.0** (exp(0)=1、EDGE-006 境界)。μt>0 で 1 未満・低角ほど小 (単調減少傾向)。
  - 🟡 cosθ が 0 近傍 (2θ→180°) となる領域の数値保護は v1 では実用域 (2θ<170° 程度) を前提に不要とみなす
    (合成グリッドは 15〜80°)。必要なら clip は tdd-green で最小限に。
- 🔵 **`AbsorptionConfig`** (frozen dataclass):
  | フィールド | 型 | 既定 | 意味 |
  |---|---|---|---|
  | `mu_t_initial` | `float` | `0.0` | 初期実効 μt (フィット開始値) |
  | `mu_t_calc` | `float \| None` | `None` | restraint 中心 (CellConfig 由来 or None=経験推定) |
  | `restraint_weight` | `float` | `100.0` | w_r。restraint ペナルティ重み |
  | `empirical_mode` | `bool` | `False` | CellConfig 未提供の経験推定モード (警告出力) |
- 🔵 **`AbsorptionConfig.from_cell_config(config: CellConfig) -> AbsorptionConfig`** (staticmethod):
  `config.mu_t_calc` が非 None のとき、それを `mu_t_calc` かつ `mu_t_initial` に採り、
  **強 restraint** (`restraint_weight=100.0`)・`empirical_mode=False`。
  🟡 `config.mu_t_calc is None` のときは経験推定へフォールバック (= `empirical()` 相当) とする
  (REQ-018: CellConfig はあっても μt 未算出なら経験推定が妥当)。
- 🔵 **`AbsorptionConfig.empirical() -> AbsorptionConfig`** (staticmethod):
  `mu_t_calc=None`・**弱 restraint** (`restraint_weight=1.0`)・`empirical_mode=True` (REQ-018)。
  🟡 弱 w_r の既定値 1.0 は interfaces.py L103 注記に依拠。
- **参照**: interfaces.py L97-114 / architecture.md D8 L95-100 / REQ-017/018/019

### 2.4 `SimulatedBackend` 拡張 — `backends/simulated.py`

- 🔵 **`__init__(..., absorption: AbsorptionConfig | None = None)`**: 末尾 keyword 追加、既定 None
  (= 従来挙動)。`self._absorption` に保持。
- 🔵 **`simulate(phases, two_theta)`**: ガウシアン重ね合わせ後、`transmission_factor(two_theta, mu_t)` を
  **乗算**。μt は「精密化中は現在のフィット μt」「absorption=None のとき乗算スキップ (係数 1)」。
  🟡 純関数性維持のため、simulate に `mu_t` を渡す引数拡張 or private `_simulate(phases, tt, mu_t)`
  ヘルパを設ける (公開 `simulate` の既存シグネチャ `(phases, two_theta)` は後方互換を保つ)。設計裁量。
- 🔵 **`refine(model, *, max_cycles=20)`**:
  - `"global.mu_t" ∈ model.free_params` かつ `absorption is not None` のとき、μt を **フィットベクトルへ
    追加成分**として含める (相パラメータ names と併走)。初期値は `absorption.mu_t_initial`。μt ≥ 0 に clip。
  - 目的関数を **chi2 = ‖r‖² + w_r·(μt − μt_calc)²** とする (restraint ペナルティ加算)。
    🟡 LM 整合には拡張残差ベクトルへ `sqrt(w_r)·(μt − μt_calc)` を 1 行足す実装が Jacobian と自然に整合。
    `mu_t_calc is None` (経験推定) のとき restraint 中心は初期値 or 0 とし、弱 w_r で緩く動かす (設計裁量 🟡)。
  - 収束後の μt を **`RefinementResult.globals["mu_t"]`** に記録。
  - `absorption is None` または `"global.mu_t" ∉ free_params` のとき μt は精密化せず (globals 空)、
    simulate も無補正 → **既存挙動と一致**。
- 🔵 **経験推定モード** (`absorption.empirical_mode=True`): `warnings` に「経験推定モード」明示 +
  **逆算 μt 提示** (fitted μt 値) を含める (REQ-018)。
- 🔵 **restraint 幅超過警告** (REQ-103): fitted μt が restraint 中心から**許容幅を超えて逸脱**したとき、
  `warnings` に相関疑い警告を載せる。🟡 許容幅の定義は設計裁量 (例: restraint 由来の 1σ ≈ 1/√w_r の
  定数倍、または相対閾値)。tdd-testcases で具体化。
- **出力例**: `RefinementResult(..., globals={"mu_t": 0.48}, warnings=())` /
  経験推定: `globals={"mu_t": 0.51}, warnings=("経験推定モード: 逆算 μt=0.51 ...",)`。
- **参照**: interfaces.py L117-118 / architecture.md D8 L95-100 /
  `src/tsumugin/backends/simulated.py` L42-235

### 2.5 `GSASIIBackend` — `backends/gsasii.py`

- 🔵 v1 は吸収を **scale への畳み込み近似**として扱う旨を **docstring に明記するのみ** (実装/テスト追加なし、
  REQ-020)。
- **参照**: architecture.md D8 L101 / REQ-020 / `src/tsumugin/backends/gsasii.py` L124-

### 2.6 データフロー

- 🔵 `CellConfig.mu_t_calc` → `AbsorptionConfig.from_cell_config` → `SimulatedBackend(absorption=...)`
  → `refine`: `free_params ∋ "global.mu_t"` → μt フィット + restraint → `RefinementResult.globals["mu_t"]`
  / (経験推定・逸脱時) `.warnings`。
- **参照**: architecture.md D8 / `docs/design/m3-operando/dataflow.md`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **非破壊性 (REQ-404 / P2 / NFR-101)**: `RefinementResult` 新規 2 フィールドは末尾・既定値付き。
  `parse_param` の `global` 分岐は既存 `phase{i}.` 経路に非干渉。`SimulatedBackend.__init__` の
  `absorption` は末尾 keyword・既定 None。**既存テストファイルは 1 行も改変しない**。
- 🔵 **無退行 (完了ゲート)**: `uv run pytest` 全体で**ベースライン 477 collected を無退行維持**
  (474 passed + @gsas 3 skip)。特に `tests/test_backend_interface.py` /
  `tests/test_simulated_backend.py` が無改変で green。
- 🔵 **μt=0 境界一致 (EDGE-006 / TC-207-05)**: `absorption=None` または μt=0 のとき simulate 出力は
  現行とビット一致 (補正因子 1)。無補正回帰を死守。
- 🔵 **決定論 (NFR-102 / REQ-402)**: 乱数不使用。μt フィットは既存 Levenberg–Marquardt の決定論拡張。
  同一入力で **2 回実行がビット同一** (chi2・globals["mu_t"]・warnings)。
- 🔵 **コア依存 numpy のみ (REQ-403)**: xraylib へ実依存しない。`from_cell_config` は
  `CellConfig.mu_t_calc` (float|None) を読むだけで MuCalculator/xraylib を呼ばない (MuCalculator は
  TASK-0025 の Protocol + NotImplementedError スタブのまま、REQ-019)。
- 🔵 **失敗の扱い (CLAUDE.md 不変条件)**: 精密化失敗は例外でなく chi2=inf 結果へ変換 (ガードレール処理)。
  chi2/rwp のセマンティクスはバックエンド間で統一 (restraint 加算後も rwp は強度残差ベースで定義維持)。
  🟡 restraint 項を chi2 に含めるか rwp から除くかは「chi2 は目的関数、rwp は強度適合度」の区別で扱う
  (rwp は既存 `_rwp` の強度残差定義を維持)。
- 🔵 **型注釈必須・Lint clean**: `uvx ruff check src tests` clean (line-length 100, py312)。
  `np.ndarray` / `float | None` / `Mapping[str, float]` / `tuple[str, ...]` / `AbsorptionConfig | None`。
  新規ファイル冒頭に `from __future__ import annotations`。
- **参照**: `CLAUDE.md` (不変条件/コーディング規約), REQ-402/403/404, NFR-102, architecture.md D8

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン

- 🔵 **透過因子計算**: `transmission_factor(np.arange(15,80,0.02), 0.5)` → 各点 exp(−0.5/cosθ)、低角ほど小。
  μt=0 → 全域 1.0。 (REQ-020)
- 🔵 **真値回収** (TC-207-02): μt_true>0 で `simulate` した合成データを、μt=0 初期 + CellConfig
  (mu_t_calc=μt_true) restraint で refine → `globals["mu_t"]` が μt_true を restraint 内で回収。 (REQ-017)
- 🔵 **restraint 抑制** (TC-207-03): restraint 中心から遠い初期/データに対し w_r·(Δμt)² が働き、
  遠い解が抑制される (w_r 大で μt が中心へ引き戻される)。 (REQ-017)

### 4.2 エッジ・エラーケース

- 🔵 **EDGE-006 / TC-207-05 (μt=0 境界)**: `absorption=None` or μt=0 → 補正因子 1、既存結果と一致。無退行。
- 🔵 **TC-207-04 (経験推定モード)**: CellConfig 未提供 (`AbsorptionConfig.empirical()`) → 弱 restraint で
  μt 精密化、`warnings` に経験推定モード明示 + 逆算 μt 提示。 (REQ-018)
- 🔵 **TC-207-06 / REQ-103 (restraint 幅超逸脱)**: fitted μt が restraint 中心から許容幅を超えて逸脱 →
  `warnings` に相関疑い警告 (§14)。
- 🔵 **TC-207-07 / REQ-019 (MuCalculator 未実装)**: `XraylibMuCalculator().mu_t(config)` は
  `NotImplementedError` (TASK-0025 で充足済。本タスクは回帰確認のみ、xraylib へ実依存しない)。
- 🟡 **μt < 0 入力保護**: フィット中は μt≥0 に clip。`transmission_factor` に負 μt を渡すと exp(正) で
  1 超になるが、v1 では clip 済み値のみ流す前提 (関数自体のバリデーションは非スコープ)。
- **参照**: acceptance-criteria.md TC-207-02〜07 / requirements.md EDGE-006, REQ-018/103/019

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m3-operando/user-stories.md` — operando 吸収補正で強度歪みを
  補正し判別信頼性を上げるストーリー (FR-317 系)。
- **参照した機能要件**:
  - REQ-016 (CellConfig データモデル / TASK-0025 で充足、本タスクの入力)
  - REQ-017 (実効 μt 1 パラメータフィット + restraint soft bound) 🔵
  - REQ-018 (CellConfig 未提供 → 経験推定 + 明示警告 + 逆算 μt) 🔵
  - REQ-019 (組成→μt は Protocol のみ / restraint 中心はユーザー指定 μt_calc) 🔵
  - REQ-020 (前方モデルへ吸収因子乗算・SimulatedBackend 検証 / GSAS-II は scale 畳み込み v1 近似) 🔵/🟡
- **参照した非機能要件**: NFR-102 (決定論/ビット同一), REQ-402 (決定論), REQ-403 (numpy のみ),
  REQ-404 (非破壊拡張)
- **参照したEdgeケース**: EDGE-006 (μt=0 補正因子 1 で既存一致)
- **参照した条件付き要件**: REQ-103 (restraint 幅超逸脱で相関疑い警告)
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md`
  TC-207-02 / 03 / 04 / 05 / 06 (本タスク主対象)、TC-207-01 / 07 (TASK-0025 充足・回帰確認)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` D8 (L93-101)、モジュール表 L43、
    ディレクトリ構造 L108-123
  - **型定義**: `docs/design/m3-operando/interfaces.py` L88-118
    (parse_param/globals/AbsorptionConfig/transmission_factor/SimulatedBackend 拡張)
  - **データフロー**: `docs/design/m3-operando/dataflow.md`
  - **既存実装**: `src/tsumugin/backends/base.py` (parse_param/RefinementResult),
    `src/tsumugin/backends/simulated.py` (LM refine ループ),
    `src/tsumugin/backends/gsasii.py` (docstring 対象), `src/tsumugin/model/cell.py` (CellConfig 入力)
  - **タスクノート**: `docs/implements/m3-operando/TASK-0026/note.md`

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (吸収式・restraint 目的関数・非破壊制約・境界挙動が具体)
- 入出力定義: 完全 (parse_param / RefinementResult / AbsorptionConfig / transmission_factor /
  SimulatedBackend の型・既定・境界を明示)
- 制約条件: 明確 (非破壊・無退行 477・決定論・numpy のみ・μt=0 一致)
- 実装可能性: 確実 (既存 LM ループの次元拡張 + 前方モデル乗算 + frozen dataclass)
- 信頼性レベル: 🔵 が主 (骨格は FR-317/D8/interfaces.py に直依拠。🟡 は w_r 既定値・restraint 数値実装・
  許容幅定義・simulate 引数拡張など設計裁量に限定)
```

**信頼性分布**: 🔵 多数 (機能骨格・I/O・制約・受け入れ基準) / 🟡 少数 (w_r=1.0 弱 restraint 既定・
restraint の残差実装形式・逸脱許容幅・simulate への μt 受け渡し方法) / 🔴 なし。

**次のお勧めステップ**: `/tsumiki:tdd-testcases m3-operando TASK-0026` でテストケースの洗い出しを行います。
