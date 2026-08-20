---
name: analyze
description: 粉末回折 (X線/中性子) の全自動 Rietveld 解析を閉ループで進める。MCP 4 ツール (propose_data_preprocessing でデータレンジ/背景項数/除外領域候補を測って決めてから auto_rietveld / propose_next_actions / refine_with_revisions) を反復駆動し、SafeAction (背景/母数解放) は自律適用、ModelAction (データリミット/相追加削除/構造改訂/混合占有) は判断してユーザー承認を挟む。Rwp/GOF と物理妥当性でチュートリアル同等を目指す。
---

# tsumugin: Agentic Rietveld 解析 (③ 判断層)

あなた (Claude) が**判断者 ③** として、tsumugin の MCP 3 ツールを反復駆動し、フィット結果を
観測して次手を決め再実行する閉ループ解析を行う。ライブラリは決定論コア (①) と薄い MCP (②) を
提供し、**開放的判断 (R3) と構造改訂・事前知識 (R5) はあなたが担う**。

設計: `docs/design/m8-agentic-loop/architecture.md` / 手順詳細: M7 `AGENT_PLAYBOOK.md` §8。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `auto_rietveld` | 計器 (実行) | histograms/phases spec (JSON) → 段階別/最終 Rwp・格子・validity・**spec ハンドル**。任意で `stages` (追加段階, 下記) / `max_cyc` / **`search` (レシピ探索, 下記)** / **`multistart` (収束確認, 下記)** |
| `propose_data_preprocessing` | 計器 (提案) | 観測ファイルパス → **データレンジ / 背景項数 / 除外領域候補** (下記「精密化する前に」) |
| `propose_next_actions` | 計器 (診断) | 直前結果 + 残差シグネチャ → `ActionProposal[]` (rationale/priority/**safe**) |
| `refine_with_revisions` | アクチュエータ | spec + あなたが決めた `AnalysisAction[]` → 改訂適用して再実行。`stages`/`max_cyc`/`backend` も同様に渡せる |
| `list_refinement_backends` | 計器 (可用性) | (引数なし) → 各精密化エンジンの `available` と解決パス。`backend` を渡す**前に**呼ぶ |

閉ループ丸ごと (agentic_analyze) は MCP に**無い**。回すのはあなた。

## 精密化成果物 (.gpx) は**既定で全部保存される** (2026-08-20 規定)

**何もしなくても保存される。** `auto_rietveld` / `refine_with_revisions` を呼ぶたびに、
その精密化の `.gpx` が 1 つ残る (改訂を 5 回回せば 5 つ)。

- **どこに**: 既定は**観測データ隣接** `<data_dir>/tsumugin_gpx/run-<日時>/`。
  `gpx_dir="..."` で**根**を指定できる (環境変数 `TSUMUGIN_GPX_DIR` より強い)。
  ⚠ 単発ツールは**呼び出しごとに独立した `run-<日時>/`** を作る (同じ `gpx_dir` を渡し続けると
  改訂の履歴が同じ根の下に時刻順で並ぶ)。1 つの run ディレクトリにまとまるのは
  系列解析 (`sequential_rietveld` / `anchored_sequential`) と、その中の探索/収束確認である。
- **どこを見る**: 返り値の **`gpx_path`** (TOPAS は `project_path`)。run ディレクトリの
  `manifest.jsonl` が「役割・相・Rwp」の索引 (1 行 1 成果物)。
- **何に使う**: **MEM 系ツール (`mem_density` / `mem_rietveld_iterate`) の入力はこれ**。
  以前は ② から精密化済み gpx を作る経路が無く、`mem-model-fix` skill は呼び出せなかった。
- **止めたいとき**: `save_gpx=false`。⚠ **既定で止めない** — 保存しなかった精密化は
  検算できない (段の無言 no-op も、後からの再プロットも、MEM も、fit そのものを要求する)。

**報告するときは `gpx_path` を添える** — 数字だけ渡されても人間は確認できない。

## どの精密化エンジンで回すか (`backend`)

既定は **`"gsasii"`** (GSAS-II)。M12 から **`"topas"`** (Bruker TOPAS) も選べる。

**手順**: `list_refinement_backends` → 目的のエンジンの `available` が `true` であることを確認 →
`auto_rietveld(..., backend="topas")`。返り値の `backend` キーで**実際にどちらで回ったか**を検算する。
`backend` を取るのは `auto_rietveld` / `refine_with_revisions` / **`discriminate`** の 3 つで、
operando 経路 (`sequential_rietveld` / `anchored_sequential`) は GSAS-II 固定である。

**TOPAS を選ぶのはこういうとき**:

- GSAS-II で異方的な線幅・微細構造が乗り切らず、TOPAS 固有のモデルが要る。
- **バックエンド間の独立確認を取りたい** — 同じデータと同じ構造から 2 つの独立実装が同じ格子・
  同じ相分率に落ちれば、大域最適の強い傍証になる (`multistart` の初期値摂動より強い。実装の
  バグまで含めて独立だから)。**食い違ったらどちらかが間違っている**ので、Rwp が低い方を
  黙って採らずに原因を追うこと。

**してはならないこと**:

- ⛔ **仮説やフレームを跨いで `backend` を切り替える**。Rwp/BIC の比較が成り立たなくなる。
  比較するなら全部を同じエンジンで回し直す。

**判別 (`discriminate`) を TOPAS で回すとき**: 固溶体 vs 二相の判別は Δevidence (BIC 差) の
比較なので、**区間の中でエンジンを混ぜてはならない**。使いどころは「GSAS で出た判定が
エンジン依存でないことを確かめる」— 区間全体を `backend="topas"` でもう一度通し、`verdict` が
一致するかを見る。**食い違ったらどちらかが間違っている**ので、Δevidence が大きい方を黙って
採らずに原因を追うこと。各相の `structure_ref` (実 CIF) は両エンジンとも同じものを読む
(TOPAS 側も実構造で判別する。簡約モデルでの代替はしない)。
- ⛔ `available` を確認せずに `backend` を渡す。未導入なら `{"error","error_type"}` が返る。
- ⛔ 綴りを推測して渡す。未知の名前は**既定へ落とさずエラーになる** (意図と違うエンジンで
  回った結果に気づけなくなるのを防ぐため)。

**TOPAS 経路の制約** (知らないと詰まる):

- `.gpx` が存在しないので **MEM 系ツール (`mem_density` 等) は使えない**。結果の `gpx_path` は
  空文字になり、`project_path` に INP/.out が残る。
- 段階フラグは**全て翻訳できる**が、条件が合わない指定は**明示的に失敗して revert される**
  (黙って無視されない)。段の `note` に `UnsupportedStageFlagError` が出る。
  - `hydrostatic_strain` は **joint (複数ヒストグラム) 専用**。単一ヒストグラムでは格子
    そのものと縮退するので失敗する。**ヒストグラムごとに測定温度が違うとき**
    (`histograms[].temperature` を入れたとき) は既定レシピが自動で 1 段入れる — 格子は
    共有したまま xdd ごとの実効セルを許す量なので、温度差があるのに入れないと**両方の
    ヒストグラムが同じくらい悪くなる**。**張った ε は結果の `cell_strain`**
    (相名 → `"<軸>_h<索引>"` → 値) に出る — `refined_cells` は構造としての 1 本のセルなので
    そこからは読めない。ε が箱 (±2%) に張り付いていたら物理的に怪しい (温度差 285 K でも
    0.3% 程度) ので、段が「効いた」ことと合わせて必ず値を見ること。
  - `absorption` は**反射光学系 (Bragg-Brentano) では失敗する** — 円筒吸収の式を平板試料に
    当てないため。透過/Debye-Scherrer で使うこと。
  - `size_strain` は **TOF ヒストグラムには張らない** (角度分散のモデルなので TOF には
    対応物が無い)。混在 joint では非 TOF にだけ張り、全 TOF なら失敗する。TOF の粒径/
    微小歪みは `tof_profile` (幅の d/d² 項) が担う。
- **`phase_fraction_sum` は未対応** — GSAS には要るが **TOPAS には概念が無い**。相ごとの
  `scale` が相分率そのもので、`MVW` が重量分率を正規化して返すため和=1 の拘束が存在しない。
  相分率を動かしたいなら `scale` を解放する (既定レシピは S0 で解放済み)。指定すると
  段が明示的に失敗する。
- `preferred_orientation` (球面調和) と `absorption` は**既定レシピに入っていない** opt-in 段。
  残差にまだ系統的なピーク強度ズレが残るときだけ `stages` に足す。
- **`seed_profile`** (TOPAS 専用の引数): TOPAS は装置ファイルのプロファイル (Caglioti U,V,W)
  を読まず汎用初期値から始まる。**放射光では桁で効く** (実測 11BM 43.9% → 8.7%) 一方、
  **CW 中性子では悪化する** (garnet 5.54 → 9.76% で物理妥当性も落ちる) ので既定 OFF。
  X 線/放射光で Rwp が「ピーク形状が合っていない」形で頭打ちなら `seed_profile: true` を試す。
  `backend="gsasii"` に渡すとエラーになる (GSAS は装置ファイルをそのまま読むので概念が無い)。
  ⚠ **`specs` ハンドルには載らない**。`refine_with_revisions` へ改訂を回すときは
  **そちらにも同じ値を渡すこと** — 渡し忘れると種付けなしのフィットになり、Rwp の変化が
  改訂の効果に見えてしまう。
- **TOPAS は既定で 1 スレッドで走る** (`list_refinement_backends` の `topas.threads`)。
  tc.exe はスレッド数で結果が変わる — 同一入力の T4 が 43.49 / 67.62 / 29.29% に散らばった
  実測があり、**Rwp が実行ごとに変わると段の受理判定も BIC 比較も意味を失う**ため再現性を
  取っている。環境変数 `TSUMUGIN_TOPAS_THREADS` で増やせるが、それは**再現性を捨てる選択**
  である (③ からは設定できない — ユーザー環境の話)。
- **背景項数は多ければ良いのではない**: 11BM (放射光) は 6 項では背景を表せず 20 項で総合
  43.5% → 26.3% になるが、24 項にすると X 線 Lorentzian 段が revert されて 67% へ跳ねる。
  `background_coeffs` を増やしたら**段列の `reverted` を必ず見る** (総合 Rwp だけを見ていると
  「増やしたら悪くなった」の理由が分からない)。

## joint (複数ヒストグラム) を読むとき

`final_rwp` は**全ヒストグラム込みの総合値**で、内訳は結果の **`histogram_rwp`** (入力の
`histograms` と同じ索引順) にある。

- **総合値だけを見ない**。放射源ごとに当てはまりが大きく違うのが普通で、総合値が下がっていても
  片方が悪化していることがある。次に何を触るかは内訳を見ないと決められない。
- 内訳が大きく偏っているとき (例: X 線 8% に対し中性子 14%) は、悪い方の**装置モデル**を疑う。
  相分率や座標をいじる前に、その放射源の波長・ゼロ点・ピーク幅・光学系補正を確認する。
- `histogram_rwp` が**空**なら内訳が取れていない (バックエンドが出していない)。総合値だけで
  判断せざるを得ないことを明示して報告する。

## 手順

0. **前処理を測って決める** (`propose_data_preprocessing`, 下記「精密化する前に」)。
   手で決めた背景項数/データリミットは次のデータで壊れる。
1. **入力を組み立てる** (AGENT_PLAYBOOK §1): データ/装置ファイルから `Radiation`・`Geometry`・
   `data_format` を判定し `HistogramSpec`/`PhaseSpec` の JSON を作る。CIF が無い相は
   `identify_phases` (元素一覧 → 単相ランキング) で候補構造を得る。
   - **装置ファイル (`instrument_path`) が無い / 正しいか分からないときは `instrument` skill**。
     `create_instrument_params` で作り (観測データ・プリセット・波長のいずれからでも)、
     **`inspect_instrument_params` で精密化前に検査する** — 放射源の取り違えと Kα2 の不整合は
     Rwp を見ても原因に辿り着けない類の誤りで、後段の全段階を壊す。
   - **相数が事前に分からない未知試料**は `identify_pattern` (M11 統一同定) を使う。1 相受理する
     ごとに残差からその寄与を減算し、**残差 S/N < 5σ になるまで**積み上げる (単相なら 1 相で停止、
     多相なら複数相)。`accepted[]` の各相の CIF/formula を `PhaseSpec` に配線して精密化へ進む
     (提案のみ・採否は ③)。外部形式の生データは手順 0 で `convert_pattern` して渡す。
2. **`auto_rietveld` を呼ぶ**。返る `specs` ハンドルを保持する。
3. **結果を読む**: `final_rwp`/`final_gof`、`validity.passed` と項目別 `checks`、`stages[*].reverted`。
   目標に届いていれば **3′ の収束確認へ進む** (Rwp が良いことは収束したことではない)。
3′. **収束を確認する** (`multistart`, 下記「収束を確認する」)。**手順を決めたあとに**、初期値を
   振って同じ解へ戻るかを見る。`convergence.structure_is_corroborated` が true なら解を採用してよい。
   割れたクラスの値 (`undetermined_by_initial_values`) は**報告するが出版しない**。
4. **`propose_next_actions` を呼ぶ** (残差シグネチャは結果と観測から見積もる)。各提案の `safe` を見る。
5. **次手を判断する** (権限境界):
   - **`safe=True` (SafeAction)** — 背景増項 `AdjustBackground` / 母数追加解放 `ReleaseParams` は
     採用してよい。適用後 Rwp が改善せず・validity を壊すなら**戻す** (過剰適合ガード)。
   - **`safe=False` (ModelAction)** — 下表の判断を要する手。**あなたが結晶学・化学の文脈で決め**、
     **構造改訂 (`ReviseStructure`)・相追加 (`AddPhase`) は必ずユーザー承認を挟む**。
6. **`refine_with_revisions`** に採った Action を渡して再実行。`specs` を持ち回り 3 へ戻る。
7. 目標 Rwp 到達 / 改善停滞 / 反復上限で終了し、最良結果と申し送り (未適用 ModelAction) を
   報告する。**最良結果の `gpx_path` を必ず添える** (上記「精密化成果物」) — 反復の各回が
   1 つずつ保存されているので、採用した fit がどれかを名指ししないと人間は開けない。

## 権限境界 (architecture.md §4.5 — 厳守)

| 判断 | 自律してよい | ユーザー承認を挟む |
|---|---|---|
| 背景増項・母数追加解放・停止 | ✅ | — |
| 保守的初期リミット (setup) | ✅ (提案を採用) | 大きく切るなら確認 |
| データリミット精密化 | — | 🟡 切り位置を提示して確認 |
| 相の追加/削除・混合占有割当 | — | ✅ 候補と根拠を示し承認 |
| 構造改訂 (空間群/原子/原点)・事前知識 | — | ✅ 変更内容を示し承認 |

**なぜ**: 残差からは原因が一意に決まらない (同じ残差が複数原因と両立)。パラメトリックで
自己検証可能な手だけ自律し、構造・相・事前知識に踏み込む手は人間の承認下で行う。

## 受理基準

各改訂は **Rwp 改善 ∧ `validity.passed` 維持** を満たすときのみ採用する。**最終解の採用は
それに加えて収束確認** (`multistart` の `convergence.structure_is_corroborated`) を見る —
Rwp と validity は単発の性質しか見ておらず、**同じ手順が別の初期値から別の答えを出すことを
検出できない** (実測: T1 は validity pass のまま結晶子サイズ 1 nm へ潰れた開始点がある)。Rwp が下がっても
Uiso<0・占有率逸脱・格子逸脱を生む手は過剰適合として棄却する。データリミット変更は観測集合が
変わり Rwp 比較不能なので、別に妥当性で評価する。

## 失敗時 (AGENT_PLAYBOOK §6)

Rwp 停滞→構造/空間群を確認 (ReviseStructure 候補)、占有率発散→混合占有制約 (SetMixedOccupancy)、
座標段階でセル発散→特殊位置の座標解放を避ける、TOF/放射光の高止まり→データリミット、
未指数ピーク→相追加 (AddPhase, 相同定へ)。いずれも ModelAction はユーザー承認を挟む。

## 精密化する前に — データレンジ/背景項数/除外領域を**測って決める** (`propose_data_preprocessing`)

**手で決めた前処理は次のデータで壊れる。** 実測された 2 件:

- CaTeO3 の **背景 24 項**は人が決めた定数だった。データが変われば適正項数も変わる。
- **T4 (NAC+CaF2) の非収束の主因は「データリミット未設定」だった** — 高角のノイズ支配域が
  点数で最小二乗を支配し、フィットを平坦化させていた。`two_theta_limits` を入れて解消した。

```json
{"path": "data/t4.fxye", "data_format": "FXYE",
 "phases": [{"structure_path": "nac.cif", "phase_name": "NAC"}], "wavelength": 0.4137}
```

| いつ使うか | 読むキー | 貼り先 |
|---|---|---|
| **精密化を始める前** (既定の一手にしてよい) | `two_theta_range.two_theta_limits` | `HistogramSpec.two_theta_limits` / `FrameSpec` 同名 |
| Rwp が高止まりし残差が背景のうねりに見える | `background_terms.recommended` / `candidates` | `auto_rietveld(background_coeffs=)` |
| 相で説明できない**鋭い孤立**ピークがある (検出器スパイク/宇宙線/試料ホルダ) | `excluded_region_candidates.candidates[]` | `HistogramSpec.excluded_regions` (**承認を得てから**) |
| 背景係数が `undetermined_parameters` に載った | `background_terms` | 項数が多すぎないか検算する |

**⛔ 除外領域は勝手に適用しない。** `requires_human_approval` は常に true。除外は解析の解釈を
変える操作であり、**未知相のピークをアーチファクトとして消せば相同定を殺す**。候補は
ユーザーに提示して承認を得ること。**通常幅の未説明ピークは除外候補ではなく「相が足りない」証拠**
であり、そちらは `identify_pattern` / `residual_report` の担当である。

- **`phases` を渡すこと。** 渡さないと「どの相でも説明できない」の判定ができず偽陽性が増える
  (`note` に警告が出る)。`auto_rietveld` に渡した `phases` と、結果の `refined_cells` を
  `refined_cell` として貼れる。
- **放射光/中性子では `wavelength` を必ず渡す。** 判らないなら `null` — 推測させない
  (誤波長の反射位置で「説明済み」判定が丸ごと誤る)。何を使ったかは `explained_source`
  (`phases`/`explicit`/`none`/`unavailable`/`wavelength_unknown`) で確認する。
- **承認済みの除外区間は `excluded_regions` 引数で戻す。** 上限判定から外れる (寄生ピークを
  混ぜると上限がそこまで押し出される)。ツールは自分の提案候補を自分のレンジ判定へ流し込まない。
- `assess_data_quality` (背景減算検出 + 上限 1 値) とは契約が違う。**下限/上限の組**が要るとき、
  esd を noise 推定に使いたいとき、切り詰めすぎのガードが要るときは本ツールを使う。

**レンジを変えたら Rwp は前の値と比較できない** (観測集合が変わる)。`search` の候補比較でも
同じ規則が効いている (下記「選択規則」3)。

## 精密化段階を追加する (`stages` / `max_cyc`)

`auto_rietveld`/`refine_with_revisions` は既定の 7 段階レシピ (`build_recipe`) の末尾に**追加段階**を
足せる (`stages` 引数, Issue #101)。既定レシピが試さない knob は ③ が明示的に足す必要がある:

```json
{"stages": [{"label": "S9 absorption", "flags": {"absorption": true}, "note": "弱吸収試料"}]}
```

| どの knob がいつ効くか | `flags` |
|---|---|
| X 線 (実験室/放射光) の残差が高止まり (CaTeO3 型: U,V,W だけでは形状に合わない) | `{"profile_lorentzian": true}` |
| TOF 中性子/放射光の残差が高止まり (XND T4 型) | `{"tof_profile": true}` |
| 選択配向が疑われる系統的 obs>calc | `{"preferred_orientation": 4}` (SH order) |
| 試料吸収が強い (透過配置の弱吸収試料) | `{"absorption": true}` |
| サイズ/微小歪みの型を変える (異方) | `{"size_strain": "uniaxial"}` / `"generalized"` (X 線限定) |

**追加段階も revert ガードが効く** — 悪化すれば当該段階だけ棄却され、他段階には影響しない
(既定レシピと同じ安全網)。まず 1 段だけ足して試し、`stages[*].reverted` で効いたか確認する。

`stages` は `auto_rietveld` が返す `specs` ハンドルにも同梱される (`specs["stages"]`) ので、
`refine_with_revisions` を反復するときは持ち回ること (省略すると追加段階が消える)。

`max_cyc` (既定 12) は各段階の最大精密化サイクル数。収束が遅い/振動する系で増やす。

## どのレシピで回すかを**測って決める** (`search`)

**単一のレシピは全データで勝てない。** 実測 Rwp (10 案 × 4 データ, 2026-07-30。既定集合の
固定候補のみ抜粋。全表は `docs/benchmark/stable-baseline-recipe/FINDINGS.md`):

| データ | `default` | `sizestrain_last` | `polish` | `serious1` | 採用 | チュートリアル |
|---|---|---|---|---|---|---|
| T1 fluoroapatite | 9.81 | 9.73 | 9.67 | 10.60 | `polish` | 10.38 |
| T2 garnet | 4.33 | 4.33 | 4.33 | 4.32 | `serious1` | 5.18 |
| T3 PbSO4 joint | 6.66 | 5.98 | 6.66 | 6.18 | `sizestrain_last` | 6.71 |
| CaTeO3 | 12.20 | 12.20 | 12.20 | 12.19 | `polish` | 9.40 |

**採用手順はデータ毎に違う。** ⚠ 採用は **Rwp 単独では決まらない** — 下の「選択規則」のとおり
収束 → 妥当性 → Rwp の階層で、同点近傍 (0.1 ポイント以内) は BIC が裁定する。CaTeO3 が
その例で、Rwp 最小は `serious1` (12.19) だが差が同点域なので BIC で `polish` が採られている。
T1 も `sizestrain_last` の 9.73 は**未収束**なので Rwp では上に来ない (§2.1 実測)。

段の順序を*当てる*ことはできない (試料変位段の配置 4 通り × 4 データで、どの配置でも 1 つ以上が
落ちた)。**候補を独立に実行して測り、規則で選ぶ**:

```json
{"search": true}
```

| いつ使うか | 指定 | 効果 |
|---|---|---|
| **単一フレームの本気解析** (既定の一手にしてよい) | `"search": true` | 既定集合 `default` / `sizestrain_last` / `polish` / `serious1` / `adaptive` を実行して最良を採る |
| 候補を絞りたい (時間/失敗した候補の除外) | `"search": ["default", "polish"]` | 指定した候補だけ |
| **探索で勝ったレシピで反復を続けたい** | `"search": ["polish"]` | そのレシピ 1 本で回す (② で既定レシピを置換する唯一の JSON 経路) |
| 同点や割れ方の判定を変えたい | `"search_config": {"rwp_tie_eps": 0.1, "disagreement_rwp_eps": 0.5}` | 同点近傍は **BIC** で裁定 / 僅差で答えが割れたら警告 |

⚠ **`"search": true` は「選べる候補全部」ではない。** 既定集合は実測で選んだ 5 本で、
`serious` (2 周) は**測定で支配された**ため既定から外してある (回すと時間だけ 1.4 倍かかる)。
名指し (`"search": ["serious"]`) では今も選べる。

**⛔ operando (`sequential_rietveld` / `anchored_sequential`) では使わない。** フレーム数 ×
候補数の積は時間予算に収まらない。時間を安定性と引き換えにできるのは単一フレーム解析だけである。

### 選択規則 (読み方)

1. **収束**していない候補は落とす — Rwp が改善したことは収束を意味しない
2. **物理妥当性 fail** は降格する (**除外はしない**。所見付きで候補表に残る)
3. **観測集合 (データレンジ) が違う候補**は Rwp/BIC では上に来られない — 勝てるのは
   「収束した/妥当だった」という点だけ。χ² は観測点数に比例するので、**データを捨てた候補は
   BIC で必ず勝ってしまう** (実測 T1: レンジを切った候補が BIC 17875→16785 で既知最良を
   Rwp 差 0.019 で "上回った")
4. 残りから Rwp 最良
5. **Rwp 差 < 0.1 ポイントは BIC で裁定** — 候補は母数が違うので Rwp 比較は不公平

返り値の `search` を必ず読む:

| キー | 読み方 |
|---|---|
| `selected` / `selection_reason` | 採用候補と、`rwp` で勝ったのか `bic` で裁定されたのか |
| `candidates[].tier_label` | `収束∧妥当` / `収束∧妥当性fail` / `未収束∧…` / `実行失敗` |
| `convergence_fallback` | **true なら全候補が未収束**でフィルタを外して選んだ = 信頼度が低い |
| `order_dependent` + `warnings` | **true なら Rwp は僅差なのに格子/相分率が割れている** |

`order_dependent` が立ったら、その解は**順序依存**である。Rwp を報告して終わらせず、
**追加測定 (`propose_discriminating_measurements`) か手動確認をユーザーに提案する**こと。
`convergence_fallback` が立ったら `max_cyc` を増やす / `stability.require_convergence` +
`extra_cycles` を足す / データレンジを疑う。

`final_rwp` 以下は**採用候補の結果**であり、`specs` も採用候補の入力 (適応候補が変えたレンジ/
背景を含む) が返る。そのまま `refine_with_revisions` へ持ち回れば同じ土俵で継続できる。

### 同じ答えに収束したかを読む (`search.agreement`)

**Rwp が近いことは同じ解に来たことを意味しない。** 実測 (T3): `serious` と `adaptive` は
Rwp 差 0.361 なのに格子が 0.161% 違う — 精密化された esd より桁で大きい。`search.agreement` は
全候補を総当たりで突き合わせ、**構造 (格子・座標・占有率) が同じ解か**を esd スケールで判定する。

| キー | 読み方 |
|---|---|
| `is_corroborated` | **経路の違う 2 手順以上が同じ解に来た**か = 収束の傍証 |
| `corroboration_reason` | 傍証にならなかった**理由** (下表)。`false` だけでは行動できない |
| `n_distinct_trajectories` vs `n_comparable` | 前者が小さいなら「N 案回したが実質 M 経路」 |
| `basins[].is_clique` | `false` なら鎖 (a≈b≈c だが a≉c) = clique より弱い証拠 |
| `pairs[].verdict` | `SAME_SOLUTION` / `SAME_ON_SHARED_SUBSET` / `DIFFERENT` / `UNDETERMINED` / `INCOMPARABLE` |
| `pairs[].classes[].worst` | **不一致の犯人**を名指す (どの相のどの軸/原子か) |

| `corroboration_reason` | 次にすること |
|---|---|
| `insufficient_procedures` | 候補が少なすぎる。`search` に候補を足す |
| `all_trajectories_duplicate` | **閾値を緩めるのではなく、別の手順を足す**。実効経路が重複している (revert される段だけが違う候補は同じ道を歩いている) |
| `no_independent_agreement` | 一致した対が重複手順どうしだった。経路の違う候補を入れる |
| `basin_too_small` | 全候補が別の解に落ちた = **順序依存が強い**。`propose_discriminating_measurements` か手動確認をユーザーに提案する |

⚠ `UNDETERMINED` は「一致しなかった」**ではない** — esd も許容差も判断材料が無い状態である。
これを「一致」とも「不一致」とも報告してはならない。esd が取れていない (段が revert された /
そのパラメータを解放していない) ことのほうが情報なので、そちらを報告する。

⚠ `profile` と `uiso` の不一致は既定では `SAME_SOLUTION` を妨げない。U/V/W はほぼ平坦な相関谷に
あり (実測 `V×W r=−0.959`)、手順ごとに谷の別の点へ落ちるのが正常だからである。**構造が同じで
プロファイルだけ違うのは矛盾ではない**ので、そう報告すること。

## 収束を確認する (`multistart`) — **規定の標準経路**

**手順を最適化しただけでは、その解が最適化問題の答えなのか出発点の答えなのかが分からない。**
実測 (T1 fluoroapatite, 同一手順の 3 開始点):

| start | Rwp | 結晶子サイズ | 微小歪み |
|---|---|---|---|
| 0 | 12.54 | 0.176 µm | 229 |
| 1 | **9.67** | 0.284 µm | 572 |
| 2 | 19.59 | **0.0010 µm (1 nm)** | 1447 |

同じ手順・同じデータで、初期格子を ±0.7% 振っただけでこうなる。**単発の Rwp 9.67 を見ても
これは見えない。**

```json
{"search": true, "multistart": {"n_starts": 5, "coord_jitter_ang": 0.05, "jobs": 5}}
```

**順序が本質**: `multistart` を渡すと ② は必ず**手順最適化 (Phase A) → 収束確認 (Phase B)** の
順で回す。逆順・片方だけは意味を成さない — 決めていない手順を確認しても、何を確認したのか
言えない。開始点は独立なので `jobs = n_starts` で**壁時計は 1 開始点分**になる (ただしその
1 開始点は平均ではなく**最悪**。摂動された開始点は無摂動より数倍長くかかる)。

| キー | 既定 | 何のためか |
|---|---|---|
| `n_starts` | 5 | 開始点数。**奇数**にすると格子グリッドの中央が無摂動になり基準点が入る |
| `lattice_frac` | 0.007 | 格子摂動の幅 (±0.7%) |
| `coord_jitter_ang` | 0.05 | 座標摂動の振幅 (Å)。**0 にすると構造の局所解を試験しない** (格子軸だけの試験になる) |
| `jitter_seed` | 0 | 摂動の種 (固定 = 再現する) |
| `jobs` | 開始点数 | 並列度 |

⚠ **`stages` (追加段階) とは併用できない** (error dict になる)。収束確認は候補を**名前**で
手順を固定するので追加段階を運べない — 追加段階を試すなら `search` 単独で、収束確認するなら
`stages` なしで呼ぶ。

### 返り値の読み方 — **単一の bool を headline にしない**

| キー | 読み方 |
|---|---|
| `convergence.structure_is_corroborated` | **格子・座標・占有率が収束したか = 解を採用してよいかの判断** |
| `convergence.class_convergence` | クラスごとの収束。**何をすべきか**はここで決まる |
| `convergence.undetermined_by_initial_values` | 開始点間で esd を超えて割れた値 = **出版してはならない値** |
| `convergence.is_corroborated` | 全クラスの厳密 AND。縮退のあるデータでは滅多に真にならない (参考) |
| `convergence.adopted_recipe` | Phase A が採用した手順 (何を確認したのか) |

**同じ「収束しなかった」でも処方が違う** — 実測で T1 は**歪**で、T3 は**格子**で割れる:

| 割れたクラス | 意味 | 次にすること |
|---|---|---|
| `microstructure` (サイズ/微小歪み) | ピーク幅を支配するパラメータどうしの**縮退**。手順では解けない | 標準試料で装置分解能を固定する (`propose_data_preprocessing` ではなく別途校正)。それまでは**値を出さない** |
| `cell` | 目的関数が平坦で格子を決める情報が足りない (Rwp 差 0.1 ポイントで格子が割れる) | `propose_discriminating_measurements` (追加測定) か高角側/別波長の検討をユーザーに提案 |
| `coord` | 構造そのものが割れている | **解を採用しない**。空間群/初期構造を疑う (`mem-model-fix` skill) |
| `occupancy` | 混合占有の分離が効いていない | コントラストのあるヒストグラム (中性子) の追加を提案 |

### ⛔ してはならないこと

- **閾値を緩めて「収束した」ことにしない。** 縮退は手順でも閾値でも解けない。緩めるのは
  「決まっていない」を「決まった」に書き換える操作であり、esd が付いているだけに
  読み手は決まった値として受け取る。**最悪の失敗形**である。
- **`undetermined_by_initial_values` に挙がった値を報告書・出版値に載せない。** 所見として
  「初期値依存のため未決定」と書く。値を書くなら必ずこの但し書きを付ける。
- **`structure_is_corroborated: false` を「解析失敗」と報告しない。** 何が割れたのかが情報
  であり、上の表がそのまま次の手になる。
- **⛔ operando (`sequential_rietveld` / `anchored_sequential`) では使わない。** `search` と
  同じ理由 — フレーム数 × 開始点数は時間予算に収まらない。

### プロファイル (U/V/W, X/Y) が割れたとき

**構造と歪が収束していれば、プロファイルは最良フィットを選ぶだけでよい。** 装置側の nuisance
であり値そのものを出版しない。Rwp のばらつきは所見として報告する (恒常的なら装置分解能の
固定を検討する材料になる)。

決定の根拠と実測: `docs/design/stable-baseline-recipe/STANDARD-PROCEDURE.md` /
`docs/benchmark/stable-baseline-recipe/PHASE-B-FINDINGS.md`。

## 段が「黙って壊れている」を疑う (`stability`)

**Rwp が改善したことは、その段が収束したことを意味しない。** GSAS は
`Maximum shift/esd = 258` を出しながら「改善した」段を通す (実測)。同様に、rwp が動かないのは
「効かなかった」のか「そもそも何も精密化していない」のかを Rwp からは区別できない。
`auto_rietveld`/`refine_with_revisions` の `stability` 引数で診断ゲートを有効にする:

```json
{"stability": {"require_convergence": true, "max_shift_esd": 1.0, "extra_cycles": 2,
               "detect_noop_stages": true, "record_weak_vars": true,
               "report_undetermined": true, "record_correlations": true}}
```

| いつ使うか | キー | 効果 |
|---|---|---|
| 段が進むほど結果が不安定・後段が壊れる | `require_convergence` (+ `max_shift_esd`/`extra_cycles`) | 未収束段は**追加サイクルで回し直し**、駄目なら revert |
| ある段から Rwp が全く動かない (段列が死んでいる疑い) | `detect_noop_stages` | n_params 不変 + rwp/gof ビット同一の段を警告 (**revert はしない**) |
| どのパラメータが決まっていないか知りたい / 出版前 | `report_undetermined` | 最終収束後の `esd >= 値` を `undetermined_parameters` に**所見として報告** (凍結しない) |
| どの段でどのパラメータが暴れたか追いたい | `record_weak_vars` | 各段の弱い変数を ledger に**記録するだけ** |
| 段の順序を疑っている / 何と何が縛られているか知りたい | `record_correlations` (+ `corr_threshold`) | \|r\|≥閾値 のペアを記録 (**検出のみ・自動凍結しない**) |

結果は `stages[*].note` (`unconverged` / `noop` / `extra_cycles=N`) に出る。
**既定 (未指定) は現行と完全に同一の挙動**なので、まず既定で回し、疑いが出てから足すこと。
未知のキーは黙って無視されず error dict になる (綴り間違いで「有効にしたつもり」にならない)。

## 「決まらなかったパラメータ」をどう読むか (`report_undetermined`)

`undetermined_parameters` (`esd >= |値|` = 標準不確かさが値そのものより大きい) は**失敗では
なく所見**である。「このデータ・このモデルではこのパラメータは決まらない」という情報であり、
握り潰すと NaCuHCF の Ow 判別 (占有率が Na>1 / O<0 に発散したこと自体が決め手だった) と
同種の診断信号を失う。**まず報告し、原因を疑うこと**:

| 何が載っているか | 疑うこと |
|---|---|
| 特定の原子の `AUiso` / `Afrac` | その原子は本当に要るか / 別サイトと縮退していないか (`compare_structure_models`) |
| プロファイル係数 (`U`/`V`/`W`/`X`/`Y`) | データがその項を分離できるだけの分解能・角度域を持っているか (`assess_data_quality`) |
| 背景係数 | 背景項数が多すぎる (`propose_data_preprocessing` の `background_terms` で検算する) |
| ほぼ全変数 | 段が実は収束していない (`require_convergence` を足す) / 相集合が間違っている (`check_phase_set`) |

- **`undetermined_exempt` は「決まっている」ではない。** 座標シフト (`dAx/dAy/dAz`) は
  そのサイクルでの**シフト量**で、収束するほど分母が 0 に近づくため比が構造的に発散する
  (よく決まっている座標ほど大きくなる = 向きが逆)。判定できないので別列に分けてある。
  座標の不確かさを見たいときは `cell_esd` や gpx の座標 esd を見ること。
- **凍結して消してはいけない。** 報告のあとに何をするかは ③ とユーザーの判断であって、
  ツールが黙って母数を削る対象ではない (提案 ≠ 適用)。

### どうしても凍結したいとき

| いつ使うか | キー | 効果 |
|---|---|---|
| 出版用に「決まらない変数を固定した最終値」が欲しい | `polish_frozen_undetermined` (要 `report_undetermined`) | 報告された変数を凍結して**もう 1 回**精密化し再報告 |
| 段が収束しない / 悪条件で進めない | `rescue_freeze_on_failure` | **未収束か `SVD0>0` のときだけ**最弱を 1 個凍結して再試行 |
| 上でも駄目・条件数が進行を妨げている | `prune_weak_vars_each_stage` | 受理された段のたびに永続凍結 (**最終手段**) |

**⚠ `polish_frozen_undetermined` を使ったら、その `final_rwp` は「一部の変数を凍結した fit」の
値である。** 拘束なしの run と同じ列に並べる前に `final_polish` (`applied` / `frozen` /
`rwp_before` → `rwp_after`) と `frozen_parameters` を必ず報告に含めること。

**⚠ `prune_weak_vars_each_stage` は不可逆なラチェットである。** 途中段階の大きな esd は
「決まらない」ではなく「まだ決まっていない」だけ (座標がずれた段階の Uiso など) で、そこで
凍結すると後段で本来決まるようになっても二度と解放されない。実測: 背景 6 項が S1 完了時に
全部凍り、`n_params` が S2 で 10 → 4 のまま最後まで走った (最終 Rwp も悪化)。
**まず `rescue_freeze_on_failure` を試すこと。**

## 格子や試料変位が暴走するとき (箱拘束 — 同じ `stability` 引数)

格子が桁で飛ぶ・試料変位が装置的にあり得ない値まで走る、といった発散は**数値的事故**であって
情報ではない。**装置・幾何パラメータにだけ**箱拘束を張って止められる:

```json
{"stability": {"bound_cell": 0.05, "bound_displacement": 5000.0, "bound_size_strain": true}}
```

| いつ使うか | キー | 効果 |
|---|---|---|
| 格子が初期値から大きく離れて発散する | `bound_cell` (相対幅, 例 0.05 = ±5%) | 逆格子成分 `A0,A1,A2` を初期値の ±X% に制限 |
| 試料変位が暴走して格子が変位を肩代わりする | `bound_displacement` (µm) | `Shift` / `DisplaceX,Y` を ±この値に制限 |
| Size/Mustrain が 0 や負へ抜けてピーク幅が発散する | `bound_size_strain` (+ `max_size`/`max_mustrain`) | 等方 Size/Mustrain に正値下限と**十分緩い**上限 |

**⚠ 占有率・Uiso・座標を拘束するキーは存在しない。意図的に作っていない。** 構造パラメータの
異常値は「モデルが間違っている」という**診断信号**である。実証: NaCuHCF の model5 は占有率が
Na>1 / O<0 に発散したこと自体が「Ow が必要」の決め手で、[0,1] に拘束していれば model5 は
「一見まとも」になり model6 と判別できなかった。**占有率や Uiso が非物理なら拘束するのではなく
モデルを疑い**、`mem-model-fix` skill へ引き継ぐこと。

**上限は物理的必要値を十分上回る値にする。** 低い上限は境界不安定を生み「偽の"改善せず"」を
作る (NaCuHCF: ADP の上限を上げたら ND Rwp 18.0→14.7%)。既定 (`max_size` 1e4 µm /
`max_mustrain` 1e5) は実在値を桁で上回っている — 締めるより先に、なぜそこまで走るのかを疑う。

**境界に当たったら握り潰さずに報告される**: `stages[*].note` の `bound_hits=N` と ledger の
`m7_stage_bound_hit` (変数名・どちら側・箱の値・理由)。境界到達は「箱が間違っている」か
「モデルが間違っている」かのどちらかなので、**当たったこと自体を所見として扱う**こと。

## restraint (bond/ChemComp) を実際に効かせる (`enable_restraints`)

**`bond_restraints` / `chem_comp_restraints` を渡しただけでは拘束は効かない。** この
バージョンの GSAS-II は headless (プログレスダイアログなし) では restraint の penalty を
最小二乗の目的関数から外すため、登録はされるが χ² に入らない。効かせるには:

```json
{"stability": {"enable_restraints": true, "report_undetermined": true}}
```

- **`report_undetermined` との併用が必須** (単独指定は error dict)。拘束は実質的に母数を
  増やすので、**何が決まらなかったかを見ないまま**回すことは認めていない。
  ⚠ 凍結 (`prune_weak_vars_each_stage`) を足す必要は**ない** — 拘束下で毎段凍結すると
  母数が不可逆に痩せる (実測: 背景 6 項が S1 で全部凍り n_params 10→4)。
- 効いているかは **同じ拘束をターゲット違いで 2 回回して結果が変わるか**で確かめる
  (変わらなければ効いていない)。

### 拘束を効かせたときに **どの Rwp を読むか**

GSAS が返す Rwp は penalty 込みの値になる (残差ベクトルに penalty が連結されるため)。
tsumugin は**データ項と penalty を分離**して返すので、読む列を間違えないこと:

| キー | 意味 | 使い道 |
|---|---|---|
| `final_rwp` / `stages[*].rwp` | **データ項のみの Rwp** | **これが出版値**。拘束の有無に関わらず「観測パターンへの合わなさ」だけを表す。拘束なしの run とそのまま比較してよい |
| `final_rwp_penalized` / `stages[*].rwp_penalized` | penalty 込みの GSAS 生値 (拘束なしなら `null`) | 最小二乗が実際に最小化している目的関数。**出版しない** |
| `final_restraint_penalty` | penalty の絶対量 (`RestraintSum`) | 重みが過大かの判断材料 |

- **段の受理/revert は `rwp` (データ項) で判定される。** 拘束は「引く力」であって適合の悪化では
  ないので、penalty の増減で段を revert してはならない (分離前は bond weight 1e5 で
  Rwp 3558 = **全段 revert** した)。
- **`final_rwp_penalized` − `final_rwp` が大きい = 拘束がモデルを強く引いている。** 拘束が
  データと争っている状態なので、`weight` を下げるか、そもそも拘束が正しいかを疑うこと。
- **`final_gof` は penalty 込みのまま**である (拘束付き精密化では拘束項を観測と自由度の
  双方に数えるのが慣行)。**これは分け忘れではなく警報として残してある** — 拘束がデータと
  争うと `final_rwp` が穏やかでも GOF が跳ねる (実測: 誤ったターゲット + weight 1e5 で
  `final_rwp` 33.07 に対し `final_gof` 1641.8)。**Rwp だけ見て「拘束は無害だった」と
  結論しないこと。**
- 分離の材料 (`rwp_data` / `rwp_penalized` / `restraint_sum`) は段ごとに ledger
  `m7_stage_restraint_split` にも残る。

## 構造改訂が要るとき → `mem-model-fix` skill

Rwp は収束したが **物理妥当性 fail・占有率発散・構造の誤りが疑われる**とき、残差だけでは「どこを
どう直すか」が一意に決まらない。**MEM (電子/核密度) で未モデル散乱を空間的に可視化して構造を修正
する** `mem-model-fix` skill (`plugins/tsumugin/skills/mem-model-fix/SKILL.md`, `/mem-fix`) へ引き継ぐ。
MCP `mem_density` → `propose_structure_revisions` → `edit_cif` → `refine_with_revisions` を駆動し、
欠損原子/分割サイト/占有率誤り/水素を判断する (構造編集はユーザー承認・Rwp 改善∧妥当性維持で受理)。
