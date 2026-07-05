# M7: 実データ検証 — GSAS-II チュートリアル同等の自動 Rietveld 解析

作成: 2026-07-05 / ブランチ: `milestone/m7-real-data-validation`

## 完了記録 (2026-07-05)

新モジュール `tsumugin.autorietveld` (model/recipe/validity/engine) を TDD で実装し、実データで検証:

| 例 | tsumugin 自動 | チュートリアル | 判定 |
|---|---|---|---|
| T1 fluoroapatite (単相ラボX線) | **Rwp 9.83% / GOF 1.76** | 10.38% / 3.44 | ✅ 上回る |
| T2 garnet (単相CW中性子, Fe/Al 混合占有) | **Rwp 4.33% / GOF 1.63** | 5.18% / 3.79 | ✅ 上回る |
| T3 PbSO4 (X線+中性子 joint) | **Rwp 6.66% / GOF 2.25** | 6.71% / 2.27 | ✅ 一致 |
| T4 NAC+CaF2 (TOF+放射光 多相) | **Rwp ~12.8%** (48% 平坦から単調収束・物理格子) | 6.83% | 🟡 収束済・更に改善余地 |

- **成果物1** (改良アルゴリズム): `autorietveld` — 適応段階解放レシピ + 物理妥当性ゲート + 制約
  自動生成 + revert/崩壊ガード。§4 の教訓を実装に反映。
- **成果物2** (指示書): `AGENT_PLAYBOOK.md`。
- **T4 収束改善 (2026-07-05 追加)**: 非収束 (48% 平坦・nvar 凍結) の原因は**データリミット未設定**
  と判明。ノイズ領域除外 + 多相専用の解放順序 (相分率を分離して先行・size/微小歪みを最後) +
  TOF プロファイル不解放 + size/歪みの CW 中性子除外ヒューリスティクスで **51%→12.8% に単調収束**。
  残差 (対 6.83%) は 11BM 背景項数・NAC mustrain 初期値等の手動調整分で、更なる改善余地。
- 実装記録: `docs/{spec,design,tasks}/m7-real-data-validation/`。

## 1. 目的

単相・多相の粉末 XRD / ND 自動解析を **GSAS-II 公式チュートリアルの実データ**で検証し、
自動解析アルゴリズムを洗練させ、AI エージェントによる全自動解析を達成する。

- **成果物 1**: 改良された自動解析アルゴリズム (段階解放レシピ・ガードレール・物理妥当性ゲート)
- **成果物 2**: AI エージェントへの自動解析指示書 (`AGENT_PLAYBOOK.md`)
- **達成目標**: チュートリアルと同等の解析結果 (Rwp / GOF / 構造・パラメータの物理的妥当性)

## 2. 検証対象 (GSAS-II tutorials — Rietveld refinement セクション)

| # | Tutorial | データ | 相 | チュートリアル最終値 | M7 合格基準 |
|---|---|---|---|---|---|
| T1 | LabData (fluoroapatite) | 実験室 X 線 CuKα (FAP.XRA + INST_XRY.PRM) | 単相 P6₃/m | Rwp 10.38% / GOF 3.44 | Rwp ≤ 12%, GOF ≤ 4.5 |
| T2 | CWNeutron (Y-Fe garnet) | CW 中性子 D1a λ=1.909Å (garnet.raw + inst_d1a.prm) | 単相 Ia-3d, Fe/Al 混合占有 | Rwp 5.18% / GOF 3.79 | Rwp ≤ 6.5%, 占有率制約充足 |
| T3 | CWCombined (PbSO4) | X 線 + CW 中性子 joint (PBSO4.XRA/.CWN) | 単相 Pnma | 合計 wR 6.71% / GOF 2.27 (N 4.53% / X 11.0%) | 合計 wR ≤ 8% |
| T4 | TOF-CW Joint (NAC+CaF2) | 放射光 11BM + POWGEN TOF×2 (3 ヒストグラム) | 二相 (CaF2 ~10%) | Rw 6.83% (75 params) | Rw ≤ 8.5%, 相分率制約充足 |
| T5 | Simulation | シミュレーション (実データなし) | — | — | 対象外 (M7 スコープ外) |

チュートリアル手順 (段階解放順序・制約・特殊設定) の詳細は §4 参照。
物理的妥当性: 格子定数が文献値 ±0.5%、Uiso > 0 かつ < 0.1 Å²、占有率 ∈ [0,1]、
制約 (占有率和・相分率和 = 1) 充足、を最低ラインとする。

## 3. 現状ギャップ (M0–M6 資産の棚卸し)

| 資産 | 状態 | M7 ギャップ |
|---|---|---|
| `tsumugin.pipeline.analyze_single_pattern` | ✅ 段階解放+ガードレール+BIC ランキング | レシピが実構造 Rietveld 向けに未較正 |
| `tsumugin.backends.GSASIIBackend` | ⚠️ **P m m m + Ni ダミー構造** (M0 の格子同定用) | ❌ 実 CIF 構造での精密化・実パラメータ (Back/Scale/cell/UVW/XY/displacement/coords/Uiso/frac) マッピングが必要 — **M7 の中核** |
| `tsumugin.reference.io` | ✅ GSAS STD (.xra/.raw) + .xy | ❌ FXYE (ESD 列)・TOF (.gsa)・.instprm 読込 (T4 に必要) |
| `tsumugin.joint` | ⚠️ joint は単一ヒストグラムバックエンドに委譲 | ❌ GSAS-II ネイティブ複数ヒストグラム (1 プロジェクト N histogram) が T3/T4 に必要 |
| 制約 | ❌ なし | 原子等価制約 (Uiso equiv)・占有率和・相分率和=1 (T2/T4 に必要) |
| 物理妥当性ゲート | ⚠️ ガードレール (発散・負値) のみ | 格子/Uiso/占有率/結合距離の妥当性チェックを評価軸に追加 |
| ベンチマーク基盤 | ✅ `docs/benchmark/` PbSO4+CandAt (相同定検証) | 精密化 (Rwp/GOF) の回帰ベンチとして拡張 |

## 4. チュートリアル精密化レシピ (自動化アルゴリズムの正解系列)

自動段階解放レシピはこの 4 例を一般化して設計する:

- **T1 LabData**: scale+background(log-interp 9 項) → cell+sample displacement (Bragg-Brentano では zero でなく displacement) → size/mustrain → coords+Uiso
- **T2 CWNeutron**: scale+background(Chebyshev 3) → cell → 制約設定 (Fe/Al Uiso equiv + frac 和) → frac → 全 Uiso → UVW + sample X,Y displacement
- **T3 CWCombined**: 共有: cell/coords/Uiso。ヒストグラム別: scale/background/displacement/size/strain (X 線のみ)/UVW。中性子側は温度差を hydrostatic strain D11,D22,D33 で吸収
- **T4 TOF-CW**: 相分率和=1 制約 (各ヒストグラム) → background 増項 (3→6) → UVW+displacement (11BM) + cell + D1.1 (TOF 側温度差) → NAC coords+Uiso / CaF2 Uiso → 相×データ毎の size/mustrain

一般化の要点 (アルゴリズム改良仮説):
1. **ジオメトリ適応**: Bragg-Brentano → displacement、Debye-Scherrer → zero/X,Y displacement
2. **温度差適応**: マルチヒストグラムで測定温度が異なる場合、格子は共有し per-histogram Dij で吸収
3. **背景適応**: 背景項数は残差から動的に増項 (固定 3 項で開始)
4. **制約自動生成**: 混合占有サイト → equiv/和制約、多相 → 相分率和=1
5. **解放順序の普遍系列**: scale+bkg → cell(+geom補正) → profile → coords → Uiso → frac (ガードレール逆転時は revert して継続 — 既存 FR-202 を維持)

## 5. フェーズ計画

- **Phase A — 実構造 GSAS-II 精密化コア**: `GSASIIBackend` を実 CIF 相で駆動する
  精密化経路 (histogram+CIF phase+instprm → パラメータキー↔GSAS-II 名マッピング → 段階実行)。
  T1 fluoroapatite で Rwp ≤ 12% を自動達成。CIF は MP/COD から取得し `docs/benchmark/testdata/m7/` に固定。
- **Phase B — CW 中性子 + 制約**: 中性子ヒストグラム対応 + 制約 API (equiv/和)。T2 garnet で検証。
- **Phase C — ネイティブ joint**: 1 プロジェクト複数ヒストグラム + 共有/個別パラメータ + Dij。T3 PbSO4 で検証。
- **Phase D — TOF + 多相**: FXYE/TOF ローダー + .instprm + 相分率制約。T4 NAC+CaF2 で検証。
- **Phase E — アルゴリズム洗練 + 指示書**: 4 例の課題を横断して段階解放レシピ・ガードレール・
  物理妥当性ゲートを一般化。回帰ベンチ (`pytest -m gsas` + `-m benchmark`) 固定。
  `AGENT_PLAYBOOK.md` (AI エージェント自動解析指示書) を作成し、エージェントが
  指示書のみで T1–T4 相当の解析を再現できることを確認する。

## 6. 不変条件 (M7 でも維持)

- P2 非破壊性 / NFR-102 再現性 (乱数種固定・ビット同一) / NFR-105 ledger ハッシュチェーン
- バックエンド失敗は chi2=inf に変換しガードレールへ
- コア import は numpy のみ (GSAS-II は遅延 import / `@pytest.mark.gsas`)
- チュートリアルデータは `docs/benchmark/testdata/m7/` にコミットし再現性を担保
  (出典 URL を README に記録)

## 7. 参照

- チュートリアル索引: https://advancedphotonsource.github.io/GSAS-II-tutorials/tutorials.html
- データ出典: https://github.com/AdvancedPhotonSource/GSAS-II-tutorials (各 `<name>/data/`)
- 既存資産の詳細調査は本ファイルと同時に実施 (2026-07-05, §3 の根拠)
