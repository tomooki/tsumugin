# m2-sequential データフロー図

**作成日**: 2026-07-03
**関連**: [architecture.md](architecture.md) / [requirements.md](../../spec/m2-sequential/requirements.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## シーケンシャル解析の全体フロー 🔵

**信頼性**: 🔵 *FR-301/303/304/305/306 (オンライン単一パスは 🟡 D1)*

```mermaid
flowchart TD
    A[FrameSeries\n2θ + 強度行列 + 軸値 + channels] --> B[frame 0:\nStagedRefinementEngine\nフル確立精密化]
    B --> C{frame i = 1..N}
    C --> D[warm start:\n直近成功フレームの phases]
    D --> E[backend.refine 直呼び\nscale+lattice, ≤10 cycles]
    E --> F[フレーム指標計算\nRwp / 格子微分 / 新規未マッチピーク]
    F --> G{複合ロバストz\n> 閾値?}
    G -->|no| H[FrameRecord 確定]
    G -->|yes: changepoint| I[HypothesisTreeSearch\n候補=現行相+候補プール]
    I --> J{新構成が\nevidence 改善?}
    J -->|yes| K[新相構成を採択\nledger: adopt 記録]
    J -->|no| L[現行構成維持\nledger: reject 記録]
    K --> H
    L --> H
    H --> M[LifecycleTracker 更新\nヒステリシス N=3]
    M --> C
    C -->|全フレーム終了| N[lifecycle 確定 + Trajectory 組立]
    N --> O[FinalSelectionEngine.decide\nフレーム裁定 or 系列裁定]
    O --> P[SequentialResult\nTrajectory / lifecycle / decisions]

    E -.->|毎フレーム| Q[(PersistentLedger\nJSONL 追記)]
    I -.-> Q
    O -.-> Q
    B -.->|snapshot| R[(PersistentSnapshotStore)]
    K -.->|snapshot| R
```

## changepoint 複合指標 🔵 (式は 🟡)

```mermaid
flowchart LR
    A[直近 W=5 フレームの\nローリング窓] --> B[Rwp 系列の中央値/MAD]
    A --> C[格子 a/b/c の\nフレーム間差分の中央値/MAD]
    A --> D[新規未マッチピーク数]
    B --> E{z_rwp > 5}
    C --> F{z_lattice > 5}
    D --> G{new_peaks ≥ 1\nかつ z 超過}
    E -->|or| H[changepoint!]
    F -->|or| H
    G -->|or| H
```

- 各指標は独立に検出可能 (TC-102-06)。窓が W 未満の序盤は検出をスキップ (warm-up) 🟡

## 永続化フロー 🔵

```mermaid
sequenceDiagram
    participant E as Engine (M0/M1/M2)
    participant L as PersistentLedger
    participant F as ledger.jsonl

    Note over L: オープン時
    L->>F: 全行読込
    L->>L: ハッシュチェーン再検証 (verify)
    alt 破損検出
        L-->>E: LedgerIntegrityError (ファイル無変更)
    end
    Note over L: 運用時
    E->>L: append(kind, payload)
    L->>L: in-memory 版と同一のハッシュ計算
    L->>F: 1 行追記 ("a" モードのみ)
    L-->>E: LedgerEntry
```

## 最終選択 2 モードのフロー 🔵

**信頼性**: 🔵 *FR-402/403*

```mermaid
flowchart TD
    A[SearchResult / フレーム裁定要求] --> B[detect_escalations\n高R / 未知相 / 僅差 / ガード]
    B --> C{mode}
    C -->|agent| D{エスカレーション\nゼロ?}
    D -->|yes| E[自動 accept\naccepted_by=agent\n根拠を ledger 記録]
    D -->|no| F[暫定裁定 provisional\n+ ReviewQueue 追記\n処理はブロックしない]
    C -->|human| G[推奨順位+根拠の提示のみ\nDecision.recommended]
    G --> H[human が accept API 呼び出し\naccepted_by=human]
    E --> I[Decision 返却]
    F --> I
    H --> I
    I -.-> J[(Ledger)]
    F -.-> K[(ReviewQueue 追記型)]

    L[revert 要求] --> M[superseded 化の追記\n履歴は保持]
    M -.-> J
```

## 高温モードのフロー 🔵

```mermaid
flowchart LR
    A[Trajectory + ExternalChannel T] --> B[格子 vs T\n多項式ベースライン fit 次数1]
    B --> C[逸脱フレーム分離]
    A --> D[相分率 vs T]
    D --> E[midpoint = 50%交差の線形補間\nonset = 10%交差\nσ = 隣接フレーム間隔]
    E --> F[TransitionEstimate]
    C --> G[ThermalReport]
```

## エラーハンドリングフロー 🔵

```mermaid
flowchart TD
    A{事象} -->|フレーム精密化失敗 chi2=inf| B[警告記録 + 最後の成功フレームから継続]
    A -->|空フレーム列| C[空 Trajectory, 例外なし]
    A -->|温度チャネル欠損| D[軸値 None + 警告]
    A -->|ledger 破損| E[LedgerIntegrityError, 無修復]
    A -->|裁定対象ゼロ| F[accept なし + エスカレーションのみ]
    A -->|局所探索が全 inf| G[現行構成維持 + 記録]
```

## データ整合性 🔵

- Trajectory の行数 = フレーム数 (失敗フレームも None 値入りで 1 行、TC-104-03)
- `Hypothesis.frame_range` は採択区間 [start, end] を保持し、系譜は parent_id (単一情報源)
- 永続 ledger のエントリ index は再オープン跨ぎで連番継続 (verify で保証)

## 信頼性レベルサマリー

- 🔵: 6 フロー / 🟡: 2 (オンライン方式・warm-up) / 🔴: 0 — **品質評価**: 高品質
