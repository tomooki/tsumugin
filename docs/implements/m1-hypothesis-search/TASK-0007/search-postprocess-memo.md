# 探索後処理 (TASK-0007) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m1-hypothesis-search/TASK-0007.md`
- `docs/implements/m1-hypothesis-search/TASK-0007/search-postprocess-requirements.md`
- `docs/implements/m1-hypothesis-search/TASK-0007/search-postprocess-testcases.md`

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (16/16 新規テストケース TC-N11〜18 / TC-E05〜07 / TC-B07〜11)
- **テスト成功率**: 100% (全 177 passed・1 skipped、スコープ内 `tests/test_tree_search.py` 36 件全 green)
- **品質判定**: 合格 (高品質・完全達成)
- **TODO更新**: ✅ 完了マーク追加 (`docs/tasks/m1-hypothesis-search/TASK-0007.md` 完了条件 7 項目チェック済み)
- **要件網羅率**: 100% (完了条件 7 項目 + 横断制約すべてに対応テストあり)

### 完了条件 → テスト対応 (全 pass)
| 完了条件 | テスト |
|---|---|
| Jenks 良好解 good_cluster_ids | TC-N11 `test_jenks_good_cluster_ids_contains_top_and_excludes_worst` |
| final_full_refine=True で metrics 更新・final_reports 記録 | TC-N12 `test_final_full_refine_records_reports_and_updates_metrics` |
| 候補外相混入 → unknown_phase_flag=True + 未マッチ報告 | TC-N16 `test_unknown_phase_reports_unmatched_peaks_with_flag` |
| 完全説明 → フラグ False・未マッチ空 | TC-N15 `test_complete_explanation_has_no_unmatched_and_flag_false` |
| 全仮説高 R → unknown_phase_flag=True | TC-E05 `test_all_high_r_forces_unknown_phase_flag` |
| フラットパターン → warnings 非空・例外なし | TC-E06 `test_flat_pattern_degrades_with_warnings_and_no_flag` |
| to_summary() が /api/result スキーマ一致 | TC-N17 `test_to_summary_matches_api_result_schema_and_is_json_serializable` |

横断制約: 再ランク昇順 (TC-N13) / 無効化 (TC-N14) / ledger.verify 追記一貫 (TC-N18) /
候補ゼロ空スキーマ (TC-E07) / Jenks 縮退フォールバック (TC-B07/B08) / 高 R 厳密比較 (TC-B09) /
max_final_refine クリップ (TC-B10) / 後処理含む決定論ビット同一 (TC-B11) も全 pass。

## 💡 重要な技術学習
### 実装パターン
- 後処理を `_postprocess` 1 メソッドへ凝集し、フラット/通常経路を末尾 1 箇所の `SearchResult`
  構築へ集約 (DRY)。`good_cluster` 抽出 → `_final_refine` (staged フル精密化 + 再ランク) →
  `_compute_unmatched` の 3 段。
- 非破壊反映は `dataclasses.replace(hyp, phases=report.final_phases, metrics=replace(report.metrics, evidence={ev.backend: ev.value}))` で新インスタンス差し替え。
- 探索と同一 `Ledger`/`SnapshotStore` を `StagedRefinementEngine(store=snapshots, ledger=ledger)` で共有し監査チェーンを 1 本に維持。

### テスト設計
- `_run_ab_search` 共通ヘルパで A+B 合成・候補 [A,B,C,D] を再利用し実行時間を抑制。
- 決定論は `==` ビット同一、物理量 (ピーク位置) は許容付き比較。`to_summary()` は `json.dumps`/`json.loads` 往復同値で純 dict 化を検証。

### 品質保証
- 縮退経路の取り違え防止: フラット (観測ピーク 0) は warnings + フラグ False、全高 R は
  フラグ True。両者を別テスト (TC-E06 vs TC-E05) で固定。
- 既存 TC-N09 骨格契約・TC-N10 探索モード契約は TASK-0007 実体化に合わせて最小修正済み
  (final_full_refine=False で探索モードのみ観測)、20 既存ケースも回帰なし。

## ⚠️ 注意点・修正が必要な項目
なし。スコープ内テスト失敗・スコープ外テスト失敗ともに 0 件。

---
*本記録は tdd-verify-complete の検証結果。git commit は本セッションでは行わない。*
