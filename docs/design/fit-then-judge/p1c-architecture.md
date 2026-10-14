# fit-then-judge P1c — 設計 (出版状態を GUI と MEM 系ツールへ)

- **状態**: 実装中 (branch `milestone/fit-then-judge-1c`)
- **上位**: [proposal.md](proposal.md) v5 §3.6・§6 の P1c (「GUI の承認カード・MEM 系ツールの sidecar 検査」)。
  1A の要件は [`requirements.md`](../../spec/fit-then-judge/requirements.md)、作業計画は
  [`docs/tasks/fit-then-judge/p1c.md`](../../tasks/fit-then-judge/p1c.md)

## 0. 調べて分かったこと (2026-10-14)

- **ワークベンチの精密化は出版状態を一度も作っていない**。GUI の精密化 (`WorkbenchSession.request_refine`) は
  ② の `auto_rietveld` を通らず、engine の `run_auto_rietveld` を直接呼ぶ (`workbench/jobs.build_default_runner`)。
  そのため `claims`・`judgment_requests`・`publishable_values` も sidecar も作られず、GUI の数値はすべて平文の値だった
  (1A が ③ に禁じた「平文のフィールドから数値を拾う」を GUI 自身がしている)。
- **MEM 系ツールは入力 gpx の出版状態を見ていない**。`mem_density` と `mem_rietveld_iterate` は gpx の存在だけを確かめる。
  MEM は精密化済みの構造 (Fcalc) を前提に密度を読むので、構造値が止められた fit からの密度は「決まっていない構造の上の診断」になる。
- **MEM-Rietveld 反復 (`mem.mpf`) は子 gpx を書くが sidecar を書かない**。子 gpx の出版状態は読み手の規則
  (sidecar が無ければ状態不明 = 出版不可) で「不明」になる。
- GUI の MEM は `mem_density` を直接呼ぶので、MEM 側で sidecar の無い gpx を**拒否**すると GUI の MEM が全部止まる。

## 1. 決めたこと

| 項目 | 決定 | 理由 |
|---|---|---|
| 出版状態の計算と記録 | **1 つの関数** `claims.publication.publication_state(result, phases, …)` にまとめ、② (`_attach_claims`) とワークベンチの両方が使う | 2 箇所で別に組むと規則が食い違う (1A の写像・判断要求・sidecar の書き方を GUI だけ外さない) |
| MEM 系ツール | 入力 gpx の sidecar を読み、結果に **`input_publication`** を足す。**拒否はしない** | MEM は診断であって出版ではない。拒否すると sidecar の無い gpx (旧結果・GUI・mpf の子) から MEM が使えなくなる。代わりに「入力の構造が出版できる状態か」を結果に必ず載せ、③ の手順書で読み方を縛る |
| mpf の子 gpx | sidecar を**書かない** (状態不明のまま)。結果の `input_publication` で入力の状態を、子は `unknown` と明記 | 子の fit は `AutoRietveldResult` を持たない (mpf は gpx を直接回し直す) ので写像の材料が無い。黙って出版可にしない |
| GUI | FIT タブに **PUBLICATION** カード (出版状態の表) と **判断要求のカード** を出す。**読み取りのみ** | 判断要求を閉じられるのは「データの証人」と「決定 2 の承認済み回答」だけ (proposal §3.5)。決定 2 は設計段階なので、回答の受け口を作ると D の止めを人が外せる経路が先にできてしまう |
| 判断要求のカードの語彙 | 既存の承認カード (二択 approve/reject) とは**別の種類**にする | 判断要求は N 択 (`candidates`)・既定回答 D (`hold`) を持つ。二択の承認カードに写すと語彙が合わない (review-response §4.3)。回答ボタンは出さず、候補と既定回答を表示する |

## 2. `claims.publication`

```
publication_state(result, phases, *, gpx_path, multistart=None, derivation=None, probe=None) -> dict
```

戻り値は ② が今足しているキーと同じ: `claims_version`・`claims`・`judgment_requests`・`publishable_values`・
`claims_policy`・`claims_sidecar`・`claims_sidecar_reason`・(失敗時) `claims_error`。**例外にしない** (組み立てに失敗したら
`claims: None`・`publishable_values: {}` = 何も出版できない側)。② の `_attach_claims` はこれを呼んで payload に足すだけにする
(出力はビット同一 — 既存テストで縛る)。

`input_publication(gpx_path) -> dict` (MEM 用、読むだけ):

| キー | 中身 |
|---|---|
| `state` | `"known"` (gpx の内容と一致する sidecar がある) / `"unknown"` (無い・壊れている・一致しない) |
| `sidecar` | 読んだ sidecar のパス (`unknown` なら `""`) |
| `n_values` / `n_publishable` | 値の数と出版可の数 (`unknown` なら `null`) |
| `structure_held` | 出版不可の構造値 (座標・Uiso・占有率) のキー (`unknown` なら `null`) |
| `blocking_requests` | blocking な判断要求の `id`・`kind` (`unknown` なら `null`) |

## 3. ワークベンチ

- `_on_refine_success` で `publication_state` を呼ぶ (ロックの外 — 重い計算)。結果を `self._publication` に保持し、
  viewmodel に **`publication`** キーで出す (project モードで精密化した後だけ。それ以外はキーを省略 = 空表示)。
- `publication` の形 (`api-contract.md` に追記):

```
{ "claims_version": str, "policy": str, "n_values": int, "n_publishable": int,
  "rows": [{key, param_class, phase, label, axis, value, esd, unit, scope, determinacy, publishable, gate: [id]}],
  "judgment_requests": [{id, kind, blocking, n_blocked, trigger, candidates: [str], default_answer: str|null}],
  "sidecar": str, "sidecar_reason": str, "error": str|null }
```

- 語彙 (`api-contract.md` §語彙に追記): `determinacy` と `scope` と判断要求の `kind`。フロントは未知の値で落ちず生の文字列を出す
  (既存の規則)。
- ledger: `refine_finished` に `n_publishable`・`n_values` を足さない (ledger のハッシュ鎖の形を変えない)。代わりに
  `publication_assessed` を 1 件追記する。

## 4. MEM 系ツールと ③

- `mem_density` / `mem_rietveld_iterate` の結果に `input_publication` を足す (既存キーは不変)。
- `skills/mem-model-fix` と該当 PLAYBOOK: 「`input_publication.state` が `unknown`、または `structure_held` が空でないなら、
  MEM の結果は**決まっていない構造の上の診断**として扱い、密度から出した構造の結論を出版値として報告しない」。手順書ガードで縛る。

## 5. 範囲外

- 判断要求への回答 (決定 2)・承認カードからの止めの解除。
- ワークベンチの探索・収束確認・テンプレート (GUI は単発の精密化だけ — 既存どおり)。
- mpf の子 gpx の出版状態の計算 (`AutoRietveldResult` を持たないため)。
