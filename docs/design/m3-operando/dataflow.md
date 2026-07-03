# m3-operando データフロー図

**作成日**: 2026-07-03
**関連**: [architecture.md](architecture.md) / [requirements.md](../../spec/m3-operando/requirements.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## operando 解析の全体フロー 🔵

**信頼性**: 🔵 *FR-311→316→313→314 の仕様順序*

```mermaid
flowchart TD
    A[FrameSeries + echem CSV] --> B[read_echem_csv\n列マッピング + 容量→x 換算]
    B --> C[EchemData → ExternalChannel 群\nフレーム同期]
    D[セル固定相プリセット\nBe/Al/graphite] --> E
    C --> E[SequentialEngine 逐次解析\n固定相=scaleのみ解放\nIssue#3 較正済み changepoint]
    E --> F[segment_series FR-316\nk=1,2,... 貪欲挿入\nΣbic + β·境界数·ln n\n粗G=5→細±G]
    F --> G{各区間}
    G --> H[discriminate_interval FR-313\n仮説A: 単相格子連続\n仮説B: 端成分二相分率変化]
    H --> I[マルチスタート必須 FR-233\n区間端点で N=8 摂動精密化\nbasin クラスタ]
    I --> J{ΔBIC ≥ 10?}
    J -->|yes| K[verdict 確定\nsolid_solution / two_phase]
    J -->|no| L[undecided + ReviewQueue\n処理はブロックしない]
    K --> M[combined_csv 出力\nwt_frac x / 格子 x / 転移点 x,V ±σ]
    L --> M
    M --> N[hysteresis 解析 (任意)\n充放電枝分離 + 同一x差分]

    E -.-> O[(Ledger)]
    F -.-> O
    H -.-> O
    I -.-> O
```

## マルチスタートのフロー 🔵

```mermaid
flowchart LR
    A[基準 phases + データ] --> B[decompose: 摂動列生成\ni=0 無摂動, i=1..N-1 決定論グリッド/LHS]
    B --> C[各 start: backend.refine\ndirect, ≤15 cycles, 純関数]
    C --> D{chi2 有限?}
    D -->|no| E[除外 + カウント]
    D -->|yes| F[正規化パラメータベクトル]
    F --> G[union-find クラスタ\n相対距離 < 1e-2]
    G --> H{n_basins}
    H -->|1| I[大域最適の傍証あり\nmetrics.multistart 記録]
    H -->|>1| J[各 basin を別仮説へ昇格\nevidence 比較 rank]
    E --> K[全滅なら警告+元仮説維持]
```

## FR-313 判別のシーケンス 🔵

```mermaid
sequenceDiagram
    participant D as discriminate_interval
    participant A as 仮説A (単相)
    participant B as 仮説B (二相)
    participant M as MultistartEngine
    participant E as BICBackend
    participant Q as ReviewQueue

    D->>A: 区間フレームを warm-start 逐次 refine (格子解放)
    A-->>D: Σbic_A + 格子トラジェクトリ
    D->>B: 端成分2相を初期化 (端点格子・格子固定) → scale/wt のみ逐次 refine
    B-->>D: Σbic_B + 分率トラジェクトリ
    D->>M: 両仮説の区間端点フレームで N=8 マルチスタート (必須)
    M-->>D: basin 数 / 昇格仮説 / metrics.multistart
    D->>E: ΔBIC = bic_A − bic_B
    alt |ΔBIC| ≥ 閾値
        D-->>D: verdict = 優位側
    else 僅差
        D->>Q: add(close_competitor 相当) — ブロックしない
        D-->>D: verdict = undecided (暫定 = 優位側)
    end
```

## 吸収補正のフロー 🔵

```mermaid
flowchart TD
    A{CellConfig 提供?} -->|yes| B[μt_calc = ユーザー指定\nrestraint 幅 = 通常]
    A -->|no| C[経験推定モード\n弱 restraint + 警告]
    B --> D[SimulatedBackend absorption 付き\nsimulate: I × exp -μt/cosθ]
    C --> D
    D --> E[refine: global.mu_t を\nフィットベクトルに追加\nchi2 += w_r·(μt−μt_calc)²]
    E --> F[RefinementResult.globals に μt]
    F --> G{restraint 幅超過?}
    G -->|yes| H[相関疑い警告 §14]
    G -->|no| I[補正済み相分率]
```

## Issue #3 (新規ピーク指標の持続条件) 🔵

```mermaid
flowchart LR
    A[フレーム i の未マッチピーク] --> B{強度 ≥ min_height_frac?}
    B -->|no| C[無視]
    B -->|yes| D[持続カウンタ += 1\n(位置ビンごと)]
    D --> E{連続 M=2 フレーム以上?}
    E -->|no| F[発火しない (単発ノイズ)]
    E -->|yes| G[new_peaks 指標に計上\n→ changepoint 判定へ]
```

## エラーハンドリング 🔵

```mermaid
flowchart TD
    A{事象} -->|echem 列欠損| B[列名を示す明示エラー]
    A -->|行数不一致| C[欠損 None + 警告]
    A -->|.mpr ローダ要求| D[NotImplementedError]
    A -->|MuCalculator 要求| E[NotImplementedError]
    A -->|マルチスタート全滅| F[警告 + 元仮説維持]
    A -->|両仮説高R| G[未知相フラグ + エスカレーション\n判別なし]
    A -->|k=1 が最良| H[分割なしで採択]
    A -->|片枝のみ| I[差分 None + 警告]
```

## データ整合性 🔵

- 分割境界・判別 verdict・マルチスタート結果はすべて ledger に理由付き記録 (P2)
- 分割仮説 (k=1,2,…) は削除されず全て保存 — 採択は evidence 順位のみ (候補除外しない)
- echem 同期は frame_index キーの外部結合 — 欠損は None (捏造しない)

## 信頼性レベルサマリー

- 🔵: 6 フロー / 🟡: 1 (結合出力詳細) / 🔴: 0 — **品質評価**: 高品質
