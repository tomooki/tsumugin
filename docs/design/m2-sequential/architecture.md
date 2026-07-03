# m2-sequential アーキテクチャ設計

**作成日**: 2026-07-03
**関連要件定義**: [requirements.md](../../spec/m2-sequential/requirements.md)
**ヒアリング記録**: [design-interview.md](design-interview.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様・M0/M1 実装に依拠 / 🟡 妥当な推測で確定 / 🔴 根拠なし推測

---

## システム概要 🔵

M0 (単発精密化) / M1 (多仮説木探索) の上に**時系列レイヤ**を載せる。フレーム列を warm start で
逐次精密化し、changepoint でのみ M1 木探索を局所起動する (P5)。全履歴は永続化された追記専用
ストアに記録され (P2)、フレームごとの裁定は最終選択エンジン (agent/human) が行う (FR-402/403)。

## アーキテクチャパターン 🔵

- **パターン**: M0/M1 と同一の「不変データ + Protocol 境界 + 追記専用ストア」。時系列は
  **オンライン単一パス** (フレーム順に検出→対応→継続) で処理する
- **選択理由**: P5 (トラジェクトリ)・NFR-102 (決定論)・NFR-103 (10 秒/フレーム) と整合。
  オンライン方式は将来の実験ストリーミング対応 (P6) も阻害しない 🟡 *design-interview D-Q1*

## コンポーネント構成

### 新規モジュール

| モジュール | 役割 | 要件 | 信頼性 |
|---|---|---|---|
| `model/channel.py` | `ExternalChannel` (kind, frame→value 同期) | REQ-006 | 🔵 §4 |
| `model/phase.py` 拡張 | `PhaseLifecycle` (birth/death/confidence) を `PhaseInstance.lifecycle` に非破壊追加 | REQ-004/404 | 🔵 §4 |
| `model/hypothesis.py` 拡張 | `Hypothesis.frame_range` 非破壊追加 | REQ-404 | 🔵 §4 |
| `sequential/series.py` | `FrameSeries` (共通 2θ + フレーム強度行列 + 軸値 + channels) | REQ-001/006 | 🟡 D-Q2 |
| `sequential/changepoint.py` | 複合指標 (Rwp 跳ね/格子微分/新規未マッチ) のロバスト z 検出 | REQ-003 | 🔵 FR-303 (式 🟡) |
| `sequential/lifecycle.py` | `LifecycleTracker` — ヒステリシス付き birth/death 判定 | REQ-004/201 | 🔵 FR-305 |
| `sequential/trajectory.py` | `Trajectory`/`FrameRecord` + `to_csv()` (stdlib) | REQ-005 | 🔵 FR-306 |
| `sequential/thermal.py` | 熱膨張ベースライン + 転移温度 onset/midpoint±σ | REQ-007/008 | 🔵 FR-322/323 |
| `sequential/engine.py` | `SequentialEngine` — オーケストレーション本体 | REQ-001/002/101/105 | 🔵 FR-301/302/304 |
| `store/serialization.py` | PhaseInstance/Lattice/Lifecycle の dict 相互変換 | REQ-011 | 🟡 |
| `store/persistent.py` | `PersistentLedger`/`PersistentSnapshotStore` (JSONL 追記) | REQ-010〜012/401 | 🔵 NFR-105 (形式 🟡) |
| `selection/review_queue.py` | `ReviewQueue` (追記型) + `ReviewItem` | REQ-015 | 🔵 FR-403 |
| `selection/engine.py` | `FinalSelectionEngine` (agent/human) + `Decision` | REQ-013/014/102〜104/202 | 🔵 FR-402 |

### 再利用する M0/M1 資産 🔵

- `RefinementBackend` (Simulated/GSASII) — フレーム精密化とパターン計算
- `StagedRefinementEngine` — 初回フレームの確立精密化 (D2)
- `HypothesisTreeSearch` + `PhaseCandidate` — changepoint 近傍の局所探索 (REQ-101)
- `find_peaks`/`match_score`/`unmatched_peaks` — 新規未マッチピーク指標 (REQ-003c)
- `BICBackend`/`rank` — 局所探索の evidence・僅差競合判定
- `Ledger`/`SnapshotStore` — インターフェースの参照実装 (永続版が同一契約を実装)

## 主要設計決定

### D1: オンライン単一パスの逐次処理 🟡
フレーム i を処理する際、直近 W (既定 5) フレームのローリング統計 (中央値/MAD) に対する
ロバスト z スコアで changepoint を判定し、検出時はその場で局所木探索→採択→継続する。
2 パス方式 (全精密化→一括検出→再精密化) より誤り伝播が少なく (§14)、実装も単純。

### D2: フレーム精密化の 2 段構え 🔵/🟡
- **初回フレーム**: `StagedRefinementEngine` のフルテンプレートで確立 (ガード付き)
- **後続フレーム**: `backend.refine` 直呼び (scale + lattice、`seq_max_cycles` 既定 10)。
  warm start は直近の**成功**フレームの phases (EDGE-002)
- 根拠: FR-301 は方式を規定しない。全フレーム staged は NFR-103 (10 秒/フレーム) に不利 🟡

### D3: changepoint 時の局所木探索と採択 🔵
検出フレームで `HypothesisTreeSearch.search` (候補 = 現行相 + 供給された候補プール) を実行。
最良仮説の相集合が現行と異なり、かつ evidence が改善する場合のみ採択し、以後のフレームは
新構成で継続。採択・棄却とも理由付き ledger 記録 (FR-214 踏襲)。

### D4: 永続ストア = JSONL 追記 🔵/🟡
- `PersistentLedger(path)`: オープン時に既存行を読み込み検証、以後 1 append = 1 行追記
  (`"a"` モードのみ、NFR-203)。ハッシュ計算は in-memory 版の `_canonical_json`/`_compute_hash`
  を共有 (単一情報源)
- `PersistentSnapshotStore(path)`: phases を `store/serialization.py` で dict 化して JSONL 追記。
  revert は in-memory 版と同一意味論
- 破損検出 (EDGE-003): オープン時 verify 失敗で `LedgerIntegrityError` (新設、修復しない)

### D5: 最終選択エンジンは SearchResult 非破壊 🔵
`FinalSelectionEngine.decide(result)` は SearchResult を変更せず、`Decision` (accepted/provisional/
escalations/rationale) を返し、accepted 化は**新しい Hypothesis インスタンス** (status/accepted_by
更新) を自身のレジストリと ledger に記録する。revert は superseded 化の追記 (REQ-202)。

### D6: エスカレーション判定は純粋関数 🔵
`detect_escalations(result, staged_escalated: bool) -> tuple[EscalationReason, ...]` —
(a) 全仮説 Rwp > 閾値、(b) unknown_phase_flag、(c) 1-2 位 ΔBIC < 閾値 (close_competitor)、
(d) ガードエスカレーション。M2 で利用可能な材料のみ (吸収補正モードは M3)。

## ディレクトリ構造 🔵

```
src/tsumugin/
├── sequential/     # 新規: series/changepoint/lifecycle/trajectory/thermal/engine
├── selection/      # 新規: engine (2モード) + review_queue
├── store/          # 拡張: serialization.py + persistent.py (ledger.py/snapshot.py は不変)
└── model/          # 拡張: channel.py 新規、phase/hypothesis に非破壊フィールド追加
tests/
├── test_sequential_*.py (series/changepoint/lifecycle/trajectory/thermal/engine)
├── test_persistent_store.py
└── test_selection.py
```

## 非機能要件の実現方法

- **NFR-001/REQ-403 (性能)**: 後続フレームは direct refine (数値ヤコビアン ~7 パラメータ×10 cycles)。
  合成 100 フレーム < 60 秒を smoke テストで担保 🟡
- **NFR-102 (決定論)**: 乱数なし。ローリング統計は中央値/MAD (決定論)。テストでビット同一検証 🔵
- **NFR-105 (改竄検知)**: JSONL 再オープン時に全チェーン再検証 🔵
- **セキュリティ**: 永続ファイルはローカル書き込みのみ。パスはユーザー指定 (traversal 面なし)。
  JSONL に生データ (強度配列) は保存しない (snapshot は phases のみ、ledger は要約値) 🟡

## 技術的制約 🔵

- コア依存 numpy のみ (CSV は stdlib csv、JSONL は stdlib json)
- 既存 API の後方互換 (REQ-404): 新フィールドは既定値付き、既存テスト 226 件が無改変で通ること
- GSAS-II 依存テストは @gsas 1 本 (TC-108-02) のみ

## 関連文書

- [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) /
  [要件定義](../../spec/m2-sequential/requirements.md)
- DB スキーマ: なし (永続化は JSONL。Project Store HDF5+SQLite は M3+ で再検討) 🔵
- API 仕様: なし (M2 に新規 HTTP API なし。Review Queue の Web 表示は M3+ FR-421) 🔵

## 信頼性レベルサマリー

- 🔵: 19 件 (63%) / 🟡: 11 件 (37%) / 🔴: 0 — **品質評価**: 高品質
