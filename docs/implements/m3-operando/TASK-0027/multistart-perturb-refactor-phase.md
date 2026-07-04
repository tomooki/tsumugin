# TASK-0027 TDD Refactor フェーズ — multistart/perturb (決定論摂動列)

**機能名**: multistart-perturb / **タスクID**: TASK-0027 / **要件名**: m3-operando
**フェーズ**: Phase 2 / **実施日**: 2026-07-04
**対象実装**: `src/tsumugin/multistart/perturb.py` (138 行) / `src/tsumugin/multistart/__init__.py` (15 行)
**対象テスト**: `tests/test_multistart_perturb.py` (18 件: 正常系 10 / 異常系 2 / 境界値 6)

> 全パスはプロジェクトルート相対。**【信頼性凡例】** 🔵 資料依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 1. リファクタリング判断: 変更不要 (YAGNI)

Green フェーズの実装は既に以下を満たしており、**構造的リファクタリングは不要**と判断した (YAGNI)。
機能追加・過剰な抽象化を避け、テストが担保する現状の設計を維持する。

| 観点 | 状態 | 根拠 |
|---|---|---|
| テスト成功 | ✅ 18/18 green | `uv run pytest tests/test_multistart_perturb.py` = 18 passed |
| 可読性 | ✅ 良好 | 全関数に日本語 docstring + 信頼性レベル (🔵🟡)、行内コメントで摂動意味論を明示 |
| 重複 (DRY) | ✅ なし | グリッド生成 `_grid_positions` / クリップ `_clip_unit` に共通化済み |
| 単一責任 | ✅ 分離済 | `_grid_positions` (決定論グリッド) / `_clip_unit` ([0,1] クリップ) / `generate_starts` (組立) |
| ファイルサイズ | ✅ 138 行 | 500 行制限に十分収まる。分割不要 |
| Lint / 型 | ✅ clean | `uvx ruff check src/tsumugin/multistart tests/test_multistart_perturb.py` = All checks passed |
| コメント品質 | ✅ 良好 | comment_template 準拠 (機能概要/実装方針/テスト対応/信頼性レベル) |

---

## 2. セキュリティレビュー

- 🔵 **入力信頼境界**: `generate_starts` は内部 API (後続 TASK-0028 が呼ぶ純関数)。外部入力・ユーザ文字列・
  ネットワーク・ファイル I/O・SQL・シェルを一切扱わないため、インジェクション/XSS/CSRF/データ漏洩の
  攻撃面は存在しない。
- 🔵 **決定論・乱数不使用 (NFR-102 / REQ-402)**: `random` / `np.random` を import していない
  (import は `dataclasses` と `tsumugin.model` のみ)。摂動値は start index `i`・相 index `j`・
  site index `s`・パラメータ種別のみの純関数。予測可能性はセキュリティ上むしろ望ましい (再現性保証)。
- 🔵 **非破壊性 (P2 / REQ-404)**: 入力 `phases` / `LatticeParams` / `occupancies` を破壊しない
  (`replace` / `with_updates` / 新 dict による非破壊生成)。T-B02 で検証済。状態汚染リスクなし。
- **判定**: 重大な脆弱性なし。追加対策不要。

---

## 3. パフォーマンスレビュー

- 🔵 **計算量**: 時間 O(N × P × S) (N=start 数, P=相数, S=最大 site 数)、空間 O(N × P)。
  マルチスタート本数は FR-231 で 8-16、相数・site 数も小さい実運用規模のため十分高速。
- 🔵 **グリッド生成**: `_grid_positions` は O(m) のリスト内包で 1 start 群あたり定数回参照。
  重い数値ライブラリ呼び出し (np.linspace 等) を使わず標準演算で完結し、オーバヘッド最小。
- 🔵 **テスト実行時間**: 18 件が瞬時に完了 (2 秒超の遅いテストなし)。最適化不要。
- **判定**: 重大な性能課題なし。追加最適化不要。

---

## 4. コード品質確認結果

- **除外チェック**: `describe.skip` / `it.skip` / `test.skip` 等の無効化テストなし。
  `pyproject.toml` の `testPathIgnorePatterns` 相当による対象ファイル除外なし。全 18 件が実行対象。
- **開発時生成ファイル**: `debug-*` / `test-*` (一時) / `*.tmp` / `*.bak` 等の不要ファイルなし
  (`git status` は本タスクの正規成果物 3 パスのみを未追跡として表示)。クリーンアップ対象なし。
- **依存**: コア依存は numpy のみ (REQ-403) の制約下だが、本実装は numpy すら使わず標準ライブラリで
  完結 (追加依存ゼロ)。制約を満たす最軽量構成。

---

## 5. 品質判定

```
✅ 高品質:
- テスト結果: 18/18 継続成功 (全 green、遅いテストなし)
- セキュリティ: 重大な脆弱性なし (乱数不使用・非破壊・攻撃面なし)
- パフォーマンス: 重大な性能課題なし (O(N·P·S)・標準演算)
- リファクタ品質: 目標達成 (YAGNI に基づき構造変更不要と判断)
- コード品質: 適切 (138 行・DRY・単一責任・Lint clean・日本語コメント充実)
- ドキュメント: 完成 (本 refactor-phase / memo 更新)
```

**次のお勧めステップ**: `/tsumiki:tdd-verify-complete m3-operando TASK-0027` で完全性検証を実行します。
