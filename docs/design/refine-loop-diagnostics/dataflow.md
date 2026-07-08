# refine-loop-diagnostics データフロー

**作成日**: 2026-07-09
**関連アーキテクチャ**: [architecture.md](architecture.md)
**関連要件定義**: [requirements.md](../../spec/refine-loop-diagnostics/requirements.md)

**【信頼性レベル凡例】**: 🔵 要件/設計/実装参照 / 🟡 妥当な推測 / 🔴 未参照推測

---

## 全体: 閉ループ (第2層b) のデータフロー 🔵

**信頼性**: 🔵 *orchestrator.run_refinement_loop 現行 + 拡張点*

```mermaid
flowchart TD
    A[AnalysisInput<br/>histograms/phases/bg/extra_stages] --> R[runner<br/>build_recipe + run_auto_rietveld]
    R --> Res[AutoRietveldResult<br/>+ 内省フィールド REQ-001]
    Res --> D[diagnose_residual REQ-002<br/>残差配列 + 内省 → ResidualFeatures]
    D --> P[propose_next_actions REQ-003<br/>候補を別々に列挙 safe優先/決定論]
    P --> Pol[RuleBasedPolicy.decide<br/>SafeAction のみ・既試行除外]
    Pol -->|Stop| Out[RefinementLoopResult<br/>best + open_proposals]
    Pol -->|action| Ap[action.apply → runner]
    Ap --> Acc{_accept?<br/>Rwp↓ ∧ validity REQ-201}
    Acc -->|yes| Keep[inp=cand / best 更新] --> D
    Acc -->|no| Rev[revert 据え置き] --> D
```

**拡張点** (本要件): 🔵
- `runner` が `AutoRietveldResult` に**内省フィールド**を詰める (REQ-001)。
- `diagnose_residual` が背景のみの粗診断を置換し、**多シグナル**を算出 (REQ-002)。
- `propose_next_actions` が新シグナルに対し**別々の候補**を列挙 (REQ-003/101〜106)。
- `_accept`・`policy`・ループ制御は**不変** (核心原理保持)。

## 診断シグナル → トライ候補の対応 🔵

**信頼性**: 🔵 *serious-flow §6・GAP 表B より*

```mermaid
flowchart LR
    subgraph Signals[ResidualFeatures 新シグナル]
      S1[asymmetry_metric]
      S2[intensity_bias_metric]
      S3[peak_width_ratio]
      S4[bg_extrema 過多]
      S5[atom_uiso 発散]
      S6[hist_absorption 不確実]
    end
    S1 -->|別々| C1a[ReleaseParams Zero]
    S1 -->|別々| C1b[ReleaseParams 非対称 SH·L/alpha]
    S2 --> C2[ReleaseParams preferred_orientation]
    S3 -->|別々| C3a[ReleaseParams U,V,W]
    S3 -->|別々| C3b[ReleaseParams X,Y]
    S3 -->|別々| C3c[ReleaseParams size_strain]
    S4 --> C4[AdjustBackground 減項]
    S5 --> C5[RestrictUiso labels]
    S6 --> C6[SetAbsorption free/物理/0]
```

各候補は独立提案。policy が優先度順に 1 つ試し `_accept` が採否 → 「別々に試して観察」を実現
(REQ-003, DD-2)。経験則 prior は priority を偏らせるのみ (REQ-301, DD-4)。

## 非対称/位置の切り分けシーケンス 🔵

**信頼性**: 🔵 *serious-flow §6 の切り分け手順より*

```mermaid
sequenceDiagram
    participant D as diagnose_residual
    participant P as propose
    participant Pol as policy
    participant Acc as _accept
    D->>P: asymmetry_metric > tol
    P->>Pol: [候補 Zero, 候補 非対称] (別提案)
    Pol->>Acc: 試行1 Zero 解放
    Acc-->>Pol: Rwp 悪化 → revert (Zero は縮退しがち)
    Pol->>Acc: 試行2 非対称 解放
    Acc-->>Pol: Rwp 改善 → 採用
    Note over Pol,Acc: どちらが効くかは焼き込まず try→revert が決定 (REQ-405)
```

## 第3層: モデル比較オーケストレータ 🔵

**信頼性**: 🔵 *REQ-005/202・compare_models 現行より*

```mermaid
flowchart TD
    V[ModelVariant 列<br/>model5 / model6 / +D 等] --> Loop[各変種を runner で精密化]
    Loop --> CM[compare.compare_models<br/>BIC + validity 序列化]
    CM --> Best[best = 妥当なうち最小 BIC<br/>妥当皆無なら全体最小 best_is_valid=False]
    Best --> L[ledger 追記 verify True]
    L --> Out[ModelComparison<br/>scores/best/best_is_valid]
```

単一モデル調律ループ (`run_refinement_loop`) の**外側**。各変種の精密化に既存 runner を用い、
序列化は `compare_models` に委譲 (DD-6)。

## エラー/縮退フロー 🔵

**信頼性**: 🔵 *EDGE ケースより*

```mermaid
flowchart TD
    A[diagnose_residual] --> B{内省フィールド有?}
    B -->|無 旧result/スタブ| C[該当シグナルを立てない<br/>EDGE-001 縮退]
    B -->|有| D{残差が信号?}
    D -->|空/全ノイズ| E[シグナルなし<br/>EDGE-102 FP回避]
    D -->|有| F[シグナル算出]
    G[model_compare] --> H{妥当な変種有?}
    H -->|無| I[全体最小BIC best_is_valid=False<br/>EDGE-101]
    H -->|有| J[妥当なうち最小BIC]
```

## 関連文書

- **アーキテクチャ**: [architecture.md](architecture.md)
- **型定義**: [interfaces.py](interfaces.py)
- **要件定義**: [requirements.md](../../spec/refine-loop-diagnostics/requirements.md)

## 信頼性レベルサマリー

- 🔵 青信号: 全フロー (要件 + 既存実装に追跡可能)
- 🟡/🔴: 0

**品質評価**: 高品質
