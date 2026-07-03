# Plan: m0-refinement-core

Tsumugin **M0 (PoC)** の中核実装。仕様 [tsumugin_spec_v0.3.md](../../../tsumugin_spec_v0.3.md)
のマイルストーン M0「GSASIIscriptable ラッパ + 段階戦略 + ガードレール。単一パターン自動多相精密化」を、
GSAS-II 非導入環境でも end-to-end 検証できる形で構築する。

## Requirements Summary

対象 FR:
- **データモデル** (§4): Project / Dataset / Frame / HistogramRef / Hypothesis / PhaseInstance。
- **RefinementBackend 抽象** (P7, §3.1): Protocol + `SimulatedBackend`(合成パターンの実 LM フィット) +
  `GSASIIBackend`(薄いラッパ、contract test は skip 条件付き)。
- **段階的パラメータ解放** (FR-200 / FR-201 / FR-202): scale+bg → lattice+zero → profile → texture →
  occupancy → coordinates → ADP のテンプレート駆動。収束判定・悪化時の固定戻し。
- **ガードレール** (FR-210): 発散検知(χ²発散/負占有率/格子暴走/負定値ADP/相分率ゼロ張り付き)、
  自動ロールバック→原因固定→再試行、3回失敗でエスカレーション。理由付き ledger 記録(FR-214)。
- **Evidence Engine** (FR-120/121/124): EvidenceBackend 抽象 + `bic`(既定)/`aic`。softmax+温度較正で
  仮説確率。ΔBIC<10 の僅差競合フラグ(FR-122 の1段目のみ、nested は M5)。
- **Ledger / Snapshot** (P2 / NFR-101 / NFR-105): 追記専用 + ハッシュチェーン、任意時点へ revert。
  破壊的操作の API を実装しない。

スコープ外(M1+): 多仮説木探索(FR-110)、シーケンシャル(FR-300)、operando(FR-310)、
中性子 joint(FR-240)、MEM(FR-600)、nested sampling、Web/REST/MCP。

## Design Overview

インターフェースファースト。境界は 3 つ:
1. `RefinementBackend` (Protocol) — `refine(model, free_params) -> RefinementResult`。実解析エンジンを差し替え可能に。
2. `EvidenceBackend` (Protocol) — `score(metrics) -> EvidenceResult`。bic/aic を差し替え可能に。
3. `Ledger` / `SnapshotStore` — 追記専用ストア。全状態遷移の単一の記録先。

データフロー(単一パターン自動多相精密化):
```
Project(observed data + 初期 PhaseInstance 群)
  └─> StagedRefinementEngine
        stage ごとに: SnapshotStore.save → Backend.refine → Guardrails.check
                       → (違反なら revert+原因固定+retry / 3回で escalate)
                       → Ledger.append(理由付き)
        └─> refined Hypothesis(metrics 付き)
  └─> EvidenceEngine.rank([Hypothesis...]) → softmax 確率 + 僅差競合フラグ
```

不変性: モデルは frozen dataclass。更新は新インスタンス生成 + Snapshot 追記のみ(P2)。

## Task Dependency Graph

```
001-core-model ──┬─> 002-backend-interface ──┬─> 003-simulated-backend ─┐
                 │                            └─> 004-gsasii-backend-stub │
                 │                            └─> 007-guardrails ─────────┤
                 ├─> 005-ledger ──> 006-snapshot-store ────────────────────┤
                 └─> 009-evidence-engine                                    │
                                                                            ▼
              003,006,007 ─────────────────────> 008-staged-engine ──> 010-integration
                                                          009 ─────────────┘
```

実装順(依存トポロジ順): 001 → 005 → 002 → 009 → 003 → 004 → 006 → 007 → 008 → 010

追補: 011-gsasii-backend-real (004/008 依存) — GSAS-II 導入と GSASIIBackend の実体化。
M1 の先行分だが、実バックエンドでの M0 受け入れ検証としてこの Plan に含めた。

## Cross-Plan Dependencies

なし(新規プロジェクトの基盤)。後続 Plan(木探索・シーケンシャル)は本 Plan の
`RefinementBackend` / `Ledger` / `Hypothesis` を共有インターフェースとして利用する。
