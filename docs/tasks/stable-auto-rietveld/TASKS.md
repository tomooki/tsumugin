# 安定自動 Rietveld — 進捗追跡 (stable-auto-rietveld)

**要件**: `docs/spec/stable-auto-rietveld/requirements.md` /
**設計**: `docs/design/stable-auto-rietveld/architecture.md`
**ブランチ**: `feat/stable-auto-rietveld` (worktree `../tsumugin-stageorder`)

状態記号: ⬜ 未着手 / 🔄 進行中 / ✅ 完了 / ⏸ 保留 / ❌ 中止

---

## 現在の状況

**Phase 0 / Phase 1 完了 (WS-1・WS-2 済)、Phase 2 設計確定**。残るは WS-3 の一部と Phase 2 実装。
WS-2 (拘束・境界) は 2026-07-29 に branch `feat/sar-constraints` で完了 — 実測値は下記。

| 前提 | 状態 |
|---|---|
| 他 worktree (delta 受理タスク) のマージ | ✅ 完了 (main は `1ca11b7`、CI 導入済み) |
| T4 の測定 | ✅ 完了 (単独 14.53% / 累積 14.58%、**どちらも既定 ~12.8% より悪い**) |

---

## Phase 0 — 土台 (直列)

| # | タスク | 要件 | 状態 | 備考 |
|---|---|---|---|---|
| 0-1 | ✅ **並列ベンチマークハーネス** — 6 データ × レシピ変種を別プロセス同時実行し比較表を出力 | D7 | ⬜ | 以降の全検証の基盤。最優先 |
| 0-2 | ✅ **共分散/Rvals 読み出し層** `autorietveld/diagnostics.py` | REQ-SAR-105 | ⬜ | WS-1 全体の前提 |
| 0-3 | ~~T4 再測定~~ | F3 の空欄を埋める | ✅ | 単独 14.53% / 累積 14.58%。**どちらも既定より悪い** (下記) |

**Phase 0 完了条件**: ハーネスで 6 データの現行値を一括再現し、`docs/benchmark/stable-auto-rietveld/` に基準表を残す。

---

## Phase 1 — 4 ワークストリーム (並列)

### WS-1 診断層 (0-2 に依存)

| # | タスク | 要件 | 状態 |
|---|---|---|---|
| 1-1 ✅ | `Rvals['Max shft/sig']` による**収束判定**を段の受理条件に追加 | REQ-SAR-101 | ✅ |
| 1-2 ✅ | 未収束段の**追加サイクル再実行** → それでも駄目なら revert | REQ-SAR-101 | ✅ |
| 1-3 ✅ | **no-op 段の検出** (n_params 不変 + rwp/gof ビット同一 → 警告) | REQ-SAR-102 | ✅ |
| 1-4 ✅ | **esd > \|値\| の自動プルーニング** + ledger 記録 | REQ-SAR-103 | ✅ |
| 1-5 ✅ | **高相関ペア検出** (\|r\|>閾値) → 記録のみ (自動凍結は Phase 2) | REQ-SAR-104 | ✅ |
| 1-6 | ②`auto_rietveld`/`refine_with_revisions` の `stability` spec + ③ `analyze` skill 節 | ★不変条件 | ✅ |

**実装** (2026-07-29): `run_auto_rietveld(stability=StabilityOptions(...))` で **opt-in**。
既定 (`None`) は共分散を 1 度も読まず現行と完全に同一 (gated テスト
`test_default_run_emits_no_stability_entries` が `read_diagnostics` を爆発させて固定)。
判断ロジックは `engine._run_convergence_cycles` / `_is_noop_stage` / `_prune_candidates` /
`_freeze_variables` に純関数として切り出し `-m "not gsas"` で回る。凍結は GSAS の
`parmFrozen`(`set_Frozen`) = 値を動かさず varyList から外すだけ。ledger kind 4 種
(`m7_stage_unconverged`/`_noop`/`_prune`/`_correlation`) を GUI (`workbench.session`) にも配線。

**WS-1 で判明した事実**:

- **`diagnostics.py` は実 GSAS データで例外を投げていた** — covData の `variables`/`sig` は
  numpy 配列で、`value or []` が truth-value ambiguous を起こす。段階ループの except が拾って
  **全段が chi2=inf → revert** されていた (T1 実測)。`_as_sequence` で修正済み。
  *診断が精密化本体を殺す形*なので、以後 numpy 配列形状のテストを必ず置くこと。
- **T1 の "成功している" 段は shift/esd 基準では収束していない** (max shft/sig = 86 / 116 / 47,
  max_cyc=3)。S1/S2 は GSAS 自身の `converged` も False。REQ-SAR-101 の動機は T1 でも成立する。
- **`Max shft/sig` は `np.max(Lastshft/sig)` で絶対値ではない** (`GSASIIstrMain:402`)。
  強い**負**シフトは小さい値として通る = 収束判定は片側にしか効かない (上流の仕様)。
- **座標シフト `dAx/dAy/dAz` は esd プルーニングの確実な偽陽性** — 収束するほど値が 0 に近づき
  `esd/|値|` が必ず 1 を超える。除外しないと T1 で座標 5 個が凍った (既定で除外)。
- **T1 のプロファイル段の実測相関は `V×W` r=-0.959 / `U×V` r=-0.955** = WS-3 が静的に禁止して
  いる Caglioti 群そのもの。動的検出が静的知識を裏付けた (D2 の二段構えが機能している)。

### WS-2 拘束・境界

| # | タスク | 要件 | 状態 |
|---|---|---|---|
| 2-1 | **箱拘束 (装置・幾何のみ)** — 格子 ±X% / 変位 / Size・Mustrain 正値 | REQ-SAR-201 | ✅ |
| 2-2 | **境界到達の検出と報告** (握り潰さない) | REQ-SAR-202 | ✅ |
| 2-3 | restraint `dlg` スタブの**対照実験** (拘束あり/なしで最終値が変わるか) | REQ-SAR-204 | ✅ |
| 2-4 | `if dlg: break` の**副作用計測** | D4 | ✅ |
| 2-5 | `TestBondRestraintHeadlessCanary` を**意味反転して書き直す** | REQ-SAR-204 | ✅ |
| 2-6 | restraint 有効化 (**既定 OFF**, 1-4 完了が前提) | REQ-SAR-203 | ✅ |
| 2-7 | **データ項 Rwp と penalty の分離** — 段の受理判定・報告値をデータ項で行う | REQ-SAR-205 | ✅ |

**実装** (2026-07-29, branch `feat/sar-constraints`):
`autorietveld/bounds.py` (箱の展開 + 境界検出, numpy-only) / `autorietveld/restraint_dlg.py`
(`RefineProgressStub`) / `StabilityOptions` に `bound_cell` `bound_displacement`
`bound_size_strain` `min|max_size` `min|max_mustrain` `enable_restraints` を追加 (**全て既定
無効 = 現行と完全に同一**)。engine は `_plan_box_bounds` / `_apply_box_bounds` /
`_frozen_variables` と、既存の `_capture_refine_status` へ `dlg=` 注入。ledger kind 2 種
(`m7_box_bounds` / `m7_stage_bound_hit`) + note `bound_hits=N`。② は `auto_rietveld` /
`refine_with_revisions` の既存 `stability` spec に同居、③ は `skills/analyze` に 2 節追加。

**WS-2 で判明した事実 (実測)**:

- **箱は最適化中の制約ではない** — `dropOOBvars` は精密化**後**に「境界へ丸めて `parmFrozen`
  へ追加」する事後処理。よって拘束は発散を*防がず*止める。逆に、その `parmFrozen` が
  REQ-SAR-202 の検出源になる。**esd プルーニングも同じリストへ書く**ので、検出は「箱を張った
  変数」に限定し、精密化呼び出しの前後という狭い窓で差を取る必要がある。
- **T1 実測**: 緩い箱 (±20% / 5000 µm / 正値性) は Rwp 9.80617% を**ビット同一**に保つ。
  `bound_cell=1e-5` で `0::A0` が境界到達 (Rwp 9.618%)、`bound_displacement=1 µm` で
  `:0:Shift` が境界到達 (Rwp 11.185%) = **締めれば実際に効く**。
- **★ restraint は `dlg` スタブで本当に χ² に入る** (PbSO4 対照実験): 既定経路はターゲット
  1.9/2.3 で S–O2 が**ビット同一** (1.411132) なのに対し、スタブ経路では 1.411132 vs
  **1.542264** とターゲット追従し、`RestraintSum` が **3.69e9 → 0.0876 (10 桁低下)**。
  ChemComp では Rwp が 40.349 → **1022.16** = penalty が残差ベクトルへ連結された直接証拠。
- **⚠ 有効化すると Rwp が penalty 込みの値になる** → 段の受理/revert (Rwp 比較) の意味が変わる。
  重みが過大だと全段 revert (bond weight 1e5 で Rwp 3558)。→ **2-7 で解決** (下記)。

**2-7 で判明した事実 (2026-07-29, branch `feat/sar-rwp-split`)**:

- **penalty 込みの Rwp で判定していた間、段列は「データへの適合」を一切見ていなかった。**
  PbSO4 で S–O ターゲットを 2.3 Å に誤設定 + weight 1e5、同一 3 段レシピの実測:

  | 段 | 分離前 (penalty 込みで判定) | 分離後 (データ項で判定) |
  |---|---|---|
  | S1 scale+bg | 8127.50 | 40.35 |
  | S2 cell | 8127.48 | **35.43** |
  | S3 coords | 8127.48 (**revert**) | **33.07** (受理) |

  S2 の「改善」は penalty が 0.02 減っただけで、**データ項が 4.9 点良くなった事実は Rwp に
  現れていなかった**。S3 は penalty が増えたので revert されたが、データ項では 2.4 点改善して
  いる = **正しい段を捨てていた**。最終報告値も 8127.48 という「Rwp ではない数」だった。
- **分離は sumwYo を知らなくてもできる** — `Rwp_data = Rwp·√(1−RestraintSum/chisq)`。
  分母 `sumwYo` は観測強度のみから積まれる (`GSASIIstrMath`:5003-5004/5183) ため共通で消える。
- **★ `RestraintSum >= chisq` なら引いてはならない** — GSAS は `RestraintSum` を `dlg` ゲートの
  **外**で報告するので、`dlg` を渡していない精密化でも巨大な値が載る (実測 4.66e9)。
  フラグ (`split`) と縮退規則の**二重の歯止め**を置いた。片方だけだと、拘束を登録しただけの
  既定経路 (`enable_restraints=False` + `bond_restraints` あり) で値が静かに変わる。
- **GOF は意図的に分離しない** (慣行どおり penalty 込み)。**拘束がデータと争う状態の唯一の警報**
  だから — 実測で `final_rwp` 33.07 に対し `final_gof` 1641.8。Rwp だけ見て「拘束は無害」と
  読まないよう skill にも明記した。
- 非回帰: T1 `9.80617260074067` / 段列 7 値すべて **baseline とビット同一** (`git stash` で
  分離前コードを同じスクリプトに掛けて照合)。ベンチも T1 9.806% / T3 6.660% を再現。
- **★ D4 の「特異行列時の自動パラメータ削除+再試行を失う」は既定 deriv type には当てはまらない**。
  削除+再試行は `'Hessian' not in deriv type` の else 分岐にしかなく、既定 `analytic Hessian`
  では `result[1] is None` が先に break するので `if dlg: break` に到達しない。弱い変数のドロップは
  `HessianLSQ.dropTerms` にあり dlg を見ない。**実測でも完全縮退 (同一構造 2 相) / 真の特異行列
  (cov=None 強制注入) の双方で dlg の有無が結果をビット同一に保った**。
  → 既定 OFF を維持する理由は「Rwp の意味が変わる」+「母数が実質増える」であって、
  当初の理由 (GSAS の自動削除を失う) ではない。`prune_weak_vars` 併用必須は前者の理由で残す。

### WS-3 レシピ規則

| # | タスク | 要件 | 状態 |
|---|---|---|---|
| 3-1 ✅ | **相関群の分割禁止**を不変条件化 + 変異テスト | REQ-SAR-301 | ⬜ |
| 3-2 ✅ | **凍結 (`freeze_others`)** の本実装 + 累積セマンティクスの非回帰 | REQ-SAR-302 | ⬜ (実験実装あり) |
| 3-3 🔄 | **元素ランク展開を engine 側へ** (no-op 段の一掃) | REQ-SAR-303 | ⬜ |
| 3-4 ⏸ | 周回入口で**最良状態へ戻す** | REQ-SAR-304 | ⬜ |
| 3-5 ✅ | **Uiso 等値の段階的緩和** (全原子 → 元素ごと → 個別) | REQ-SAR-305 | ⬜ |

### WS-4 データ前処理の自動化

| # | タスク | 要件 | 状態 |
|---|---|---|---|
| 4-1 ✅ | **背景項数エスカレーション** (6→12→24, revert ガードで停止) | REQ-SAR-401 | ⬜ |
| 4-2 ✅ | **データレンジ自動決定** (ノイズ支配域の検出) | REQ-SAR-402 | ⬜ |
| 4-3 ✅ | **除外領域の提案** (自動適用禁止) | REQ-SAR-403 | ⬜ |
| 4-4 ⏸ | **Le Bail 基準線** (格子固定・プロファイル+背景のみ) | REQ-SAR-404 | ⬜ |

---

## Phase 2 — 探索 (WS-1 / WS-3 完了後)

| # | タスク | 要件 | 状態 |
|---|---|---|---|
| 5-1 | **レシピ候補の多重実行** + 「収束したものの中で最良」選択 | REQ-SAR-500 / D6 | ✅ |
| 5-2 | 候補間の**不一致を警告として出す** (順序依存 = 信頼度低) | REQ-SAR-501 | ✅ |
| 5-3 | **operando は軽量レシピ既定を維持** (非回帰確認) | REQ-SAR-502 | ✅ |
| 5-4 | 決定論 (seed 固定でビット同一) の確認 | P-SAR-4 / NFR-102 | ✅ |
| 5-5 | ② `auto_rietveld(search=, search_config=)` + ③ `analyze` skill 節 | ★不変条件 | ✅ |

**実装** (2026-07-29, branch `feat/sar-search`): `autorietveld/search.py` (numpy-only, GSAS は
`run_auto_rietveld` の遅延 import 越し)。`RecipeCandidate` / `CandidateOutcome` /
`RecipeSearchResult` / `run_recipe_search`。**`run_auto_rietveld` は無変更** (候補 1 つの実行に
使うだけ)。ledger kind 2 種 (`m7_search_candidate` / `m7_search_select`) を GUI
(`workbench.session`) にも配線 (select は **GUARD** — 信頼度の所見を運ぶため)。

### 収束フィルタの実装 — tier + フォールバック (設計判断)

WS-1 が「T1 の成功している段も shift/esd 基準では未収束」を実測しているため、収束フィルタを
字義どおり実装すると**全候補が落ちる**。採った形は **tier (層) による順位付け**:

| tier | 条件 | 意味 |
|---|---|---|
| 0 | 収束 ∧ 妥当 | 採用したい層 |
| 1 | 収束 ∧ 妥当性 fail | 妥当性は**降格**なので収束層の中で下位 |
| 2/3 | 未収束 | 収束層が空のときだけ到達 (`convergence_fallback=True` + 警告) |
| 4 | 実行失敗 | 順位表に残すが選ばれない |

収束候補が 1 つでもあれば tier 0/1 で決着するので「未収束を落とすフィルタ」と厳密に同値。
全滅時だけフォールバックする。**閾値は緩めていない** — 判定材料は GSAS 自身の
`Rvals['converged']` であり、`Max shft/sig` は絶対値でない (片側にしか効かない) ので、
こちらで閾値を動かしても「収束した」の意味は良くならない。収束判定は**最後に受理された段**
(revert された段は巻き戻されている) から読み、`stability.require_convergence` を有効にした
ときは engine が note に書く `unconverged` (shift/esd 由来の厳しい判定) を優先する。

### ★ 実測で発覚した構造的バイアス — 観測集合を跨いだ Rwp/BIC 比較

T1 の初回実測で **適応候補 (レンジ 19.32–130° に自動切り詰め) が既知最良の `default` に
BIC で勝った** (17875 → 16785、Rwp 差はわずか 0.019)。原因は χ² = GOF²·(n_obs − n_params) が
**観測点数に比例する**こと — つまり**データを捨てた候補ほど BIC が下がる**。Rwp も同じ理由で
観測集合を跨いでは比較できない (③ の受理基準にも「データリミット変更は Rwp 比較不能」とある)。

対処: 順位キーに**観測集合**を入れ、基準 (列挙順で最初に結果を返した候補 = `default`) と
点数が違う候補は **Rwp/BIC では上に来られない**ようにした。勝てるのは tier (収束・妥当性)
だけである。これは適応レンジ本来の動機と一致する — T4 の非収束はレンジ未設定が主因なので、
レンジを切った候補は「**収束する**」ことで勝つべきで「点数が減って χ² が小さい」ことで
勝つべきではない。

### 実データ検証 (検証計画 1)

| データ | default | serious | adaptive | 探索の選択 | 既知最良 |
|---|---|---|---|---|---|
| T1 | **9.806** (収束∧妥当) | 10.452 | 9.825 (レンジ 19.32–130°, n_obs 5535) | **default** (`rwp`) | default 9.81 ✅ |
| T3 | 6.660 (**未収束**∧妥当) | **6.100** (収束∧妥当) | 6.461 (n_obs 7542) | **serious** | serious 6.10 ✅ |

- T3 で **`default` は GSAS 自身の `converged=False`** だった = 収束 tier が実データで実際に効く。
- T3 で **順序依存の警告が発火**: `serious` と `adaptive` は Rwp 差 0.361 と僅差なのに格子が
  0.16% 違う (PbSO4 a 8.4739 vs 8.4875 / b 5.3941 vs 5.4028)。REQ-SAR-501 が実データで機能。
- T4 は 1 回 ~3 時間のため本タスクでは未実行 (`--with-slow` で節目に測る)。

---

## T4 実測記録 (2026-07-28, 本気フィット 両版)

```
単独版: Rwp=14.5252 GOF=5.5698 60 段 / 21 revert (10120s = 2.8h)
累積版: Rwp=14.5812 GOF=5.5913 60 段 / 22 revert (10401s = 2.9h)
```

**⚠ どちらも既定レシピ (~12.8%) より悪い。累積版でも改善しなかった** — CaTeO3 の
18.07%→12.19% から「T4 も累積版で改善するだろう」と予測したが**外れ**。

### 原因: T4 ではプロファイル段が完全に効かない

```
単独版:  S4 profile_W  38.9858 | S5 profile_U   38.9858 (R) | S6 profile_V  38.9848
累積版:  S4 profile_W  38.9858 | S5 profile_WU  38.9858 (R) | S6 profile_WUV 38.9858 (R)
```

**累積版では W 以降の 2 段が両方 revert し、rwp がビット同一**。CaTeO3 は「単独だと revert・
累積なら効く」だったが、T4 は**どちらでも効かない**。U,V,W の解放方法の問題ではない。

推測: T4 は 3 ヒストグラム中 2 本が TOF で、engine はプロファイル段で TOF を除外する
(`rad.is_tof → continue`)。残る 11BM 放射光 1 本だけでは寄与が小さい可能性。要調査。

### 計画への含意

1. **REQ-SAR-500 (レシピ探索) の根拠が強まった。** 最良レシピはデータごとに違う:

   | | M7 既定 | 本気(単独) | 本気(累積) |
   |---|---|---|---|
   | T1 | 9.83 | **9.69** | 10.45 |
   | T3 | 6.66 | **6.02** | 6.10 |
   | CaTeO3 | 12.43 | 18.07 | **12.19** |
   | T4 | **~12.8** | 14.53 | 14.58 |

   **3 つのレシピが 3 通りの勝ち方をしている。**単一レシピを既定に据える設計は
   この時点で棄却してよい。

2. **no-op 段検出 (REQ-SAR-102) の事例が増えた** — T4 は profile 段 2 つ + 終盤 5 段が
   rwp ビット同一。実データ裏付けとして十分。

3. **T4 固有の課題を Phase 1 に追加する必要がある** — 多相 + TOF で本気フィットが
   まったく効かない理由 (プロファイル段の TOF 除外・n_params 27 の少なさ・GOF 5.57) は
   未解明。WS-4 (レンジ/背景の自動化) や TOF プロファイル (`tof_profile` フラグ) の
   関与を疑う。

---

## 検証ゲート (全タスク共通)

各タスクは以下を満たして初めて完了とする。

1. **6 データすべてで非回帰** — T1 / T2 / T3 / T4 / CaTeO3 / NaCuHCF
2. **改善は単独で測る** — 合成すると原因が切り分けられない (U,V,W の件を特定できたのは 1 変数ずつ測ったから)
3. **ガードテストは変異させて fail することを実証**する
4. `uv run pytest -m "not gsas"` が green
5. `uv run ruff check src tests` が clean
6. ベンチマーク結果を `docs/benchmark/stable-auto-rietveld/` に追記

---

## ベンチマーク基準値 (Phase 0 で再確認する)

| データ | M7 既定 | 本気 (U,V,W 単独) | 本気 (U,V,W 累積) | チュートリアル |
|---|---|---|---|---|
| T1 fluoroapatite | 9.83% | 9.69% | 10.45% | 10.38% |
| T2 garnet | 4.33% | 未測定 | 未測定 | 5.18% |
| T3 PbSO4 joint | 6.66% | **6.02%** | 6.10% | 6.71% |
| T4 NAC+CaF2 | **~12.8%** | 14.53% (2.8 h) | 14.58% (2.9 h) | 6.83% |
| CaTeO3 frame030 | 12.43% | 18.07% | **12.19%** | 9.4% |
| NaCuHCF | XRD 4.84% / ND ~12% | 未測定 | 未測定 | — |

---

## 決定ログ

| 日付 | 決定 | 根拠 |
|---|---|---|
| 2026-07-27 | 安定性最優先・時間は無視 (operando 除く) | ユーザー判断 |
| 2026-07-27 | **構造パラメータ (占有率/Uiso/座標) に箱拘束を張らない** | ユーザー指摘。異常値はモデル誤りの証拠であり診断信号 (NaCuHCF model5/6 判別の実例) |
| 2026-07-27 | restraint は `dlg` スタブで有効化可能。**既定 OFF**・esd プルーニング先行 | `GSASIIstrMath:5203` のゲートを特定。`GSASIIstrMain:430` の副作用があるため |
| 2026-07-27 | 単一順序に賭けず**探索する** | 4 配置 × 4 データの実測でどれも 1 つ以上落ちた |
| 2026-07-27 | ベンチマークハーネスを最初に作る | 検証コストが全作業を律速するため |
| 2026-07-28 | **単一レシピを既定に据える設計を棄却** | 3 レシピが 3 通りの勝ち方をした (T1/T3=本気単独・CaTeO3=本気累積・T4=M7 既定)。REQ-SAR-500 の探索が必須 |

---

## 未解決 / 引き継ぎ

| 項目 | 状態 |
|---|---|
| **T4 が本気フィットに応答しない**原因 | 未解明。プロファイル段が完全 no-op (下記)。多相/TOF の扱いとして Phase 1 で追う |
| CaTeO3 delta 受理 (別タスク task_96458c15) | 別 worktree で進行中。マージ後に本作業へ影響がないか確認 |
| GSAS-II 本体への `dlg` ゲート報告 | 未着手 (アップストリーム Issue 化の候補) |


---

## Phase 1 実測で判明したこと (Phase 2 の設計入力, 2026-07-28)

| 発見 | 含意 |
|---|---|
| **T1 の「成功している」段は shift/esd 基準では収束していない** (max shft/sig = 86 / 116 / 47、S1/S2 は GSAS 自身の `converged` も False) | `require_convergence` を既定 ON にすると**現行レシピはほぼ全段 revert する**。収束予算 (max_cyc / extra_cycles) とセットで設計しないと使えない |
| **`Max shft/sig` は絶対値ではない** (`GSASIIstrMain:402` = `np.max(Lastshft/sig)`) | 強い**負**シフトは小さい値として通る = 判定は片側にしか効かない。厳密にやるなら `sig` から自前計算が要る (上流仕様) |
| **動的相関検出が静的知識を裏付けた** — T1 プロファイル段の実測 `V×W` r=−0.959 / `U×V` r=−0.955 | architecture.md D2 の二段構え (静的な相関群 + 実測補正) が機能している。Caglioti 群の分割禁止は実測でも正しい |
| **座標シフト `dAx/dAy/dAz` は esd プルーニングの構造的な偽陽性** (収束するほど値が 0 に近づき比が必ず 1 を超える) | 既定で除外している (`prune_exempt_tokens`)。**仕様書に無い追加判断なので要レビュー** |
| **既存 `dataquality.suggest_two_theta_limit` に偽陽性** (実ピーク終端 40° のデータで 48.44° を返す) | Issue 化候補。`autorange` は持続性要求で 40.54° |

## 積み残し (要判断)

| 項目 | 内容 |
|---|---|
| **3-3 元素ランク展開** | レシピ側は `element_expansion="heavy_first"` を opt-in で宣言済み。**engine 側の実展開が未実装**のため既定は `"ranks"` のまま (先に既定を変えると「1 段で全原子解放」という別物になる) |
| **3-4 周回入口の最良復元** | 設計メモのみ (engine 側の作業) |
| **4-4 Le Bail 基準線** | 設計のみ (`autorange.py` docstring に 6 手順) |
| **WS-2 拘束・境界** | 未着手。1-4 (esd プルーニング) が入ったので restraint 有効化の前提は満たされた |
| **② 露出 (autorange)** | `autorange` は ② 未露出。★不変条件として要対応 |
