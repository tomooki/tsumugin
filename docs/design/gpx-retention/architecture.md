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

**run ディレクトリの粒度**: 系列解析・探索・収束確認・モデル比較・M8 閉ループは **1 実行 = 1
ディレクトリ**を共有する (フレームごとに分かれると 754 個できて探せない)。単発ツール
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
| データ隣接に書けない (読み取り専用ディスク等) | **temp へ退避し理由を ledger** (`m9_gpx_fallback` / `m7_gpx_fallback`) | 750 フレームの系列をこれだけで落とさない。かつ黙って保存を諦めない |
| 既定保存のコピーに失敗 | `gpx_path=""` + ledger `m7_gpx_error`、**精密化結果は返す** | 成果物は便宜であって結果ではない |
| **明示 `keep_gpx` の保存に失敗** | **例外のまま送出** | 握り潰すと呼び出し側が「保存しない設定」と区別できない |
| 索引 (`manifest.jsonl`) の書き込み失敗 | 黙って諦める (解析は続行) | 索引は便宜。真実は ledger と結果オブジェクト |

既存ファイルは**決して上書きしない** (P2)。run ディレクトリ名・成果物名とも `-2`, `-3` … で
衝突を避ける。

## 6. ①②③ の配線 (Issue #97 の規則)

| 層 | 到達手段 |
|---|---|
| ① | `run_auto_rietveld` / `run_topas_rietveld` / `run_sequential_rietveld` / `run_anchored_sequential` / `run_refinement_loop` / `run_recipe_search` / `run_multistart_rietveld` / `compare_models` の `gpx_dir` / `save_gpx` |
| ② | `auto_rietveld` / `refine_with_revisions` / `sequential_rietveld` / `anchored_sequential` の `gpx_dir` / `save_gpx`。出力は `gpx_path` (単発) / `frames[].gpx_path` + `gpx_dir` (系列) / `project_path` (TOPAS) |
| ③ | `skills/analyze`「精密化成果物」節 / `skills/insitu` の成果物表 / `skills/operando-diagnose`「疑うときの一次資料」/ `skills/mem-model-fix` の入力の出所 / `skills/joint` / AGENT_PLAYBOOK 3 本 |

恒久ガード: `tests/test_plugin_gpx_retention.py` (手順書が規定とハンドル名を書いているか・
② に無い ① 専用引数 `keep_gpx` を宣伝していないか) / `tests/test_layer_coverage.py`
(`gpxstore` パッケージ宣言 + `FrameRietveldResult.gpx_path` の露出宣言)。

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
