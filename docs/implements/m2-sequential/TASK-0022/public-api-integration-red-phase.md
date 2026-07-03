# TASK-0022 公開 API 統合 + E2E — TDD Red フェーズ記録

- **機能名**: 公開 API 統合 + 統合 E2E テスト + ドキュメント (M2 総仕上げ)
- **タスクID**: TASK-0022 / **要件名**: m2-sequential
- **テストファイル**: `tests/test_m2_e2e.py` (新規)
- **作成日時**: 2026-07-03
- **対象テストケース**: TC-022-01〜19 (全 19 件, `@gsas` 1 件含む)

---

## 1. 作成したテストケース一覧 (19 件 / 1:1 対応)

| # | テスト関数 | 分類 | マーカー | 対応 |
|---|-----------|------|----------|------|
| TC-022-01 | `test_m2_public_symbols_are_reexported` | 正常系 | なし | 公開 API 型解決 |
| TC-022-02 | `test_m2_symbols_in_dunder_all_and_sorted` | 正常系 | なし | `__all__` 昇順 + 後方互換 |
| TC-022-03 | `test_e2e_warming_sequence_completes_all_frames` | 正常系 | なし | TC-108-01a 全フレーム完走 |
| TC-022-04 | `test_e2e_changepoint_fires_near_transition` | 正常系 | なし | TC-108-01b changepoint 発火 |
| TC-022-05 | `test_e2e_new_phase_adopted_into_hypotheses` | 正常系 | なし | TC-108-01c 新相採択 |
| TC-022-06 | `test_e2e_lifecycle_birth_death_recorded` | 正常系 | なし | TC-108-01d lifecycle |
| TC-022-07 | `test_e2e_transition_temperature_estimated` | 正常系 | なし | TC-108-01e 転移温度 |
| TC-022-08 | `test_e2e_agent_final_selection_decides` | 正常系 | なし | TC-108-01f agent 裁定 |
| TC-022-09 | `test_e2e_persistent_ledger_verify_and_reopen` | 正常系 | なし | TC-108-01g 永続 ledger |
| TC-022-10 | `test_e2e_trajectory_to_csv_written` | 正常系 | なし | TC-108-01h CSV 出力 |
| TC-022-11 | `test_e2e_gsasii_three_frame_sequential_smoke` | 正常系 | `@gsas` | TC-108-02 3 フレーム smoke |
| TC-022-12 | `test_e2e_empty_series_degrades_gracefully` | 異常系 | なし | EDGE-001 空フレーム列 |
| TC-022-13 | `test_e2e_corrupted_persistent_ledger_raises_on_reopen` | 異常系 | なし | EDGE-003 破損検知 |
| TC-022-14 | `test_e2e_agent_no_candidates_escalates_only` | 異常系 | なし | EDGE-004 裁定対象ゼロ |
| TC-022-15 | `test_e2e_deterministic_trajectory_and_csv_bitwise_identical` | 境界値 | なし | REQ-402 決定論 |
| TC-022-16 | `test_e2e_single_frame_sequence` | 境界値 | なし | EDGE-101 単一フレーム |
| TC-022-17 | `test_e2e_no_changepoint_skips_local_search` | 境界値 | なし | EDGE-104 非発火 |
| TC-022-18 | `test_readme_m2_example_executes` | 境界値 | なし | 完了条件⑤ README 例 |
| TC-022-19 | `test_e2e_hundred_frames_within_time_budget` | 境界値 | なし | TC-108-03 / NFR-001 性能 |

- **信頼性内訳**: 🔵 16 / 🟡 3 (TC-022-18/19 + 分率抽出ヒューリスティック) / 🔴 0
- **共有 fixture**: `warming_run` (module スコープ)。昇温 + 相転移一気通貫を 1 回だけ実行し
  TC-022-03〜10 で読み取り専用共有 (M1 `ab_result` の範)。永続 ledger/snapshots は
  `tmp_path_factory` で隔離。

---

## 2. 合成データ設計 (TC-108-01 一気通貫)

- `_warming_transition_series(n_frames=16, b_onset=10)`: 主相 A を熱膨張
  (`a = 5.0 + 0.01*i`、SE-B06 で非発火較正済み) させつつ、frame 10 以降で新相 B (a=6.0) を
  重畳。温度チャネル (`300 + 5*i`) を同期。
  - changepoint は B の新規未マッチピークで frame 10 近傍に発火 (SE-N03 の踏襲)。
  - B は局所探索で採択され以降継続 (SE-N04)、lifecycle N=3 で birth 確定 (SE-N06)。
  - 相分率 (B の存在指標 0→1) を trajectory から抽出し `estimate_transition` を発火。
- `_expansion_series(...)`: 相構成不変・格子のみ膨張 (changepoint 非発火。TC-022-16/17/19)。

---

## 3. 期待される失敗内容 (Red)

- **失敗機構**: モジュール冒頭 `from tsumugin import (ChangepointConfig, ..., phase_from_dict)` が
  トップレベル未 re-export のため **collection 時 ImportError**。`tests/test_m1_e2e.py` と同一方針。
- **確認済み実際の失敗**:
  ```
  tests\test_m2_e2e.py:53: in <module>
      from tsumugin import (
  E   ImportError: cannot import name 'ChangepointConfig' from 'tsumugin'
  ```
- **結果**: collection error 1 件 → 本ファイルの全 19 テストが失敗 (実行前に停止)。
- **既存テストへの影響なし**: `--ignore=tests/test_m2_e2e.py -m "not gsas"` で既存スイート全 green を確認。
- **ruff**: `uvx ruff check tests/test_m2_e2e.py` → All checks passed (line-length 100)。

---

## 4. Green フェーズで実装すべき内容

- `src/tsumugin/__init__.py` に M2 の昇格シンボル (26 件) を各サブパッケージから re-export:
  - `sequential`: `SequentialEngine` / `SequentialConfig` / `SequentialResult` / `FrameSeries` /
    `FrameRecord` / `Trajectory` / `ChangepointConfig` / `ChangepointSignal` / `LifecycleConfig` /
    `LifecycleTracker` / `ThermalBaseline` / `TransitionEstimate` / `detect_changepoint` /
    `estimate_transition` / `fit_thermal_baseline`
  - `selection`: `FinalSelectionEngine` / `Decision` / `ReviewQueue` / `ReviewItem` /
    `detect_escalations`
  - `store`: `PersistentLedger` / `PersistentSnapshotStore` / `phase_to_dict` / `phase_from_dict`
  - `model`: `ExternalChannel` / `PhaseLifecycle`
- `__all__` へ追記し **アルファベット昇順**を維持 (M0/M1 の 26 件は削除・改名しない = REQ-404)。
- トップレベルはサブパッケージ実体の re-export (`tsumugin.X is tsumugin.<pkg>.X`) を満たすこと。
- (ドキュメント成果物 README / context.md / verification.md は完了条件⑤で別途。TC-022-18 は
  コードによる実行可能性のみを検証。)

## 次のステップ

`/tsumiki:tdd-green m2-sequential TASK-0022` で Green フェーズ (最小実装 = 公開面 re-export) を開始する。
