# AI エージェント operando 系列 診断・モデル改訂 指示書 (AGENT_PLAYBOOK)

対象: **非 Claude ハーネス** (Codex 等) を含む任意の ③ 判断層。Claude Code は
`plugins/tsumugin/skills/operando-diagnose/SKILL.md` を使う (内容は本書と同一)。
**MCP (②) が共有ポータブル核**であり、③ の実体が何であっても駆動手順は変わらない。

設計: `docs/design/operando-diagnosis/architecture.md`。
根拠データ: K₂Mn[Fe(CN)₆] 放射光電気化学 operando (247 フレーム, λ=0.501345 Å)。
実測値はすべて当該解析で取得したもの。

## 0. この指示書の存在理由 — **Rwp では原理的に検出できない誤り**

実解析で最も重大だった失敗は、**フィット統計がすべて良好なまま物理的に誤った描像**を得たこと:

- 充電域を cubic+tetra の 2 相に限定 (「放電相 mono は充電時に存在しない」という一見妥当な判断)。
- 転移端に残る monoclinic の強度を、計量の近い **tetragonal が肩代わり**。
- 結果:「tetragonal が増減を繰り返す」非物理な描像 (`0.42→0.17→0.70→0.04→0.63`)。
- **Rwp は終始 ~8% と良好**。GOF も validity も警告を出さない。
- 全 3 相を入れ直すと単一ドーム (`0→0.58→0`) に収束 = 正解。
- **発見者は人間の物理的直感**だった。

計量が近い相 (本系は mono/cubic/tetra が全て cubic 派生) は**互いの強度を吸収し合う**。
① の統計量では検出できない。**だから ③ が要る**。

## 1. 前提

- GSAS-II (GSASIIscriptable) 導入済。未導入なら該当ツールが error dict を返す。
- ② の全ツールは**例外を送出せず** `{"error", "error_type"}` へ縮退する。error dict は
  読んで直すこと (**存在しないパスを渡した場合を除く** → Issue #94)。
- 相同定は MP キー (`.env` の `MATERIALS_PROJECT_API` を自動読込, #51)。無ければ CIF 直接指定。

## 2. 手順

### 2.1 データ品質を先に問う (**精密化の前に**)

```python
assess_data_quality(path, data_format="XYE",
                    excluded_regions=[[6.6, 7.6], [23.89, 23.97], [30.0, 41.4]])
# -> {"is_subtracted": true, "confidence": 1.0, "reasons": [...],
#     "suggested_two_theta_limit": 20.5, "recommendation": "..."}
```

- **`is_subtracted=True` → 系列を回す前に生データの有無を人間に問う**。背景減算済 + esd=√I は
  ノイズ底を過大重みし、**同一モデルで Rwp 26% → 生+背景精密化 6.7%**。**fit でなく重み付けの
  問題**であり、気づかず回すと全フレームの Rwp が無意味に高いまま「収束しない」と誤診する。
  **本解析で最大のレバーだった**。
- `suggested_two_theta_limit` を取る際は**寄生ピーク窓を `excluded_regions` で必ず渡す**
  (渡さないとセル由来の反射を信号終端と拾い上限が押し出される — 実測 38.1°)。

### 2.2 系列を回す

```python
sequential_rietveld(
    frames=[{"data_path": f, "axis_value": i, "data_format": "XYE",
             "two_theta_limits": [2.4, 18.0],
             "excluded_regions": [[6.6, 7.6], [12.36, 12.50]]} for i, f in enumerate(files)],
    initial_phases=[{"structure_path": "mono.cif", "phase_name": "mono", "refine_cell": False},
                    {"structure_path": "cubic.cif", "phase_name": "cubic"},
                    {"structure_path": "tetra_real.cif", "phase_name": "tetra", "refine_cell": False}],
    instrument={"path": "kmnfe.instprm", "radiation": "xray_synchrotron",
                "geometry": "debye_scherrer", "background_coeffs": 18,
                "auto_freeze_minor_cells": 0.2},   # ← instrument spec の中。tool の kwarg ではない
    warm_start_fractions=True,
    two_theta_limits=[2.4, 18.0],
)
```

**`instrument` を省略すると実験室 X 線 Bragg-Brentano・背景 6 項の便宜既定になる**
(放射光データでは必ず明示)。実測で効いた設定:

| 設定 | 効果 (実測) |
|---|---|
| 生データ + `background_coeffs=18` | Rwp 26% → **6.7%** (12/24 項は劣る) |
| `two_theta_limits=[2.4, 18.0]` | 30°→18° で **369s→8s** かつ収束改善 |
| 少数相のセル凍結 (`PhaseSpec.refine_cell=False` / `instrument["auto_freeze_minor_cells"]=0.2`) | 解放すると計量相関で発散・分率崩壊 |
| `warm_start_fractions=True` (tool の kwarg) | 分率が初期値に張り付くフレームを是正 (#82) |

> **置き場所に注意** (2 つは階層が違う):
> - `refine_cell` は **`PhaseSpec` のキー** (相ごとの手動凍結。手動が自動に優先する)。
> - `auto_freeze_minor_cells` は **`instrument` spec のキー** (tool のトップレベル kwarg ではない
>   — 直接渡すと `TypeError` が MCP 境界を越える)。サーバが runner を組むときにのみ効く。
>
> `auto_freeze_minor_cells` は**相分率の閾値 (float, 例 0.2)。bool ではない** —
> `True` は `float(True)==1.0` = 全相凍結になる (② が bool を拒否する)。

### 2.3 疑う (**本書の主眼**)

#### J5 相集合の完全性 ★最重要

```python
check_phase_set(result)
# -> {"is_complete": false, "union": [...], "frames_with_missing": [...],
#     "phases": [{"phase": "tetra", "turning_points": 4, "flagged": true}],
#     "seed_pinned": true,
#     "seed_pinned_frames": [{"frame": 125, "rwp": 8.4, "n_phases": 2, "seed_value": 0.5,
#                             "phase_fractions": {"cubic": 0.5, "tetra": 0.5}}]}
```

- **`is_complete=False`** → 「**除外した相の強度を、計量の近い別の相が肩代わりしていないか**」
  を疑う。**和集合で再フィットし相分率を比較**する。**Rwp が良くても信じない**。
- **`flagged=True` (分率が非単調に振動)** → 物理的に妥当かを問う。単調な転移 (A→B→C) が
  自然な系で分率が増減を繰り返すなら、**まず artifact を疑う**。実データではこれが唯一の手がかり。
- **`seed_pinned=True` (相分率が seed に張り付き)** → **そのフレームの分率を報告に使わない**。
  分率が等分 seed (1/相数; 2 相なら 0.500/0.500) に**厳密に一致** = 分率精密化がそのフレームで
  一度も動いていない。**Rwp は平凡なまま** (実測 8.4-8.5%) で `is_complete` にも非単調フラグにも
  出ない (張り付きは「平坦」であって振動ではない) — **厳密な seed 一致が唯一の指紋**。実測
  (K2Mn[Fe(CN)6] 247 フレーム) で 9 フレームが張り付き、**うち 6 連続が転移ドーム頂点の直前**に
  あったため報告したドームの位置と高さが信用できなくなった。→ `repair_frames` で近傍から
  ウォームスタート再フィット (`seed_pinned_frames[].frame` が対象)。**黙って捨てない**
  (可視化して解釈対象から外す判断をユーザーに示す)。

#### J2/J3 残差から欠落相・対称性低下を仮説化

`sequential_rietveld` / `auto_rietveld` の出力には**フレーム毎に `residual_report` が同梱**される
(残差配列は MCP を跨がない — 実測 135KiB/frame・247 frame で 32.6MiB になるため ① 側で畳む)。

```python
result["frames"][i]["residual_report"]
# -> {"rwp":…, "peak_only_rwp":…, "baseline_numerator_fraction":…,
#     "angular_rwp":[[lo,hi,v],…], "top_features":[{"two_theta":5.69,"residual":39.7,"obs":…},…]}
```

- **`top_features` の + 残差** (obs > calc) = **未説明ピーク** = 欠落相の候補。2θ → d 値 →
  **d 比**で格子型を推定 (実データ: 5.7°/10.9° の +残差 → d=5.258/3.729/2.640 の比から
  **cubic Fm-3m を独立同定**)。→ `identify_and_add_phase` かユーザー CIF。
- **強度比のズレ・ピーク分裂** → **対称性低下** (実データ: 深充電の (220)/(400) 比ズレ →
  **Mn³⁺ Jahn-Teller 正方晶**, 実 CIF で c/a_pc=1.054 = 5.4% 伸長)。部分群候補を提示し**承認を得る**。
- **`baseline_numerator_fraction` が大きい** → 「モデルでは下げられない」= **データ側の問題** →
  **2.1 に戻る**。**相を足して誤魔化さない**。

#### J6 系統ブロックの再構成

```python
repair_frames(result, frames, phases, instrument={...}, two_theta_limits=[2.4, 18.0])
# -> {"repairs":[…採用済…], "needs_model_revision":[…], "ledger_entries":[…]}
```

- **`phases` には系列で使われている全相を渡す** (`appearances` の自動追加相を含む)。欠けると
  ② がエラーにする — **黙って相を落として「Rwp 15→7 の修復成功」と報告させないため**。
- `repairs` は Rwp 改善時のみ採用済 (自己検証可能な規則 → ①/② に置ける安全部分集合)。
- **`needs_model_revision` はモデルの欠陥**。近傍 warm-start では直らない (**両隣も同欠陥**)。
  相集合/セル解放を**再構成**する (実データ: pure-mono ブロックは単相 mono+セル解放で
  9.1-10.7% → **6.5-8.1%**)。

#### J4 参照構造の供給

**手組みモデルを信用しない**。実データでは手組み正方晶の**歪み方向が逆**で、実験 tetra CIF
(I4/mmm) の投入が決定打だった。MP かユーザー提供 CIF を優先する。DFT (MP) 由来は格子が軸別に
ずれるため異方セル補正が自動で入る (#20)。

#### J8 電気化学との突合

分率の振動が多段酸化還元か artifact かは **dQ/dV 無しでは決まらない**。未確定なら**未確定と書き**、
V-t / dQ/dV を人間に要求する。

### 2.4 改訂は承認を挟む

相の追加/除外・対称性変更・セル解放方針の変更は**人間の承認後に適用**し、
**Rwp 改善 ∧ 物理妥当性維持**で受理、外れれば**可逆棄却** (P2 非破壊・ledger 追記)。**提案≠適用**。

### 2.5 因果を確定させる

「直った」で終わらせない。**単一変数の統制実験**で真因を特定する。

> 実例: Rwp 66% を「プロファイル初期値のせい」と誤診し W=180 を入れた (68% — 効いていない
> 手がかりを無視)。統制実験で真因は **CIF 空間群設定バグ (#48)** と判明:
> 正しい CIF は W=1→**19.94%** / W=180→26.14%、壊れた CIF は W=1→75.10% / W=180→72.48%。
> **手で入れた W=180 はむしろ悪化させていた**。→ Issue #79 は前提否定で close。

## 3. 禁止事項

- **Rwp が良いことを根拠に相集合を正しいと結論しない** (失敗は Rwp 8% で起きた)。
- **閾値を「期待した数字」に合わせて調整しない**。②/① は提案のみ。実測値を報告する。
- **系統ブロックを近傍 warm-start で「直そう」としない** (両隣も同欠陥 = 無効)。
- **「対策を入れたら直った」で因果を確定させない**。
- **残差を説明するためだけに相を足さない** (`baseline_numerator_fraction` 大 = データ側の問題)。

## 4. 権限境界

| 判断 | 決定論コア (自律) | ③ (あなた/人間) |
|---|---|---|
| データ品質の検出・2θ 上限の提案 | ✅ 提示のみ | ✅ 生データの要求は人間へ |
| 不連続フレームの近傍 warm-start 修復 | ✅ 自律 (Rwp 改善時のみ採用・ledger) | `needs_model_revision` を判断 |
| **新相の自動追加** (`phase_id` 有効時) | 🟡 **受理基準で自律採用する** (frac∧Rwp∧validity) | ✅ **`appearances` を監査**し化学妥当性を確認 |
| **相集合の完全性** (相の**欠落**) | ❌ **原理的に不可** | ✅ **③ が疑う** |
| **③ が判断して**相を追加/除外・対称性変更・構造改訂 | ❌ | ✅ **人間の承認必須** |

> `sequential_rietveld` に `phase_id` を渡すと**コアは承認なしに相を追加する** (受理基準を満たす
> 場合のみ・可逆棄却つき)。「相集合は自分が変えない限り不変」と思い込まず、**`appearances` を
> 必ず読む**こと。人間の承認が要るのは **③ が判断して行う**改訂である。

**なぜ相の欠落は自律検出できないか**: 受理基準は「**追加された相が残差を説明するか**」しか
見ない。欠落相は**その視野の外**にあり、しかも欠けた相の強度は計量の近い別相が肩代わりして
Rwp を保つ。**統計量では検出できない。③ が疑う以外に手段が無い。**

## 5. 再現ベンチマーク (K₂Mn[Fe(CN)₆] K-10 0.1C)

| | 解析フレーム | Rwp |
|---|---|---|
| 学生の手動解析 (RIETAN, 単相) | frame-1 のみ (1/247) | 16.24% |
| **本フロー (3 相)** | **63/247 (stride 4 の間引き)** | **6.02–8.96% (mean 7.47%), 9% 超ゼロ** |

> ⚠ **間引きである点に注意**。系列は 247 フレームだが、上の Rwp 統計は
> `range(0, 247, 4) + [246]` = **63 フレーム (25.5%)** に対するもの (`scripts/full_3phase.py` の
> 既定 `step=4`)。**全フレーム解析は未実施**であり、間引きで見えない短寿命の中間相・
> 転移端の挙動が残っている可能性がある。全 247 フレームの結果が要る場合は `step=1` で回すこと。
> (本表は当初「全 247 フレーム」と誤記していた — 実測は 63 フレームだった。)

**結論**: monoclinic P2₁/n (K-rich, 放電) → cubic Fm-3m (充電) → **tetragonal I4/mmm (深充電,
Mn³⁺ Jahn-Teller)** → cubic → monoclinic の**完全可逆な 3 相転移**。tetragonal は**単一ドーム**
(peak 0.58 @ frame 124)。frame0 ≈ frame246 で可逆性を構造から確認。
