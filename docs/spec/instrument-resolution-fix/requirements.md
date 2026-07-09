# 装置分解能関数の抽出・固定 (instrument-resolution-fix) 要件定義書

## 概要 (Issue #38)

CW 装置プロファイル (U,V,W / X,Y / SH·L) を試料精密化で自由解放すると、装置由来と試料由来の広がりが
**相関して分離できず**、良好 Rwp でも個々の値が非物理・不安定になる (PR #37 で判明: T1 は U=-1.96 に収束)。

対策として **標準試料 (NIST SRM 674b CeO2 等) から装置分解能関数を実測抽出**し、試料精密化では
**装置プロファイル一式を固定**して、試料由来の広がりは size/mustrain のみで担わせる。

**CeO2 実測で確認 (直接 GSAS)**: シャープな放射光ピークは **Lorentzian 支配** — U,V,W のみでは Rwp 20%
(U=-10 に暴走)、X,Y を足すと 9.6% に激減。U↔X,Y は強相関。よって **Gaussian のみ固定では不十分**で、
装置プロファイル一式 (U,V,W,X,Y,SH/L) の固定が必要 (ユーザ確定)。

## 関連文書
- **設計**: [architecture.md](../../design/instrument-resolution-fix/architecture.md) /
  [interfaces.py](../../design/instrument-resolution-fix/interfaces.py)
- PR #37 (プロファイル物理性ガード, `H_G²<0` 警告の動機)、Issue #38。

## 機能要件 (EARS)

**【凡例】** 🔵 確実 / 🟡 妥当な推測 / 🔴 資料にない推測

### 通常要件
- REQ-001: システムは**標準試料の分解能関数**を保持する不変データ型 `InstrumentProfile`
  (GSAS キー→値の Mapping + 出典 Rwp + 波長) を提供しなければならない 🔵 *ユーザ確定*
- REQ-002: システムは標準試料データ+構造から装置分解能を抽出する `extract_instrument_profile` を
  提供しなければならない。抽出は **size/mustrain を解放しない**専用レシピ (背景→cell→W→U,V,W→U,V,W,X,Y→
  (任意)SH/L の段階解放) で行い、結果の `hist_profile` から U,V,W,X,Y,SH/L を返す 🔵 *CeO2 実測で確立した順序*
- REQ-002b: システムは**生の 2 列標準試料データ (.dat) 1 ファイルから**装置分解能を一括再現する
  `extract_instrument_profile_from_standard` を提供しなければならない。2 列読込 (Poisson esd 付与)・
  標準参照構造 (CeO2/Si 内蔵)・PXC instprm 生成を内包し、決定論的に `InstrumentProfile` を返す
  (scratchpad の手作業を再現可能な関数に集約) 🔵 *ユーザ要望「再現可能なように別関数化」*
- REQ-003: システムは `HistogramSpec.instrument_profile` (省略可) を提供し、指定時はその値を
  GSAS instprm に seed しなければならない 🔵 *ユーザ確定*

### 条件付き要件
- REQ-101: `instrument_profile` が指定されたヒストグラムについて、システムは段階解放で
  **U,V,W / X,Y / SH·L を解放してはならない** (固定)。試料由来の広がりは size/mustrain が担う 🔵 *ユーザ確定*
- REQ-102: `instrument_profile` が **未指定** のヒストグラムは従来どおり U,V,W 等を解放する (後方互換) 🔵 *非回帰*
- REQ-103: joint (多ヒストグラム) で一部のみ `instrument_profile` 指定時、固定は**当該ヒストグラムのみ**に
  適用され、他ヒストグラムの解放に影響してはならない 🔵 *per-hist 独立*

### オプション要件
- REQ-301: `extract_instrument_profile` は SH/L 解放の有無・背景項数・レンジを引数で調整可能にしてよい 🔵
- REQ-302: `extract_instrument_profile` は runner 注入可能にしてよい (決定論テスト用) 🔵 *compare_models 流儀*

### 制約要件
- REQ-401: `InstrumentProfile`・レシピ組立・固定判定・seed 値マッピングは numpy コアで GSAS 非依存 (遅延 import) 🔵 *CLAUDE.md*
- REQ-402: 決定論 (NFR-102)・frozen dataclass・`with_updates` 流儀。既存 T1〜T4 非回帰 (instrument_profile 既定 None) 🔵

## Edgeケース
- EDGE-001: `instrument_profile.values` に一部キーのみ (例 SH/L 欠落) → 存在するキーのみ seed/固定 🔵
- EDGE-002: 抽出で `hist_profile` にキーが無い → `InstrumentProfile.values` から除外 🔵
- EDGE-003: TOF ヒストグラムに `instrument_profile` (CW 用) 指定 → CW キーのみ扱い、TOF 解放には影響しない 🟡
