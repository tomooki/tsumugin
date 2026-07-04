# m4-joint-mcp タスク概要

**作成日**: 2026-07-04 / **総タスク数**: 11 件 (全 TDD) / **推定工数**: 約 43 時間

## 関連文書

- [📋 requirements.md](../../spec/m4-joint-mcp/requirements.md) /
  [✅ acceptance-criteria.md](../../spec/m4-joint-mcp/acceptance-criteria.md) /
  [📐 architecture.md](../../design/m4-joint-mcp/architecture.md) /
  [📝 interfaces.py](../../design/m4-joint-mcp/interfaces.py) /
  [🔄 dataflow.md](../../design/m4-joint-mcp/dataflow.md) /
  [💬 design-interview.md](../../design/m4-joint-mcp/design-interview.md)

## フェーズ構成

| フェーズ | 成果物 | タスク | 工数 |
|---------|--------|--------|------|
| Phase 1: モデル/例外拡張 | TofBankParams+HistogramRef.bank_params+serialization 往復 / PhaseRef / errors 2 例外 | TASK-0036〜0037 | 6h |
| Phase 2: joint 精密化 | JointHistogram/Model/Metrics/Result+weights / engine (refine_joint/detailed) | TASK-0038〜0039 | 11h |
| Phase 3: contrast + verification | 散乱長/Z テーブル+recommend_occupancy_release / verify_survivors | TASK-0040〜0041 | 9h |
| Phase 4: chem | base+rules+compose / ranking (降格のみ・除外禁止) | TASK-0042〜0043 | 8h |
| Phase 5: MCP | tools+mem (8 ツール実処理) / server (遅延 import アダプタ) | TASK-0044〜0045 | 9h |
| Phase 6: 統合 | 公開 API __all__ 昇順 + M4 E2E + ドキュメント | TASK-0046 | 4h |

## タスク一覧と依存関係

- [ ] [TASK-0036: model/project 拡張 (TofBankParams + HistogramRef.bank_params + serialization 往復)](TASK-0036.md) - 3h (TDD) 🔵
- [ ] [TASK-0037: model/phase PhaseRef + errors 2 例外 (MCPUnavailableError/MEMUnavailableError)](TASK-0037.md) - 3h (TDD) 🔵
- [ ] [TASK-0038: joint/model + joint/weights (JointHistogram/Model/Metrics/Result + HistogramWeighting)](TASK-0038.md) - 5h (TDD) 🔵
- [ ] [TASK-0039: joint/engine (refine_joint / refine_joint_detailed)](TASK-0039.md) - 6h (TDD) 🔵
- [ ] [TASK-0040: joint/contrast (散乱長/Z テーブル + recommend_occupancy_release)](TASK-0040.md) - 5h (TDD) 🔵
- [ ] [TASK-0041: joint/verification (verify_survivors)](TASK-0041.md) - 4h (TDD) 🔵
- [ ] [TASK-0042: chem/base + chem/rules + chem/compose](TASK-0042.md) - 4h (TDD) 🔵
- [ ] [TASK-0043: chem/ranking (rank_with_plausibility・降格のみ・除外禁止)](TASK-0043.md) - 4h (TDD) 🔵
- [ ] [TASK-0044: mcp/tools + mcp/mem (8 ツール実処理・SDK 非依存)](TASK-0044.md) - 5h (TDD) 🔵
- [ ] [TASK-0045: mcp/server (遅延 import アダプタ・stdio/local)](TASK-0045.md) - 4h (TDD) 🔵
- [ ] [TASK-0046: 公開 API 統合 + M4 E2E + ドキュメント](TASK-0046.md) - 4h (TDD) 🔵

```
0036: 先行依存なし (既存 model/project + serialization のみ)
0037: 先行依存なし (既存 model/phase + errors のみ)
0036 → 0038 → 0039        (joint model は bank_params/JointHistogram に依存)
0037, 0039 → 0040         (PhaseRef + joint model で contrast 判定)
0039, 0040 → 0041         (verify_survivors は engine + contrast を配線)
0037 → 0042 → 0043        (chem base は PhaseRef、ranking は base+compose)
0041, 0043, 0037 → 0044   (mcp tools は verify_survivors/rank/errors へ委譲)
0044 → 0045               (server は tools レジストリを配線)
0041, 0043, 0045 → 0046   (E2E + 公開 API 統合)
```

**クリティカルパス**: 0036 → 0038 → 0039 → 0040 → 0041 → 0044 → 0045 → 0046

## タスク番号管理

**使用済み**: TASK-0001〜0035 (M0〜M3) / **本 M4**: TASK-0036〜0046 / **次回開始**: TASK-0047

## 運用ルール (CLAUDE.md 準拠)

- タスク完了 (全テスト green + ruff clean) ごとに 1 コミット。TDD 厳守 (Red→Green→Refactor)・実装エージェントは Opus
- 非破壊追加のみ (既存 API 後方互換 / `__all__` は末尾追加 + 昇順維持)。削除・上書き API を新設しない (P2/NFR-101)
- 決定論・ビット同一 (NFR-102)、ledger は追記 + ハッシュチェーン (`verify()` 常に True, NFR-105)
- コア依存は numpy のみを維持 (mcp は optional extra、散乱長は軽量静的テーブル、REQ-403)
- ChemPlausibility は降格のみ (候補除外禁止, REQ-019)、`run_mem` は M5 委譲境界のみ (REQ-101)

## 信頼性レベルサマリー

- 🔵: 11 / 🟡: 0 / 🔴: 0 — **品質評価**: 高品質

## 次のステップ

`/tsumiki:kairo-implement TASK-0036` から順に実装 (kairo-loop で自動実行)
