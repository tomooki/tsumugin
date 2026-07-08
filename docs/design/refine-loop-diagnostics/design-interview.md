# refine-loop-diagnostics 設計ヒアリング記録

**作成日**: 2026-07-09
**ヒアリング実施**: step4 既存情報ベースの差分ヒアリング

## ヒアリング目的

要件定義 (`requirements.md`) でスコープ境界 (P3=第3層維持, P4=包含) が確定済みで、対象モジュール
(`refine_loop` action/diagnostics/policy/orchestrator、`autorietveld` model/engine/compare) は
本セッションで全読了済み。設計は要件 + 既存実装から**一意に決まる**ため、設計フェーズでの新規
ヒアリングは実施しなかった。

## 設計方針の決定事項 (要件・既存実装から確定)

- **DD-1** 汎用性優先: 大半の新診断は既存 `ReleaseParams` + engine flag で表現、新 Action は
  `RestrictUiso`/`SetAbsorption` の 2 つのみ (NFR-101・GAP 表C)。
- **DD-2** 非対称/位置は別々の候補 (シフト Zero と 非対称 SH·L/alpha を独立提案, REQ-101/405)。
- **DD-3** 内省フィールドは `AutoRietveldResult` に非破壊・既定空で末尾追加 (EDGE-001 後方互換)。
- **DD-4** 経験則は priority を偏らせる非拘束 prior (REQ-301)。
- **DD-5** データリミットは第3層維持 (`SetLimits` は ModelAction のまま, ヒアリング P3)。
- **DD-6** モデル比較は単一モデル調律ループの外側の薄い上位 (`model_compare`, ヒアリング P4)。

## 残課題

- なし (設計は要件 + 既存実装で確定、全項目 🔵)。

## 信頼性レベル分布

- ヒアリング前: 🔵 多数 / 🟡 0 / 🔴 0 (要件段階で境界確定済)
- ヒアリング後: 変化なし (新規質問なし)

## 関連文書

- **アーキテクチャ設計**: [architecture.md](architecture.md)
- **データフロー**: [dataflow.md](dataflow.md)
- **型定義**: [interfaces.py](interfaces.py)
- **要件定義**: [requirements.md](../../spec/refine-loop-diagnostics/requirements.md)
