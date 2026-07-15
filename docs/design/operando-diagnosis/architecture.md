# operando 診断・判断層 (③) アーキテクチャ設計

作成: 2026-07-15
前提: M8 3層分離 (`docs/design/m8-agentic-loop/architecture.md`) を継承する。
根拠: K₂Mn[Fe(CN)₆] 放射光電気化学 operando 実データ解析 (247 フレーム, λ=0.501345 Å)。
実測値はすべて当該解析で取得したもの。

## 0. 動機 — **Rwp では原理的に検出できない誤り**が実在した

実解析で最も重大だった失敗は、**フィット統計がすべて良好なまま物理的に誤った描像**を得たことである:

- 充電域を cubic+tetra の 2 相に限定 (「放電相 mono は充電時に存在しない」という一見妥当な判断) →
  転移端に残る monoclinic の強度を、計量の近い **tetragonal が肩代わり**。
- 結果:「tetragonal が増減を繰り返す」非物理な描像 (`tetra = 0.42→0.17→0.70→0.04→0.63`)。
- **Rwp は終始 ~8% と良好**。GOF も validity も警告を出さない。
- 全 3 相を入れ直すと単一ドーム (`0→0.58→0`, 端は mono 0.64 / tetra **0.00**) に収束 = 正解。
- **発見者は人間の物理的直感**であった (「一度増えてから減るのは妥当か?」)。

計量が近い相 (本系は mono/cubic/tetra が全て cubic 派生) は**互いの強度を吸収し合う**ため、
この誤りは ① の統計量では検出できない。**だから ③ (判断層) が要る**。本設計はこの失敗を
再現可能な形で ③ に埋め込むことを目的とする。

同様に「対策を入れたら直った」で因果を誤認した例もある (プロファイル初期値が原因と誤診したが、
統制実験で真因は CIF 空間群設定バグ #48 と判明; Issue #79 は前提否定で close)。
**③ は単一変数の統制実験で因果を確定させる責務も負う**。

## 1. 責務配置 (M8 の 3 層を継承)

| 層 | 実体 | 本設計での担当 | 状態 |
|---|---|---|---|
| ① 決定論コア | `autorietveld.dataquality` / `.residual_report` / `insitu.repair` / `insitu.phaseset` | 観測・診断・**規則で決まる修復**のみ | **実装済** (#78/#83/#81/#84) |
| ② MCP | 薄い 4 ツール (下記) | ① を構造化して露出 | **本設計で追加** |
| ③ プラグイン | `skills/operando-diagnose` + `commands/operando-diagnose` | **R3 開放的判断 / R5 構造改訂・事前知識** | **本設計で追加** |

原則は M8 を継承: **提案≠適用** / 規則は安全部分集合のみ / 受理は Rwp だけでなく物理妥当性 /
P2 非破壊・ledger 追記。**MCP は共有ポータブル核**で、Codex 等は同じ ② を AGENT_PLAYBOOK で駆動する。

## 2. ② 追加する MCP ツール (計器のみ・判断しない)

| ツール | ① の実体 | 入力 | 出力 (構造化) |
|---|---|---|---|
| `assess_data_quality` | `dataquality` | 観測ファイル (+esd) | `is_subtracted`/`confidence`/`reasons`/`recommendation`, `suggested_two_theta_limit` (要 `excluded_regions`) |
| `residual_report` | `residual_report` | **`auto_rietveld` の出力に `residual_report` を同梱** (配列は MCP を跨がせない) + 明示配列入力 (x,yobs,ycalc,w) も可 | `rwp`/`peak_only_rwp`/`baseline_numerator_fraction`/`angular_rwp`/`top_features` (2θ+符号) |
| `check_phase_set` | `insitu.phaseset` | 系列結果 | `is_complete`/`union`/`frames_with_missing`, 相ごとの `turning_points`/`flagged` |
| `repair_frames` | `insitu.repair` | 系列結果 + frames + phases | `repairs` (採用のみ)/`needs_model_revision`/`systematic_hint` |

いずれも**返すだけ**。閉ループも判断も ② には出さない (M8 の `agentic_analyze` を出さない方針を踏襲)。

`residual_report` は **`auto_rietveld` の出力に同梱する**のが主経路である。残差配列
(`residual_two_theta`/`residual_intensity`/`residual_sigma`) は実データで 2392 点 × 3 本 ≈ 150KB あり
**MCP 境界を跨がせてはならない**が、レポート自体は数個の float + ~6 特徴と小さい。よってサーバ側
(`rietveld_tools._result_to_dict` → `residual_report_from_result`) で算出して返し、③ は**再精密化なしに**
J2/J3 を判断できる。単独ツール (明示配列入力) は既に配列を手元に持つ呼び出し側のために残す。
`repair_frames` は再精密化を伴うが、**Rwp 改善時のみ採用**という自己検証可能な規則なので ①/② に置ける
(= 安全部分集合)。改善しなかったものは `needs_model_revision` として ③ へ上げる。

## 3. ③ skill 設計 — `operando-diagnose`

既存 `analyze` (単一フレーム) / `insitu` (逐次+新相同定) / `mem-model-fix` (密度→構造修正) に並ぶ
**operando 系列の診断・モデル改訂**担当。`insitu` が「回して新相を足す」のに対し、本 skill は
**「得られた系列結果を疑い、モデルの誤りを見つけて改訂する」**。

### 判断項目 (③ が担う R3/R5) — すべて実データ由来

| # | 判断 | 入力 (②) | 実測の根拠 | 出口 |
|---|---|---|---|---|
| J1 | **データ品質**: 背景減算済なら生データを要求 | `assess_data_quality` | 減算済+esd=√I で Rwp **26% → 生+背景精密化 6.7%** (同一モデル)。fit でなく重み付けの問題 | ユーザーに生データの有無を問う (**人間の情報が要る**) |
| J2 | **未説明ピーク → 欠落相の仮説** | `residual_report.top_features` (符号+) | 5.7°/10.9° の +残差 → d=5.258/3.729/2.640 比から **cubic Fm-3m を独立同定** | `identify_and_add_phase` / ユーザー CIF |
| J3 | **対称性低下の仮説** | `residual_report` (強度比・分裂) | 深充電の (220)/(400) 比ズレ → **Mn³⁺ Jahn-Teller 正方晶** (実 CIF で c/a_pc=1.054) | 部分群の候補を提示し承認を得る |
| J4 | **参照構造の供給・選定** | — (R5 事前知識) | 実験 tetra CIF (`0129@2`, I4/mmm) の投入が決定打。手組みモデルは歪み方向が逆で誤っていた | MP / ユーザー提供 CIF |
| **J5** | **相集合の完全性** ★最重要 | `check_phase_set` | **Rwp 8% のまま tetra が mono を肩代わり**。全 3 相で単一ドームに是正 | **除外相を戻して再フィットし分率を比較** |
| J6 | **系統ブロックのモデル再構成** | `repair_frames.needs_model_revision` | pure-mono ブロックは近傍 warm-start 無効 (両隣も同欠陥) → 単相 mono+セル解放で 9.1-10.7→**6.5-8.1%** | 相集合/セル解放の再構成 |
| J7 | **物理的にありえない結果の棄却** | `check_phase_set.flagged` + 人間 | 「tetra が増減を繰り返す」の棄却。**どの統計量でも拾えなかった** | 仮説を立て直す |
| J8 | **電気化学との突合** | — (外部データ) | 分率の振動が多段酸化還元か artifact かは dQ/dV 無しでは未確定と明記した | ユーザーに V-t/dQ/dV を要求 |

### 手順 (skill 本文の骨子)

1. **データ品質を先に問う** (J1)。`assess_data_quality` が `is_subtracted=True` を返したら、
   **精密化を始める前に**生データの有無をユーザーに確認する。ここが最大のレバー (26%→6.7%)。
   併せて `suggested_two_theta_limit` を得る (**寄生ピーク窓を `excluded_regions` で渡すこと**;
   渡さないとセル由来の反射を信号と拾い上限が押し出される — 実測 38.1°)。
2. **系列を回す** (`sequential_rietveld`, `insitu` skill と同じ)。
3. **疑う** — ここからが本 skill の主眼:
   - `check_phase_set` → `is_complete=False` なら **J5**: 「除外した相の強度を、計量の近い別の相が
     肩代わりしていないか」を疑い、**和集合で再フィットして分率を比較**する。`flagged=True`
     (分率が振動) なら **J7**: 物理的に妥当かを問う。**Rwp が良くても信じない**。
   - `repair_frames` → `repairs` は採用済 (規則)。`needs_model_revision` は **J6**: モデルを直す。
   - `residual_report` → `top_features` の + 残差位置から **J2/J3**: 欠落相 or 対称性低下を仮説化。
     `baseline_numerator_fraction` が大きければ「モデルでは下げられない」= データ側の問題 (J1 へ戻る)。
4. **改訂は必ず承認を挟む** (ModelAction): 相の追加/除外、対称性変更、セル解放方針の変更は
   ユーザー承認後に適用し、**Rwp 改善 ∧ 物理妥当性維持**で受理、外れれば可逆棄却 (P2)。
5. **因果を確定させる**: 「直った」で終わらせず、**単一変数の統制実験**で真因を特定する
   (実例: プロファイル初期値と CIF 設定バグを分離し、真因が後者と確定 → Issue #79 は前提否定で close)。

### 禁止事項 (skill に明記する)

- **Rwp が良いことを根拠に相集合を正しいと結論しない** (J5/J7 の失敗が Rwp 8% で起きた)。
- **閾値を「期待した数字」に合わせて調整しない**。実測値を報告する (②/① の助言器は提案のみ)。
- 系統ブロックを近傍 warm-start で「直そう」としない (両隣も同欠陥 = 無効)。

## 3.5 既存 `insitu` skill の改訂 (**必須**)

新 skill を足すだけでは不十分。**既存 `insitu` skill は本解析の知見と矛盾する記述・陳腐化した記述を
含む**ため以下 5 点を改訂する。監査結果: `two_theta_limits` / `excluded_regions` / `auto_freeze` /
`warm_start_fractions` / `repair` / 減算 / `dataquality` / 分率振動 への言及がいずれも **0 件**。

| # | 現状 (SKILL.md) | 問題 | 改訂 |
|---|---|---|---|
| **R1** ★危険 | 手順4「**Rwp がフレーム全域で目標帯 (チュートリアル値±マージン) に収まるか**」(37行目) | **この受理基準が本解析の失敗そのもの**。Rwp 8% (目標帯内) のまま tetragonal が monoclinic を肩代わりし非物理な描像を生成した。Rwp は**相集合の誤りに盲目** | 「Rwp だけで収束を判定しない」と明記。`check_phase_set` (相集合完全性・分率の非単調) と物理妥当性の確認を**必須手順**へ格上げ |
| **R2** ★最大レバー | 手順1「入力を組み立てる」にデータ品質確認が無い | 背景減算済 + esd=√I はノイズ底を過大重みし Rwp を膨らませる (同一モデルで **26% → 生+背景精密化 6.7%**)。気づかず系列を回すと**全フレームの Rwp が無意味に高い** | **手順 0** に `assess_data_quality` を追加。`is_subtracted=True` なら**精密化前に**生データの有無をユーザーに問う |
| **R3** | 2θ 上限・除外窓への言及なし | ノイズ域が最小二乗を支配し遅く不正確 (30°→18° で **369s→8s** かつ収束改善)。寄生ピーク (セル由来) を `excluded_regions` で渡さないと信号終端が押し出される (実測 38.1°) | 手順1 に `two_theta_limits`/`excluded_regions` の設定を明記 (`suggest_two_theta_limit` を助言に使う) |
| **R4** | 新機能への言及なし | 実装済みの第2層機能が使われない | `auto_freeze_minor_cells` (#80: 少数相セルを解放すると発散・分率崩壊)、`warm_start_fractions` (#82: 分率が seed に張り付く frame を是正)、`repair_frames` (#81: 不連続点の近傍 warm-start 修復) を手順へ配線 |
| **R5** | 前提「MP キーは**環境変数**が必要。未設定なら error」(61行目) | **陳腐化**。#51 (PR #85 マージ済) で `.env` から自動読込するようになった | 「`.env` に `MATERIALS_PROJECT_API` があれば自動読込。未設定時のみ CIF 直接指定へ切替」に更新 |

権限境界テーブルも補強する。現状は「新相の**採否**は受理基準 (frac∧Rwp∧validity) で自律可、化学的に
不自然な相は ③ が退ける」とあるが、本解析の失敗は**相が追加された誤り**ではなく**相が欠けている誤り**
だった。受理基準は「残差の説明力」しか見ないため**欠落相は原理的に検出できない**。
→ 「**相集合の完全性は受理基準では担保されない。③ が `check_phase_set` で疑うこと**」を追記する。

> 本節は設計レビューでの指摘 (「既存 insitu スキルの改訂は不要?」) により追加。新機能の追加だけを
> 考え、**既存の助言が新知見と矛盾したまま残る**リスクを見落としていた。skill は「実行者への指示」で
> あり、誤った受理基準を残すことは実装バグと同等に有害である。

## 4. 既存プラグインとの関係

```
plugins/tsumugin/
├── skills/analyze/           # 単一フレーム閉ループ (M8)
├── skills/insitu/            # 逐次 + 新相自動同定 (M9)
├── skills/mem-model-fix/     # 密度 → 構造修正 (M8-③)
└── skills/operando-diagnose/ # ★本設計: 系列結果を疑い・モデルを改訂する
```
`insitu` が「進める」skill、`operando-diagnose` が「疑う」skill。両者は併用され、
`insitu` の結果を `operando-diagnose` に渡すのが標準動線。

## 5. 実装計画

| 段 | 内容 | 依存 |
|---|---|---|
| 1 | ② MCP 4 ツール (`mcp/tools.py`, MCP_TOOLS に追加) + 決定論テスト | ① 実装済 |
| 2 | ③ `skills/operando-diagnose/SKILL.md` + `commands/operando-diagnose.md` | 段1 |
| 2b | **既存 `skills/insitu/SKILL.md` の改訂 (§3.5 の R1-R5)** — R1 (危険な受理基準) と R5 (陳腐化) は独立に先行実施可 | R1/R5 は即時、R2-R4 は段1 |
| 3 | `AGENT_PLAYBOOK` に移植版を追記 (Codex 等の非 Claude ハーネス用) | 段2 |
| 4 | plugin.json の description 更新 (operando 診断を明記) | 段2 |

## 6. 受け入れ基準

- ② の 4 ツールが ① を呼び構造化 dict を返す (numpy 決定論テスト; GSAS は境界外)。
- ③ の skill が、本セッションの実データで**私 (人間) が辿った判断列を再現できる**こと:
  減算検出 → 生データ要求 → 系列 → `check_phase_set` の flagged → 相集合を戻して再フィット →
  単一ドームに是正、が skill 手順として辿れる。
- **提案≠適用**: 構造改訂はすべて承認ゲートを通る。ledger に残る。
- **既存 `insitu` skill から R1 (Rwp のみでの収束判定) と R5 (MP キーの陳腐化) が除去**され、
  相集合の完全性確認が必須手順になっていること。
