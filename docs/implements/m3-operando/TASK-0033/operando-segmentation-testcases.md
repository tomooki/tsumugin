# TASK-0033 TDD テストケース定義 — operando/segmentation (FR-316: IC 区間自動分割)

**機能名**: operando-segmentation / **タスクID**: TASK-0033 / **要件名**: m3-operando
**実装対象**: `src/tsumugin/operando/segmentation.py` / **テストファイル**: `tests/test_segmentation.py`
**信頼性**: テストケース全 17 件 (正常系 9 / 異常系 2 / 境界値 6)

> 全パスはプロジェクトルートからの相対パス。信頼性 🔵=資料に直接依拠 / 🟡=妥当な推測 / 🔴=資料にない推測。
> 対象契約: `docs/design/m3-operando/interfaces.py` L287-321。AC: `docs/spec/m3-operando/acceptance-criteria.md`
> TC-206-01〜05/07 (L53-60)。TC-206-06 (Issue #3) は TASK-0031 完了済みで**本タスク対象外**。

---

## 共通テストフィクスチャ方針 🔵

*参照: note.md §5, `tests/test_discrimination.py` / `tests/test_sequential_engine.py` 先例*

- **バックエンド**: `SimulatedBackend` (Ycalc・乱数なし → ビット同一) を主とし、失敗注入/呼び出し記録は
  Fake/Spy バックエンドで行う。GSAS-II 非依存 (マーカー不要)。
- **2 区間合成系列 (`_two_regime_series`)**: 前半フレーム = 単相の `lattice.a` を連続変化 (固溶体)、
  後半フレーム = 端成分 2 相の scale を漸移 (二相)。真の切り替わりフレーム `TRUE_BOUNDARY` を既知にする。
  `FrameSeries(two_theta, np.stack(rows))`。グリッドは smoke 用に粗め (例 `np.arange(15.0, 60.0, 0.1)`)。
- **一様系列 (`_uniform_series`)**: 全フレーム同一相・同一格子 (機構切替なし)。
- **区間コスト評価回数を数える Spy**: `refine` 呼び出しを `(free_params, n_frame相当)` で記録するカウンタ付き
  バックエンドで、メモ化によるキャッシュヒット (再評価なし) を検証する。
- **決定論検証**: `result_a == result_b` (frozen dataclass の `==`)。数値は `pytest.approx`、Mapping は dict 比較。

---

## 1. 正常系テストケース（基本的な動作）

### N1. 2 区間合成データで k=2 採択・境界が真値 ±2 フレーム 🔵 *TC-206-01 / 完了条件1*

- **テスト名**: `test_two_regime_series_adopts_k2_boundary_within_tolerance`
  - **何をテストするか**: 前半固溶体・後半二相の 2 区間合成データで `segment_series` が k=2 を採択し、
    採択境界が真の切り替わりフレーム ±2 に入ること。
  - **期待される動作**: 貪欲挿入 + 粗→細スキャンで境界 1 本を真値近傍に配置。
- **入力値**: `_two_regime_series(true_boundary=T)`, `initial_phases`=単相, `config=SegmentationConfig()`
  - **入力データの意味**: FR-316 が想定する「反応機構が切り替わる operando 系列」の代表。
- **期待される結果**: `result.n_segments == 2`、`len(result.boundaries) == 1`、
  `abs(result.boundaries[0] - T) <= 2`。
  - **期待結果の理由**: 合計コスト (Σbic + β·境界数·ln n) が k=2 で最小になり、境界は機構切替位置に収束する
    (AC TC-206-01)。
- **テストの目的**: 分割の中核機能 (機構境界の自動検出精度) を保証。
  - **確認ポイント**: 境界本数=1、位置誤差 ±2、`evidence_by_k[2] < evidence_by_k[1]`。
- 🔵 *acceptance-criteria.md L53, architecture.md D5 L78-82*

### N2. 一様データで k=1 が最良（過分割しない）🔵 *TC-206-02 / EDGE-004 / 完了条件2*

- **テスト名**: `test_uniform_series_selects_k1_no_oversegmentation`
  - **何をテストするか**: 機構切替のない一様系列で k=1 が最良となり、境界を追加しないこと。
  - **期待される動作**: 境界追加の改善が閾値未満 → k=1 採択。
- **入力値**: `_uniform_series()`, `initial_phases`=単相, `SegmentationConfig()`
  - **入力データの意味**: EDGE-004 (固溶体単区間) の代表。過分割抑止の検証。
- **期待される結果**: `result.n_segments == 1`、`result.boundaries == ()`。
  - **期待結果の理由**: 境界追加で Σbic が有意に減らず、ペナルティ増で total_cost が悪化するため k=1 が最良。
- **テストの目的**: ペナルティ項による過分割抑止を保証。
  - **確認ポイント**: `boundaries` 空、`evidence_by_k[1]` が最小 (存在すれば `evidence_by_k[2] >= evidence_by_k[1]`)。
- 🔵 *acceptance-criteria.md L54, requirements.md EDGE-004 L124*

### N3. k 逐次追加が改善閾値未満で打ち切られる（max_segments まで走らない）🔵 *TC-206-03 / 完了条件3*

- **テスト名**: `test_greedy_insertion_stops_below_improvement_threshold`
  - **何をテストするか**: k を増やしても改善が `improvement_threshold` 未満になった時点で打ち切り、
    `max_segments` まで走らないこと。
  - **期待される動作**: 直前 k からの改善 < 閾値 → その k を採択せず直前 k で確定。
- **入力値**: 真の区間数が 2 の系列 + `SegmentationConfig(max_segments=6, improvement_threshold=10.0)`
  - **入力データの意味**: 打ち切り制御の検証 (無限に分割しない)。
- **期待される結果**: `result.n_segments < config.max_segments`
    (真の系列なら 2)、`evidence_by_k` のキーが `max_segments` まで到達しない
    (例 `max(evidence_by_k) <= result.n_segments + 1` 程度で停止)。
  - **期待結果の理由**: §15-1 の「改善が閾値未満で打ち切り」規約。
- **テストの目的**: 計算量制御と過分割抑止の両立を保証。
  - **確認ポイント**: 探索が打ち切られたこと (最終 k < max_segments)、打ち切り理由が warnings/ledger に残ること。
- 🔵 *acceptance-criteria.md L55, requirements.md REQ-013 L59-62*

### N4. 各分割仮説（k=1,2,…）が Hypothesis として保存され代替閲覧できる 🔵 *TC-206-04 / 完了条件4*

- **テスト名**: `test_partitions_saved_as_hypotheses_and_browsable_by_k`
  - **何をテストするか**: 評価した各 k の分割が `partitions` に `Hypothesis` として保存され、
    `evidence_by_k` で k → 合計コストが閲覧できること。
  - **期待される動作**: k=1..採択k (打ち切り含む) の分割仮説を保持。
- **入力値**: `_two_regime_series()`, `SegmentationConfig()`
  - **入力データの意味**: REQ-014 (代替分割の閲覧・選択) の検証。
- **期待される結果**:
    - `len(result.partitions) >= 2` (少なくとも k=1, k=2)。
    - 各 `partitions[i]` は `Hypothesis` で `id` が `"seg-k{K}-"` 前置、`frame_range == (0, n_frames-1)` (全区間)。
    - `set(result.evidence_by_k.keys())` が評価した k を網羅、値は float の合計コスト。
    - `result.n_segments` に対応する Hypothesis が `partitions` に存在。
  - **期待結果の理由**: D6「各 k の分割を 1 Hypothesis (id=seg-k{K}-XXXX, frame_range=全区間) として保存」。
- **テストの目的**: 分割仮説の保存・代替閲覧契約を保証。
  - **確認ポイント**: id 命名規約、frame_range=全区間、evidence_by_k の網羅性。
- 🔵 *acceptance-criteria.md L56, architecture.md D6 L84-86, design-interview.md D-Q6 L34-38*

### N5. 粗→細 2 段: 細密化で境界が粗スキャンより改善 🟡 *TC-206-05 前半 / 完了条件5*

- **テスト名**: `test_fine_scan_improves_boundary_over_coarse`
  - **何をテストするか**: 採択境界を ±coarse_step で細密スキャン再配置した結果、粗スキャン採択時より
    合計コストが改善 (悪化しない) こと。真値が粗グリッド格子上にない系列で差が出る。
  - **期待される動作**: 粗グリッド採択境界 → ±G 細密再配置で真値へ近づく。
- **入力値**: `true_boundary` を粗グリッド格子からずらした `_two_regime_series()`, `SegmentationConfig(coarse_step=5)`
  - **入力データの意味**: 粗→細 2 段 (NFR-002) の有効性検証。
- **期待される結果**: 細密化後の `boundaries[0]` が粗グリッド格子点よりも真値に近い
    (`abs(fine - T) <= abs(coarse_grid_point - T)`)、かつ細密化後 total_cost ≤ 粗スキャン時 total_cost。
  - **期待結果の理由**: D5「採用境界は ±G の細密スキャンで再配置」。
- **テストの目的**: 2 段スキャンの精度改善を保証。
  - **確認ポイント**: 細密化後コスト ≤ 粗コスト、境界が真値へ近接。
- 🟡 *acceptance-criteria.md L57 (🟡), architecture.md D5 L81*

### N6. 区間コストのメモ化で評価回数が抑制される（spy 検証）🟡 *TC-206-05 後半 / 完了条件5*

- **テスト名**: `test_interval_cost_memoized_reduces_backend_calls`
  - **何をテストするか**: 同一 `(start, end)` 区間のコストがメモ化され、貪欲挿入・細密スキャンで
    再評価されない (backend.refine 呼び出しが重複しない) こと。
  - **期待される動作**: `(start,end)` キャッシュヒット時は refine を再実行しない。
- **入力値**: 呼び出し記録 Spy バックエンド + `_two_regime_series()`, `SegmentationConfig()`
  - **入力データの意味**: メモ化 (D-Q5) による計算量抑制の検証。
- **期待される結果**: Spy が記録した「同一区間 (start,end) に対する refine 系列の実行回数」が 1 回のみ
    (2 回目以降キャッシュヒット)。総 refine 回数がメモ化なし想定 (全候補×フレーム) を有意に下回る。
  - **期待結果の理由**: D-Q5「区間コストはメモ化して貪欲挿入の再評価を回避」。
- **テストの目的**: メモ化の実効性を保証 (性能 NFR-002)。
  - **確認ポイント**: 同一区間の重複評価ゼロ。細密スキャンでもキャッシュ共用。
- 🟡 *acceptance-criteria.md L57, design-interview.md D-Q5 L28-32, architecture.md NFR-002 L128*

### N7. 決定論: 分割結果がビット同一 🔵 *TC-206-07 / 完了条件6*

- **テスト名**: `test_segmentation_deterministic_bit_identical`
  - **何をテストするか**: 同一入力で `segment_series` を 2 回実行し、結果がビット同一であること。
  - **期待される動作**: 乱数/IO/集合反復順に依存しない。
- **入力値**: 同一 `_two_regime_series()` + 同一 `config` で 2 回呼ぶ。
  - **入力データの意味**: NFR-102 再現性の検証。
- **期待される結果**: `r1.boundaries == r2.boundaries`、`r1.n_segments == r2.n_segments`、
    `r1.evidence_by_k == r2.evidence_by_k`、`r1.partitions == r2.partitions` (Hypothesis の `==`)。
  - **期待結果の理由**: 決定論バックエンド + 安定 tie-break (小 index 優先) でビット同一。
- **テストの目的**: 再現性 (NFR-102) を保証。
  - **確認ポイント**: 全フィールド一致、同コスト候補の tie-break 安定性。
- 🔵 *acceptance-criteria.md L60, CLAUDE.md NFR-102*

### N8. Ledger 記録 + verify() が True 🔵 *P2 / NFR-105*

- **テスト名**: `test_ledger_records_boundaries_and_verify_true`
  - **何をテストするか**: 分割境界・打ち切り等が ledger に追記記録され、`ledger.verify()` が True であること。
  - **期待される動作**: `"segmentation.*"` 前置 kind で追記、ハッシュチェーン整合。
- **入力値**: `_two_regime_series()` + `ledger=Ledger()`
  - **入力データの意味**: 非破壊・監査可能性 (P2/NFR-105) の検証。
- **期待される結果**: `result.ledger is` 渡した ledger (または新規)、`result.ledger.verify() is True`、
    追記されたエントリ kind が `"segmentation."` 前置。
  - **期待結果の理由**: P2 追記専用 + NFR-105 ハッシュチェーン。
- **テストの目的**: 監査ログの完全性を保証。
  - **確認ポイント**: verify()==True、境界/evidence が payload に含まれる。
- 🔵 *CLAUDE.md P2/NFR-105, interfaces.py L309*

### N9. fixed_phases 指定で固定相は scale のみ解放される 🔵 *FR-312 連携*

- **テスト名**: `test_fixed_phases_scale_only_free_in_interval_refine`
  - **何をテストするか**: `fixed_phases` を渡すと区間逐次 refine に固定相が連結され、固定相の格子が
    精密化後もビット不変 (scale のみ解放) であること。
  - **期待される動作**: 固定相 index の free_params が `("scale",)` のみ。
- **入力値**: `fixed_phases=(FixedPhaseSpec(CELL_PHASE_PRESETS["Be"], "Be"),)` + `_two_regime_series()`
  - **入力データの意味**: セル固定相込み operando (FR-312 連携) の検証。
- **期待される結果**: 分割は成功し、固定相の `lattice.*` が入力と一致 (ビット不変)、
    bic の n_params が固定相 scale 分のみ増加。
  - **期待結果の理由**: `fixed_free_suffixes(spec) == ("scale",)` 契約。
- **テストの目的**: 固定相組み込みの正しさを保証。
  - **確認ポイント**: 固定相格子不変、free_params が scale のみ。
- 🔵 *note.md §3.6, cell_phases.py fixed_free_suffixes*

---

## 2. 異常系テストケース（エラーハンドリング）

### E1. 全フレーム非有限（backend 全滅）→ 分割なし + warnings 縮退 🟡 *M1 教訓 / ガードレール*

- **テスト名**: `test_all_frames_nonfinite_degrades_to_k1_with_warning`
  - **エラーケースの概要**: 全フレームで refine が chi2=inf (収束失敗) を返す病的ケース。
  - **エラー処理の重要性**: inf/NaN を Σbic・合計コストへ漏らすと貪欲比較が壊れる (M1 教訓)。
- **入力値**: 常に `chi2=inf` を返す FailAllBackend + `_uniform_series()`
  - **不正な理由**: 有限 bic が得られず区間コストが定義できない。
  - **実際の発生シナリオ**: 相モデルが全く合わない/データ品質不良。
- **期待される結果**: 例外を投げず、`result.n_segments == 1`、`result.boundaries == ()`、
    `result.warnings` に非有限縮退の理由文字列を含む。inf を `evidence_by_k` の採択値に据えない。
  - **エラーメッセージの内容**: 「全フレーム非有限のため分割不能」等の説明的 warning。
  - **システムの安全性**: 例外でなく縮退結果を返し上位を止めない。
- **テストの目的**: 非有限漏洩防止 (ガードレール) の保証。
  - **品質保証の観点**: chi2=inf を結果へ変換しガードレールに処理させる CLAUDE.md 不変条件。
- 🟡 *CLAUDE.md 不変条件, note.md §6-7*

### E2. 一部フレーム失敗（chi2=inf）を Σbic に混ぜない 🟡 *非有限漏洩防止*

- **テスト名**: `test_partial_frame_failure_excluded_from_interval_bic`
  - **エラーケースの概要**: 特定フレームのみ refine が inf を返す (局所的失敗)。
  - **エラー処理の重要性**: 区間 Σbic に inf を加算すると当該区間を含む分割が不当に排除される。
- **入力値**: 指定フレームのみ inf を返す FrameFailBackend + `_two_regime_series()`
  - **不正な理由**: 局所的な収束失敗は区間全体を無効化すべきでない。
  - **実際の発生シナリオ**: 一時的な測定欠損/外れフレーム。
- **期待される結果**: 分割は完走し、区間 Σbic は有限フレームのみの和 (inf を除外)、warnings に除外を記録。
    全区間で非有限フレームが混じっても採択境界・n_segments は有限成分で決まる。
  - **システムの安全性**: 有限成分で分割継続、非有限を下流に漏らさない。
- **テストの目的**: 局所失敗に対する頑健性の保証。
  - **品質保証の観点**: discrimination の `n_finite` 管理と同型。
- 🟡 *note.md §3.1・§6-7, discrimination.py 先例*

---

## 3. 境界値テストケース（最小値・最大値・null 等）

### B1. n_frames < 2（1 フレーム）→ 分割不能で k=1 のみ + warnings 🟡 *縮退*

- **テスト名**: `test_single_frame_series_returns_k1_only`
  - **境界値の意味**: 分割には 2 フレーム以上必要。最小フレーム数の下限。
- **入力値**: `FrameSeries(two_theta, intensities[(1, n_points)])`
  - **境界値選択の根拠**: n_frames=1 は境界を挿入できない最小縮退。
- **期待される結果**: `result.n_segments == 1`、`result.boundaries == ()`、warnings に分割不能理由。例外なし。
  - **境界での正確性**: 分割候補が空でも結果契約 (Result 全フィールド) を満たす。
- **テストの目的**: 最小フレーム数での安全動作。
- 🟡 *note.md §6-7 (縮退)*

### B2. coarse_step >= n_frames → 挿入候補なしで k=1 確定 🟡 *境界*

- **テスト名**: `test_coarse_step_ge_nframes_yields_k1`
  - **境界値の意味**: 粗グリッド刻みがフレーム数以上だと有効な境界候補が生成されない。
- **入力値**: `n_frames=4` の系列 + `SegmentationConfig(coarse_step=5)`
  - **境界値選択の根拠**: coarse_step と n_frames の大小関係の境界。
- **期待される結果**: `result.n_segments == 1`、`result.boundaries == ()`、例外なし
    (候補ゼロで貪欲ループが即終了)。
  - **一貫した動作**: 候補生成が空でも通常の k=1 採択経路へ縮退。
- **テストの目的**: グリッド設定の境界での堅牢性。
- 🟡 *note.md §6-7 (縮退), interfaces.py L296 (coarse_step)*

### B3. max_segments 到達で強制停止（改善が続く病的系列）🟡 *安全上限*

- **テスト名**: `test_reaches_max_segments_upper_bound`
  - **境界値の意味**: `max_segments` はセグメント数 k の安全上限。改善が続いても超えない。
- **入力値**: 段差の多い合成系列 + `SegmentationConfig(max_segments=3, improvement_threshold=0.0)`
  - **境界値選択の根拠**: 改善閾値 0 で打ち切りが効かない場合の上限保証。
- **期待される結果**: `result.n_segments <= config.max_segments` (= 3)、
    `max(evidence_by_k.keys()) <= config.max_segments`。
  - **境界での正確性**: 上限で必ず停止 (無限ループしない)。
- **テストの目的**: 安全上限の遵守を保証。
- 🟡 *interfaces.py L297 (max_segments), architecture.md D5*

### B4. ledger=None → 内部で新規生成し結果は同一 🔵 *依存注入省略*

- **テスト名**: `test_ledger_none_generates_internal_and_result_invariant`
  - **境界値の意味**: 依存注入 (ledger) 省略時の既定挙動。
- **入力値**: `ledger=None` と `ledger=Ledger()` の 2 回実行を比較。
  - **境界値選択の根拠**: ledger の有無で分割結果 (boundaries/evidence_by_k/partitions) が変わらないこと。
- **期待される結果**: `result.ledger` は非 None (新規 Ledger)、`verify() is True`、
    boundaries/n_segments/evidence_by_k は ledger 明示時とビット同一。
  - **一貫した動作**: 記録の有無が数値結果に影響しない (先例 TC-BV05 系)。
- **テストの目的**: ledger 依存注入の省略安全性。
- 🔵 *interfaces.py L320, note.md §3.9*

### B5. SegmentationConfig / SegmentationResult の不変性 (frozen) 🔵 *不変データ契約*

- **テスト名**: `test_config_and_result_are_frozen`
  - **境界値の意味**: frozen dataclass 契約 (代入拒否)。
- **入力値**: `SegmentationConfig()` / `SegmentationResult` インスタンスへ属性代入。
  - **境界値選択の根拠**: 不変データ (P2 / コーディング規約) の境界検証。
- **期待される結果**: `with pytest.raises(dataclasses.FrozenInstanceError)` で代入が拒否される。
  - **境界での正確性**: 生成後の状態変更不可。
- **テストの目的**: 不変データ規約の遵守を保証。
- 🔵 *interfaces.py L292/L301 (@dataclass(frozen=True)), CLAUDE.md コーディング規約*

### B6. 改善量が閾値ちょうどのときの打ち切り規約 🟡 *打ち切り境界*

- **テスト名**: `test_improvement_exactly_at_threshold_boundary`
  - **境界値の意味**: 改善量 == `improvement_threshold` の境界での採否 (`<` か `<=` かを 1 つに固定)。
- **入力値**: 改善量が閾値ちょうどになるよう調整した合成系列 + 既定 config。
  - **境界値選択の根拠**: 打ち切り条件「改善 < 閾値で打ち切り」の等号側 (== は打ち切らない=採択) を固定検証。
- **期待される結果**: 改善量 == 閾値のとき当該 k を**採択**する (打ち切りは厳密に閾値未満)。
    採否が決定論的で 2 回実行同一。
  - **一貫した動作**: 境界の内外で採否が反転しない。
- **テストの目的**: 打ち切り閾値の境界仕様を明確化 (tdd-red で `<` 規約を凍結)。
- 🟡 *requirements.md REQ-013 (改善が閾値未満で打ち切り), note.md §6-3*

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12 (uv 管理, src layout + hatchling)。数値は numpy のみ (REQ-403)。
  - **テストに適した機能**: frozen dataclass の `==` によるビット同一比較、型注釈による契約明確化。
- **テストフレームワーク**: pytest (>=8) + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` (testpaths=["tests"])。
    既存テスト (`tests/test_discrimination.py` 等) と統一。
  - **テスト実行環境**: `uv run pytest tests/test_segmentation.py`。GSAS-II 非依存 (SimulatedBackend/Fake/Spy)、
    `gsas` マーカー不要。数値近似は `pytest.approx`、frozen 検証は `dataclasses.FrozenInstanceError`。
- 🔵 *pyproject.toml, tests/conftest.py, CLAUDE.md L21-23*

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下を必ず付す (先例 `tests/test_discrimination.py`):

```python
def test_two_regime_series_adopts_k2_boundary_within_tolerance():
    # 【テスト目的】: 2 区間合成データで k=2 が採択され境界が真値 ±2 に入ることを確認する
    # 【テスト内容】: segment_series を貪欲挿入 + 粗→細スキャンで実行し boundaries を検証
    # 【期待される動作】: n_segments==2、境界 1 本が真値近傍に配置
    # 🔵 acceptance-criteria.md TC-206-01

    # 【テストデータ準備】: 前半固溶体・後半二相の合成系列を真の境界 T で生成する理由 = FR-316 の代表入力
    # 【初期条件設定】: SimulatedBackend (乱数なし)・既定 config
    series = _two_regime_series(true_boundary=T)

    # 【実際の処理実行】: segment_series を呼び出す
    # 【処理内容】: k=1→2 の貪欲挿入 + ±G 細密スキャン
    result = segment_series(backend, series, initial_phases)

    # 【結果検証】: 採択 k と境界位置を検証
    # 【期待値確認】: k=2 かつ境界誤差 ±2
    assert result.n_segments == 2  # 【検証項目】: k=2 採択 🔵
    assert abs(result.boundaries[0] - T) <= 2  # 【検証項目】: 境界 ±2 フレーム 🔵
```

- Given: 【テストデータ準備】【初期条件設定】【前提条件確認】
- When: 【実際の処理実行】【処理内容】
- Then: 【結果検証】【期待値確認】【品質保証】、各 assert に【検証項目】+ 信頼性レベル

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `operando-segmentation-requirements.md` §1 (IC 区間自動分割・貪欲挿入・過分割抑止)
- **参照した入力・出力仕様**: 同 §2 (`segment_series` シグネチャ・`SegmentationConfig`/`SegmentationResult`・
  コスト式 total_cost = Σ interval_bic + β·境界数·ln n)
- **参照した制約条件**: 同 §3 (決定論 NFR-102 / 非破壊 P2 / 非有限漏洩防止 / 後方互換 REQ-404 / メモ化 NFR-002)
- **参照した使用例**: 同 §4 (2 区間反応・一様過分割抑止・EDGE-004・縮退各種)

### AC カバレッジ表

| AC / 完了条件 | 対応テスト | 信頼性 |
|---|---|---|
| TC-206-01 (k=2・境界 ±2) | N1 | 🔵 |
| TC-206-02 / EDGE-004 (k=1・過分割しない) | N2 | 🔵 |
| TC-206-03 (改善閾値打ち切り) | N3, B6 | 🔵🟡 |
| TC-206-04 (分割仮説保存・代替閲覧) | N4 | 🔵 |
| TC-206-05 (粗→細改善 + メモ化抑制) | N5, N6 | 🟡 |
| TC-206-07 (決定論ビット同一) | N7 | 🔵 |
| P2/NFR-105 (ledger 非破壊・verify) | N8, B4 | 🔵 |
| FR-312 連携 (固定相 scale のみ) | N9 | 🔵 |
| ガードレール (非有限漏洩防止) | E1, E2 | 🟡 |
| 縮退・境界 (最小フレーム/グリッド/上限/frozen) | B1, B2, B3, B5 | 🔵🟡 |
| **スコープ外** TC-206-06 (Issue #3 新規ピーク持続) | — (TASK-0031 完了済み) | — |

---

## 品質判定

✅ **高品質**:
- テストケース分類: 正常系 9 / 異常系 2 / 境界値 6 = **17 件**、AC TC-206-01〜05/07 を全網羅 + 縮退/非破壊/frozen を補完
- 期待値定義: 各ケースに具体的期待値 (n_segments / boundaries / evidence_by_k / warnings / verify) を明記
- 技術選択: Python 3.12 + pytest 確定、SimulatedBackend/Fake/Spy で GSAS-II 非依存
- 実装可能性: TASK-0032 の `_refine_interval` / BICBackend / Hypothesis 再利用で確実
- 信頼性レベル: 🔵 主体 (🟡 は粗→細/メモ化/縮退/打ち切り境界の妥当推測のみ、🔴 なし)
