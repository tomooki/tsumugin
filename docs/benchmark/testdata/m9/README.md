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
- `alpha_CaTeO3_H2O.cif`: Jana `.m40/.m50` から変換した初期相 (P1 展開・水素略・X 線)。**注意**: P1
  展開のため対称拘束が緩い。tutorial 相当には真の空間群 CIF が望ましい (改善余地)。
- `delta_CaTeO3.cif`: delta 無水相 (自動同定のローカル代替/正解確認用。primary は MP 自動同定)。
- 全 14 フレームは元 `Data.zip` (`Example 02.6_ CaTeO3 cyclic/Data.zip`) から取得。

## cucr2o4/ — GSAS-II "Parametric sequential fitting" (CuCr₂O₄+CuO, 新相なし)

出典: https://github.com/AdvancedPhotonSource/GSAS-II-tutorials (`SeqRefine/data/SeqTut.zip`)。
11-BM 放射光 (.fxye)。17 フレーム (`OH_00`〜`OH_53`) 7–300K。CuCr₂O₄ (Fddd) + CuO 不純物相。
**新相出現なし** (2 次転移で b→c 収束; 相集合は一定)。パラメトリック解析 (格子 vs T・b/c 比) が主。

- チュートリアル最終値: 各フレーム wRp ~13–17% / GOF ~1.1。
- 同梱: `CuCr2O4.cif`, `CuO.cif`, `OH_00.prm` (装置), `OH_00.fxye` (先頭フレーム)。残り 16 フレーム
  (`OH_04`〜`OH_53.fxye`) は上記 `SeqTut.zip` から取得。

## 検証状況 (honest status)

- **配線 (end-to-end)**: CaTeO3 2 フレームの逐次実行を確認済 — GSAS 駆動・ウォームスタート格子伝播・
  XRDML→XYE 自己変換 (GSAS の optional xmltodict 不要)・ledger `verify()` True。
- **Rwp 収束**: 現状 frame0 Rwp ~70% (tutorial ~9%)。主因は (i) 初期相 CIF の P1 展開 (真の空間群未指定)、
  (ii) 装置プロファイル (INST_XRY.PRM は fluoroapatite 由来で本回折計と不一致)、(iii) 背景項数/低角
  リミット。M7 が T1–T4 で示した通り、各データセットの Rwp 収束は装置/背景/リミットの反復調整を要する
  (`tests/insitu/test_engine_gsas.py` の目標帯を段階的に締める)。
- **numpy コア**: XRDML ローダー・model・parametric・phaseid・逐次エンジンの制御ロジック・MCP は
  GSAS/MP 非依存に決定論テストで green (`tests/insitu/`, `tests/mcp/test_insitu_tools.py`)。
