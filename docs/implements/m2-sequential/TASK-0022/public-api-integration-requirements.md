# TASK-0022 公開 API 統合 + E2E + ドキュメント — TDD 要件定義書

- **機能名**: 公開 API 統合 + 統合 E2E テスト + ドキュメント (M2 総仕上げ)
- **タスクID**: TASK-0022 / **要件名**: m2-sequential
- **出力ファイル**: `docs/implements/m2-sequential/TASK-0022/public-api-integration-requirements.md`
- **タスクノート**: `docs/implements/m2-sequential/TASK-0022/note.md`

**【信頼性レベル凡例】**: 🔵 EARS 要件定義書・設計文書・実装済みソースに依拠 / 🟡 妥当な推測 (根拠記載) / 🔴 根拠なし推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M2 (シーケンシャル解析基盤) の実装済み成果物 (TASK-0011〜0021) を
  トップレベル公開 API `src/tsumugin/__init__.py` へ re-export で配線し、統合 E2E テスト
  (`tests/test_m2_e2e.py`) とドキュメント (README / context.md / 検証レポート) で「一気通貫で
  動作すること」を裏取りする総仕上げタスク。新規のビジネスロジックは実装せず、既存部品の
  **結線 (integration) と公開面の確定**が中核。
- 🔵 **どのような問題を解決するか**: M2 の個別コンポーネント (逐次エンジン・changepoint・
  lifecycle・thermal・永続化・最終選択) は各タスクで単体テスト済みだが、それらを `from tsumugin
  import ...` の単一名前空間から利用でき、かつ「昇温シーケンス → 転移検出 → 裁定 → 永続監査 →
  CSV」という実利用シナリオが端から端まで破綻なく流れることが未担保。この統合ギャップを埋める。
- 🔵 **想定されるユーザー**: Tsumugin を Python ライブラリとして使う解析者 / エージェント。
  `import tsumugin` だけで M0/M1/M2 の全公開シンボルへ到達し、README の M2 使用例を写経して
  最初のシーケンシャル解析を走らせる。
- 🔵 **システム内での位置づけ**: architecture.md「システム概要」の最上位統合点。M0/M1 の
  抽象境界 (`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore` /
  `HypothesisTreeSearch`) を再利用した M2 フレーム列オーケストレーション層の公開面。M1 の
  TASK-0010 (公開 API 統合) と同型 (M1 検証レポートで確立したパターンの M2 版)。

- **参照した EARS 要件**: REQ-001 (逐次精密化), REQ-005 (トラジェクトリ/CSV), REQ-008 (転移温度),
  REQ-010〜012 (永続化), REQ-013〜015 (最終選択 2 モード + エスカレーション), REQ-404 (後方互換)
- **参照した設計文書**: `docs/design/m2-sequential/architecture.md` (システム概要 / コンポーネント構成表 /
  D1〜D6), `docs/design/m2-sequential/interfaces.py` (全公開型)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 公開 API 統合 (完了条件①) 🔵

- **対象ファイル**: `src/tsumugin/__init__.py` (現状 M0 + M1 の 27 シンボルのみ re-export)
- **追加する M2 シンボル (サブパッケージ `__all__` から昇格)**:
  - `sequential`: `SequentialEngine`, `SequentialConfig`, `SequentialResult`, `FrameSeries`,
    `FrameRecord`, `Trajectory`, `ChangepointConfig`, `ChangepointSignal`, `LifecycleConfig`,
    `LifecycleTracker`, `ThermalBaseline`, `TransitionEstimate`, `detect_changepoint`,
    `estimate_transition`, `fit_thermal_baseline`
  - `selection`: `FinalSelectionEngine`, `Decision`, `ReviewQueue`, `ReviewItem`,
    `detect_escalations` (`EscalationReason` は型エイリアスのため昇格任意)
  - `store`: `PersistentLedger`, `PersistentSnapshotStore`, `phase_to_dict`, `phase_from_dict`
  - `model`: `ExternalChannel`, `PhaseLifecycle`
  - (最終集合は Green で確定。M1 昇格粒度「サブパッケージ __all__ に準じ、E2E/summary 解釈に
    必要なものを昇格」を踏襲)
- **入力**: `import tsumugin` / `from tsumugin import SequentialEngine, FrameSeries, ...` (引数なし)
- **出力/期待**: 各シンボルが解決し、`SequentialEngine`/`FinalSelectionEngine`/`LifecycleTracker`/
  `PersistentLedger`/`PersistentSnapshotStore`/`ReviewQueue` は class、`SequentialConfig`/
  `FrameSeries`/`Trajectory`/`ExternalChannel`/`Decision`/`PhaseLifecycle` 等は
  `dataclasses.is_dataclass` True、`detect_changepoint`/`estimate_transition`/
  `fit_thermal_baseline`/`detect_escalations` は `callable`。トップレベルはサブパッケージ実体の
  re-export (同一 `is` 関係)。`tsumugin.__all__` は昇格シンボルを包含しアルファベット昇順を維持、
  かつ M0/M1 の既存 27 シンボルを 1 つも削除・改名しない (REQ-404 後方互換)。

### 2.2 統合 E2E — TC-108-01 一気通貫 (完了条件②) 🔵

- **入力**: 昇温合成 `FrameSeries` (共通 2θ グリッド + `(n_frames, n_points)` 強度行列 +
  温度 `axis_values`/`ExternalChannel(kind="temperature")`)。**熱膨張で格子定数が単調変化する
  主相 + フレーム途中で相転移 (新相の出現または相の消失)** を含むよう `SimulatedBackend.simulate`
  で合成する。`SequentialEngine(backend, candidates=[...], ledger=PersistentLedger(path),
  snapshots=PersistentSnapshotStore(path2))` に `.run(series, initial_phases)`。
- **出力/期待 (パイプライン各段の結線検証)**:
  1. 逐次精密化: 全フレーム完走 (`SequentialResult` を返す、例外なし)
  2. changepoint: 転移フレーム近傍で発火 (`trajectory.records[k].changepoint is True` かつ
     `search_results` に該当 frame_index)
  3. 局所探索で新相: 採択後の相集合が転移前と異なり `hypotheses` に系譜が登録される
  4. lifecycle: `trajectory.lifecycles` に birth_frame / death_frame が記録される
  5. 転移温度: `estimate_transition(temperatures, fractions, phase_ref=...)` が
     `TransitionEstimate` (onset / midpoint が None でない) を返す
  6. agent 裁定: `FinalSelectionEngine(mode="agent").decide(search_result)` が `Decision` を返す
  7. 永続 ledger: `result.ledger.verify() is True` かつ、注入した `PersistentLedger` を
     **再オープン**して `verify() is True` (プロセス跨ぎの改竄検知)
  8. CSV: `trajectory.to_csv(path)` が書き出しパスを返し、ファイルが実在・ヘッダ + n_frames 行
- **決定論 (REQ-402)**: 同一入力・同一設定で 2 回実行し trajectory / CSV バイト列 / ranking が
  ビット同一 (`==`)。

### 2.3 @gsas 統合 E2E — TC-108-02 smoke (完了条件③) 🔵

- **入力**: `GSASIIBackend` で短い **3 フレーム** `FrameSeries` を `SequentialEngine.run`
  (`@pytest.mark.gsas`)。GSAS-II が確実に計算できる立方 (CIF 簡約) 相を使用。
- **出力/期待**: 例外なく完走し `SequentialResult` を返す (実 GSAS-II 精密化の統合 smoke)。
  `trajectory.records` の長さ 3、`ledger.verify() is True`。未導入環境は conftest が自動 skip。

### 2.4 ドキュメント成果物 (完了条件⑤) 🔵/🟡

- `README.md`: 「使い方 (M2)」節 (10-15 行、`SequentialEngine` 最小使用例、実行確認)。
  アーキテクチャ表に `tsumugin.sequential` / `tsumugin.selection` / `store.persistent` 行追加 🟡
- `docs/dev/context.md`: Overview を M2 スコープへ、Project Structure に sequential/selection/
  persistent 追記、「M1 スコープ外」記述更新 🟡
- `docs/tasks/m2-sequential/reports/verification.md`: `reports/` ごと新規作成。M1 の同ファイル
  構成 (サマリ / タスク別テスト内訳表 / 完了条件充足表 / 仕様適合の要点) を範とする 🔵

- **参照した REQ**: REQ-001/002 (逐次+warm start), REQ-003/101 (changepoint+局所探索),
  REQ-004/201 (lifecycle), REQ-005 (CSV), REQ-008 (転移温度), REQ-010〜012 (永続化),
  REQ-013/102 (agent 裁定), REQ-402 (決定論), REQ-404 (後方互換)
- **参照した設計文書**: `interfaces.py` (`SequentialEngine`/`SequentialResult`/`FrameSeries`/
  `Trajectory`/`PersistentLedger`/`FinalSelectionEngine`/`Decision`/`estimate_transition`),
  `dataflow.md` (全体フロー図)

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **パフォーマンス (NFR-001 / NFR-103 / REQ-403)**: 合成 100 フレーム (changepoint なし) が
  60 秒以内。非探索区間は warm start + direct refine で軽量に、changepoint 近傍のみ局所木探索。
  E2E は範囲を絞った合成データ (M1 の GRID `np.arange(15.0, 60.0, 0.02)` 流用可) で実行時間抑制。
- 🔵 **非破壊 / 監査 (P2 / NFR-101 / NFR-105 / NFR-201 / NFR-203 / REQ-401)**: 破壊的 API を
  追加しない。in-memory / persistent の Ledger・SnapshotStore・ReviewQueue に削除・上書き
  メソッド禁止 (追記 + revert のみ)。永続化書き込みは追記モード (`"a"`) のみ。ledger は追記専用 +
  ハッシュチェーンで `verify()` 常に True (永続版は再オープン時に全チェーン再検証)。E2E で assert。
- 🔵 **決定論 (NFR-102 / NFR-202 / REQ-402)**: 同一入力・同一設定で全出力ビット同一。乱数不使用、
  中央値/MAD ロバスト統計、canonical JSON ソート、ID 決定論採番 (`cfg-XXXX`/`hyp-XXXX`/`rq-XXXX`)。
- 🔵 **後方互換 (REQ-404)**: データモデル拡張 (`Hypothesis.frame_range` / `PhaseInstance.lifecycle` /
  `ExternalChannel`) は既定値付き非破壊追加。M0/M1 公開シンボル (現 `__all__` 27 件) を削除・改名
  しない。既存全テストが無改変で通ること。
- 🔵 **アーキテクチャ制約 (architecture.md)**: frozen dataclass + Protocol 境界 + オンライン単一
  パス (D1)。永続ストアは in-memory 版と**同一インターフェース**で既存エンジンに無改変注入 (D4/REQ-012)。
  最終選択エンジンは SearchResult 非破壊 (D5)。エスカレーション判定は純関数 (D6)。
- 🔵 **技術スタック制約**: コア依存 numpy のみ。CSV = stdlib csv、JSONL = stdlib json。
  GSAS-II 依存テストは @gsas 1 本 (TC-108-02) のみ。遅延 import (D6) で web/gsas 未導入でも
  `import tsumugin` 成功。
- 🔵 **DB / API 制約**: M2 に新規 DB スキーマ・HTTP API なし (永続化は JSONL、Review Queue の
  Web 表示は M3+)。E2E は Python API のみを対象。

- **参照した NFR**: NFR-001, NFR-102, NFR-103, NFR-105, NFR-201, NFR-202, NFR-203
- **参照した REQ**: REQ-401, REQ-402, REQ-404
- **参照した設計文書**: `architecture.md` (アーキテクチャパターン / D1/D4/D5/D6 / 非機能要件の実現方法 /
  技術的制約)

---

## 4. 想定される使用例（Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵
```python
import numpy as np
from tsumugin import SequentialEngine, FrameSeries, SimulatedBackend, PhaseInstance, LatticeParams

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 60.0, 0.02)
# 昇温で格子が膨張しつつ途中で相転移する合成フレーム列を組む
series = FrameSeries(two_theta, intensities, axis_values=temps, axis_kind="temperature")
engine = SequentialEngine(backend, candidates=[...])
result = engine.run(series, initial_phases=[PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0))])
result.trajectory.to_csv("traj.csv")
```

### 4.2 データフロー (dataflow.md / architecture.md D1〜D3) 🔵
frame 0 = `StagedRefinementEngine` 確立 → 後続 = 直近成功フレーム warm start + direct refine →
`detect_changepoint` (複合指標ロバスト z) → 発火フレームのみ `HypothesisTreeSearch.search`
(共有 ledger) → evidence 改善時のみ採択 → `LifecycleTracker` (ヒステリシス N=3) → `Trajectory` 組立 →
`estimate_transition` (相分率シグモイド) → `FinalSelectionEngine.decide` (agent/human) →
エスカレーション → `ReviewQueue`。

### 4.3 エッジ / エラーケース (E2E で縮退確認) 🔵
- **EDGE-001**: 空フレーム列 → 空トラジェクトリ (例外なし)
- **EDGE-002**: あるフレームの精密化失敗 (chi2=inf) → 警告付き記録、次フレームは最後に成功した
  フレームの phases から warm start 継続 (FrameRecord.refine_failed=True、rwp/chi2 は None)
- **EDGE-003**: 永続 ledger 破損 (ハッシュ不整合) → 再オープン時 `LedgerIntegrityError` (修復しない)
- **EDGE-004**: agent モードで裁定対象ゼロ → accept せずエスカレーションのみ
- **EDGE-101**: 単一フレーム → 単発解析等価 + 長さ 1 のトラジェクトリ
- **EDGE-104**: changepoint ゼロ → 局所木探索は一度も呼ばれない (`search_results` 空)

- **参照した EDGE**: EDGE-001, EDGE-002, EDGE-003, EDGE-004, EDGE-101, EDGE-104
- **参照した設計文書**: `dataflow.md` (全体フロー), `architecture.md` (D1〜D6)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m2-sequential/user-stories.md` (シーケンシャル解析者 /
  高温 in situ 実験者 / 監査者 / エージェント裁定)
- **参照した機能要件**: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008,
  REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015, REQ-101, REQ-102, REQ-201, REQ-404
- **参照した非機能要件**: NFR-001, NFR-102, NFR-103, NFR-105, NFR-201, NFR-202, NFR-203
- **参照したEdgeケース**: EDGE-001, EDGE-002, EDGE-003, EDGE-004, EDGE-101, EDGE-104
- **参照した受け入れ基準** (`docs/spec/m2-sequential/acceptance-criteria.md`): **TC-108-01**
  (昇温一気通貫 E2E), **TC-108-02** (@gsas 3 フレーム smoke), **TC-108-03** (100 フレーム 60 秒)。
  併せて構成部品の代表基準 TC-101 系 (逐次)・TC-102 系 (changepoint/局所探索)・TC-103 系
  (lifecycle)・TC-104 系 (trajectory/CSV)・TC-105 系 (thermal)・TC-106 系 (永続化)・TC-107 系
  (2 モード) の統合結線を E2E で横断確認。
- **参照した完了条件** (`docs/tasks/m2-sequential/TASK-0022.md`): ① 公開 API / ② TC-108-01 一気通貫 /
  ③ TC-108-02 @gsas smoke / ④ 全 green・カバレッジ 90%・ruff clean / ⑤ README + context.md + 検証レポート
- **参照した設計文書**:
  - **アーキテクチャ**: `architecture.md` (システム概要 / コンポーネント構成 / D1〜D6 / ディレクトリ構造)
  - **データフロー**: `dataflow.md` (M2 全体フロー図)
  - **型定義**: `interfaces.py` (`SequentialEngine`/`SequentialConfig`/`SequentialResult`/`FrameSeries`/
    `Trajectory`/`FrameRecord`/`ExternalChannel`/`PhaseLifecycle`/`ThermalBaseline`/`TransitionEstimate`/
    `PersistentLedger`/`PersistentSnapshotStore`/`FinalSelectionEngine`/`Decision`/`ReviewQueue`/
    `detect_changepoint`/`estimate_transition`/`fit_thermal_baseline`/`detect_escalations`)
  - **データベース**: なし (永続化は JSONL)
  - **API 仕様**: なし (M2 に新規 HTTP API なし)
- **参照した既存実装・テスト**: `src/tsumugin/__init__.py` (公開面), `tests/test_m1_e2e.py`
  (公開 API 統合 E2E の直接の範), `tests/test_sequential_engine.py` (昇温合成データ生成),
  `tests/test_persistent_store.py` (再オープン + verify), `tests/test_selection.py`,
  `tests/test_thermal.py`, `tests/test_trajectory.py`, `tests/conftest.py` (@gsas 自動 skip)

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (統合タスク。公開シンボル・E2E 検証項目・ドキュメント成果物が具体的に確定)
- 入出力定義: 完全 (実装済みソースで全シグネチャ確認済み。昇格シンボル最終集合のみ Green で確定)
- 制約条件: 明確 (非破壊 P2 / 決定論 NFR-102 / 後方互換 REQ-404 / 性能 NFR-001)
- 実装可能性: 確実 (全構成部品 TASK-0011〜0021 実装済み。M1 TASK-0010 と同型の統合作業)
- 信頼性レベル: 🔵 優勢 (E2E 検証項目・制約はすべて要件/設計/実装ソースに直接依拠)
```

- **要改善点 (実装時に TDD で確定すべき事項)**:
  1. 🔵 昇格シンボルの最終集合 — 推奨: サブパッケージ `__all__` に準拠しつつ E2E/CSV/裁定で使う
     中核型を昇格。Green で確定
  2. 🟡 TC-108-03 (100 フレーム 60 秒) を E2E テスト化するか verify-complete の性能 smoke で担保
     するか — testcases で切り分け (CI 実行時間との兼ね合い)
  3. 🟡 README M2 使用例の文面は Green で確定 (コードによる実行可能性のみテスト化)

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m2-sequential TASK-0022` でテストケースの洗い出しを行います。
