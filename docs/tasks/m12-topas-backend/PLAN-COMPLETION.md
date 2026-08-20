# M12 完全対応計画 (第 2 期) — 2026-08-19

第 1 期 (PR #176 / #177) で TOPAS バックエンドは**動く**ところまで到達した。本計画は
**残る 5 Issue (#173 / #175 / #178 / #179 / #180) を閉じて M12 を完了**させるための実装計画である。

- 第 1 期の記録: [PLAN.md](PLAN.md) / 設計: [../../design/m12-topas-backend/architecture.md](../../design/m12-topas-backend/architecture.md)
- ベンチ実測: [../../benchmark/m12-topas/README.md](../../benchmark/m12-topas/README.md)
- トリアージ上の位置づけ: P2 (「GSAS 経路は動いているので当面の到達性は損なわれていない」)

## 0. 完了の定義 (Definition of Done)

| # | 条件 | 現在 |
|---|---|---|
| D1 | T12 実データ 5 系すべてが合格基準を満たす | 3/5 (T3-joint 8.29 / T4 30.9 が未達) |
| D2 | 段階フラグ 17/17 | 16/17 (`hydrostatic_strain` 未対応) |
| D3 | `TopasBackend` が実 CIF 対応 → ② `discriminate(backend=)` で露出 | 非露出 (理由を機械検査中) |
| D4 | 段方針 (受理/revert 判定) が GSAS/TOPAS 共通 | 別実装 (T7 未着手) |
| D5 | ベンチ README / PLAN / CLAUDE.md / provenance が実測と一致 | 第 1 期時点 |
| D6 | Issue #173 #175 #178 #179 #180 クローズ | 5 件 OPEN |

**D1 が満たせない場合の扱いは先に決める** (§5 の判断 1)。「基準未達のまま完了」を黙って
やらないこと。

## 1. 調査で判ったこと (計画の根拠)

### (a) #173 と #178 は同じ仕事である — 「検算できる実データが無い」は誤り

Issue #173 は `hydrostatic_strain` を「検算できる実データが無いので入れていない」としているが、
**T3-joint がまさにその実データ**である。

- GSAS のレシピは**ヒストグラム間に温度差があると per-histogram Dij を張る**
  ([`autorietveld/recipe.py:436`](../../../src/tsumugin/autorietveld/recipe.py):436 / :473, `_has_temperature_difference`)。
- M7 の T3 は **X 線 295 K / CW 中性子 10 K** ([`tests/autorietveld/test_engine_t3.py:34`](../../../tests/autorietveld/test_engine_t3.py):34, :42) →
  **GSAS 6.66% は Dij を使って出した値**である。
- TOPAS 側は (i) `build_topas_recipe` に該当段が無く、(ii) `flags.SUPPORTED_FLAGS` が未対応で、
  さらに (iii) joint ではセルが [`topas/inp.py::_shared_prm_plan`](../../../src/tsumugin/topas/inp.py) で
  トップレベル `prm` へ持ち上げられ**全 xdd で 1 本を共有**している。
- つまり TOPAS は 285 K 分の熱膨張差を**単一のセルで妥協して吸収**している。
  内訳が X 線 8.26 / 中性子 8.37 と**両方同じくらい悪い**のは、片側故障ではなく
  「共有セルが両者の中間に落ちている」像と整合する。

⇒ **#173 を実装することが #178 の第一仮説**であり、両者は 1 つの作業単位にする。

### (b) T4 は GSAS と違う条件で測っている — 比較の前提が崩れている

| | GSAS T4 ([`test_engine_t4.py`](../../../tests/autorietveld/test_engine_t4.py)) | TOPAS T4 (#179 記載) |
|---|---|---|
| 11BM 放射光 | 2.5–32.0° | 2–40° |
| PG3-1066 | 11750–103794 µs | 7000–100000 µs |
| PG3-2665 | **制限なし** | 26500–200000 µs |
| temperature | 3 本とも 298 K | (指定の記録なし) |

M7 で「T4 非収束の主因は**データリミット未設定**」と実測で結論づけている以上、
**リミットが違う 2 つの値を並べて 30.9 対 12.8 と言うことに意味がない**。
また **TOPAS の T4 には回帰テストが存在しない** (`tests/topas/test_engine.py` は T1 / T2 /
T3-joint のみ) ので、30.9% はアドホック測定の記録でしかない。

### (c) #175 の記載は古い — T9 (`TopasBackend`) は実装済み

コミット `aa6cdbc` で `backends/topas.py` は入っている。#175 に残っているのは
**T7 (stagepolicy 共通化) のみ**。Issue 本文の更新が要る。

### (d) 前提は揃っている

`tc.exe` は `C:\TOPAS7\tc.exe` に解決でき、T1–T4 の実データ
(`docs/benchmark/testdata/m7/{labdata,cwneutron,cwcombined,tofcw}`) はすべて手元にある。
本計画は**ローカルで完走できる** (CI では `-m topas` は回らない — GSAS と同じ扱い)。

## 2. 作業単位

順序の原則は「**測り方を正してから測る → 効果の大きい仮説から潰す → リファクタは最後**」。

### W0 比較条件の是正 + T4 の回帰ガード新設 (前提整備)

- [x] `tests/topas/test_engine.py` に `test_benchmark_t4_multiphase_tof_synchrotron` を追加。
      **GSAS T4 と同一の `HistogramSpec`** (リミット / `temperature=298.0`) を使う。
- [x] 現状値で回して固定 (合格基準 15% はまだ課さない)。**実測 68.61%** (旧アドホック 30.32%)。
- [x] README に「条件を揃えた後の T4」として記録。

**結果 (2026-08-19)**: 同一条件では **68.61%** で、以前の 30.9% は**リミットが違う**測定だった。
差は「広いレンジでは通った S7/S8 のプロファイル段が、狭いレンジでは箱に張り付いて revert
される」ことに由来し、**フィット自体はどちらの条件でも S0 から 70% 前後で膠着している**。
`.gsa` は BANK が ``SLOG … FXYE`` なので TOPAS 経路のローダは `"FXYE"` を指定する
(`parse_gsas_powder` は CONST 固定ビンしか読めない = Issue #181)。

> ⚠ **Rwp の上限だけを見るガードでは条件の変更を検出できない** (広げると「良く」なる)。
> 精密化に使った観測点数 `n_obs == 40150` を固定した。アドホック条件は 49709 なので落ちる
> (**実測で確認**)。

**W2 へ持ち越す 2 件** (W0 で判明):

- `size_strain` 段で tc.exe が異常終了する (両条件とも)。rwp=inf → revert には縮退している。
- S3 phase_fractions / S5 occupancy が rwp・n_params ともビット同一で `reverted` も立たない
  = 無言 no-op の疑い。

### W1 `hydrostatic_strain` の翻訳 (#173) → T3-joint の第一仮説 (#178)

- [x] **設計**: joint でセルが共有 `prm` の場合、各 xdd の `str` ブロックで
      `a = <shared_a> (1 + eps_a_h<i>);` 形の参照式に差し替える。
      - 基準ヒストグラム (index 0) の `eps` は **0 固定** — 共有セルと完全縮退するため。
        GSAS は SVD 減衰で吸収しているが、TOPAS では明示的に潰す。
      - 結晶系で変数の数を決める (立方=1 / 正方・六方=2 / 直方=3 / 単斜・三斜は当面
        直方相当の 3 とし、それ以外は `UnsupportedStageFlagError` を維持する = 黙って近似しない)。
      - 単一ヒストグラムでは**無効** (共有 `prm` が無く、格子そのものと縮退する)。
        指定されたら段を no-op にせず**明示的に失敗させる**。
- [x] **単体テスト (numpy/文字列のみ)**: 生成 INP の字面で
      (i) xdd ごとに参照式が 1 本ずつ出る (ii) h0 が固定 (iii) 名前が重複しない
      (既存の不変条件ガード `test_no_parameter_name_is_declared_twice_in_a_joint_document` に載る)
      (iv) 単一ヒストグラムでは `UnsupportedStageFlagError`。
- [x] **実 tc.exe が受理すること**を既存の
      `test_new_flags_produce_inp_that_tc_actually_accepts` のパラメータに追加 (★このガードが
      `Cylindrical_I_Correction` の罠を捕まえた実績のある形)。
- [x] **`build_topas_recipe` に温度差アダプタ**を足す (GSAS の `_has_temperature_difference` を
      再利用。段の位置は S2 cell+displacement の直後)。
- [x] **T3-joint 実測**: **8.29% → 7.19%** (GOF 1.44) で**合格基準 ≤8% を達成**。内訳は X 線 8.26→8.22 / 中性子 **8.37→4.07** で、共有セル 1 本の妥協が中性子側を押し下げていたことが確認できた (仮説どおり)。⇒ **#178 は #173 で解決**。
- [x] **②③ (★不変条件)**:
      - ② `mcp/_recipe_spec.py` は既に `hydrostatic_strain` を許すので**配線追加は不要**。
        JSON だけで `auto_rietveld(backend="topas", recipe=[...])` に載ることを実測確認する。
      - ③ [`skills/analyze/SKILL.md:53`](../../../plugins/tsumugin/skills/analyze/SKILL.md):53 の
        「`hydrostatic_strain` は未対応」を**同じ PR で**直す。
      - ガードは既に `tests/test_m12_plugin.py::test_unsupported_flag_list_matches_the_implementation`
        が `SUPPORTED_FLAGS` と突き合わせている (**変異させて fail することを再確認済**)。

**実装中に判った TOPAS の仕様 (実測)**: ε の箱を ±5% にすると **CW 中性子側で tc.exe が
``Invalid d spacing encountered`` を出して異常終了する**。セルが式のとき TOPAS は hkl の
d 範囲を箱の分だけ広げて評価するらしく、λ=1.909 Å に対し観測の d_min が λ/2 の 3% 上に
しかないため縮み側が ``d < λ/2`` を跨ぐ。**同じ INP でも X 線側に張れば完走する**ので
「式にすると落ちる」のではない。箱を ±2% にして解消 (温度差 285 K の歪みは 0.3% 程度)。
併せて `driver._failure_reason` が ``Invalid d spacing`` を**失敗確定後の診断行**として
拾うようにした (判定は広げない — 警告として出て完走する可能性を排除できないため)。

### W2 T4 の TOF を詰める (#179) — **一区切り (2026-08-20): 67.6% → 19.25%**

⚠ **測り直した**: 途中で **tc.exe がスレッド数で結果を変える**ことが判明したため
(同一入力の T4 が 43.49 / 67.62 / 43.49 / 29.29%)、`driver` を 1 スレッド固定にしてから
全部測り直している。以下はすべて決定論値。

| 設定 | 総合 | 11BM | PG3-1066 | PG3-2665 | validity |
|---|---|---|---|---|---|
| 既定 (背景 6・種付けなし) | 67.62% | 73.07 | 36.63 | 44.83 | ✅ |
| ↑ − TOF の α/β | 67.74% | 73.09 | 36.70 | 46.13 | ✅ |
| 背景 20 項 | 26.33% | 21.22 | 32.71 | 45.05 | ✅ |
| **背景 20 + 放射光の種付け** | **19.25%** | **8.67** | 29.01 | 44.57 | ❌ |
| ↑ − `tof_profile` 段 | 22.45% | 7.16 | 46.97 | 46.72 | ❌ |

- [x] **再現性 (NFR-102) を取り戻した** — `driver` が ``OMP_NUM_THREADS=1`` で起動する。
      逃げ道は ``TSUMUGIN_TOPAS_THREADS``。実測所要は T4 全段で 14–21 秒なので代償は小さい。
- [x] TOF の α/β を装置ファイルから写す (`TOF_Exponential`)。**効果は小さい** (67.74→67.62)
      が写像は `topas.inc` から導ける。当初の「45.5% へ一気に」は非決定性を引いた値だった。
- [x] `tof_profile` 段を既定レシピへ (22.45→19.25%)。**置き場所は結果に効かない**
      (前でも後ろでもビット同一)。当初の「24 ポイント差」も非決定性。
- [x] 背景 20 項 (67.62→26.33%)。24 項では悪化する (非単調)。
- [x] `seed_profile` を ①②③ へ配線 (26.33→19.25%)。**放射源で効果が逆転する**
      (放射光 43.9→8.7% / CW 中性子 5.54→9.76% で validity fail) ので既定 OFF、
      `backend="gsasii"` に渡すとエラー。
- [x] **`size_strain` の tc.exe クラッシュを解消** — 原因は ``Negative FWHM encountered`` で、
      `CS_L`/`Strain_L` が**波長と Bragg 角で書かれた角度分散のモデル**だから (TOF には
      対応物が無い)。TOF で同じ物理を担うのは `tof_profile` の d/d² 項。混在 joint では
      非 TOF にだけ張り、全 TOF ならレシピが出さず、指定されたら明示的に失敗する。
- [ ] 背景項数の **per-histogram 化** (11BM は 20 項・TOF は 6 項が妥当)。`HistogramSpec` に
      持たせるのが正しい形だが **GSAS 経路も同時に実装しないと「片方で黙って無視される引数」**
      になるため別 Issue へ。
- [ ] CaF2 の Uiso < 0 (少数相の未モデル寄与)。19.25% は物理妥当性が落ちた状態である。
- [x] **構造的 no-op だった S3/S5 を落とした** (A 案)。S3 は「scale は S0 で既に自由」+
      「`phase_fraction_sum` は TOPAS に概念が無い」の二重の空振り、S5 は占有率の宣言が
      無い相では解放対象ゼロ。`phase_fraction_sum` は受理せず理由付きで失敗させる。
      **結果はビット同一** (消えたのは段列の嘘だけ)。
- [x] **B 案 (分離を本当にやる) も測ったが効かなかった** — S0 を「背景のみ」→「+ 相分率」の
      2 段に割っても A 案と全段一致 (最終 19.2525 / 67.6165 で不変)。背景と相分率は
      この系では分けるほど縮退していない。負けた案として README とレシピのコメントに残す。
- [ ] PG3-2665 の 44.6% (残差の支配項)。

**基準は decision 1(a) に従い改定** — 到達値と理由をベンチ README に記録し、
**「19.25% / validity fail」を記録値として未達のまま**とした。GSAS 側の ≤15% は据え置く。

### W3 T3-joint の残差詰め (#178 の残り)

W1 で届かなかった分。**上から順に 1 つずつ測る** (同時に変えない)。

- [ ] 背景項数 (現状 6)。
- [ ] 中性子側の非対称 `Simple_Axial_Model` の初期値。
- [ ] size/mustrain の解放順序 (現状 S9 最後)。
- [ ] 選択配向を**既定レシピに載せるか** → §5 の判断 2。

### W4 `TopasBackend` の実 CIF 対応と ② 露出 (#180) — **完了 (2026-08-19)**

- [x] `backends/topas.py::_structure_phase` に `structure_ref` 分岐を実装
      (実 CIF を読み**格子長だけ** warm-start へ上書き・**角度は CIF 由来**・解放は
      **結晶系の独立軸のみ**)。GSAS 側 `_add_phases` / `_apply_cell` と対。
- [x] `NotImplementedError` の拒否を外し、宣言を**露出側へ反転**
      (`test_topas_backend_exposure_precondition_still_holds`: 簡約モデルへ戻ったら落ちる。
      `test_mcp_selects_backends_only_through_the_shared_resolver`: 名前の語彙を
      `resolve_protocol_backend` 1 か所に閉じる)。
- [x] ② `discriminate(backend=)` を追加 (JSON のみで到達・未知名は error dict・
      結果に `backend` キーを載せて出所を検算できる)。
- [x] ③ `skills/analyze/SKILL.md` に「いつ TOPAS で判別するか」+ **区間内でエンジンを
      混ぜない**規律を明記 (ガード 2 本)。
- [x] **実データ検証**: 同じ実 CIF (PbSO4) + 同じ実データ + 同じ 0.4% 摂動から
      **両エンジンが同じ格子へ収束** — TOPAS 8.47648/5.40376/6.95684 と
      GSAS-II 8.48207/5.40312/6.96325 (最大 0.066% 差)。gated テストに固定。

**副産物 (この配線で見つけた既存欠陥)**: `TopasBackend` だけ既定重みが ``w=1`` で、
Simulated/GSAS の ``w=1/max(y,1)`` と違っていた。同じ実データで chi2 が 1.4e9 対 6.8e5 と
数桁ずれ、**判別の `close_threshold` (絶対 ΔBIC 閾値) がエンジン依存**になっていた。
既定重みを `backends.base.default_weights` に一本化して解消。

**BIC の母数も修正**: `n_params` を `3 * len(cell_free)` で数えていた (簡約モデル
P m m m 専用の数え方)。実 CIF では結晶系で変わる (立方晶は 1) ので**文書が実際に解放して
いる数**を数える。

### W5 段方針の共通化 (#175 の T7) — **完了 (2026-08-19)**

- [x] `autorietveld/stagepolicy.py` に**判定だけ**を純関数で抽出
      (`decide_stage(previous, trial, worsen_eps, unconverged, detect_noop) -> StageDecision`)。
      revert 理由 (`unconverged`/`non_finite`/`worse`) も返して ledger に残せるようにした。
- [x] `.gpx` 操作・無言失敗検出・試料ジオメトリ整合・セル崩壊ガードには**触っていない**
      (スナップショット復元も ledger のキーも各 engine のまま)。
- [x] **抽出しただけで終わらせない** — 共有した結果、**GSAS 側にしか無かった no-op 検出
      (REQ-SAR-102) が TOPAS 経路にも効くようになった**。W0 で見つけた「T4 の S3/S5 が
      rwp・n_params ビット同一で `reverted` も立たない」がこれで表に出る
      (`StageResult.note` + ledger `noop`/`revert_reason`)。ガードは変異させて fail を実証。
- [x] 「両 engine が同じ関数を使っていること」を機械検査
      (`test_both_engines_use_the_shared_policy`: 別実装に戻ったら落ちる)。
- [ ] 受け入れ: `-m gsas -k "engine_t1 or engine_t2 or engine_t3 or engine_t4"` 非回帰 (実行中)。
- [ ] Issue #175 本文から T9 (実装済み) を落とす。

### W6 仕上げ

- [ ] 全ベンチ再測 → `docs/benchmark/m12-topas/README.md` を実測で更新
      (`n_params` / GOF も入れる — Issue #159 と同じ理由で母数なしの Rwp 比較は判断材料にならない)。
- [ ] `docs/benchmark/provenance.toml` に新規成果物の由来 (`public`/`synthetic`/`private`) を宣言。
      結果は `*/results/` へ (**拡張子で ignore を切らない** — v0.1 公開時の漏洩の型)。
- [ ] `PLAN.md` の進捗表を更新、CLAUDE.md の M12 段落を実測へ合わせる (16/17 → 17/17 等)。
- [ ] `docs/spec/m12-topas-backend/` が**空**のまま (三点セットの spec が欠けている)。
      ここで埋めるか「design + PLAN で足りる」と宣言するかを決める → §5 の判断 3。
- [ ] Issue #173 / #175 / #178 / #179 / #180 をクローズ。

## 3. 検証コマンド

```bash
uv run pytest -m "not gsas and not topas and not agent"
```

```bash
uv run pytest -m topas
```

```bash
uv run pytest -m gsas -k "engine_t1 or engine_t2 or engine_t3 or engine_t4"
```

```bash
uv run ruff check src tests
```

③ からの到達確認 (テスト green ≠ 完了): MCP 経由で `list_refinement_backends` →
`auto_rietveld(backend="topas", recipe=[... "hydrostatic_strain" ...])` を **JSON 引数だけ**で通し、
`result["backend"] == "topas"` と有限の `final_rwp`、そして**段が revert されていない**ことを見る。

## 4. 進め方 (ブランチ / コミット)

- ブランチ `milestone/m12-topas-completion` を切る。
- W0 → W1 → W2 → W3 → W4 → W5 → W6 の順に、**1 単位 green ごとに 1 コミット**。
- W3 終了時点 (= D1/D2 が決着) で一度 PR を出し `/code-review` の修正ループを回す。
  W4/W5 は独立性が高いので分割 PR でもよい。
- 実装は Fable 主導 TDD。調査のファンアウトは Sonnet に委任してよいが、
  **物理仮説の採否と受け入れ判断は委任しない**。

## 5. 決定事項 (2026-08-19 ユーザー判断済)

1. **T4 が ≤15% に届かなかったときは (a)** — 基準を **TOPAS 用に改め、理由を記録して完了**とする。
   TOF のプロファイル関数形が GSAS と違い素直な写像が無いため、届かない可能性は現実にある。
   - **条件**: 改定した基準値と**なぜその値なのか** (どこまで詰めて何が律速だったか) を
     `docs/benchmark/m12-topas/README.md` に書く。**黙って基準を下げない**。
   - 改定は「TOPAS の TOF はここまで」という**事実の記録**であって、GSAS 側の基準
     (≤15%) は据え置く。両者を同じ表に並べるときは基準が別であることを明示する。
2. **選択配向は opt-in を維持する** — 既定レシピには載せない。実測では下がる
   (T3-joint 8.30→8.10 / garnet 12.34→11.68) が、これは**モデルを足して残差を下げている**ので
   「基準を満たすための手段」にすると相数を Rwp で決めない規律と同じ穴を開ける。
   W3 で PO を試すのは**切り分けのため**であり、合格の手段にはしない。
3. **`docs/spec/m12-topas-backend/` は埋めない** — 「仕様 §P7 + design + PLAN で足りる」と宣言する。
   空ディレクトリは削除し、design の冒頭に「仕様の正は §P7」と 1 行書く (決めて書く、が要点)。

## 6. 見積り

| 単位 | 内容 | 目安 |
|---|---|---|
| W0 | 条件是正 + T4 回帰ガード | 0.5 日 |
| W1 | `hydrostatic_strain` + T3-joint 検証 | 1–1.5 日 |
| W2 | T4 の TOF 詰め | 2–3 日 (探索的、上振れしやすい) |
| W3 | T3-joint 残差詰め | 0.5–1 日 |
| W4 | 実 CIF 対応 + ②③ 露出 | 1–1.5 日 |
| W5 | stagepolicy 共通化 | 1 日 |
| W6 | 再測 + 文書 + クローズ | 0.5 日 |

実データを回す時間 (`-m topas` / `-m gsas` の実精密化) が支配的で、W2 の探索回数が最大の不確実性。
