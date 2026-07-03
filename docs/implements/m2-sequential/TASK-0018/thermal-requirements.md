# TASK-0018 TDD 要件定義書 — thermal (熱膨張ベースライン + 転移温度推定)

**機能名**: thermal (熱膨張ベースライン + 転移温度推定)
**タスクID**: TASK-0018 / **要件名**: m2-sequential / **タスクタイプ**: TDD
**対象実装**: `src/tsumugin/sequential/thermal.py` / **テスト**: `tests/test_thermal.py`
**作成日**: 2026-07-03

**【信頼性レベル凡例】**: 🔵 EARS要件・設計文書に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 昇温 (operando / 高温) 粉末回折の時系列解析で、(a) 格子定数-温度曲線の
  **熱膨張ベースライン**を多項式 (既定 1 次) でフィットし残差からベースライン逸脱フレーム
  (=転移候補) を分離する `fit_thermal_baseline`、(b) 相分率の温度依存トラジェクトリの
  シグモイド遷移から**転移温度を onset / midpoint ± σ で推定**する `estimate_transition` の
  純関数 2 本を提供する。
- 🔵 **どのような問題を解決するか**: 温度上昇に伴う正常な熱膨張 (滑らかなトレンド) と、相転移に
  よる不連続 (格子ジャンプ・分率の急変) を定量的に切り分け、転移温度を再現可能な数値で提示する。
  手作業のグラフ読み取りを排し、監査可能・決定論的な推定を自動化する。
- 🔵 **想定されるユーザー**: Tsumugin の SequentialEngine (TASK-0022 で統合) および高温相図を
  解析する研究者。本タスク自体はエンジンから独立した純関数ライブラリ層。
- 🔵 **システム内での位置づけ**: `tsumugin.sequential` パッケージの高温モード解析ユーティリティ。
  M2 (シーケンシャル) の FR-320 系。エンジン統合は E2E (TASK-0022) で行い、本タスクは純関数として
  単体で完結・決定論を保証する。
- **参照したEARS要件**: REQ-007 (FR-322), REQ-008 (FR-323)
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` (L169-203 sequential/thermal.py セクション),
  `docs/design/m2-sequential/design-interview.md`

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 `fit_thermal_baseline(temperatures, values, *, degree=1) -> ThermalBaseline`

- 🔵 **入力**:
  - `temperatures: Sequence[float]` — フレーム毎の温度 (昇順想定、単調性は強制しない)。
  - `values: Sequence[float]` — フレーム毎の対象値 (例: 格子定数 `lattice.a`)。`temperatures` と同長。
  - `degree: int = 1` (キーワード専用) — 多項式次数。既定 1 次 (線形熱膨張)。🔵 既定は 🟡。
- 🔵 **出力** `ThermalBaseline` (frozen dataclass, `interfaces.py` L173-180):
  - `parameter: str` — 対象パラメータ名 (例 `"lattice.a"`)。🟡 呼び出し側指定の識別子。
  - `coefficients: tuple[float, ...]` — **低次から** の多項式係数。
    🟡 numpy.polyfit は高次→低次で返すため反転 (`[::-1]`) して格納する。
  - `residuals: tuple[float, ...]` — フレーム毎の残差 (実測 - フィット値)、`values` と同長・同順。
  - `outlier_frames: tuple[int, ...]` — 残差のロバスト z (中央値/MAD) が閾値超過のフレーム index 昇順
    (= ベースライン逸脱 = 転移候補)。🔵
- 🔵 **入出力の関係性**: `coefficients` の多項式を各 `temperatures[i]` で評価した予測に対する
  `values[i] - 予測` が `residuals[i]`。`residuals` のロバスト z 超過 index 集合が `outlier_frames`。

### 2.2 `estimate_transition(temperatures, fractions, *, phase_ref) -> TransitionEstimate | None`

- 🔵 **入力**:
  - `temperatures: Sequence[float]` — フレーム毎の温度。`fractions` と同長。
  - `fractions: Sequence[float]` — 相分率トラジェクトリ (0..1 想定、シグモイド遷移)。
  - `phase_ref: str` (キーワード専用) — 対象相の識別子。
- 🔵 **出力** `TransitionEstimate | None` (frozen dataclass, `interfaces.py` L183-191):
  - `phase_ref: str` — 入力の `phase_ref` をそのまま保持。
  - `onset: float | None` — 分率が **10% 交差** する温度 (線形補間)。🟡 interview Q6。
  - `midpoint: float | None` — 分率が **50% 交差** する温度 (隣接フレーム間の**線形補間**)。🟡
  - `sigma: float | None` — **隣接フレーム間隔ベース**の遷移幅の代理散布度 (> 0)。🟡
  - `direction: Literal["appearing", "disappearing"]` — 分率が増加基調なら `appearing`、
    減少基調なら `disappearing`。🟡
  - **遷移がない場合** (定数分率 / 50% 交差が起きない) → **`None` を返す**。🔵
- 🔵 **入出力の関係性**: 遷移方向により基準 (増加なら 0→1、減少なら 1→0) を定め、指定分率レベル
  (10% / 50%) を横切る隣接フレーム対を線形補間して温度を得る。`onset < midpoint` (appearing 時の
  低温側) の順序関係を満たす。

### 2.3 データフロー

- 🔵 SequentialEngine が生成する `Trajectory` (フレーム毎の温度・相ごと格子/分率) から、
  1 パラメータ列 (格子 or 分率) を抜き出して本純関数へ渡す。本タスクの範囲は「配列 in → 値オブジェクト out」。
- **参照したEARS要件**: REQ-007, REQ-008
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` (ThermalBaseline / TransitionEstimate /
  fit_thermal_baseline / estimate_transition), `docs/design/m2-sequential/dataflow.md`

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (NFR-102 / REQ-402)**: 乱数・I/O・外部状態なしの純関数。同一入力 2 回でビット同一。
  決定論テストは `==` 比較 (`pytest.approx` 禁止箇所)。TC-105-05 で保証。
- 🔵 **非有限値を漏らさない (M1 教訓 / CLAUDE.md)**: `inf`/`nan` を戻り値・下流へ伝播させない。
  算出不能 (交差なし・MAD=0・点数不足) は `None` または空タプルへ縮退し、例外化しない。
- 🔵 **numpy 利用可**: `numpy.polyfit` 使用可 (タスク明記)。polyfit の係数は高次→低次のため反転が必要。
- 🔵 **frozen dataclass**: `ThermalBaseline` / `TransitionEstimate` は `@dataclass(frozen=True)`。
  再代入不可 (FrozenInstanceError)。型注釈必須。
- 🔵 **コーディング規約 (CLAUDE.md)**: snake_case / PascalCase、日本語 docstring 可、line-length 100
  (ruff)、`any` 回避。実装後 `src/tsumugin/sequential/__init__.py` に re-export を追加。
- 🟡 **パフォーマンス**: 純関数・軽量。NFR-001 (100 フレーム 60 秒) はエンジン統合 (TASK-0022) の
  責務で、本純関数は 1 回呼び出しが即時。
- 🟡 **依存**: GSAS-II 非依存 → `@pytest.mark.gsas` 不要。numpy のみ。
- **参照したEARS要件**: NFR-102 (再現性), REQ-402 (決定論), NFR-001 (性能, 間接)
- **参照した設計文書**: `CLAUDE.md` (実装上の不変条件・コーディング規約), `docs/design/m2-sequential/interfaces.py`

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本パターン

- 🔵 **TC-105-03**: 線形熱膨張 + 転移ジャンプの合成データ (例: `a = 5.0 + 1e-4*T`、途中フレームで
  +0.05 のジャンプ)。`fit_thermal_baseline` の 1 次係数が真値近傍、ジャンプフレームが `outlier_frames`
  として正しく分離される。
- 🔵 **TC-105-04**: 相分率がシグモイドで 0→1 に遷移する合成データ。`estimate_transition` の
  `midpoint` が真値 ±1 フレーム間隔、`onset < midpoint`、`sigma > 0`。
- 🔵 **遷移なし**: 定数分率 (例 全フレーム 0.0 or 1.0) → `estimate_transition` は `None`。
- 🟡 **方向判定**: 分率が増加 → `direction="appearing"`、減少 (1→0) → `disappearing`。

### 4.2 エッジケース (testcases フェーズで詳細化)

- 🟡 **完全フィット (残差 MAD=0)**: 逸脱なし → `outlier_frames = ()`。0 除算回避 (ロバスト z 縮退)。
- 🟡 **点数不足** (`len < degree+1`): polyfit が解けないケースの縮退方針 (例外化せず安全側)。testcases で確定。
- 🟡 **単調でないノイズ分率で 50% を複数回交差**: 決定論的に 1 つを選ぶ規則 (例: 最初/方向整合の交差)。testcases で確定。
- 🟡 **単一フレーム / 空入力**: 交差不能 → `None` (estimate) / 空残差 (baseline)。testcases で確定。
- 🔵 **決定論 (TC-105-05)**: 同一入力 2 回で `ThermalBaseline` / `TransitionEstimate` がビット同一。
- **参照したEARS要件**: REQ-007, REQ-008 / 受け入れ基準 TC-105-03/04/05
- **参照した設計文書**: `docs/spec/m2-sequential/acceptance-criteria.md` (REQ-006/007/008 高温モード),
  `docs/design/m2-sequential/interfaces.py`

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 高温 operando 解析ユーザー (昇温相転移の定量化) — REQ-007/008 由来
- **参照した機能要件**: REQ-007 (FR-322 熱膨張ベースライン), REQ-008 (FR-323 転移温度 onset/midpoint±σ)
- **参照した非機能要件**: NFR-102 (再現性・ビット同一), REQ-402 (決定論), NFR-001 (性能, 間接)
- **参照したEdgeケース**: 完全フィット/点数不足/多重交差/単一・空入力 (interfaces.py の縮退方針を敷衍、
  testcases フェーズで確定) — 🟡
- **参照した受け入れ基準**: TC-105-03 (ベースライン係数+逸脱分離), TC-105-04 (midpoint±1/onset<midpoint/σ>0),
  TC-105-05 (決定論ビット同一) — `docs/spec/m2-sequential/acceptance-criteria.md` L54-58
- **参照した設計文書**:
  - **アーキテクチャ**: `CLAUDE.md` (frozen dataclass + 純関数 / 非破壊 / 非有限を漏らさない)
  - **データフロー**: `docs/design/m2-sequential/dataflow.md`
  - **型定義**: `docs/design/m2-sequential/interfaces.py` (ThermalBaseline / TransitionEstimate /
    fit_thermal_baseline / estimate_transition, L169-203)
  - **参考実装**: `src/tsumugin/sequential/changepoint.py` (ロバスト z (中央値/MAD)・MAD=0 縮退・
    決定論・信頼性注記スタイルの手本)
  - **タスク定義**: `docs/tasks/m2-sequential/TASK-0018.md`

---

## 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (対象関数・入出力型・完了条件が interfaces.py + acceptance-criteria で確定)
- 入出力定義: 完全 (2 関数の引数/戻り値型と縮退方針を明記)
- 制約条件: 明確 (決定論・非有限漏洩禁止・frozen・polyfit 係数順)
- 実装可能性: 確実 (numpy polyfit + ロバスト z + 線形補間。changepoint.py に実装手本あり)
- 信頼性レベル: 🔵 が骨格 (関数契約・完了条件・決定論)、🟡 は推定式詳細 (onset/σ/方向) に限定
```

**信頼性レベル分布**: 🔵 中核契約・受け入れ基準は仕様依拠 / 🟡 推定式 (onset=10%・σ=隣接間隔・
方向判定) と一部エッジ縮退方針は妥当な推測 (interfaces.py の "interview Q6" 注記に遡及可能) / 🔴 なし。

**次のお勧めステップ**: `/tsumiki:tdd-testcases m2-sequential TASK-0018` でテストケースの洗い出しを行います。
