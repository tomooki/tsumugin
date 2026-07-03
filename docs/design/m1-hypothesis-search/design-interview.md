# m1-hypothesis-search 設計ヒアリング記録

**作成日**: 2026-07-03
**実施形態**: 自律実行モード — 質問は行わず、要件定義書・仕様書・M0 実装・推奨案で確定。
以下は設計上の裁量点と自律確定の根拠。

## 自律確定した設計判断

### D-Q1: 木探索の展開戦略 (BFS/DFS/best-first)

**カテゴリ**: アーキテクチャ
**確定**: best-first (マッチングスコア順 + Rwp 改善ゲート) + 組合せ重複排除
**根拠**: FR-111 の「事前枝刈り」と FR-115 の「R 改善閾値」が自然に best-first を構成する 🔵。
探索順自体の明示は仕様になし 🟡。決定論のため同点時は候補 index 順の安定ソート。

### D-Q2: 探索ノードの精密化に StagedRefinementEngine を使うか

**カテゴリ**: 技術選択
**確定**: 使わない。backend.refine 直呼び (scale+lattice, ≤5 cycles)
**根拠**: FR-113「保守的設定の制約付き精密化(探索モード)」。段階テンプレートのフル実行は
ノードあたりコストが NFR-103 (300 相 3 分) と両立しない 🔵。サイクル数 5 は推測 🟡。

### D-Q3: 最終検証のフル精密化

**カテゴリ**: アーキテクチャ
**確定**: Jenks 良好クラスタ上位 3 件のみ StagedRefinementEngine 適用 (config で無効化可)
**根拠**: Dara 思想「精密化を検証エンジンとして使う」(§1.1) 🔵。件数 3 は推測 🟡。

### D-Q4: Rwp 改善閾値の解釈 (相対% vs 絶対ポイント)

**カテゴリ**: アルゴリズム
**確定**: 絶対ポイント (parent_rwp − child_rwp ≥ 2.0)
**根拠**: 仕様 FR-115「R改善閾値(既定2%)」の単位が曖昧 🟡。Rwp 自体が % 量のため
絶対ポイント解釈を採用し、SearchConfig で変更可能にして曖昧さを設定に逃がす。

### D-Q5: Web UI のフレームワーク

**カテゴリ**: 技術選択
**確定**: FastAPI + uvicorn (optional extra `web`) + 静的 HTML 1 枚。テストは fastapi TestClient (httpx)
**根拠**: requirements interview Q2 の確定を踏襲 🟡。コア依存 (numpy のみ) は不変。

### D-Q6: DB スキーマ

**カテゴリ**: データモデル
**確定**: 作成しない
**根拠**: M1 に永続 DB 要件なし。Project Store (HDF5+SQLite, §3) は M2 の ledger/snapshot
永続化と併せて設計する 🔵。

### D-Q7: PhaseCandidate の導入

**カテゴリ**: データモデル
**確定**: PhaseInstance の薄いラッパ `PhaseCandidate(phase, delta_u=0.0, label)` を新設。
search() は両型を受理 (PhaseInstance は delta_u=0 で正規化)
**根拠**: FR-114 の FoM が ΔU を要求するが M1 に hull データ源 (FR-103) が無い。
界面のみ先行確保 🟡。

### D-Q8: GSASIIBackend との .gpx コード共有

**カテゴリ**: 技術選択
**確定**: GSASIIBackend の一時 gpx 構築部を `_build_project()` ヘルパとして抽出し、
export_gpx と refine の両方から使う (重複実装しない)
**根拠**: M0 実装の再利用・単一情報源 🔵。

## 残課題 (実装時確定)

- Jaccard 類似閾値 0.85 / ビン幅 0.2° / マッチ許容 0.15° は合成データのテストで較正
- Jenks クラス数 k=2 固定で開始、必要なら k 自動選択を M2 で検討
- Web UI の見た目は最小 (テーブル + 詳細 pane)。デザイン投資は M2 以降

## 信頼性レベル分布 (設計文書全体)

- 🔵 青信号: 45 件 (64%)
- 🟡 黄信号: 25 件 (36%)
- 🔴 赤信号: 0 件

## 関連文書

- **アーキテクチャ設計**: [architecture.md](architecture.md)
- **データフロー**: [dataflow.md](dataflow.md)
- **型定義**: [interfaces.py](interfaces.py)
- **API 仕様**: [api-endpoints.md](api-endpoints.md)
- **要件定義**: [requirements.md](../../spec/m1-hypothesis-search/requirements.md)
