# m3-operando 準備タスク（ユーザー作業）

> **仕様**: [requirements.md](requirements.md) / **生成日**: 2026-07-03

**【信頼性レベル凡例】**: 🔵 明確に必要 / 🟡 妥当な推測 / 🔴 予防的推測

## 必須（実装開始前に完了が必要）

なし — M3 も外部サービス・認証情報・追加インフラを必要としない。
テストは合成データで完結し、xraylib / .mpr パーサはインターフェースのみ (実装しない)。

## 推奨（実装中に用意できればOK）

- [ ] **実測 operando データ (検証用, 任意)** 🟡 *仕様 §12-3 operando ベンチより*
  - 既知系 (例: LFP 二相 / グラファイトステージング) の回折フレーム列 + サイクラー CSV が
    1 セットあると M3 完了後の実地検証に使える。M3 のテスト自体には不要
  - 関連要件: REQ-007, REQ-010

## 確認事項（判断が必要）

- [ ] **xraylib / galvani (.mpr) を将来 optional extra に追加する方針の可否** 🟡 *interview Q3/REQ-019*
  - M3 は Protocol + 未実装エラーで確定した。実測運用を始める際に
    `uv sync --extra mu` / `--extra echem` の形で追加する想定 (M-later)
  - 関連要件: REQ-008, REQ-019

---

## サマリー

| 優先度 | 件数 | 🔵 | 🟡 | 🔴 |
|--------|------|-----|-----|-----|
| 必須 | 0 | 0 | 0 | 0 |
| 推奨 | 1 | 0 | 1 | 0 |
| 確認事項 | 1 | 0 | 1 | 0 |

## 関連文書

- [requirements.md](requirements.md) / [interview-record.md](interview-record.md)
