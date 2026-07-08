# プロファイル物理性ガード (profile-physicality-guard) 要件定義書

## 概要

自動 Rietveld のプロファイルパラメータ (CW: U,V,W / X,Y / SH·L, TOF: sig-0/1/2, alpha, beta-0/1) は、
強度比が合っていない収束前状態から段階解放すると**非物理値に走りやすい** (XND joint 解析で判明)。
現状の段階解放エンジンは revert 判定が **Rwp 単独** (`engine.py:635`) + 格子崩壊ガード
`_cells_physical` (`engine.py:79`) のみで、プロファイルが非物理でも Rwp が下がれば採用されてしまう。

本要件は、`_cells_physical` と**同格の物理ガード** `_profiles_physical` を追加し、
「トライ → **非物理なら revert**」の核心原理をプロファイルにも適用する。判定は**材料非依存の物理法則**
= 幅関数の測定レンジ全域での正値性で行い、材料固有の結論は埋め込まない (過度な一般化の禁止)。
併せて、TASK-0001 で追加済だが engine 未配線の内省フィールド `AutoRietveldResult.hist_profile` を
充填し、`diagnose_residual` (M8 診断) が実プロファイル値を使えるようにする。

## 関連文書

- **ヒアリング記録**: [💬 interview-record.md](interview-record.md)
- **ユーザストーリー**: [📖 user-stories.md](user-stories.md)
- **受け入れ基準**: [✅ acceptance-criteria.md](acceptance-criteria.md)
- **一般化フロー**: `docs/reference/serious-refinement-flow.md`
- **診断拡張 (前段)**: `docs/design/refine-loop-diagnostics/GAP_ANALYSIS.md`

## 機能要件（EARS記法）

**【信頼性レベル凡例】**:
- 🔵 **青信号**: GSAS-II プロファイル定義・既存実装・ユーザ入力設計を参考にした確実な要件
- 🟡 **黄信号**: 妥当な推測による要件
- 🔴 **赤信号**: 資料にない推測による要件

### 通常要件

- REQ-001: システムは各ヒストグラムの GSAS `Instrument Parameters`
  (`[0][key] = [default, value, refine_flag]`) から現在のプロファイル値と解放フラグを抽出し、
  `AutoRietveldResult.hist_profile` に `{key: value}` の Mapping として格納しなければならない 🔵 *ユーザ入力設計(1)*
- REQ-002: システムは CW ガウス幅 `H_G² = U·tan²θ + V·tanθ + W` が測定 2θ レンジ全域で正 (>0) か
  判定しなければならない。判定はレンジ端点および頂点 (`tanθ* = -V/2U`, レンジ内のときのみ) で行う 🔵 *ユーザ入力設計(2)/Caglioti*
- REQ-003: システムは CW ローレンツ係数 X, Y が非負 (≥ 0) か判定しなければならない 🔵 *ユーザ入力設計(2)*
- REQ-004: システムは非対称パラメータ SH/L が 0 以上か判定しなければならない 🔵 *ユーザ入力設計(2)*
- REQ-005: システムは TOF ガウス分散 `σ² = sig-0 + sig-1·d² + sig-2·d⁴` が d レンジ全域で非負 (≥ 0) か
  判定しなければならない 🔵 *ユーザ入力設計(2)*
- REQ-006: システムは TOF の立上り/減衰係数 alpha, beta-0, beta-1 が正 (> 0) か判定しなければならない
  (式中 `1/alpha`, `1/beta` でゼロ近傍発散するため) 🔵 *ユーザ入力設計(2)/T4 教訓*

### 条件付き要件

- REQ-101: プロファイル物理ガードに違反した段階が検出された場合、システムは当該段階を非物理とみなし
  `rwp = gof = inf` に変換して、既存の revert 経路 (`engine.py:635`) に処理させなければならない 🔵 *ユーザ入力設計(3)*
- REQ-102: あるパラメータが**解放されていない (refined=False)** 場合、その個別係数の符号違反 (X<0 等) を
  revert 判定に用いてはならない (初期 instprm の borderline 値による誤 revert を防ぐ) 🔵 *ユーザ入力設計(2) 誤revert防止*
- REQ-103: soft 上限 (過大な SH/L 等) を超えたが hard 物理制約は満たす場合、システムは revert せず
  `ValidityReport.warnings` に記録しなければならない 🔵 *ユーザ入力設計(4) 第2層*

### 状態要件

- REQ-201: 現在の段階がプロファイル関連フラグ (`profile` / `profile_lorentzian` / `profile_asymmetry` /
  `tof_profile`) を解放している状態のとき、システムはその段階適用・精密化後にプロファイル物理性を
  検査しなければならない 🔵 *ユーザ入力設計(3)/engine recipe*
- REQ-202: 幅関数正値性 (REQ-002/005) は、パラメータの解放有無に依らず常に評価してよい (物理法則のため)。
  ただし未解放かつ初期 instprm 由来で違反した場合は revert でなく警告に留める 🟡 *REQ-102 との整合から妥当な推測*

### オプション要件

- REQ-301: システムはプロファイル物理性の許容閾値 (符号 tol・SH/L soft 上限) を引数で調整可能にしてよい 🔵 *validity.py の既存 tol 引数流儀*

### 制約要件

- REQ-401: `check_profile_physicality` は **numpy のみ**に依存し GSAS-II 非依存の純関数でなければならない
  (validity.py に配置) 🔵 *CLAUDE.md「numpy コア + GSAS 遅延 import」*
- REQ-402: 全変更は決定論的でビット同一を保たねばならない 🔵 *NFR-102*
- REQ-403: engine のガード追加は `_cells_physical` と**同じ扱い**で、accept/revert の基本構造
  (段階ループ・スナップショット復元) を変更してはならない 🔵 *ユーザ核心原理「エンジン不変」*
- REQ-404: T1〜T4 の実 Rietveld テスト (`@pytest.mark.gsas`) は非回帰でなければならない 🔵 *CLAUDE.md M7 教訓*

## 非機能要件

### パフォーマンス

- NFR-001: 抽出・判定は `O(ヒストグラム数 × パラメータ数)` で、精密化1サイクルに対し無視できる 🔵 *アルゴリズム自明*

### 再現性

- NFR-101: 乱数・浮動小数の非決定を持ち込まず、同一入力で同一 `hist_profile`・同一 revert 判定を返す 🔵 *NFR-102*

### 保守性

- NFR-201: 物理性判定ロジックは validity.py に集約し、engine は抽出と1行ガードのみを担う (責務分離) 🔵 *既存 _cells_physical パターン*

## Edgeケース

### エラー処理

- EDGE-001: `hist_profile` が空 / 抽出不能 (キー欠落・GSAS 構造差) の場合、判定を skip して
  `passed=True` に縮退する (revert しない) 🔵 *check_bond_validity の縮退流儀*
- EDGE-002: 2θ = 90°/180° 近傍で `tanθ`/`1/cosθ` が発散する場合、評価点を安全域にクランプするか
  当該点をスキップし、数値例外を出してはならない 🟡 *数値安定から妥当な推測*
- EDGE-003: TOF で d レンジが不明な場合、`difC` から 2θ↔d 換算するか、d レンジが得られなければ
  当該ヒストグラムの TOF 判定を skip する 🟡 *difC 直写像 (interop) から妥当な推測*

### 境界値

- EDGE-101: `two_theta_limits = None` (全域) のとき、実測データの 2θ 最小・最大を評価レンジに用いる 🔵 *HistogramSpec 既定*
- EDGE-102: 頂点 `tanθ* = -V/2U` がレンジ外のとき、頂点評価を省き端点のみで正値判定する 🔵 *2次関数の単調性*
- EDGE-103: U = 0 (頂点非存在, 線形) のとき、端点評価のみで判定する 🔵 *2次→1次退化*
