# m2-sequential タスク概要

**作成日**: 2026-07-03 / **総タスク数**: 12 件 (全 TDD) / **推定工数**: 約 43 時間

## 関連文書

- [📋 requirements.md](../../spec/m2-sequential/requirements.md) /
  [✅ acceptance-criteria.md](../../spec/m2-sequential/acceptance-criteria.md) /
  [📐 architecture.md](../../design/m2-sequential/architecture.md) /
  [📝 interfaces.py](../../design/m2-sequential/interfaces.py) /
  [🔄 dataflow.md](../../design/m2-sequential/dataflow.md) /
  [📝 note.md](../../spec/m2-sequential/note.md)

## フェーズ構成

| フェーズ | 成果物 | タスク | 工数 |
|---------|--------|--------|------|
| Phase 1: モデル/永続化基盤 | model 拡張・serialization・Persistent{Ledger,SnapshotStore} | TASK-0011〜0014 | 12h |
| Phase 2: 時系列コンポーネント | series/changepoint/lifecycle/trajectory/thermal | TASK-0015〜0018 | 14h |
| Phase 3: エンジン | SequentialEngine / selection (queue+engine) | TASK-0019〜0021 | 13h |
| Phase 4: 統合 | 公開 API + E2E + ドキュメント | TASK-0022 | 4h |

## タスク一覧と依存関係

- [x] [TASK-0011: model 拡張 (Lifecycle/Channel/frame_range)](TASK-0011.md) - 3h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0012: store/serialization (phase dict 相互変換)](TASK-0012.md) - 3h (TDD) 🟡 ✅ 完了 (2026-07-03)
- [x] [TASK-0013: PersistentLedger (JSONL 追記+検証)](TASK-0013.md) - 3h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0014: PersistentSnapshotStore](TASK-0014.md) - 3h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0015: FrameSeries + changepoint 検出](TASK-0015.md) - 4h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0016: LifecycleTracker (ヒステリシス)](TASK-0016.md) - 3h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0017: Trajectory + to_csv](TASK-0017.md) - 3h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0018: thermal (ベースライン+転移温度)](TASK-0018.md) - 4h (TDD) 🔵 ✅ 完了 (2026-07-03)
- [ ] [TASK-0019: SequentialEngine (オンライン逐次+局所探索)](TASK-0019.md) - 6h (TDD) 🔵
- [ ] [TASK-0020: ReviewQueue + detect_escalations](TASK-0020.md) - 3h (TDD) 🔵
- [ ] [TASK-0021: FinalSelectionEngine (agent/human)](TASK-0021.md) - 4h (TDD) 🔵
- [ ] [TASK-0022: 公開 API 統合 + E2E + ドキュメント](TASK-0022.md) - 4h (TDD) 🔵

```
0011 → 0012 → 0014          0011 → 0015,0016,0017,0018,0020
       0013 → 0014          0013〜0018 → 0019
                            0020 → 0021
                            0019, 0021 → 0022
```

**クリティカルパス**: 0011→0012→0014→0019→0022 (または 0011→0015→0019→0022)

## タスク番号管理

**使用済み**: TASK-0001〜0010 (m1) + TASK-0011〜0022 (本 Plan) / **次回開始**: TASK-0023

## 運用ルール (CLAUDE.md 準拠)

- タスク完了 (全テスト green + ruff clean) ごとに 1 コミット。TDD 厳守・実装エージェントは Opus
- GSAS-II 依存テストは @pytest.mark.gsas (M2 では TC-108-02 の 1 本のみ)

## 信頼性レベルサマリー

- 🔵: 11 / 🟡: 1 (0012 シリアライズ詳細) / 🔴: 0 — **品質評価**: 高品質

## 次のステップ

`/tsumiki:kairo-implement TASK-0011` から順に実装 (kairo-loop で自動実行)
