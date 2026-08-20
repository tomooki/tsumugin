# Issue 自動処理ループの設計 (loop engineering)

対象: `tomooki/tsumugin` (public, OPEN 53 件 / 2026-08-20 時点)。
前提入力: `docs/tasks/issue-triage/2026-08-19-triage.md` (全 53 件の実地確認済トリアージ + 付与済ラベル)。

---

## 0. 先に結論 — 「専用ツール」は存在しない

「Issue を自動で処理する」ための**専用スキル/プラグインは無い** (カタログ検索 = 0 件)。
存在するのは**部品**だけで、ループの規律は自分で書く必要がある。

| 部品 | 実体 | この用途での位置づけ |
|---|---|---|
| `claude-code-action@v1` | GitHub Actions。`prompt` を渡すと **automation mode** で `@claude` 不要で走る。`schedule` / `issues` / `issue_comment` すべてトリガ可 | **クラウド側の実行系**。ただし本リポジトリでは `-m gsas` が回らないので**適用できる Issue が限られる** (§1) |
| `/install-github-app` | 上記のセットアップ。`CLAUDE_CODE_OAUTH_TOKEN` (= `claude setup-token`) をリポジトリ secret に置く | 導入手順 |
| `/loop` (組込スキル) | 同一セッションで prompt/slash コマンドを間隔実行。間隔省略で自己ペース | **ローカル側の周回ドライバ**。1 セッション内なので状態が持てる反面、落ちると止まる |
| `/schedule` + `CronCreate` | cron で動くクラウド routine | 定時トリガ (棚卸し・進捗報告) 向き。**実装作業には向かない** (ローカル資産が無い) |
| `claude --bg` / `claude agents` / `-w, --worktree` | バックグラウンドエージェント + git worktree 隔離 | **ローカル側のワーカー実体**。`.claude/worktrees/` は既に使われている |
| `Workflow` ツール | 決定論スクリプトで subagent をファンアウト | 1 Issue 内の多角レビューには使えるが、**Issue キュー全体の周回には使わない** (状態が揮発する) |
| `loggbas` プラグイン (自作) | capture→clarify→**dispatcher→worker→reviewer**→trust 分岐→承認/却下→ledger | **最も近い既存設計**。「自律実行 + 人間ゲート + 追記型台帳」を既に解いている。GitHub Issue を入力に接続する選択肢はあるが、本設計は **GitHub 自身を台帳に使う** 方を採る (§3) |

> 結論: **`claude-code-action` (クラウド) + `claude --bg --worktree` (ローカル) を、
> GitHub のラベルを状態機械にして回す**。新しいデーモンは書かない。

---

## 1. このリポジトリで実際に律速になるもの

汎用の「Issue → PR ボット」をそのまま当てると**必ず失敗する**。理由は 3 つで、すべて本リポジトリ固有。

### (a) 検証の非対称性 — CI で証明できる Issue は少数派

CI (`.github/workflows/ci.yml`) が回すのは `ruff` + `pytest -m "not gsas and not agent"` + frontend だけ。
実 Rietveld (`-m gsas`, ~50 分) は **GSAS-II が PyPI 非公開でソースツリー + ビルド済みバイナリを要する**ため
runner で再現できない。TOPAS (`tc.exe`) と実測データも同様。

→ **クラウドのループが「green だから完了」と言える Issue は、53 件中の一部でしかない。**
残りは Windows のローカル機 (GSAS-II + 実データ) でしか受け入れ判定ができない。
この非対称性を設計の中心に置く (§2 のゲート級)。

### (b) Issue 本文がコードと合っていないことが実際にある

トリアージ §3 が確認した通り、53 件中 **5 件が現状と食い違い**、うち 2 件は
**本文の指示どおり直すと壊れる**:

- **#200** — 本文は「① が返さない」と読めるが、実際は ① は返しており **② の露出ギャップ**。
  本文どおり ① にフィールドを足すと**不要な二重実装**になる。
- **#189** — 本文の「`is None` 判定にする」は、既定値が `()` で `None` になる経路が無いため
  **そのままでは直らない**どころか「全レシピで Uiso が一切解放されない」**逆向きの沈黙誤り**を作る。

→ ループの第 1 段は実装ではなく **「本文の主張をコードで実地確認する」** で、
**食い違ったら実装せずコメントして止まる**こと。ここを省くと、自律ループは
「指示どおり正しく間違える」。

### (c) 既定を動かす修正はベンチ全体の再測定を連れてくる

#169 / #198 / #190 は妥当性ゲートや拘束の**既定**を動かす。動かすと T1–T4 / CaTeO3 の
判定が全部動く。しかも `tc.exe` はスレッド数で結果が変わる (`OMP_NUM_THREADS=1` で固定済) など、
**測定条件を揃えないと比較が成立しない**履歴がある。

→ 「既定を動かす」クラスは**自動 PR の対象から外す**。ループの成果物は PR ではなく**測定レポート**。

---

## 2. ゲート級 — 何をもって「終わった」とするか

ラベルに 1 軸追加する。既存の `priority:*` / `area:*` / `needs-decision` はそのまま。

| ラベル | 受け入れ条件 (Definition of Done) | 実行系 | 自動化の上限 |
|---|---|---|---|
| `gate:fast` | `ruff` + `pytest -m "not gsas"` + frontend が green、かつ §4 の証明 3 種 | クラウド or ローカル | **PR 作成まで**。マージは人間 |
| `gate:gsas` | 上記 + ローカルで該当 `-m gsas` サブセットが green | **ローカルのみ** | PR 作成まで |
| `gate:bench` | 上記 + T1/T2/T3/T4/CaTeO3 の**再測定表**が付く (既定を動かすため) | **ローカルのみ** | **PR を作らない**。測定レポートまで |
| `gate:human` | 人間の判断・外部への働きかけが本体 | — | **調査メモまで**。実行しない |

初期割り当て (トリアージ §2 からの写像。例示):

- `gate:fast` … #105 (`__all__` 未 re-export) / #127 (仕様残件) / #119 (skill 監査残件) / #125 (② 露出) /
  #200・#193 (② 直列化) / #159 (ベンチ表に n_params 列)
- `gate:gsas` … #188 / #162 / #189 / #199 / #191 / #192 / #194 / #195 / #196 / #197 / #160 / #163 / #164 /
  #165 / #166 / #167 / #168 / #17 / #33 / #13
- `gate:bench` … #169 / #198 / #190 / #173 / #175 / #178 / #179
- `gate:human` … #185 (再配布可否の確認) / #122 / #123 / #124 / #126 / #181 (`needs-decision`) /
  #136 (**upstream への報告 = 外部への発信**) / #10 (ネットワーク取得) / #23 (データ調達)

> **`gate:human` は「難しい」ではなく「機械にやらせてはいけない」の意味**。
> 特に #136 は第三者トラッカーへの投稿であり、ループから発信させない (§6)。

---

## 3. 状態機械 — 台帳は GitHub そのもの

新しいキューを作らない。**ラベル遷移が状態、Issue タイムラインが追記型台帳**
(P2 非破壊性・NFR-105 と同じ思想: 消さない・上書きしない)。

```
        (トリアージ済 = gate:* が付いている)
                     |
     loop:queued ────┼──> loop:in-progress ──> loop:review ──> [人間] merge → closed
                     |            |                  |
                     |            └── 失敗 x2 ──> loop:blocked (理由コメント付き)
                     └── 本文とコードが食い違う ──> loop:blocked (確認結果コメント)
```

- 1 Issue = 1 ブランチ `auto/issue-<N>`。**既に存在したら着手しない** (再入防止 = 冪等)。
- 各周回は Issue に**証跡コメント 1 件**を追記する (何を試し、何が通り、何を諦めたか)。
  ここが `ledger` に相当する。**沈黙して終わらない**。
- ループはラベルを**進める**だけで、`closed` にはしない。クローズはマージの副作用か人間。

---

## 4. 1 周回の段構成 — 「無言成功」を殺す

本リポジトリが Rietveld 側で何度も踏んだ欠陥クラスは
**「失敗しているのに完走して見える」**だった (GSAS の `Refine` 戻り値が捨てられていた件、
`tc.exe` が構文エラーでも終了コード 0 を返す件)。**同じ穴がループにも開く** —
「テストが green なので完了しました」と報告する空回りの周回である。段の設計はここを潰すことに費やす。

| 段 | やること | 止める条件 |
|---|---|---|
| **S0 受入** | ラベルから gate 級を読む。`gate:human` なら**着手しない** | ゲート未付与 → `loop:blocked` |
| **S1 実地確認** | Issue 本文の主張を **grep/read でコードに当てる** (トリアージ付録と同じ作法)。「既に直っている」「本文の指示だと壊れる」を先に検出 | **食い違い → 実装せずコメントして終了** (§1-b) |
| **S2 赤** | 失敗するテストを先に書く。**base commit で実行して落ちることを実測**し、出力を証跡に貼る | base で通ってしまう → その「テスト」は何も守っていない → 停止 |
| **S3 緑** | 最小実装 | — |
| **S4 変異証明** | ガード系テストは **src を逆向きに変異させて fail することを実証**してから受け入れる (CLAUDE.md の恒久規則)。実証後に変異を revert | 変異させても通る → **落ちないガードは無いより悪い** → 停止 |
| **S5 露出確認** | `src/tsumugin/**` に公開シンボルが増えたなら ②MCP と ③SKILL.md の差分があるか。`tests/test_layer_coverage.py` が機械強制するので**まず走らせる** | 露出宣言も非露出宣言も無い → 停止 |
| **S6 ゲート実行** | `gate:fast`: ruff + fast tier + frontend。`gate:gsas`: 加えて該当 `-m gsas` サブセット。`gate:bench`: 加えてベンチ再測定 | 落ちたら S3 へ戻る (**最大 2 回**) |
| **S7 自己レビュー** | `/code-review` を**新規指摘が出なくなるまで**回す (CLAUDE.md の既定運用)。見送る指摘は理由を書く | 3 周しても新規指摘が続く → 人間へ |
| **S8 提出** | PR を作り、Issue に証跡コメント。**マージしない** | — |

### 「無言成功」の 3 つの検出器 (必須)

1. **ゼロ差分検出** — 成功を報告したのに `git diff base..HEAD` が空、
   またはテストファイルしか動いていないのに「バグを直した」と言っている周回は**失敗として扱う**。
2. **red→green の実測** (S2) — 新テストが base で落ちることを**実行して**確かめる。
   「落ちるはず」は証拠ではない。
3. **変異証明** (S4) — ガードは変異させて落とす。

### ⚠ ローカル実行で必ず踏む 3 つの罠 (記録済み。ドライバに焼き込むこと)

- **worktree の editable install シャドウ** — editable install は **main の `src` を指す**。
  worktree でテストを回すと**別のソースを検証してしまう**。ワーカーは必ず
  `$env:PYTHONPATH="$PWD\src"` を設定する。**これを忘れると全周回が静かに無意味になる。**
- **パイプが終了コードを潰す** (PowerShell / bash 双方で実測、2 回踏んだ) —
  `pytest | tee log` は**成否を偽陰性化する**。素で実行し、終了コードを別途記録する。
- **`git add -A` 厳禁** — `scratchpad/` は gitignore だが**追跡済みの `.py` がある**。
  ワーカーは変更ファイルを明示列挙して add する。`docs/benchmark/` 配下には触れない
  (public repo の由来規約。`tests/test_docs_provenance.py` が fast tier で強制する)。

---

## 5. 実行系

### 5.1 ローカル (主) — `gate:gsas` / `gate:bench` はここでしか終われない

実装: **`tools/issue_loop.ps1`** (既定 dry-run)。周回の中身は **`.claude/skills/issue-work/SKILL.md`**。

```powershell
.\tools\issue_loop.ps1 -Gate fast -Max 4 -ListOnly   # 何が拾われるかを見るだけ
.\tools\issue_loop.ps1 -Gate fast                    # dry-run (S1 まで・GitHub へ書かない)
.\tools\issue_loop.ps1 -Gate gsas -Max 2 -Apply      # ローカルワーカーを worktree 隔離で起動
```

- **同時実行 2 まで** — `-m gsas` は実 GSAS 精密化で CPU を掴む。`tc.exe` は
  `OMP_NUM_THREADS=1` 固定 (再現性のため) なので並列は効くが、メモリと実データの I/O が競合する。
- 周回のトリガは `/loop` の自己ペース (数十分間隔) か Windows タスクスケジューラの夜間実行。
- `-ListOnly` で「何が拾われるか」だけを見る (ワーカーを起動しない)。

#### ⚠ ドライバ実装で実際に踏んだ 2 件 (どちらも「空/壊れを正常と答える」型)

1. **`ConvertFrom-Json "[]"` は空配列を「1 個のオブジェクト」としてパイプへ流す** —
   `$raw | ConvertFrom-Json | Where-Object {...}` と直接繋ぐと**空キューが 1 件の仕事に化け**、
   番号の無い Issue でワーカーを起動しかけた。いったん変数へ代入すると展開されて 0 件になる。
   対処は代入 + `number` を持つ要素だけ数えること。**②MCP の「空/不正入力を正常と答えない」と同じ規律**が
   ドライバにも要る。
2. **Windows PowerShell 5.1 は BOM の無い `.ps1` を cp932 として読む** — 日本語コメントを含む
   UTF-8 (BOM 無し) スクリプトは文字列終端が壊れてパースエラーになる。**UTF-8 BOM 付きで保存する**。
   (併せて、バッククォートの行継続は改行コードに依存して壊れるので**引数配列 + splat** を使う。)
- ワーカーは `--permission-mode acceptEdits`。**`bypassPermissions` は使わない**
  (ネットワークと共有ドライブが見える実機である)。

### 5.2 クラウド (従) — `gate:fast` のみ

```yaml
# 設計案: .github/workflows/claude-issue-loop.yml (未実装)
name: Claude Issue Loop (fast gate only)
on:
  schedule: [{ cron: "0 0 * * *" }]     # 09:00 JST
  workflow_dispatch:
jobs:
  work:
    runs-on: ubuntu-latest
    permissions: { contents: write, issues: write, pull-requests: write, id-token: write, actions: read }
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --all-extras --frozen       # extras 欠けは「本体の回帰」に誤読される
      - uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          prompt: "/issue-work --gate fast --pick-one"
          claude_args: |
            --max-turns 40
            --model claude-opus-5
```

注意点 (公式ドキュメント由来):

- `prompt` を渡すと **automation mode** = `@claude` 不要で走る。既定では結果が
  **workflow ログにしか出ない**ので、Issue/PR へ書くツールを `--allowedTools` で明示的に渡すこと。
- `schedule` は**既定ブランチからしか走らず**、public リポジトリでは
  **60 日無活動で自動停止**する。
- scheduled run の実行者は「cron を最後に触った人」に帰属する。bot 名義になると
  **bot actor チェックで弾かれる** (`allowed_bots` が必要)。
- fork PR には secret が渡らない (単独メンテなら実害なし)。

**クラウドに `gate:gsas` を渡さないこと。** runner に GSAS-II が無いので
「fast tier が green だから完了」と報告する周回になる = §4 の無言成功そのもの。

### 5.3 `@claude` 対話 (随時)

`gate:human` の Issue でも「調べてほしい」は成立する。`@claude` メンションの
interactive mode は残しておき、**着手ではなく調査**に使う。

---

## 6. 絶対にやらせないこと (ハード境界)

- **マージしない / `main` に push しない / Issue を close しない。**
- **第三者への発信をしない** — #136 の upstream 報告、COD/ICSD への取得 (#10) などは
  外向きの行為であり、ループの権限外。下書きまで。
- **`docs/benchmark/` 配下のデータを追加・変更しない** (public repo の由来規約)。
  測定結果は `*/results/` (gitignore) に置く。
- **未公開データ由来の数値を PR 本文・コメントに書かない。**
- **ラベルを剥がさない** — `loop:*` の遷移以外でラベルを消さない (トリアージの結論は人間の判断)。
- **同じ Issue に 3 回目の自動着手をしない** — 2 回失敗したら `loop:blocked`。
  「失敗が伝わらないまま回り続ける」のが最悪 (GSAS `Refine` の件と同型)。

---

## 7. 導入順序 (段階的に権限を開ける)

| 段 | 開けるもの | 撤退条件 |
|---|---|---|
| **0. dry-run** | Issue に**計画コメントを書くだけ**。PR も branch も作らない。`gate:fast` の 3–5 件で回す | 計画が S1 (実地確認) を素通りする / 既に直っている件に着手しようとする |
| **1. fast 自動 PR** | `gate:fast` で PR 作成まで。マージは人間 | S4 変異証明を省く周回が出る |
| **2. gsas ローカル** | `gate:gsas` をローカルワーカーへ。同時 2 | worktree の PYTHONPATH 罠を踏んだ形跡がある |
| **3. bench** | `gate:bench` は**測定レポートのみ** (PR を作らせない) | — |

最初に回す候補は **#105 / #127 / #119** (いずれも `gate:fast` かつ影響範囲が閉じている)。
**#188 + #162 は費用対効果が最大**だが `gate:gsas` なので段 2 まで待つ。

---

## 8. コスト

- `--max-turns` / `--max-budget-usd` をワーカー既定に入れる。
- クラウドは 1 日 1 件だけ拾う (`--pick-one`)。GitHub Actions 分も消費する。
- ローカルは `-m gsas` の実時間 (~50 分/フル) が支配的。**サブセット指定を必須**にし、
  フル実行は PR 直前の 1 回だけ。

---

## 9. 意図的に自動化しないもの (宣言)

- **トリアージそのもの** — 優先度の判断は人間 (2026-08-19 の実地確認がその実例)。
  ループは**トリアージ済の列**を消化するだけ。
- **仕様 (`docs/tsumugin_spec_v0.3.md`) の改版** — `needs-decision` 5 件は判断が本体。
- **ベンチ基準の改定** — T4 の基準改定は人間判断だった前例がある。

> 露出規約と同じ作法で、**「自動化しない」と決めたものは理由付きで宣言する** (黙って未対応にしない)。
