# TDD開発メモ: final-selection-engine (TASK-0021)

## 概要

- 機能名: FinalSelectionEngine + Decision (最終選択 agent/human 2 モード裁定)
- 要件名: m2-sequential / タスクID: TASK-0021
- 開発開始: 2026-07-03
- 現在のフェーズ: Refactor 完了

## 関連ファイル

- 要件定義: `docs/implements/m2-sequential/TASK-0021/final-selection-engine-requirements.md`
- テストケース定義: `docs/implements/m2-sequential/TASK-0021/final-selection-engine-testcases.md`
- タスクノート: `docs/implements/m2-sequential/TASK-0021/note.md`
- Red フェーズ記録: `docs/implements/m2-sequential/TASK-0021/final-selection-engine-red-phase.md`
- 実装ファイル (未作成): `src/tsumugin/selection/engine.py` (Decision / FinalSelectionEngine 追記)
- テストファイル: `tests/test_selection.py` (既存 19 件に 17 件を追記)

## Redフェーズ（失敗するテスト作成）

### 作成日時

2026-07-03

### テストケース

17 件 (正常系 8 / 異常系 4 / 境界値 5) を `tests/test_selection.py` 末尾に追記。
N-01〜N-08 / E-01〜E-04 / B-01〜B-05。詳細は red-phase.md の一覧表を参照。
`Decision` / `FinalSelectionEngine` は未実装のため、各テスト関数の**内部**で import して
既存 19 件 (TASK-0020) の collection を壊さないようにした。

### テストコード

`tests/test_selection.py` に追記済み (既存 19 件は無改変)。主なテストダブルは既存ヘルパ
`_ranked(hyp_id, rwp, close)` / `_result(ranked, *, unknown_phase=False)` を流用。

### 期待される失敗

```
uv run pytest tests/test_selection.py
=> 17 failed, 19 passed in 0.88s
```

新規 17 件はいずれも `ImportError: cannot import name 'FinalSelectionEngine'
(E-04 は 'Decision' も) from 'tsumugin.selection'` により FAILED。
既存 19 件は pass を維持。`uvx ruff check` は All checks passed! (line-length 100)。

### 次のフェーズへの要求事項

Green フェーズで `src/tsumugin/selection/engine.py` に `Decision` (frozen dataclass) と
`FinalSelectionEngine` (set_mode/decide/accept/revert/accepted) を追記し、
`selection/__init__.py` に re-export を追加する。実装契約は red-phase.md §4 を参照。
制約: D5 非破壊 / REQ-013 単一 accept 経路 / REQ-014 ledger 記録 / NFR-102 決定論 /
P2 追記型レジストリ。detect_escalations / ReviewQueue は無改変で利用する。

## Greenフェーズ（最小実装）

`src/tsumugin/selection/engine.py` に `Decision` (frozen dataclass) と `FinalSelectionEngine`
(`set_mode`/`decide`/`accept`/`revert`/`accepted`) を実装し、`selection/__init__.py` に re-export 済み。
`uv run pytest tests/test_selection.py` => 36 passed (既存 19 + 新規 17)。

## Refactorフェーズ（品質改善）

### 実施日時

2026-07-03

### 改善内容

- **フォーマット正規化 (ruff format)** 🔵: `decide` シグネチャと `can_auto_accept` 述語式が
  line-length 100 内に収まるのに折り返されていたため 1 行へ正規化。分岐可読性が向上 (機能変更なし)。
- **decide 分岐構造は変更不要と判断 (YAGNI)** 🔵: 4 分岐 (human/best 不在/自動 accept/暫定裁定) は
  すべてガード節 + 名前付き述語 `can_auto_accept` + 日本語コメントで表現済み。追加抽象化は間接層を
  増やし可読性を下げるため導入しない。

### セキュリティレビュー結果

重大な脆弱性なし。未知 id の accept/revert は KeyError で防御、入力 SearchResult は非破壊 (D5)、
ledger payload は素の型のみ。SQL/eval/外部コマンド実行なし。

### パフォーマンスレビュー結果

重大な性能課題なし。decide/accept とも ranked に対し O(n) 走査 1 回。決定論 (NFR-102) 維持。

### 品質評価

✅ 高品質: 36 passed 継続 / ruff clean / 317 行 (<500) / 日本語コメント完備 / ドキュメント完成。
詳細は `final-selection-engine-refactor-phase.md` を参照。

## Verify-Complete フェーズ（完全性検証）

### 🎯 最終結果 (2026-07-03)

- **実装率**: 100% (17/17 テストケース: 正常系 8 / 異常系 4 / 境界値 5)
- **要件網羅率**: 100% (完了条件 7 項目すべてに 1:1 以上でテスト対応)
- **テスト成功率**: 100% (スコープ内 tests/test_selection.py 36 passed)
- **全体テスト**: `uv run pytest` => 406 passed, 3 skipped in 13.31s (スコープ外失敗なし)
- **品質判定**: 合格 (高品質・完全達成)
- **TODO更新**: ✅ TASK-0021.md に完了マーク + 完了条件 7 checkbox 更新済み

### 完了条件 ↔ テストケース対応 (7 項目すべて充足)

| 完了条件 | 受け入れ基準 | テスト |
|---|---|---|
| agent 自動 accept (accepted_by=agent, ledger 根拠) | TC-107-01 | N-01 |
| agent 僅差 → provisional + Queue + 完了 | TC-107-02 | N-02 |
| human recommend のみ + 明示 accept(by=human) | TC-107-03 | N-03 / N-04 |
| set_mode が ledger 記録 | TC-107-04 | N-05 |
| revert → superseded + 履歴保持 | TC-107-05 | N-06 / B-05 |
| ranked 空 → accept なし + escalation のみ | TC-107-08 / EDGE-004 | E-01 |
| SearchResult 非破壊 | D5 | B-03 |

補助検証: N-07 (rationale/根拠 ledger) / N-08 (追記型 Mapping) / E-02・E-03 (未知 id KeyError) /
E-04 (Decision frozen) / B-01 (best.close のみ) / B-02 (unknown_phase のみ) / B-04 (rationale 決定論)。

### 💡 重要な技術学習

- **実装パターン**: 裁定の accepted 化は `dataclasses.replace` の新 Hypothesis で表現し、入力 SearchResult を
  非破壊 (D5) に保つ。agent 自動 accept も human 明示 accept も `_register_accept` の単一経路 (REQ-013)。
- **テスト設計**: 既存ヘルパ `_ranked` / `_result` を流用し木探索を回さず ranked/unmatched のみで境界を精密に
  制御。ledger 検証は engine 注入 `Ledger().entries` で行い result.ledger 非汚染 (D5) を独立確認。
- **品質保証**: detect_escalations の close_competitor は 2 位基準・Q8 の best.close は 1 位基準という
  意味差を B-01 で明示検証。決定論 (NFR-102) は B-04 で 2 エンジン独立実行の rationale 一致で保証。

### スコープ外・遅いテスト

- スコープ外テスト失敗: なし (全 406 passed)。
- 遅いテスト (2秒以上): なし (最遅 0.32s / 総 13.31s < 30s)。
