# Verification Report: m2-sequential

> 2026-07-03 / TDD 自律実装 (M2: シーケンシャル解析 — 全 12 タスク完了)

## サマリ

M2 (シーケンシャル/operando 逐次解析) スコープの 12 タスク (全 TDD) を TDD で実装完了。全タスク完了。
M0 (PoC) + M1 (多仮説木探索) の全公開面を非破壊で維持したまま、時系列フレーム列の**オンライン逐次
精密化** (warm start + direct refine)・**changepoint 検出**時のみ局所木探索を起動する新相採択・
**lifecycle (ヒステリシス)**・**転移温度推定**・**trajectory/CSV**・**agent/human 2 モードの最終選択**・
**JSONL 永続化 (再オープン改竄検知)** を積み上げ、公開 API 統合と一気通貫 E2E で束ねた。

- **テスト**: 425 passed, 3 skipped (428 collected)。skip 3 件はいずれも「GSAS-II 導入済みのため
  *未導入時に例外* 経路を実行しない」正しい skip (test_gpx_export.py ×2 / test_gsasii_backend.py ×1、M1 から継続)。
- **GSAS-II 経路 (`@pytest.mark.gsas`)**: 実 GSAS-II (2.0, win_64_p3.12_n2.2 バイナリ) で green。
  M2 追加分は TC-022-11 (GSASIIBackend 3 フレーム逐次 smoke = TC-108-02) の 1 本。
- **カバレッジ**: 97% (2076 stmts / 65 miss)。M2 追加分 (`sequential` / `selection` / `store.persistent`
  / `store.serialization` / `model.channel` / `model.PhaseLifecycle`) を含め 90% 基準を充足。
  公開 API 統合点 `src/tsumugin/__init__.py` は 100%。
- **Lint**: `uvx ruff check src tests` クリーン (line-length 100, target py312)。
- **決定論**: 同一入力 → `Trajectory` と `to_csv` のバイト列がビット同一を E2E で検証 (REQ-402 / TC-022-15)。
- **公開 API**: `from tsumugin import SequentialEngine, SequentialConfig, FrameSeries, Trajectory,`
  `ExternalChannel, PersistentLedger, PersistentSnapshotStore, FinalSelectionEngine, ReviewQueue,`
  `estimate_transition, ...` がトップレベルで解決。`__all__` は 52 件 (M0/M1 26 + M2 26)・
  アルファベット昇順・後方互換維持 (REQ-404)。

## タスク別テスト内訳

| Task | 種別 | モジュール | テスト | 状態 |
|------|------|-----------|-------|------|
| 0011 | TDD | model 拡張 (`PhaseLifecycle` / `ExternalChannel` / `frame_range`) | test_model_m2.py (15) | ✅ |
| 0012 | TDD | store.serialization (`phase_to_dict` / `phase_from_dict` 相互変換) | test_serialization.py (15) | ✅ |
| 0013 | TDD | store.persistent (`PersistentLedger` JSONL 追記+検証) | test_persistent_store.py (27)* | ✅ |
| 0014 | TDD | store.persistent (`PersistentSnapshotStore`) | test_persistent_store.py (27)* | ✅ |
| 0015 | TDD | sequential.series + changepoint (`FrameSeries` / `detect_changepoint`) | test_sequential_series.py (9) + test_changepoint.py (15) | ✅ |
| 0016 | TDD | sequential.lifecycle (`LifecycleTracker` ヒステリシス) | test_lifecycle.py (13) | ✅ |
| 0017 | TDD | sequential.trajectory (`Trajectory` + `to_csv`) | test_trajectory.py (17) | ✅ |
| 0018 | TDD | sequential.thermal (ベースライン + 転移温度 `estimate_transition`) | test_thermal.py (18) | ✅ |
| 0019 | TDD | sequential.engine (`SequentialEngine` オンライン逐次 + 局所探索) | test_sequential_engine.py (18) | ✅ |
| 0020 | TDD | selection.review_queue (`ReviewQueue` + `detect_escalations`) | test_selection.py (36)* | ✅ |
| 0021 | TDD | selection.engine (`FinalSelectionEngine` agent/human 2 モード) | test_selection.py (36)* | ✅ |
| 0022 | TDD | `__init__` 公開 API 統合 + E2E | test_m2_e2e.py (19) | ✅ |

*`test_persistent_store.py` の 27 件は TASK-0013 (PersistentLedger) と TASK-0014 (PersistentSnapshotStore)
を、`test_selection.py` の 36 件は TASK-0020 (ReviewQueue/エスカレーション) と TASK-0021 (FinalSelectionEngine)
を合わせて担保する (各ペアが同一 `store/persistent.py` / `selection/engine.py` に積層するためテストファイルを共有)。

**M2 新規テスト計**: 202 件 (model_m2 15 + serialization 15 + persistent 27 + series 9 + changepoint 15 +
lifecycle 13 + trajectory 17 + thermal 18 + sequential_engine 18 + selection 36 + m2_e2e 19)。
M0+M1 から継続の 226 件 (223 passed + 3 skip) と合わせ 428 collected / 425 passed / 3 skip。

## TASK-0022 完了条件の充足 (本タスク)

| # | 完了条件 | 根拠 | 状態 |
|---|---------|------|------|
| ① | `from tsumugin import SequentialEngine, ...` で M2 API 利用可能 | `src/tsumugin/__init__.py` re-export + `__all__` 52 件昇順 / TC-022-01,02 | ✅ |
| ② | TC-108-01 一気通貫 E2E green (逐次→changepoint→新相→lifecycle→転移温度→agent 裁定→永続 ledger verify→CSV) | TC-022-03〜10 (`test_m2_e2e.py` の 8 段、`warming_run` fixture 共有) | ✅ |
| ③ | (@gsas) TC-108-02 3 フレーム smoke | TC-022-11 (実 GSAS-II で green) | ✅ |
| ④ | 全テスト green・カバレッジ 90% 以上・ruff clean | 425 passed/3 skip・97%・ruff clean | ✅ |
| ⑤ | README M2 例 (10-15 行・実行確認) + context.md 更新 + 検証レポート | `README.md` §使い方(M2) + アーキ表 (TC-022-18 で実行担保) / `docs/dev/context.md` / 本ファイル | ✅ |

## E2E テストケース (TC-022-01〜19) の網羅

`tests/test_m2_e2e.py` にテストケース定義書の全 19 件を 1:1 実装、全 green (検証内訳: 正常系 11 / 異常系 3 / 境界値 5)。

- **正常系 11**: 公開シンボル re-export + 型確認 (01) / `__all__` 昇順・後方互換 (02) / 昇温逐次が全
  フレーム完走・trajectory 長 = n_frames (03) / changepoint 転移近傍発火 (04) / 局所探索で新相 B 採択→
  hypotheses 系譜反映 (05) / lifecycle birth 記録 (06) / `estimate_transition` 転移温度推定 (07) /
  agent 裁定 → `Decision` (08) / 永続 ledger `verify()` True + **再オープン** verify True (09) /
  `Trajectory.to_csv` ヘッダ + n_frames 行 (10) / @gsas GSASIIBackend 3 フレーム smoke 完走 (11)。
- **異常系 3**: 空フレーム列 → 空トラジェクトリへ例外なく縮退 (12) / 永続 ledger 破損 → 再オープンで
  `LedgerIntegrityError` (13) / agent 裁定対象ゼロ → accept せずエスカレーションのみ (14)。
- **境界値 3+2**: 決定論ビット同一 (trajectory / CSV) (15) / 単一フレーム → 長さ 1 トラジェクトリ (16) /
  changepoint ゼロ → 局所木探索が一度も呼ばれない (17) / README 使用例の実行可能性 (18) /
  合成 100 フレーム < 60 秒の性能予算 (19)。

## 仕様適合の要点

- **REQ-001〜008 (逐次精密化)**: frame0 を staged 精密化で確立し、以降は直近成功フレームからの
  warm start + direct refine で軽量処理。複合指標ロバスト z の `detect_changepoint` 発火フレームでのみ
  局所木探索を起動し新相を採択する。`SequentialEngine` に実装、E2E で昇温列の全フレーム完走と
  新相 B の系譜反映を検証。
- **REQ-005/006 (lifecycle・転移温度)**: `LifecycleTracker` がヒステリシス閾値で相の birth/death を
  判定し黙殺を防止。`estimate_transition` が相分率シグモイドから onset/midpoint 転移温度を推定。
- **REQ-007/008 (trajectory 出力)**: `Trajectory` が相分率・格子定数・Rwp の時系列を保持し `to_csv` で
  ヘッダ + フレーム行の CSV を書き出す (operando 可視化・下流連携)。
- **REQ-010〜012 / NFR-105 (永続化・監査)**: `PersistentLedger` (追記専用 JSONL ハッシュチェーン) と
  `PersistentSnapshotStore` により全操作を別プロセス再オープン可能な形で永続化。E2E で `verify()` True +
  破損時 `LedgerIntegrityError` 検出を担保 (P2 非破壊監査の永続化拡張)。
- **REQ-013〜015 (最終選択 2 モード)**: `FinalSelectionEngine` が agent (自動裁定) / human (Review Queue)
  の 2 モードを提供。`detect_escalations` + `ReviewQueue` で人間介入点を明示。裁定対象ゼロ時は accept せず
  エスカレーションのみに縮退。
- **REQ-402 (決定論)**: 乱数種固定 + canonical 出力で 2 回実行の `Trajectory` / CSV がビット同一。
- **REQ-404 / 後方互換 (要件 §3.2)**: M0+M1 公開シンボル 26 件を 1 つも削除・改名せず、M2 の 26 シンボルを
  昇格追加し `__all__` 52 件を昇順維持。`import tsumugin` はコア (numpy のみ) で成立 (web/GSAS-II は遅延 import)。

## 設計上の注記 / 実装時に確定した事項

- **昇格シンボル 26 件**: エンジン系 (`SequentialEngine`/`SequentialConfig`/`SequentialResult`)、時系列
  データ (`FrameSeries`/`FrameRecord`/`Trajectory`/`ExternalChannel`)、検出/推定 (`ChangepointConfig`/
  `ChangepointSignal`/`detect_changepoint`/`ThermalBaseline`/`TransitionEstimate`/`fit_thermal_baseline`/
  `estimate_transition`)、lifecycle (`LifecycleConfig`/`LifecycleTracker`/`PhaseLifecycle`)、選択
  (`FinalSelectionEngine`/`Decision`/`ReviewQueue`/`ReviewItem`/`detect_escalations`)、永続化
  (`PersistentLedger`/`PersistentSnapshotStore`/`phase_to_dict`/`phase_from_dict`) をトップレベル公開。
- **E2E fixture 共有**: module スコープ fixture `warming_run` で一気通貫 (TC-108-01) を 1 回だけ実行し、
  正常系 TC-022-03〜10 の 8 ケースで frozen な `SequentialResult` と永続ファイルパスを読み取り専用共有
  (実行時間抑制。M1 `ab_result` の範を踏襲)。全 425 テスト合計 15.14 秒。
- **共有テストファイル**: `test_persistent_store.py` (0013+0014) と `test_selection.py` (0020+0021) は
  ペアタスクが同一実装ファイルに積層するためテストを共有 (M1 `test_tree_search.py` と同型の運用)。
- **Refactor 判断**: TASK-0022 の実装対象 (re-export + doc + E2E) はロジックを持たないため、Green 完了
  時点で品質基準充足と判断し YAGNI に基づき変更なし (詳細は
  `docs/implements/m2-sequential/TASK-0022/public-api-integration-refactor-phase.md`)。
- **既知の無害警告**: 起動時の "Error reading {cfgfile}" は GSAS-II が既存 `~/.GSASII/config.ini`
  (cp932) を UTF-8 で読む upstream 表示バグ。テスト実行・結果に影響なし (context.md に記録済み)。

## M2 スコープ外 (次段 M3+)

operando の高度解析、中性子 joint (FR-240)、MEM (FR-600)、nested sampling、REST/MCP、
永続化 DB (RDB)。M2 の永続化は JSONL 追記ファイルに留め、DB バックエンドは M3+ で本格化する。
