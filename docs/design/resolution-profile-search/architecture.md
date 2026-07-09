# 分解能プロファイルの物理候補探索 アーキテクチャ設計

**作成日**: 2026-07-09 / **要件**: [requirements.md](../../spec/resolution-profile-search/requirements.md)

**【凡例】** 🔵 確実 / 🟡 妥当な推測

## 概要 🔵
物理拘束解をアンカーに候補プロファイルを生成し、各候補を固定して軽量精密化 (scale/bg/cell) で Rwp 評価、
総 FWHM>0 の候補から Rwp 最小を選ぶ。固定評価は既存 `HistogramSpec.instrument_profile` を再利用。

## 実測に基づく設計判断
- **DD-1**: 自由精密化は初期値に依らず非物理解へ (大域アトラクタ)。→ 素朴な初期値探索でなく**物理候補を
  固定評価**する。物理候補は総 FWHM>0 で構成/フィルタするので選定結果は必ず転写可能 🔵
- **DD-2 (アンカー)**: 非負拘束抽出 (PR #40) の物理解を中心に周辺探索。スケールが試料/装置依存でも
  データ由来のアンカーに追随でき汎化する 🔵
- **DD-3 (摂動対象)**: Lorentzian X (主成分)・Gaussian W・Lorentzian Y を係数/オフセットで摂動。V は
  交差項・U は小さいので固定 🟡
- **DD-4 (評価)**: 候補を instrument_profile 固定 → recipe=[bg,cell] で精密化 (profile は skip) → Rwp。
  プロファイルは動かず「その分解能の当てはまり」を公平に測る 🔵
- **DD-5 (pluggable)**: 既定 grid。`optimizer` 注入で Bayesian (skopt 遅延等) に差し替え可 🔵

## コンポーネント
| モジュール | 役割 | 依存 |
|---|---|---|
| `resolution.profile_total_fwhm(values, tt)` | GSAS getFWHM 準拠の総 FWHM (numpy) | numpy |
| `resolution.profile_fwhm_min(values, lo, hi, n)` | レンジ区間最小 (物理性判定) | numpy |
| `resolution.candidate_profiles(anchor, ...)` | アンカー周辺の候補生成 (grid) | numpy |
| `resolution.search_instrument_profile(...)` | アンカー→候補→FWHM 正フィルタ→固定評価→最良 | run_auto_rietveld 経由 (GSAS 遅延) |

## データフロー
```
search_instrument_profile(standard, structure)
  → anchor = extract_instrument_profile(constrain_nonneg=True)      # 物理アンカー (numpy+GSAS)
  → cands  = candidate_profiles(anchor.values)                      # numpy
  → 各 cand: fwhm_min>0 か (numpy) → 固定評価: run([replace(standard, instrument_profile=cand)], recipe=[bg,cell])
             → Rwp                                                   # GSAS
  → 物理候補のうち Rwp 最小を InstrumentProfile で返す (無ければ anchor)
```

## 非回帰 🔵
探索は opt-in の新関数群。既存 extract/固定/T1〜T4 経路は不変。固定評価は既存 instrument_profile 機構の再利用。

## 決定論・境界 🔵
profile_total_fwhm・候補生成・最良選定は numpy 決定論。runner/optimizer 注入で GSAS 非依存テスト。
候補評価失敗は除外し継続 (EDGE-001)。tanθ 発散はクランプ (EDGE-003)。
