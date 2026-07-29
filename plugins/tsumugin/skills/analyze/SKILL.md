---
name: analyze
description: 粉末回折 (X線/中性子) の全自動 Rietveld 解析を閉ループで進める。MCP 3 ツール (auto_rietveld / propose_next_actions / refine_with_revisions) を反復駆動し、SafeAction (背景/母数解放) は自律適用、ModelAction (データリミット/相追加削除/構造改訂/混合占有) は判断してユーザー承認を挟む。Rwp/GOF と物理妥当性でチュートリアル同等を目指す。
---

# tsumugin: Agentic Rietveld 解析 (③ 判断層)

あなた (Claude) が**判断者 ③** として、tsumugin の MCP 3 ツールを反復駆動し、フィット結果を
観測して次手を決め再実行する閉ループ解析を行う。ライブラリは決定論コア (①) と薄い MCP (②) を
提供し、**開放的判断 (R3) と構造改訂・事前知識 (R5) はあなたが担う**。

設計: `docs/design/m8-agentic-loop/architecture.md` / 手順詳細: M7 `AGENT_PLAYBOOK.md` §8。

## 使う MCP ツール (②)

| ツール | 役割 | 入出力 |
|---|---|---|
| `auto_rietveld` | 計器 (実行) | histograms/phases spec (JSON) → 段階別/最終 Rwp・格子・validity・**spec ハンドル**。任意で `stages` (追加段階, 下記) / `max_cyc` / **`search` (レシピ探索, 下記)** |
| `propose_next_actions` | 計器 (診断) | 直前結果 + 残差シグネチャ → `ActionProposal[]` (rationale/priority/**safe**) |
| `refine_with_revisions` | アクチュエータ | spec + あなたが決めた `AnalysisAction[]` → 改訂適用して再実行。`stages`/`max_cyc` も同様に渡せる |

閉ループ丸ごと (agentic_analyze) は MCP に**無い**。回すのはあなた。

## 手順

1. **入力を組み立てる** (AGENT_PLAYBOOK §1): データ/装置ファイルから `Radiation`・`Geometry`・
   `data_format` を判定し `HistogramSpec`/`PhaseSpec` の JSON を作る。CIF が無い相は
   `identify_phases` (元素一覧 → 単相ランキング) で候補構造を得る。
   - **相数が事前に分からない未知試料**は `identify_pattern` (M11 統一同定) を使う。1 相受理する
     ごとに残差からその寄与を減算し、**残差 S/N < 5σ になるまで**積み上げる (単相なら 1 相で停止、
     多相なら複数相)。`accepted[]` の各相の CIF/formula を `PhaseSpec` に配線して精密化へ進む
     (提案のみ・採否は ③)。外部形式の生データは手順 0 で `convert_pattern` して渡す。
2. **`auto_rietveld` を呼ぶ**。返る `specs` ハンドルを保持する。
3. **結果を読む**: `final_rwp`/`final_gof`、`validity.passed` と項目別 `checks`、`stages[*].reverted`。
   目標に届いていれば終了。
4. **`propose_next_actions` を呼ぶ** (残差シグネチャは結果と観測から見積もる)。各提案の `safe` を見る。
5. **次手を判断する** (権限境界):
   - **`safe=True` (SafeAction)** — 背景増項 `AdjustBackground` / 母数追加解放 `ReleaseParams` は
     採用してよい。適用後 Rwp が改善せず・validity を壊すなら**戻す** (過剰適合ガード)。
   - **`safe=False` (ModelAction)** — 下表の判断を要する手。**あなたが結晶学・化学の文脈で決め**、
     **構造改訂 (`ReviseStructure`)・相追加 (`AddPhase`) は必ずユーザー承認を挟む**。
6. **`refine_with_revisions`** に採った Action を渡して再実行。`specs` を持ち回り 3 へ戻る。
7. 目標 Rwp 到達 / 改善停滞 / 反復上限で終了し、最良結果と申し送り (未適用 ModelAction) を報告する。

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

各改訂は **Rwp 改善 ∧ `validity.passed` 維持** を満たすときのみ採用する。Rwp が下がっても
Uiso<0・占有率逸脱・格子逸脱を生む手は過剰適合として棄却する。データリミット変更は観測集合が
変わり Rwp 比較不能なので、別に妥当性で評価する。

## 失敗時 (AGENT_PLAYBOOK §6)

Rwp 停滞→構造/空間群を確認 (ReviseStructure 候補)、占有率発散→混合占有制約 (SetMixedOccupancy)、
座標段階でセル発散→特殊位置の座標解放を避ける、TOF/放射光の高止まり→データリミット、
未指数ピーク→相追加 (AddPhase, 相同定へ)。いずれも ModelAction はユーザー承認を挟む。

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

**単一のレシピは全データで勝てない。** 実測 (真の基準表 2026-07-29):

| データ | `default` | `serious` | チュートリアル |
|---|---|---|---|
| T1 fluoroapatite | **9.81%** | 10.45% | 10.38% |
| T2 garnet | 4.33% | 4.32% | 5.18% |
| T3 PbSO4 joint | 6.66% | **6.10%** | 6.71% |
| CaTeO3 | 12.20% | 12.19% | 9.40% |

段の順序を*当てる*ことはできない (試料変位段の配置 4 通り × 4 データで、どの配置でも 1 つ以上が
落ちた)。**候補を独立に実行して測り、規則で選ぶ**:

```json
{"search": true}
```

| いつ使うか | 指定 | 効果 |
|---|---|---|
| **単一フレームの本気解析** (既定の一手にしてよい) | `"search": true` | `default` / `serious` / `adaptive` を実行して最良を採る |
| 候補を絞りたい (時間/失敗した候補の除外) | `"search": ["default", "serious"]` | 指定した候補だけ |
| **探索で勝ったレシピで反復を続けたい** | `"search": ["serious"]` | そのレシピ 1 本で回す (② で既定レシピを置換する唯一の JSON 経路) |
| 同点や割れ方の判定を変えたい | `"search_config": {"rwp_tie_eps": 0.1, "disagreement_rwp_eps": 0.5}` | 同点近傍は **BIC** で裁定 / 僅差で答えが割れたら警告 |

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

## 段が「黙って壊れている」を疑う (`stability`)

**Rwp が改善したことは、その段が収束したことを意味しない。** GSAS は
`Maximum shift/esd = 258` を出しながら「改善した」段を通す (実測)。同様に、rwp が動かないのは
「効かなかった」のか「そもそも何も精密化していない」のかを Rwp からは区別できない。
`auto_rietveld`/`refine_with_revisions` の `stability` 引数で診断ゲートを有効にする:

```json
{"stability": {"require_convergence": true, "max_shift_esd": 1.0, "extra_cycles": 2,
               "detect_noop_stages": true, "prune_weak_vars": true, "record_correlations": true}}
```

| いつ使うか | キー | 効果 |
|---|---|---|
| 段が進むほど結果が不安定・後段が壊れる | `require_convergence` (+ `max_shift_esd`/`extra_cycles`) | 未収束段は**追加サイクルで回し直し**、駄目なら revert |
| ある段から Rwp が全く動かない (段列が死んでいる疑い) | `detect_noop_stages` | n_params 不変 + rwp/gof ビット同一の段を警告 (**revert はしない**) |
| 母数が多すぎて esd が発散している | `prune_weak_vars` | `esd >= 値` の変数を次段以降で凍結。座標シフト (`dAx/dAy/dAz`) は既定で除外 |
| 段の順序を疑っている / 何と何が縛られているか知りたい | `record_correlations` (+ `corr_threshold`) | \|r\|≥閾値 のペアを記録 (**検出のみ・自動凍結しない**) |

結果は `stages[*].note` (`unconverged` / `noop` / `pruned=N` / `extra_cycles=N`) に出る。
**既定 (未指定) は現行と完全に同一の挙動**なので、まず既定で回し、疑いが出てから足すこと。
未知のキーは黙って無視されず error dict になる (綴り間違いで「有効にしたつもり」にならない)。

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
{"stability": {"enable_restraints": true, "prune_weak_vars": true}}
```

- **`prune_weak_vars` との併用が必須** (単独指定は error dict)。拘束で実質的に母数が増えるため、
  esd 駆動の自動凍結を同時に置く。
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
