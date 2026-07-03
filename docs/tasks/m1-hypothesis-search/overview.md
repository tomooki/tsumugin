# m1-hypothesis-search タスク概要

**作成日**: 2026-07-03
**総タスク数**: 10 件 (TDD 9 / DIRECT 1)
**推定工数**: 約 34 時間

## 関連文書

- **要件定義書**: [📋 requirements.md](../../spec/m1-hypothesis-search/requirements.md)
- **受け入れ基準**: [✅ acceptance-criteria.md](../../spec/m1-hypothesis-search/acceptance-criteria.md)
- **設計文書**: [📐 architecture.md](../../design/m1-hypothesis-search/architecture.md)
- **型定義**: [📝 interfaces.py](../../design/m1-hypothesis-search/interfaces.py)
- **API仕様**: [🔌 api-endpoints.md](../../design/m1-hypothesis-search/api-endpoints.md)
- **コンテキストノート**: [📝 note.md](../../spec/m1-hypothesis-search/note.md)

## フェーズ構成

| フェーズ | 成果物 | タスク | 工数 |
|---------|--------|--------|------|
| Phase 1: 基盤 | パッケージ骨格 + web extra | TASK-0001 | 1h |
| Phase 2: 探索コンポーネント | peaks/matcher/pruning/clustering | TASK-0002〜0005 | 13h |
| Phase 3: 探索エンジン | HypothesisTreeSearch | TASK-0006〜0007 | 10h |
| Phase 4: 相互運用・UI・統合 | export_gpx / Web UI / e2e | TASK-0008〜0010 | 10h |

## タスク一覧と依存関係

- [x] [TASK-0001: web extra 追加とパッケージ骨格](TASK-0001.md) - 1h (DIRECT) 🔵 ✅ 完了 (2026-07-03)
- [x] [TASK-0002: 観測ピーク検出 find_peaks](TASK-0002.md) - 3h (TDD) 🟡 ✅ 完了 (2026-07-03)
- [ ] [TASK-0003: PeakMatcher (スコア/未マッチ)](TASK-0003.md) - 4h (TDD) 🔵
- [ ] [TASK-0004: 動的枝刈り閾値 dynamic_threshold](TASK-0004.md) - 2h (TDD) 🔵
- [ ] [TASK-0005: Jaccard クラスタ + FoM + Jenks](TASK-0005.md) - 4h (TDD) 🔵
- [ ] [TASK-0006: 木探索コア (展開/探索精密化/ledger)](TASK-0006.md) - 6h (TDD) 🔵
- [ ] [TASK-0007: 探索後処理 (良好解/フル精密化/未知相/summary)](TASK-0007.md) - 4h (TDD) 🔵
- [ ] [TASK-0008: .gpx 書き出し export_gpx](TASK-0008.md) - 3h (TDD) 🔵
- [ ] [TASK-0009: Web UI 最小版 (FastAPI read-only)](TASK-0009.md) - 4h (TDD) 🟡
- [ ] [TASK-0010: 公開 API 統合 + E2E + ドキュメント](TASK-0010.md) - 3h (TDD) 🔵

```
TASK-0001 → 0002 → 0003 → 0004 → 0006
                 └→ 0005 ────────┘
TASK-0006 → 0007 → 0009, 0010
TASK-0001 → 0008 (0006 と並行可)
TASK-0007/0008/0009 → 0010
```

**クリティカルパス**: 0001→0002→0003→0006→0007→0010

## タスク番号管理

**使用済み**: TASK-0001〜0010 / **次回開始**: TASK-0011

## 運用ルール (CLAUDE.md 準拠)

- 各タスク完了 (全テスト green + ruff clean) ごとに 1 コミット
- TDD 厳守: Red → Green → Refactor。実装エージェントは Opus
- GSAS-II 依存テストは `@pytest.mark.gsas`

## 信頼性レベルサマリー

- 🔵: 8 タスク / 🟡: 2 タスク (0002 ピーク検出式, 0009 Web UI) / 🔴: 0

**品質評価**: 高品質

## 次のステップ

`/tsumiki:kairo-implement TASK-0001` から順に実装 (kairo-loop で自動実行)
