# M11 逐次減算同定 (単相/多相の統一エントリ) 要件定義 (EARS)

対象: `tsumugin.reference.iterative` (新規: `identify_pattern`) + `reference.significance` (`insitu.residual`
昇格) + 非負スケール joint フィット + `chem` 降格 prior 配線。仕様 (正) `docs/tsumugin_spec_v0.3.md`
**FR-118 (1〜7)**。既存 `identify_phases` (rerank/化学) ・`identify_phase_mixtures` ・`residual_significance`
・`ReferenceBackend` プロファイル合成・`group_by_composition` を再利用。

## 0. 背景 — なぜ統一が必要か

未知の XRD パターンを相同定するとき、**単相か多相かは事前に分からない**。現状は入口が2つ (`identify_phases`
単相ランキング / `identify_phase_mixtures` 多相木探索) で、ユーザーが相数を知っている前提になっている。
実測でこの欠陥が顕在化:
- 多相木探索は**全パターンに対して各相をスコア**するため少数相が希釈され (検出限界 15–30%)、calcite が rank 12 に沈む。
- 単相の武器 (異方 rerank・化学ガード) が多相側に無く、フル同定で graphite (元素部分集合) が混入する。

一方、本セッションの検証で **残差ベース同定は clean 残差なら正解相を rank 1 で当てる** ことが確認済。静的混合は
共変質のない stable host なので、残差反復 (search-match-subtract) で単一エントリに統一できる。

## 1. ユーザーストーリー

- 研究者として、**相数を指定せず**パターンと元素だけを渡せば、単相でも多相でも同じ関数で相集合を同定してほしい。
- 少数相 (5–20%) も、主相を減算した後の残差で**検出限界を下げて**同定してほしい。
- 元素部分集合の偶然マッチ (graphite 等) を、恣意的な除外でなく**残差で説明できないから**という物理根拠で排除してほしい。
- 同組成多形 (calcite vs aragonite) の厳密判別は、探索でなく**実 Rietveld へ委譲**する旗を立ててほしい。

## 2. 機能要件 (EARS)

### 2.1 単一エントリと反復 (FR-118-1/2)
- **REQ-1101** `identify_pattern(two_theta, intensity, provider, elements, known_phases=())` は、受理相集合・
  最終残差・未知相レポート・反復履歴を持つ `IterativeIdentification` を返さねばならない。相数の事前指定を要求しない。
- **REQ-1102** システムは、前処理で SNIP 背景減算・`find_peaks`・計数統計 σ (√raw) 推定を行い、`known_phases`
  があればそのモデルを joint スケール fit して残差から先に減算せねばならない (operando warm-start 点)。
- **REQ-1103** システムは反復 k=1..max_phases で、現残差に `identify_phases` を実行し (異方 rerank 既定 on・
  背景減算・動的閾値)、候補提案を得ねばならない。
- **REQ-1104** システムは、提案上位 K を順に、**全採用相 + 候補**のプロファイルを原パターンへ**非負スケール
  最小二乗**で joint 再フィットし、未説明強度 (正残差の二乗和) が相対 `eps_gain` 超減る候補のみ受理せねばならない。
- **REQ-1105** システムは、受理後に残差 = 原パターン − Σ 採用相の (スケール×プロファイル) を再計算せねばならない
  (貪欲減算の誤差蓄積を避け毎回原パターンから)。

### 2.2 停止と decoy 棄却 (FR-118-3/4)
- **REQ-1106** システムは、残差の `residual_significance().max_snr` が `snr_stop` 未満になったら反復を停止
  せねばならない (全て説明済)。単相パターンは k=1 で自然停止せねばならない。
- **REQ-1107** システムは、周回で受理候補が 0 (全棄却) なら停止せねばならない。
- **REQ-1108** システムは、既説明ピークしか持たない候補 (元素部分集合の decoy 等) を、joint 再フィットで
  スケール≈0 → `eps_gain` 未達により**自然棄却**せねばならない (hard 除外でない)。
- **REQ-1109** システムは化学妥当性を `chem` の**降格 prior** としてスコアに合成せねばならず、候補を除外しては
  ならない (Dara 教訓, P2)。全元素系 hard ガードは operando 限定の opt-in とする。

### 2.3 多形と委譲 (FR-118-5)
- **REQ-1110** システムは、受理相の同組成競合を `group_by_composition` で代替候補として保持せねばならない。
- **REQ-1111** システムは、受理相集合に僅差の同組成多形 (score 差 < `polymorph_margin`) が含まれるとき、
  **「実 Rietveld で確定せよ」**のエスカレーション旗を出力に立てねばならない (pseudo-R では多形判別不可)。

### 2.4 operando 一本化・非破壊・決定論 (FR-118-6/7)
- **REQ-1112** `insitu.phaseid.identify_new_phases` は `identify_pattern(known_phases=現行相集合)` に委譲でき、
  同一プリミティブで静的 (空起点) と逐次 (既知起点) を扱えねばならない (段階移行, 後方互換シム可)。
- **REQ-1113** システムは、全反復・各候補の受理/棄却・スケール・残差 S/N を ledger に追記せねばならない (P2)。
- **REQ-1114** システムは乱数を用いず、同一入力でビット同一の受理相集合・順序を返さねばならない (NFR-102)。

## 3. 非機能要件

- **NFR-M11-1** コア (`identify_pattern`・非負スケール LSQ・残差評価) は **numpy-only**。pymatgen/GSAS は
  供給元/物質化の遅延 import 境界の内側に留める。
- **NFR-M11-2** テストは実装ファイルと 1:1。単相縮退・decoy 棄却・joint rescale・停止・決定論を stub 供給元で
  green。実データ (CandAt/PbSO4) は `@pytest.mark.mp`。
- **NFR-M11-3** import 方向を保つ: `reference` は `insitu` を読めないため `residual_significance` を
  `reference.significance` へ昇格し、`insitu.residual` は re-export で後方互換にする。

## 4. スコープ外 (M-later)

- 多形の厳密判別 (実 Rietveld へ委譲, FR-200/M7)。
- プロファイル形状の精密化 (本 M11 は固定 FWHM 合成; 形状最適化は Rietveld 側)。
- ピーク重なりが激しい系の deconvolution 高度化 (初版は非負スケール LSQ)。
- `identify_phase_mixtures` の廃止 (本 M11 は**受理集合+代替の小プールでの組合せ検証**用途に再配置し残す)。

## 5. 受け入れ基準 (検証データ)

- **AC-1** CandAt × MP 全 169 候補 (現状 graphite 混入で失敗): `identify_pattern` が **calcite + aragonite を
  受理し graphite を棄却**する (残差支持による自然棄却)。
- **AC-2** PbSO4 実測 (単相): **k=1 で停止**し偽 2 相目を出さない (snr_stop を実データ校正)。
- **AC-3** minority_probe (合成): 減算後の少数相検出限界が単発 15% から**大幅低下**する。
- **AC-4** 決定論: 同一入力で受理相集合がビット同一 (NFR-102)。単相縮退で M6 単相結果と整合。
