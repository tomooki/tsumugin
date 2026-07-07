# M11 逐次減算同定 (単相/多相の統一エントリ) アーキテクチャ設計

仕様 (正): `docs/tsumugin_spec_v0.3.md` FR-118 / 要件: `docs/spec/m11-iterative-identification/requirements.md`

## 0. スコープと達成目標

未知パターンの単相/多相を事前に区別せず、**残差に対する反復同定 (search-match-subtract)** で単一エントリ
`identify_pattern` に統一する。CandAt × MP 全候補で calcite+aragonite を受理し graphite を棄却 (AC-1)、
PbSO4 単相で k=1 停止 (AC-2)、少数相検出限界の低下 (AC-3) を達成する。

**核心の設計判断 (本セッションの実測に基づく):**
1. **残差に対して同定** — clean 残差で正解相 rank 1 (issue23_verify)。静的混合=共変質なし。
2. **joint 非負スケール再フィット** — 貪欲減算の誤差蓄積を防ぐ (M10 consolidation の peak-space 版)。
3. **decoy は残差支持で棄却** — hard 化学ガードでなく「残差を説明できないから s≈0」で自然棄却 (Dara 教訓遵守)。
4. **停止は残差 S/N** — bic はピーク空間で寛容すぎ (ベンチ済); ノイズ 3.3σ vs 構造化 108σ の分離を使う。
5. **多形判別は Rietveld へ委譲** — pseudo-R ~95% では C2/Pnma を分離不可 (実測)。

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
| `reference/iterative.py` (新規) | 反復同定オーケストレーション | `identify_pattern`, `IterativeIdentification`, `AcceptedPhase`, `IdentifyConfig` |
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
identify_pattern(tt, intensity, provider, *, elements, known_phases=(), cfg=IdentifyConfig()) -> IterativeIdentification
```

```
0. 前処理: SNIP 背景減算, find_peaks, σ=√raw。accepted ← list(known_phases)
   accepted があれば fit_nonneg_scales で先に残差計算 (operando warm-start)
1. for k in 1..cfg.max_phases:
     resid = intensity − render(accepted)                         # 原パターンから
     sig = residual_significance(tt, resid, σ)
     if sig.max_snr < cfg.snr_stop: break                          # 全て説明済 (単相は k=1 で停止)
     ident = identify_phases(tt, resid, provider, elements=elements,   # 提案 (rerank 既定 on)
                 subtract_bg=False, refine_lattice=True, strain_penalty=cfg.chem_penalty(...))
     best = None
     for cand in ident.matches[:cfg.try_k]:                        # 受理: joint 再フィット
         trial = accepted + [cand]
         s, _, ss = fit_nonneg_scales(tt, intensity, trial, cfg.fwhm)
         gain = (ss_prev − ss) / ss_prev
         if s[-1] > cfg.scale_min and gain > cfg.eps_gain and (best is None or ss < best.ss):
             best = (cand, s, ss)
         ledger.append("m11_trial", {...accept/reject, scale, gain...})
     if best is None: break                                        # 全棄却で停止
     accepted.append(best.cand); ss_prev = best.ss
2. groups = group_by_composition(accepted)                         # 多形集約
   escalate = 僅差同組成多形あり (score 差 < polymorph_margin)      # 実 Rietveld 委譲旗
3. return IterativeIdentification(accepted, residual, groups, escalate, unmatched, ledger)
```

**decoy 棄却の仕組み**: graphite は calcite/aragonite 減算後の残差に説明対象を持たないため、joint fit で
scale≈0 → gain < eps_gain → 受理されない。hard 除外なしに残差支持だけで落ちる (FR-118-4)。

## 5. 要素3 — 化学は降格 prior (chem 配線, FR-118-4/9)

- `chem.ChemPlausibility` (FR-412) を `identify_phases` の `strain_penalty` 同様の**スコア減点**として合成
  (候補除外はしない)。元素部分集合の単純相は prior で下がるが、残差が本当にそれを要求すれば受理され得る。
- operando の全元素系 hard ガード (`require_elements`) は本ループでも opt-in で残す (層3)。

## 6. 要素4 — 多形委譲 (FR-118-5)

- `group_by_composition(accepted)` で同組成 (CaCO3) を1グループに集約。グループ内 score 差 < `polymorph_margin`
  なら `escalate_to_rietveld=True` + 対象グループを出力。呼び出し側 (agentic / M7) が `run_auto_rietveld` の
  多相で真の Rwp/bic 判別へ回す。**探索では確定しない** (設計分担の明示)。

## 7. operando 一本化 (FR-118-6)

`insitu.phaseid.identify_new_phases` は `identify_pattern(known_phases=現行相集合, elements=...)` を呼ぶシムに
段階移行する。静的同定 = `known_phases=()` 起点、逐次同定 = 既知相集合起点で、**同一プリミティブ**。既存
シグネチャは後方互換で温存 (物質化 → PhaseSpec の配線は M9 のまま)。

## 8. データフロー

```
観測 + elements (+ known_phases)
   │  SNIP + find_peaks + σ
   ▼
[反復] resid ─→ residual_significance ──(< snr_stop)──▶ 停止
   │                                    (単相は k=1)
   ├─ identify_phases(resid)  ← 異方 rerank(層1) + chem 降格 prior
   ▼
   受理: fit_nonneg_scales(原パターン, accepted+cand)  ← joint 非負スケール
   │   gain > eps_gain ∧ scale > scale_min → 受理    (decoy は s≈0 で棄却)
   ▼
   accepted 更新 → resid 再計算 (原パターンから) → ledger
   ▼
group_by_composition → 多形集約 + Rietveld エスカレーション旗
   ▼
IterativeIdentification (accepted, residual, groups, escalate, ledger)
```

## 9. 段階計画 (TDD, Opus)

1. **significance 昇格** — `insitu.residual` → `reference.significance`、re-export で後方互換。テスト移設。
2. **scale.py** — `fit_nonneg_scales` + `render_model` + 決定論テスト (既知スケール回復・非負・決定論)。
3. **iterative.py 骨格** — `identify_pattern` の単相縮退 + 停止 (stub 供給元) テスト。
4. **反復受理/棄却** — joint 再フィット受理 + decoy 棄却 + known_phases 起点テスト。
5. **chem 降格 prior + 多形委譲旗** — テスト。
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

- 多形の厳密判別 (実 Rietveld 委譲)。プロファイル形状最適化。重畳系 deconvolution 高度化。
- `identify_phase_mixtures` の廃止 (受理集合+代替の小プール組合せ検証に再配置し残す)。
- 層1 の異方 rerank 既定 on は PR #26 前提 (マージ後に本 M11 実装が乗る)。
