---
name: issue-work
description: トリアージ済の GitHub Issue を 1 件受け取り、実地確認 → TDD → 自己レビュー → PR まで進める自動処理ループの 1 周回。ゲート級 (gate:fast / gate:gsas / gate:bench / gate:human) で受け入れ条件と実行系を切り替え、「テストが green なので完了」型の無言成功を 3 つの検出器 (ゼロ差分 / red→green 実測 / 変異証明) で殺す。マージ・close・main への push・外部への発信はしない。設計は docs/design/issue-auto-loop/architecture.md。
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, Skill
---

# issue-work — Issue 自動処理ループの 1 周回 (③ 実行層)

引数: `/issue-work <issue番号> [--dry-run]`

`--dry-run` のとき: **S1 までで止まり、計画レポートをローカルに書くだけ**。
ブランチも PR も作らず、GitHub へ 1 バイトも書かない。段 0 の既定はこちら。

設計の正: `docs/design/issue-auto-loop/architecture.md`。
本 skill が実行可能な指示であることは、その設計の §4 (段構成) の写像である。
**手順書の誤りは実装バグと同等に有害** — ② に無い操作をここに書かない。

---

## 0. この周回が守る唯一のこと

**「失敗しているのに完走して見える」を作らない。**

本リポジトリは同型の欠陥を実際に 2 回踏んでいる — GSAS-II の `Refine` が失敗を戻り値で返すのに
`G2Project.refine` がそれを捨てていた件と、`tc.exe` が INP 構文エラーでも終了コード 0 を返す件。
**自律ループにも同じ穴が開く**: 差分ゼロで「直しました」と言う周回、既に green だったテストを
足して「テストを追加しました」と言う周回、変異させても落ちないガードを置く周回。
どれも最終報告だけ見ると成功に見える。§4 の検出器はこのために在る。

---

## 1. ゲート級を読む (S0)

Issue のラベルから gate を決める。**gate が無い Issue には着手しない** (未トリアージ)。

| ラベル | 受け入れ条件 | 実行系 | 到達点 |
|---|---|---|---|
| `gate:fast` | `ruff` + `pytest -m "not gsas"` + §4 の証明 3 種 (+ **`frontend/` を触ったときだけ** oxlint/vitest/build) | どこでも | PR 作成 |
| `gate:gsas` | 上記 + 該当 `-m gsas` サブセット green | **ローカルのみ** | PR 作成 |
| `gate:bench` | 上記 + ベンチ再測定表 | **ローカルのみ** | **PR を作らない**。測定レポートまで |
| `gate:human` | — | — | **着手しない**。調査メモのみ |

```bash
gh issue view <N> --json number,title,body,labels,comments
```

⚠ `gate:gsas` を GitHub Actions の runner で回さない。runner に GSAS-II も TOPAS も実データも無く、
fast tier だけが green になって**「完了」と報告する周回**になる。これが §0 そのもの。

---

## 2. 実地確認 — 本文を信じない (S1)

**Issue 本文の主張を、コードに当ててから着手する。** 実例が既にある
(`docs/tasks/issue-triage/2026-08-19-triage.md` §3):

- **#200** は「① が返さない」と読めるが実際は ① は返しており、**② の露出ギャップ**だった。
  本文どおり ① にフィールドを足すと**不要な二重実装**になる。
- **#189** の「`is None` 判定にする」は、既定値が `()` で `None` になる経路が無いため
  そのままでは直らず、**「全レシピで Uiso が一切解放されない」逆向きの沈黙誤り**を作る。

やること:

1. 本文が名指ししている関数・行を `grep -n` / `sed -n` で**実際に開く**。
2. 主張ごとに `path:line` の根拠を書く。「たぶんそう」は根拠ではない。
3. 既に解決済でないかを確認する (呼び出し元の有無だけで判定しない — #70 が
   「実装済に見えるが要求している結線は未着手」の実例)。

**判定**:

| 確認結果 | 次 | ラベル |
|---|---|---|
| 本文どおり | S2 へ | (そのまま) |
| 既に解決済 | **実装しない**。確認結果を証跡に書く (人間が close を判断) | `loop:blocked` |
| 本文の指示だと壊れる | **実装しない**。何がどう壊れるかを証跡に書く | `loop:blocked` |
| 主張が確認できない (再現手順が無い等) | **実装しない**。何が足りないかを書く | `loop:blocked` |

⚠ **止まるときは必ずラベルを進めること。** 起動時に `loop:queued` は既に外れ
`loop:in-progress` が付いているので、**何もせず終了すると Issue は永久に in-progress に
なる** — キューからも外れ `loop:review` にも進まないため、判定が正しくても**人間の目に
留まらない**。`gate:bench` の「PR を作らず測定レポートまで」も同じ:

```bash
gh issue edit <N> --add-label loop:blocked --remove-label loop:in-progress
```

`--dry-run` はここで終わり。レポートを `scratchpad/issue-loop/<N>-plan.md` に書く。

---

## 3. TDD (S2 → S3)

**S2 赤** — 失敗するテストを先に書き、**実行して落ちることを実測する**。

```bash
uv run pytest tests/<新テスト> -x
```

- 出力 (失敗行) を証跡にそのまま貼る。**「落ちるはず」は証拠ではない。**
- ここで**通ってしまったら停止**する。そのテストは何も守っていない。
  「バグを直した」と言いながら追加したテストが最初から green なのは、
  修正対象が存在しないか、テストが対象を突いていないかのどちらか。

**S3 緑** — 最小実装。テストなしの実装コミットは禁止 (CLAUDE.md)。

---

## 4. 無言成功の検出器 (S4 / 必須)

### (1) ゼロ差分検出

```bash
git diff --stat main...HEAD
```

`src/` に差分が無いのに「バグを直した」と報告する周回は**失敗として扱う**。
テストファイルだけの差分も同様 (仕様変更でない限り)。

### (2) red→green の実測 — S2 で済ませてある

### (3) 変異証明 (ガード系テストを足したとき **必ず**)

CLAUDE.md の恒久規則: **落ちないガードは無いより悪い**。

```bash
# 1. 直した src を逆向きに変異させる (修正前の挙動へ戻す)
#    2. 新しいテストを走らせる → **落ちなければ停止**
uv run pytest tests/<新テスト> -x
# 3. 変異を revert
git checkout -- src/tsumugin/<変異させたファイル>
```

変異させても通るガードは**置かない**。証跡に「変異内容」と「落ちたこと」を書く。

---

## 5. 露出確認 (S5)

`src/tsumugin/**` に**公開シンボルが増えた**なら、CLAUDE.md の ★ 不変条件が発動する:

1. ② MCP ツール (または既存ツールの JSON 引数) から到達できるか
2. ③ の手順書 (`plugins/tsumugin/skills/*/SKILL.md`) に「いつ使うか」があるか
3. 露出しないと決めたなら**理由付きで宣言**したか (黙って未露出にしない)

機械強制がある:

```bash
uv run pytest tests/test_layer_coverage.py
```

**完了の定義は「テストが green」ではなく「③ が実際に呼べる」。**
callable 引数だけの経路は不可 (③ は JSON しか送れない)。

---

## 6. ゲート実行 (S6)

```bash
uv run ruff check src tests
uv run pytest -m "not gsas and not agent"
```

`gate:gsas` は加えて**該当サブセット**を回す (フルの `-m gsas` は ~50 分。PR 直前の 1 回だけ):

```bash
uv run pytest -m gsas -k "<関係するテスト>"
```

`gate:bench` は加えてベンチ再測定 (`tools/bench_recipes.py`)。結果は `*/results/` (gitignore) へ。

落ちたら S3 へ戻る。**戻れるのは 2 回まで。** 3 回目は `loop:blocked` にして人間へ渡す。

### ⚠ ローカル実行の 3 つの罠 (踏むと周回が静かに無意味になる)

- **worktree の editable install シャドウ** (ローカルの `--worktree` 実行のときだけ。GitHub
  Actions の runner は通常の checkout なので該当しない) — editable install は **main の `src`**
  を指す。worktree でテストを回すと**別のソースを検証してしまう**。必ず:
  ```powershell
  $env:PYTHONPATH = "$PWD\src"
  ```
- **パイプが終了コードを潰す** (PowerShell / bash 双方で実測) — `pytest | tee log` は
  **成否を偽陰性化する**。素で実行し、終了コードを別途記録する。
- **`git add -A` 厳禁** — `scratchpad/` は gitignore だが**追跡済みの `.py` がある**。
  変更ファイルを**明示列挙**して add する。

---

## 7. 自己レビュー (S7)

`/code-review` を**新規指摘が出なくなるまで**回す (CLAUDE.md の既定運用)。
MEDIUM/LOW も直す。見送るのは明確な誤検出か、**理由を添えた意図的な設計判断**のみ。
3 周しても新規指摘が続くなら人間へ渡す (収束していない = まだ設計が定まっていない兆候)。

---

## 8. 提出 (S8)

1. ブランチ `auto/issue-<N>` に明示列挙で add してコミット
2. PR を作る (`gh pr create`)。本文に §9 の証跡を入れる
3. Issue にラベル遷移 `loop:in-progress` → `loop:review`

**やらないこと**: マージ / `main` への push / Issue の close / ラベルの剥がし。

**どの終わり方でも `loop:in-progress` のまま終了しない** — 提出したなら `loop:review`、
止まったなら `loop:blocked`。どちらでもない終了は「誰も気づかない完了」になる。

---

## 9. 証跡の書式 (固定)

Issue コメントと PR 本文に、この形で**必ず**残す。空欄を作らない。

~~~markdown
## 自動周回 <日付> — Issue #<N> (gate:<級>)

**S1 実地確認**: <本文どおり / 既に解決済 / 本文の指示だと壊れる / 確認できない>
- <主張1> → `path:line` <確認結果>

**S2 red**: `<テスト名>` を base で実行 → 失敗を確認
```
<失敗出力の要点>
```

**S4 変異証明**: <変異内容> → 新テストが落ちることを確認 / (ガード追加なし)

**S5 露出**: <② ツール名 / ③ SKILL.md の該当節 / 非露出と理由 / 公開シンボル追加なし>

**S6 ゲート**: ruff ✓ / fast tier ✓ / `-m gsas -k <...>` ✓ / (bench 表)

**S7 自己レビュー**: <周回数> 周で新規指摘なし。見送り: <指摘と理由 / なし>

**やらなかったこと**: <スコープ外に落としたものと理由。無ければ「なし」>
~~~

**「やらなかったこと」を空にしない。** 部分的にしか直せなかったなら、
そう書いて残りを Issue に残す — 黙って縮小するのは人間の判断を奪う。

---

## 10. ハード境界 (どの周回でも越えない)

- **マージしない / `main` に push しない / Issue を close しない。**
- **第三者への発信をしない** — upstream への報告 (#136)、外部 DB への取得 (#10) は
  下書きまで。投稿・取得は人間が行う。
- **`docs/benchmark/` 配下のデータを追加・変更しない** (public repo の由来規約)。
  `tests/test_docs_provenance.py` が fast tier で強制する。
- **未公開データ由来の数値を PR 本文・コメントに書かない。**
- **`loop:*` 以外のラベルを触らない** — 優先度・領域は人間のトリアージ結果。
- **同じ Issue に 3 回目の自動着手をしない** — 2 回失敗で `loop:blocked` + 理由コメント。
  失敗が伝わらないまま回り続けるのが最悪の形。
