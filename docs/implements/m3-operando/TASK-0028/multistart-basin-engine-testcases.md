# TASK-0028 TDDテストケース定義: multistart/basin + MultistartEngine (FR-230/232)

**要件名**: m3-operando / **タスクID**: TASK-0028 / **機能名**: multistart-basin-engine
**対象実装**: `src/tsumugin/multistart/basin.py` (**未実装**) / `src/tsumugin/multistart/engine.py` (**未実装**)
**テストファイル**: `tests/test_multistart_basin.py` / `tests/test_multistart_engine.py` (**新規**)
**信頼性サマリー**: 🔵 5 / 🟡 1 (FR-230/232 / 設計 D2/D3 / REQ-002〜006・102 / AC TC-201-02〜06)

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。
> AC の受け入れ基準 TC-201-02〜07 と本書のテスト ID (B01〜/E01〜/BV01〜) の対応を各ケースに明記する。

---

## 0. テスト方針・共通テストダブル

- **フレームワーク**: pytest (>=8) + pytest-cov。実行 `uv run pytest tests/test_multistart_basin.py
  tests/test_multistart_engine.py`。GSAS-II 非依存 (FakeBackend) → `gsas` マーカー不要。
- **決定論検証**: `==` によるビット同一比較 (basins / member_starts / promoted)。物理量近似は `pytest.approx`。
- **frozen 検証**: `with pytest.raises(dataclasses.FrozenInstanceError):`。
- **ベースライン**: 523 collected (2026-07-04)。既存テストは無改変。本タスクは新規ファイル分だけ増加。

### 共通ダブル: 初期値依存 FakeBackend (双峰テストの要 / 🔵 note §3 の範)

`tests/test_tree_search.py` の `FakeBackend` (`chi2_by_refs` 方式) を**初期値依存へ拡張**したスタブを
テストファイル内に定義する (test_tree_search.py は無改変)。`RefinementBackend` Protocol
(`name` + `refine(model, *, max_cycles=20) -> RefinementResult`) のみ満たす。

```python
class InitialValueFakeBackend:
    """初期値 (model.phases[0].lattice.a) 依存で収束解を決める決定論スタブ。

    - basin_map: a の閾値 → (収束 phases, chi2) の吸引域テーブル。
    - 単峰: 全 a を同一 (phases, chi2) へ写像。
    - 双峰: a < split → basin1、a >= split → basin2。
    - 発散: diverge_predicate(a) True の start は chi2=inf を返す。
    refine は入力 a を吸引域へスナップした固定 phases を返す (basin 距離が閾値内に収まる)。
    """
    name = "ivfake"
    def refine(self, model, *, max_cycles=20) -> RefinementResult: ...
```

- 収束 phases は**吸引域ごとに固定** (格子 a/b/c・scale) にし、同一 basin の start が正規化距離
  `< basin_rel_tol` に収まるようにする (basin クラスタが 1 群に畳まれる)。
- chi2 は吸引域ごとに固定 (双峰では basin1 と basin2 で別値にして代表選出・evidence 昇順を検証可能にする)。
- `n_obs` = `model.intensity.size`、`n_params` = `len(model.free_params)` を返す (BIC 算出のため)。
- `converged = math.isfinite(chi2)`。

---

## 1. 正常系テストケース

### TC-B01: basin クラスタ — 全解近接で 1 basin 🔵 (対応: TC-201-02 の basin 層)
- **何をテストするか**: `basin.py` のクラスタ関数が、正規化距離が全対で `basin_rel_tol` 未満の
  収束解群を 1 つの basin に畳むこと。
- **期待される動作**: 返り値 `len == 1`。`member_starts` に全 start index が昇順で入る。
  `representative` は chi2 最小解。
- **入力値**: 8 個の `RefinementResult` (格子 a がすべて基準 ±0.1% 以内、chi2 は 8..15 でばらつき)。
  - **入力の意味**: 単峰 = 全 start が同一 basin へ収束した状況の直接表現。
- **期待される結果**: `basins == (BasinInfo(representative=<chi2 最小の解>,
  member_starts=(0,1,2,3,4,5,6,7), chi2=8.0, evidence=<bic(8.0)>),)`。
- **確認ポイント**: member_starts の昇順、代表 = chi2 最小 (同点なし)、evidence = `BICBackend` 値。
- 🔵 信頼性: D3 (相対距離 < tol の union-find) / REQ-002 に直接依拠。

### TC-B02: basin クラスタ — 2 群で 2 basin・evidence 昇順 🔵 (対応: TC-201-03 の basin 層)
- **何をテストするか**: 2 つの離れたパラメータ群 (群内近接・群間 tol 超) が 2 basin に分かれ、
  返り値が **evidence 昇順** に並ぶこと。各 basin の chi2/evidence が正しく報告されること。
- **期待される動作**: `len == 2`、`basins[0].evidence <= basins[1].evidence`。各 `member_starts` は
  それぞれの群の index 群 (昇順)。
- **入力値**: 4 解が格子 a≈5.0 (chi2≈8 群)、4 解が a≈6.0 (chi2≈12 群)。
- **期待される結果**: basin(a≈5.0, chi2=8, evidence 小) が `basins[0]`、basin(a≈6.0, chi2=12) が `basins[1]`。
  各 `chi2`/`evidence` が群代表の値。
- **確認ポイント**: 群分割の正しさ、evidence 昇順ソート、各 basin の chi2/evidence 報告 (REQ-002)。
- 🔵 信頼性: D3 / REQ-002 (basin 数・chi2・evidence・代表報告) に直接依拠。

### TC-B03: basin 代表 = chi2 最小 (同点は start index 小) 🔵
- **何をテストするか**: 1 basin 内で `representative` が chi2 最小解になり、chi2 同点時は
  start index の小さい方が代表になること (決定論)。
- **入力値**: 3 解が同一 basin、chi2 = [10.0, 8.0, 8.0] (index1/2 が同点最小)。
- **期待される結果**: `representative` は index1 の解 (同点 → index 小)。`member_starts == (0,1,2)`。
- **確認ポイント**: chi2 最小選出 + 同点 index 小優先の決定論。
- 🔵 信頼性: D3 (代表は chi2 最小) / clustering の同点 index 小優先パターンに依拠。

### TC-E01: engine 単峰 → n_basins=1・傍証あり 🔵 (対応: TC-201-02 / EDGE-001)
- **何をテストするか**: `MultistartEngine.run` が単峰スタブで全 start を同一 basin へ収束させ、
  `is_global_corroborated == True`、`promoted == ()` を返すこと。
- **期待される動作**: `len(result.basins) == 1`、`result.is_global_corroborated is True`、
  `result.promoted == ()`、`result.n_diverged == 0`、`result.n_starts == 8`。
- **入力値**: `InitialValueFakeBackend` 単峰モード、`config=MultistartConfig(n_starts=8)`、合成 `two_theta`/`intensity`。
- **期待される結果**: 上記 + `result.basins[0].member_starts` が全 8 index。
- **確認ポイント**: 単一 basin 判定と「大域最適の傍証あり」フラグ (REQ-003)。
- 🔵 信頼性: TC-201-02 / EDGE-001 / REQ-003 に直接依拠。

### TC-E02: engine 双峰 → n_basins=2・両 basin の chi2/evidence 報告 🔵 (対応: TC-201-03)
- **何をテストするか**: 双峰スタブ (初期値依存で 2 解へ収束) で `n_basins == 2` となり、
  両 basin の chi2/evidence が報告されること。
- **期待される動作**: `len(result.basins) == 2`、各 `BasinInfo.chi2`/`.evidence` が有限で 2 値が異なる。
  basins は evidence 昇順。
- **入力値**: `InitialValueFakeBackend` 双峰モード (a<split→chi2=8, a>=split→chi2=12)、n_starts=8。
  摂動列 `generate_starts` により半数が各吸引域へ入るよう split を設定。
- **期待される結果**: `basins[0].chi2 == 8.0`, `basins[1].chi2 == 12.0`、
  `basins[0].evidence < basins[1].evidence`、両 `member_starts` の和集合 = 発散を除く全 start。
- **確認ポイント**: 初期値依存の 2 解分離、両 basin 報告、evidence 昇順。
- 🔵 信頼性: TC-201-03 に直接依拠。

### TC-E03: engine 複数 basin → Hypothesis 昇格・rank 可能 🔵 (対応: TC-201-04 / FR-232)
- **何をテストするか**: 双峰で複数 basin が検出されたとき、各 basin が `Hypothesis` へ昇格され
  `result.promoted` に入り、evidence で rank 可能なこと (多峰性を隠蔽しない REQ-003)。
- **期待される動作**: `len(result.promoted) == 2`。各 `Hypothesis.phases` が該当 basin 代表の phases。
  `promoted` は evidence 昇順 (basins と同順)。各 `Hypothesis.metrics.multistart` が非 None。
- **入力値**: TC-E02 と同じ双峰構成。
- **期待される結果**: `promoted[0]` が evidence 最小 basin 由来、`promoted[1]` が次点。
  各 metrics.multistart == `{"n":8, "n_basins":2, "n_diverged":<D>}`。
- **確認ポイント**: 昇格仮説の生成・順序・phases 対応・rank 可能性 (evidence 昇順)。
- 🔵 信頼性: TC-201-04 / FR-232 / REQ-003 に直接依拠。

### TC-E04: metrics.multistart {n, n_basins, n_diverged} 記録 🔵 (対応: TC-201-06 / REQ-006)
- **何をテストするか**: 昇格仮説 (複数 basin) の `metrics.multistart` に `{"n","n_basins","n_diverged"}`
  が正しく記録されること。
- **期待される動作**: `Hypothesis.metrics.multistart == {"n": 8, "n_basins": 2, "n_diverged": 0}` (双峰・発散なし時)。
- **入力値**: TC-E02 の双峰構成 (発散なし)。
- **期待される結果**: 上記 dict と完全一致 (キー・値とも)。
- **確認ポイント**: 記録キーの正しさ (`n`/`n_basins`/`n_diverged`)、値の整合。
- 🔵 信頼性: TC-201-06 / REQ-006 (RefinementMetrics.multistart) に直接依拠。

### TC-E05: 各 start が direct refine で N 回呼ばれる 🔵 (対応: D2 / REQ-005)
- **何をテストするか**: `run` が各 start に対し `backend.refine` を **N 回** (staged でなく 1 start 1 回)、
  `max_cycles=config.ms_max_cycles` で呼ぶこと。
- **期待される動作**: スパイ backend の `refine` 呼び出し回数 == `config.n_starts`。各呼び出しの
  `max_cycles == config.ms_max_cycles` (既定 15)。各 `free_params` が `free_suffixes` × 相数で構成される。
- **入力値**: 呼び出し記録スパイ (RecordingSpy 拡張)、n_starts=8, ms_max_cycles=15。
- **期待される結果**: `len(spy.calls) == 8`、全 `max_cycles == 15`、`free_params` に
  `phase0.scale`/`phase0.lattice.a/b/c` を含む。
- **確認ポイント**: direct 1 回呼び (D2)・max_cycles 伝播・free_params 構築 (param_name)。
- 🔵 信頼性: D2 / interfaces.py run シグネチャ (free_suffixes) / REQ-005 に依拠。

### TC-E06: ledger 記録・verify()==True 🔵 (対応: NFR-105 / タスク「全操作 ledger 記録」)
- **何をテストするか**: `ledger` 提供時、`run` が各操作を追記し、実行後も `ledger.verify()` が True であること。
- **期待される動作**: `len(ledger.entries) > 0` (start/basin/promote 等)、`ledger.verify() is True`。
  `kind` が `"multistart.*"` で始まる。
- **入力値**: `Ledger()` を渡した engine、双峰構成。
- **期待される結果**: エントリ非空、verify True、追記のみ (既存 entries を上書きしない)。
- **確認ポイント**: 追記専用・ハッシュチェーン整合 (NFR-105)、ledger=None なら記録スキップも別途確認 (TC-BV05)。
- 🔵 信頼性: NFR-105 / TASK-0028 タスク本文「全操作 ledger 記録」に依拠。

### TC-E07: 決定論 — 2 回 run でビット同一 🔵 (対応: NFR-102 / REQ-402)
- **何をテストするか**: 同一入力で `run` を 2 回実行すると、`MultistartResult` がビット同一になること。
- **期待される動作**: `result_a == result_b` (basins / member_starts / promoted / n_diverged /
  is_global_corroborated すべて `==`)。
- **入力値**: 双峰構成を 2 回実行 (新規 engine インスタンスで各回)。
- **期待される結果**: 完全一致。
- **確認ポイント**: union-find (根 index 小)・代表選出 (同点 index 小)・basins ソート (evidence 同点 index 小) の決定論。
- 🔵 信頼性: NFR-102 / REQ-402 / 完了条件「決定論 (2 回でビット同一)」に直接依拠。

---

## 2. 異常系テストケース (発散・全滅)

### TC-A01: 発散 start 除外 + n_diverged カウント 🟡 (対応: TC-201-05 / REQ-102)
- **エラーケースの概要**: 一部 start が chi2=inf (発散) を返すとき、その start を basin から除外し
  `n_diverged` にカウントすること。
- **エラー処理の重要性**: 発散解を basin に混ぜると多峰性判定が壊れる。除外は判別信頼性の前提。
- **入力値**: `InitialValueFakeBackend` で start index の一部 (例 2 本) に chi2=inf を返させる、n_starts=8。
- **不正な理由**: chi2=inf は精密化発散 (非物理・非収束) を表す (CLAUDE.md「失敗は chi2=inf 結果へ変換」)。
- **実際の発生シナリオ**: 極端な摂動初期値で refine が収束しない、GSAS-II 失敗を chi2=inf へ変換した場合。
- **期待される結果**: `result.n_diverged == 2`、basins の `member_starts` の総和集合が発散 2 本を含まない、
  `result.n_starts == 8`。例外は投げない。
- **システムの安全性**: 発散を例外化せず縮退。残 basin は正常に報告。
- **確認ポイント**: 発散判定 (`math.isfinite`)、除外、カウント、非例外化。
- 🟡 信頼性: REQ-102 / TC-201-05 に依拠 (「一部発散」の具体本数はテスト設計の妥当推測)。

### TC-A02: 全滅 (全 start 発散) → 警告 + 空 basins + 元仮説維持 🟡 (対応: TC-201-05 / EDGE-002)
- **エラーケースの概要**: 全 start が発散したとき、警告を出し `basins == ()`、
  `is_global_corroborated == False`、`promoted == ()` を返す (元仮説維持)。
- **エラー処理の重要性**: 全滅時に落ちず、上流 (判別) が元仮説を維持して継続できること。
- **入力値**: 全 start に chi2=inf を返すスタブ、n_starts=8。
- **期待される結果**: `result.basins == ()`、`result.n_diverged == 8`、`result.warnings` 非空
  (全滅を示す文言)、`result.is_global_corroborated is False`、`result.promoted == ()`。
- **システムの安全性**: 例外を投げず縮退値を返す。ledger 提供時も verify True。
- **確認ポイント**: 全滅縮退・警告・元仮説維持・非例外化。
- 🟡 信頼性: EDGE-002 / TC-201-05 / REQ-102 に依拠 (警告文言は実装裁量)。

---

## 3. 境界値テストケース

### TC-BV01: basin_rel_tol 境界 — ちょうど tol での分離/結合 🔵
- **境界値の意味**: `basin_rel_tol` は同一 basin か否かを分ける閾値。境界での挙動を固定する。
- **入力値**: 2 解の正規化相対距離を `tol` ちょうど / `tol` 直下 / `tol` 直上に設定した 3 パターン。
- **境界値選択の根拠**: D3「相対距離 < tol」の**厳密不等号**を検証 (< tol は同一、= tol は別 basin)。
- **期待される結果**: 距離 < tol → 1 basin、距離 == tol → 2 basin、距離 > tol → 2 basin。
- **確認ポイント**: 不等号の向き (strict `<`) の一貫性。境界内外で basin 数が一貫。
- 🔵 信頼性: D3 (相対距離 < tol) に依拠 (= tol の扱いは strict `<` の自然な帰結 🟡 → tdd-red で確定)。

### TC-BV02: N=1 縮退 (摂動なし 1 本) → n_basins=1 🟡 (対応: TC-201-07 / EDGE-101)
- **境界値の意味**: `n_starts == 1` は摂動なしの最小構成 (基準解のみ)。
- **入力値**: `config=MultistartConfig(n_starts=1)`、単峰スタブ (or 任意 backend)。
- **境界値選択の根拠**: `generate_starts` は N=1 で基準 1 組のみ返す (TASK-0027 実装済)。エンジンが
  1 start でも成立し basin=1 になることを確認。
- **期待される結果**: `result.n_starts == 1`、`len(result.basins) == 1`、
  `is_global_corroborated is True`、`n_diverged == 0`、`promoted == ()`。
- **確認ポイント**: 1 本での 0 除算回避 (正規化距離計算・basin 集約)、単一 basin 判定。
- 🟡 信頼性: EDGE-101 / TC-201-07 に依拠 (N=1 でのエンジン挙動は妥当推測)。

### TC-BV03: basin クラスタ空入力 → 空タプル 🔵
- **境界値の意味**: 全滅後などクラスタ入力が空 (収束解 0) のときの縮退。
- **入力値**: `cluster_basins([], basin_rel_tol=1e-2)` (空 Sequence)。
- **期待される結果**: `()` (空タプル)。例外を投げない (`clustering.py` の空入力縮退パターンに整合)。
- **確認ポイント**: 空入力の非例外化 (M0 規約)。
- 🔵 信頼性: clustering.py 空入力縮退 (L172-175) / M0 規約に依拠。

### TC-BV04: 単一収束解 → 1 basin (member_starts 単一) 🔵
- **境界値の意味**: 収束解が 1 個 (発散除外後 1 本残) のときの最小 basin。
- **入力値**: `RefinementResult` 1 個をクラスタ / または n_starts=8 で 7 本発散・1 本収束。
- **期待される結果**: `len == 1`、`member_starts == (<残 index>,)`、代表 = その解、evidence = bic。
- **確認ポイント**: 単一要素 basin の member_starts・代表・evidence。
- 🔵 信頼性: D3 / clustering 単一要素クラスタ挙動に依拠。

### TC-BV05: ledger=None でも動作 (記録スキップ) 🔵
- **境界値の意味**: `ledger` 未提供 (既定 None) でもエンジンが完全に動作すること。
- **入力値**: `MultistartEngine(backend)` (ledger 省略)、双峰構成。
- **期待される結果**: `MultistartResult` が TC-E02 と同一内容で返る (ledger 記録なしでも basins/promoted 不変)。
  例外なし。
- **確認ポイント**: ledger 非依存 (None ガード)、結果の同一性。
- 🔵 信頼性: interfaces.py `ledger: Ledger | None = None` 既定に依拠。

### TC-BV06: BasinInfo / MultistartResult は frozen (不変) 🔵
- **境界値の意味**: 値オブジェクトの不変性 (P2 / コーディング規約 frozen dataclass)。
- **入力値**: 生成した `BasinInfo` / `MultistartResult` のフィールドへ再代入を試みる。
- **期待される結果**: `dataclasses.FrozenInstanceError` が送出される。
- **確認ポイント**: frozen=True の付与。
- 🔵 信頼性: CLAUDE.md 規約 (frozen dataclass) / interfaces.py `@dataclass(frozen=True)` に依拠。

---

## 4. 開発言語・フレームワーク

- 🔵 **プログラミング言語**: Python 3.12。
  - **言語選択の理由**: 既存コードベースが Python 3.12 (src layout + hatchling)。frozen dataclass +
    Protocol の不変値オブジェクト設計に適合。
  - **テストに適した機能**: dataclass の `==` によるビット同一比較 (決定論検証)、
    `dataclasses.FrozenInstanceError` (不変検証)、numpy の合成データ生成。
- 🔵 **テストフレームワーク**: pytest (>=8) + pytest-cov。
  - **選択理由**: リポジトリ標準 (`pyproject.toml [tool.pytest.ini_options]`)。`@pytest.mark.gsas` で
    GSAS-II 依存テストを分離 (本タスクは非依存 → マーカー不要)。
  - **実行環境**: `uv run pytest tests/test_multistart_basin.py tests/test_multistart_engine.py`。
    依存導入は `uv sync --extra gsas`。Lint `uvx ruff check src tests` (line-length 100)。
- 🔵 信頼性: `pyproject.toml` / `CLAUDE.md` (技術スタック) / note.md §5 に依拠。

---

## 5. テストケース実装時の日本語コメント指針 (雛形)

```python
def test_multistart_bimodal_produces_two_basins():
    # 【テスト目的】: 初期値依存で 2 解へ収束する双峰問題で n_basins=2 を確認 (TC-201-03)
    # 【テスト内容】: InitialValueFakeBackend (双峰) + MultistartEngine.run のフルパイプライン
    # 【期待される動作】: basins が 2 件、evidence 昇順、両 basin の chi2/evidence が有限
    # 🔵 信頼性レベル: 受け入れ基準 TC-201-03 に直接依拠

    # 【テストデータ準備】: a<split→chi2=8, a>=split→chi2=12 の 2 吸引域スタブ
    # 【初期条件設定】: n_starts=8、摂動列で半数ずつ各吸引域へ入る split
    backend = InitialValueFakeBackend(mode="bimodal", split=5.5)
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8))

    # 【実際の処理実行】: generate_starts → 各 direct refine → 発散除外 → basin クラスタ
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: basin 数・evidence 昇順・chi2 報告
    # 【検証項目】: n_basins == 2
    # 🔵
    assert len(result.basins) == 2  # 【確認内容】: 双峰が 2 basin に分離
    # 【検証項目】: evidence 昇順
    # 🔵
    assert result.basins[0].evidence <= result.basins[1].evidence  # 【確認内容】: 昇順ソート
```

- frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`、
  決定論は `assert result_a == result_b`、evidence は `pytest.approx` (必要時) を用いる。

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `multistart-basin-engine-requirements.md` §1 (basin クラスタ + MultistartEngine)。
- **参照した入力・出力仕様**: 同 §2.1 (basin.py: results→BasinInfo) / §2.2 (engine.py: run→MultistartResult)。
- **参照した制約条件**: 同 §3 (決定論 NFR-102 / 非破壊 P2 / direct refine D2 / 発散縮退 REQ-102 / ledger NFR-105)。
- **参照した使用例**: 同 §4 (単峰/双峰/昇格/metrics/発散/N=1)。
- **受け入れ基準対応表**:
  | AC | 内容 | 対応テスト |
  |---|---|---|
  | TC-201-02 | 単峰 → n_basins=1・傍証あり | TC-B01, TC-E01 |
  | TC-201-03 | 双峰 → n_basins=2・両 basin chi2/evidence | TC-B02, TC-E02 |
  | TC-201-04 | 複数 basin → Hypothesis 昇格・rank 可能 | TC-E03 |
  | TC-201-05 | 発散除外+カウント、全滅で警告+空 basins | TC-A01, TC-A02 |
  | TC-201-06 | metrics.multistart {n,n_basins,n_diverged} 記録 | TC-E04 |
  | TC-201-07 | N=1 縮退 | TC-BV02 |
  | (完了条件) | 決定論 (2 回でビット同一) | TC-E07 |
  | (D2) | direct refine N 回 | TC-E05 |
  | (NFR-105) | 全操作 ledger 記録 | TC-E06, TC-BV05 |
  | (D3) | 代表=chi2最小 / tol 境界 / 空入力 | TC-B03, TC-BV01, TC-BV03, TC-BV04 |
  | (規約) | frozen 不変 | TC-BV06 |

---

## テストケース数内訳

- **正常系 (§1)**: 7 件 (TC-B01〜B03 [basin] + TC-E01〜E07 のうち正常系 = B01/B02/B03/E01/E02/E03/E04/E05/E06/E07)
  → **basin 正常系 3 (B01-B03)** + **engine 正常系 7 (E01-E07)** = **10 件**
- **異常系 (§2)**: 2 件 (TC-A01 発散除外 / TC-A02 全滅)
- **境界値 (§3)**: 6 件 (TC-BV01 tol 境界 / BV02 N=1 / BV03 空入力 / BV04 単一解 / BV05 ledger=None / BV06 frozen)
- **合計: 18 件** (basin: B01-B03 + BV01/BV03/BV04 = 6 件 / engine: E01-E07 + A01/A02 + BV02/BV05/BV06 = 12 件)

---

## 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 10 / 異常系 2 / 境界値 6 で網羅 (AC TC-201-02〜07 + 決定論 + D2/D3/ledger/frozen)
- 期待値定義: 各ケースに具体値・== / approx の判定方法を明記
- 技術選択: Python 3.12 + pytest 確定 (既存構成)
- 実装可能性: perturb / _UnionFind / BICBackend / Ledger / 初期値依存 FakeBackend で実現可能
- 信頼性レベル: 🔵 支配的 (🟡 は発散本数・N=1 エンジン挙動・tol=境界の細部のみ)
```

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m3-operando TASK-0028` で Red フェーズ (失敗テスト作成) を開始します。
