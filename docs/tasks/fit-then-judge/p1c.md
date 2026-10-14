# fit-then-judge P1c — 作業計画

設計 [`docs/design/fit-then-judge/p1c-architecture.md`](../../design/fit-then-judge/p1c-architecture.md)。
branch `milestone/fit-then-judge-1c` (worktree `../tsumugin-ftj-1b`)。タスク 1 件 green ごとに 1 コミット。
ガード系テストは変異させて落ちることを確かめる。マージ前に PR に対して `/code-review` を回す (CLAUDE.md)。

小さめの段階なので要件は設計書の §1 の表と本書の受け入れ条件で足りる (spec は作らない)。

| # | タスク | 主な成果物 | テスト | 状態 |
|---|---|---|---|---|
| 0 | 設計・作業計画 | 本書・設計書 | — | done |
| 1 | 出版状態の計算と記録を 1 つに | `claims/publication.py` (`publication_state`・`input_publication`)。② `_attach_claims` はそれを呼ぶだけに | ② の出力が変わらないこと (既存テスト) + 失敗時の縮退 + `input_publication` の各状態 | done |
| 2 | MEM 系ツール | `mem_density`・`mem_rietveld_iterate` に `input_publication`。③ `skills/mem-model-fix` + PLAYBOOK の読み方 | ② の出力 (sidecar あり/なし/不一致)・例外にしない・手順書ガード (変異実証) | done |
| 3 | ワークベンチ | `_on_refine_success` で出版状態・sidecar・viewmodel `publication`・ledger `publication_assessed`。`api-contract.md` | セッションのテスト (注入 runner)・失敗時の縮退・demo/none ではキーを省略 | done |
| 4 | フロント | 型・FIT タブの PUBLICATION カードと判断要求のカード (読み取りのみ)・文字列 (日英) | vitest (表示・未知の語彙で落ちない・回答ボタンが無い) | done |
| 5 | 仕上げ | layer coverage・全テスト・PR・`/code-review` | — | |

## 受け入れ条件

- ② `auto_rietveld` / `refine_with_revisions` の出力はビット同一 (出版状態のキーを含めて)。
- MEM 系ツールは sidecar の無い gpx でも従来どおり動き、`input_publication.state: "unknown"` を返す。
- GUI の精密化の後、FIT タブに出版状態と判断要求が出る。数値の表示は `publishable` と状態を必ず伴う。判断要求に回答する操作は無い。

## 実装して分かったこと

- **GUI の精密化は出版状態を一度も作っていなかった** (② の `auto_rietveld` を通らず engine を直接呼ぶ)。GUI の数値はすべて平文で、
  GUI の MEM の入力 gpx は常に sidecar が無い = 状態不明だった。計算と記録を `claims.publication` に一本化して、GUI の精密化からも
  sidecar が書かれ、GUI の MEM が `input_publication.state: "known"` を読めることを合成 ZnO の gated テストで確かめた
  (`tests/workbench/test_publication_gsas.py`)。
- 精密化の ledger は `refine_finished` の後に `publication_assessed` (GUARD) が 1 件増える (既存の契約テストを更新)。

## 開発に使ったデータ

- 合成 (`S-dev`): wurtzite ZnO — GUI の精密化から sidecar と MEM の入力状態まで。(準) hold-out は参照していない
  (既存の CaTeO3 の GUI e2e には新しい検査を足していない — `tests/test_holdout_guard.py`)。
