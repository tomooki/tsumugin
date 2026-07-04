# m4-joint-mcp データフロー図

**作成日**: 2026-07-04
**関連**: [architecture.md](architecture.md) / [requirements.md](../../spec/m4-joint-mcp/requirements.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## M4 全体フロー (探索プライマリ → joint 検証 → コントラスト → 降格 → 選択) 🔵

**信頼性**: 🔵 *FR-245 → FR-242 → FR-244 → FR-412 → FR-402 の順序*

```mermaid
flowchart TD
    A[Project: Frame.histograms\nxray + neutron_cw/tof + TofBankParams] --> B[プライマリヒスト 1 本を抽出\nFR-245 探索コスト抑制]
    B --> C[HypothesisTreeSearch.search\n既存 M1 資産・探索段は不変 REQ-202]
    C --> D[SearchResult.ranked\n生存仮説 = 良好解]
    D --> E[verify_survivors FR-242\n生存仮説のみ joint 検証精密化]
    E --> F[JointRefinementModel 構築\n構造共有 free + ヒスト独立 scale/bg/profile]
    F --> G{backend 種別}
    G -->|GSASIIBackend| H[GSAS-II ネイティブ\nマルチヒストグラム 1 gpx]
    G -->|SimulatedBackend| I[ヒストごと refine → χ² 合算\n共有構造は χ² 和で更新]
    H --> J[集約 RefinementResult\nΣχ² / 結合 Rwp / 共有構造 ±σ\nglobals: histK.rwp/scale REQ-006]
    I --> J
    J --> K[recommend_occupancy_release FR-244\njoint データありのみ発火 REQ-104]
    K --> L[rank_with_plausibility FR-412\n素 rank → 降格のみ・除外しない]
    L --> M[FinalSelectionEngine.decide\nagent/human 同一適用 FR-402]

    E -.-> N[(Ledger)]
    K -.-> N
    L -.-> N
    M -.-> N
```

## joint 検証精密化のフロー 🔵

```mermaid
flowchart LR
    A[生存仮説 phases + JointHistogram 群] --> B[HistogramWeighting\n既定 統計重み 1/σ²\n経験重みはオプション FR-243]
    B --> C[各ヒスト: backend.refine\nヒスト独立 free_params]
    C --> D{全ヒスト有限?}
    D -->|no| E[当該ヒスト chi2=inf\njoint 全体は継続 EDGE-001]
    D -->|yes| F[共有構造を χ² 和で更新\nブロック座標降下 簡易版]
    E --> G[集約: Σχ²=inf\nwarnings に失敗ヒスト明示]
    F --> H[集約: Σχ² / 結合 Rwp\n共有構造 ±σ]
    G --> I[単一 RefinementResult\n+ JointRefinementResult 詳細]
    H --> I
    I --> J[σ 由来を warnings に明示\n共分散/ヒスト重み由来 NFR-107]
```

## コントラスト占有率解放判定のフロー 🔵

```mermaid
flowchart TD
    A{joint データあり?\nヒスト≥2 かつ probe種別≥2} -->|no| B[提案空・警告なく続行\nREQ-104/EDGE-004]
    A -->|yes| C[各サイトの占有元素対 A,B]
    C --> D[f_norm = f_A/f_A+f_B  Z近似\nb_norm = b_A/|b_A|+|b_B|  静的表]
    D --> E{|f_norm − b_norm| ≥ 閾値?\n既定 0.15}
    E -->|no| F[コントラスト不十分\n提案しない]
    E -->|yes| G[占有率解放を戦略へ追加提案\nglobal.occ.site 命名]
    F --> H{全サイト閾値未満?}
    H -->|yes| I[提案空・警告なく続行\nREQ-103/EDGE-003]
    G --> J[ledger 記録: どのサイトをなぜ\ncontrast_occupancy_recommend REQ-012]
    J --> K[自動適用しない・推奨のみ\nREQ-011/TC-404-06]
```

## ChemPlausibility 降格 rank のフロー 🔵

**最重要不変条件**: 降格のみ・候補除外しない (Dara 教訓, REQ-019)

```mermaid
flowchart TD
    A[joint 検証済み仮説群] --> B[evidence.ranking.rank\n素の BIC 順位・確率 p]
    B --> C{ChemPlausibility\nモジュール登録あり?}
    C -->|no| D[素の rank をそのまま返す\nREQ-105/EDGE-006]
    C -->|yes| E[各仮説の各相を評価\nscore PhaseRef, SynthesisContext]
    E --> F[複数モジュール合成\n重み付き幾何平均 REQ-018]
    F --> G{module が score=0?}
    G -->|yes| H[幾何平均で降格が伝播\n除外はしない EDGE-007]
    G -->|no| I[相スコア s∈0,1]
    H --> J[仮説スコア = 相スコア合成]
    I --> J
    J --> K[p' = p · s で確率補正\n再正規化して並べ替え]
    K --> L[低スコア相も rank に残る\n順位が下がるだけ EDGE-005]
    L --> M[ledger 記録: 降格スコアと理由]
```

## MCP submit → list → compare → accept → revert のフロー 🔵

```mermaid
sequenceDiagram
    participant C as MCP クライアント
    participant S as server.py アダプタ (SDK 依存)
    participant T as tools.py 実処理 (SDK 非依存)
    participant A as M0〜M3 資産
    participant L as Ledger

    C->>S: submit_analysis(pattern, candidates)
    S->>T: submit_analysis(session, ...)
    T->>A: analyze_single_pattern / verify_survivors
    A-->>T: SearchResult / ranked
    T->>L: append(mcp_submit, reason)
    T-->>S: {hypotheses: [...]}
    S-->>C: JSON-RPC 応答

    C->>S: list_hypotheses / compare_hypotheses
    S->>T: 実処理 (session)
    T->>A: SearchResult.to_summary / rank
    T-->>S: {ranked: [...]}
    S-->>C: 応答

    C->>S: accept_hypothesis(id, by="agent")
    S->>T: accept_hypothesis(session, id, by)
    alt final_selection_mode == "human" かつ by="agent"
        T-->>S: {status: recommend_only} 拒否 REQ-106
    else agent モード
        T->>A: FinalSelectionEngine.accept(by)
        T->>L: append(mcp_accept, reason)
        T-->>S: {status: accepted}
    end
    S-->>C: 応答

    C->>S: revert(id)
    S->>T: revert(session, id)
    T->>A: FinalSelectionEngine.revert (superseded 化・追記型)
    T->>L: append(mcp_revert, reason)
    T-->>S: {status: superseded} 件数減らない REQ-024
    S-->>C: 応答
```

## MCP 縮退・境界のフロー 🔵

```mermaid
flowchart TD
    A{事象} -->|mcp SDK 未導入で create_mcp_server| B[MCPUnavailableError\n実処理関数は動作 REQ-102/EDGE-009]
    A -->|run_mem 呼び出し| C[MEMUnavailableError または\nプレースホルダ M5委譲・破壊操作なし REQ-101/EDGE-008]
    A -->|export_gpx が GSAS未導入| D[GSASUnavailableError を\nMCP エラーへ変換 EDGE-011]
    A -->|human モードで agent accept| E[accepted 化拒否・推奨提示 EDGE-010]
    A -->|MCP 破壊操作要求| F[API 表面に存在しない\nrevert=superseded のみ REQ-024/TC-407-09]
```

## データ整合性 🔵

- joint 昇格・コントラスト提案・ChemPlausibility 降格・MCP 全操作は ledger に理由付き記録 (P2/NFR-105)
- ChemPlausibility 降格で候補は削除されない — 順位が下がるのみ (Dara 教訓・REQ-019)
- MCP `revert` は superseded 化 (追記型)。accept 履歴は残り件数は減らない (REQ-024)
- コントラスト提案・run_mem は状態を書き換えない (推奨/委譲のみ・自動適用なし)
- joint のヒスト欠損・失敗は chi2=inf として明示 (捏造しない)

## 信頼性レベルサマリー

- 🔵: 6 フロー / 🟡: 0 (詳細閾値は architecture.md D4/D5 へ集約) / 🔴: 0 — **品質評価**: 高品質
