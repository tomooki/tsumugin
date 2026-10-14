# fit-then-judge P1c — 作業計画

設計 [`docs/design/fit-then-judge/p1c-architecture.md`](../../design/fit-then-judge/p1c-architecture.md)。
branch `milestone/fit-then-judge-1c` (worktree `../tsumugin-ftj-1b`)。タスク 1 件 green ごとに 1 コミット。
ガード系テストは変異させて落ちることを確かめる。マージ前に PR に対して `/code-review` を回す (CLAUDE.md)。

小さめの段階なので要件は設計書の §1 の表と本書の受け入れ条件で足りる (spec は作らない)。

| # | タスク | 主な成果物 | テスト | 状態 |
|---|---|---|---|---|
| 0 | 設計・作業計画 | 本書・設計書 | — | done |
| 1 | 出版状態の計算と記録を 1 つに | `claims/publication.py` (`publication_state`・`input_publication`)。② `_attach_claims` はそれを呼ぶだけに | ② の出力が変わらないこと (既存テスト) + 失敗時の縮退 + `input_publication` の各状態 | |
| 2 | MEM 系ツール | `mem_density`・`mem_rietveld_iterate` に `input_publication`。③ `skills/mem-model-fix` + PLAYBOOK の読み方 | ② の出力 (sidecar あり/なし/不一致)・例外にしない・手順書ガード (変異実証) | |
| 3 | ワークベンチ | `_on_refine_success` で出版状態・sidecar・viewmodel `publication`・ledger `publication_assessed`。`api-contract.md` | セッションのテスト (注入 runner)・失敗時の縮退・demo/none ではキーを省略 | |
| 4 | フロント | 型・FIT タブの PUBLICATION カードと判断要求のカード (読み取りのみ)・文字列 (日英) | vitest (表示・未知の語彙で落ちない・回答ボタンが無い) | |
| 5 | 仕上げ | layer coverage・全テスト・PR・`/code-review` | — | |

## 受け入れ条件

- ② `auto_rietveld` / `refine_with_revisions` の出力はビット同一 (出版状態のキーを含めて)。
- MEM 系ツールは sidecar の無い gpx でも従来どおり動き、`input_publication.state: "unknown"` を返す。
- GUI の精密化の後、FIT タブに出版状態と判断要求が出る。数値の表示は `publishable` と状態を必ず伴う。判断要求に回答する操作は無い。
