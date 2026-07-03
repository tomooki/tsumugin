# m1-hypothesis-search API エンドポイント仕様 (Web UI 最小版)

**作成日**: 2026-07-03
**関連設計**: [architecture.md](architecture.md)
**関連要件定義**: [requirements.md](../../spec/m1-hypothesis-search/requirements.md)

**【信頼性レベル凡例】**: 🔵 要件に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

> 対象は M1 の**読み取り専用ローカル Web UI** のみ。汎用 REST API (FR-512) は M4+ で別設計。

## 共通仕様

- **バインド**: 127.0.0.1 既定 (NFR-101) 🟡
- **認証**: なし (ローカル単一ユーザーの閲覧ツール。host 変更による外部公開は非サポート) 🟡
- **非有限値**: chi2=inf 等 (EDGE-004 の正常経路) は JSON に存在しないため、rwp/gof/chi2/
  evidence 値は非有限のとき `null` で配信する (両エンドポイント共通の契約) 🔵
- **バージョニング/CORS/レート制限**: なし (M1 スコープ外を明示) 🔵
- **read-only 保証**: GET 以外のルートを定義しない。テスト TC-007-03 で担保 🔵 *REQ-007*

## エンドポイント一覧

### GET / 🟡

静的 `index.html` を返す。ランキングテーブルと仮説詳細を fetch で描画する単一ページ。

### GET /api/result 🟡

**関連要件**: REQ-007

`SearchResult.to_summary()` をそのまま返す。

```json
{
  "ranked": [
    {
      "id": "hyp-0003",
      "rank": 1,
      "probability": 0.93,
      "close_competitor": false,
      "rwp": 4.2,
      "gof": 1.1,
      "evidence": {"backend": "bic", "value": 123.4},
      "phases": [{"phase_ref": "A", "wt_frac": null, "lattice": {"a": 4.0, "b": 4.0, "c": 4.0}}],
      "parent_id": "hyp-0001",
      "in_good_cluster": true
    }
  ],
  "unknown_phase_flag": false,
  "unmatched_observed": [{"position": 33.1, "height": 120.0}],
  "extra_calculated": [41.7],
  "warnings": [],
  "n_hypotheses": 7
}
```

### GET /api/hypotheses/{id} 🟡

**関連要件**: REQ-007/301

仮説 1 件の詳細 (相ごとの格子・scale・metrics 全量・系譜)。

**エラー**: 存在しない id → `404 {"detail": "hypothesis not found"}` 🟡

## 信頼性レベルサマリー

- 🔵: 2 / 🟡: 6 / 🔴: 0 — Web UI は仕様上「最小版」の語のみのため推測比率が高い。
  read-only 制約と表示項目は要件 REQ-007 に遡及。

**品質評価**: 要件範囲内で十分 (M2 の FR-421/422 で拡張予定)
