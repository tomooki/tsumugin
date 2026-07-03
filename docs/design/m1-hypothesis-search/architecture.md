# m1-hypothesis-search アーキテクチャ設計

**作成日**: 2026-07-03
**関連要件定義**: [requirements.md](../../spec/m1-hypothesis-search/requirements.md)
**ヒアリング記録**: [design-interview.md](design-interview.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様・M0 実装に依拠 / 🟡 妥当な推測で確定 / 🔴 根拠なし推測

---

## システム概要 🔵

M0 の「候補セット固定の逐次精密化」の前段に**多仮説木探索エンジン**を挿入する。
観測パターンと候補相集合から、(1) 観測ピーク検出 → (2) 相ごとのピークマッチング →
(3) Jaccard 等構造縮約 → (4) 動的枝刈り → (5) 探索モード精密化による木探索 →
(6) BIC 一次評価 → (7) Jenks 良好解抽出 → (8) 未マッチピーク報告、を実行する。
付随して .gpx 書き出し (FR-505) と読み取り専用 Web UI を提供する。

## アーキテクチャパターン 🔵

**信頼性**: 🔵 *CLAUDE.md / M0 設計の踏襲*

- **パターン**: M0 と同じ「不変データ + Protocol 境界 + 追記専用ストア」のレイヤード構成
- **選択理由**: P2 (非破壊)・P7 (バックエンド交換可能性)・NFR-102 (再現性) を M0 で実証済み。
  木探索はその上の純粋なオーケストレーション層として実装し、Worker 並列化 (NFR-104, M-later)
  を阻害しない純関数的ノード評価とする (REQ-404)

## コンポーネント構成

### 新規モジュール 🔵/🟡

| モジュール | 役割 | 要件 | 信頼性 |
|---|---|---|---|
| `tsumugin/search/peaks.py` | 観測ピーク検出 (numpy 局所極大+高さ閾値) | REQ-002 | 🟡 実装式は推測 |
| `tsumugin/search/matcher.py` | PeakMatcher: マッチングスコア・未マッチピーク | REQ-002/005 | 🔵 FR-111/117 |
| `tsumugin/search/clustering.py` | Jaccard 等構造クラスタ + FoM 代表選出 + Jenks breaks | REQ-103/104 | 🔵 FR-114/116 |
| `tsumugin/search/pruning.py` | スコア累積分布の変曲点による動的閾値 | REQ-101 | 🔵 FR-112 (式は🟡) |
| `tsumugin/search/tree.py` | HypothesisTreeSearch: 木探索本体 | REQ-001/102/201/202 | 🔵 FR-110/113/115 |
| `tsumugin/export/gpx.py` | export_gpx: .gpx 書き出し | REQ-006/105 | 🔵 FR-505 |
| `tsumugin/webui/app.py` | FastAPI アプリ (read-only) + serve() | REQ-007 | 🟡 |
| `tsumugin/webui/static/index.html` | 単一ページの結果ビュー | REQ-007 | 🟡 |

### 再利用する M0 資産 🔵

- `RefinementBackend` (Simulated / GSASII) — ノードの探索モード精密化 (scale+lattice, 少サイクル)
- `EvidenceBackend` (BIC 既定) + `evidence.ranking.rank` — 一次評価・確率・僅差競合
- `Ledger` / `SnapshotStore` — 全探索操作の記録 (REQ-402)
- `StagedRefinementEngine` — 良好解クラスタの最終フル精密化 (FR-113 の「検証エンジン」)
- `errors.GSASUnavailableError` — .gpx の未導入時エラー

### 依存関係の追加 🟡

- optional extra `web`: `fastapi`, `uvicorn` (+ dev: `httpx` — TestClient 用)
- コア依存は numpy のみを維持 (ピーク検出は自前実装、scipy 不使用)

## ディレクトリ構造 🔵

```
src/tsumugin/
├── search/
│   ├── __init__.py      # 公開 API re-export
│   ├── peaks.py         # Peak, find_peaks()
│   ├── matcher.py       # MatchResult, match_score(), unmatched_peaks()
│   ├── pruning.py       # dynamic_threshold()
│   ├── clustering.py    # jaccard_clusters(), fom(), jenks_breaks()
│   └── tree.py          # SearchConfig, HypothesisTreeSearch, SearchResult
├── export/
│   ├── __init__.py
│   └── gpx.py           # export_gpx()
└── webui/
    ├── __init__.py
    ├── app.py           # create_app(), serve()
    └── static/index.html
tests/
├── test_peaks.py, test_matcher.py, test_pruning.py, test_clustering.py,
├── test_tree_search.py, test_gpx_export.py, test_webui.py
```

## 主要設計決定

### D1: 探索木の展開戦略 🔵/🟡

**信頼性**: 🔵 *FR-110/111/115* (best-first の選択は 🟡)

- ノード = 相組合せ (frozenset of candidate index)。根 = 空集合
- **Best-first 展開**: 生存候補をマッチングスコア降順で試行。深さ d の仮説に候補を 1 相追加した
  子を評価し、**Rwp 改善が r_improve_pct (既定 2.0 ポイント) 以上**の子のみ展開キューへ
- 停止条件: max_phases (既定 5) 到達、改善なし、キュー空
- 評価済みノードはすべて `Hypothesis` (status=refined) として保持 — 枝刈り理由は ledger へ
- 同一組合せの重複評価は組合せキー (ソート済みインデックスタプル) で排除

### D2: 探索モード精密化 🔵

**信頼性**: 🔵 *FR-113「保守的設定」*

- backend.refine を直接呼ぶ (StagedRefinementEngine は使わない): free = 全相の scale + lattice.a/b/c、
  max_cycles = explore_max_cycles (既定 5)
- 失敗 (chi2=inf) は当該ノードの降格として扱い探索は継続 (EDGE-004)

### D3: 最終検証精密化 🟡

**信頼性**: 🟡 *FR-113「精密化の前倒し」+ M0 資産活用からの推測*

- Jenks 良好クラスタの仮説 (上位 max_final_refine 件、既定 3) に対してのみ
  StagedRefinementEngine のフルテンプレートを適用し、metrics を更新して再ランキング
- config で無効化可能 (`final_full_refine=False`)

### D4: FoM と ΔU 🔵

**信頼性**: 🔵 *FR-114 式そのまま* (ΔU の M1 での既定は 🟡)

- FoM = 1 / ((1 − fit) + ΔU)。fit = マッチングスコア [0,1]
- M1 では hull エネルギーデータ (FR-103) が無いため ΔU は `PhaseCandidate.delta_u` (既定 0.0)
  として入力界面のみ用意

### D5: .gpx 書き出し 🔵

**信頼性**: 🔵 *FR-505 + M0 GSASIIBackend の実装経路*

- `export_gpx(path, phases, two_theta, intensity, ...)`: GSASIIBackend の gpx 構築ヘルパを
  永続パスで実行し `gpx.save()`。ヒストグラム+全相+計算パターン込み
- GSASIIBackend 内の一時 gpx 構築コードを `_build_project()` として抽出・共有

### D6: Web UI 🟡

**信頼性**: 🟡 *interview Q2 で確定した推奨案*

- FastAPI + 同梱静的 HTML 1 枚 (ビルドツール無し、fetch で JSON を描画)
- GET のみ実装 (read-only 保証は「変更系ルートの不存在」で担保、テストで検証)
- `SearchResult.to_summary()` が JSON 化可能な dict を返し、app はそれを配信するだけ
- 既定バインド 127.0.0.1 (NFR-101)

## 非機能要件の実現方法

### パフォーマンス 🟡
- ノード評価は O(生存候補 × 展開仮説) に枝刈りで抑制 (NFR-002)。探索精密化は 5 サイクル上限
- ノード評価関数は (入力, 設定) → 結果の純関数構成で、将来の並列 map 置換が可能 (REQ-404)

### セキュリティ 🟡
- Web UI は localhost バインド既定・認証なし (ローカルツール)。外部公開は非サポートと明記

### 信頼性・再現性 🔵
- 乱数不使用。全ソートはキー明示の安定ソート。ledger ハッシュチェーン検証は既存テスト踏襲

## 技術的制約 🔵

- コア依存は numpy のみ (CLAUDE.md)。web/gsas は optional extra
- GSAS-II 依存機能 (.gpx) は `@pytest.mark.gsas`、未導入環境で自動 skip
- ruff line-length 100 / frozen dataclass / Protocol 境界 / TDD 厳守

## 関連文書

- **データフロー**: [dataflow.md](dataflow.md)
- **型定義**: [interfaces.py](interfaces.py)
- **API 仕様**: [api-endpoints.md](api-endpoints.md)
- **DB スキーマ**: なし — M1 は永続 DB を導入しない (Project Store HDF5+SQLite は M2 ledger/snapshot 永続化で検討) 🔵

## 信頼性レベルサマリー

- 🔵 青信号: 14 件 (61%) / 🟡 黄信号: 9 件 (39%) / 🔴: 0 件

**品質評価**: 高品質 (推測はアルゴリズム実装式・Web UI 詳細に限定され、いずれも要件へ遡及可能)
