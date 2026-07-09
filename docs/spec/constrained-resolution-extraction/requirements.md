# パラメータ物理拘束付き分解能抽出 (constrained-resolution-extraction) 要件定義書

## 概要

Issue #38 の `extract_instrument_profile` (PR #39) は標準試料を**無拘束**で精密化するため、CeO2 の超シャープ
ピークが擬 Voigt を**相関した非物理解**に引き込む (実測: Y=-5.32)。この解は CeO2 自身 (低角ピーク支配) には
Rwp 8.88% で合うが、**総 FWHM が 2θ>32° で負**になり、別試料 (NaCuHCF, 全域に反射) へ**転写すると破綻**する
(負のピーク幅で反射スキップ・Rwp 18.7%)。

対策として、装置プロファイル係数を**非負拘束** (U,W,X,Y ≥ 0) して抽出する。実測で **U,W,X,Y≥0 拘束は
CeO2 Rwp 9.06% (無拘束 8.88% と同等) かつ全域 FWHM 正の転写可能解** (U=0,V=1.81,W=0.96,X=0.41,Y=0) を与え、
NaCuHCF joint に固定して **Rwp 15.25% を k=46 (無拘束 baseline 48) で honest 達成** (ΔBIC≈-18 有利)。

## 関連
- Issue #38 / PR #39 (装置分解能の抽出・固定)。GSAS parmMin/parmMax は既存の占有率 [0,1] 拘束と同機構
  (`_bound_occupancy`)。設計/知見は [[instrument-resolution-fix]] メモリ。

## 機能要件 (EARS)

**【凡例】** 🔵 確実 / 🟡 妥当な推測

### 通常要件
- REQ-001: システムは `HistogramSpec.profile_bounds` (省略可, GSAS 装置キー→(min,max)) を提供し、指定時は
  当該ヒストグラムの装置パラメータに GSAS parmMin/parmMax 拘束を登録しなければならない 🔵 *set_Controls*
- REQ-002: システムは `extract_instrument_profile` に `constrain_nonneg` (既定 True) を設け、True のとき
  U,W,X,Y を非負 (≥0) 拘束して抽出しなければならない (転写可能な分解能を既定にする) 🔵 *CeO2 実測*
- REQ-003: `extract_instrument_profile_from_standard` は `constrain_nonneg` を透過しなければならない 🔵

### 条件付き要件
- REQ-101: `profile_bounds` の各 (min,max) について、min が None なら parmMin を登録せず、max が None なら
  parmMax を登録してはならない (片側拘束を許容) 🔵
- REQ-102: `profile_bounds` 未指定 (None) のヒストグラムは拘束を登録してはならない (後方互換) 🔵 *非回帰*
- REQ-103: joint (多ヒストグラム) では拘束は**当該ヒストグラムの変数名** (`:{hist_index}:{key}`) にのみ
  適用されなければならない 🔵 *per-hist 独立*

### 制約要件
- REQ-401: `profile_bounds` 場・拘束変数名の組立・`constrain_nonneg`→bounds 写像は numpy コアで
  GSAS 非依存 (実際の set_Controls は engine の GSAS 経路) 🔵 *CLAUDE.md*
- REQ-402: 決定論・frozen dataclass・既存 T1〜T4/joint 非回帰 (profile_bounds 既定 None) 🔵
- REQ-403: 古い GSAS で parmMin/parmMax 未対応でも精密化継続 (拘張のみ諦める, `_bound_occupancy` 流儀) 🔵

## Edgeケース
- EDGE-001: `profile_bounds` に instprm 非存在キー → set_Controls が無視/例外なら try で握り継続 🔵
- EDGE-002: `constrain_nonneg=True` かつ呼出側が既に `profile_bounds` 指定 → 非負 bounds をマージ
  (呼出側の明示指定を優先) 🟡
- EDGE-003: V, SH/L は非負拘束の対象外 (V は Caglioti 交差項で負が正常・SH/L は非対称) 🔵
