# TASK-0022 公開 API 統合 + E2E + ドキュメント — TDD テストケース定義書

- **機能名**: 公開 API 統合 + 統合 E2E テスト + ドキュメント (M2 総仕上げ)
- **タスクID**: TASK-0022 / **要件名**: m2-sequential
- **テストファイル**: `tests/test_m2_e2e.py` (新規)
- **要件定義**: `docs/implements/m2-sequential/TASK-0022/public-api-integration-requirements.md`
- **タスクノート**: `docs/implements/m2-sequential/TASK-0022/note.md`
- **信頼性サマリー (テストケース)**: 🔵 16 / 🟡 3 / 🔴 0 — 品質評価: 高品質

## テストケース一覧 (全 19 件)

| # | ID | 分類 | 概要 | マーカー | 完了条件/AC | 信頼性 |
|---|-----|------|------|----------|-------------|--------|
| 1 | TC-022-01 | 正常系 | M2 公開シンボルが `from tsumugin import ...` で解決 (型確認) | なし | ① | 🔵 |
| 2 | TC-022-02 | 正常系 | `tsumugin.__all__` に M2 シンボル包含 + 昇順 + M0/M1 後方互換 | なし | ① / REQ-404 | 🔵 |
| 3 | TC-022-03 | 正常系 | TC-108-01(a) 昇温逐次精密化が全フレーム完走・trajectory 長 = n_frames | なし | ② / TC-108-01 | 🔵 |
| 4 | TC-022-04 | 正常系 | TC-108-01(b) changepoint が転移近傍で発火・`search_results` に該当フレーム | なし | ② / TC-108-01 | 🔵 |
| 5 | TC-022-05 | 正常系 | TC-108-01(c) 局所探索で新相採択 → `hypotheses` 系譜へ反映 | なし | ② / TC-108-01 | 🔵 |
| 6 | TC-022-06 | 正常系 | TC-108-01(d) lifecycle に birth/death が記録 | なし | ② / TC-108-01 | 🔵 |
| 7 | TC-022-07 | 正常系 | TC-108-01(e) `estimate_transition` が転移温度を推定 (None でない) | なし | ② / TC-108-01 | 🔵 |
| 8 | TC-022-08 | 正常系 | TC-108-01(f) agent 裁定 `FinalSelectionEngine.decide` → `Decision` | なし | ② / TC-108-01 | 🔵 |
| 9 | TC-022-09 | 正常系 | TC-108-01(g) 永続 ledger `verify()` True + **再オープン** verify True | なし | ② / TC-108-01 | 🔵 |
| 10 | TC-022-10 | 正常系 | TC-108-01(h) `Trajectory.to_csv` 書き出し・ヘッダ + n_frames 行 | なし | ② / TC-108-01 | 🔵 |
| 11 | TC-022-11 | 正常系 | TC-108-02 @gsas GSASIIBackend 3 フレーム逐次 smoke が完走 | @gsas | ③ / TC-108-02 | 🔵 |
| 12 | TC-022-12 | 異常系 | 空フレーム列 → 空トラジェクトリ・例外なし | なし | EDGE-001 | 🔵 |
| 13 | TC-022-13 | 異常系 | 永続 ledger 破損 → 再オープンで `LedgerIntegrityError` | なし | EDGE-003 | 🔵 |
| 14 | TC-022-14 | 異常系 | agent 裁定対象ゼロ → accept なし + エスカレーションのみ | なし | EDGE-004 | 🔵 |
| 15 | TC-022-15 | 境界値 | 決定論: 2 回実行で trajectory / CSV バイト列がビット同一 | なし | REQ-402 | 🔵 |
| 16 | TC-022-16 | 境界値 | 単一フレーム → 長さ 1 のトラジェクトリ (単発解析等価) | なし | EDGE-101 | 🔵 |
| 17 | TC-022-17 | 境界値 | changepoint ゼロ → 局所木探索が一度も呼ばれない (`search_results` 空) | なし | EDGE-104 | 🔵 |
| 18 | TC-022-18 | 境界値 | README の M2 使用例コードが実際に動作する | なし | ⑤ | 🟡 |
| 19 | TC-022-19 | 境界値 | TC-108-03 合成 100 フレーム (changepoint なし) が 60 秒以内 | なし | TC-108-03 / NFR-001 | 🟡 |

> **検証内訳**: 正常系 11 / 異常系 3 / 境界値 5。うち `@gsas` 1 件 (TC-022-11、GSAS-II 未導入環境は `tests/conftest.py` が自動 skip)。
> **非テスト検証項目 (verify-complete で担保、テストケース化しない)**: カバレッジ 90% 以上 (`uv run pytest --cov=tsumugin`)、
> ruff clean (`uvx ruff check src tests`) = 完了条件④; `README.md` M2 節文面 / `docs/dev/context.md` / `reports/verification.md` の内容整合 = 完了条件⑤。

---

## 共通テストデータ・前提 (`tests/test_sequential_engine.py` / `tests/test_m1_e2e.py` の慣習を踏襲)

```python
# 【観測グリッド】: 全候補ピークが収まる 15–60° / step 0.02。tree.py と同較正 (clustering の bin 較正上必須)。🔵
GRID = np.arange(15.0, 60.0, 0.02)
# 【高速グリッド】: 100 フレーム性能 smoke 用の粗い小グリッド (changepoint 非発火・実行時間抑制)。🟡
GRID_FAST = np.arange(15.0, 40.0, 0.05)

def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンス (格子定数 a を変えるとピーク位置が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)

def _refs(phases) -> set[str]:
    return {p.phase_ref for p in phases}
```

- **E2E は実バックエンドを使う** (統合の裏取りが目的): `SimulatedBackend` (マーカー無し) / `GSASIIBackend` (`@pytest.mark.gsas`)。
- **昇温 + 相転移合成データ (TC-108-01 用)**: 前半フレームは主相 A のみ (熱膨張で格子 a を線形増加)、
  後半フレームで新相 B を出現 (または A を消失) させた `(n_frames, n_points)` 強度行列を `SimulatedBackend.simulate`
  で組み、`FrameSeries(GRID, intensities, axis_values=temps, axis_kind="temperature",
  channels=(ExternalChannel("temperature", {i: T_i}),))` を構築する。転移は 3 フレーム以上継続させ lifecycle
  ヒステリシス (N=3) を確定させる。相分率が 0→1 に単調変化するよう scale を設計し `estimate_transition` を発火させる。
- **module スコープ fixture** (`warming_run`): TC-108-01 の一気通貫パイプラインを **1 回だけ**実行し、
  frozen な `SequentialResult` と永続ファイルパスを正常系 TC-022-03〜10 で読み取り専用共有する (M1 `ab_result` の範)。
- **@gsas** は `tests/conftest.py::pytest_collection_modifyitems` が未導入環境で自動 skip。本環境は GSAS-II 導入済みで実行。
- 決定論 (TC-022-15) は `==` ビット同一、物理量は `pytest.approx`、非有限漏洩は `math.isfinite`。

---

## 1. 正常系テストケース（基本的な動作）

### TC-022-01: M2 公開シンボルのトップレベル再エクスポート

- **テスト名**: `test_m2_public_symbols_are_reexported`
  - **何をテストするか**: `from tsumugin import SequentialEngine, SequentialConfig, FrameSeries, Trajectory, ExternalChannel, PhaseLifecycle, PersistentLedger, PersistentSnapshotStore, FinalSelectionEngine, ReviewQueue, Decision, detect_escalations, detect_changepoint, estimate_transition, fit_thermal_baseline` が例外なく解決し、各シンボルが期待の型 (class / dataclass / 関数) であること。
  - **期待される動作**: トップレベル `tsumugin` 名前空間から M2 中核シンボルへ到達できる。
- **入力値**: `import tsumugin` および上記 from-import 文 (引数なし)。
  - **入力データの意味**: 完了条件①「`from tsumugin import SequentialEngine, ...` で M2 API 利用可能」の直接検証。M1 `test_m1_public_symbols_are_reexported` と同じ公開面確認パターン。
- **期待される結果**: 全 import が成功。`SequentialEngine`/`FinalSelectionEngine`/`LifecycleTracker`/`PersistentLedger`/`PersistentSnapshotStore`/`ReviewQueue` は `inspect.isclass` True、`SequentialConfig`/`FrameSeries`/`Trajectory`/`ExternalChannel`/`PhaseLifecycle`/`Decision`/`ThermalBaseline`/`TransitionEstimate` は `dataclasses.is_dataclass` True、`detect_changepoint`/`estimate_transition`/`fit_thermal_baseline`/`detect_escalations` は `callable`。トップレベルはサブパッケージ実体の re-export (`tsumugin.SequentialEngine is tsumugin.sequential.SequentialEngine` 等)。
  - **期待結果の理由**: サブパッケージ側では re-export 済みだが、トップレベルへの昇格が本タスクの中核作業。
- **テストの目的**: 公開 API 統合 (完了条件①) の達成確認。
  - **確認ポイント**: 逐次/選択/永続/model 拡張の各パッケージから代表シンボルが漏れなく昇格されていること。
- 🔵 信頼性: 要件定義 §2.1 / 完了条件① / `tests/test_m1_e2e.py::test_m1_public_symbols_are_reexported` に直接依拠

### TC-022-02: `__all__` への追記・昇順ソート維持・M0/M1 後方互換

- **テスト名**: `test_m2_symbols_in_dunder_all_and_sorted`
  - **何をテストするか**: 昇格した M2 シンボルが `tsumugin.__all__` に含まれ、`__all__` が昇順ソートを維持し、既存 M0/M1 の 27 シンボルが 1 つも削除・改名されていないこと。
  - **期待される動作**: `__all__` が M0 + M1 + M2 を統合しアルファベット昇順のまま。
- **入力値**: `tsumugin.__all__` (リスト)。
  - **入力データの意味**: 既存 `__init__.py` の「`__all__` はソート維持」慣習 (M1 `test_m1_symbols_in_dunder_all_and_sorted` が固定) と REQ-404 (後方互換) の遵守確認。
- **期待される結果**: `_M2_PROMOTED_SYMBOLS <= set(tsumugin.__all__)` かつ `_M0M1_PUBLIC_SYMBOLS <= set(tsumugin.__all__)` (削除なし)、`list(tsumugin.__all__) == sorted(tsumugin.__all__)`、`all(hasattr(tsumugin, name) for name in tsumugin.__all__)` (実属性との乖離なし)。
  - **期待結果の理由**: 公開面の一貫性・可読性の維持と後方互換 (REQ-404)。
- **テストの目的**: 公開面の配線・規約遵守・非破壊の確認。
  - **確認ポイント**: M0/M1 の既存 27 シンボルが全て残存 (後方互換維持)。
- 🔵 信頼性: 要件定義 §2.1 / REQ-404 / 既存 `src/tsumugin/__init__.py` の `__all__` 慣習に直接依拠

### TC-022-03: TC-108-01(a) — 昇温逐次精密化が全フレーム完走

- **テスト名**: `test_e2e_warming_sequence_completes_all_frames` (fixture `warming_run`)
  - **何をテストするか**: 昇温 + 相転移合成 `FrameSeries` に対し `SequentialEngine(...).run(series, initial_phases)` が例外なく完走し `SequentialResult` を返すこと。`trajectory.records` の長さが `series.n_frames` に一致。
  - **期待される動作**: frame0 staged → 後続 warm start direct → changepoint → lifecycle → Trajectory 組立の単一パスが公開 API 経由で完走。
- **入力値**: 昇温 + 相転移合成データ (前半 A のみ / 後半 A+B)、`candidates=[PHASE_A, PHASE_B]`、`ledger=PersistentLedger(tmp)`、`snapshots=PersistentSnapshotStore(tmp2)`。
  - **入力データの意味**: 完了条件②「TC-108-01 一気通貫 E2E」のパイプライン完走部分の直接検証。
- **期待される結果**: `isinstance(result, SequentialResult)`、`len(result.trajectory.records) == series.n_frames`、各 `FrameRecord.rwp` が有限または None (非有限漏洩なし)。
  - **期待結果の理由**: 逐次精密化 (REQ-001) がフレーム列全長で破綻しないことが一気通貫の前提。
- **テストの目的**: E2E 統合 (完了条件②) の逐次精密化段の完走確認。
  - **確認ポイント**: 公開 `from tsumugin import SequentialEngine` 経由で TASK-0019 と同一結果が得られること。
- 🔵 信頼性: 完了条件② / 受け入れ基準 TC-108-01 / `tests/test_sequential_engine.py` に直接依拠

### TC-022-04: TC-108-01(b) — changepoint が転移近傍で発火

- **テスト名**: `test_e2e_changepoint_fires_near_transition` (fixture `warming_run`)
  - **何をテストするか**: 相転移を仕込んだフレーム近傍で少なくとも 1 つの `FrameRecord.changepoint is True` になり、`result.search_results` に該当 frame_index のキーが存在すること。
  - **期待される動作**: 複合指標 (Rwp 跳ね / 格子微分 / 新規未マッチ) のロバスト z が転移フレームで発火し局所探索が起動。
- **入力値**: `warming_run` の `result`。
  - **入力データの意味**: 完了条件②「changepoint → 局所探索」の結線検証 (REQ-003/101)。
- **期待される結果**: `any(r.changepoint for r in result.trajectory.records)` が True、発火フレームの `changepoint_reasons` が非空、`result.search_results` が非空 (キーは発火 frame_index)。
  - **期待結果の理由**: 転移という相構成変化を changepoint が捉え、その場で局所木探索を起動するのが設計 (D3)。
- **テストの目的**: changepoint 検出 + 局所探索起動の E2E 結線確認。
  - **確認ポイント**: 非 changepoint フレームでは木探索が起動しないこと (EDGE-104 と対をなす)。
- 🔵 信頼性: 完了条件② / TC-108-01 / REQ-003/101 / `tests/test_changepoint.py` に直接依拠

### TC-022-05: TC-108-01(c) — 局所探索で新相が採択され系譜へ反映

- **テスト名**: `test_e2e_new_phase_adopted_into_hypotheses` (fixture `warming_run`)
  - **何をテストするか**: changepoint 局所探索の結果 evidence 改善時に新相構成が採択され、`result.hypotheses` に転移前と異なる相集合の系譜が含まれること。
  - **期待される動作**: 転移前は {A}、転移後は {A,B} (または {B}) の系譜が `hypotheses` に登録され、frame_range が付与される。
- **入力値**: `warming_run` の `result`。
  - **入力データの意味**: 完了条件②「局所探索で新相」の直接検証 (REQ-101 / D3)。
- **期待される結果**: `result.hypotheses` が非空、採択された系譜のいずれかの相集合に "B" (新相) が含まれる。少なくとも 2 種類の相集合が系譜に現れる (転移の反映)。
  - **期待結果の理由**: 相構成の時間変化を系譜として非破壊に記録するのが FR-304/305。
- **テストの目的**: 新相採択の系譜反映 (完了条件②) の確認。
  - **確認ポイント**: 採択・棄却が理由付きで ledger 記録されること (TC-022-09 と連動)。
- 🔵 信頼性: 完了条件② / TC-108-01 / REQ-101 / architecture.md D3 に直接依拠

### TC-022-06: TC-108-01(d) — lifecycle に birth/death が記録

- **テスト名**: `test_e2e_lifecycle_birth_death_recorded` (fixture `warming_run`)
  - **何をテストするか**: `result.trajectory.lifecycles` に相ごとの `PhaseLifecycle` が入り、新相 B の `birth_frame` (または消失相の `death_frame`) が非 None で妥当なフレーム番号であること。
  - **期待される動作**: ヒステリシス (N=3) で確定した birth/death が lifecycle に反映。
- **入力値**: `warming_run` の `result`。
  - **入力データの意味**: 完了条件②「lifecycle」の直接検証 (REQ-004/201)。
- **期待される結果**: `"B" in result.trajectory.lifecycles`、`result.trajectory.lifecycles["B"].birth_frame is not None` かつ転移フレーム近傍。`confidence` が [0,1]。
  - **期待結果の理由**: 相の出現/消滅を点滅抑制しつつ確定するのが FR-305。
- **テストの目的**: lifecycle 追跡の E2E 結線確認。
  - **確認ポイント**: birth_frame が転移を仕込んだフレーム以降であること。
- 🔵 信頼性: 完了条件② / TC-108-01 / REQ-004/201 / `tests/test_lifecycle.py` に直接依拠

### TC-022-07: TC-108-01(e) — 転移温度が推定される

- **テスト名**: `test_e2e_transition_temperature_estimated` (fixture `warming_run`)
  - **何をテストするか**: トラジェクトリの温度軸と相分率から `estimate_transition(temperatures, fractions, phase_ref="B")` が `TransitionEstimate` (onset / midpoint が None でない) を返すこと。
  - **期待される動作**: 相分率シグモイド遷移の補間から転移温度 onset/midpoint±σ を算出。
- **入力値**: `warming_run` の trajectory から抽出した温度列と相 B の分率列。
  - **入力データの意味**: 完了条件②「転移温度」の直接検証 (REQ-008 / FR-323)。
- **期待される結果**: 戻り値が `None` でなく、`estimate.onset` と `estimate.midpoint` が有限値で `onset <= midpoint` (appearing 方向)、`estimate.direction == "appearing"`。
  - **期待結果の理由**: 明瞭な相出現データでは転移温度が推定可能 (推定不能な曖昧データのみ None)。
- **テストの目的**: 転移温度推定の E2E 結線確認。
  - **確認ポイント**: 温度チャネル (ExternalChannel) の同期が trajectory へ正しく伝播していること。
- 🔵 信頼性: 完了条件② / TC-108-01 / REQ-008 / `tests/test_thermal.py` に直接依拠

### TC-022-08: TC-108-01(f) — agent 裁定が Decision を返す

- **テスト名**: `test_e2e_agent_final_selection_decides` (fixture `warming_run`)
  - **何をテストするか**: 転移フレームの局所探索結果 (`SearchResult`) に `FinalSelectionEngine(mode="agent").decide(sr)` を適用し `Decision` を返すこと。裁定が根拠付きで ledger に記録されること。
  - **期待される動作**: agent モードで明確な最良仮説なら自動 accepted、僅差競合等なら暫定裁定 + Review Queue 通知。
- **入力値**: `warming_run` の `result.search_results` の代表 `SearchResult`、`FinalSelectionEngine(mode="agent", ledger=..., queue=ReviewQueue())`。
  - **入力データの意味**: 完了条件②「agent 裁定」の直接検証 (REQ-013/014/102)。
- **期待される結果**: `isinstance(decision, Decision)`、`decision.mode == "agent"`、`decision.rationale` が非空文字列 (定量根拠を含む)。accepted なら `decision.accepted.accepted_by == "agent"`。ledger に裁定エントリが追記される。
  - **期待結果の理由**: 単一 API 経由でのみ accepted 化し根拠を残すのが FR-402。
- **テストの目的**: 最終選択エンジンの E2E 結線確認。
  - **確認ポイント**: `decide` が `SearchResult` を破壊しない (D5)。
- 🔵 信頼性: 完了条件② / TC-108-01 / REQ-013/014/102 / `tests/test_selection.py` に直接依拠

### TC-022-09: TC-108-01(g) — 永続 ledger の verify() True + 再オープン検証

- **テスト名**: `test_e2e_persistent_ledger_verify_and_reopen` (fixture `warming_run`)
  - **何をテストするか**: 実行後 `result.ledger.verify() is True` かつ `entries` 非空。注入した `PersistentLedger` のファイルを **新インスタンスで再オープン**して `verify() is True`、エントリ数が一致すること。
  - **期待される動作**: 全操作が追記専用ハッシュチェーン JSONL に理由付きで記録され、プロセス跨ぎで改竄検知が機能。
- **入力値**: `warming_run` の `result.ledger` と永続 ledger パス。再オープン: `PersistentLedger(same_path)`。
  - **入力データの意味**: 完了条件②「永続 ledger verify() True」の直接検証 (REQ-010 / NFR-105/201)。
- **期待される結果**: `result.ledger.verify() is True`、`len(result.ledger.entries) > 0`、`PersistentLedger(path).verify() is True`、再オープン後の entries 数が実行時と一致。
  - **期待結果の理由**: 永続化後も追記専用性・ハッシュチェーンが保たれ監査可能 (P2 / NFR-105)。
- **テストの目的**: 永続化 + 監査の E2E 結線確認。
  - **確認ポイント**: 空 ledger の自明 True でないこと (entries 非空)。
- 🔵 信頼性: 完了条件② / TC-108-01 / REQ-010 / NFR-105/201 / `tests/test_persistent_store.py` に直接依拠

### TC-022-10: TC-108-01(h) — Trajectory.to_csv の書き出し

- **テスト名**: `test_e2e_trajectory_to_csv_written` (fixture `warming_run`)
  - **何をテストするか**: `result.trajectory.to_csv(path)` が書き出しパスを返し、ファイルが実在し、ヘッダ 1 行 + データ n_frames 行を持つこと。
  - **期待される動作**: stdlib csv でトラジェクトリ (フレーム軸値・温度・相ごとの scale/格子・Rwp/GOF・changepoint・lifecycle) を CSV 化。
- **入力値**: `warming_run` の `result.trajectory`、`tmp_path / "traj.csv"`。
  - **入力データの意味**: 完了条件②「CSV 出力」の直接検証 (REQ-005)。
- **期待される結果**: `written == str(path)`、`Path(written).exists()`、CSV 行数 == `1 + series.n_frames` (ヘッダ + フレーム行)、非有限値セルは空欄。
  - **期待結果の理由**: 外部委譲出口 (REQ-009) として CSV が機械可読で完全であること。
- **テストの目的**: トラジェクトリ CSV 出力の E2E 結線確認。
  - **確認ポイント**: 失敗フレーム (rwp=None) のセルが空欄化されること (M1 教訓)。
- 🔵 信頼性: 完了条件② / TC-108-01 / REQ-005 / `tests/test_trajectory.py` に直接依拠

### TC-022-11: TC-108-02 @gsas — GSASIIBackend 3 フレーム逐次 smoke

- **テスト名**: `test_e2e_gsasii_three_frame_sequential_smoke` (`@pytest.mark.gsas`)
  - **何をテストするか**: `SequentialEngine(GSASIIBackend()).run(series_3frames, initial_phases)` が実バックエンドで例外なく完走し `SequentialResult` を返すこと。
  - **期待される動作**: GSAS-II 実精密化を用いた短い逐次解析が破綻しない (統合 smoke)。
- **入力値**: `GSASIIBackend().simulate([...], GRID)` で作る **3 フレーム** `FrameSeries`。GSAS-II が確実に計算できる立方 (CIF 簡約) 相を使用。
  - **入力データの意味**: 完了条件③「TC-108-02 3 フレーム smoke」の直接検証。
- **期待される結果**: `len(result.trajectory.records) == 3`、`result.ledger.verify() is True`、例外なし。
  - **期待結果の理由**: バックエンド交換 (P7) しても逐次パイプラインが同契約で完走すること。
- **テストの目的**: 実バックエンド統合 (完了条件③) の完走確認。
  - **確認ポイント**: GSAS-II 特有の失敗が chi2=inf 変換され逐次全体をクラッシュさせないこと (EDGE-002 相当)。
- 🔵 信頼性: 完了条件③ / TC-108-02 / `tests/test_gsasii_backend.py` の @gsas パターンに直接依拠。GSAS-II 未導入環境は自動 skip

---

## 2. 異常系テストケース（エラーハンドリング・縮退動作）

### TC-022-12: 空フレーム列 → 空トラジェクトリへ縮退

- **テスト名**: `test_e2e_empty_series_degrades_gracefully`
  - **エラーケースの概要**: `intensities` が `(0, n_points)` の空フレーム列で `run` を呼んでも例外を投げず、空トラジェクトリを返す。
  - **エラー処理の重要性**: 上流が空データを渡してもパイプラインがクラッシュしない (M0/M1 縮退規約の踏襲)。
- **入力値**: `FrameSeries(GRID, np.empty((0, GRID.size)))`、`SequentialEngine(SimulatedBackend()).run(series, [PHASE_A])`。
  - **不正な理由**: フレームゼロは解析対象がない縮退入力。
  - **実際の発生シナリオ**: フレームフィルタで全フレームが除外された、または未計測のシーケンス。
- **期待される結果**: 例外を投げず `result.trajectory.records == ()`、`result.trajectory.lifecycles == {}`、`result.ledger.verify() is True`、`result.search_results == {}`。
  - **エラーメッセージの内容**: 例外を出さない (EDGE-001: 空トラジェクトリを返す契約)。
  - **システムの安全性**: 空入力でも trajectory/ledger が健全な状態を保つ。
- **テストの目的**: 縮退動作 (EDGE-001) の E2E 確認。
  - **品質保証の観点**: 境界的な空入力での堅牢性を統合レベルで保証。
- 🔵 信頼性: 要件定義 §4.3 / 受け入れ基準 EDGE-001 / `tests/test_sequential_engine.py` (空 series 縮退) に直接依拠

### TC-022-13: 永続 ledger 破損 → 再オープンで LedgerIntegrityError

- **テスト名**: `test_e2e_corrupted_persistent_ledger_raises_on_reopen`
  - **エラーケースの概要**: 追記済み JSONL ledger のあるエントリを改竄 (ハッシュ不整合) してから `PersistentLedger(path)` で再オープンすると `LedgerIntegrityError` を送出する。ファイルは修復・上書きしない。
  - **エラー処理の重要性**: 改竄・破損を黙って修復すると監査証跡の信頼性が崩れる (P2 / NFR-105)。
- **入力値**: 正常に追記した永続 ledger ファイルの 1 行の payload を書き換え、`PersistentLedger(path)` を再構築。
  - **不正な理由**: ハッシュチェーンが切れたファイル = 改竄されたか破損した ledger。
  - **実際の発生シナリオ**: ディスク破損・外部プロセスによる不正な書き換え・部分書き込み。
- **期待される結果**: `pytest.raises(LedgerIntegrityError)`。例外送出後もファイル内容は不変 (修復・上書きしない)。
  - **エラーメッセージの内容**: ハッシュ不整合を検出した旨の明示エラー。
  - **システムの安全性**: 破損を検出して明示的に停止し、証跡を保全する。
- **テストの目的**: 永続化の改竄検知 (EDGE-003) の確認。
  - **品質保証の観点**: 非破壊性・監査可能性の破壊耐性を保証。
- 🔵 信頼性: 要件定義 §4.3 / 受け入れ基準 EDGE-003 / REQ-401 / `tests/test_persistent_store.py` に直接依拠

### TC-022-14: agent 裁定対象ゼロ → accept なし + エスカレーションのみ

- **テスト名**: `test_e2e_agent_no_candidates_escalates_only`
  - **エラーケースの概要**: 裁定対象仮説がゼロ (空 `SearchResult` = 候補ゼロ探索の結果) の `SearchResult` に `FinalSelectionEngine(mode="agent").decide` を適用すると、accepted 化せずエスカレーションのみ返す。
  - **エラー処理の重要性**: 裁定材料が無い状態で誤って accept すると誤同定を確定させてしまう。
- **入力値**: `HypothesisTreeSearch(SimulatedBackend()).search(GRID, y, [])` で得た空 `SearchResult`、`FinalSelectionEngine(mode="agent", queue=ReviewQueue())`。
  - **不正な理由**: ranked が空 = 裁定対象なしの縮退状態。
  - **実際の発生シナリオ**: 候補フィルタで全相が除外され探索が空になったフレーム。
- **期待される結果**: `decision.accepted is None`、エスカレーション (または空裁定) が返り、`FinalSelectionEngine.accepted` に新規 accepted が増えない。例外なし。
  - **エラーメッセージの内容**: 例外でなく Decision 構造で「accept なし」を表現。
  - **システムの安全性**: 材料ゼロで裁定を確定させない。
- **テストの目的**: 裁定縮退 (EDGE-004) の E2E 確認。
  - **品質保証の観点**: 誤 accept 防止による同定信頼性の担保。
- 🔵 信頼性: 要件定義 §4.3 / 受け入れ基準 EDGE-004 / TC-107-08 / `tests/test_selection.py` に直接依拠

---

## 3. 境界値テストケース（決定論・最小フレーム・非発火・ドキュメント整合・性能）

### TC-022-15: 決定論 — 2 回実行で trajectory / CSV がビット同一

- **テスト名**: `test_e2e_deterministic_trajectory_and_csv_bitwise_identical`
  - **境界値の意味**: 同一入力・同一設定での 2 回実行結果が「ビット同一」であること (再現性の下限保証)。
  - **境界値での動作保証**: 乱数不使用・中央値/MAD・canonical JSON ソート・ID 決定論採番により全出力が完全再現。
- **入力値**: 同一の昇温 + 相転移合成データ・同一 `SequentialConfig` で `run` を独立に 2 回実行し、それぞれ `to_csv` の書き出しバイト列を取る (毎回 backend/engine を独立生成)。
  - **境界値選択の根拠**: REQ-402「同一入力・同一設定で全出力ビット同一」の直接検証。物理量近似ではなく `==` 完全一致の境界。
  - **実際の使用場面**: 解析の再実行・監査・回帰比較で結果の同一性が前提となる。
- **期待される結果**: 2 回の CSV バイト列が `==` で完全一致。`records` の frame_index / phases 相集合 / changepoint フラグ列も一致。
  - **境界での正確性**: 浮動小数の非決定性・辞書順の揺れ・ID 採番の揺れが混入しない。
  - **一貫した動作**: 実行回数に依存しない出力。
- **テストの目的**: 決定論 (REQ-402 / NFR-102) の統合確認。
  - **堅牢性の確認**: 公開 API 経由でも決定論が崩れないこと。
- 🔵 信頼性: 受け入れ基準 REQ-402 / NFR-102/202 / `tests/test_sequential_engine.py` (SE-B02 決定論) に直接依拠

### TC-022-16: 単一フレーム → 長さ 1 のトラジェクトリ

- **テスト名**: `test_e2e_single_frame_sequence`
  - **境界値の意味**: フレーム 1 = シーケンスの最小非空ケース。単発解析と等価な結果。
  - **境界値での動作保証**: 最小フレーム数でも run が長さ 1 のトラジェクトリを破綻なく返す。
- **入力値**: 単一フレームの `FrameSeries` (主相 A のみ)、`SequentialEngine(SimulatedBackend()).run(series, [PHASE_A])`。
  - **境界値選択の根拠**: EDGE-101「単一フレーム → 単発解析等価 + 長さ 1 のトラジェクトリ」の直接検証。フレーム数の下限 (非ゼロ最小)。
  - **実際の使用場面**: 単一パターンをシーケンシャル API で扱う最小ケース。
- **期待される結果**: `len(result.trajectory.records) == 1`、`result.trajectory.records[0].changepoint is False` (履歴不足で発火しない)、`result.ledger.verify() is True`、`result.search_results == {}`。
  - **境界での正確性**: 直近窓不足でも changepoint 判定が破綻しない。
  - **一貫した動作**: 空 (TC-022-12) と複数フレーム (TC-022-03) の中間で連続的に動作。
- **テストの目的**: 最小フレーム境界 (EDGE-101) の E2E 確認。
  - **堅牢性の確認**: 極小入力での安定動作。
- 🔵 信頼性: 受け入れ基準 EDGE-101 / `tests/test_sequential_engine.py` に直接依拠

### TC-022-17: changepoint ゼロ → 局所木探索が呼ばれない

- **テスト名**: `test_e2e_no_changepoint_skips_local_search`
  - **境界値の意味**: 相構成不変 (熱膨張のみ) のシーケンス = changepoint 非発火の境界。
  - **境界値での動作保証**: 発火が無い区間で局所木探索を一度も呼ばず (コスト集中の設計、FR-304)。
- **入力値**: 相構成不変で格子のみ線形膨張する合成 `FrameSeries` (新相なし)、`SequentialEngine(SimulatedBackend()).run(series, [PHASE_A])`。
  - **境界値選択の根拠**: EDGE-104「changepoint ゼロ → 木探索は一度も呼ばれない」の直接検証。呼び出し回数 (`search_results` の空) で検証。
  - **実際の使用場面**: 相転移のない等温・単純昇温シーケンス。
- **期待される結果**: `all(not r.changepoint for r in result.trajectory.records)`、`result.search_results == {}` (局所探索未起動)、trajectory 長 == n_frames。
  - **境界での正確性**: 熱膨張 (連続変化) を changepoint と誤検出しない。
  - **一貫した動作**: 発火あり (TC-022-04) と対をなし、非発火時のコスト回避を保証。
- **テストの目的**: 局所探索の条件起動 (EDGE-104 / REQ-101) の E2E 確認。
  - **堅牢性の確認**: 非探索区間の軽量性 (NFR-103) の前提保証。
- 🔵 信頼性: 受け入れ基準 EDGE-104 / REQ-101 / `tests/test_sequential_engine.py` に直接依拠

### TC-022-18: README の M2 使用例コードが実際に動作する

- **テスト名**: `test_readme_m2_example_executes`
  - **境界値の意味**: ドキュメント (README の M2 使用例) と実装の境界整合。使用例が実行可能であることの下限保証。
  - **境界値での動作保証**: README に記載する 10-15 行の最小使用例と同等のコードが例外なく完走し期待の型を返す。
- **入力値**: README「使い方 (M2)」節に記載する最小例と同等のコード (公開 import → `SimulatedBackend` で昇温合成 → `SequentialEngine(...).run(...)` → `trajectory.to_csv(...)`)。
  - **境界値選択の根拠**: 完了条件⑤「README に M2 使用例 (10-15 行、実行確認)」の実効性検証。ドキュメント成果物のうち唯一コードで自動検証可能な部分。
  - **実際の使用場面**: 新規ユーザーが README を写経して最初のシーケンシャル解析を走らせる場面。
- **期待される結果**: 使用例コードが例外なく実行され、`SequentialResult` が得られ `to_csv` が書き出しパスを返す (存在するファイル)。公開シンボル名・シグネチャが README と実装で一致。
  - **境界での正確性**: import 名・引数名の乖離を防止。
  - **一貫した動作**: README 更新でコード例が壊れたら本テストが検知。
- **テストの目的**: ドキュメントと公開 API の同期 (完了条件⑤) を回帰防止。
  - **堅牢性の確認**: 使用例が公開 API の実シグネチャに追従していること。
- 🟡 信頼性: 完了条件⑤ / 要件定義 §2.4 からの妥当な推測 (README 文面は Green で確定、コードによる検証のみテスト化)。M1 `test_readme_m1_example_executes` の範

### TC-022-19: TC-108-03 — 合成 100 フレーム (changepoint なし) が 60 秒以内

- **テスト名**: `test_e2e_hundred_frames_within_time_budget`
  - **境界値の意味**: 100 フレーム = CI 実用性を測る性能境界。changepoint なし (非探索区間) での 1 パス処理時間。
  - **境界値での動作保証**: 非探索区間は warm start + direct refine で軽量に処理される (NFR-103)。
- **入力値**: 相構成不変で格子のみ緩やかに膨張する **100 フレーム**・粗グリッド (`GRID_FAST`) の合成 `FrameSeries`、`SequentialEngine(SimulatedBackend()).run(...)`。実行時間を計測。
  - **境界値選択の根拠**: 受け入れ基準 TC-108-03 / NFR-001「合成 100 フレームが 60 秒以内」の直接検証。
  - **実際の使用場面**: 実オペランド計測の中規模シーケンス (数十〜百フレーム) の実用性確認。
- **期待される結果**: `run` が 60 秒未満で完走 (`elapsed < 60.0`)、trajectory 長 == 100、`search_results == {}` (非発火)。
  - **境界での正確性**: フレーム数に対する計算コストが線形域に収まる。
  - **一貫した動作**: フレーム数増でも非探索区間の単価が一定に保たれる。
- **テストの目的**: 性能 smoke (NFR-001 / TC-108-03) の確認。
  - **堅牢性の確認**: CI 実行時間内での完走 (実行環境依存のため閾値は保守的に、必要なら verify-complete で担保)。
- 🟡 信頼性: 受け入れ基準 TC-108-03 / NFR-001 / `tests/test_sequential_engine.py` (SE-B08 性能 smoke) からの妥当な推測 (閾値は環境依存で 🟡)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12
  - **言語選択の理由**: プロジェクト全体が Python 3.12 固定 (`target-version = "py312"`)。M0/M1/M2 実装・既存テストと同一言語。
  - **テストに適した機能**: frozen dataclass の値等価比較、`json.dumps(sort_keys=True)` / CSV バイト列比較による決定論検証、`pytest.approx` による物理量近似、`math.isfinite` による非有限漏洩検知。
- **テストフレームワーク**: pytest >= 8 + pytest-cov >= 5
  - **フレームワーク選択の理由**: 既存全テストが pytest。マーカー (`@pytest.mark.gsas`) と `conftest.py` の自動 skip、`tmp_path` / `tmp_path_factory` フィクスチャ、module スコープ fixture を活用できる。
  - **テスト実行環境**: `uv run pytest` (既定) / `uv run pytest --cov=tsumugin` (カバレッジ) / `uv run pytest -m gsas` (GSAS 経路)。依存導入は `uv sync --extra gsas --extra web` (プレーン `uv sync` は禁止)。
- 🔵 信頼性: `pyproject.toml [tool.pytest.ini_options]` / note §5 / `tests/conftest.py` に直接依拠

### テスト実装方針 (Red フェーズ)

- `tests/test_m2_e2e.py` を新規作成。モジュール冒頭で `from tsumugin import SequentialEngine, SequentialConfig, FrameSeries, Trajectory, ExternalChannel, PhaseLifecycle, PersistentLedger, PersistentSnapshotStore, FinalSelectionEngine, ReviewQueue, Decision, detect_escalations, estimate_transition, fit_thermal_baseline` を試みる — **M2 シンボルが `__init__.py` に未昇格の間は collection 時 ImportError で全テスト失敗 (Red)**。`tests/test_m1_e2e.py` と同一の Red 方針。
- `LedgerIntegrityError` は `tsumugin.store.persistent` (または `tsumugin.errors`) から import (TC-022-13)。
- TC-108-01 の一気通貫は module スコープ fixture `warming_run` で 1 回だけ実行し TC-022-03〜10 で共有 (実行時間の抑制。M1 `ab_result` の範)。
- 実装コメントは各テストに「【テスト目的】/【テスト内容】/【期待される動作】+ 信頼性レベル」と Given/When/Then コメントを付す (プロジェクト慣習)。
- `@gsas` 1 件 (TC-022-11) は GSAS-II 導入環境でのみ実行。`tmp_path` で永続ファイル・CSV を隔離。

---

## 5. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (M2 成果物の公開面配線 + 統合 E2E + ドキュメント)
- **参照した入力・出力仕様**: 要件定義 §2.1 (re-export シンボル表) / §2.2 (TC-108-01 一気通貫の 8 段検証) / §2.3 (@gsas smoke) / §2.4 (ドキュメント成果物)
- **参照した制約条件**: 要件定義 §3 (性能 NFR-001 / 非破壊 P2 / 決定論 NFR-102 / 後方互換 REQ-404 / 遅延 import / DB・API なし)
- **参照した使用例**: 要件定義 §4.1 (基本使用パターン) / §4.2 (データフロー) / §4.3 (EDGE-001/002/003/004/101/104)
- **参照した受け入れ基準** (`docs/spec/m2-sequential/acceptance-criteria.md`): TC-108-01 (昇温一気通貫、TC-022-03〜10), TC-108-02 (@gsas 3 フレーム smoke、TC-022-11), TC-108-03 (100 フレーム 60 秒、TC-022-19)、および EDGE-001/003/004/101/104 (TC-022-12〜14/16/17)
- **参照した完了条件** (`docs/tasks/m2-sequential/TASK-0022.md`): ① 公開 API (TC-022-01/02), ② TC-108-01 一気通貫 (TC-022-03〜10 + 決定論 TC-022-15), ③ TC-108-02 @gsas (TC-022-11), ④ 全 green・カバレッジ・ruff (非テスト検証項目), ⑤ README/context.md/検証レポート (TC-022-18 + verify-complete)
- **参照した既存実装・テスト**: `src/tsumugin/__init__.py` (公開面), `tests/test_m1_e2e.py` (公開 API 統合 E2E の直接の範), `tests/test_sequential_engine.py` (昇温合成データ・warm start・決定論・性能 smoke), `tests/test_persistent_store.py` (再オープン + verify + 破損), `tests/test_selection.py` (裁定・エスカレーション), `tests/test_thermal.py` (転移温度), `tests/test_trajectory.py` (CSV), `tests/test_gsasii_backend.py` (@gsas smoke), `tests/conftest.py` (@gsas 自動 skip)

---

## 6. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 11 / 異常系 3 / 境界値 5 を網羅 (公開面・一気通貫 8 段・@gsas・縮退・決定論・境界・性能・ドキュメント整合)
- 期待値定義: 全ケースで具体的な assert 対象 (シンボル型 / __all__ / trajectory 長 / changepoint / lifecycle / 転移温度 / Decision / verify() / CSV 行数 / ビット同一 / 例外) を特定
- 技術選択: Python 3.12 + pytest 8 + pytest-cov / @gsas 自動 skip / tmp_path / module fixture で確定
- 実装可能性: 全 19 件が既存テストパターン (test_m1_e2e / test_sequential_engine / test_persistent_store / test_selection / test_thermal / test_trajectory) の組合せで実装可能
- 信頼性レベル: 🔵 16 / 🟡 3 / 🔴 0 — 🔵 優勢
```

- **要改善点 (実装時に TDD で確定すべき事項)**:
  1. 🔵 昇格シンボルの最終集合 (TC-022-01/02) — 推奨: サブパッケージ `__all__` 準拠 + E2E/CSV/裁定で使う中核型。Green で確定
  2. 🟡 TC-022-19 (100 フレーム 60 秒) の閾値は実行環境依存 — E2E で緩め (保守的) に検証するか verify-complete の性能 smoke へ委譲するか Red で確定
  3. 🟡 TC-022-18 (README M2 例) の文面は Green で確定 (コードによる実行可能性のみテスト化)
  4. 🔵 TC-108-01 の一気通貫を module fixture で共有する範囲 — TC-022-03〜10 は同一 `warming_run` を読む前提 (M1 `ab_result` の範)

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m2-sequential TASK-0022` で Red フェーズ（失敗テスト作成）を開始します。
