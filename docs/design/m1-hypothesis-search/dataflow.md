# m1-hypothesis-search データフロー図

**作成日**: 2026-07-03
**関連アーキテクチャ**: [architecture.md](architecture.md)
**関連要件定義**: [requirements.md](../../spec/m1-hypothesis-search/requirements.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 木探索の全体フロー 🔵

**信頼性**: 🔵 *FR-110〜117 / REQ-001〜106*

```mermaid
flowchart TD
    A[観測パターン 2θ, I] --> B[find_peaks: 観測ピーク検出]
    C[候補相集合 PhaseCandidate*N] --> D[match_score: 相ごとのマッチング]
    B --> D
    D --> E[jaccard_clusters: 等構造縮約\n代表=FoM最大, 他は alternatives]
    E --> F[dynamic_threshold: 変曲点枝刈り\n(候補<4 は全展開)]
    F --> G[木探索 best-first]
    G --> G1[ノード=相組合せ\nbackend.refine 探索モード\nscale+lattice, ≤5cycles]
    G1 --> G2{Rwp改善 ≥ 2pt?}
    G2 -->|yes, 相数<5| G
    G2 -->|no| G3[枝打ち切り\nledger: prune 記録]
    G1 --> H[BIC 一次評価\nmetrics.evidence]
    H --> I[rank: softmax確率+僅差競合]
    I --> J[jenks_breaks: 良好解クラスタ]
    J --> K[StagedRefinementEngine\n良好解のみフル精密化 🟡]
    K --> L[unmatched_peaks: 未マッチ報告\n未知相フラグ]
    L --> M[SearchResult]

    G1 -.->|全操作| N[(Ledger 追記)]
    K -.-> N
    G3 -.-> N
```

## シーケンス: search() 呼び出し 🔵

```mermaid
sequenceDiagram
    participant U as 呼び出し元
    participant T as HypothesisTreeSearch
    participant P as PeakMatcher
    participant B as RefinementBackend
    participant E as EvidenceBackend(BIC)
    participant L as Ledger

    U->>T: search(2θ, I, candidates)
    T->>P: find_peaks(2θ, I)
    P-->>T: observed peaks
    loop 各候補相
        T->>P: match_score(candidate, observed)
        T->>L: append("match_score", ...)
    end
    T->>T: jaccard_clusters → 代表選出
    T->>L: append("cluster", 代表/代替)
    T->>T: dynamic_threshold → 生存候補
    T->>L: append("prune_threshold", ...)
    loop 木探索 (best-first, 重複組合せ排除)
        T->>B: refine(組合せ, scale+lattice, ≤5cyc)
        B-->>T: RefinementResult (失敗は chi2=inf)
        T->>E: score(metrics)
        T->>L: append("node_refine"/"branch_prune", ...)
    end
    T->>T: rank + jenks_breaks
    opt final_full_refine (既定 on)
        T->>B: StagedRefinementEngine.run (良好解のみ)
        T->>L: append(stage系列)
    end
    T->>P: unmatched_peaks(最良仮説)
    T-->>U: SearchResult (ranked/tree/unmatched/ledger)
```

## .gpx 書き出しフロー 🔵

**信頼性**: 🔵 *FR-505 / M0 GSASIIBackend の経路*

```mermaid
flowchart LR
    A[Hypothesis or phases+data] --> B{gsasii_available?}
    B -->|no| C[GSASUnavailableError]
    B -->|yes| D[G2Project 構築\n.xye/.instprm/CIF 生成]
    D --> E[ヒストグラム+相を登録\nmax cyc 0 で計算]
    E --> F[gpx.save → path]
    F --> G[GSAS-II GUI で開ける .gpx]
```

## Web UI データフロー 🟡

**信頼性**: 🟡 *interview Q2 の確定案*

```mermaid
sequenceDiagram
    participant Br as ブラウザ
    participant W as FastAPI (127.0.0.1)
    participant R as SearchResult (メモリ上)

    Br->>W: GET /
    W-->>Br: index.html (静的)
    Br->>W: GET /api/result
    W->>R: to_summary()
    R-->>W: dict (ranked/unknown_flag/...)
    W-->>Br: JSON
    Br->>W: GET /api/hypotheses/{id}
    W-->>Br: 仮説詳細 JSON (相・格子・metrics)
    Note over W: 変更系ルートは存在しない (read-only)
```

## エラーハンドリングフロー 🔵

**信頼性**: 🔵 *EDGE-001〜004 / M0 規約*

```mermaid
flowchart TD
    A{事象} -->|候補ゼロ| B[空 SearchResult, 例外なし]
    A -->|観測ピークなし| C[全スコア0 → 空良好解+警告フィールド]
    A -->|ノード精密化失敗| D[chi2=inf → 当該枝降格, 探索続行]
    A -->|全仮説高R| E[unknown_phase_flag=True + 要確認]
    A -->|.gpx & GSAS-II未導入| F[GSASUnavailableError 送出]
    A -->|不明な hypothesis id (Web)| G[404 JSON]
```

## データ整合性 🔵

- SearchResult 内の全 ID (`hyp-XXXX`) は reports / ranked / tree で一意・整合 (M0 pipeline 規約)
- ledger は search() ごとに単一インスタンス、`verify()` True を保証
- 仮説の親子関係は parent_id のみで表現 (グラフ構造の別持ちはしない — 単一情報源)

## 信頼性レベルサマリー

- 🔵: 5 フロー / 🟡: 1 フロー (Web UI) / 🔴: 0

**品質評価**: 高品質
