# refine-loop-diagnostics タスク概要

**作成日**: 2026-07-09
**推定工数**: 41 時間
**総タスク数**: 9 件 (全 TDD)

## 関連文書

- **要件定義書**: [📋 requirements.md](../../spec/refine-loop-diagnostics/requirements.md)
- **アーキテクチャ**: [📐 architecture.md](../../design/refine-loop-diagnostics/architecture.md)
- **データフロー**: [🔄 dataflow.md](../../design/refine-loop-diagnostics/dataflow.md)
- **型定義**: [📝 interfaces.py](../../design/refine-loop-diagnostics/interfaces.py)
- **設計入力(正)**: [GAP_ANALYSIS.md](../../design/refine-loop-diagnostics/GAP_ANALYSIS.md) /
  [serious-refinement-flow.md](../../reference/serious-refinement-flow.md)
- **コンテキストノート**: [📝 note.md](../../spec/refine-loop-diagnostics/note.md)

## フェーズ構成

| フェーズ | 成果物 | タスク数 | 工数 |
|---------|--------|----------|------|
| Phase 1 前提工事(P0) | 内省フィールド + diagnose_residual | 2 | 8h |
| Phase 2 診断規則(P1) | 非対称/位置・PO/幅・背景減項 | 3 | 13h |
| Phase 3 新SafeAction(P2) | RestrictUiso / SetAbsorption | 2 | 8h |
| Phase 4 モデル比較(P4) | model_compare オーケストレータ | 1 | 5h |
| Phase 5 統合 | orchestrator 既定 diagnose 差替 + 統合 | 1 | 4h |

## タスク番号管理

**使用済み**: TASK-0001 〜 TASK-0009 / **次回開始**: TASK-0010

## 全体進捗

- [ ] Phase 1: 前提工事 (TASK-0001, 0002)
- [ ] Phase 2: 診断規則 (TASK-0003, 0004, 0005)
- [ ] Phase 3: 新 SafeAction (TASK-0006, 0007)
- [ ] Phase 4: モデル比較 (TASK-0008)
- [ ] Phase 5: 統合 (TASK-0009)

---

## Phase 1: 前提工事 (P0)

**目標**: 残差以外の異常(Uiso/占有率/吸収/プロファイル/幅/非対称/配向/背景)を「見える」化。

- [ ] [TASK-0001: AutoRietveldResult 内省フィールド追加](TASK-0001.md) - 3h (TDD) 🔵 — REQ-001
- [ ] [TASK-0002: 残差解析 diagnose (diagnose_residual)](TASK-0002.md) - 5h (TDD) 🔵 — REQ-002

### 依存関係
```
TASK-0001 → TASK-0002
```

---

## Phase 2: 診断規則 (P1)

**目標**: 診断シグナル→候補を**別々に列挙**(結論を焼き込まない)。大半は既存 `ReleaseParams`。

- [ ] [TASK-0003: ResidualFeatures 拡張 + 非対称/位置を別々に提案](TASK-0003.md) - 6h (TDD) 🔵 — REQ-101/003/405
- [ ] [TASK-0004: preferred orientation + 幅個別 提案](TASK-0004.md) - 4h (TDD) 🔵 — REQ-102/103
- [ ] [TASK-0005: 背景 overfit 減項 提案](TASK-0005.md) - 3h (TDD) 🔵 — REQ-104

### 依存関係
```
TASK-0002 → TASK-0003 → TASK-0004
TASK-0003 → TASK-0005
```

---

## Phase 3: 新 SafeAction (P2)

**目標**: 「解放」でなく「限定/値固定」の手を追加。

- [ ] [TASK-0006: RestrictUiso SafeAction](TASK-0006.md) - 4h (TDD) 🔵 — REQ-004/105
- [ ] [TASK-0007: SetAbsorption SafeAction](TASK-0007.md) - 4h (TDD) 🔵 — REQ-004/106

### 依存関係
```
TASK-0003 → TASK-0006
TASK-0003 → TASK-0007
```

---

## Phase 4: モデル比較 (P4)

**目標**: 変種を BIC+妥当性で裁定する上位オーケストレータ。

- [ ] [TASK-0008: モデル比較オーケストレータ (model_compare)](TASK-0008.md) - 5h (TDD) 🔵 — REQ-005/202

### 依存関係
```
TASK-0001 → TASK-0008
```

---

## Phase 5: 統合

**目標**: 既定 diagnose を diagnose_residual に差し替え、統合の決定論・非回帰を確認。

- [ ] [TASK-0009: orchestrator 既定 diagnose 差替 + 統合](TASK-0009.md) - 4h (TDD) 🔵 — REQ-201/402

### 依存関係
```
TASK-0002,0003,0004,0005,0006,0007 → TASK-0009
```

---

## クリティカルパス

```
TASK-0001 → TASK-0002 → TASK-0003 → TASK-0004 → TASK-0009
                                   ↘ TASK-0005/0006/0007 ↗
TASK-0008 は TASK-0001 後に並行可
```

## 信頼性レベルサマリー

- 総タスク数: 9 件 / 🔵 青信号: 9 (100%) / 🟡🔴: 0

**品質評価**: 高品質(全タスク設計文書 + 要件に追跡可能)

## 次のステップ

- 全タスク実装: `/tsumiki:kairo-implement`
- 特定タスク: `/tsumiki:kairo-implement TASK-0001`
