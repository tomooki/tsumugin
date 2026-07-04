# m5-nested-mem-oed データフロー図

**作成日**: 2026-07-04
**関連**: [architecture.md](architecture.md) / [requirements.md](../../spec/m5-nested-mem-oed/requirements.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## (a) 階層的裁定フロー (bic 一次 → 競合抽出 → nested 再裁定 → 統合) 🔵

**信頼性**: 🔵 *FR-122 / REQ-010〜013/102/201 — 探索段 bic 固定・僅差競合のみ nested*

```mermaid
flowchart TD
    A[生存仮説群 Hypothesis\n木探索は bic 固定 REQ-010/201] --> B[rank BICBackend\n一次順位・確率・close_competitor]
    B --> C{close_competitor 群あり?\nΔBIC<10 REQ-011}
    C -->|no / problems・nested 未供給| D[bic 一次を最終結果\n下段スキップ REQ-102/EDGE-003]
    C -->|yes| E{full_nested 設定?}
    E -->|yes| F[全生存仮説を nested 対象\nREQ-012/EDGE-004]
    E -->|no 既定| G[close_competitor 群のみ nested 対象]
    F --> H[各対象: problems から EvidenceProblem]
    G --> H
    H --> I[nested.run_with_fallback\nvalue=-logZ + logz_err]
    I --> J{30 分超過?\nNFR-103}
    J -->|yes| K[打ち切り + Laplace 代替 + 警告\ntruncated=True REQ-101/EDGE-002]
    J -->|no| L[logZ±誤差で evidence 差し替え]
    K --> M[統合ランキング再構成\n確率再計算・adjudicated_by 明示]
    L --> M
    D --> M
    M --> N[ArbitrationResult\nnested_ids 昇順・primary_backend]
    B -.-> Z[(Ledger)]
    I -.-> Z
    M -.-> Z
```

- **決定論**: 仮説 ID 昇順で処理。nested は種固定 + logZ±誤差 (ビット同一でなく誤差範囲一致, EDGE-014)。
- **記録 (REQ-013)**: どの仮説を bic 一次で確定し、どの競合を nested 再裁定したかを理由付きで ledger 追記。

## (a') 確率較正フロー (reliability diagram / ECE, bic/nested 別系列) 🔵

```mermaid
flowchart LR
    A[較正ベンチ CalibrationSample\n予測確率・真偽・backend] --> B[calibrate_by_backend\nbackend で系列分離 REQ-016/106]
    B --> C[bic 系列]
    B --> D[nested 系列 EDGE-012]
    C --> E[reliability_diagram\n等幅ビン・下端昇順 REQ-017]
    D --> F[reliability_diagram]
    E --> G[expected_calibration_error\nΣ count/N·|acc−conf|]
    F --> H[expected_calibration_error]
    G --> I[CalibrationReport backend=bic\nprobability_semantics=BIC 近似]
    H --> J[CalibrationReport backend=nested\nprobability_semantics=logZ NFR-004]
```

## (b) MEM 解析フロー (joint 結果 → F_obs → MEM 入力 → Dysnomia → 密度/断面/ボンド経路) 🔵

**信頼性**: 🔵 *FR-600〜606 / REQ-021〜031*

```mermaid
flowchart TD
    A[JointVerificationResult\n生存仮説 joint 検証済み] --> B[check_mem_applicability\n単相/主相支配? REQ-030]
    B --> C{推奨条件 満たす?}
    C -->|no 多相/低統計| D[信頼性警告 warnings\nMEM 実行は継続・除外しない REQ-031/103/EDGE-007]
    C -->|yes| E[extract_structure_factors\nF_obs 位相=モデル由来 REQ-021]
    D --> E
    E --> F[build_mem_input\nprobe→密度種別 REQ-022\nxray=電子密度 / neutron=核密度\n反射 h,k,l 昇順 REQ-023]
    F --> G[MEMBackend.run\nDysnomiaBackend 遅延 import]
    G --> H{Dysnomia 導入?}
    H -->|no| I[MEMUnavailableError\nEDGE-006・破壊操作なし]
    H -->|yes| J[入力ファイル生成→バイナリ実行→回収\n入出力契約固定 REQ-406]
    J --> K[MEMResult\n密度マップ.grd + 統計]
    K --> L[write_density_map .grd REQ-027]
    K --> M[extract_cross_section 1D/2D REQ-028]
    K --> N[bond_path_min_density\n伝導ボトルネック REQ-029]
    B -.-> Z[(Ledger)]
    G -.-> Z
```

## (c) MEM-Rietveld 反復ループ (既定オフ・子スナップショット追記) 🔵

**信頼性**: 🔵 *FR-603 / REQ-024/025/026/107/202 — 親不変・追記のみ*

```mermaid
flowchart TD
    A[run_mem_rietveld] --> B{config.enabled?\n既定オフ REQ-024}
    B -->|no| C[stop_reason=disabled\n即返し・反復しない]
    B -->|yes| D[反復 iter=0]
    D --> E[MEM 密度 → F_calc 更新 → 再精密化\nMPF サイクル]
    E --> F[snapshots.save 子スナップショット追記\nlabel=mem_rietveld_iter{n} REQ-025/202]
    F --> G{発散?\n密度負値/R 悪化 REQ-107}
    G -->|yes| H[当該サイクルは子に残し停止\nstop_reason=diverged\nledger 記録 EDGE-008]
    G -->|no| I{収束?\nR/密度変化 < tol REQ-026}
    I -->|yes| J[stop_reason=converged\nledger 記録]
    I -->|no| K{max_iter 到達?}
    K -->|yes| L[stop_reason=max_iter\nledger 記録 EDGE-009]
    K -->|no| M[iter += 1]
    M --> E
    F -.-> S[(SnapshotStore 追記型)]
    H -.-> Z[(Ledger)]
    J -.-> Z
    L -.-> Z
```

- **親不変 (REQ-202/NFR-005)**: 元 joint 精密化済み仮説 (親スナップショット) は書き換えない。
- **P2**: SnapshotStore は save/revert のみ (削除/上書き API なし)。ロールバックは revert 経由・破壊しない。

## (d) OED 提案フロー (僅差競合 → 測定提案 JSON) 🔵

**信頼性**: 🔵 *FR-431/432 / REQ-035/037/038/EDGE-010 — 非破壊・提案のみ*

```mermaid
flowchart TD
    A[ranked RankedHypothesis\nrank の close_competitor] --> B{僅差競合あり?\nΔBIC/ΔlogZ < 閾値 REQ-038}
    B -->|no| C[提案 空 tuple\n状態変更なし EDGE-010]
    B -->|yes| D[判別測定提案 生成\n高統計再測定/追加温度点/\njoint 用中性子測定/組成分析 REQ-035]
    D --> E[estimated_information_gain\nv1 簡易近似 REQ-304]
    E --> F[情報利得降順 + kind 昇順\n決定論 REQ-402]
    F --> G[proposals_to_json\nfinite_or_none 純化]
    G --> H[OED 提案 JSON\n情報利得順]
    D -.->|ledger 追記のみ・非破壊| Z[(Ledger)]
    H --> I{PyBOED 獲得関数接続?\nacquire 境界}
    I -->|未導入| J[OEDUnavailableError\n提案生成 v1 は動作 REQ-105/EDGE-011]
    I -->|v1| K[提案生成のみ・獲得関数実行しない REQ-036]
```

- **非破壊 (REQ-037)**: 仮説の accepted/rejected 化・データ改変を一切伴わない。ledger 追記記録のみ (P2)。

## (e) run_mem MCP フロー (MEMBackend 実体化) 🔵

**信頼性**: 🔵 *FR-513 / REQ-033/034/104/EDGE-006/013 — placeholder 契約維持・破壊操作なし*

```mermaid
sequenceDiagram
    participant C as MCP クライアント
    participant S as server.py アダプタ (SDK 依存)
    participant T as tools.py run_mem (SDK 非依存)
    participant B as mcp/mem.py run_mem_boundary
    participant M as MEMBackend (DysnomiaBackend)
    participant L as Ledger / SnapshotStore

    C->>S: run_mem(hypothesis_id, frame_index)
    S->>T: run_mem(session, **params)
    T->>B: run_mem_boundary(session, mem_backend, ...)
    alt placeholder=True (M4 後方互換)
        B-->>T: {status: not_implemented, milestone: M5} REQ-033
    else mem_backend 供給
        B->>M: build_mem_input → run
        alt Dysnomia 未導入
            M-->>B: MEMUnavailableError
            B-->>T: {status: error, error: mem_unavailable} REQ-104/EDGE-006
        else 実行成功
            M-->>B: MEMResult (密度マップ/断面/最小密度/警告)
            B->>L: 子スナップショット追記 + ledger 記録 (破壊なし)
            B-->>T: 素の型 dict (finite_or_none 純化) REQ-034/EDGE-013
        end
    end
    T-->>S: dict
    S-->>C: JSON-RPC 応答 (allow_nan=False 安全 TC-511-04)
```

## nested/mem/oed 縮退・境界のフロー 🔵

```mermaid
flowchart TD
    A{事象} -->|dynesty/ultranest 未導入で nested 実行| B[NestedUnavailableError\nコア import は成功 REQ-005/EDGE-001]
    A -->|nested 30 分超過| C[打ち切り + Laplace 代替 + 警告\ntruncated=True・例外化しない REQ-101/EDGE-002]
    A -->|Dysnomia 未導入で MEM 実行| D[MEMUnavailableError\n破壊操作なし REQ-020/EDGE-006]
    A -->|MEM 適用ガード非充足| E[信頼性警告のみ・MEM 実行継続\n仮説除外しない REQ-031/EDGE-007]
    A -->|MEM-Rietveld 発散| F[子スナップショットに残し停止\nledger 記録・破壊しない REQ-107/EDGE-008]
    A -->|PyBOED 未導入で acquire| G[OEDUnavailableError\n提案生成 v1 は動作 REQ-105/EDGE-011]
    A -->|僅差競合なしで OED| H[提案 空・状態変更なし REQ-038/EDGE-010]
    A -->|Laplace の Hessian 特異| I[BIC 近似フォールバック + 警告 REQ-002/EDGE-005]
```

## データ整合性 🔵

- nested 裁定振り分け・MEM 反復サイクル・OED 提案・較正結果は ledger に理由付き記録 (P2/NFR-105)。
  `ledger.verify()` は M5 全操作を通しても常時 True (TC-514-01)。
- MEM 適用ガードで仮説は除外されない — 警告が付くのみ (Dara 教訓・REQ-031)。
- MEM-Rietveld 反復は子スナップショット追記 (親 joint 結果は不変)。削除/上書き API なし (REQ-202/P2)。
- OED 提案・run_mem・nested 裁定は生データを書き換えない (推奨/評価/委譲のみ・自動適用なし)。
- nested の logZ は種固定でも確率的 → ビット同一でなく logZ±誤差で再現性を保証 (NFR-102 の nested 例外)。
- nested 打ち切り・MEM 未導入・Laplace 特異・OED 未導入は例外を上げず縮退値/error dict で解析を止めない。

## 信頼性レベルサマリー

- 🔵: 7 フロー / 🟡: 0 (数値閾値・MPF 詳細は architecture.md D2/D3/D5/D6 へ集約) / 🔴: 0 — **品質評価**: 高品質
