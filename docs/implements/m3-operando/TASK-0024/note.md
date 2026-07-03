# TASK-0024 TDD 開発コンテキストノート

**タスク**: thermal `estimate_transition` の onset 意味論修正 — disappearing 相の onset を「遷移開始側」= 90% 交差へ (Issue #4)
**要件名**: m3-operando / **タスクID**: TASK-0024 / **タイプ**: TDD / **推定 2h**
**フェーズ**: Phase 1 (技術負債+モデル) / **信頼性**: 🔵 4/4 (Issue #4 / 設計 D-Q8 / REQ-021 / TC-208-01/02)
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`src/tsumugin/sequential/thermal.py` の `estimate_transition` を修正し、**onset を direction に依らず「遷移開始側」
(= 遷移が始まる低温側・先行するエッジ) を指す**ようにする。現状は direction に関わらず分率 10% 交差を onset とするため、
**disappearing 相 (1→0) では 10% 交差が高温側 (遷移の終端側) に来て `onset > midpoint` となり**、下流で
「遷移開始温度」と誤読される (Issue #4)。

**修正方針 (D-Q8 / Issue #4 対応案 1)**:
- **appearing (0→1)**: onset = **分率 10% 交差** — 現行のまま (低温側・遷移開始側)。
- **disappearing (1→0)**: onset = **分率 90% 交差** — 遷移開始側 (低温側) へ切り替え。
- `_interpolate_crossing` を **direction 対応** にする (もしくは `estimate_transition` 側で direction 別に onset レベルを選ぶ)。
- **フィールド名 `onset` は維持** (中立名 `crossing_10pct` への改名は API 破壊のため回避 — interview Q9)。

**🚨 絶対制約 (完了条件と直結)**:
- **appearing: onset(10% 交差) < midpoint(50%)** — 現行挙動を維持 🔵
- **disappearing: onset(90% 交差) = 遷移開始側 (低温側)** — 90% 交差を採用 🔵 *TC-208-01 / D-Q8*
- direction 別の onset/midpoint 順序を**テストで固定** (現状 disappearing の onset は**未検証**なので**検証を追加**) 🔵 *Issue #4*
- 既存 thermal テストが**意味論修正後の期待値で green** 🔵 *TC-208-02*
- 既存テストの**期待値変更は理由コメント付きで最小修正** (無闇に触らない) 🔵
- **決定論 (NFR-102)** を維持 — 純関数・乱数/IO なし・同一入力ビット同一。
- **非有限漏洩なし (M1 教訓 / CLAUDE.md)** — 交差なしは `None`、例外化しない。
- **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。
- (コミット時) メッセージに **"Closes #4"** を含める (コミット自体は本タスク外)。

**参照元**: `docs/tasks/m3-operando/TASK-0024.md`, `docs/design/m3-operando/design-interview.md` D-Q8,
`docs/design/m3-operando/interfaces.py` L372-373, `docs/spec/m3-operando/interview-record.md` Q9,
`docs/spec/m3-operando/requirements.md` REQ-021, `docs/spec/m3-operando/acceptance-criteria.md` TC-208-01/02,
`docs/spec/m3-operando/user-stories.md` ストーリー 5.1

---

## ⚠️ 重要: 仕様文書の順序不等号に関する矛盾フラグ (実装前に必読)

`docs/tasks/m3-operando/TASK-0024.md` (L12, L20) と `docs/spec/m3-operando/acceptance-criteria.md` TC-208-01 は
**「disappearing で onset(90%) > midpoint」** と記述しているが、これは**採用メカニズム (90% 交差) と数学的に矛盾する**。

**根拠 (数値検証済み)**: `SIGMOID_DOWN`(中心 400 K, 幅 15, 昇温 300→490 K) で `_interpolate_crossing` を実測:

| direction | 10% 交差 | 50% 交差 (midpoint) | 90% 交差 |
|---|---|---|---|
| appearing (SIGMOID_UP) | **366.46 K** | 400.0 K | 433.54 K |
| disappearing (SIGMOID_DOWN) | 433.54 K | 400.0 K | **366.46 K** |

- 単調**減少**シグモイドでは 90% 交差 (分率 0.9) は**必ず 50% 交差より低温側**に来る (366 < 400)。
  すなわち **disappearing の onset(90%) = 366 K < midpoint(400 K)** で、正しくは **`onset < midpoint`**。
- これは Issue #4 の**目的そのもの**と整合する: Issue #4 は「onset は遷移に**先行**すべき (`onset < midpoint`)」であり、
  修正前の `onset(10%) = 433 > midpoint` (=バグ) を**解消**する。よって修正後は `onset < midpoint` が正しい。
- また熱分析の慣用でも onset (転移開始温度) は常に低温側 (< peak/midpoint)。方向によらず `onset < midpoint`。

**結論**: 本タスクのテストは**メカニズム (90% 交差) と実測値 (366 K)** に忠実に **`disappearing: onset < midpoint`** で固定する。
TASK-0024.md L12/L20・TC-208-01 の **「onset > midpoint」表記は誤り**であり、
**「onset は遷移開始側 (低温側)、両方向とも `onset < midpoint`」へ修正すべき**旨を成果物 (requirements/testcases) に明記して上流へ差し戻す。
(タスク prompt の方針文「disappearing の onset = 90% 交差 (遷移開始側)」はメカニズムと `遷移開始側` ラベルを与えており、
不等号は明示していない。メカニズムを優先する。)

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling ビルド)。本タスクは `numpy` を用いる純関数の局所修正。
- **依存**: `numpy` (thermal.py が既に使用)。GSAS-II には依存しない。標準ライブラリ `math` / `typing.Literal`。
- **アーキテクチャパターン**: レイヤ分離 (Interfaces / Agent / Orchestrator / Workers / Data)。
  `sequential/thermal.py` は Workers 層の**純関数モジュール** (乱数・I/O・外部状態なしの決定論関数 2 本 + 値オブジェクト 2 種)。
- **モジュール配置**: 修正対象は `src/tsumugin/sequential/thermal.py` の `estimate_transition` と `_interpolate_crossing`
  (および onset レベル定数 `_ONSET_LEVEL`/`_MIDPOINT_LEVEL`)。公開シンボルは `sequential/__init__.py` / `__init__.py` から re-export 済み (署名不変)。
- **参照元**: `docs/spec/m3-operando/note.md` (技術スタック節), `pyproject.toml`, `CLAUDE.md`

## 2. 開発ルール

- **TDD 厳守**: Red → Green → Refactor。テストなしの実装コミット禁止。本タスクは既存 Green 実装への**意味論修正**のため、
  Red では「disappearing onset の新期待値 (90% 交差 = 低温側)」を検証する失敗テストを追加する。
- **命名規則**: 関数 snake_case、定数 UPPER_SNAKE。`onset` フィールド名は**維持** (改名しない)。
- **型チェック**: 型注釈必須 (`TransitionEstimate.onset: float | None`)。`any` 回避。
- **docstring**: 日本語可。FR/NFR/REQ 番号を紐づける慣習。信頼性レベル 🔵🟡🔴 表記。
  修正に伴い L29-32 の onset 定数コメント・L204-206 の onset 推定コメント・モジュール docstring L7-8 の
  「onset (10% 交差)」記述を **direction 依存 (appearing 10% / disappearing 90%)** へ更新すること。
- **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- **非破壊追加**: frozen dataclass の署名は不変 (本タスクは dataclass フィールド変更なし・値の意味論のみ変更)。
- **タスク毎コミット**: 完了 (テスト green + ruff clean) ごとに 1 コミット。**本セッションでは commit 禁止**。
  Issue #4 は該当コミットに "Closes #4" を含める (コミット自体は本タスク外)。
- **参照元**: `CLAUDE.md`, `docs/spec/m3-operando/note.md` (開発ルール節), `docs/tasks/m3-operando/overview.md`

## 3. 関連実装

### 修正対象 (現行挙動を厳密に読み取ること): `src/tsumugin/sequential/thermal.py`

- **`_ONSET_LEVEL = 0.10` / `_MIDPOINT_LEVEL = 0.50`** (L31-32): onset/midpoint の分率交差レベル定数。
  → onset は **direction 依存**にする必要がある (appearing 0.10 / disappearing 0.90)。
  `_DISAPPEARING_ONSET_LEVEL = 0.90` 等の定数追加、または `1.0 - _ONSET_LEVEL` を disappearing で用いる形が自然。

- **`_interpolate_crossing(temperatures, fractions, level) -> tuple[float, int] | None`** (L140-170):
  分率が `level` を**最初に**横切る隣接対を線形補間し `(温度, 開始 index)` を返す。符号積 `(f0-level)*(f1-level) <= 0`
  で挟み込み判定、平坦対 (`f0 == f1`) は 0 除算回避で除外、交差なしは `None`。
  → **direction 対応化** (D-Q8): appearing は level=0.10、disappearing は level=0.90 を渡すだけで既存ロジックが再利用可能
  (関数シグネチャは変えず、呼び出し側 `estimate_transition` で level を選ぶのが最小変更)。

- **`estimate_transition(temperatures, fractions, *, phase_ref) -> TransitionEstimate | None`** (L173-218):
  - L189-191: 点数 < 2 は `None` へ縮退。
  - L193-197: midpoint = 50% 交差 (`_interpolate_crossing(..., _MIDPOINT_LEVEL)`)。交差なしは `None` (遷移なし)。
  - L199-202: **direction 判定** — `"appearing" if fractions[-1] >= fractions[0] else "disappearing"`。
  - L204-206: **onset 推定 (修正対象)** — 現状 `_interpolate_crossing(..., _ONSET_LEVEL)` で **direction 非依存に 10% 交差**。
    → **direction が "disappearing" のとき onset レベルを 0.90 に切り替える** のが本タスクの核心。
  - L208-209: σ = midpoint 交差隣接フレームの温度間隔 (方向非依存・不変)。
  - **最小修正案**: L204-206 を
    `onset_level = _ONSET_LEVEL if direction == "appearing" else (1.0 - _ONSET_LEVEL)` →
    `onset_hit = _interpolate_crossing(temperatures, fractions, onset_level)` に置換 (midpoint/σ/direction は不変)。

- **`TransitionEstimate`** (L51-65): frozen dataclass。`onset: float | None` フィールド名・型は**不変**。意味論 (値の解釈) のみ変更。

### 参考パターン (同モジュール内・触らない)

- `fit_thermal_baseline` / `_outlier_frames` (L68-137): 本タスク対象外。無改変。
- σ 推定・direction 判定・点数不足縮退: **無改変** (onset レベル選択のみが変更点)。

**参照元**: `src/tsumugin/sequential/thermal.py`

## 4. 設計文書

- **D-Q8 (Issue #4 の実装・確定)** — `docs/design/m3-operando/design-interview.md` L44-48:
  > `_interpolate_crossing` を direction 対応にし、disappearing では 90% 交差を onset に。既存テスト
  > `test_transition_sigmoid_down_direction_disappearing` に onset 検証を追加、既存の期待値変更は変更理由コメント付き。**根拠**: Issue #4 対応案 🔵。
- **interfaces.py (Issue #4 注記)** — `docs/design/m3-operando/interfaces.py` L372-373:
  > estimate_transition (Issue #4 🔵): disappearing の onset = 90% 交差 (遷移開始側)。direction 不変。
- **interview Q9 (onset 修正方針・確定)** — `docs/spec/m3-operando/interview-record.md` L50-53:
  > disappearing は 90% 交差を onset とし、onset は direction に依らず「遷移が始まる側」。フィールド名は維持。
  > **根拠**: Issue #4 の対応案 1 を採用 (命名変更は API 破壊のため回避) 🔵。
- **REQ-021 (Issue #4)** — `docs/spec/m3-operando/requirements.md` L86-88:
  > `estimate_transition` の disappearing 相の onset は**遷移開始側** (90% 交差) を返すよう修正し、
  > direction 別の onset/midpoint 順序をテストで固定しなければならない 🔵。
- **ユーザストーリー 5.1 (onset の誤読防止)** — `docs/spec/m3-operando/user-stories.md` L109-110:
  disappearing 相でも onset が「遷移開始側」を指す / 優先度 Must Have。
- **公開 API**: `src/tsumugin/__init__.py::__all__` / `sequential/__init__.py` に `estimate_transition` / `TransitionEstimate` を re-export 済み。署名不変のため `__all__` 変更なし。
- **参照元**: `docs/design/m3-operando/{design-interview.md,interfaces.py}`, `docs/spec/m3-operando/{interview-record,requirements,user-stories}.md`, `src/tsumugin/__init__.py`

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov (+ httpx, dev グループ)。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **コマンド**: `uv run pytest tests/test_thermal.py` (単体) / `uv run pytest` (全体回帰、`uv sync --extra gsas` 前提)。
  **依存導入は `uv sync --extra gsas`** (プレーン `uv sync` は gsas extra が外れるため禁止)。
- **対象テストファイル**: `tests/test_thermal.py` (既存・18 件)。命名は `test_{module}.py`。
- **合成データ (モジュールレベル・共有)**:
  - `TEMPS_20` = 300..490 K の 10 K 刻み 20 フレーム。
  - `SIGMOID_UP` = `1/(1+exp(-(t-400)/15))` (0→1, appearing, midpoint 真値 400 K)。
  - `SIGMOID_DOWN` = `1/(1+exp((t-400)/15))` (1→0, disappearing, midpoint 真値 400 K)。
    実測交差: 90% 交差 ≈ 366.46 K, 50% ≈ 400 K, 10% 交差 ≈ 433.54 K。
- **direction 関連の既存テスト (必読・影響評価済み)**:
  - `test_transition_sigmoid_up_midpoint_onset_sigma` (L134): appearing。`onset < midpoint` を assert。
    → onset レベルは appearing で 0.10 のまま。**無改変で green** (366 < 400)。
  - `test_transition_sigmoid_down_direction_disappearing` (L155): disappearing。現状 `direction/midpoint/sigma` のみ検証、
    **onset は未検証**。→ **onset 検証を追加** (D-Q8 指定)。新期待値: `onset ≈ 366.46 K` かつ `onset < midpoint` (90% 交差=低温側)。
  - `test_transition_onset_before_midpoint_and_sigma_positive` (L351): appearing。`onset < midpoint`・`σ>0`・有限。
    → **無改変で green** (appearing の onset 10% 交差=低温側は不変)。
  - `test_transition_crossing_on_grid_point` (L332): 端点一致の増加分率。onset 未検証。→ **無改変で green**。
  - `test_transition_deterministic_bit_identical` (L369): appearing で `==` 決定論。→ **無改変で green**。
- **回帰確認 (改変せずに green を維持すべき既存テスト)**:
  - `tests/test_m2_e2e.py::test_e2e_transition_temperature_estimated` (L403): **appearing** 相 B (0→1) で `onset <= midpoint` を assert。
    appearing の onset は不変のため**無改変で green**。
  - `tests/test_m2_e2e.py` の `__all__`/シンボル同一性テスト (署名不変のため影響なし)。
- **影響のない箇所**: disappearing の onset を検証する既存テストは `tests/` 全体で**皆無** (grep 済み)。
  よって**期待値の実質変更は「disappearing テストへの onset assertion 追加」1 点のみ**で、他の既存 assertion は破壊されない。
- **決定論検証の作法**: `==` ビット同一 (pytest.approx 禁止)、温度近似は `pytest.approx`、非有限は `math.isfinite`、frozen は `FrozenInstanceError`。
- **参照元**: `pyproject.toml`, `tests/test_thermal.py`, `tests/test_m2_e2e.py`, `CLAUDE.md`

## 6. 注意事項

### 技術的制約
- **最小修正の原則**: 変更点は「onset レベルの direction 依存化」1 点に閉じる。midpoint 算出・direction 判定・σ 算出・
  点数不足縮退・`_interpolate_crossing` の探索ロジックは**無改変**。既存の Green 挙動を必要以上に動かさない。
- **direction 判定は不変**: `fractions[-1] >= fractions[0]` (境界の等号は appearing 側)。onset レベル選択は**この direction に従う**。
- **`_interpolate_crossing` は「最初の交差」を返す**: 単調シグモイドでは各レベル 1 交差なので、level=0.90 を渡せば
  disappearing の 90% 交差 (低温側・最初の交差) を一意に得る。多相・非単調分率での複数交差は本タスクの想定外 (M2 契約踏襲)。
- **非有限漏洩禁止**: 90% 交差が無い (定数分率・端点未達等) 場合は onset=`None` に縮退し、例外化しない (既存 `_interpolate_crossing` の `None` 経路を踏襲)。
- **決定論**: 純関数のまま。乱数・順序依存・浮動小数の非決定なし。`==` ビット同一を維持。

### 意味論の正: onset は「遷移開始側 (低温側)」
- appearing・disappearing の**どちらも onset < midpoint** となるのが正 (onset は遷移に先行する低温側エッジ)。
  - appearing: 0→1 の 10% 交差 (低温側) = 遷移開始側。
  - disappearing: 1→0 の 90% 交差 (低温側) = 遷移開始側。
- §「⚠️ 矛盾フラグ」の通り、TASK-0024.md/TC-208-01 の「disappearing: onset > midpoint」記述は誤り。**テストは `onset < midpoint` で固定**する。

### セキュリティ・非破壊性
- 純関数のみ。副作用なし・決定論 (NFR-102)。公開 API 署名 (`TransitionEstimate` フィールド・`estimate_transition` 引数) は無改変 (P2 / REQ-404)。

### パフォーマンス
- ホットパスではない (1 相あたり数十フレームの線形補間)。性能要件なし。可読性・意味論の正しさを優先。

- **参照元**: `docs/tasks/m3-operando/TASK-0024.md`, `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/design/m3-operando/design-interview.md` D-Q8, `CLAUDE.md`
