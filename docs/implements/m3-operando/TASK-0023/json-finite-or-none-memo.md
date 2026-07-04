# json-finite-or-none (`_json.finite_or_none` 統合, Issue #5) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m3-operando/TASK-0023.md`
- `docs/implements/m3-operando/TASK-0023/json-finite-or-none-requirements.md`
- `docs/implements/m3-operando/TASK-0023/json-finite-or-none-testcases.md`
- `docs/implements/m3-operando/TASK-0023/json-finite-or-none-refactor-phase.md`

## 🎯 最終結果 (2026-07-03)
- **実装率**: 100% (16/16 テストケース定義を網羅 / `tests/test_json_util.py` 16 items)
- **テスト状況**: 全体 **446 passed / 3 skipped** (スコープ内・スコープ外ともグリーン、失敗ゼロ)
  - ベースライン 430 passed + 新規 16 = 446 passed。3 skip は gsas マーカー (未導入環境用、スコープ外・想定内)
- **Lint**: `uvx ruff check src tests` All checks passed!
- **品質判定**: 合格 (高品質・完全達成)
- **TODO更新**: ✅ 完了マーク追加 (`docs/tasks/m3-operando/TASK-0023.md` 完了条件 3/4 チェック、
  4 項目目「コミットに Closes #5」はコミット時付与のため未チェック=本セッションは commit しない制約)

## 💡 重要な技術学習
### 実装パターン
- **無依存の葉モジュール化**: 重複ユーティリティを `src/tsumugin/_json.py` (標準ライブラリ `math` のみ依存) へ集約し、
  全層が下向き import する形にすることで、webui→search / store→search の**レイヤ逆依存を解消**。
- **委譲 + 局所性の両立**: 汎用判定 (非有限→None) は葉へ委譲しつつ、ドメイン固有ロジック
  (探索センチネル `>= _EVIDENCE_SENTINEL`) は呼び出し側 (tree) に残す設計 (D-Q9)。
- **None 許容の上位互換**: 統合先を `float | None -> float | None` にして serialization の `None` 入力経路を保存
  (tree は `float` のみ渡すため上位互換で問題なし)。

### テスト設計
- **委譲の同一性検証**: `ser.finite_or_none is finite_or_none` のように**関数オブジェクト同一性 (`is`)** を assert し、
  重複定義の廃止・単一情報源化を機械的に固定。
- **レイヤ制約の回帰ガード**: `inspect.getsource` で葉モジュールソースに上位レイヤ/`import numpy` が
  含まれないことを検査し、将来の逆依存混入を恒久防止 (TC-J-R05)。
- **挙動不変の担保**: 新規コードを足さず既存テスト無改変 green (TC-J-R01~R04) でリファクタの非退行を証明。

### 品質保証
- 非有限値を JSON 配信前に `None` へ縮退させ `json.dumps(allow_nan=False)` の ValueError を防ぐ (EDGE-004 / M1 教訓)。
- `0.0` 等の falsy な有限値を `is None` / `math.isfinite` で正しく分岐し None に潰さない (B-06 思想)。

## ⚠️ 注意点・修正が必要な項目
- **修正が必要な項目なし** (スコープ内・スコープ外ともテスト失敗ゼロ、実装不足ゼロ)。
- Refactor は YAGNI に基づき**コード変更不要**と判断 (Green 完了時点で高品質)。詳細は refactor-phase.md 参照。
- **コミット未実施**: 完了条件「コミットに "Closes #5"」は本セッションの git commit しない制約により未実施。
  ユーザーがコミットする際に "Closes #5" を含めること。
- **統合対象外 (触っていない)**: `sequential/trajectory.py::_num_cell` は戻り値 `str` (CSV 用) でシグネチャが異なり本タスク対象外。

---
*Red→Green→Refactor→Verify の経過は各フェーズ文書へ集約。本メモは最終結果と再利用可能な学習に絞る。*
