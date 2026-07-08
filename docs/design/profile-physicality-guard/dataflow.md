# プロファイル物理性ガード データフロー

**作成日**: 2026-07-09
**関連アーキテクチャ**: [architecture.md](architecture.md)

**【信頼性レベル凡例】**: 🔵 確実 / 🟡 妥当な推測 / 🔴 資料にない推測

---

## 段階ループ内の revert 判定フロー 🔵

**信頼性**: 🔵 *engine.py:609-661 精読*

```mermaid
sequenceDiagram
    participant L as 段階ループ
    participant G as GSAS (do_refinements)
    participant E as _extract_profile / _profile_ranges
    participant P as check_profile_physicality (numpy)
    participant R as 既存 revert 経路

    L->>G: _apply_stage + do_refinements
    G-->>L: rwp, gof, nvar
    L->>E: g2hists, radiations
    E-->>P: profiles, ranges, radiations
    P-->>L: ValidityReport(passed, warnings)
    alt not _cells_physical OR not passed
        L->>L: rwp=gof=inf, converged=False
        L->>R: rwp>prev_rwp → スナップショット復元
        R-->>L: 直前段階へ revert
    else 物理的
        L->>L: 従来どおり Rwp 判定 (非回帰)
    end
```

## hist_profile 充填と警告マージ (最終結果) 🔵

**信頼性**: 🔵 *engine.py:673-711 精読*

```mermaid
flowchart TD
    A[全段階完了] --> B[_extract_profile 最終状態]
    B --> C[hist_profile = key→value に射影]
    A --> D[check_profile_physicality 最終状態]
    D --> E{soft 逸脱?}
    E -->|あり| F[ValidityReport.warnings に追記]
    E -->|なし| G[そのまま]
    C --> H[AutoRietveldResult]
    F --> H
    G --> H
```

## 幅関数正値性の評価 (CW ガウス) 🔵

**信頼性**: 🔵 *Caglioti / 2次関数の区間最小*

```mermaid
flowchart TD
    A["U,V,W と 2θ レンジ (lo,hi)"] --> B["t_lo=tan(lo/2), t_hi=tan(hi/2)"]
    B --> C["端点評価 H(t_lo), H(t_hi)"]
    A --> D{"U>0 かつ 頂点 t*=-V/2U が [t_lo,t_hi] 内?"}
    D -->|yes| E["頂点も評価 H(t*)"]
    D -->|no| F["端点のみ"]
    C --> G[min を取る]
    E --> G
    F --> G
    G --> H{"min > width_floor?"}
    H -->|yes| I[OK]
    H -->|no| J["U,V,W いずれか refined?"]
    J -->|yes| K[hard NG → revert]
    J -->|no| L[warning のみ]
```

## エラー処理フロー 🔵

**信頼性**: 🔵 *EDGE-001/002/003 + check_bond_validity 縮退流儀*

```mermaid
flowchart TD
    A[抽出/判定] --> B{Instrument Parameters 取得可?}
    B -->|no| C[空 dict → passed=True skip]
    B -->|yes| D{レンジ取得可?}
    D -->|no| E[レンジ依存判定 skip, 符号判定は継続]
    D -->|yes 但し tanθ 発散| F[評価点をレンジ端でクランプ/skip]
    D -->|yes| G[通常判定]
```

## 状態管理 🔵

**信頼性**: 🔵 *engine スナップショット機構 (既存)*

- revert は既存の `.gpx` スナップショット復元で行う。本機能は「非物理 → rwp=inf」への変換のみ足し、
  復元自体は既存経路が担う (新しい状態遷移を導入しない)。

## 信頼性レベルサマリー
- 🔵 青信号: 100%

**品質評価**: 高品質
