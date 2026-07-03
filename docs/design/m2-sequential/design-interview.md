# m2-sequential 設計ヒアリング記録

**作成日**: 2026-07-03
**実施形態**: 自律実行モード — 質問は行わず、要件定義書・仕様書・M0/M1 実装・推奨案で確定。

## 自律確定した設計判断

### D-Q1: シーケンシャル処理方式 (オンライン単一パス vs 2 パス)
**確定**: オンライン単一パス (フレーム順に 検出→局所探索→採択→継続)
**根拠**: §14「逐次解析の誤り伝播」— 変化点で即座に相構成を修正する方が下流フレームの
warm start が正しくなる。2 パスは全フレーム再精密化のコスト増 🟡。

### D-Q2: フレーム精密化の方式
**確定**: 初回フレームのみ StagedRefinementEngine フル確立、後続は backend.refine 直呼び
(scale+lattice, ≤10 cycles)
**根拠**: NFR-103 (非探索区間 ≤10 秒/フレーム)。フルテンプレート×毎フレームは過剰 🟡。
FR-301 は方式を規定しない。

### D-Q3: changepoint 検出の統計
**確定**: 直近 W=5 フレームの中央値/MAD ロバスト z スコア、閾値 5.0、3 指標の OR。
warm-up (W 未満) は検出スキップ
**根拠**: requirements interview Q5 の確定を実装可能な形に具体化 🟡。決定論 (乱数なし)。

### D-Q4: 局所探索の採択基準
**確定**: 最良仮説の相集合が現行と異なり、かつ evidence (BIC) が現行構成の同フレーム評価より
改善する場合のみ採択。採択/棄却とも ledger 記録
**根拠**: FR-304 + P1 (仮説は列挙するが採択は evidence 根拠) 🔵/🟡。

### D-Q5: 永続化の分業
**確定**: `store/serialization.py` (phase の dict 相互変換) を独立モジュールにし、
persistent.py と将来の Project Store (M3+) が共有。ハッシュ計算は ledger.py の既存私的関数を
import して共有 (M1 レビュー指摘の教訓: 私的横断 import になるため、実装時に `_canonical_json`
を公開ヘルパへ昇格させてよい)
**根拠**: 単一情報源。JSONL 選定は requirements interview Q4 🟡。

### D-Q6: FinalSelectionEngine の状態管理
**確定**: SearchResult は不変のまま、エンジンが裁定レジストリ (id → accepted Hypothesis) を保持。
accepted 化は `dataclasses.replace` による新インスタンス生成
**根拠**: P2 非破壊 + M0/M1 の frozen dataclass 規約 🔵。

### D-Q7: Review Queue と ledger の関係
**確定**: ReviewQueue は独立の追記型コレクション (ledger 注入時は add/resolve を ledger にも記録)。
キュー自体の永続化は M2 では ledger 経由の再構築で足りるため実装しない
**根拠**: FR-403 の必須要素は「通知される・ブロックしない・後から見直せる」🔵。専用永続化は
M3 の Review Queue UI (FR-421) と併せて 🟡。

### D-Q8: native sequential (GSAS-II) の扱い
**確定**: `SequentialConfig.orchestration="native"` は `NotImplementedError` (明示メッセージ付き)
**根拠**: REQ-105。GSAS-II ネイティブ sequential の統合は温度依存 instprm 等の論点が多く M-later 🔵。

## 残課題 (実装時確定)

- confidence の算出式 (存在フレーム率 vs ヒステリシス重み付き) — TDD で確定
- Trajectory CSV の列順 — 実装時に固定しテストで凍結
- `_canonical_json` の公開昇格の是非 — TASK 実装時のリファクタで判断

## 信頼性レベル分布 (設計文書全体)

- 🔵: 63 件 (61%) / 🟡: 40 件 (39%) / 🔴: 0 件

## 関連文書

- [architecture.md](architecture.md) / [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) /
  [要件定義](../../spec/m2-sequential/requirements.md)
