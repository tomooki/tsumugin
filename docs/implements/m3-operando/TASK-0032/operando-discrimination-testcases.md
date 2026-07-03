# TASK-0032 TDDテストケース定義: operando/discrimination — 固溶体 vs 二相判別 (FR-313)

**要件名**: m3-operando / **タスクID**: TASK-0032 / **機能名**: operando-discrimination
**対象実装**: `src/tsumugin/operando/discrimination.py` (**新規**) — `DiscriminationConfig` /
`DiscriminationResult` / `discriminate_interval`
**テストファイル**: `tests/test_discrimination.py` (**新規**、実装と 1:1 — 設計 architecture.md L121-122)
**信頼性サマリー**: 🔵 6 / 🟡 1 (FR-313 / 設計 D4 / REQ-010/101 / EDGE-005 / AC TC-204-01〜06 + TC-209-03)

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。
> AC の受け入れ基準 TC-204-01〜06 / TC-209-03 と本書のテスト ID (N/E/BV) の対応を各ケースと §6 の表に明記する。

---

## 0. テスト方針・共通テストダブル

- **フレームワーク**: pytest (>=8) + pytest-cov。実行 `uv run pytest tests/test_discrimination.py`。
  GSAS-II 非依存 (SimulatedBackend + Fake/Spy) → `gsas` マーカー不要 (`tests/conftest.py` の自動 skip 対象外)。
- **決定論検証**: frozen dataclass の `==` によるビット同一比較。物理量の近似は `pytest.approx`。
- **frozen 検証**: `with pytest.raises(dataclasses.FrozenInstanceError):`。
- **ベースライン**: 580 tests collected (2026-07-04)。既存テストは無改変 green。本タスクは新規ファイル分のみ増加。

### 共通ヘルパ 1: 合成系列生成 (SimulatedBackend・乱数なし → ビット同一)

```python
GRID = np.arange(15.0, 60.0, 0.05)  # <30 秒 smoke を意識した小グリッド (先例は 0.02 刻み)

def _solid_solution_series(n_frames=8, a0=5.0, a1=5.10) -> FrameSeries:
    """単相の lattice.a をフレームで線形変化 (格子連続変化 = 固溶体)。"""
    # 各フレーム: SimulatedBackend().simulate((phase(a_i),), GRID) を行として stack

def _two_phase_series(n_frames=8, a_alpha=5.0, a_beta=5.3) -> FrameSeries:
    """端成分 2 相 (格子固定・別位置ピーク) の scale を α:1→0 / β:0→1 で漸移 (二相反応)。"""
```

- 固溶体系列は仮説 A (単相格子解放) が完全適合し、仮説 B (格子固定 2 相) は中間フレームで不適合 → Σbic_A ≪ Σbic_B。
- 二相系列は逆に仮説 B が適合 → Σbic_B ≪ Σbic_A。ピーク分離幅 (a_alpha vs a_beta) は
  `SimulatedBackend.peak_positions` で確認して選ぶ。

### 共通ダブル 2: RecordingSpyBackend (TC-204-03 の要)

```python
class RecordingSpyBackend:
    """SimulatedBackend へ委譲しつつ refine 呼び出し (free_params / max_cycles / phases 数) を記録する。
    RefinementBackend Protocol (name + refine) のみ満たす。先例: tests/test_sequential_engine.py の
    PhaseRecordingSpyBackend / tests/test_multistart_engine.py の呼び出し記録スパイ。"""
    name = "spy"
    def refine(self, model, *, max_cycles=20) -> RefinementResult: ...
```

### 共通ダブル 3: 判別を制御する FakeBackend (僅差 / 高 R / 全滅の注入)

```python
class ControlledFakeBackend:
    """model.phases の相数 (単相=A / 2 相=B) で chi2/rwp を固定返しする決定論スタブ。
    - close モード: Σbic_A − Σbic_B が |ΔBIC| < 10 になる chi2 の組を返す (TC-204-04)。
    - high_r モード: 両仮説とも rwp > 30.0 を返す (TC-204-05/EDGE-005)。
    - diverge モード: マルチスタート対象呼び出しに chi2=inf を返す (EDGE-002)。
    n_obs = model.intensity.size / n_params = len(model.free_params) を返し BIC 算出可能にする。"""
```

---

## 1. 正常系テストケース（基本的な動作）

### TC-N01: 固溶体合成データ → verdict "solid_solution" 🔵 (対応: TC-204-01)
- **何をテストするか**: 格子連続変化の合成系列で単相仮説 (A) の evidence が優位になり、
  `discriminate_interval` が `"solid_solution"` を返すこと。
- **期待される動作**: 仮説 A の区間 Σbic が仮説 B より `close_threshold` 以上小さい → A 優位判定。
- **入力値**: `_solid_solution_series(n_frames=8)`、`frame_range=(0, 7)`、`initial_phases=(単相 a=5.0,)`、
  `backend=SimulatedBackend()`、既定 config。
  - **入力の意味**: FR-313 が判別すべき「固溶体反応」の最小の直接表現 (格子だけが動く)。
- **期待される結果**: `result.verdict == "solid_solution"`、
  `result.delta_evidence <= -config.close_threshold` (ΔBIC = Σbic_A − Σbic_B ≤ −10)、
  `result.escalations == ()`、`result.hypothesis_single.phases` の格子が精密化済み。
- **確認ポイント**: verdict と delta_evidence 符号規約 (requirements §2.3) の整合、非エスカレーション。
- 🔵 信頼性: TC-204-01 / REQ-010 / D4 に直接依拠 (符号規約は requirements §2.3 で確定済み 🟡)。

### TC-N02: 二相合成データ → verdict "two_phase" 🔵 (対応: TC-204-02)
- **何をテストするか**: 端成分分率変化の合成系列で二相仮説 (B) が優位になり `"two_phase"` を返すこと。
- **期待される動作**: 仮説 B (端点格子で初期化・格子固定・scale/wt のみ) の Σbic が優位。
- **入力値**: `_two_phase_series(n_frames=8)`、`frame_range=(0, 7)`、`initial_phases=(単相 a=5.0,)`。
  - **入力の意味**: 二相反応 (2 つの固定位置ピーク群の強度だけが漸移) の最小表現。
- **期待される結果**: `result.verdict == "two_phase"`、`result.delta_evidence >= config.close_threshold`、
  `result.hypothesis_two_phase.phases` が 2 相 (+固定相 0)。
- **確認ポイント**: B 側優位の判定、`hypothesis_two_phase` が端成分 2 相構成であること。
- 🔵 信頼性: TC-204-02 / REQ-010 / D4 に直接依拠。

### TC-N03: マルチスタート必須適用 (spy 検証) 🔵 (対応: TC-204-03 / REQ-004 / FR-233)
- **何をテストするか**: 判別 1 回で両仮説の**区間端点フレーム**にマルチスタート (N=n_starts) が
  必ず適用されること (呼び出し検証)。
- **期待される動作**: `RecordingSpyBackend` の refine 記録に、逐次 refine 分 (max_cycles=seq_max_cycles)
  と別に、マルチスタート分 (max_cycles=ms_max_cycles=15) が **両仮説 × 端点 × n_starts** 本含まれる。
- **入力値**: `_solid_solution_series()`、`config=DiscriminationConfig(multistart=MultistartConfig(n_starts=4))`
  (spy 記録を数えやすい小 N)。
  - **入力の意味**: REQ-004「FR-313 判別時は必須適用」の直接検証。N=4 で呼び出し本数を確定可能に。
- **期待される結果**: `[c for c in spy.calls if c.max_cycles == 15]` の本数が
  `4 × (端点数) × (仮説数)` と一致 (端点 2 × 仮説 2 なら 16)。`result.multistart_single` /
  `result.multistart_two_phase` の `n_starts == 4`。
- **確認ポイント**: マルチスタートの適用箇所 (端点のみ)・本数・`ms_max_cycles` 伝播。
- 🔵 信頼性: TC-204-03 / REQ-004 / D4「区間端点でマルチスタート必須」に直接依拠
  (端点 = start/end の 2 フレームという解釈は dataflow L68 due 🟡)。

### TC-N04: metrics.multistart 付与 🔵 (対応: TC-204-03 後半 / REQ-006)
- **何をテストするか**: `result.hypothesis_single.metrics.multistart` と
  `result.hypothesis_two_phase.metrics.multistart` に `{"n","n_basins","n_diverged"}` が付与されること。
- **期待される動作**: 判別側が `MultistartResult` から dict を組んで両仮説の metrics に記録する
  (単一 basin でも付与 — note.md §6-4)。
- **入力値**: TC-N01 と同じ固溶体構成 (n_starts=8 既定)。
- **期待される結果**: 両仮説の `metrics.multistart` が非 None で、`multistart["n"] == 8`、
  `multistart["n_basins"] == len(result.multistart_*.basins)`、
  `multistart["n_diverged"] == result.multistart_*.n_diverged` と整合。
- **確認ポイント**: キー 3 つの存在と `MultistartResult` との値整合。
- 🔵 信頼性: 完了条件 3「metrics.multistart」/ interfaces.py L266「multistart 記録付き」/ REQ-006 に依拠。

### TC-N05: 仮説 B の格子固定 (D4) 🟡 (対応: D4 / dataflow L66)
- **何をテストするか**: 仮説 B の逐次 refine とマルチスタートで**格子パラメータが解放されない**こと。
- **期待される動作**: spy 記録のうち仮説 B 系呼び出しの `free_params` に `lattice.*` が含まれず
  `scale`/`wt_frac` 系のみ。`hypothesis_two_phase.phases` の格子が端点初期化値とビット同一。
- **入力値**: `RecordingSpyBackend` + `_two_phase_series()`。
- **期待される結果**: B 系 `free_params ⊆ {phase{i}.scale, phase{i}.wt_frac}`。2 相の
  `lattice.a/b/c` が初期化値と `==`。
- **確認ポイント**: D4「格子固定、scale/wt のみ解放」の字義どおりの実装。
- 🟡 信頼性: D4 (L73-74) / dataflow (L66) に依拠 (wt 解放の suffix `wt_frac` は SimulatedBackend
  `_SCALAR_KEYS` からの妥当推測 — note.md §6-3)。

### TC-N06: 固定相 (FixedPhaseSpec) 込み判別 🔵 (対応: FR-312 / REQ-009 / タスク本文)
- **何をテストするか**: `fixed_phases=(CELL_PHASE_PRESETS["Al"],)` を渡すと固定相が両仮説に常駐し、
  構造固定 (scale のみ解放) で扱われること。
- **期待される動作**: 判別は正常完了し、固定相の格子は精密化後もビット不変。spy 記録の固定相 index には
  `phase{i}.scale` のみ解放 (`fixed_free_suffixes` 契約)。
- **入力値**: 固定相ピークを重畳した固溶体合成系列 (simulate に Al 相を加えて生成) + `fixed_phases`。
- **期待される結果**: `result.verdict == "solid_solution"` (固定相が判別を乱さない)、
  `hypothesis_single.phases` 内の固定相 lattice が `CELL_PHASE_PRESETS["Al"].phase.lattice` と `==`。
- **確認ポイント**: 固定相の格子ビット不変 (先例 `tests/test_cell_phases.py` TC-BV03)・scale のみ解放。
- 🔵 信頼性: タスク本文「固定相 (FixedPhaseSpec) 対応」/ REQ-009 / `fixed_free_suffixes` docstring
  (呼び側 = TASK-0032 と明記) に直接依拠。

### TC-N07: ledger 記録 + verify() == True 🔵 (対応: タスク本文「全操作 ledger 記録」/ NFR-105)
- **何をテストするか**: `ledger` 提供時に判別の各操作が追記され、実行後も `ledger.verify()` が True であること。
- **期待される動作**: `ledger.entries` に判別系 kind (`"discrimination.*"` 前置 🟡) と
  マルチスタート系 (`"multistart.*"`) が積まれ、ハッシュチェーンが壊れない。
- **入力値**: `Ledger()` を渡した TC-N01 構成。
- **期待される結果**: `len(ledger.entries) > 0`、判別 verdict/ΔBIC を含むエントリが存在、
  `ledger.verify() is True`。
- **確認ポイント**: 追記専用 (P2)・verify 恒真 (NFR-105)・kind 前置規約。
- 🔵 信頼性: タスク本文 / NFR-105 / データ整合性 (dataflow L120-124) に依拠 (kind 文字列は 🟡 実装裁量)。

### TC-N08: 決定論 — 2 回実行でビット同一 🔵 (対応: TC-204-06 / NFR-102)
- **何をテストするか**: 同一入力で `discriminate_interval` を 2 回実行すると
  `DiscriminationResult` が完全ビット同一になること。
- **期待される動作**: `result_a == result_b` (verdict / delta_evidence / hypothesis_* / multistart_* /
  escalations / warnings すべて `==`)。
- **入力値**: TC-N01 の固溶体構成を独立に 2 回 (ledger/queue なし)。
- **期待される結果**: 完全一致。
- **確認ポイント**: 乱数不使用・安定順・決定論 id 採番 (`MultistartEngine` の決定論に判別側が乗る)。
- 🔵 信頼性: TC-204-06 / 完了条件 6 / NFR-102 / REQ-402 に直接依拠。

---

## 2. 異常系テストケース（エラーハンドリング）

### TC-E01: 僅差 (|ΔBIC| < 10) → "undecided" + ReviewQueue 通知・ブロックしない 🔵 (対応: TC-204-04 / REQ-101)
- **エラーケースの概要**: 両仮説の evidence 差が閾値未満で自動確定できない僅差競合。
- **エラー処理の重要性**: 誤確定を防ぎつつ自動解析を止めない (FR-403 のエスカレーション哲学)。
- **入力値**: `ControlledFakeBackend(mode="close")` — 相数で chi2 を固定返しし
  |Σbic_A − Σbic_B| < 10 を注入。`queue=ReviewQueue()` を渡す。
  - **不正な理由**: どちらの仮説も同程度に説明可能 = 判別情報が不足しているデータ。
  - **実際の発生シナリオ**: 転移初期の僅かな二相分離、低 S/N の operando 区間。
- **期待される結果**: **例外を投げず** `DiscriminationResult` が返る。`verdict == "undecided"`、
  `abs(result.delta_evidence) < 10`、`queue.unresolved` に `reason == "close_competitor"` の
  `ReviewItem` が 1 件以上、`result.escalations` に僅差を示す文字列。
  - **システムの安全性**: 暫定判別 + 人間レビューで継続 (処理ブロックなし)。
- **確認ポイント**: undecided 判定・Queue 連携 (`close_competitor`)・非例外。
- 🔵 信頼性: TC-204-04 / REQ-101 / dataflow L72-76 に直接依拠。

### TC-E02: 両仮説高 R → エスカレーション・判別なし 🔵 (対応: TC-204-05 / EDGE-005)
- **エラーケースの概要**: 両仮説とも rwp > `high_r_threshold` (30.0) — どちらの仮説でもデータを
  説明できない = 未知相の疑い。
- **エラー処理の重要性**: 不適合仮説どうしの比較で誤った verdict を出さない (Dara 教訓)。
- **入力値**: `ControlledFakeBackend(mode="high_r")` — 全 refine に rwp=50.0 を返す。
  `queue=ReviewQueue()` 付き。
  - **不正な理由**: 適合度が悪い仮説同士の evidence 差は判別根拠にならない。
  - **実際の発生シナリオ**: 区間に未知第三相が出現、初期相の同定ミス。
- **期待される結果**: 例外なし。`verdict == "undecided"` (優位側を宣言しない = 「判別なし」の契約表現
  — requirements §2.3)、`result.escalations` に高 R/未知相を示す文字列が非空、
  queue 提供時 `reason == "all_high_r"` (または `"unknown_phase"`) の ReviewItem が積まれる。
  - **システムの安全性**: 未知相フラグで人間へ委譲し、誤確定を回避。
- **確認ポイント**: 高 R 判定 (両仮説とも閾値超)・escalations・verdict を確定しないこと。
- 🔵 信頼性: TC-204-05 / EDGE-005 / dataflow エラーハンドリング (L115) に直接依拠
  (「判別なし」= undecided + escalations の表現は requirements §2.3 で確定済み 🟡)。

### TC-E03: マルチスタート全滅 → 警告付きで判別継続 🟡 (対応: REQ-102 / EDGE-002)
- **エラーケースの概要**: 端点マルチスタートの全 start が発散 (chi2=inf) しても判別がクラッシュしないこと。
- **エラー処理の重要性**: 全滅を例外化すると自動解析パイプライン全体が停止する。
- **入力値**: `ControlledFakeBackend(mode="diverge_multistart")` — マルチスタート呼び出し
  (max_cycles=15) にのみ chi2=inf、逐次 refine は正常値。
  - **不正な理由**: 摂動初期値が全て非収束 = 大域確認が不能な状態。
  - **実際の発生シナリオ**: 摂動幅に対して極端に鋭いピーク・不安定な精密化。
- **期待される結果**: 例外なし。`result.multistart_single.basins == ()` かつ
  `multistart_single.warnings` 非空 (`MultistartEngine` の全滅縮退)、`result.warnings` にも伝播
  (または包含)。verdict は逐次 Σbic 比較から通常どおり決まる (元仮説維持)。
  - **システムの安全性**: 縮退値で継続、判別は放棄しない。
- **確認ポイント**: 全滅の非例外化・警告伝播・判別本体の継続。
- 🟡 信頼性: REQ-102 / EDGE-002 / dataflow L114 (「全滅なら警告+元仮説維持」) に依拠
  (判別側 warnings への伝播粒度は妥当推測)。

### TC-E04: 不正 frame_range → ValueError 🟡 (対応: 器の契約違反 / requirements §2.2)
- **エラーケースの概要**: `start > end` または範囲外 index (`end >= n_frames`、負値) の frame_range。
- **エラー処理の重要性**: 黙って空区間や誤った区間を判別すると上流 (segmentation) のバグを隠蔽する。
- **入力値**: `frame_range=(5, 2)` / `(0, 99)` / `(-1, 3)` (n_frames=8 の系列に対し)。
  - **不正な理由**: 判別対象の区間が定義できない (器の契約違反であり統計縮退ではない)。
  - **実際の発生シナリオ**: 区間分割 (TASK-0033) 側のバグ・手動呼び出しの指定ミス。
- **期待される結果**: `pytest.raises(ValueError)` — 範囲を示すメッセージ。判別処理は開始されない
  (spy の refine 呼び出し 0 件)。
  - **システムの安全性**: フェイルファストで誤判別を防止。
- **確認ポイント**: 3 パターンとも ValueError、メッセージに不正値が含まれる。
- 🟡 信頼性: `sequential/series.py` の明示 ValueError 慣習 / requirements §2.2 に依拠
  (FR-313 要件文には明記なし — 妥当推測)。

---

## 3. 境界値テストケース（最小値、最大値、null等）

### TC-BV01: ΔBIC ちょうど閾値 (|ΔBIC| == 10.0) → verdict 確定 🟡
- **境界値の意味**: 「ΔBIC ≥ 閾値で verdict」(タスク本文) の**閉境界**を固定し、僅差判定との
  不等号の向きを仕様化する。
- **入力値**: `ControlledFakeBackend` で Σbic 差をちょうど 10.0 / 10.0 直下 (9.99) / 直上 (10.01) に注入。
  - **境界値選択の根拠**: タスク本文「ΔBIC ≥ 閾値で verdict、未満は undecided」の字義 (≥ は確定側)。
  - **実際の使用場面**: 閾値付近の実データで確定/エスカレーションのどちらに倒れるかの再現性。
- **期待される結果**: 差 10.0 → 優位側 verdict (undecided ではない)・queue 通知なし。
  差 9.99 → `"undecided"` + queue 通知。差 10.01 → 優位側 verdict。
- **確認ポイント**: `>=` の閉境界の一貫性 (境界の内外で挙動が単調)。
- 🟡 信頼性: タスク本文「ΔBIC ≥ 閾値で verdict」に依拠 (= ちょうどの扱いはその字義からの推測)。

### TC-BV02: queue=None / ledger=None でも動作・結果不変 🔵
- **境界値の意味**: 省略可能な依存注入の既定 (None) での完全動作 (interfaces.py 既定値)。
- **入力値**: TC-E01 と同じ僅差構成で `queue=None, ledger=None`。
  - **境界値選択の根拠**: 僅差 = queue 通知が発生する経路で None ガードが最も効く。
  - **実際の使用場面**: 単発のプログラマティック利用 (Queue/台帳なしの探索的解析)。
- **期待される結果**: 例外なし。`verdict == "undecided"`・`delta_evidence`・`escalations` が
  queue/ledger 提供時と `==` (通知・記録の有無だけが異なる)。
- **確認ポイント**: None ガード (先例 `MultistartEngine` TC-BV05 / `ReviewQueue(ledger=None)`)。
- 🔵 信頼性: interfaces.py L282-283 (`ledger: Ledger | None = None` / `queue: ReviewQueue | None = None`) に直接依拠。

### TC-BV03: 単一フレーム区間 (start == end) の縮退 🟡
- **境界値の意味**: 区間の最小構成。端点 2 つが同一フレームに縮退する。
- **入力値**: `frame_range=(3, 3)` (n_frames=8 の固溶体系列)。
  - **境界値選択の根拠**: 「区間端点」(start/end) が同一になる縮退で二重適用・0 除算等がないこと。
  - **実際の使用場面**: 区間分割が 1 フレームの区間を切り出した場合 (TASK-0033 の粗グリッド端)。
- **期待される結果**: 例外なし。判別結果が返る (verdict はいずれか)。マルチスタートは同一端点への
  重複適用でも決定論 (2 回実行ビット同一) を維持。
- **確認ポイント**: 最小区間の成立・非例外・決定論。
- 🟡 信頼性: frame_range 契約 (requirements §2.2) からの妥当推測 (仕様に単一フレーム区間の明記なし)。

### TC-BV04: DiscriminationConfig / DiscriminationResult は frozen (不変) 🔵
- **境界値の意味**: 値オブジェクトの不変性 (P2 / コーディング規約 frozen dataclass)。
- **入力値**: 既定 `DiscriminationConfig()` と判別結果の各フィールドへ再代入を試みる。
  併せて既定値 `close_threshold=10.0 / high_r_threshold=30.0 / seq_max_cycles=10 /
  multistart == MultistartConfig()` を検証。
- **期待される結果**: `dataclasses.FrozenInstanceError` 送出。既定値が interfaces.py L252-257 と一致。
- **確認ポイント**: frozen=True の付与・既定値の契約一致。
- 🔵 信頼性: interfaces.py L252-271 / CLAUDE.md 規約 (frozen dataclass) に直接依拠。

### TC-BV05: 性能 smoke — 判別 1 区間 (N=8) < 30 秒 🟡 (対応: TC-209-03 / NFR-001)
- **境界値の意味**: NFR-001 の性能上限。マルチスタートを全フレームに掛けると超過する設計違反の検出。
- **入力値**: `_solid_solution_series(n_frames=8)` + `SimulatedBackend()` + 既定 config (n_starts=8)、
  小グリッド (GRID 0.05 刻み)。`time.perf_counter` で計測。
  - **境界値選択の根拠**: AC TC-209-03「判別 1 区間 (N=8) が 30 秒以内」の字義。
  - **実際の使用場面**: 区間分割が多数の区間を生む operando 解析全体のスループット下限。
- **期待される結果**: 経過時間 < 30.0 秒 (合成小グリッド)。判別結果自体も正しい (verdict ==
  "solid_solution")。
- **確認ポイント**: 端点のみマルチスタート・direct refine の設計 (architecture.md L127) が守られていれば
  大幅に余裕で通る smoke であること。
- 🟡 信頼性: TC-209-03 / NFR-001 に依拠 (グリッド粒度・計測方法はテスト設計の妥当推測)。

---

## 4. 開発言語・フレームワーク

- 🔵 **プログラミング言語**: Python 3.12
  - **言語選択の理由**: 既存コードベース (src layout + hatchling、uv 管理) と同一。frozen dataclass +
    Protocol の設計に適合。
  - **テストに適した機能**: dataclass `==` によるビット同一比較 (決定論検証)、
    `dataclasses.FrozenInstanceError` (不変検証)、numpy の決定論合成データ。
- 🔵 **テストフレームワーク**: pytest (>=8) + pytest-cov
  - **フレームワーク選択の理由**: リポジトリ標準 (`pyproject.toml [tool.pytest.ini_options]`,
    testpaths=["tests"])。GSAS-II 依存は `@pytest.mark.gsas` で分離 (本タスクは非依存 → 不要)。
  - **テスト実行環境**: `uv run pytest tests/test_discrimination.py`。依存導入 `uv sync --extra gsas`。
    Lint `uvx ruff check src tests` (line-length 100)。
- 🔵 信頼性: `pyproject.toml` / `CLAUDE.md` (技術スタック) / note.md §1/§5 に依拠。

---

## 5. テストケース実装時の日本語コメント指針（雛形）

```python
def test_solid_solution_series_yields_solid_solution_verdict():
    # 【テスト目的】: 格子連続変化の合成系列で仮説 A が優位となり "solid_solution" 判別になることを確認 (TC-204-01)
    # 【テスト内容】: SimulatedBackend 合成の固溶体系列に discriminate_interval を適用するフルパイプライン
    # 【期待される動作】: verdict=="solid_solution"、delta_evidence <= -close_threshold、escalations==()
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-01 / 設計 D4 に直接依拠

    # 【テストデータ準備】: 単相の lattice.a を 5.00→5.10 へ線形変化させた 8 フレーム合成系列 (乱数なし)
    # 【初期条件設定】: initial_phases は a=5.0 の単相、既定 DiscriminationConfig (n_starts=8)
    series = _solid_solution_series(n_frames=8)
    backend = SimulatedBackend()

    # 【実際の処理実行】: 仮説A 逐次 refine → 仮説B 端成分固定 refine → 端点マルチスタート → ΔBIC 判定
    result = discriminate_interval(backend, series, (0, 7), (PHASE_A0,))

    # 【結果検証】: verdict / delta_evidence 符号 / エスカレーション無し
    # 【検証項目】: 固溶体判別
    # 🔵
    assert result.verdict == "solid_solution"  # 【確認内容】: 仮説 A 優位の verdict
    # 【検証項目】: ΔBIC 符号規約 (Σbic_A − Σbic_B ≤ −閾値)
    # 🔵
    assert result.delta_evidence <= -10.0  # 【確認内容】: A 側 evidence が閾値以上優位
```

- frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`、決定論は
  `assert result_a == result_b`、性能は `time.perf_counter` 差 < 30.0、数値近似は `pytest.approx`。

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `operando-discrimination-requirements.md` §1 (両仮説構築 + evidence 判別)。
- **参照した入力・出力仕様**: 同 §2.1〜2.4 (DiscriminationConfig / discriminate_interval /
  DiscriminationResult / データフロー 7 段)。
- **参照した制約条件**: 同 §3 (決定論 / <30 秒 / 非破壊 / 失敗縮退 / ブロックしない / 固定相粒度 / 後方互換)。
- **参照した使用例**: 同 §4 (固溶体・二相・spy・固定相・僅差・高 R・全滅・不正区間・smoke)。
- **受け入れ基準対応表**:

  | AC / 完了条件 | 内容 | 対応テスト |
  |---|---|---|
  | TC-204-01 | 固溶体データ → "solid_solution" | TC-N01 |
  | TC-204-02 | 二相データ → "two_phase" | TC-N02 |
  | TC-204-03 | マルチスタート必須 (spy) + metrics.multistart | TC-N03, TC-N04 |
  | TC-204-04 | 僅差 → undecided + Queue (ブロックしない) | TC-E01, TC-BV01, TC-BV02 |
  | TC-204-05 / EDGE-005 | 両仮説高 R → エスカレーション・判別なし | TC-E02 |
  | TC-204-06 | 決定論 (2 回でビット同一) | TC-N08 |
  | TC-209-03 / NFR-001 | 判別 1 区間 (N=8) < 30 秒 smoke | TC-BV05 |
  | D4 | 仮説 B 格子固定・scale/wt のみ | TC-N05 |
  | FR-312 / REQ-009 | 固定相対応 (格子不変・scale のみ) | TC-N06 |
  | NFR-105 / P2 | 全操作 ledger 記録 + verify | TC-N07 |
  | REQ-102 / EDGE-002 | マルチスタート全滅の縮退 | TC-E03 |
  | 器の契約 | 不正 frame_range → ValueError | TC-E04 |
  | 規約 (P2) | frozen 不変 + config 既定値 | TC-BV04 |
  | interfaces 既定 | queue/ledger None 動作 | TC-BV02 |
  | 縮退 | 単一フレーム区間 | TC-BV03 |

---

## テストケース数内訳

- **正常系 (§1)**: 8 件 — TC-N01 (固溶体) / N02 (二相) / N03 (spy 必須適用) / N04 (metrics.multistart) /
  N05 (B 格子固定) / N06 (固定相) / N07 (ledger) / N08 (決定論)
- **異常系 (§2)**: 4 件 — TC-E01 (僅差→undecided+Queue) / E02 (両仮説高R) / E03 (全滅縮退) /
  E04 (不正 frame_range)
- **境界値 (§3)**: 5 件 — TC-BV01 (閾値ちょうど) / BV02 (queue/ledger=None) / BV03 (単一フレーム区間) /
  BV04 (frozen+既定値) / BV05 (<30 秒 smoke)
- **合計: 17 件**

---

## 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 8 / 異常系 4 / 境界値 5 で AC TC-204-01〜06 + TC-209-03 と完了条件 7 項目を全網羅
- 期待値定義: 各ケースに具体値と判定方法 (== / pytest.approx / raises / perf_counter) を明記
- 技術選択: Python 3.12 + pytest 確定 (既存構成)
- 実装可能性: SimulatedBackend / MultistartEngine / FixedPhaseSpec / ReviewQueue / Ledger の
  実装済み API + Fake/Spy (先例あり) のみで実現可能
- 信頼性レベル: 🔵 支配的 (🟡 は閾値ちょうどの扱い・B の free_suffixes・全滅警告の伝播粒度・
  frame_range 検証・単一フレーム区間・smoke 計測方法 — いずれも要件へ遡及可能な設計裁量)
```

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m3-operando TASK-0032` で Red フェーズ (失敗テスト作成) を開始します。
