# M11 逐次減算同定 (単相/多相の統一エントリ) アーキテクチャ設計

仕様 (正): `docs/tsumugin_spec_v0.3.md` FR-118 / 要件: `docs/spec/m11-iterative-identification/requirements.md`

## 0. スコープと達成目標

未知パターンの単相/多相を事前に区別せず、**残差に対する反復同定 (search-match-subtract)** で単一エントリ
`identify_pattern` に統一する。CandAt × MP 全候補で calcite+aragonite を受理し graphite を棄却 (AC-1)、
PbSO4 単相で k=1 停止 (AC-2)、少数相検出限界の低下 (AC-3) を達成する。

**核心の設計判断 (本セッションの実測に基づく):**
1. **残差に対して同定** — clean 残差で正解相 rank 1 (issue23_verify)。静的混合=共変質なし。
2. **joint 非負スケール再フィット** — 貪欲減算の誤差蓄積を防ぐ (M10 consolidation の peak-space 版)。
3. **decoy は残差支持で棄却** — hard ガードでなく「残差を説明できないから s≈0」で自然棄却。
4. **停止は残差 S/N** — bic はピーク空間で寛容すぎ (ベンチ済); ノイズ 3.3σ vs 構造化 108σ の分離を使う。
5. **多形判別は相同定の責務** — pseudo-R ~95% では calcite/aragonite を分離不可 (実測) なので、**注入した実
   Rietveld を相同定内で呼び真 Rwp で確定**する (委譲しない)。
6. **化学はコア非依存 (第3層)** — 提案・受理は化学に依存せず、opt-in の hard ガードのみエージェント/人間が渡す。

## 1. 設計原則

- **numpy-only コア + 遅延 import**: ループ・非負スケール LSQ・残差評価は numpy のみ。供給元 (MP) / 物質化 /
  Rietveld は境界の内側。
- **既存部品の再利用が主、新規は薄い**: `identify_phases` (rerank/化学込み) を「次の1相提案」プリミティブに、
  `ReferenceBackend` をプロファイル合成に、`residual_significance` を停止に、`group_by_composition` を多形集約に。
- **P2 / 提案≠適用**: 反復・受理/棄却・スケール・残差 S/N を ledger 追記。棄却経路も保持。
- **NFR-102 決定論**: 乱数なし。import 方向を保つため `residual_significance` を `reference.significance` へ昇格
  (reference は insitu を読めない)、`insitu.residual` は re-export で後方互換。

## 2. モジュール構成

| ファイル | 役割 | 主要シンボル |
|---|---|---|
| `reference/significance.py` (昇格) | 残差 S/N (insitu.residual から移設) | `residual_significance`, `ResidualSignificance` |
| `reference/scale.py` (新規) | 非負スケール joint 最小二乗 + プロファイル合成 | `fit_nonneg_scales`, `render_model` |
| `reference/iterative.py` (新規) | 反復同定 + 多形 Rietveld 深段 | `identify_pattern`, `refine_polymorphs`, `IterativeIdentification`, `AcceptedPhase`, `IdentifyConfig`, `RietveldRefiner` (注入型) |
| `insitu/residual.py` | `reference.significance` を re-export (後方互換) | (既存 import 温存) |
| `insitu/phaseid.py` | `identify_pattern(known_phases=)` へ委譲する薄いシム (段階移行) | (既存 `identify_new_phases` 温存) |

## 3. 要素1 — 非負スケール joint フィット (scale.py)

```
render_model(two_theta, ref, scale, fwhm) -> np.ndarray        # 相のプロファイル (ReferenceBackend 相当)
fit_nonneg_scales(two_theta, observed, refs, fwhm) -> (scales, residual, unexplained_ss)
```

- 各相のプロファイル行列 A (列=相, 行=2θ) を固定 FWHM ガウスで合成し、`observed ≈ A·s` を **非負最小二乗**で解く。
- 実装: 閉形式 `s = (AᵀA)⁻¹Aᵀy` → 負成分クリップ→アクティブセット反復 (~30 行 numpy, scipy 不要)。
- `unexplained_ss` = ‖max(observed − A·s, 0)‖² (正残差の二乗和; 未説明強度)。負残差 (過剰) は罰さない。

**なぜ joint**: 貪欲に1相ずつ引くと減算誤差が蓄積し後続の相が歪む。毎回**全採用相を原パターンへ同時**に
スケールし直す (M10 consolidation と同思想を peak-space で)。

## 4. 要素2 — 反復ループ (iterative.py, FR-118)

```
identify_pattern(tt, intensity, provider, *, elements, known_phases=(),
                 refiner=None, cfg=IdentifyConfig()) -> IterativeIdentification
```

```
0. 前処理: SNIP 背景減算, find_peaks, σ=√raw。accepted ← list(known_phases)
   accepted があれば fit_nonneg_scales で先に残差計算 (operando warm-start)
1. for k in 1..cfg.max_phases:                                     # 【高速段: ピーク空間】
     resid = intensity − render(accepted)                         # 原パターンから
     sig = residual_significance(tt, resid, σ)
     if sig.max_snr < cfg.snr_stop: break                          # 全て説明済 (単相は k=1 で停止)
     ident = identify_phases(tt, resid, provider, elements=elements,   # 提案 (rerank 既定 on)
                 subtract_bg=False, refine_lattice=True,
                 require_elements=cfg.require_elements)             # 化学は opt-in (既定 None=層3)
     best = None
     for cand in ident.matches[:cfg.try_k]:                        # 受理: joint 非負スケール再フィット
         trial = accepted + [cand]
         s, _, ss = fit_nonneg_scales(tt, intensity, trial, cfg.fwhm)
         gain = (ss_prev − ss) / ss_prev
         if s[-1] > cfg.scale_min and gain > cfg.eps_gain and (best is None or ss < best.ss):
             best = (cand, s, ss)
         ledger.append("m11_trial", {...accept/reject, scale, gain...})
     if best is None: break                                        # 全棄却で停止
     accepted.append(best.cand); ss_prev = best.ss
2. groups = group_by_composition(accepted)                         # 同組成集約
   if refiner and (僅差多形 or cfg.always_refine):                 # 【深段: 実 Rietveld で多形裁定】
     accepted = refine_polymorphs(groups, refiner, tt, intensity, cfg, ledger)  # 真 Rwp/bic 最良を採用
3. return IterativeIdentification(accepted, residual, groups, refined=bool(refiner), unmatched, ledger)
```

**decoy 棄却の仕組み**: graphite は calcite/aragonite 減算後の残差に説明対象を持たないため、joint fit で
scale≈0 → gain < eps_gain → 受理されない。hard 除外なしに残差支持だけで落ちる (FR-118-4)。

**多形裁定 (深段)**: `group_by_composition` の CaCO3 グループ内で calcite/aragonite の pseudo-R は近接する
(実測 94.75 vs 95.90)。`refiner` があれば各多形を実 Rietveld し真 Rwp で確定 — **相同定自身の責務**。

## 5. 化学はコア非依存 (第3層, FR-118-4)

- **コアの提案・受理は化学に一切依存しない**。decoy (graphite 等) 棄却は残差支持 (joint fit で scale≈0 →
  gain 未達) のみで成立する。化学判断 (相転移か分解か・骨格保存の是非) は**第3層 (エージェント/人間)** の責務。
- 必要時のみ呼び出し側が opt-in の全元素系 hard ガード (`require_elements`) を `IdentifyConfig` で渡す。コアの
  **既定挙動には入れない** (Dara 教訓と整合しつつ、判断を層3へ明示分離)。

## 6. 要素3 — 多形判別 = 注入 Rietveld 深段 (FR-118-5)

**多形判別を相同定アルゴリズムの責務とする** (委譲しない)。`identify_pattern(refiner=...)` に**実 Rietveld
backend を注入**する (M7 `run_auto_rietveld` ラッパ; コアは GSAS 非依存)。

```
refiner: Callable[[Sequence[PhaseCandidate]], RefineResult]   # 注入境界。真 Rwp/bic/validity を返す
```

- `group_by_composition(accepted)` で同組成 (CaCO3) を集約。
- `refiner` 注入かつ (**僅差多形** score 差 < `polymorph_margin`、または `cfg.always_refine`) のとき、対象
  グループの各多形を**実 Rietveld で精密化**し、**真の Rwp/bic が最良の多形を受理相に採る**。ピーク探索の
  pseudo-R (~95%) では分離不可な calcite/aragonite を、**相同定自身が確定**する。
- `refiner` 未注入なら集約のみ (ピーク空間段の受理相 + 多形代替候補) を返す。Rietveld 失敗は chi2=inf に
  変換しピーク空間段の結果へフォールバック (提案≠適用・崩壊耐性)。試行/採否は ledger 追記。

**2 段受理**: (高速) ピーク空間 joint 非負スケール = 相の有無・少数相検出。(深) 注入 Rietveld = 多形/僅差の
真値裁定。深段はコスト高のため僅差時のみが既定 (`always_refine=False`)。

## 7. operando 一本化 (FR-118-6)

`insitu.phaseid.identify_new_phases` は `identify_pattern(known_phases=現行相集合, elements=...)` を呼ぶシムに
段階移行する。静的同定 = `known_phases=()` 起点、逐次同定 = 既知相集合起点で、**同一プリミティブ**。既存
シグネチャは後方互換で温存 (物質化 → PhaseSpec の配線は M9 のまま)。

## 8. データフロー

```
観測 + elements (+ known_phases, + refiner?)
   │  SNIP + find_peaks + σ
   ▼
[反復・高速段] resid ─→ residual_significance ──(< snr_stop)──▶ 停止
   │                                          (単相は k=1)
   ├─ identify_phases(resid)  ← 異方 rerank(層1)。化学は opt-in のみ (既定なし=層3)
   ▼
   受理: fit_nonneg_scales(原パターン, accepted+cand)  ← joint 非負スケール
   │   gain > eps_gain ∧ scale > scale_min → 受理    (decoy は s≈0 で棄却)
   ▼
   accepted 更新 → resid 再計算 (原パターンから) → ledger
   ▼
group_by_composition → 同組成集約
   │  refiner あり & (僅差多形 or always_refine)
   ▼
[深段] refine_polymorphs: 各多形を実 Rietveld → 真 Rwp/bic 最良を採用 (Rietveld 失敗は fallback)
   ▼
IterativeIdentification (accepted, residual, groups, refined, ledger)
```

## 9. 段階計画 (TDD, Opus)

1. **significance 昇格** — `insitu.residual` → `reference.significance`、re-export で後方互換。テスト移設。
2. **scale.py** — `fit_nonneg_scales` + `render_model` + 決定論テスト (既知スケール回復・非負・決定論)。
3. **iterative.py 骨格** — `identify_pattern` の単相縮退 + 停止 (stub 供給元) テスト。
4. **反復受理/棄却** — joint 再フィット受理 + decoy 棄却 + known_phases 起点テスト。
5. **多形 Rietveld 深段** — `refine_polymorphs` (注入 `refiner` で同組成多形を実 Rietveld 裁定・失敗
   fallback) + テスト (stub refiner)。化学はコアから除外 (opt-in `require_elements` のみ残す)。
6. **operando シム** — `identify_new_phases` を `identify_pattern` 委譲へ (M9 テスト非回帰)。
7. **実データ検証** — CandAt/PbSO4/minority_probe (`@pytest.mark.mp`) で AC-1/2/3 + snr_stop 校正。
8. **`/code-review` ループ → PR**。

## 10. テスト戦略

- **決定論コア** (scale/iterative 制御): stub 供給元で単相縮退・多相受理・decoy 棄却・停止・known_phases・
  決定論を network/GSAS なしに green。
- **回帰: 単相縮退 = M6 単相**。`identify_pattern` の k=1 結果が `identify_phases` 首位と整合。
- **AC-1 の核**: 「graphite を含む候補プールで graphite が joint fit で s≈0 → 棄却」を stub で固定。
- **gated**: 実データ (CandAt/PbSO4/minority) は mp mark。

## 11. スコープ外 (M-later)

- プロファイル形状最適化 (深段 Rietveld が担うが、本 M11 の高速段は固定 FWHM)。重畳系 deconvolution 高度化。
- `identify_phase_mixtures` の廃止 (受理集合+代替の小プール組合せ検証に再配置し残す)。
- 化学的妥当性のコア組込み (第3層に分離; opt-in `require_elements` のみ)。
- 層1 の異方 rerank 既定 on は PR #26 前提 (マージ後に本 M11 実装が乗る)。

**スコープ内 (方針変更)**: 多形の厳密判別は本 M11 の責務 (注入 `refiner` による実 Rietveld 深段)。以前の
「Rietveld へ委譲」設計から「相同定が Rietveld を呼んで確定」へ変更。

## 12. 実装知見 (実データ検証, E1-E4 改善ループ)

並列 Sonnet サブエージェント + Opus 分析の改善ループ (`scratchpad/m11_experiment_log.md`) で確定した実データ知見:

- **減算前ピーク整合が実データ多相回復の鍵 (E1, 実装済)**: `_peaklist` が生の参照ピークを使うと、MP 参照の
  DFT 格子/位置誤差がそのまま減算残差に位置ミスマッチ (~560σ) として残り次相検出を汚染する。受理判定・
  最終減算の両方で候補を**現残差へ格子整合** (`_candidate_peaklists`: 異方 `align_peaks_anisotropic` 優先・
  cell 不足時等方) してからプロファイル合成する。整合は少数ピークでノイズ過剰適合し得るため生版と整合版を
  実 joint fit の ss で選択 (`_best_peaklist_and_fit`, 事前閾値でなく実測適合)。FWHM 自動推定 (`auto_fwhm`)
  併用。**CandAt で calcite+aragonite 両回復**。異方経路は cell 付き候補 (live MP) で活性化 (キャッシュは
  cell なしで等方のみ)。
- **元素部分集合の偽陽性は fast tier で棄却不能 (E3/E4 で確認)**: Ca 金属等は (1) 少数ピークが最強反射に
  偶然一致し gain 最大、(2) 固有ピークも持つため「固有新ピーク」ゲート (E3) も通過、(3) dara 順受理 (E4) も
  効かず合成テストを壊す。**これは設計境界通り** — element-subset FP は**深段 refiner (構造因子で該当強度を
  出せないと判明) or 層3 化学ガード (opt-in `require_elements`)** の担当。fast tier = 正解相回復 + 明白 decoy
  (graphite・部分集合のみ相) 棄却まで。「fast tier で偽陽性ゼロ」を求めるのは 2 段構え設計と矛盾する。

## 13. 未完 (follow-up)

- **T6 operando 一本化 (Issue #28, 実装済)**: `insitu.phaseid.identify_new_phases` を
  `identify_pattern(known_phases=, cfg=)` 委譲へ移行。素の `identify_phases` ランキングを**残差支持の
  受理 (joint 非負スケール) + S/N 停止**に置換し、静的同定=`known_phases=()` 起点・operando 逐次同定=
  現行相集合起点で同一プリミティブに統一した。物質化 → PhaseSpec の配線 (材料化・異方セル補正 Issue #20・
  失敗フォールバック・strain 伝播) は M9 のまま温存。実配線に伴い (1) `AcceptedPhase` へ `strain` を追加
  (`PhaseMatch.strain` 由来、materialize の格子補正に転送)、(2) `IdentifyConfig` へ `max_strain`/
  `hull_cutoff_ev`/`kalpha2`/`rerank_wavelength` を追加し内部 `identify_phases` 呼び出しへ転送、(3)
  `identify_new_phases` に optional `known_phases`/`cfg` を追加 (後方互換)。M9/M10 insitu テストは
  非回帰 (受理は残差支持ゲートを通るため、単体テストは現実的カウント数 + ≥8 ピーク整合の合成へ更新)。
- **T6-B operando warm-start 実注入 (実装済)**: engine.py の新相探索を identify-all-then-exclude から
  **現行相集合の known_phases 先減算**へ格上げ。`insitu.phaseid.phasespec_to_reference` (CIF →
  pymatgen → `mp.xrd.simulate_reference_peaks`、`refined_cell` で**現フレームの精密化格子へ置換**して
  ピーク生成; 遅延 import・失敗時 None) で現行相を `ReferencePhase` に変換し、`PhaseFinder` プロトコルへ
  `known_phases` 引数を追加、`_try_add_phase` が精密化格子付きで注入する。CIF 素の DFT 格子でなく現
  フレーム実測格子で減算するため残差がクリーンになり少数新相の検出感度が上がる (M11「減算前ピーク整合」
  の operando 版)。`PhaseIdConfig.warm_start_known_phases` (既定 True) で制御。変換不能 (pymatgen 不在 /
  CIF 読込失敗 / スタブ finder 擬似パス) は空集合へ縮退し**静的同定 (identify-all-then-exclude) に安全
  フォールバック** (提案≠適用・純テスト非回帰)。numpy コア import は pymatgen 非依存を維持 (engine top
  で phaseid を import するが phasespec_to_reference 内で遅延 import)。gated 実データ (CaTeO3 全 14 フレーム)
  の warm-start 効果検証は MP キー要 (次段)。
- **MP キャッシュの cell 付き再生成**: 現キャッシュは Issue #18 前スキーマで cell なし → 異方経路が gated
  テストで no-op。cell 付き再取得で恒久強化可 (`scratchpad/t7_live_aniso.py` 参照)。
