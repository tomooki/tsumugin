# fit-then-judge P1-1A — 設計 (出版状態の型と出版の止め)

- **状態**: 実装中 (branch `milestone/fit-then-judge-1a`)
- **上位**: [proposal.md](proposal.md) v5 §3 (決定 1A)。要件は [`docs/spec/fit-then-judge/requirements.md`](../../spec/fit-then-judge/requirements.md)、
  作業計画は [`docs/tasks/fit-then-judge/p1-1a.md`](../../tasks/fit-then-judge/p1-1a.md)
- 本書は proposal §3 を**既存コードに落とすときに決めたこと**だけを書く。軸の意味・順序・合成は proposal §3.1 が正。

---

## 1. 置き場所 — 新パッケージ `tsumugin.claims`

| モジュール | 役割 | 依存 |
|---|---|---|
| `claims.model` | `Claim` と軸の型・順序・合成・`publishable` の導出・直列化 | stdlib のみ |
| `claims.build` | `AutoRietveldResult` (+ 任意の収束確認) → `Claim` の写像 | numpy、`autorietveld.model`/`agreement` |
| `claims.requests` | 判断要求の型・発行・止める値の伝播・既定ポリシー D | `claims.model` |
| `claims.witness` | 相集合の完全性の証人 (反射位置から離れた窓の残差 S/N) | numpy |
| `claims.chemistry` | 結晶化学検査器 (三値) | pymatgen を**遅延 import** |
| `claims.sidecar` | `<gpx>.claims.json` の書き出し・読み取り | stdlib |
| `claims.export` | 出版状態の列を持つ CSV | stdlib |

`autorietveld` の中に置かないのは、`Claim` が「1 種類の型を全境界で使い回す」(principles §3) ためで、
将来 insitu・TOPAS も同じ型に載る。`claims.model` は stdlib のみ (`gpxstore`・`instprm` と同じ leaf) にして、
どこからでも import できるようにする。

## 2. 値のキー — 収束確認と同じ語彙

`Claim` のキーは `"<class>:<key>"` とし、`<key>` は `autorietveld.agreement` が開始点の比較に使う文字列と
**同じ**にする (収束確認の判定を値ごとに引き当てるため)。

| class | key の形 | 値の出所 (`AutoRietveldResult`) |
|---|---|---|
| `cell` | `<phase>.<a\|b\|c\|alpha\|beta\|gamma>` | `refined_cells` / `cell_esd` |
| `coord` | `<phase>.<label>.<x\|y\|z>` | `atom_coords` / `atom_coord_esd` |
| `uiso` | `<phase>.<label>` | `atom_uiso` / `atom_uiso_esd` |
| `occupancy` | `<phase>.<label>` | `atom_occupancy` / `atom_occupancy_esd` |
| `weight_fraction` | `<phase>.wt` | `phase_weight_fractions` / `_esd` |
| `microstructure` | `<phase>.<hist>.<size\|mustrain>` | `hap_size` / `hap_mustrain` と esd |
| `profile` | `hist<i>.<key>` | `hist_profile` / `hist_profile_esd` |

`Claim` 自身も `param_class`・`phase`・`label`・`axis` を構造化して持つので、キー文字列を解析する必要はない
(ラベルに `.` を含む CIF でも壊れない)。

## 3. 出自 — engine に足す観測フィールド

**調べて分かったこと**: 最終の共分散 (`gpx["Covariance"]["data"]` の `varyList`・`covMatrix`・`depSigDict`) は
`autorietveld.diagnostics` が段ごとに一時的に読むだけで、結果には残らない。esd の三状態 (`>0`/`0.0`/`None`) では
「未解放」と「revert」と「共分散なし」を区別できない (proposal §3.1 の指摘)。

そこで `AutoRietveldResult` に**観測専用**のフィールドを足す (フィットは変えない — ゴールデンで縛る):

| フィールド | 中身 | 未計測 |
|---|---|---|
| `final_covariance` | 最終段の `varyList`・`depSigDict` のキー (拘束の従属側)・\|ρ\| ≥ 0.9 の対 (`diagnostics.CovarianceRecord`) | `None` (TOPAS・共分散なし) |
| `claim_variables` | 値のキー → それが依存する GSAS 変数名の組 (例 `cell:P.a` → `0::A0…A5`) | `None` |
| `reflection_two_theta` | 先頭ヒストグラムの全相の計算反射位置 (精密化範囲内) | `None` |

`claim_variables` を engine で作るのは、相 ID・原子の行番号とラベルの対応を知っているのが engine だけだから
(GSAS の変数名 `pid::dAx:i` の `i` は原子行の添字)。ρ の閾値 0.9 は `read_diagnostics` の既定と同じ。

写像 (proposal §3.1 の表をこのフィールドで実装する):

| 条件 (上から先に当てる) | `provenance` | `determinacy` |
|---|---|---|
| `final_covariance is None` | (空) | `esd_only`、検査 `provenance_known = unevaluated` |
| 依存変数のどれかが `frozen_parameters` にある | `pruned` | `undetermined_esd` |
| 依存変数のどれかが varyList/従属にある、かつ `undetermined_parameters` に名がある | `refined` | `undetermined_esd` |
| 依存変数のどれかが varyList/従属にある | `refined` | `esd_only` (最終段が非収束なら `unconverged`) |
| esd が `0.0` (対称性で厳密に固定) | `symmetry` | `exact` |
| それ以外 (解放しなかった) | `input` | `esd_only` 未満にしない固定値 — `input_value` 検査で出版時に「入力値」と明示 |

⚠ 「解放しなかった入力値」は proposal の表で `exact` ではない固定値とされる。出版可否は
「入力値として出版してよいか」で、1A では**出版しない**側に倒す (必須検査 `refined_or_symmetry` が fail)。
入力値をそのまま報告に混ぜると「精密化した」と読まれるため。

## 4. 証人

### 4.1 `determined` — 収束確認の値ごとの一致

`ConvergenceReport` に残るのはクラスごとの**最悪の 1 件**だけ (`ClassAgreement.worst`)。値ごとの判定は
`agreement.compare_results` の中で作って捨てている。そこで `agreement` に公開関数
`parameter_agreements(a, b, tol) -> tuple[ParameterAgreement, ...]` を足し (中身は既存の `*_items` を並べるだけ)、
`claims.build` が有効な開始点の全対について値ごとに集計する:

- 全対で `is_agreement` (AGREE / AGREE_BY_FLOOR / AGREE_ONE_SIDED_ESD) → `determined`。証人は
  `{"kind": "multistart_agreement", "n_starts", "n_pairs", "k_esd", "max_z"}`
- どれかの対で `DISAGREE` → `initial_value_dependent` (証人は割れた対と z)
- それ以外 (UNDETERMINED・INCOMPARABLE・ASYMMETRIC) → 昇格しない
- `perturbation_applied` が偽 (何も振っていない) → どの値も昇格しない (空虚な一致)

### 4.2 相集合の完全性 — 反射から離れた窓の残差 S/N

`claims.witness.residual_window_witness(two_theta, residual, sigma, reflections, profile)` (版 `residual-window/3`):
1. 各計算反射の周り ±`3·FWHM(2θ)` を除外する。Kα1+Kα2 の装置では engine が `reflection_two_theta` に
   Kα2 の位置も入れる (GSAS の反射リストは Kα1 の位置しか持たない)。FWHM は `hist_profile` の
   U,V,W,X,Y から GSAS の CW の式で求める (取れなければ `unevaluated`)。
2. 残りの連続区間ごとに ±5 FWHM の局所中央値を引き、反射から離れた点の規格化残差の MAD で σ の過小評価を
   割り戻す (1 未満にはしない)。
3. 各点を中心に**平均 0 の山形の窓** (中央 1 FWHM を +、両側 FWHM/2 を −) の S/N をとり、最大が 5 を超えれば
   `fail`。平均 0 なので**坂は打ち消される** — 単純な窓の和は、除外域のすぐ外まで伸びた強い反射の裾を
   欠落相と取り違えた (実データ T2 garnet で踏んだ)。
4. 残差が空・反射位置が無い・幅が無い・窓が無い・**複数ヒストグラム** → `unevaluated`。窓の中心になれた点が
   5% 未満なら、山が見つからなかったときだけ `unevaluated` (見つけた山は根拠ごと `fail`)。
合成データ (雑音 σ、FWHM 0.235°) で雑音のみ 200 種中 fail 0、FWHM 幅の山は 2σ/点で 12/50・3σ/点で 45/50 を検出。

`check_phase_set` (系列専用) と `unindexed_peak_frac` (反射位置を見ない) は使わない。

## 5. 結晶化学検査器 (`claims.chemistry`)

相ごとに 3 つの検査を三値で返す: `short_contact` (最短距離 / 元素半径和 < 下限)・`bvs_gii`
(結合原子価和の GII が上限超)・`charge_neutrality` (推定酸化数の和 ≠ 0)。

- 構造は相の入力 CIF の非対称単位に、精密化後の格子・座標・占有率を差し込んで pymatgen で組む
  (`Structure.from_spacegroup`)。空間群を組めない・pymatgen が無い → 3 検査とも `unevaluated`。
- R0 は pymatgen 同梱の結合原子価パラメータ (`pymatgen.analysis.bond_valence`) を使い、リポジトリに表を
  複製しない。酸化数は `BVAnalyzer` で推定し、決められなければ `bvs_gii`・`charge_neutrality` は `unevaluated`。
- 閾値 (GII ≤ 0.2 v.u. を pass、0.2–0.3 は pass と区別しない、> 0.3 を fail) は Salinas-Sanchez らの
  経験則で、P1.5 で調整する (版番号付き)。
- 既存 `validity.check_bond_validity` (bool・M10 が依存) は変えない。

## 6. 判断要求と D

proposal は「既存の `ActionProposal` を拡張する」としていたが、**別の型 `JudgmentRequest` にする**:
`ActionProposal` は「適用できる行動」(refine_loop が適用する) で、判断要求は「決まっていないこと」—
候補が行動とは限らない (相集合の完全性の候補は「相を足す」「足さない」「別の測定」)。
`ActionProposal` に止める値の欄を足すと、refine_loop が読まない欄が増えるだけになる。候補に行動があるときは
`ActionProposal` の直列化 (`refine_loop.serialization.proposal_to_dict`) をそのまま載せる。

`JudgmentRequest = (id, kind, blocking, blocks: frozenset[キー], trigger, evidence, candidates, default, priority)`

| kind | 発行条件 | blocking | blocks |
|---|---|---|---|
| `phase_set_completeness` | 証人が `fail`/`unevaluated` | yes | 全値 |
| `input_structure_provenance` | 常に (1A に宣言の受け口が無い) | no | — (`scope.input_provenance = undeclared`) |
| `crystal_chemistry` | その相の検査が `fail`/`unevaluated` | yes | その相の coord/uiso/occupancy |
| `validity` | `validity.checks` に fail | yes | 違反した値とその相 (検査名から引く) |
| `initial_value_dependence` | §4.1 で割れた値がある | yes | 割れた値 + 直接 \|ρ\| の相手 |
| `frozen_cell` | `refine_cell=False` の相、および格子を 1 軸も精密化しなかった相 (入力値・剪定) | yes | **全相の** weight_fraction (分率の和は 1 なので凍結相の誤差は他相に移る。単相の分率 = 1 の exact は除く) |
| `coordinate_freedom` | `coordinate_freedom_mismatches` に原子 | yes | その原子の coord |

blocking な要求の id は `blocks` の各 `Claim.gate` に入る。\|ρ\| の伝播は `final_covariance.correlations` を
`claim_variables` の逆引きで値のキーに直し、**直接の相手だけ**に足す。GSAS は拘束 (混合占有の和など) を
varyList で `::constrN` に置き換えるので、その変数との相関は相手の値を引けない (実 GSAS で確認)。拘束の従属側
だけで動く値も同じ。拘束の中身は別の相のこともある (スケール ↔ 他相の占有率) ので、相手が分からない割れた
値があれば**全値**を止める (`evidence.unmapped_partners`)。

**D (`D-1A/1`)**: 全要求に `{"answer": "hold", "policy": "D-1A/1"}` を返す。gate を外さない。結果は
`judgment_requests[].default` に載り、ledger には残さない (② の単発経路は ledger を返さない — gpx-retention と同じ事情)。
sidecar に D の版を記録する。

## 7. ② の出力

`_result_to_dict` の後に `claims.build.build_claims(result, phases=inp.phases, convergence=None)` を呼び、
次のキーを**足す** (既存キーは変えない):

| キー | 形 |
|---|---|
| `claims_version` | `"fit-then-judge/1A/1"` |
| `claims` | `{キー: Claim.to_dict()}` |
| `judgment_requests` | `[JudgmentRequest.to_dict()]` |
| `publishable_values` | `{キー: {"value", "esd", "unit", "scope", "determinacy"}}` — `publishable` な値だけ (`scope` を落とすと相対値の格子が絶対値として報告される) |
| `claims_sidecar` | 書いた sidecar のパス (`""` = 書いていない) |
| `claims_sidecar_reason` | sidecar を書かなかった理由 (`warnings` は成果物の退避理由の行なので混ぜない) |
| `claims_policy` | 既定ポリシー D の版 (`D-1A/1`) |

- 単発経路 (`auto_rietveld` 単発・`refine_with_revisions`): 収束確認が無いので `determined` は付かない
  (`esd_only` が上限)。
- 探索経路: 採用候補の結果で同上。
- 収束確認経路: `report.best` の結果に `report.multistart` を渡して §4.1 の証人を付ける。sidecar は
  best の gpx の隣に書く (engine は収束確認の結果を知らないので ② が書く)。
- 例外は送出しない。claims の構築に失敗したら `claims: null` と `warnings` に理由を載せ、`publishable_values: {}`
  (= 何も出版できない側に倒す)。

## 8. sidecar

- 置き場所: `Path(gpx_path).with_suffix(".claims.json")`。中身は `claims_version`・`gpx_sha256`・`policy`・
  `claims`・`judgment_requests`。
- 既に同名がある (keep_gpx での上書き実行など) → `<stem>.claims.<sha256 の先頭 12>.json` に書く (上書きしない)。
- 読み手 `read_claims_sidecar(gpx_path)` は候補の sidecar のうち `gpx_sha256` が現在の gpx と一致するものだけを
  返し、無ければ `None` (= 状態不明 → 出版不可)。

## 9. CSV と ③

- `claims.export.write_claims_csv(claims, path)`: 列は `key, class, phase, label, axis, value, esd, publishable,
  determinacy, provenance, scope, checks, gate`。**出版不可の行も書くが状態の列で示す** (値を消すと
  「無かった」と読まれる)。上書きしない。② ツール `export_claims_csv(gpx_path, path)` で露出する。
  出版状態は gpx の隣の sidecar (ハッシュ照合) から読み、**呼び手の渡した状態は受けない** (`gpx_path` は
  `auto_rietveld` の出力そのもの — §4.5 到達可能性)。
- ③ `skills/analyze`: 報告は `publishable_values` から書き、出版不可の値は `claims[k]` の `determinacy`・
  `gate`・`checks` を添えて「決まっていない/検査できなかった」と書く。`judgment_requests` を報告に載せる。
  ガードテストで手順書の記述を縛る。

## 10. 既知の限界

- 平文のフィールド (`refined_cells` 等) は互換のため残るので、② だけでは出版を強制できない。強制するのは
  CSV と ③ の手順書。
- 入力宣言 (内部標準・較正) の受け口は 1B。1A の格子は常に `scope = relative_within_sample`。
- `locally_stable` (±δ プローブ) と `undeterminable` (縮退方向の証人) は 1A では発行しない (型だけ用意する)。
- 結晶化学の閾値は経験則で、P1.5 で調整する。
- 格子の各軸は A0..A5 の全項に依存するとしている (Laue 群ごとの軸 → 項の対応を持たない)。どれか 1 項が
  剪定されると 6 軸すべてが `pruned` になり、相関の相手も 6 軸に広がる — 止めすぎる側 (安全側) の誤り。
- 収束確認の一致は既定の `AgreementTolerances` (k=3) で判定する (multistart の結果は許容幅を持たない)。
