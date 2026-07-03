# multistart-perturb (決定論摂動列) TDD開発完了記録

## 確認すべきドキュメント

- `docs/tasks/m3-operando/TASK-0027.md`
- `docs/implements/m3-operando/TASK-0027/multistart-perturb-requirements.md`
- `docs/implements/m3-operando/TASK-0027/multistart-perturb-testcases.md`
- `docs/implements/m3-operando/TASK-0027/multistart-perturb-refactor-phase.md`

## 🎯 最終結果 (2026-07-04)
- **実装率**: 100% (18/18 テストケース)
- **品質判定**: 合格 (スコープ内 18/18 green、全体 520 passed + 3 skip)
- **TODO更新**: ✅完了マーク追加 (TASK-0027.md 完了条件 4 項目 + checkbox 更新)

## 概要
- **対象実装**: `src/tsumugin/multistart/perturb.py` (138 行) / `src/tsumugin/multistart/__init__.py` (15 行)
- **対象テスト**: `tests/test_multistart_perturb.py` (18 件: 正常系 10 / 異常系 2 / 境界値 6)
- **要旨**: マルチスタート大域最適確認 (FR-230) の初期値摂動列生成器を、乱数不使用の
  index ベース決定論列として実装。i=0 無摂動、i≥1 は格子等間隔グリッド / scale 対数一様グリッド /
  占有率固定 LHS で一意に決まる。非破壊生成。

## 💡 重要な技術学習
### 実装パターン
- **乱数不使用の決定論摂動 (NFR-102)**: `random`/`np.random` を持たず、start index `i`・相 index `j`・
  site index `s` のみの純関数でグリッド点を導出。`_grid_positions(m)` が [-1,1] 等間隔列を返し、
  m<=0 で空 (N=1 縮退)・m==1 で単一点 (N=2) の境界を明示処理して 0 除算を回避。
- **decorrelate**: 格子と scale を `half=m//2` だけグリッド上でずらし、i≥1 の全 start が
  基準と必ず異なる (縮退しない) ことを保証。
- **非破壊生成 (P2/REQ-404)**: `dataclasses.replace(lattice, ...)` + `PhaseInstance.with_updates(...)` +
  新 dict で入力 `phases` を破壊せず独立インスタンスを返す。

### テスト設計
- **決定論は `==`**: ビット同一検証は frozen dataclass の構造的等価 (`starts_a == starts_b`) で担保。
- **範囲検証**: 格子は相対倍率域、scale は `math.log10` の対数域、占有率は [0,1] クリップ + 幅で検証。
- **境界**: N=1 縮退 / N=2 最小非退化 / 空 occupancies / [0,1] 境界クリップ / frozen / 非破壊を網羅。

### 品質保証
- 純関数・攻撃面なし・追加依存ゼロ (numpy すら不使用) で REQ-403 を最軽量で満たす。
- Refactor は YAGNI に基づき構造変更なし (Green 実装が可読性/DRY/単一責任/500 行制限/Lint を既達成)。

## 検証結果 (完全性)
- **スコープ内テスト**: `tests/test_multistart_perturb.py` 18/18 green。
- **スコープ外テスト**: 失敗なし (全体 520 passed + @gsas 3 skip = 523 collected、無退行維持)。
- **完了条件網羅**: TASK-0027 の 4 完了条件すべてテスト対応・green
  (決定論=T-N02 / 摂動範囲=T-N04・N05・N06・E02 / i=0 無摂動・N=1 縮退=T-N03・B01 / 多相各相摂動=T-N07)。
- **テスト実行時間**: 全体 15.72s (30s 未満)、2 秒超の遅いテストなし。
- **要件網羅率**: 100% (要件定義書 §2 I/O・§3 制約・§4 使用例をすべて実装・テスト)。

## ⚠️ 注意点・修正が必要な項目
- なし。スコープ内・スコープ外とも失敗ゼロ、修正対象なし。
- 後続 TASK-0028 は `PerturbationSpec`/`MultistartConfig` フィールド名・`generate_starts` シグネチャ
  (`phases, *, config`)・戻り値型を interfaces.py D1 契約どおり消費すること (壊さない)。
