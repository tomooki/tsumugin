# 安定自動 Rietveld — 設計 (stable-auto-rietveld)

**要件**: `docs/spec/stable-auto-rietveld/requirements.md` /
**進捗**: `docs/tasks/stable-auto-rietveld/TASKS.md`

## 全体像

```
                    ┌──────────────────────────────┐
                    │ 0-2 共分散/Rvals 読み出し層   │  ← 全診断の唯一の情報源
                    │   Rvals / covMatrix /        │
                    │   varyList / sig             │
                    └───────────┬──────────────────┘
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
  ┌───────────────┐   ┌──────────────────┐   ┌────────────────┐
  │ WS-1 診断層    │   │ WS-2 拘束・境界   │   │ WS-3 レシピ規則 │
  │ 収束/no-op/    │   │ 箱拘束(装置のみ) │   │ 相関群/凍結/    │
  │ esd/相関       │   │ restraint 有効化 │   │ 元素展開       │
  └───────┬───────┘   └────────┬─────────┘   └───────┬────────┘
          └────────────┬───────┴──────────────────────┘
                       ▼
              ┌─────────────────┐      ┌────────────────────┐
              │ Phase2 探索      │      │ WS-4 データ前処理   │
              │ レシピ多重実行   │      │ 背景/レンジ/LeBail │
              └─────────────────┘      └────────────────────┘
                       │
                       ▼
              0-1 並列ベンチマークハーネス (全段階の検証基盤)
```

## モジュール配置

| ファイル | 役割 | 新規/変更 |
|---|---|---|
| `autorietveld/diagnostics.py` | **共分散/Rvals 読み出し層** (REQ-SAR-105)。gpx → `{max_shift_esd, varyList, sig, corr_pairs, weak_vars}`。GSAS 遅延 import・返すのは素の float/list | 新規 |
| `autorietveld/engine.py` | 段の受理判定に収束/no-op を追加、凍結 (`freeze_others`)、元素ランク展開、箱拘束、restraint スタブ | 変更 |
| `autorietveld/bounds.py` | **箱拘束の展開と境界到達の検出** (REQ-SAR-201/202)。装置・幾何のみ。numpy-only | 新規 |
| `autorietveld/restraint_dlg.py` | **restraint を χ² に入れる `dlg` スタブ** (REQ-SAR-203)。GSAS 非依存の duck-typed オブジェクト | 新規 |
| `autorietveld/recipe.py` | 相関群の不変条件、`build_serious_recipe`、Le Bail 前段 | 変更 |
| `autorietveld/search.py` | レシピ候補の多重実行と選択 (REQ-SAR-500/501) | 新規 |
| `autorietveld/autorange.py` | データレンジ/背景項数/除外領域の自動決定 (REQ-SAR-401/402/403) | 新規 |
| `mcp/rietveld_tools.py` | ↑の ② 露出 `propose_data_preprocessing` (★不変条件。`search` の adaptive 候補経由でしか到達できないと ③ から**名指しで呼べない** = M10 anchor の再演) | 変更 |
| `tools/bench_recipes.py` (または `scripts/`) | **並列ベンチマークハーネス** | 新規 |

## 設計判断

### D1. 診断は「共分散を読む 1 箇所」に集約する

収束判定 (REQ-SAR-101)・esd プルーニング (103)・相関検出 (104) は**どれも同じ情報源**
(`gpx.data["Covariance"]["data"]`) を必要とする。3 箇所で別々に掘ると drift するので、
`diagnostics.py` を唯一の読み出し口にする。既存の `engine._nobs` も将来ここへ寄せる。

**返す型は素の Python/numpy スカラ**にし、GSAS のデータ構造を外へ漏らさない
(② MCP へ載せるときにそのまま JSON 化できる)。

### D2. 相関群は「初期知識 + 実測補正」の二段構え

- **静的 (REQ-SAR-301)**: {U,V,W} 等の既知の物理的結合はレシピ生成側で分割禁止にする。
  これは*知っている*相関を確実に防ぐ。
- **動的 (REQ-SAR-104)**: 共分散から測った |r|>閾値 のペアは、データ固有の相関
  (格子×変位、Uiso×背景、多相の分率同士) を捕まえる。

静的だけでは未知の相関を防げず、動的だけでは「最初の 1 回」を守れない。両方要る。

### D3. 箱拘束の適用範囲 (P-SAR-1) — 構造パラメータには張らない

| 張る | 張らない |
|---|---|
| 格子 (初期値 ±X%)、Shift/DisplaceX,Y、Size/Mustrain の正値性 | 占有率・Uiso・座標 |

実装: `autorietveld/bounds.py` (GSAS 非依存の純関数) + `engine._plan_box_bounds` /
`_apply_box_bounds` / `_frozen_variables`。設定は `StabilityOptions.bound_cell` /
`bound_displacement` / `bound_size_strain` (いずれも既定無効)。
**構造パラメータ用のフィールドは意図的に存在させない** — `tests/autorietveld/test_bounds.py`
の `test_no_option_exists_for_boxing_structural_parameters` と、実配線側の
`test_box_bounds_gsas.py::test_registered_bounds_never_touch_structural_parameters`
(`Afrac`/`AUiso`/`dAx` が箱に載っていないこと) が恒久ガードになっている。

**GSAS の箱は最適化中の制約ではない**: `GSASIIstrMain.dropOOBvars` が精密化の**後**に
「範囲外なら境界へ丸めて `Controls['parmFrozen']` へ追加」する事後処理である。よって

* 拘束は発散を*防ぐ*のではなく*止める* (1 サイクルは外へ出る)、
* 境界に到達した変数は `parmFrozen` に載る → **これが REQ-SAR-202 の検出源**。

救済プルーニング/最終研磨 (REQ-SAR-103) も同じ `parmFrozen` へ書くため、検出は
**(a) 箱を張った変数に限定** し **(b) 精密化呼び出しの前後という狭い窓で差を取る**。
どちら側の境界かは covData に残る**丸められる前の値**から決める (推測しない)。

実測 (2026-07-29, T1):

| 設定 | Rwp | 境界到達 |
|---|---|---|
| 既定 (箱なし) | 9.80617% | — |
| `bound_cell=0.2` + `bound_displacement=5000` + `bound_size_strain` | 9.80617% (ビット同一) | なし |
| `bound_cell=1e-4` | 9.80617% (ビット同一) | なし |
| `bound_cell=1e-5` | 9.61768% | `0::A0` (min) |
| `bound_cell=1e-6` | 9.75674% | `0::A0`, `0::A2` (min) |
| `bound_displacement=1.0` (µm) | 11.18520% | `:0:Shift` (max) |

= **緩い箱は結果をビット同一に保ち、締めた箱は実際に効いて所見が出る**。

構造パラメータの逸脱は**モデル誤りの証拠**であり、握り潰すと NaCuHCF の model5/model6 判別
(占有率が Na>1/O<0 に発散したことが Ow 必要性の決め手) のような推論ができなくなる。

代わりに REQ-SAR-202 で「境界到達を所見として報告」する経路を持つ。数値上限を置く場合も
**物理的必要値を十分上回る**値にする (低 cap は境界不安定 = 偽の「改善せず」を作る)。

### D3-a. 弱い変数は「観測 → 報告 → (判断としての) 凍結」に分ける (REQ-SAR-103)

**当初の実装は「受理された段のたびに `esd >= |値|` を永続凍結」だった。これは誤りである。**
理由と正しいタイミングは requirements.md の REQ-SAR-103 詳細表にあり、ここには**実装の分界**を書く。

| タイミング | 実装 | ledger |
|---|---|---|
| 各段 (観測) | `record_weak_vars` → 記録のみ。**凍結しない** | `m7_stage_weak_vars` |
| 救済 (判断) | `_needs_rescue` (`SVD0>0` or 未収束) → `_run_rescue_freezes` が最弱から凍結して再試行 | `m7_stage_rescue` |
| 最終 (報告) | `needs_final_diagnostics` → `split_weak_variables` → `AutoRietveldResult.undetermined_parameters` | `m7_undetermined` |
| 最終研磨 (opt-in) | `_run_final_polish` → 凍結 → 1 回精密化 → 段列末尾に `final polish` 段 + `FinalPolish` | `m7_final_polish` |
| 毎段凍結 (opt-in) | `prune_weak_vars_each_stage` (旧既定挙動。逃げ道として残置) | `m7_stage_prune` |

**順序が意味を持つ**: 追加サイクル (`_run_convergence_cycles`, 母数はそのまま反復を増やす) を
**先に**尽くし、それでも収束しない/特異なときに初めて救済 (母数を削る) へ進む。逆にすると
「収束が遅いだけのパラメータ」を決定不能と誤断して捨てる。

**救済凍結は revert と一緒に巻き戻る**: 凍結先の `Controls['parmFrozen']` は gpx ツリーの一部
なので、段のスナップショット復元で消える。engine 側の追跡集合 (`frozen_vars`) からも同時に外す
(追跡だけ残ると、実際は解放されている変数が以降の候補から永久に消える)。

**研磨は破綻だけを revert する**: 凍結は自由度を減らすので Rwp は普通わずかに悪化する。それを
revert 条件にすると研磨は決して適用されない。破棄するのは GSAS の失敗・非有限 Rwp・格子崩壊/
プロファイル非物理だけで、コストは `FinalPolish.rwp_before/rwp_after` の差として見せる。

### D4. restraint 有効化は既定 OFF・「決まらなかったパラメータの報告」とセット

`G2strMain.Refine(gpx, dlg=<stub>)` で penalty が χ² に入る。実装は
`autorietveld/restraint_dlg.py` (スタブ) + `engine._capture_refine_status(dlg=…)` (既に
`Refine` を包んでいるパッチ点へキーワードで挿し込む)。有効化は
`StabilityOptions.enable_restraints` (**既定 OFF**)。

スタブの要件 (ソースから確定):

| メンバ | 呼び出し | 要件 |
|---|---|---|
| `Update(value, newmsg=...)` | `errRefine`:5016-5023 / `strMain`:210 | **タプル `(True, '')` を返す** (両方の消費形を満たす) |
| `SetRange(n)` | `strMain`:207 | no-op でよい |
| `SetHistogram` | `errRefine`:4973 | `hasattr` ガードあり → **実装しない** |

型名に `"G2"` を含めないこと (`errRefine`:5015 で分岐する)。

#### D4-a. 対照実験 (2026-07-29 実測) — **拘束は実際に χ² に入るようになった**

PbSO4 実データ・S–O 距離ターゲット 1.9 / 2.3 Å (weight 1e5)。同一データ・同一拘束で
`enable_restraints` だけを切り替えた:

| | target 1.9 | target 2.3 | 判定 |
|---|---|---|---|
| 既定 (dlg なし) 最終 S–O2 | 1.411132 Å | 1.411132 Å | **ビット同一** = target-invariant |
| 既定 (dlg なし) Rwp | 40.34906 | 40.34906 | ビット同一 |
| 既定 (dlg なし) `RestraintSum` | 4.66e9 | 3.69e9 | 下がらない (最小化されていない) |
| **スタブ経路** 最終 S–O2 | 1.411132 Å | **1.542264 Å** | ターゲット依存 = 追従している |
| **スタブ経路** `RestraintSum` | 4.66e9 (段が revert) | **0.0876** | **10 桁の低下** = 最小化されている |

ChemComp でも同じ結論が別の指標で出る: 同一拘束 (Pb 占有 total 3.2, weight 1e4) で
Rwp が 40.34906 → **1022.16** に変わる。`Rw = √(ΣM²/SumwYo)` なので、penalty が残差ベクトル
M に連結された以外に Rwp が桁で動く説明が無い。

**⚠ 副産物: 有効化すると Rwp が penalty 込みの値になる。** tsumugin の段の受理/revert は Rwp
比較なので、拘束の重みが過大だと全段が「悪化」判定で revert される (実測: bond weight 1e5 で
Rwp 3558)。→ **D4-c で解決** (呼び手への注意事項ではなく、engine の判定を直した)。

#### D4-c. データ項 Rwp と penalty の分離 (REQ-SAR-205)

**判定を penalty 込みの Rwp で行うのは誤りである。** 拘束は「モデルを引く力」であって
「データへの合わなさ」ではないので、penalty の増減で段を revert してはならない。

分離は**復元可能**である。`Rwp = 100·√(chisq/sumwYo)` の分母 `sumwYo` は観測強度だけから
積まれ (`GSASIIstrMath`:5003-5004/5183)、`chisq` にだけ penalty が入る
(`GSASIIstrMain`:359 の `Σfvec²`、`RestraintSum` は :364) ので、分母を知らなくても

    Rwp_data = Rwp · √(1 − RestraintSum / chisq)

で割れる。実装:

| 層 | 場所 | 役割 |
|---|---|---|
| 純関数 | `diagnostics.data_term_rwp` | 上式 + 縮退規則。GSAS 非依存 |
| 読み出し | `RefinementDiagnostics.rwp/.chisq/.data_rwp` | REQ-SAR-105 の 1 箇所から材料を出す |
| engine | `_data_rwp(gpx, rwp, split=)` | `enable_restraints` が真のときだけ分離。偽なら `Rvals` を**1 度も読まない** |
| 報告 | `StageResult.rwp` / `AutoRietveldResult.final_rwp` | **常にデータ項** |
| 報告 (生値) | `*.rwp_penalized` / `final_restraint_penalty` | penalty 込みの値は別キー |

**縮退規則が要点**: `RestraintSum >= chisq` なら**引かない**。GSAS は `RestraintSum` を
`dlg` ゲートの**外**で報告するので、`dlg` を渡していない精密化でも巨大な値が載る
(実測 4.66e9)。フラグを見ずに引くと負の chisq を作る上、拘束を登録しただけの既定経路で
値が変わってしまう。**`split` フラグと縮退規則の二重の歯止め**を置いている。

**GOF は意図的に分離しない。** 拘束付き精密化の GOF は拘束項を観測と自由度の双方に数えるのが
慣行で、GSAS の式 (`√(χ²/(Nobs+RestraintTerms−Nvars))`) はそのとおり書かれている。加えて
penalty 込みで残すと**拘束がデータと争っている状態が値に現れる** (実測: `final_rwp` 33.07 に
対し `final_gof` 1641.8) — データ項 Rwp だけでは見えない警報なので潰さない。

#### D4-b. 副作用計測 — **「自動パラメータ削除+再試行を失う」は既定 deriv type には当てはまらない**

当初の懸念は `GSASIIstrMain`:430 の `if dlg: break` だったが、ソースを読むと:

* 「1 個消して再試行」ループは `'Hessian' not in Controls['deriv type']` の **else 分岐だけ**
  (`GSASIIstrMain`:431-438)。
* 既定 `analytic Hessian` では `result[1] is None` が :326-329 で**先に break** するので、
  `if dlg: break` を含む except 節に到達しない (= その行はこの経路では死んでいる)。
* 弱い/特異な変数を落として続ける処理は `GSASIImath.HessianLSQ` の `dropTerms` にあり、
  **dlg を参照しない**。

実測 (2026-07-29):

| 実験 | dlg なし | dlg スタブ |
|---|---|---|
| 完全縮退 (同一構造 2 相の相分率和=1) | `1 Parameter(s) dropped: ::constr0` / Rwp 40.34906 / 分率 0.5,0.5 | **完全に同一** |
| 真の特異行列 (`HessianLSQ` に cov=None を強制注入) | `HessianLSQ` 1 回/精密化 → 失敗 → chi2=inf → revert | **完全に同一** |

→ **失うものは無い。** それでも既定 OFF を維持する理由は D4-a の副産物 (Rwp の意味が変わる)
と、拘束で母数が実質増えることの 2 点であり、「GSAS の自動削除を失うから」ではない。

⚠ **この実測は「毎段プルーニング必須」の根拠そのものを崩している** (2026-07-29 改訂)。
併用必須 (`StabilityOptions.__post_init__`) は残すが、**要求するのは `report_undetermined`
(見ること) だけ**に落とした — 拘束下で毎段凍結すると母数が不可逆に痩せる実害
(実測 `n_params` S2 で 7 → 3) の方が大きい。D3-a を参照。
恒久ガードは `tests/autorietveld/test_restraint_dlg_gsas.py` (deriv type の前提ごと固定)。

### D5. 元素ランク展開は engine 側 (レシピは宣言的に保つ)

`build_recipe` は GSAS 非依存の純関数なので、CIF を読めず**実際の元素数を知らない**。
現在の実験実装は「重い方から 6 番目まで」を決め打ちし、実元素数を超えた段が no-op として残る
(T1 で 59 段中の相当数)。

→ レシピは `coords: "heavy_first"` と**宣言**し、engine が適用時に実際の元素で展開する。
段数がデータに適応し、ledger も読めるようになる。

### D6. 探索は「収束したものの中で最良」

REQ-SAR-500 の選択規則は **Rwp 単独ではない**:

1. 収束判定 (REQ-SAR-101) を満たす候補だけを対象にする
2. その中で Rwp/GOF が最良のものを採る
3. 物理妥当性 (`check_validity`) が fail するものは所見付きで降格する

「収束していない best」を選ばないことが要点。相数の比較で Rwp を使わない既存の規律
(`insitu.anchor.select.frame_bic`) と同じ発想を、レシピ選択にも適用する。

### D7. ベンチマークハーネスを最初に作る

改善のたびに 6 データ × 複数レシピを回す。今回の調査では 1 件ずつ直列に回して膨大な待ちを
作った (T3 単発で 329 秒、T4 は 10 分超)。**別プロセス並列 + 比較表出力**のハーネスを先に
作れば、以降すべての検証が同じ土俵に乗る。

出力は `docs/benchmark/stable-auto-rietveld/<日付>.md` に残し、**各改善を単独で測る**
(合成すると原因の切り分けができない — 今回 U,V,W の件を特定できたのは 1 変数ずつ測ったから)。

## ベンチマークデータ

| 名前 | 内容 | 現行 Rwp | 位置づけ |
|---|---|---|---|
| T1 fluoroapatite | 単相ラボ X 線 | 9.83% | 基本形 |
| T2 garnet | 単相 CW 中性子 + 混合占有 | 4.33% | 占有率・コントラスト |
| T3 PbSO4 | X 線 + CW 中性子 joint | 6.66% | **順序変更で最も壊れた** |
| T4 NAC+CaF2 | 多相 + TOF + 放射光 | ~12.8% | **多相・唯一の TOF** |
| CaTeO3 frame030 | Kα1 単色ラボ X 線 | 12.43% | 変位が大きい (Shift −274 µm) |
| NaCuHCF | SXRD + ND joint, 重水 | XRD 4.84% / ND ~12% | 複雑系・model 選択 |

## 既知のリスク

| リスク | 対処 |
|---|---|
| 探索の導入で実行時間が線形に増える | operando は既定オフ (REQ-SAR-502)。ハーネスで並列化 |
| ~~restraint 有効化で自動プルーニングを失う~~ | **前提が誤りだった** (D4-b の実測)。代わりに「決まらなかったパラメータの報告」を必須にする (D3-a) |
| 自動凍結が母数を不可逆に痩せさせる | D3-a (凍結は最終研磨と救済のみ。各段は観測に留める) |
| 箱拘束が診断信号を潰す | D3 (構造パラメータには張らない) |
| 改善の合成で原因が追えなくなる | D7 (単独測定) |
| 決定論が壊れる | 候補列挙・実行順・選択をすべて seed 固定 (NFR-102) |
