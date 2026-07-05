# M6 相同定 拡張計画 — Dara フロー準拠 (Rietveld 統合)

参照: Fei et al., *"Dara: Automated Multiple-Hypothesis Phase Identification and Refinement from
Powder XRD"*, Chem. Mater. 2026, 38, 1364–1376.

## 1. Dara の相同定フロー (論文 Methods)

1. **参照前処理**: 化学系 (元素) で候補選択 → 分子/有機相除去 → pymatgen StructureMatcher で重複排除
   (20°C 最近・最古エントリを代表) → hull エネルギー >100 meV/atom を除外 (MP 未登録は保持)。
2. **ピーク抽出**: 実測ピークを BGMN TEIL&EFLECH で抽出。**各参照相を単相 Rietveld 精密化**して
   格子調整済みの計算ピークを生成 (← 格子ズレをここで吸収)。
3. **ピークマッチスコア (式1)**: matched / wrong-intensity / missing / extra に4分類。
   `Score = (I_matched + I_wrong − 0.1·I_missing − 0.5·I_extra) / I_exp`。
4. **木探索** (BFS/best-first, Ray 並列):
   - ノード = 相組合せ。各ノードで **未説明 (missing) 実測ピーク**を求め、候補を missing ピークに
     対してスコアし、動的閾値 (累積分布の変曲点) 超のみ展開。
   - **各ノードで BGMN Rietveld 精密化** (格子最大1%歪み・scale/背景/試料変位/簡易プロファイル) →
     背景補正 R値 (Rpb)。Rpb 改善 <2% で展開停止。最大5相。
   - 順序制約 (新規相は既存相より最大ピーク強度が小)。
   - 等構造クラスタ (Jaccard 0.9) → 代表を **FoM = (1/(1−ρ))·100·(Σ|Δlattice|/lattice0)** で選出
     (fit + 格子シフト ΔU。格子変化が小さい相を優先 = 固溶体の過適合回避)。
5. **最終精密化**: 生存組合せに広めのパラメータ (SPHAR4 選択配向等) で再精密化 → 相分率。
   原子位置・占有率は参照固定、ADP=0.01 固定。
6. **結果表現**: Jenks で良好クラスタ抽出 → 組成でグルーピング → 未マッチピーク報告。

**核心**: 相同定の最終判定は **多相 Rietveld 精密化の Rwp**。ピークマッチスコアは高コストな精密化を
避けるための**高速事前フィルタ**。格子ズレ (DFT vs 実測) は精密化で格子を動かして吸収する。

## 2. 現状実装との比較

| Dara ステップ | 現状 (`tsumugin.reference` ほか) | 差分 |
|---|---|---|
| 参照前処理: 元素系 + hull フィルタ | `filter_references` / MP provider | ✅ ほぼ同等 |
| 参照前処理: StructureMatcher 重複排除 | `mp.xrd.group_equivalent` | ✅ (温度/年代選択は未) |
| 参照前処理: 分子/有機相除去・formula+SG 重複排除 | なし | ⚠️ 未実装 |
| ピーク抽出 (実測) | `find_peaks` (numpy) | ✅ 同等 |
| **各参照の単相精密化で計算ピーク生成** | XRDCalculator の**未精密化 DFT 格子ピーク** | ❌ **格子未調整 (本質的ギャップ)** |
| ピークマッチスコア (式1) | `dara_peak_score` | ✅ 実装済 |
| 木探索 (組合せ・動的閾値・Jaccard・最大相数) | `HypothesisTreeSearch` | ✅ 骨格あり |
| **ノード評価の Rietveld 精密化 (格子精密化)** | `ReferenceBackend` = **NNLS スケール фит のみ** | ❌ **格子精密化なし (本質的ギャップ)** |
| missing ピーク駆動の展開 | 全パターン再スコア (残差駆動でない) | ⚠️ 部分的 |
| 順序制約 (最大強度降順) | なし | ⚠️ 未実装 |
| FoM (格子シフト ΔU) で代表選出 | FoM に ΔU 項はあるが常に 0 | ⚠️ ΔU 未計算 |
| Rpb (背景補正) 改善閾値 | Rwp 改善閾値 (背景補正なし) | ⚠️ 近似 |
| 最終精密化 (SPHAR4 等) | `final_full_refine` (格子なし) | ⚠️ 限定的 |
| Jenks 良好クラスタ | `good_cluster_ids` | ✅ 実装済 |
| 組成グルーピング | 部分的 (クラスタのみ) | ⚠️ 未整備 |
| 未マッチ報告 | `UnmatchedPeakReport` | ✅ 実装済 |
| 背景減算 | `subtract_background` (SNIP) | ✅ (Dara は BGMN 内背景) |
| Kα2 二重線 | `add_kalpha2_satellites` | ✅ (Dara は BGMN 内) |

**結論**: スコア・木探索・前処理・レポートの骨格は揃った。**唯一かつ最大の欠落は「実構造を使う
格子精密化 Rietveld」**。これが無いため MP の DFT 緩和格子でピーク位置がずれ、CandAt のような
実データで Rwp が高止まり・判別が不安定になる (現状は信頼 CIF に絞ってようやく成立)。

既存の `GSASIIBackend` は実在するが、全相を「P mmm・原点 Ni 1 原子」に簡約しており実構造を使わず、
相同定フローにも未接続。これを実構造対応にするのが拡張の中心。

## 3. 拡張計画 (フェーズ別・TDD)

### Phase A — 実構造 Rietveld バックエンド (基盤・最優先)
- `ReferencePhase` に構造ハンドル (CIF テキスト or pymatgen Structure, 不透明) を非破壊追加
  (末尾 Optional フィールド)。`cif_to_reference_phases` / MP provider が併せて保持。
- `GSASIIBackend` を実構造対応に拡張 (または新 `RietveldBackend`): CIF を GSASIIscriptable へ投入し、
  **scale + 格子 a/b/c (≤1% 歪み拘束) + 背景 + 試料変位 (zero) + 簡易プロファイル**を精密化。
  原子位置・占有率固定、ADP=0.01 (Dara 準拠)。Rwp / 背景補正 Rpb / 精密化後格子を返す。
- 決定論 (NFR-102): 乱数種固定・同一入力ビット同一。失敗は chi2=inf へ縮退 (既存規約)。

### Phase B — 単相事前精密化で格子調整済み計算ピーク
- Dara スコア (未精密化ピーク) で候補を粗く絞る → 上位 K のみ **単相 Rietveld 精密化**で格子調整 →
  調整済み計算ピークで Dara スコア再計算。コスト管理のため「粗フィルタ→精密化」の順で K を制限。
- `identify_phases(..., refine_candidates=True, refine_top_k=...)` として段階導入。

### Phase C — Rietveld ベースのノード評価 (多相・格子精密化)
- `identify_phase_mixtures` のノード評価を `ReferenceBackend` (NNLS) から実構造 Rietveld へ切替。
  ピークマッチ (Dara スコア) は事前プルーニングに残す (Dara の設計: match で絞り refine で確定)。
- これで **DFT 格子ズレを吸収した真の Rwp** で多相仮説をランクし、CandAt を信頼 CIF に頼らず同定。

### Phase D — Dara フロー細部
- missing ピーク駆動の展開 (未説明ピークに対する候補スコアで枝を選ぶ)。
- 順序制約 (最大ピーク強度降順) で組合せ重複を排除。
- FoM の格子シフト ΔU を精密化前後の格子から実計算し、等構造代表選出に反映。
- Rpb (背景補正 R) 改善閾値。

### Phase E — 結果表現
- 組成グルーピング (agglomerative)。曖昧性 (同点競合) の明示レポート強化。

## 4. 優先度と依存

```
Phase A (格子精密化) ──┬─→ Phase B (単相事前精密化)
                       └─→ Phase C (多相ノード評価) ──→ Phase D → E
```

- **最優先 = Phase A + C**: ユーザー指摘の「格子ズレを吸収する精密化」を実現する中核。
- Phase B は単相同定の頑健化 (peak matching を DFT 耐性に)。
- D/E は精度・可読性の仕上げ。
- (DFT 経験補正は不要と判断し対象外。格子精密化が格子ズレを直接吸収するため。Issue #11 クローズ)

## 実装状況 (2026-07-05 A–E 完了)

| Phase | 実装 | モジュール / API |
|---|---|---|
| A | ✅ 格子ズレ吸収 (等方歪み ε + ゼロシフト z, Pawley-lite) | `reference.rietveld.align_peaks` / `LatticeAlignment` |
| B | ✅ 単相事前格子整合 | `identify_phases(refine_lattice=True, max_strain=)` |
| C | ✅ 多相ノードの格子整合 (事前フィルタ後に整合し junk 混入回避) | `identify_phase_mixtures(refine_lattice=True)` |
| D | ✅ 格子シフト ΔU をランキング反映 (`PhaseMatch.strain` / `strain_penalty`)。missing 駆動展開・順序制約は既存木探索が機能的に相当し据置 | `identify_phases(strain_penalty=)` |
| E | ✅ 組成グルーピング (同組成多形を集約) | `reference.group_by_composition` / `PhaseMatchGroup` |

Dara スコアも公開コード (CederGroupHub/dara) 準拠に厳密化 (2 閾値分類・min 寄与・係数)。
実検証: 実測 CandAt を **元素 (Ca,C,O) のみ**で全 MP 候補から calcite+aragonite 同定 (格子整合で
aragonite の単相スコア 0.047→0.314)。full 異方 Rietveld (GSAS-II, 原子/プロファイル) は将来拡張。

## 実装方針 (numpy コア維持)
格子精密化は当面 **numpy のみの Pawley-lite** (等方歪み ε + ゼロシフト z、必要なら hkl ベースの
異方歪みへ拡張) で実装し、コア (identify のピークマッチ経路) を numpy 依存に保つ。full 異方
Rietveld (GSAS-II, 原子/プロファイル精密化) は将来の重い拡張として境界を空けておく。

## 5. リスク / 論点
- **GSAS-II 統合コスト**: 実 CIF の投入・格子拘束付き精密化の実装と決定論確保。既存バックエンドの
  P mmm 簡約からの脱却が必要。GSAS-II 依存テストは `@pytest.mark.gsas` で隔離。
- **計算コスト**: 参照ごとの精密化は高価。Dara は Ray 並列。本実装は「Dara スコアで粗く絞ってから
  精密化」の順序でノード数・参照数を制限して現実的コストに収める。
- **`ReferencePhase` の構造保持**: frozen dataclass への Optional 末尾追加で後方互換維持。
- **コア numpy-only 維持**: Rietveld は optional extra (gsas) の遅延 import 境界に隔離し、コア
  (identify_phases のピークマッチ経路) は numpy のみで動作を継続。
