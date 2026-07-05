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
  4. **背景 24 項** (実験室 X 線は背景が複雑; 既定 6 では不足)。
  5. **X,Y (Lorentzian) + Zero プロファイル解放** (U,V,W のみでは 43%; +X,Y,Zero で 19%→13%)。
     → M7 `_profile_keys` を X 線で U,V,W,X,Y,Zero に拡張 (revert ガードで M7 T1–T4 は非回帰)。
  残差 13→9.4% は preferred orientation (テクスチャ) + 水素 (X 線で微小) の未モデル分。
- **numpy コア**: XRDML ローダー・model・parametric・phaseid・逐次エンジン制御・MCP は GSAS/MP 非依存に
  決定論テスト green (`tests/insitu/`, `tests/mcp/test_insitu_tools.py`)。
