# operando 公開 API 統合 + E2E (TASK-0035) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m3-operando/TASK-0035.md`
- `docs/implements/m3-operando/TASK-0035/operando-integration-e2e-requirements.md`
- `docs/implements/m3-operando/TASK-0035/operando-integration-e2e-testcases.md`
- `docs/tasks/m3-operando/reports/verification.md`

## 🎯 最終結果 (2026-07-04)
- **実装率**: 100% (18/18 テストケース TC-035-01〜18)
- **品質判定**: ✅ 合格 (完全実装)
- **全体テスト**: 644 passed / 3 skipped (無退行) ・カバレッジ 98% ・ruff clean
- **TODO更新**: ✅ 完了マーク追加 (完了条件 5/5 達成)

## 💡 重要な技術学習
### 実装パターン
- 統合タスクの公開面配線は「サブパッケージ実体からの re-export (別実装でなく is 同一実体)」+
  `__all__` アルファベット昇順の非破壊追記 (M0/M1/M2 削除・改名禁止 = REQ-404)。
- import 群にグルーピングコメントを置くと、追記時の順序崩れ・二重実装を自己文書化で抑止できる。

### テスト設計
- 一気通貫 E2E は module スコープ fixture (`operando_run`) で 1 回だけ実行し正常系を読み取り専用共有 →
  実行時間を抑制 (M2 `warming_run` の範)。判別は `n_starts=2` の高速 config。
- 配線検証は「from tsumugin import ... の解決」+「__all__ 昇順・後方互換包含」+「is 同一実体」の 3 点で担保。
- 決定論は独立 Ledger で 2 回実行し verdict 列 / boundaries / CSV バイト列を `==` ビット一致で検証。

### 品質保証
- 共有 Ledger を segment/discriminate へ注入し末尾で `verify() is True` + `len(entries) > 0`
  (空 ledger の自明 True でない) を確認 → P2/NFR-105 の非破壊性を E2E で担保。
- README M3 使用例は `test_readme_m3_example_executes` で写経実行し文面と公開 API 実シグネチャの乖離を防止。

## ⚠️ 注意点・修正が必要な項目
- なし。スコープ内テスト全 green・スコープ外テスト失敗なし・完了条件 5/5 達成。
- Refactor は「機能不変・テスト意味不変」で __init__.py コメント追加 + ドキュメント整備に限定。

---
*Refactor フェーズ詳細は operando-integration-e2e-refactor-phase.md を参照。*
