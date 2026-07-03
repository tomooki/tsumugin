# peak-matcher (PeakMatcher) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m1-hypothesis-search/TASK-0003.md`
- `docs/implements/m1-hypothesis-search/TASK-0003/peak-matcher-requirements.md`
- `docs/implements/m1-hypothesis-search/TASK-0003/peak-matcher-testcases.md`

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (19/19 テストケース定義 → 22 test items 実装)
- **成功率**: 100% (test_matcher.py 22 passed / スコープ内失敗 0)
- **全体テスト**: 109 passed, 1 skipped (skip は gsas マーカーのスコープ外テスト)
- **品質判定**: 合格 (高品質 — 要件網羅率 100%)
- **TODO更新**: ✅完了マーク追加 (TASK-0003.md 完了条件 5/5 チェック済み)

## 実装・検証対象
- 実装: `src/tsumugin/search/matcher.py` (`MatchResult`, `match_score`, `UnmatchedPeakReport`, `unmatched_peaks`)
- 公開集約: `src/tsumugin/search/__init__.py` の `__all__` に 4 シンボル追記済み
- テスト: `tests/test_matcher.py` (19 関数, TC-N04 ×3 / TC-E04 ×2 parametrize = 22 items)

## テストケース網羅 (19/19)
- 正常系 10: TC-N01(TC-002-01 一致>不一致) / N02(matched_observed 昇順) / N03(unmatched_candidate extra) /
  N04(score∈[0,1]) / N05(candidate_index 伝搬・kw専用) / N06(決定論) / N07(TC-005-01 未マッチ報告+flag) /
  N08(TC-005-02 完全説明で空・flag False) / N09(frozen 不変) / N10(等重み式 0.375 数値一致)
- 異常系 4: TC-E01(候補ゼロ縮退) / E02(観測ゼロ・全 extra EDGE-003) / E03(high_r_flag=True 強制 REQ-106) /
  E04(フラット観測空 TC-005-03)
- 境界値 5: TC-B01(tol 閉区間内マッチ) / B02(tol 超過 extra) / B03(境界決定論) /
  B04(貪欲 1:1 重複防止) / B05(extra_calculated 昇順・重複排除)

## 要件充足
- REQ-002 (FR-111 マッチングスコア): TC-N01/N04/N10 で充足
- REQ-005 (FR-117 未マッチ/extra 構造化出力): TC-N02/N03/N07/N08/B05 で充足
- REQ-106 (全仮説高 R で未知相フラグ強制): TC-E03 で充足
- EDGE-003 (観測ゼロ縮退・例外禁止): TC-E02/E04 で充足
- NFR-102/REQ-403 (決定論): TC-N06/B03 で充足
- REQ-402 (非破壊 frozen): TC-N09 で充足

## 💡 重要な技術学習
### 実装パターン
- 貪欲 1:1 マッチ: 候補を位置昇順走査 + `used[]` フラグで未使用最近傍観測を 1 本確保。
  best_diff=inf 番兵で None 特例分岐を排除し決定論を担保。
- 縮退設計: 分母 0 (候補 0 / 観測 0) を三項で 0.0 に落とし例外を投げない (M0 規約)。
- 集約: `unmatched_peaks` は match_results を 1 パス走査で explained index と extra 位置を同時構築 (DRY)。

### テスト設計
- 手計算検算 (TC-N10 score=0.375) と教師データ生成 (simulate→find_peaks) を併用し絶対値と相対比較を両立。
- 決定論は approx でなく `==` (frozen dataclass 値等価) で検証。
- 境界値は tol ちょうど (0.15) / 僅超 (0.16) を対で配置しオフバイワンを排除。

### 品質保証
- キーワード専用引数 (candidate_index / tol_deg / high_r_flag) を pytest.raises(TypeError) で契約検証。
- frozen 不変性を FrozenInstanceError で検証し非破壊契約を保証。

## ⚠️ 注意点・修正が必要な項目
- スコープ内の未実装・失敗なし。修正対象なし。
- スコープ外: 全体 1 skipped は `gsas` マーカー付きテスト (GSAS-II 依存, 本タスク非対象)。失敗ではないため対応不要。
- 環境ノイズ: pytest 起動時に `Error reading {cfgfile} 'utf-8' codec ...` の警告が出るが GSAS-II 側の
  設定ファイル読込で、テスト結果 (109 passed) には影響しない。

---
*Refactor 済み実装 (matcher.py) と testcases.md を照合し検証。要件網羅率 100%・スコープ内成功率 100% を確認。*
