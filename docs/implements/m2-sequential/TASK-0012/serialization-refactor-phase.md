# TASK-0012 store/serialization Refactorフェーズ記録

**日時**: 2026-07-03 / **要件名**: m2-sequential / **機能名**: serialization

## リファクタリング方針

Greenフェーズで全 15 テスト (N-01〜N-06 / E-01〜E-03 / B-01〜B-06) が green・141 行・ruff クリーンの
高品質実装が完成済み。YAGNI に従い、機能変更を伴わない可読性改善 1 件のみを適用し、残りの候補は
新規挙動の追加 (契約拡張) のため「変更不要」と判断した。

## 適用した改善

### 改善1: 内部ヘルパ定義位置の統一 (可読性 / 🔵)

- **内容**: `_value_or_default` を `phase_from_dict` の後方 (末尾) から、他の 2 ヘルパ
  (`_finite_or_none` / `_finite_map`) と同じモジュール冒頭 (`_finite_map` の直後・`phase_to_dict` の直前) へ移動。
- **理由**: 3 つの private ヘルパのうち 2 つが冒頭に定義されているのに 1 つだけ末尾にあり、
  定義位置が不統一だった。全ヘルパを冒頭にまとめることで「private ヘルパ群 → 公開 API 2 関数」の
  トップダウン構成となり読み下しやすくなる (refactoring_guidelines #1 可読性)。
- **安全性**: Python のモジュールレベル関数は呼び出し時解決のため定義順は機能に無影響。純粋な移動で
  ロジック無変更。移動後も 15 passed / ruff クリーンを確認。
- 🔵 信頼性: Greenフェーズ課題リスト (「`_value_or_default` の定義位置整理」) に明示。

## 見送った候補 (YAGNI / 変更不要判断)

- **lattice 必須キー a/b/c が None の場合の契約明文化**: 現状は素通し。テストが要求せず、
  例外送出等を足すと新規挙動 (契約拡張) になるため YAGNI で見送り。非有限入力の値保存は
  完了条件の対象外 (③ は JSON 安全性のみ要求) であり、現状の素通しで整合。🔵
- **docstring / インラインコメントの粒度統一**: 既に【機能概要】【実装方針】【テスト対応】+
  信頼性レベルの統一形式で高品質。追加改善の必要性低くコスト過多のため見送り。

## セキュリティレビュー結果

- 入力は Mapping / dataclass のみで外部 I/O・eval・SQL・シェル実行なし。インジェクション面なし。🔵
- `phase_from_dict` は `data.get()` の明示キー取り出しで未知キーを無視 (`**data` 展開を使わない) ため、
  悪意ある余分キーによる `TypeError`/属性汚染の余地なし (B-03 で担保)。🔵
- 非有限 float は `_finite_or_none` で None 化され、`json.dumps(allow_nan=False)` を通す純データのみ出力
  (JSON 破壊・DoS 入力の遮断)。重大な脆弱性なし。🔵

## パフォーマンスレビュー結果

- 時間計算量 O(n) (n = sigma + occupancies の要素数)。dict 内包表記による単一走査で最適。🔵
- 追加のコピー・変換は `dict(mapping)` 1 回のみ (呼び出し側からの隔離目的で必要)。冗長処理なし。🔵
- 純関数・入力無変更・乱数不使用で決定論的 (NFR-102)。重大な性能課題なし。テスト実行 0.73s (遅いテストなし)。🔵

## テスト実行結果

- `uv run pytest tests/test_serialization.py -q` → **15 passed** (N-01〜N-06 / E-01〜E-03 / B-01〜B-06 全 green)
- `uvx ruff@latest check src/tsumugin/store/serialization.py` → **All checks passed!**

## 改善後コード全文

`src/tsumugin/store/serialization.py` (141 行, ヘルパ 3 関数を冒頭に集約):
`_finite_or_none` / `_finite_map` / `_value_or_default` → `phase_to_dict` → `phase_from_dict`。
ロジックは Greenフェーズから不変 (定義位置のみ変更)。

## 品質判定

✅ **高品質**: 全 15 テスト継続成功 / ruff クリーン / 141 行 (≪ 500 行) / モック・スタブなし /
重大なセキュリティ脆弱性・性能課題なし / 日本語コメント統一形式維持 / 純関数・決定論。
