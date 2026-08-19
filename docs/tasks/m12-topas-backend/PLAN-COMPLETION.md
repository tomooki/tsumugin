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

- [ ] `tests/topas/test_engine.py` に `test_benchmark_t4_multiphase_tof` を追加。
      **GSAS T4 と同一の `HistogramSpec`** (リミット / `temperature=298.0` / 同じ instprm) を使う。
- [ ] 現状値で回して**実測を閾値に固定**する (合格基準 15% はまだ課さない。
      `pytest.approx` ではなく「これより悪化したら落ちる」形の上限で置き、W2/W3 で締める)。
- [ ] 同じ条件で再測した値を README に**「条件を揃えた後の T4」**として記録する。

**判断材料**: この再測値が 30.9% からどれだけ動くか。大きく動けば W2 の重みが下がる。

> ⚠ 恒久ガードは**変異させて fail することを実証**してから受け入れる (CLAUDE.md)。
> 「リミットを外すと落ちる」ことを 1 回確かめる。

### W1 `hydrostatic_strain` の翻訳 (#173) → T3-joint の第一仮説 (#178)

- [ ] **設計**: joint でセルが共有 `prm` の場合、各 xdd の `str` ブロックで
      `a = <shared_a> (1 + eps_a_h<i>);` 形の参照式に差し替える。
      - 基準ヒストグラム (index 0) の `eps` は **0 固定** — 共有セルと完全縮退するため。
        GSAS は SVD 減衰で吸収しているが、TOPAS では明示的に潰す。
      - 結晶系で変数の数を決める (立方=1 / 正方・六方=2 / 直方=3 / 単斜・三斜は当面
        直方相当の 3 とし、それ以外は `UnsupportedStageFlagError` を維持する = 黙って近似しない)。
      - 単一ヒストグラムでは**無効** (共有 `prm` が無く、格子そのものと縮退する)。
        指定されたら段を no-op にせず**明示的に失敗させる**。
- [ ] **単体テスト (numpy/文字列のみ)**: 生成 INP の字面で
      (i) xdd ごとに参照式が 1 本ずつ出る (ii) h0 が固定 (iii) 名前が重複しない
      (既存の不変条件ガード `test_no_parameter_name_is_declared_twice_in_a_joint_document` に載る)
      (iv) 単一ヒストグラムでは `UnsupportedStageFlagError`。
- [ ] **実 tc.exe が受理すること**を既存の
      `test_new_flags_produce_inp_that_tc_actually_accepts` のパラメータに追加 (★このガードが
      `Cylindrical_I_Correction` の罠を捕まえた実績のある形)。
- [ ] **`build_topas_recipe` に温度差アダプタ**を足す (GSAS の `_has_temperature_difference` を
      再利用。段の位置は S2 cell+displacement の直後)。
- [ ] **T3-joint 実測**: 合格基準 ≤8% に届くか。届かなければ W3 へ持ち越し。
- [ ] **②③ (★不変条件)**:
      - ② `mcp/_recipe_spec.py` は既に `hydrostatic_strain` を許すので**配線追加は不要**。
        JSON だけで `auto_rietveld(backend="topas", recipe=[...])` に載ることを実測確認する。
      - ③ [`skills/analyze/SKILL.md:53`](../../../plugins/tsumugin/skills/analyze/SKILL.md):53 の
        「`hydrostatic_strain` は未対応」を**同じ PR で**直す。
      - ガードを文字列一致でなく **`SUPPORTED_FLAGS` との突き合わせ**にする
        (今は SKILL に手書きしてあるだけなので、次に増えたときまた腐る)。

### W2 T4 の TOF を詰める (#179)

W0 の再測結果を見てから着手する。優先順位は内訳 (PG3 45.9 / 48.2 が支配的) の通り TOF から。

- [ ] **TOF ピーク形状**: `TOF_Exponential` (立ち上がり/減衰 = GSAS の alpha/beta) を
      `topas/instrument.py::tof_peak_type` に導入する。
      - GSAS の sig-1/sig-2 は**分散の d²/d⁴ 係数**、TOPAS は **FWHM の d/d² 係数**で関数形が違い、
        実 POWGEN の sig-1 は**負** (-167.4) なので素直な写像が無い (docstring 既述)。
        **写像を捏造せず**、TOPAS 側の初期値から精密化で寄せる方針を採る。
      - `tof_profile` 段が revert されている原因を先に切り分ける (初期値か、箱 (`min/max`) か、
        段の位置か)。**revert が「効かない」ではなく「悪化する」ことの確認**から入る。
- [ ] **背景項数の per-histogram 化**: 現在 `run_topas_rietveld(background_coeffs: int)` が全 xdd 共通。
      11BM は M9 CaTeO3 で 24 項が必要だった前例がある一方 TOF は少数で足りる。
      `int | Sequence[int] | Mapping[int, int]` を受けるよう拡張する。
      - **② への配線を同じ PR で**確認する (JSON から per-histogram 背景に到達できること。
        できなければ ③ にとってこの機能は存在しない)。
- [ ] 1 手ごとに測って**どの変更が何ポイント効いたか**を README に残す
      (「ピークはどこかに立つので Rwp だけが悪い」型の欠陥は、効果を記録しないと次に辿れない)。

### W3 T3-joint の残差詰め (#178 の残り)

W1 で届かなかった分。**上から順に 1 つずつ測る** (同時に変えない)。

- [ ] 背景項数 (現状 6)。
- [ ] 中性子側の非対称 `Simple_Axial_Model` の初期値。
- [ ] size/mustrain の解放順序 (現状 S9 最後)。
- [ ] 選択配向を**既定レシピに載せるか** → §5 の判断 2。

### W4 `TopasBackend` の実 CIF 対応と ② 露出 (#180)

- [ ] `backends/topas.py` に `structure_ref` 分岐を実装する
      ([`backends/gsasii.py:324`](../../../src/tsumugin/backends/gsasii.py):324 相当 = 実 CIF を読んで
      格子だけ上書き)。素材は `topas.structure.structure_to_topas_phase` に揃っている。
- [ ] `NotImplementedError` による拒否を**外す**。外した瞬間に
      `tests/test_layer_coverage.py::test_topas_backend_non_exposure_reason_is_still_true` が落ちる
      (= 非露出宣言の再検討が強制される。設計どおりの挙動)。
      `test_no_mcp_tool_constructs_the_topas_backend` も併せて更新する。
- [ ] ② `discriminate` に `backend` 引数を足す (JSON のみで到達できること)。
- [ ] ③ `skills/analyze/SKILL.md` に「**いつ TOPAS で判別するか**」を書く (★不変条件の 2 点目)。
- [ ] **実データ検証**: 同じ `structure_ref` 付き仮説集合を GSAS と TOPAS の両方で判別し、
      **順位が一致すること**を見る (不変条件「バックエンドを替えると仮説の順位が変わる」を作らない)。

### W5 段方針の共通化 (#175 の T7)

**最後に置く**。W1–W3 で TOPAS engine の受理/revert 周りに手が入る可能性があり、
動く形が確定してから抽出する方が安全なため。

- [ ] `autorietveld/stagepolicy.py` に**判定ロジックだけ**を純関数で抽出する
      (受理/revert 判定・`StageResult` 組立・ledger 追記キー)。
- [ ] `.gpx` 操作・無言失敗検出 (`_capture_refine_status`)・`_apply_sample_geometry` の
      Type 整合・セル崩壊ガードには**触らない** (実測で積み上げた振舞い)。
- [ ] 受け入れ: `-m gsas -k "engine_t1 or engine_t2 or engine_t3 or engine_t4"` が
      M7 記録値 (9.83 / 4.33 / 6.66 / ~12.8%) から非回帰。`-m topas` も非回帰。
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
