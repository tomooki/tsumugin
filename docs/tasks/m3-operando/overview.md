# m3-operando タスク概要

**作成日**: 2026-07-03 / **総タスク数**: 13 件 (全 TDD) / **推定工数**: 約 47 時間

## 関連文書

- [📋 requirements.md](../../spec/m3-operando/requirements.md) /
  [✅ acceptance-criteria.md](../../spec/m3-operando/acceptance-criteria.md) /
  [📐 architecture.md](../../design/m3-operando/architecture.md) /
  [📝 interfaces.py](../../design/m3-operando/interfaces.py) /
  [🔄 dataflow.md](../../design/m3-operando/dataflow.md) /
  [📝 note.md](../../spec/m3-operando/note.md)

## フェーズ構成

| フェーズ | 成果物 | タスク | 工数 |
|---------|--------|--------|------|
| Phase 1: 技術負債+モデル | Issue#4/#5 解消、CellConfig/channel/metrics 拡張 | TASK-0023〜0025 | 7h |
| Phase 2: backends+multistart | global文法/吸収補正、摂動列、basin+engine | TASK-0026〜0028 | 13h |
| Phase 3: operando 部品 | echem/cell_phases/changepoint較正(#3) | TASK-0029〜0031 | 8h |
| Phase 4: 判別・分割・出力 | discrimination/segmentation/hysteresis+output | TASK-0032〜0034 | 15h |
| Phase 5: 統合 | 公開 API + E2E + ドキュメント | TASK-0035 | 4h |

## タスク一覧と依存関係

- [x] [TASK-0023: _json.finite_or_none 統合 (Issue #5)](TASK-0023.md) - 2h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0024: thermal onset 意味論修正 (Issue #4)](TASK-0024.md) - 2h (TDD) 🔵 ✅ 完了
- [x] [TASK-0025: model 拡張 (CellConfig/channel/metrics.multistart)](TASK-0025.md) - 3h (TDD) 🔵 ✅ 完了
- [x] [TASK-0026: backends 拡張 (global 文法/吸収補正)](TASK-0026.md) - 5h (TDD) 🔵 ✅ 完了
- [x] [TASK-0027: multistart/perturb (決定論摂動列)](TASK-0027.md) - 3h (TDD) 🔵 ✅ 完了
- [x] [TASK-0028: multistart/basin + MultistartEngine](TASK-0028.md) - 5h (TDD) 🔵 ✅ 完了
- [x] [TASK-0029: operando/echem (CSV マッパ + Loader Protocol)](TASK-0029.md) - 3h (TDD) 🔵 ✅ 完了
- [x] [TASK-0030: operando/cell_phases (固定相プリセット)](TASK-0030.md) - 2h (TDD) 🔵 ✅ 完了
- [x] [TASK-0031: changepoint 感度較正 (Issue #3)](TASK-0031.md) - 3h (TDD) 🔵 ✅ 完了
- [x] [TASK-0032: operando/discrimination (FR-313)](TASK-0032.md) - 6h (TDD) 🔵
- [x] [TASK-0033: operando/segmentation (FR-316)](TASK-0033.md) - 5h (TDD) 🔵
- [x] [TASK-0034: operando/hysteresis + output (FR-315/314)](TASK-0034.md) - 4h (TDD) 🔵
- [x] [TASK-0035: 公開 API 統合 + E2E + ドキュメント](TASK-0035.md) - 4h (TDD) 🔵

```
0023, 0024, 0025, 0030, 0031: 先行依存なし (0023/0024 は既存資産のみ)
0025 → 0026 → 0028      0025 → 0027 → 0028      0025 → 0029
0026,0028,0030,0031 → 0032      0028,0031 → 0033      0029 → 0034
0032,0033,0034 → 0035
```

**クリティカルパス**: 0025→0026→0028→0032→0035

## タスク番号管理

**使用済み**: TASK-0001〜0035 / **次回開始**: TASK-0036

## 運用ルール (CLAUDE.md 準拠)

- タスク完了 (全テスト green + ruff clean) ごとに 1 コミット。TDD 厳守・実装エージェントは Opus
- Issue #3/#4/#5 は該当タスクのコミットメッセージに "Closes #N" を含める

## 信頼性レベルサマリー

- 🔵: 13 / 🟡: 0 / 🔴: 0 — **品質評価**: 高品質

## 次のステップ

`/tsumiki:kairo-implement TASK-0023` から順に実装 (kairo-loop で自動実行)
