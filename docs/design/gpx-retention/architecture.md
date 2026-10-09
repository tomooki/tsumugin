# 精密化成果物の全保存 (NFR-108) — 設計

**決定日**: 2026-08-20 (ユーザー決定)
**要件**: `docs/tsumugin_spec_v0.3.md` NFR-108
**実装**: `tsumugin.gpxstore` (leaf) + 各エンジン/系列の配線

## 1. 何を決めたか

**実際に精密化バックエンドを起動した単位ごとに、成果物を 1 つ保存する。**

| 決定事項 | 値 | 理由 |
|---|---|---|
| 既定 | **保存する** (`save_gpx=True`) | 「保存しなかった精密化は検算できない」。以前は `keep_gpx` を明示した呼び出しだけが残り、系列解析は**1 つも**残さなかった |
| 置き場所 (既定) | **観測データ隣接** `<data_dir>/tsumugin_gpx/run-<日時>/` | 解析の産物がどのデータのものか自明になる。`workbench` の `<spec_dir>/workbench_out/` と同じ流儀 |
| 粒度 | **精密化 1 回 = 1 成果物** (段階スナップショットは残さない) | 754 フレーム × 8 段 = 数 GB になる。段の追跡が要るときだけの診断モードは M-later |
| 索引 | `manifest.jsonl` (追記専用) | 「全部保存」は「後から**探せる**」までが要件 |

**opt-out**: `save_gpx=False` (呼び出し単位) / `TSUMUGIN_GPX_DIR=none` (環境単位)。
**上書き**: 明示 `gpx_dir` > `TSUMUGIN_GPX_DIR` > データ隣接。**明示指定は `none` にも勝つ**
(頼まれた保存を環境変数で黙って捨てない)。
**明示パス** (`keep_gpx` / `keep_project`) は opt-out (`save_gpx=False` / `none`) **にも勝つ**
(2026-10-09 決定、順位の正本は `gpxstore.plan_output`)。opt-out が止めるのは**既定保存**
(置き場所を tsumugin が決める保存) であり、名指しされた保存ではない。明示パスは単独でも既定保存を
置き換えるので、併用は「そのパスにだけ残す」と一意に読める。`gpx_dir` は保存の依頼ではなく
既定保存の置き場所なので、`save_gpx=False` と併用すると使われない。
**N 回精密化する入口** (`run_recipe_search` / `run_multistart_rietveld` / `compare_models` と、
標準経路 `optimize_then_confirm`。`run_model_comparison` は `compare_models` 経由) は明示パスを
**何も回す前・ディスクに触る前に ValueError で拒み** `gpx_dir` を案内する (`gpxstore.reject_single_keep`)。
透過すると全候補が 1 パスへ上書きされ (マルチスタートは並列で競合)、候補ごとの成果物も残らない。
剥がして警告する手は「頼まれたパスに何も置かない」点で黙った無効化と変わらず、各回のパスを派生する手は
「このパス」を「この接頭辞」に読み替える (頼まれていない解釈) ので採らなかった。`None` / `""` は
`plan_output` と同じく「指定なし」として通す。

## 2. なぜ「棄却された fit」まで残すのか

本リポジトリで実際に踏んだ病理が、いずれも**最終 Rwp からは追えなかった**ため:

| 病理 | 数値に現れる姿 | 残っていないと切れないもの |
|---|---|---|
| 段の無言 no-op (GSAS `Refine` の失敗戻り値を握り潰す) | rwp/n_params がビット同一・`reverted` も立たない | 段ごとの状態 |
| 相追加トライアルの棄却 | 相分率 ~1e-12 | 「残差を説明できない相」か「セルがずれて説明**できなかった**相」か |
| M10 bic crossover | `total_bic` の 1 数字 | **採られなかった方向**の fit (相集合が違う経路の比較そのもの) |
| レシピ探索 / 収束確認 | 順位表の Rwp | 負けた候補・別ベイスンへ落ちた開始点がどんな解だったか |

さらに MEM (`mem_density` / `mem_rietveld_iterate`, FR-601/603) は**精密化済み成果物そのもの**を
入力に要求する。保存が既定になるまで、② の中に「その入力を産むツール」が存在しなかった
(§4.5 到達可能性の違反 — ③ から MEM を呼ぶ経路が閉じていなかった)。

## 3. 命名 (役割がファイル名に出る)

```
<data_dir>/tsumugin_gpx/run-20260820-134501/
  PbSO4.gpx                     # 単発 (データ名)
  f0000_frame.gpx               # 系列フレーム
  f0180_trial_delta-CaTeO3.gpx  # 相追加トライアル (棄却されたものも)
  f0032_consolidate_delta.gpx   # セル整合の再精密化
  f0031_backward_delta.gpx      # onset 逆伝播
  f0005_anchor.gpx              # M10 アンカー確定
  f0005_anchor_ab.gpx           # FR-318 制約有無 A/B の B
  f0007_forward_a0005.gpx       # M10 前方パス (どのアンカー起点か)
  f0007_backward_a0012.gpx      # M10 後方パス
  f0042_repair_L.gpx            # 不連続修復の試行
  f0002_multistart.gpx          # 収束確認の各開始点
  candidate_polish.gpx          # レシピ探索の各候補
  model_model6.gpx              # モデル比較の各バリアント
  f0003_iteration.gpx           # M8 閉ループの各反復
  manifest.jsonl                # 索引 (役割/番号/ラベル/データ/相/Rwp/GOF/backend)
```

**run ディレクトリの粒度**: 系列解析・探索・収束確認・モデル比較・不連続修復・M8 閉ループは
**1 実行 = 1 ディレクトリ**を共有する (フレームごとに分かれると 754 個できて探せない)。単発ツール
(`auto_rietveld` / `refine_with_revisions`) は**呼び出しごとに独立した run ディレクトリ**を作る。

## 4. 命名をどう運ぶか — ContextVar 側路

系列エンジンは `Runner` プロトコル `(frame, phases, initial_cells[, initial_fractions])` で
任意の runner を呼ぶ。ここへ「成果物の名前」を渡すために**第 5 引数を足すと素の 3 引数 runner が
黙って壊れる** (FR-318 で同じ罠を避けた経緯: per-frame の目標組成は `FrameSpec` に載せた)。

名前は**物理でない** (精密化の入力ではない) ので、入力仕様には載せず `gpxstore.gpx_context`
(ContextVar) で運ぶ。文脈を読まない runner は素通りするだけで壊れない。

```
run_sequential_rietveld
  └ gpx_context(series_ctx)                     # run ディレクトリを 1 つ決める
      ├ gpx_context(child(role="frame", index=i))   → runner → run_auto_rietveld が読む
      └ gpx_context(child(role="trial", index=i, label=候補相))
```

**例外はマルチスタート**: 開始点は別プロセスで走るので ambient は届かない。
`run_auto_rietveld(gpx_context=...)` に **frozen dataclass を明示的に渡す** (pickle 可)。
明示引数が ambient に優先する。

## 5. 失敗の扱い (規律)

| 失敗 | 振る舞い | 理由 |
|---|---|---|
| データ隣接に書けない (読み取り専用ディスク等) | **temp へ退避し理由を ledger** (`m7_gpx_fallback` = 単発・探索・マルチスタート・収束確認・M8 閉ループ / `m9_gpx_fallback` = 逐次・修復 / `m10_gpx_fallback` = アンカー双方向 / TOPAS 単発は `m12_project_fallback`)。ledger を持たない入口・**台帳が呼び出し側へ返らない入口**は**結果にも**載せる (モデル比較 `compare_models` → `ModelComparison.warnings` = ② `warnings`。台帳を受ける `run_model_comparison` はそれを `model_compare_warning` 行に写す。M8 閉ループ `run_refinement_loop` は台帳が任意なので `RefinementLoopResult.warnings` にも常に載せる。逐次/アンカー双方向は `SequentialRietveldResult.warnings` の先頭行。単発 `run_auto_rietveld` / `run_topas_rietveld` は `AutoRietveldResult.artifact_fallback_reason`)。結果に載せる形は全入口で `成果物の保存先: <理由>` の 1 行 (`gpxstore.fallback_warning` — ③ の手順書がこの形を名指しするので入口ごとに書き分けない) | 750 フレームの系列をこれだけで落とさない。かつ黙って保存を諦めない |
| 既定保存のコピーに失敗 | `gpx_path=""` + ledger `m7_gpx_error`、**精密化結果は返す** | 成果物は便宜であって結果ではない |
| **明示 `keep_gpx` の保存に失敗** | **例外のまま送出** | 握り潰すと呼び出し側が「保存しない設定」と区別できない |
| 索引 (`manifest.jsonl`) の書き込み失敗 | 黙って諦める (解析は続行) | 索引は便宜。真実は ledger と結果オブジェクト |

既存ファイルは**決して上書きしない** (P2)。run ディレクトリ名・成果物名とも `-2`, `-3` … で
衝突を避ける。

**退避理由は run ディレクトリを解決した入口でしか分からない**。`gpxstore.group_context` /
`series_context` は `(文脈, 退避理由)` を返し、エンジンは解決済みの文脈を受け取るだけなので
退避を記録しない。入口が理由を捨てると、成果物が %TEMP% に置かれたことはどこにも残らない —
実際に `group, _reason = group_context(...)` の形で捨てていた入口が 6 つ中 5 つあった
(探索 / マルチスタート / モデル比較 / 修復 / M8 閉ループ。系列だけが載せていた)。

- **単発ではエンジン自身が入口である**: 文脈 (ambient / 明示) を受けずに呼ばれた
  `run_auto_rietveld` / `run_topas_rietveld` は `plan_output` で自分の run ディレクトリを解決する
  ので、退避理由を知っているのはエンジンである。台帳 (`m7_gpx_fallback` / `m12_project_fallback`)
  に加えて `AutoRietveldResult.artifact_fallback_reason` に載せる — ② の単発 `auto_rietveld` /
  `refine_with_revisions` はエンジンの台帳を返さず (`run_auto_rietveld` が内部で作る私有の台帳)、
  TOPAS は台帳自体が任意なので、**結果に載せない限り ③ には %TEMP% を指すパスしか見えない**。
  載せるのは**退避先に保存できたとき**だけ (台帳の `*_fallback` 行と同じ条件。退避先にも
  書けなかったら `""` で、その失敗は `m7_gpx_error` / `m12_project_error` の担当)。他の入口が
  解決した文脈の下で回るエンジン (系列のフレーム・探索の候補…) は文脈の run ディレクトリを使うので
  理由は常に `""` — 退避の記録は解決した入口の 1 行だけで、結果ごとに繰り返さない。
- **捨てる既定を持たない**: `resolve_run_dir` は常に `(run_dir, 退避理由)` を返す (旧
  `report_fallback=False` 既定はパスだけを返して理由を捨てていたので撤去した)。
- **歯止め**: `tests/test_gpx_fallback_surfaced.py` が src の全呼び出しを AST で検査する (戻り値を
  その場で 2 名に分解し、理由名を `_` で始めず、分解の後・上書きの前に読む。理由を
  `return ctx, reason` のように転送するだけの形は `gpxstore` 自身の解決関数の中だけ)。網が止めるのは
  **うっかり捨てる形**までで、載せる先 (台帳の種別・`warnings`) の正しさは入口ごとの振る舞い
  テストが見る。
- **採らなかった案 — 理由を `GpxContext` に載せ、エンジンの `_save_gpx_artifact` に
  `m7_gpx_fallback` を書かせる**: (1) ファンアウト経路ではエンジンの台帳が**私有**である
  (探索の既定 runner・マルチスタートの子プロセス・モデル比較/修復/系列/閉ループの runner は
  どれも呼び出し側の台帳を渡さず、② の単発 `auto_rietveld` も台帳を返さない)。記録したように
  見えて誰も読まない台帳に落ちるので、無言の no-op を「構造化」するだけになる。
  (2) 属性にすると読み忘れが呼び出し側に痕跡を残さない (`_reason` すら書かれない) — 捨てた
  ことがかえって見えなくなる。(3) 入れ子の入口 (収束確認 ⊃ 探索/マルチスタート) がそれぞれ
  理由を持つ文脈を受けて記録し、「1 実行 = 退避の記録 1 行」が崩れる。

## 6. ①②③ の配線 (Issue #97 の規則)

| 層 | 到達手段 |
|---|---|
| ① | `run_auto_rietveld` / `run_topas_rietveld` / `run_sequential_rietveld` / `run_anchored_sequential` / `run_refinement_loop` / `run_recipe_search` / `run_multistart_rietveld` / `compare_models` / `repair_isolated` の `gpx_dir` / `save_gpx`。⚠ `run_refinement_loop` は **② から呼ばれない** (② の `refine_with_revisions` は改訂を適用した単発精密化で、ループを回すのは ③ 自身) ので、その退避理由 (`RefinementLoopResult.warnings` / 台帳の `m7_gpx_fallback`) は **① 専用 (非露出)** |
| ② | `auto_rietveld` / `refine_with_revisions` / `sequential_rietveld` / `anchored_sequential` / `compare_structure_models` / `repair_frames` の `gpx_dir` / `save_gpx` (**`auto_rietveld` の `search`/`multistart` 経路にも届く** — この 2 経路は既定 runner を通らないので ① へ明示的に運ぶ)。型は ② の入口で検査する: `save_gpx` の null は既定 (保存)・bool 以外と非文字列 `gpx_dir` は error dict (スキーマが緩いので `bool(None)` が opt-out に倒れる)。出力は `gpx_path` (単発) / `frames[].gpx_path` + `gpx_dir` (系列) / `project_path` (TOPAS) / `search.candidates[].gpx_path` + `convergence.multistart.starts[].gpx_path` (探索・収束確認の全候補/全開始点) / `scores[].gpx_path` (モデル比較の全バリアント = 棄却モデルも) / `repairs[].gpx_path` + `gpx_dir` + `ledger_entries` の `insitu_repair_rejected` 行の `gpx_path` (修復: 採用 / 試行の run ディレクトリ / 棄却)。退避理由 (`成果物の保存先: <理由>` 行) は単発 `auto_rietveld` / `refine_with_revisions` なら `warnings` (`AutoRietveldResult.artifact_fallback_reason` の写し; キーは常に在り、退避が無ければ空)、逐次 `sequential_rietveld` / アンカー `anchored_sequential` なら `warnings` (系列の先頭行)、探索/収束確認なら `search.warnings` / `convergence.warnings` (退避は run ディレクトリ単位なのでこちらに出る。③ が経路によらず同じキーを読めるよう、② が同じ行を最上位 `warnings` へ拾い上げる)、モデル比較なら `warnings`、修復なら `ledger_entries` の `m9_gpx_fallback`。精密化を回す ② は全部どこかで返す — 台帳を返さない ② が台帳だけに書くと、③ から見えるのは `gpx_path` が一時領域を指していることだけになる |
| ③ | `skills/analyze`「精密化成果物」節 / `skills/insitu` の成果物表 / `skills/operando-diagnose`「疑うときの一次資料」/ `skills/mem-model-fix` の入力の出所 / `skills/joint` / AGENT_PLAYBOOK 3 本 |

恒久ガード: `tests/test_plugin_gpx_retention.py` (手順書が規定とハンドル名を書いているか・
② に無い ① 専用引数 `keep_gpx` を宣伝していないか・**退避理由の行の形と在処のキーを退避の段落の
中で名指ししているか** [analyze / insitu / operando-diagnose / AGENT_PLAYBOOK 3 本]) /
`tests/test_layer_coverage.py`
(`gpxstore` パッケージ宣言 + `FrameRietveldResult.gpx_path` の露出宣言 + **`runner` 注入シームを
持つ = 精密化を回す ② ツールは全部 `gpx_dir` / `save_gpx` を受ける** — モデル比較と修復が ① では
保存しているのに ② から止められず置き場所も選べなかった穴の再発防止) /
`tests/test_gpx_fallback_surfaced.py` (退避理由を捨てる呼び出しを src 全体で止める — §5)。
退避理由が ② の戻り値まで届くことは入口ごとの振る舞いテストが見る (単発/改訂/逐次/アンカーは
`tests/mcp/test_gpx_exposure.py` の「退避理由」節 — 逐次/アンカーは ① の系列エンジンを本物のまま
回す。単発のエンジン側は `tests/autorietveld/test_gpx_default_gsas.py` [gated] と
`tests/topas/test_engine.py`。`AutoRietveldResult.artifact_fallback_reason` の ② キーは
`tests/test_layer_coverage.py` の宣言表が強制する)。

## 7. 容量

0.5-1.5 MB/フレーム (実測: 単相 0.5 MB / joint 3.4 MB)。754 フレーム系列で ~1 GB、
M10 双方向はフレームあたり 2 回以上精密化するのでその 2 倍前後。
既定の置き場所はデータ隣接なので、リポジトリ内に置いたデータで解析すると
作業ツリーに出る — `.gitignore` に `tsumugin_gpx/` を**ディレクトリごと**登録済み
(拡張子で切らない: v0.1 公開時に `*.gpx` だけ守って csv/log が漏れた経緯がある)。

## 8. 意図的にやらなかったこと

- **段階スナップショットの保存**: 754 フレーム × 8 段で数 GB〜十数 GB。無言 no-op の追跡には
  最強だが、既定にする費用対効果が合わない。必要なら診断モードとして opt-in で足す (M-later)。
- **成果物の自動削除/世代管理**: P2 非破壊性と衝突する。掃除はユーザーの判断
  (run ディレクトリが日時で並ぶので手で消せる)。
- **`backends.gsasii.GSASIIBackend.refine` (簡約モデルの多仮説探索・判別 FR-313) — 今回は対象外**:
  ⚠ **`autorietveld.backend_adapter.AutoRietveldBackend` (実構造の多仮説) とは別物**で、
  そちらは `run_auto_rietveld` を通るため**既定で保存される** (仮説ごとに 1 成果物。
  `RefinementResult` にパス欄が無いので戻り値からは辿れないが、run ディレクトリの
  `manifest.jsonl` の `phases` 列でどの仮説の fit かを識別できる)。対象外なのは
  簡約モデル側の `GSASIIBackend` だけである。
  この経路は `RefinementModel` (2θ/強度**配列**) を受け取り一時 gpx を組むため、
  (a) **隣接データファイルが存在しない**ので既定の置き場所が決まらず (CWD に落ちる)、
  (b) 返り値 `RefinementResult` に**成果物パスを載せるフィールドが無い** — 保存しても
  ③ から到達できない「黙って増えるファイル」になる。規定を満たすには `RefinementResult`
  へのハンドル追加と `evidence`/`selection`/② 仮説ツール群への波及が要るため、別作業とする。
  **判別 (`discriminate`) は本来この規定の対象**である (採られなかった仮説の fit こそ
  Δevidence の根拠) ので、負債として明示しておく。
- **索引を読む ② ツール (`list_artifacts` 等) — 意図的に非露出**: 索引の中身は
  **その実行の返り値から既に到達できる** (`gpx_path` / `frames[].gpx_path` / `gpx_dir`) ので、
  同じ情報に 2 つ目の経路を作らない。過去の実行の索引を読みたい場合、`manifest.jsonl` は
  プレーンな JSON Lines であり ③ (Claude Code) は自分のファイル読み取りで開ける。
  **MCP しか持たないクライアントから過去実行を掘る要求が実際に出たら**そのとき足す
  (先に作ると「どの ② 出力から `gpx_dir` が来るのか」を言えない引数になり §4.5 に反する)。
