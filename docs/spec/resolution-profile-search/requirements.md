# 分解能プロファイルの物理候補探索 (resolution-profile-search) 要件定義書

## 概要

PR #40 の非負拘束抽出は物理解を与えるが、**Y=0 の境界解**に張り付く (境界クランプ)。実測で判明した事実:
(1) **自由精密化は初期値に依らず必ず非物理解 (Y<0・FWHM 負) に落ちる** — 非物理領域が大域アトラクタで
素朴な初期値探索は無効。(2) 物理拘束下では **Rwp がほぼ平坦で Y は不定** — CeO2 の超シャープピークで
擬 Voigt が病的に過剰決定される。

そこで**物理的な候補プロファイルを探索して最良フィットを選ぶ**: 非負拘束抽出で得た物理解をアンカーに、
周辺の候補プロファイルを生成し、各候補を**固定して scale/bg/cell のみ精密化**して Rwp を評価、
**総 FWHM>0 (転写可能) の候補から Rwp 最小**を選ぶ。境界クランプを避け真の最良物理解を得る。

## 関連
- PR #37/#39/#40 (物理性ガード・分解能抽出・非負拘束)。固定評価は既存 `instrument_profile` を再利用。
  知見は [[instrument-resolution-fix]] メモリ。

## 機能要件 (EARS)

**【凡例】** 🔵 確実 / 🟡 妥当な推測

### 通常要件
- REQ-001: システムはプロファイル値から GSAS getFWHM 準拠の**総ピーク FWHM** を計算する純関数
  (`profile_total_fwhm` / `profile_fwhm_min`) を提供しなければならない (物理性=全域 FWHM>0 の判定用) 🔵 *GSAS getFWHM*
- REQ-002: システムは物理アンカーの周辺に候補プロファイル群を生成しなければならない (W,X,Y を係数で摂動) 🔵
- REQ-003: システムは `search_instrument_profile` を提供し、各候補を**固定** (instrument_profile) して
  scale/bg/cell のみ精密化した Rwp で評価、**総 FWHM>0 の候補から Rwp 最小**を `InstrumentProfile` で返さ
  なければならない 🔵 *物理候補探索*

### 条件付き要件
- REQ-101: アンカー未指定時、システムは非負拘束抽出 (`extract_instrument_profile(constrain_nonneg=True)`)
  でアンカーを求めなければならない 🔵
- REQ-102: 総 FWHM が全域で正でない候補は選定から除外しなければならない (転写可能性の担保) 🔵
- REQ-103: 物理候補が 1 つも無い場合、システムはアンカー (非負拘束解) を返さなければならない (安全網) 🔵
- REQ-104: `extract_instrument_profile_from_standard(search="grid")` は生データから探索を実行しなければならない 🔵

### オプション要件
- REQ-301: 探索手法は grid (既定) の他、注入した optimizer で Bayesian 等に差し替え可能にしてよい 🔵 *pluggable*
- REQ-302: グリッド係数・FWHM 評価レンジ・SH/L 解放を引数で調整可能にしてよい 🔵

### 制約要件
- REQ-401: `profile_total_fwhm`/候補生成/最良選定は numpy コアで GSAS 非依存。固定評価の精密化のみ
  run_auto_rietveld 経由 (GSAS 遅延)。runner/optimizer 注入で決定論テスト可能 🔵 *CLAUDE.md*
- REQ-402: grid 探索は決定論 (NFR-102)。候補順・選定は入力から一意 🔵
- REQ-403: 既存 T1〜T4/joint 非回帰 (探索は opt-in の新関数・既存経路不変) 🔵

## Edgeケース
- EDGE-001: 候補の固定評価が失敗 (例外/inf) → 当該候補を除外し継続 🔵
- EDGE-002: アンカーの values が空 → 探索不能につきアンカーをそのまま返す 🟡
- EDGE-003: FWHM 評価レンジで tanθ 発散 (2θ→180°) → クランプ (既存 _gauss_min_over_range 流儀) 🔵
