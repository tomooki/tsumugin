# TASK-0034 TDD 開発コンテキストノート

**タスク**: operando/hysteresis + 結合出力 (FR-315 充放電ヒステリシス解析 / FR-314 電気化学量結合出力)。
`operando/hysteresis.py` に `BranchComparison` / `split_branches` / `branch_differences` を、
`operando/output.py` に `combined_csv(trajectory, echem, path)` / `TransitionPoint` を実装する
**要件名**: m3-operando / **タスクID**: TASK-0034 / **タイプ**: TDD / **推定 4h**
**フェーズ**: Phase 4 / **信頼性**: 🔵 3 / 🟡 2 (FR-314/315 / 設計 D9/D-Q10 / REQ-011/012/104 / EDGE-007 / AC TC-205 系)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando (想定)
**依存タスク**: 前提 TASK-0029 (echem CSV ローダ) — 完了 / 後続 TASK-0035 (E2E)。
関連完了資産: TASK-0032 (discrimination)・TASK-0033 (segmentation)・M2 sequential/trajectory・thermal も完了。

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

operando (充放電) の逐次解析トラジェクトリと電気化学量 (echem) を**結合出力**し (FR-314)、
充放電往復の**ヒステリシス**を枝分離・枝間差分として解析する (FR-315)。すべて**決定論の純関数**
(乱数/時刻/集合反復順なし) で、非有限値を CSV/結果へ漏らさない。

### 0.1 `operando/hysteresis.py` (FR-315 / REQ-012/104) 🟡

- **`split_branches(x_values) -> (charge_idx, discharge_idx)`**: 組成 x 列の**隣接差分 dx の符号**で
  充電枝/放電枝のフレーム index を分離する。x が非単調 (往復) の場合に往路/復路を自動判定する
  (REQ-104「x が非単調なら枝分離を自動判定」)。None フレームは差分計算から除外し捏造しない。🟡
- **`branch_differences(x_values, values, *, n_grid=20) -> tuple[BranchComparison, ...]`**:
  充電枝と放電枝を**共通 x グリッド** (n_grid 分割) 上へそれぞれ補間し、同一 x での枝間差分
  (格子/分率など任意の `values` 列) を `BranchComparison(x, charge_value, discharge_value, difference)` で返す。
  **片枝しか存在しない x では charge/discharge/difference のいずれかを `None` にする** (EDGE-007)。🟡
- **`BranchComparison(x, charge_value, discharge_value, difference)`** frozen dataclass。片枝欠損は None。🟡

### 0.2 `operando/output.py` (FR-314 / REQ-011) 🔵/🟡

- **`combined_csv(trajectory, echem, path) -> str`**: `sequential.trajectory.Trajectory` の各行 (frame_index を
  キーとする相由来列 = 格子 a/b/c・scale・wt_frac + フレーム共通列) に、`EchemData` の
  echem 列 (voltage/current/capacity/composition_x = **V/I/Q/x**) を **frame_index 外部結合**で連結して
  CSV へ書き出す。これにより **wt_frac(x)・格子(x)** が同一行に並ぶ (D9)。**非有限 (inf/NaN)/None は空欄**
  (M1/M2 教訓・trajectory `_num_cell` と同一純化)。書き出したパス (str) を返す。🟡 D9
- **`TransitionPoint(frame_index, x, voltage, sigma_x, sigma_v)`** frozen dataclass。判別で確定した
  **区間境界フレームの echem 値を線形補間**して x/V を、**隣接フレームの echem 差**を σ_x/σ_v として算出する
  (D-Q10 / M2 `estimate_transition` と同型)。echem 欠損 (None) は該当フィールドを None にする。🔵

**🚨 絶対制約 (完了条件 5 項目、= AC TC-205)**:
1. トラジェクトリ + echem 結合 CSV (V/x 列入り) が**読み戻せる** (wt_frac(x)/格子(x) 列を含む) 🔵 *TC-205-01*
2. 転移点 **x/V±σ** の算出 (判別境界フレーム echem の線形補間 + 隣接差 σ) 🔵 *TC-205-02*
3. 非単調 x の往復データで**充電枝/放電枝が自動分離**される 🟡 *TC-205-03 / REQ-104*
4. 同一 x での**枝間差分** (格子/分率) が出力され、**片枝のみは None + 警告** 🟡 *TC-205-04 / EDGE-007*
5. **CSV に非有限値が漏れない** (inf/NaN/None は空欄化) 🔵 *M1/M2 教訓*
- **git commit しない** (ユーザー判断)。**質問しない** (自律実行・推奨案で確定)。
- 失敗/欠損は例外でなく縮退 (None + 警告) へ変換 (CLAUDE.md 不変条件)。非有限を出力へ混ぜない。
- 既存テスト無改変 green (後方互換 REQ-404)。`operando/__init__.py` `__all__` へ非破壊追記。

**⚠️ スコープ外**: dQ/dV プロット描画は M3 スコープ外 (データ出力のみ / requirements.md L133)。
転移点の元となる区間境界の**検出**は TASK-0032/0033 (discrimination/segmentation) の担当。本タスクは
与えられた境界フレーム index から echem 表現 (x/V±σ) を導出する出力層に徹する。

**参照元**: `docs/tasks/m3-operando/TASK-0034.md`, `docs/design/m3-operando/architecture.md` D9 (L103-106)・
分割表 (L41-42)、`docs/design/m3-operando/dataflow.md` (結合出力/ヒステリシスノード L27-29)、
`docs/design/m3-operando/design-interview.md` D-Q10 (L55-57)、
`docs/design/m3-operando/interfaces.py` L324-363、
`docs/spec/m3-operando/requirements.md` REQ-011/012/104 (L52-55, L100-101)・EDGE-007 (L127)、
`docs/spec/m3-operando/acceptance-criteria.md` TC-205-01〜04 (L46-49)

---

## 1. 技術スタック

- **言語 / ランタイム**: Python >=3.12 (`pyproject.toml`、uv 管理、src layout + hatchling)。数値は numpy のみ (REQ-403)。
  補間は numpy (`np.interp` 等) を利用可。CSV は stdlib `csv` のみ (trajectory と統一)。
- **テスト**: `uv run pytest` / カバレッジ `uv run pytest --cov=tsumugin`。Lint `uvx ruff check src tests` (line-length 100)。
- **依存導入**: `uv sync --extra gsas` (プレーン `uv sync` は禁止 — gsas 依存が外れる)。
- **アーキテクチャパターン**: 不変データ (frozen dataclass + `with_updates()`) + `typing.Protocol` 境界 +
  純関数コア + stdlib csv 出力層。M0〜M2 / TASK-0029〜0033 と同一。
- **本タスクの対象レイヤ**: `operando/hysteresis.py` = **枝分離/枝間差分の純関数**、
  `operando/output.py` = **結合 CSV 出力 + 転移点導出の純関数**。いずれも精密化 backend を呼ばず、
  上流結果 (`Trajectory` / `EchemData` / 判別境界フレーム index) を受けて変換・出力するだけの下流層。
- **参照元**: `pyproject.toml`, `CLAUDE.md` (L15-27, L63-77), `docs/design/m3-operando/architecture.md` (L18-22)

## 2. 開発ルール

- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしの実装コミット禁止。
- **テスト配置**: 本タスクは `tests/test_hysteresis_output.py` (新規・hysteresis と output の両モジュールを 1 ファイルで検証)
  — 設計のテストファイル一覧に明記 (`docs/design/m3-operando/architecture.md` L121-122)。
- **決定論 (NFR-102)**: 乱数/IO なし・安定ソート・dict 反復順非依存。同一入力 2 回でビット同一。
  枝分離の tie-break (dx==0 のフレーム) は決定論的規約 (例: 直前の枝に属させる or 両枝除外) で固定する。
- **非破壊性 (P2)**: 入力 `trajectory`/`echem`/`x_values`/`values` を破壊しない。返す dataclass は frozen。
  CSV 書き出しは新規ファイル生成 (既存 Ledger/Snapshot に破壊 API を足さない)。
- **非有限を漏らさない** (M1/M2 教訓): inf/NaN/None を CSV セルへ書かず空欄化 (trajectory `_num_cell` を踏襲)。
  枝間差分・転移点でも非有限は None へ縮退。
- **後方互換 (REQ-404)**: 新規モジュール追加のみ。`operando/__init__.py` の `__all__` へ
  `BranchComparison`/`split_branches`/`branch_differences`/`combined_csv`/`TransitionPoint` を非破壊追記。
- **コーディング規約**: snake_case / 型注釈必須 / 日本語 docstring 可 / 実装コメントに信頼性レベル (🔵🟡) 併記が先例。
- **参照元**: `CLAUDE.md` (L40-77), `docs/implements/m3-operando/TASK-0033/note.md` (直近先例),
  `src/tsumugin/operando/__init__.py`, `src/tsumugin/sequential/trajectory.py`

## 3. 関連実装 (実 API 確認済み)

### 3.1 `src/tsumugin/sequential/trajectory.py` — 結合出力の土台 (M2 完了) 🔵
- **`Trajectory(records: tuple[FrameRecord,...], lifecycles: Mapping[str, PhaseLifecycle])`** (frozen)。
  `to_csv(path) -> str` が「フレーム共通列 (frame_index/axis_value/temperature/rwp/chi2/changepoint/…) +
  各相の 8 列 (`{ref}.a/b/c/scale/wt_frac/birth_frame/death_frame/confidence`)」を stdlib csv で決定論書き出し。
- **`FrameRecord(frame_index, axis_value, temperature, phases, rwp, chi2, changepoint, changepoint_reasons, refine_failed)`**
  (frozen)。`frame_index` が **echem 結合の外部結合キー** (D9)。相由来列 (格子/scale/wt_frac) は `record.phases` から。
- **`_num_cell(value) -> str`**: 有限数は `str(value)`、None/非有限 (inf/-inf/NaN) は空文字。**combined_csv も同一純化を再利用**
  (レイヤ横断 import は避け、必要なら output.py 内に同思想のローカル関数を持つ — trajectory の先例に倣う)。
- **combined_csv の設計選択肢**: (a) `Trajectory.to_csv` の列に echem 4 列を append する薄いラッパを output.py に作る、
  (b) trajectory の行組み立てを再利用しつつ echem 列を frame_index で外部結合。**行数は trajectory と echem の
  フレーム和集合 (外部結合)** で、片方欠損フレームは対応列を空欄。tdd-red で列順・結合規約を凍結。
- **参照元**: `src/tsumugin/sequential/trajectory.py` L20-197

### 3.2 `src/tsumugin/operando/echem.py` — echem 列の供給元 (TASK-0029 完了) 🔵
- **`EchemData(voltage, current, capacity, composition_x)`** (frozen)。各フィールドは `tuple[float|None,...]`、
  **位置 index = frame_index** (フレーム同期済み)。欠損は None。空フィールドは `()`。
- combined_csv は `echem.voltage[i]`/`echem.composition_x[i]` 等を frame_index `i` で引き **V/I/Q/x 列**を作る。
  空 tuple (未提供列) は列自体を出さない or 全空欄 — tdd-red で規約固定。None セルは空欄化。
- `to_channels()` は ExternalChannel 群化 (本タスクでは未使用、参照のみ)。
- **参照元**: `src/tsumugin/operando/echem.py` L34-73

### 3.3 `src/tsumugin/sequential/thermal.py` — 転移点算出の同型先例 (M2 / TASK-0024 完了) 🔵
- **`estimate_transition(...) -> TransitionEstimate | None`**: 相分率シグモイドの 50% 交差を**線形補間**で
  midpoint 温度に、**σ = 隣接フレーム温度間隔** `abs(temp[cross+1] - temp[cross])` として算出。
  D-Q10「転移点 x/V±σ は M2 転移温度推定 (Q6) と同型」の直接の実装先例。
- **`TransitionEstimate(onset, midpoint, sigma, ...)`** (frozen)。`_interpolate_crossing(xs, ys, level)` が
  線形補間ユーティリティ。**TransitionPoint も同じ「線形補間 + 隣接差 σ」パターン**を採る。
- **本タスクとの差分**: thermal は分率の 50% 交差点を探すが、TransitionPoint は**境界フレーム index が既知**
  (判別で確定済み)。境界フレーム b は「区間の切り替わり位置」なので、b を挟む隣接 2 フレーム (b-1, b) の
  echem 値を線形補間 (既定は中点相当) して x/V、σ = `abs(echem[b] - echem[b-1])` とするのが自然 (tdd-red で凍結)。
- **参照元**: `src/tsumugin/sequential/thermal.py` L60-233

### 3.4 `src/tsumugin/operando/discrimination.py` — 転移点の入力元 (TASK-0032 完了) 🔵
- **`DiscriminationResult(verdict, delta_evidence, hypothesis_single, hypothesis_two_phase, …)`**。
  各仮説 `Hypothesis.frame_range == (start, end)` が区間境界を保持。TransitionPoint はこの境界フレーム
  (segmentation の `boundaries` や discrimination の区間端点) を `frame_index` 引数に受ける想定。
- **本タスクは discrimination/segmentation を呼ばない**。境界フレーム index を**引数で受け取り**、echem から
  x/V±σ を導出する (責務分離)。TransitionPoint 生成関数のシグネチャ (境界 index + EchemData を受ける形) は
  tdd-red で確定 (interfaces.py には dataclass のみで生成関数は未定義 → 妥当な純関数を新設)。
- **参照元**: `src/tsumugin/operando/discrimination.py` L74-91

### 3.5 `src/tsumugin/operando/segmentation.py` — 境界の供給元 (TASK-0033 完了) 🔵
- **`SegmentationResult.boundaries: tuple[int,...]`** (昇順・端 0/n_frames は含めない) が転移点の frame_index 群。
  E2E (TASK-0035) では `boundaries` の各要素を TransitionPoint 化する流れ。本タスクでは境界 index を直接受ける。
- **参照元**: `src/tsumugin/operando/segmentation.py`, `docs/implements/m3-operando/TASK-0033/note.md`

### 3.6 `src/tsumugin/model/` — 相/チャネル (M0/M2 完了) 🔵
- `PhaseInstance(lattice, scale, wt_frac, phase_ref, …)` (frozen)。`lattice.a/b/c` を combined_csv の格子(x) 列に使う。
- `ExternalChannel(kind, sync_map)` / `ChannelKind` に `"voltage"|"current"|"capacity"|"composition"` 追加済み
  (TASK-0025 拡張)。本タスクは EchemData を直接使うため ExternalChannel は経由しなくてよい。
- **参照元**: `src/tsumugin/model/`, `src/tsumugin/operando/echem.py` L18-28

### 3.7 `src/tsumugin/operando/__init__.py` — export 集約点 🔵
- 現状 `__all__` に echem/cell_phases/discrimination/segmentation の公開 API を列挙。本タスクの 5 シンボルを
  **アルファベット順維持で非破壊追記** (`BranchComparison`/`branch_differences`/`combined_csv`/`split_branches`/`TransitionPoint`)。

## 4. 設計文書

- **契約 (必達)**: `docs/design/m3-operando/interfaces.py` L324-363
  - `BranchComparison(x: float, charge_value: float|None, discharge_value: float|None, difference: float|None)` (frozen)
  - `split_branches(x_values: Sequence[float|None]) -> tuple[tuple[int,...], tuple[int,...]]` — dx 符号で充電枝/放電枝 index 分離 🟡 REQ-104
  - `branch_differences(x_values: Sequence[float|None], values: Sequence[float|None], *, n_grid: int = 20) -> tuple[BranchComparison,...]`
  - `combined_csv(trajectory, echem: EchemData, path: str) -> str` — trajectory + echem 列 (V/I/Q/x) を frame_index 結合し CSV 🟡 D9
  - `TransitionPoint(frame_index: int, x: float|None, voltage: float|None, sigma_x: float|None, sigma_v: float|None)` (frozen) 🔵 FR-314
- **設計 D9** (`architecture.md` L103-106): `FrameRecord` は不変のまま、`combined_csv` が echem 列 (V/I/Q/x) を
  frame_index で**外部結合**して CSV 化。転移点 x/V は**判別境界フレームの echem 値から線形補間**、σ は**隣接フレーム間隔**。
- **設計 D-Q10** (`design-interview.md` L55-57): 転移点 x/V±σ = 判別で確定した区間境界フレームの echem 値を線形補間、
  σ は隣接フレームの echem 差。算出式は M2 の転移温度推定 (Q6 / `estimate_transition`) と**同型**。
- **データフロー** (`dataflow.md` L27-29): 判別 verdict 確定 → `combined_csv` 出力 (wt_frac x / 格子 x / 転移点 x,V±σ)
  → `hysteresis 解析 (任意)` (充放電枝分離 + 同一 x 差分)。
- **要件**: REQ-011 (wt_frac(x)/格子(x)/転移点 x/V±σ をトラジェクトリ/CSV に含める・FR-314)、
  REQ-012 (充放電枝分離 + 同一 x の格子/分率の枝間差分・FR-315)、REQ-104 (x 非単調で枝分離を自動判定)、
  EDGE-007 (片枝のみのデータ → 差分 None + 警告)。
- **AC**: TC-205-01〜04 (`acceptance-criteria.md` L46-49)。TC-209-01 (E2E 一気通貫) は TASK-0035 で検証。
- **参照元**: `docs/design/m3-operando/architecture.md` (D9 / 分割表)、`docs/design/m3-operando/dataflow.md` (L27-29)、
  `docs/design/m3-operando/design-interview.md` (D-Q10)、`docs/design/m3-operando/interfaces.py` (L324-363)、
  `docs/spec/m3-operando/requirements.md` (REQ-011/012/104・EDGE-007)、`docs/spec/m3-operando/acceptance-criteria.md` (TC-205)

## 5. テスト関連情報

- **フレームワーク**: pytest (>=8) + pytest-cov (`pyproject.toml [tool.pytest.ini_options]`, testpaths=["tests"])。
  `tests/conftest.py` が GSAS-II 未導入環境で `gsas` マーカーを自動 skip — **本タスクは backend 非依存
  (Trajectory/EchemData/純データのみ) で GSAS-II 不要 (マーカー不要)**。
- **新規テストファイル**: `tests/test_hysteresis_output.py` (実装 `operando/hysteresis.py` + `operando/output.py` と対応)。
- **命名/コメント規約**: 関数名 `test_*`、日本語コメント【テスト目的】【テスト内容】【期待される動作】+
  信頼性レベル 🔵🟡 (先例: `tests/test_trajectory.py`, `tests/test_discrimination.py`, `tests/test_thermal.py`)。
- **合成データの作り方 (決定論)**:
  - **結合 CSV (TC-205-01)**: `Trajectory` を数フレーム分手組み (各 `FrameRecord` に frame_index と相 phases) +
    `EchemData(voltage=(...), composition_x=(...))` を同数フレームで用意 → `combined_csv` → 生成 CSV を
    `csv.DictReader` で読み戻し、V/x 列と wt_frac/格子(x) 列が期待値どおりか検証 (往復読み戻し)。
  - **転移点 (TC-205-02)**: 既知境界フレーム b と単調な `composition_x`/`voltage` 列 → x/V が隣接補間値、
    σ_x/σ_v が隣接差の絶対値になることを `pytest.approx` で検証。
  - **枝分離 (TC-205-03)**: 非単調な x 列 (例 0→0.8 まで増加後 0.8→0 へ減少) → `split_branches` が
    増加区間 index 群 (充電) と減少区間 index 群 (放電) を返す。折返し点・None フレームの帰属を検証。
  - **枝間差分 (TC-205-04 / EDGE-007)**: 両枝が重なる x 域では difference が有限、片枝しかない x では None +
    `warnings.warn` (UserWarning) を `pytest.warns` で捕捉。
  - **非有限漏洩 (完了条件5)**: chi2/rwp/格子に inf/NaN/None を混ぜた Trajectory・None を含む echem → CSV セルが空欄。
  - 先例グリッド/相組み立て: `tests/test_trajectory.py` の `_record` ヘルパ、`tests/test_thermal.py` の系列生成。
- **テストダブル**: backend 不要。純データ (Trajectory/EchemData) を直接構築する。CSV は `tmp_path` フィクスチャへ書く。
- **決定論検証**: `combined_csv` を 2 回実行しファイルバイト列一致 (trajectory.to_csv の決定論と同様)。
  dataclass 結果は `==` でビット同一比較。
- **frozen 検証**: `with pytest.raises(dataclasses.FrozenInstanceError)` (`BranchComparison`/`TransitionPoint`)。
- **実行**: `uv run pytest tests/test_hysteresis_output.py`。ベースラインは全テスト green を維持 (既存無改変)。
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_trajectory.py`, `tests/test_thermal.py`,
  `tests/test_discrimination.py`, `CLAUDE.md` (L21-23)

## 6. 注意事項

### ⚠️ 設計判断フラグ (tdd-requirements / tdd-testcases / tdd-red で確定すべき点)

1. **combined_csv の結合規約と列順**: (a) trajectory 行に echem 4 列 (voltage/current/capacity/composition_x =
   V/I/Q/x) を**追加**する列順、(b) 行集合 = frame_index の**外部結合** (trajectory ∪ echem のフレーム和集合)、
   (c) 片側欠損フレーム・None セルは空欄。列ヘッダ名 (例 `voltage`/`composition_x` or `V`/`x`) を 1 つに固定。
   最小実装は `Trajectory.to_csv` の列を土台に echem 4 列を末尾追加 (frame_index で引く) が自然。tdd-red で凍結。
2. **転移点の補間規約 (D-Q10)**: 境界フレーム index `b` は「区間切り替わり位置」。x/V は b を挟む隣接 2 フレーム
   (b-1, b) の echem 値の**線形補間** (既定=中点 `(v[b-1]+v[b])/2` 相当、または境界を分数 index として補間)、
   σ = **隣接フレーム echem 差** `abs(v[b]-v[b-1])` (thermal の σ 算法と同型)。b=0 や b=n-1 の端・echem 欠損時の
   フォールバック (None) を固定。**生成関数のシグネチャ** (`transition_point(echem, frame_index) -> TransitionPoint`
   相当の純関数を新設) を tdd-red で確定 (interfaces.py は dataclass のみ定義)。
3. **split_branches の符号規約 (REQ-104)**: dx = x[i]-x[i-1] の符号で枝分離。**充電/放電のどちらを正 dx に
   割り当てるか** (電池慣習では充電=脱リチウム=x 減少が一般的だが、要件は「符号で分離」のみ規定) を 1 つに固定し
   docstring 明記。**折返し点 (dx 符号反転フレーム)** と **dx==0 (平坦)** のフレーム帰属、**None フレーム**の
   除外規約を決定論的に固定 (TC-205-03 / NFR-102)。最初のフレーム (dx 未定義) の扱いも規約化。
4. **branch_differences の共通 x グリッド (EDGE-007)**: 充電枝・放電枝それぞれの (x, value) を共通 x グリッド
   (両枝の x 範囲の重なり or 全範囲を n_grid 分割) 上へ**補間** (numpy `np.interp`、x 昇順ソート要)。
   **重なり域外 (片枝のみ)** の x では該当枝 value を None、difference も None、かつ **UserWarning を 1 回出す**
   (EDGE-007)。グリッドを「重なり域」に取るか「全域」に取るかで片枝 None の出方が変わる → tdd-red で凍結。
   両枝とも同一 x を持つ格子/分率トラジェクトリ (values) を渡す前提 (values は x_values と同長のフレーム列)。
5. **非有限/None の一貫処理**: combined_csv は trajectory `_num_cell` と同思想で inf/NaN/None を空欄化。
   TransitionPoint / BranchComparison は非有限を None へ縮退 (float フィールドに inf を格納しない)。
   M1/M2 教訓 (非有限を出力へ漏らさない) を全出口で守る。
6. **決定論 (NFR-102)**: 補間・ソートは安定 (numpy は決定論)。`combined_csv` は `newline=""`/`utf-8` で
   バイト同一 (trajectory と同一)。枝分離 tie-break・グリッド生成に乱数/集合反復順を持ち込まない。
7. **警告の扱い**: EDGE-007 の片枝欠損は `warnings.warn(..., UserWarning, stacklevel=2)` (echem.py の欠損警告と
   同流儀)。警告は結果 (BranchComparison の None) と併発し、処理はブロックしない (縮退継続)。

### その他の技術的制約

- **numpy のみ** (REQ-403): 補間は `np.interp` 等。pandas 等の外部パーサ/データフレームは使わない。CSV は stdlib csv。
- **後方互換 (REQ-404)**: `operando/__init__.py` の `__all__` へ 5 シンボルをアルファベット順維持で追記。
  既存 export (echem/cell_phases/discrimination/segmentation) は無改変。sequential/trajectory も無改変
  (combined_csv は trajectory を**読むだけ**、必要なら to_csv を内部利用)。
- **性能**: 出力層のため計算量は軽微。テストは数フレームの小データで足りる。
- **参照元**: `src/tsumugin/sequential/trajectory.py`, `src/tsumugin/operando/echem.py`,
  `src/tsumugin/sequential/thermal.py`, `src/tsumugin/model/`,
  `docs/design/m3-operando/architecture.md` (D9), `docs/design/m3-operando/design-interview.md` (D-Q10), `CLAUDE.md`
