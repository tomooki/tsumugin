# fit-then-judge P1-1B — 設計 (テンプレート: pass 1 → 静的コンパイル → 候補 `"template"`)

- **状態**: 実装中 (branch `milestone/fit-then-judge-1b`)
- **上位**: [proposal.md](proposal.md) v5 §4 (決定 1B)・§5 (統計の規約)。要件は
  [`docs/spec/fit-then-judge/requirements-1b.md`](../../spec/fit-then-judge/requirements-1b.md)、作業計画は
  [`docs/tasks/fit-then-judge/p1-1b.md`](../../tasks/fit-then-judge/p1-1b.md)
- 本書は proposal §4・§5 を**既存コードに落とすときに決めたこと**だけを書く。段の表・オフセットの表・統計の判定量は proposal が正。

---

## 1. 置き場所

| モジュール | 役割 | 依存 |
|---|---|---|
| `evidence.fitstats` | §5 の判定量 (Hamilton 検定・同母数の 2 解の比較・実効自由度の推定) | numpy、scipy (**遅延 import** — χ² 分位点) |
| `template.declarations` | `TemplateDeclarations` (§4.1 の入力宣言)・`TemplateScopeError`・範囲の検査 | stdlib、`autorietveld.model` |
| `template.compile` | 判断 (`TemplateDecisions`) → 静的な段列・`PhaseSpec`・ヒストグラム (純関数)。pass 1 の段列もここで作る | `autorietveld.model`/`recipe` |
| `template.pass1` | pass 1 の進行 (runner を注入) と判断の決定 | `evidence.fitstats`、`template.compile` |
| `template.uiso` | Uiso のまとめ方の規則 ((元素, 配位数) でまとめる) | pymatgen を**遅延 import** (無ければ `unevaluated`) |
| `template.probe` | 初期値プローブの判定 (プローブ結果 → 値ごとの戻り/割れ) | `autorietveld.agreement` |
| `autorietveld.engine` | 段フラグ `cell_phases`・`blas_threads`・保存した gpx からのプローブ (`probe_from_gpx`) | GSAS 遅延 import |

`autorietveld` の中に置かないのは、テンプレートが「engine の部品を組み合わせて使う手続き」で、engine の外から
`run_auto_rietveld(recipe=…)` だけを呼ぶため (静的コンパイルの不変条件そのもの)。`search` はテンプレートを
候補として呼ぶが、`template` は `search` を import しない (循環を作らない — 候補への包みは `search` 側が持つ)。

統計を `evidence` に置くのは、BIC (`evidence.ic`) と同じ「モデル比較の尺度」の置き場所だから。BIC の実装の統合は別作業
(proposal §5) なので、`fitstats` は BIC を再実装しない。

## 2. 統計 (`evidence.fitstats`)

- `hamilton_test(chi2_small, chi2_big, gof2_big, k, *, alpha, dof_ratio=1.0) -> HamiltonResult | None`
  — 判定量 `LR = (χ²_small − χ²_big) / GOF²_big · dof_ratio` を χ²_k の `1−α` 分位点と比べる。`significant` と
  `lr`・`critical`・`k`・`alpha`・`dof_ratio` を返す (derivation に載せるため)。非有限・k<1・GOF²≤0 は None。
- χ² は GSAS の段の値から `GOF² · (n_obs − n_params)` で戻す (段には rwp/gof/n_params、結果には n_obs がある)。
  **拘束 (restraint) を張った fit には使わない** — GOF が拘束項を含む (テンプレートは拘束を張らない)。
- `same_dof_comparison(m1, m2, sigma, chi2_1, chi2_2, gof2, *, alpha)` — `S = Σ((m₁−m₂)/σ)²`、`S/GOF²` が χ²₁ の分位点未満なら
  `distinguishable=False`、それ以外は `z = Δχ²/(2·GOF·√S)`。
- `effective_dof_ratio(residual) -> float | None` — Durbin–Watson `d = Σ(eᵢ−eᵢ₋₁)²/Σeᵢ²` から一次の系列相関 `ρ = 1 − d/2`、
  AR(1) の近似で `n_eff/n = (1−ρ)/(1+ρ)` を (0, 1] に切って返す (正の相関は情報量を減らす。負の相関で 1 を超えた分は使わない)。
  点数が 3 未満・非有限・全ゼロは None (= 補正しない、と明記して derivation に残す)。
  Bérar–Lelann の esd 補正は同じ ρ からの因子で、esd には掛けない (proposal §5「esd に GOF を掛け直さない」と同じ理由で、
  1B の判定量にだけ使う)。
- `RefinementMetrics.effective_dof_ratio` (None 既定) — `evidence.ic` の BIC/AIC で `n` を `n·ratio` に、χ² を `χ²·ratio` にする。
  `noise_scale` との同時指定は `ValueError`。None なら計算に触れない (既存 BIC のビット同一をテストで縛る)。

**σ(χ²)=√(2·dof) をコードに書かない** — `src/` を走査するガード (`2 * dof`/`2.0 * dof` と `sqrt` の組) で縛る。

## 3. 宣言と範囲 (`template.declarations`)

```
TemplateDeclarations(
    instrument_calibrated: bool | None = None,   # 装置関数 (U,V,W,X,Y・非対称) が標準試料由来か
    internal_standard: str | None = None,        # 同一試料内の内部標準の相名 → 格子 scope=absolute
    target_phase: str | None = None,             # 対象相の宣言
    zero_calibrated: bool | None = None,         # 装置ファイルの Zero が較正値か
)
```

- `from_dict` は `_config_spec.spec_value` の規約 (null=既定・型違い/未知キー=ValueError)。宣言の id は `"<キー>"` で、
  宣言に依存した値の `provenance` は `declared(<キー>)`。
- 幾何は `HistogramSpec.geometry` (必須の enum) をそのまま使う — 「不明」は型として存在しないので、proposal §4.2 の「不明」行は
  この範囲では起きない (将来の宣言の拡張点として表に残す)。
- 範囲: ヒストグラム 1 本・`radiation` が CW X 線 (`xray_lab`/`xray_synchrotron` 相当で `is_neutron`/`is_tof` が偽)・バックエンド GSAS-II。
  外れたら `TemplateScopeError(TsumuginError, ValueError)`。
- 宣言は `ledger.append("template_declaration", {..., "actor": "caller_unverified"})` で記録する。**検出器は宣言を読まない**
  (対象相を宣言しても積分強度の比較は回り、近ければ判断要求が出る)。

## 4. コンパイル (`template.compile`)

```
TemplateDecisions(                         # pass 1 が決める (固定するもの)
    target_phase, frozen_cell_phases, background_coeffs, uiso_groups,  # uiso_groups: 対象相の組
    offset: "shift" | "zero", polar_origin: bool,
)
compile_template(histograms, phases, decisions, declarations) -> CompiledTemplate(
    stages, phases, histograms, background_coeffs, template_version, derivation)
pass1_stages(histograms, phases, declarations, *, background_coeffs, cell_phases) -> tuple[RefinementStage, ...]  # 段 0–4
```

段の表し方 (proposal §4.2 の表をこう写す):

| # | label | flags |
|---|---|---|
| 0 | `scale+background` | `scale`, `background: {coeffs: n}` (+ 多相なら次段に `phase_fraction_sum`) |
| 1 | `lattice+offset` | `cell: True` (+ `cell_phases: [凍結しない相]` — 凍結相があるときだけ)、BB は `displacement: {0: ["Shift"]}` / DS は `zero_offset: True` |
| 2 | `width-1` | 較正なし `profile: ["U","V","W"]` / 較正あり `size_strain: "isotropic"` |
| 3 | `width-2` | 較正なし `profile_lorentzian: ["X","Y"]` (Zero を束ねない) / 較正あり — (異方性幅は v1 では出さない。§9) |
| 4 | `asym` | 較正なしのときだけ `profile_asymmetry: True` |
| R | `lattice-retry` | 凍結相があるときだけ `cell: True` (全相) |
| 5 | `coords` | `coords: True` (非対象相は `frozen_coord_labels` で凍結済み) |
| 6 | `B` | `uiso: True` (まとめ方は対象相の `uiso_equiv_groups`) |
| 7 | `occupancy` | 混合占有・部分占有があるときだけ `occupancy: True` |
| 8 | `pref` | Bragg-Brentano のときだけ `preferred_orientation` (対象相・March–Dollase 既定) |
| 8R | `struct-retry` | `coords: True, uiso: True` |
| 9 | `final` | 新しい解放なし (全受理パラメータを回し直す) |

- **フラグは累積** (engine `_apply_stage` は enable のみ) なので、段 R・8R は「直前までに棄却された解放をもう一度試す」ことになり、
  既に受理済みなら同じ解放の再精密化 (= no-op 判定の対象。`StabilityOptions.detect_noop_stages` は期待自由度 0 の段を
  **除外**して判定する — §4.2「期待自由度が 0 の段は noop 判定から除く」は、R・8R・9 の note に `expected_new_dof=0` を残し、
  derivation に載せることで満たす。engine の判定は変えない)。
- 段 9 の「収束確認の追加 1–2 サイクル」は候補の `StabilityOptions(require_convergence=True, extra_cycles=2)` で表す
  (候補が自分の実行設定を持つ既存の仕組み `RecipeCandidate.stability`)。GSAS の `Max shft/sig` を使わず |shift|/esd を自前で
  計算するのは既存の診断ゲート (REQ-SAR-101) がしていること。
- 非対象相: `frozen_coord_labels`・`frozen_uiso_labels` に全原子ラベル。ラベルは CIF から読む (`autorietveld.atomrows` 等の既存の読み手)。
  読めなければ `TemplateScopeError` ではなく**コンパイルの失敗** (候補が立たない + 理由) にする。
- 極性群の対象相は `fix_polar_origin=True`。極性かどうかは CIF の空間群から決める (GSAS の `SGPolax` を引くので GSAS 遅延 import。
  使えなければ derivation に `unevaluated` と残し、固定しない)。
- コンパイル結果の `phases` は `dataclasses.replace` で作る (呼び手の `PhaseSpec` を変えない)。

### 4.1 engine の段フラグ `cell_phases`

`cell: True` の段で格子を解放する相を相名の列に絞る。`refine_cell=False` (手動凍結) と自動凍結 (`auto_freeze_minor_cells`) には勝たない
(手動 > 自動 > 既定の順序を壊さない)。未知の相名は `CorrelationGroupViolation` と同じく入口で `InvalidPhaseSpecError`。
② の `stages` spec でも到達できる (`mcp/_recipe_spec` の語彙に足す)。

pass 1 で凍結した相を `refine_cell=False` で表さないのは、段 R でもう一度試すため (`refine_cell=False` は「決して解放しない」の意味で、
段フラグで覆せない)。代償: 収束確認はこの相の格子も摂動する (`refine_cell` が真なので)。段 R が開始点によって受理/棄却で割れれば
その相の格子は `initial_value_dependent` になる — **評価し直す側の割れを隠さない** (REQ-FTJ-1B-504) のでこれは意図どおり。

### 4.2 engine の `blas_threads`

`run_auto_rietveld(blas_threads=None)`。整数なら `threadpoolctl.threadpool_limits(blas_threads, user_api="blas")` の中で精密化し、
入った直後に `threadpool_info()` で実際のスレッド数を確かめる (違えば ledger に記録して続行 — 再現性の主張を黙って外さない)。
依存に `threadpoolctl` を足す (`uv.lock` 更新)。プロセス全体に効く (workbench の並行ジョブを含む) ことを docstring と ③ に明記する。
テンプレート候補は `blas_threads=1` を持つ (候補のフィールド)。

## 5. pass 1 (`template.pass1`)

```
run_template_pass1(histograms, phases, declarations, *, runner, config, ledger) -> Pass1Outcome(decisions, derivation, results)
```

`runner(histograms, phases, stages) -> AutoRietveldResult` を注入する (既定は `run_auto_rietveld(recipe=…)`。gpx の役割名は
`gpx_context(group.child(role="template_pass1", label=<試行名>))`)。

1. **A: 段 0–4** (全相の格子を解放)。段 1 が受理されたら凍結相なし。
2. 段 1 が棄却されたら (`reverted`): 単相ならその相を凍結。多相なら相ごとに「その相だけ格子を外した段 0–1」を回し、段 1 が受理されて
   Rwp が最小になる 1 相を凍結する。どの 1 相でも受理されなければ全相を凍結 (= 段 R に任せる)。凍結を決めたら A をやり直す
   (proposal §4.3「全体を戻してから」— engine は毎回 CIF から組み立てるので、やり直しは自然に「戻した」状態から始まる)。
3. A の最終状態から: 対象相 (`phase_integrated_intensity` の最大。2 位/1 位 ≥ `target_tie_ratio` (既定 0.8) なら判断要求の印) と
   実効自由度 (A の残差) を決める。
4. **B: 段 0–4 + 背景の増分段** (`background_<n>` を `background_ladder` 既定 (12, 18, 24) のうち初期値より大きいもの) + BB なら
   `zero_offset` 段。Hamilton 検定を隣り合う段で順に行い、最初に有意でなくなった手前の項数を採る (棄却された段は有意でない扱い)。
   Zero は最後の段と直前の段で検定する。
5. Uiso のまとめ方 (`template.uiso`) を対象相の CIF から決める。

`Pass1Config(alpha=0.01, background_ladder=(12, 18, 24), target_tie_ratio=0.8)` — 値は P1.5 で調整する (今の値は「動くこと」のための仮置き)。

`derivation` は JSON 安全な dict: 各判断ごとに `{decision, basis, evidence}` (例 背景: 各段の χ²・LR・臨界値・dof_ratio)。
判断を決められなかった項目は `{"decision": <既定>, "status": "unevaluated", "reason": …}`。

## 6. 探索・収束確認

- `RecipeCandidate` に `phases: tuple[PhaseSpec, ...] | None = None`・`derivation: Mapping | None = None`・`blas_threads: int | None = None`
  を末尾追加 (既定で既存候補はビット同一)。`to_dict` は `derivation`・`template_version` を載せる (None のときはキーを出さない —
  既存の ② 出力を変えない)。
- `CANDIDATE_NAMES` の末尾に `"template"`。`build_candidates` は `"template"` を作らない (GSAS を回す必要があるため) —
  `run_recipe_search` が `"template"` を要求されたとき、**最初に**範囲を検査し (外れたら送出)、候補を回す前に pass 1 を回して
  候補を組む。pass 1 が失敗したら候補は立たず warnings に理由 (適応候補と同じ扱い)。
- 候補の実行 (`_default_candidate_runner`) と `optimize_then_confirm` の Phase B は `cand.phases or phases`・`cand.blas_threads` を使う。
- 収束確認の座標の摂動: engine `_apply_coord_jitter` が、`fix_polar_origin` の相では原点を決める原子の極性方向の座標を摂動しない。
  原点を決める原子の選び方は `_apply_polar_origin` と同じ関数を使う (2 箇所で別に選ぶと食い違う)。これに伴い
  `refuse_polar_origin_with_coord_jitter` を外す (組み合わせが正しく動くので拒否する理由が無い)。既存の Phase B は
  `fix_polar_origin=False` なので変わらない。

## 7. 初期値プローブ

- engine `probe_from_gpx(gpx_path, histograms, phases, *, cell_frac, coord_jitter_ang, sign, seed, max_cyc) -> AutoRietveldResult`:
  gpx を一時ディレクトリへ複製して開き、**その時点で精密化フラグが立っている**格子 (相の `Cell` フラグ) と座標 (原子の `X` フラグ) にだけ
  ±δ を掛け、フラグを変えずに精密化して、`run_auto_rietveld` と同じ抽出で結果を作る。保存した gpx は書き換えない。
  抽出は `run_auto_rietveld` の末尾の組み立てを関数に切り出して共用する (2 箇所で別に組み立てると食い違う)。
- `template.probe.probe_witness(base, plus, minus, tolerances) -> dict[key, "returned" | "split"]` は `parameter_agreements` を使う。
  `claims.build.with_probe(claims, verdicts)` が `esd_only` → `locally_stable` (証人 `initial_value_probe`) と `split` → `initial_value_dependent`
  を付ける。合成は最小なので `determined` の値は戻れば変わらず、割れれば落ちる。
- ②: `auto_rietveld(initial_value_probe={"cell_frac": 0.003, "coord_jitter_ang": 0.02})` (null で回さない)。gpx を保存しない呼び出しでは
  `initial_value_probe_reason` に理由を返して回さない。

## 8. ② と ③

- `auto_rietveld(search=[..., "template"], template={宣言})`: `template` は `"template"` を要求したときだけ意味を持つ。要求せずに渡したら
  error dict (黙って無視しない)。範囲外は error dict。出力の探索表 (`search.candidates[]`) のテンプレート候補に `derivation`・`template_version`。
- テンプレートの判断から出る判断要求 (対象相が僅差・Zero が有意) は 1A の `assess` に `extra_requests` として渡す (`JudgmentRequest` の
  新しい種類 `target_phase_ambiguous` (blocking: 全相の構造値)・`zero_offset_significant` (非 blocking))。
- `refine_with_revisions`: 入力 spec の生の dict に `template_version` があれば error dict。
- ③ `skills/analyze`: 「テンプレート」節 — いつ使うか (CW X 線・単一ヒストグラムで、既定の探索の候補群が共通に破綻したとき /
  比較のための 1 候補として)、使えない範囲、`derivation` の読み方、判断要求を閉じないこと。AGENT_PLAYBOOK も同じ。

## 9. 既知の限界 (v1 で入れないもの)

- 較正ありの width-2 (異方性幅): 異方性の型の選択が要るので出さない (P1.5 で判断)。
- 任意段の統計的受理 (段ごとに Hamilton 検定で受理する): engine の受理規則を変えることになるので入れない。pass 1 の判断にだけ使う。
- 外部背景・偏光・参照構造の温度の宣言: 型は将来の拡張点として残し、v1 の `TemplateDeclarations` には入れない (受け口を作って何もしないと
  「宣言したのに効かない」になる)。
- ledger の永続化の ② 配線: `run_auto_rietveld(ledger=)` に `PersistentLedger` を渡せば足りるが、② の到達経路 (パスの規約) は別作業。
