# M9 検証データ — 高温/時間 in situ 逐次 Rietveld

M9 (`tsumugin.insitu`) の逐次実構造 Rietveld + 新相自動同定の検証データ。2 系列。

## cateo3/ — Jana2020 Cookbook Example 02.6 "CaTeO3 cyclic" (相転移 + 新相自動同定)

出典: Jana2020 Cookbook Example 02.6 (`2.6_CaTeO3cyclic`)。実験室 X 線 Cu Kα (Panalytical XRDML)。
14 フレーム (`NB-LM01MO_030`〜`_420`) の昇温→降温 cyclic 実験。

- **相転移**: alpha CaTeO3·H₂O (含水, P2₁cn #33, a=14.78/b=6.79/c=8.06) を昇温すると脱水し、
  **delta 無水 CaTeO3 (P2₁ca #29, a=13.32/b=6.53/c=8.17) へ転移**。中間フレーム (150–300, param
  数 16→21) で alpha+delta が共存。**初期相 alpha のみ与え、delta は Materials Project から自動同定**
  するのが M9 の中心検証。
- チュートリアル最終値: 各フレーム wRp ~8.7–9.5% / GOF ~0.9–1.0。

同梱 (リポジトリには全 14 フレームでなく代表 2 フレームのみ):
- `NB-LM01MO_030.XRDML` (alpha 単相域), `NB-LM01MO_180.XRDML` (alpha+delta 共存域)
- `alpha_CaTeO3_H2O.cif` / `delta_CaTeO3.cif`: Jana `.m40/.m50` から `jana_to_cif.py` で変換した
  **標準セッティング CIF** (alpha=Pna2₁ #33 / delta=Pca2₁ #29, 厳密な Jana 原子, 水素略)。
- `cateo3_CuKa.instprm`: Cu **Kα1 単色** instprm (HighScore 処理で Kα2 除去済; W≈30 で実測ピーク幅
  ~0.056° に整合)。
- `jana_to_cif.py`: Jana→CIF 変換スクリプト (対称操作 comma 区切り + 標準設定変換の教訓を実装)。
- 全 14 フレームは元 `Data.zip` (`Example 02.6_ CaTeO3 cyclic/Data.zip`) から取得。

## cucr2o4/ — GSAS-II "Parametric sequential fitting" (CuCr₂O₄+CuO, 新相なし)

出典: https://github.com/AdvancedPhotonSource/GSAS-II-tutorials (`SeqRefine/data/SeqTut.zip`)。
11-BM 放射光 (.fxye)。17 フレーム (`OH_00`〜`OH_53`) 7–300K。CuCr₂O₄ (Fddd) + CuO 不純物相。
**新相出現なし** (2 次転移で b→c 収束; 相集合は一定)。パラメトリック解析 (格子 vs T・b/c 比) が主。

- チュートリアル最終値: 各フレーム wRp ~13–17% / GOF ~1.1。
- 同梱: `CuCr2O4.cif`, `CuO.cif`, `OH_00.prm` (装置), `OH_00.fxye` (先頭フレーム)。残り 16 フレーム
  (`OH_04`〜`OH_53.fxye`) は上記 `SeqTut.zip` から取得。

## 検証状況

- **配線 (end-to-end)**: CaTeO3 2 フレーム逐次を確認済 — GSAS 駆動・ウォームスタート格子伝播・
  XRDML→XYE 自己変換 (GSAS optional xmltodict 不要)・ledger `verify()` True (`tests/insitu/test_engine_gsas.py`)。
- **Rwp 収束**: **frame0 Rwp 13.4% / GOF 1.44** を M9 エンジンで自動達成 (LeBail 到達可能 12.7%,
  チュートリアル 9.4%)。70%→13% への収束で判明した鍵 (M7 T1–T4 同様の反復調整):
  1. **Jana→CIF 変換バグ**: 対称操作を space 区切りで渡すと全原子が (x,0,0) に潰れる → comma 区切りに。
  2. **標準セッティング**: Jana 非標準設定 (P2₁cn) を GSAS が拒否 → `get_conventional_standard_structure`
     で標準化 (原子改変なし)。P1 展開では格子が精密化されない。
  3. **Kα2 除去データ**: HighScore 処理で Kα2 が除かれており、instprm を **Kα1 単色**にする
     (I(L2)/I(L1)→0 が精密化で判明; Kα2 satellite の phantom が最大の系統残差)。
  4. **背景 24 項** (`make_gsas_runner(background_coeffs=24)`; 実験室 X 線は背景が複雑, 既定 6 では不足)。
  5. **X 線プロファイルを別段階で追加解放** (U,V,W のみでは 43%): recipe に `profile_lorentzian`
     (X,Y + Zero) と `profile_asymmetry` (SH/L, 分割擬フォークト相当の非対称) を X 線限定で追加。
     **U,V,W と同段階に混ぜず各 revert ガードで分離**する (混ぜると悪化時 whole-stage revert で
     M7 T3/T4 が回帰・CaTeO3 frame0 も 13.4→16.3 に劣化した)。
  残差 12.6→9.4% は preferred orientation (テクスチャ) + 水素 (X 線で微小) の未モデル分。
- **全 14 フレーム逐次 + delta 自動同定 (MATERIALS_PROJECT_API)**: **end-to-end 動作を確認**。
  frame0 12.57% (GOF 1.36)。系列は昇温で alpha (含水) が**実サンプルとして進行的に脱水**し alpha 単相
  Rwp が上昇 (frame060 単独でも 23.7%, frame120 57%)。転移域で **MP から CaTeO3 (delta) を自動同定・
  物質化・追加**し相集合が `(alpha, delta)` に成長 (ledger verify True)。エンジン改善: (a) **相の成長で
  Rwp が動いたら再探索** (単調上昇する転移相を捉える), (b) **top_k 候補を全試行し最良 Rietveld フィット
  を採用** (Dara 首位が最良構造とは限らない; MP に CaTeO3 は 8 多形), (c) **DFT 格子過大評価を align_peaks
  の歪みで物質化構造に補正** (`materialize(strain=)`, max_strain 0.01→0.05; MP の DFT セルは実測より
  ~3% 大)。**未完 (honest, 切り分け済の結論)**: 転移域〜delta 域の Rwp が高い。証拠に基づく正確な内訳:
  - **パイプライン + 良い構造は near-tutorial**: **実測 Jana delta で clean delta フレーム (frame420
    単相) Rwp 13.48%** (チュートリアル ~9%)。frame0 alpha 12.57%。→ M9 の配線・レシピ・装置設定は正しい。
  - **律速だった MP(DFT)構造の異方的な格子誤差** (→ **[Issue #20](https://github.com/tomooki/tsumugin/issues/20)
    — 解決済**): 同 frame420 で MP delta (mp-1195263) は 44%。切り分けで **mp-1195263 と Jana delta は同一多形
    (Pca2₁ #29, 40 原子, StructureMatcher fit=True, 原子 RMS 0.28 Å)** と判明し、**MP 座標 + 正しい格子で
    Rwp 13.28%**(=座標は Rietveld で合う)。真因は **c 軸だけ +3.4% 過大**な DFT 異方格子誤差で、
    Rietveld のセル精密化の収束半径(~2%)を超え c が動かなかった。**Issue #20 で解決**:
    `autorietveld.lattice` (逆格子計量テンソル最小二乗の異方セルソルバ) + `autorietveld.pawley`
    (`prealign_cell_from_structure`: **per-axis スケールの有界 FoM グリッドで大域ベイスンを先に特定→線形
    精密化**する 2 段で、Issue が「非自明」とした頑健指数付け [素朴反復の誤収束] を回避)。`insitu.phaseid` の
    `cell_refiner` (`PhaseIdConfig.refine_new_phase_cell` 既定 ON) で物質化 CIF を異方セルに置換。等方歪み補正
    (`materialize(strain=)`) の上位互換。**検証**: alpha を delta と同じ誤差プロファイル (a+0.4% b+0.8% c+3.4%)
    で摂動し実測 frame030 から真セルへ回復 (c 誤差 0.50→0.01 Å)。
  - **転移フレーム (frame270) は追加で難しい**: 実測 Jana delta でも ~30% (frame quality + 98%delta/
    2%alpha 混合)。clean frame (420) の 13.48% とは別要因。
  - **代替**: 実測 delta 構造 (同梱 `delta_CaTeO3.cif`) をローカル参照供給元にすれば DFT 問題を回避し
    clean フレーム 13% 級 (COD/ICSD は [Issue #10])。**同定・単一フレーム収束 (frame0/frame420 とも ~13%)・
    逐次配線・異方セル補正 (Issue #20) は達成済**。残る tutorial 級 (~9%) との差は preferred orientation + 水素の未モデル分。
- **operando warm-start (Issue #28 T6-B) の実 MP+GSAS A/B 検証 (2 フレーム, MATERIALS_PROJECT_API)**:
  frame030 (alpha 単相) + frame180 (alpha+delta 共存) を逐次実 GSAS 精密化し、frame180 で **MP から
  delta (mp-1195263, CaTeO3) を自動同定・物質化・追加**。`PhaseIdConfig.warm_start_known_phases` で
  現行相 alpha を精密化格子付き `ReferencePhase` に変換し `identify_pattern(known_phases=)` へ渡して
  **先に残差から減算**してから新相を探す (identify-all-then-exclude の格上げ)。同一設定で A/B 比較:

  | | frame0 (alpha) | frame1 (共存): Rwp / GOF / delta 分率 / validity | delta ID |
  |---|---|---|---|
  | A static (`warm_start_known_phases=False`) | 12.57% | 33.57% / 3.66 / 0.392 / False | mp-1195263 ✓ |
  | **B warm-start** (既定 True) | 12.57% | 33.45% / 3.62 / **0.468** / **True** | mp-1195263 ✓ |

  両者とも delta を MP から自動同定・採用 (ledger verify True)。**warm-start B は delta 分率が真値
  (~50/50 共存) に近く (0.468 vs 0.392)・物理妥当性 pass (True vs False)・Rwp/GOF も僅かに良い** — 「現
  フレーム精密化格子で先に減算 → 残差がクリーン → 少数相の定量が改善」という設計主張と整合。frame1 の
  絶対 Rwp ~33% は転移共存フレーム固有の難しさ (preferred orientation + 水素 + 混合相; 上記 frame270 と
  同種) で A/B 共通・パイプライン欠陥ではない。**再現**: `scratchpad/cateo3_full_mp_gsas.py [--static]`
  (MP キーは `.env` から読込, GSAS 実行)。
- **全 14 フレーム (Data.zip 全配置) の検証 (Issue #28 ①)**: 全 14 フレーム (ax 30–420) を配置し実行
  (`scratchpad/cateo3_full14_mp_gsas.py`, XRDML は `scratchpad/cateo3_frames14/` へ Data.zip 展開・gitignore)。
  - **alpha 単相軌跡 (phase-id 無効, 完走)**: 含水 alpha CIF を全 14 フレームに単相フィットした Rwp 軌跡が
    **脱水進行を定量的に捉える**: ax30 **12.57%** → ax90 40.8% → **ax120 57.4%** (含水 alpha が最悪適合) →
    転移で試料低結晶化 (ax150 で max intensity 4059→909) → delta 域 ax300–420 で ~54% plateau。
    単相経路は全系列ハングなしで完走 (`--no-phaseid`)。
  - **全系列 + MP 相同定はハング (→ [Issue #33](https://github.com/tomooki/tsumugin/issues/33))**: 転移域
    フレーム (ax≈150 付近) の **2 相 (alpha+delta) GSAS 精密化が単一 LSQ/SVD サイクル内でハング** (near-
    singular; `masked→nan`・`invalid divide`・shift/esd 発散)。順方向・逆伝播 consolidation 双方で発生、
    `max_cyc` 圧縮でも解消せず。**alpha 単相全系列は完走**するので**ハングは 2 相精密化に固有**で M9/M11 の
    numpy 制御ロジックの問題ではない (GSAS 呼び出し自体のハングは崩壊ガードが精密化後にしか効かない)。
    修正案は GSAS 精密化のウォッチドッグ (タイムアウト→chi2=inf 変換, CLAUDE.md 不変条件と整合) 等
    (Issue #33)。→ **全系列一括完走はブロック**されるが、**delta 自動同定能力・warm-start 効果の検証は
    2 フレーム版で達成済** (上記)。
- **numpy コア**: XRDML ローダー・model・parametric・phaseid・逐次エンジン制御・MCP は GSAS/MP 非依存に
  決定論テスト green (`tests/insitu/`, `tests/mcp/test_insitu_tools.py`)。
