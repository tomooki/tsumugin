# TASK-0034 TDD 要件定義書 — operando/hysteresis + 結合出力 (FR-315 / FR-314)

**機能名**: operando-hysteresis-output / **タスクID**: TASK-0034 / **要件名**: m3-operando
**タイプ**: TDD / **フェーズ**: Phase 4 / **信頼性**: 🔵 3 / 🟡 2
**実装対象**: `src/tsumugin/operando/hysteresis.py` + `src/tsumugin/operando/output.py`
**テスト**: `tests/test_hysteresis_output.py`

> 本書のすべてのパスはプロジェクトルートからの相対パス。信頼性レベル 🔵=資料に直接依拠 /
> 🟡=資料からの妥当な推測 / 🔴=資料にない推測。

---

## 1. 機能の概要（EARS 要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: operando (充放電/高温 in-situ) の逐次 Rietveld 解析トラジェクトリと**電気化学量
  (echem)** を結合して出力し (FR-314)、充放電往復の**ヒステリシス**を枝分離・枝間差分として解析する
  (FR-315)。具体的には 2 モジュール:
  - `operando/output.py`: `combined_csv(trajectory, echem, path)` (トラジェクトリ + echem 列 V/I/Q/x を
    frame_index で外部結合し CSV 化)、`TransitionPoint` (判別境界フレームの echem 線形補間で x/V±σ を算出)。
  - `operando/hysteresis.py`: `split_branches` (組成 x の隣接差分符号で充電枝/放電枝を分離)、
    `branch_differences` (共通 x グリッド上の枝間差分、片枝欠損は None)、`BranchComparison` (差分レコード)。
  *参照: `docs/tasks/m3-operando/TASK-0034.md`, FR-314/315, REQ-011/012*
- 🔵 **解決する問題**: operando 電池反応で「相分率・格子が電気化学量 (x=組成, V=電圧) に対してどう応答するか」
  (wt_frac(x)・格子(x)) を人が読める結合データとして出力し、反応機構の切り替わり点を **転移点 x/V±σ** で
  定量化する。さらに充放電の往復で生じる**ヒステリシス** (同一 x での格子/分率の充電枝と放電枝の差) を
  可視化用データとして提供する。
  *参照: REQ-011/012, `docs/design/m3-operando/dataflow.md` L27-29*
- 🔵 **想定ユーザー**: operando 電池を自動 Rietveld 解析するツール利用者、および上位パイプライン
  (E2E: echem 同期 → 逐次解析 → 区間分割 → 区間判別 → **結合出力/ヒステリシス**) から本機能を呼ぶ
  上位エージェント/オーケストレータ (TASK-0035 E2E)。
  *参照: `docs/spec/m3-operando/acceptance-criteria.md` TC-209-01 (L82-83)*
- 🔵 **システム内での位置づけ**: `operando/hysteresis.py` / `operando/output.py` は**下流の純関数出力層**。
  精密化 backend を呼ばず、上流結果 (`sequential.trajectory.Trajectory` / `operando.echem.EchemData` /
  判別で確定した境界フレーム index) を受けて変換・出力するだけ。dataflow 上は discrimination (FR-313) の
  後段・E2E の末端。転移点算出は M2 `sequential.thermal.estimate_transition` と同型 (D-Q10)。
  *参照: `docs/design/m3-operando/architecture.md` D9 (L103-106)・分割表 (L41-42), dataflow.md L27-29*

- **参照した EARS 要件**: FR-314, FR-315, REQ-011, REQ-012, REQ-104
- **参照した設計文書**: `architecture.md` D9, `dataflow.md` (結合出力/ヒステリシスノード), `interfaces.py` L324-363

---

## 2. 入力・出力の仕様（EARS 機能要件・型定義ベース）

### 2.1 関数・データ型シグネチャ 🔵

*参照: `docs/design/m3-operando/interfaces.py` L329-363*

```python
# operando/hysteresis.py (FR-315)
@dataclass(frozen=True)
class BranchComparison:
    x: float
    charge_value: float | None
    discharge_value: float | None
    difference: float | None

def split_branches(
    x_values: Sequence[float | None],
) -> tuple[tuple[int, ...], tuple[int, ...]]: ...  # (charge_idx, discharge_idx)

def branch_differences(
    x_values: Sequence[float | None],
    values: Sequence[float | None],
    *,
    n_grid: int = 20,
) -> tuple[BranchComparison, ...]: ...

# operando/output.py (FR-314)
def combined_csv(trajectory, echem: EchemData, path: str) -> str: ...

@dataclass(frozen=True)
class TransitionPoint:
    frame_index: int
    x: float | None
    voltage: float | None
    sigma_x: float | None
    sigma_v: float | None
```

加えて、TransitionPoint を境界フレーム index + `EchemData` から導出する**純関数を新設**する
(interfaces.py は dataclass のみ定義、生成関数は未定義のため tdd-red で確定)。想定シグネチャ 🟡:

```python
def transition_point(echem: EchemData, frame_index: int) -> TransitionPoint: ...
```

### 2.2 入力パラメータ 🔵

| 引数 | 型 | 制約・意味 | 信頼性 |
|---|---|---|---|
| `trajectory` | `sequential.trajectory.Trajectory` | `records: tuple[FrameRecord,...]`。`frame_index` が echem 結合の外部結合キー | 🔵 |
| `echem` | `operando.echem.EchemData` | `voltage/current/capacity/composition_x: tuple[float\|None,...]`。位置 index=frame_index | 🔵 |
| `path` | `str` | 出力 CSV パス。戻り値と一致 | 🔵 |
| `x_values` | `Sequence[float \| None]` | フレーム順の組成 x 列。非単調 (往復) を許容。None は欠損 | 🔵 |
| `values` | `Sequence[float \| None]` | `x_values` と同長のフレーム値列 (格子/分率など枝間差分対象) | 🟡 |
| `n_grid` | `int` | 共通 x グリッドの分割数 (既定 20) | 🔵 |
| `frame_index` | `int` | 転移点を導出する境界フレーム index (判別/分割で確定) | 🔵 |

### 2.3 出力値 🔵

| 関数/型 | 出力 | 意味 | 信頼性 |
|---|---|---|---|
| `combined_csv` | `str` | 書き出した CSV パス。CSV は trajectory 列 + echem 列 (V/I/Q/x)、非有限/None は空欄 | 🔵 (列順は 🟡) |
| `split_branches` | `(charge_idx, discharge_idx)` | dx 符号で分離した充電枝/放電枝のフレーム index tuple | 🟡 |
| `branch_differences` | `tuple[BranchComparison,...]` | 共通 x グリッド上の枝間差分レコード列。片枝欠損は None | 🟡 |
| `BranchComparison` | frozen dataclass | `x`/`charge_value`/`discharge_value`/`difference` (片枝欠損 None) | 🟡 |
| `TransitionPoint` | frozen dataclass | 境界フレームの `x`/`voltage`/`sigma_x`/`sigma_v` (欠損 None) | 🔵 |

### 2.4 入出力の関係性 (算出規約) 🔵

- **結合出力 (D9)**: `combined_csv` の各行 = frame_index。trajectory 由来の相列 (格子 a/b/c・scale・wt_frac) と
  echem 由来の V/I/Q/x が同一行に並ぶことで **wt_frac(x)・格子(x)** が表現される。行集合は trajectory と echem の
  フレーム**外部結合** (和集合)、片側欠損・None・非有限は空欄。
  *参照: 設計 D9 (`architecture.md` L104-106), `interfaces.py` L349-350*
- **転移点 (D-Q10)**: 境界フレーム `b` に対し x/V = b を挟む隣接 2 フレーム (b-1, b) の echem 値の**線形補間**、
  σ_x/σ_v = **隣接フレーム echem 差** `abs(v[b] - v[b-1])` (M2 `estimate_transition` の σ 算法と同型)。
  echem 欠損 (None) の該当フィールドは None。
  *参照: 設計 D-Q10 (`design-interview.md` L55-57), `src/tsumugin/sequential/thermal.py` L207-226*
- **枝分離 (REQ-104)**: dx = x[i] − x[i−1] の**符号**で充電枝/放電枝を分離。非単調 x (往復) で往路/復路が
  自動判定される。None フレーム・折返し点・dx==0 の帰属は決定論規約で固定。
  *参照: REQ-104, `interfaces.py` L339-341*
- **枝間差分 (EDGE-007)**: 充電枝・放電枝の (x, value) を**共通 x グリッド** (n_grid 分割) 上へ補間し、
  同一 x での `difference = charge_value − discharge_value`。**片枝しか値を持たない x** は該当 value と
  difference を None にし **UserWarning** を出す。
  *参照: EDGE-007, `interfaces.py` L344-346*

### 2.5 データフロー 🔵

*参照: `dataflow.md` L27-29*

`discriminate_interval (FR-313) で verdict 確定` → **`combined_csv` 出力 (wt_frac x / 格子 x / 転移点 x,V±σ)**
→ **`hysteresis 解析 (任意)` (充放電枝分離 + 同一 x 差分)**。本タスクは判別/分割を呼ばず、上流結果
(Trajectory / EchemData / 境界 index) を受けて出力・変換する末端層。

- **参照した EARS 要件**: FR-314, FR-315, REQ-011, REQ-012, REQ-104
- **参照した設計文書**: `interfaces.py` L324-363, `dataflow.md` L27-29, `design-interview.md` D-Q10

---

## 3. 制約条件（EARS 非機能要件・アーキテクチャ設計ベース）

- 🔵 **非有限を漏らさない (M1/M2 教訓 / 完了条件5)**: CSV セルは inf/NaN/None を**空欄化**
  (`sequential.trajectory._num_cell` と同思想)。`TransitionPoint`/`BranchComparison` の float フィールドへ
  非有限を格納せず None へ縮退。
  *参照: `CLAUDE.md` 不変条件, `src/tsumugin/sequential/trajectory.py` L183-197*
- 🔵 **決定論 (NFR-102)**: 乱数/時刻/集合反復順なし。補間・ソートは numpy の決定論演算のみ。
  `combined_csv` は `newline=""`/`utf-8` でバイト同一 (trajectory.to_csv と同一)。枝分離の tie-break
  (dx==0・折返し点) は安定規約で固定し 2 回実行でビット同一。
  *参照: `CLAUDE.md` NFR-102, TC-205 決定論*
- 🔵 **非破壊性 (P2 / NFR-101/105)**: 入力 `trajectory`/`echem`/`x_values`/`values` を破壊しない。返す
  dataclass は frozen。CSV は新規ファイル生成のみ (Ledger/Snapshot に破壊 API を足さない)。
  *参照: `CLAUDE.md` P2*
- 🔵 **後方互換 (REQ-404)**: 新規モジュール追加のみ。`operando/__init__.py` の `__all__` へ
  `BranchComparison`/`branch_differences`/`combined_csv`/`split_branches`/`TransitionPoint` を非破壊追記。
  既存 export・`sequential/trajectory.py` は無改変 (combined_csv は trajectory を読むだけ)。全テスト green 維持。
  *参照: `src/tsumugin/operando/__init__.py`, REQ-404*
- 🔵 **コア依存 numpy のみ (REQ-403)**: 補間は `np.interp` 等。pandas 等の外部データフレーム/パーサ不使用。
  CSV は stdlib `csv` のみ。
  *参照: `CLAUDE.md`, REQ-403*
- 🟡 **縮退・警告政策 (EDGE-007)**: 片枝欠損は `warnings.warn(..., UserWarning, stacklevel=2)` で通知しつつ
  None を返し処理をブロックしない (echem.py の欠損警告と同流儀)。
  *参照: EDGE-007, `src/tsumugin/operando/echem.py` L137-143*
- 🔵 **アーキテクチャ制約**: 不変データ (frozen dataclass) + 純関数コア + stdlib csv 出力層。型注釈必須・
  snake_case・日本語 docstring 可・信頼性レベル併記。
  *参照: `CLAUDE.md` コーディング規約, `architecture.md` L18-22*

- **参照した EARS 要件**: NFR-101/102/105, REQ-403/404, EDGE-007
- **参照した設計文書**: `architecture.md` (L18-22, D9), `CLAUDE.md` 不変条件

---

## 4. 想定される使用例（EARS Edge ケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

1. **結合出力 (通常系)**: 逐次解析で得た `Trajectory` と `read_echem_csv` で得た `EchemData` を
   `combined_csv` に渡す → V/x 列 + wt_frac(x)/格子(x) 列を含む CSV が生成され、`csv.DictReader` で読み戻せる。
   *参照: TC-205-01, REQ-011*
2. **転移点定量化**: 判別/分割で確定した境界フレーム index を `transition_point(echem, b)` に渡す →
   境界の x/V (隣接補間) と σ_x/σ_v (隣接差) が `TransitionPoint` として得られる。
   *参照: TC-205-02, REQ-011, D-Q10*
3. **ヒステリシス解析 (任意)**: 充放電往復で非単調な x 列を `split_branches` に渡す → 充電枝/放電枝の
   フレーム index が分離され、`branch_differences(x_values, values)` で同一 x の枝間差分が得られる。
   *参照: TC-205-03/04, REQ-012*

### 4.2 データフロー 🔵

*参照: `dataflow.md` L27-29*

verdict 確定 → `combined_csv` (wt_frac x/格子 x/転移点 x,V±σ を出力) → `hysteresis 解析` (充放電枝分離 +
同一 x 差分)。転移点は境界フレームを起点に echem 線形補間、枝分離は x の dx 符号、枝間差分は共通 x グリッド補間。

### 4.3 エッジ・エラーケース

| ケース | 期待動作 | 信頼性 | 参照 |
|---|---|---|---|
| 非有限 (inf/NaN)/None セル | CSV は空欄化、dataclass float は None へ縮退 | 🔵 | 完了条件5 / M1/M2 教訓 |
| 片枝のみのデータ (往復なし) | 該当 x の枝間差分 None + `UserWarning` | 🟡 | EDGE-007 / TC-205-04 |
| 非単調 x (往復) | dx 符号で充電枝/放電枝を自動分離 | 🟡 | REQ-104 / TC-205-03 |
| echem 欠損フレーム (None) / 境界端 (b=0, b=n-1) | 転移点の該当フィールドを None (隣接不能) | 🟡 | D-Q10 縮退 |
| echem 列が空 tuple (未提供) | 該当 echem 列を CSV に出さない or 全空欄 | 🟡 | echem.py 空縮退 (tdd-red 凍結) |
| trajectory と echem のフレーム数不一致 | 外部結合し欠損側を空欄 | 🟡 | D9 外部結合 |
| dx==0 (平坦) / 折返し点フレーム | 決定論規約で枝帰属を固定 | 🟡 | NFR-102 (tdd-red 凍結) |

- **参照した EARS 要件**: EDGE-007, REQ-104
- **参照した設計文書**: `dataflow.md` L27-29, `architecture.md` D9, `design-interview.md` D-Q10

---

## 5. EARS 要件・設計文書との対応関係

- **参照したユーザストーリー**: operando 電気化学量結合出力・充放電ヒステリシス解析
  (`docs/spec/m3-operando/user-stories.md` 結合出力/ヒステリシス / operando 一気通貫)
- **参照した機能要件**: REQ-011 (wt_frac(x)/格子(x)/転移点 x/V±σ をトラジェクトリ/CSV に含める・FR-314),
  REQ-012 (充放電枝分離 + 同一 x の格子/分率の枝間差分・FR-315), REQ-104 (x 非単調で枝分離を自動判定)
- **参照した非機能要件**: NFR-102 (決定論/再現性), NFR-101/105 (非破壊・ハッシュチェーン), REQ-403 (numpy のみ),
  REQ-404 (後方互換・非破壊追加)
- **参照した Edge ケース**: EDGE-007 (片枝のみ → 差分 None + 警告)
- **参照した受け入れ基準**: TC-205-01 (V/x 列入り結合 CSV・wt_frac(x)/格子(x) 出力), TC-205-02 (転移点 x/V±σ),
  TC-205-03 (非単調 x の充放電枝自動分離), TC-205-04 (同一 x 枝間差分・片枝のみ None+警告)。
  **スコープ外**: TC-209-01 (E2E → TASK-0035)、dQ/dV プロット描画 (M3 スコープ外・データ出力のみ)。
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` D9 (L103-106: 結合出力・転移点線形補間)、
    分割表 (L41-42: hysteresis/output モジュール)、ディレクトリ構造 (L113-122)
  - **データフロー**: `docs/design/m3-operando/dataflow.md` L27-29 (combined_csv / hysteresis ノード)
  - **型定義**: `docs/design/m3-operando/interfaces.py` L324-363 (`BranchComparison` / `split_branches` /
    `branch_differences` / `combined_csv` / `TransitionPoint`)
  - **設計ヒアリング**: `docs/design/m3-operando/design-interview.md` D-Q10 (L55-57: 転移点 x/V±σ = 境界フレーム
    echem 線形補間 + 隣接差 σ、M2 転移温度推定と同型)
  - **依存実装**: `src/tsumugin/sequential/trajectory.py` (Trajectory/to_csv/_num_cell = 結合出力の土台),
    `src/tsumugin/operando/echem.py` (EchemData = echem 列供給元),
    `src/tsumugin/sequential/thermal.py` (estimate_transition = 転移点算出の同型先例),
    `src/tsumugin/operando/discrimination.py`/`segmentation.py` (境界フレームの供給元),
    `src/tsumugin/operando/__init__.py` (export 集約点)

---

## 品質判定

✅ **高品質**:
- 要件の曖昧さ: なし (契約は interfaces.py L324-363 に確定、転移点算式は D9/D-Q10 + thermal 先例に明記)
- 入出力定義: 完全 (5 シンボルのシグネチャ・Config/Result 全フィールド・結合/補間/枝分離規約を明記)
- 制約条件: 明確 (非有限漏洩防止/決定論/非破壊/後方互換/numpy のみ/警告政策を NFR 紐付けで列挙)
- 実装可能性: 確実 (Trajectory.to_csv / EchemData / estimate_transition が実装済みで再利用可、backend 不要)
- 信頼性レベル: 🔵 主体 (🟡 は枝分離符号規約・共通グリッド・結合列順・転移点補間の細部と縮退派生に集中)

**残す設計判断 (tdd-testcases / tdd-red で確定)**: combined_csv の列順/結合規約、転移点の補間規約と生成関数
シグネチャ、split_branches の符号割当・折返し/None 帰属、branch_differences の共通グリッド域取り
(→ note.md §6 に整理済み)。

---

**次のお勧めステップ**: `/tsumiki:tdd-testcases m3-operando TASK-0034` でテストケースの洗い出しを行います。
