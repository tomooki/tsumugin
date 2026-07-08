# refine-loop-diagnostics 要件定義書

## 概要

`tsumugin.refine_loop` (M8 決定論 agentic 閉ループ) の**第2層b(診断オートトライ)を拡張**する。
`docs/reference/serious-refinement-flow.md` の一般化フローと現行実装のギャップ
(`docs/design/refine-loop-diagnostics/GAP_ANALYSIS.md`) を正式要件化する。核心原理
「可能性があればトライ→ダメなら revert」を保持し、accept/revert エンジン
(`orchestrator._accept` = Rwp 改善 ∧ validity 維持) は不変。追加は診断シグナル・トライ候補・
少数の新 SafeAction・上位のモデル比較オーケストレータ。

## 関連文書

- **ヒアリング記録**: [💬 interview-record.md](interview-record.md)
- **ユーザストーリー**: [📖 user-stories.md](user-stories.md)
- **受け入れ基準**: [✅ acceptance-criteria.md](acceptance-criteria.md)
- **コンテキストノート**: [📝 note.md](note.md)
- **設計入力(正)**: [GAP_ANALYSIS.md](../../design/refine-loop-diagnostics/GAP_ANALYSIS.md) /
  [serious-refinement-flow.md](../../reference/serious-refinement-flow.md)

## スコープ境界 (ヒアリング決定)

- **P3 データリミットは第3層のまま** — レンジ変更は Rwp 直接比較を壊すため、ループ内オートトライに
  しない。`SetLimits` は ModelAction(提案のみ)、setup 用 `propose_initial_limits` のみ自動 🔵。
- **P4 BIC モデル選択は今回に含める** — refine_loop 上位に薄いモデル比較オーケストレータを新設し、
  変種を `compare.compare_models` で BIC+妥当性裁定 🔵。

## 機能要件（EARS記法）

**【信頼性レベル凡例】**: 🔵 設計文書/実装/ヒアリング参照の確実な要件 / 🟡 妥当な推測 / 🔴 未参照推測

### 通常要件

- REQ-001: システムは `AutoRietveldResult` に**内省フィールド**(per-atom の Uiso・占有率、
  per-histogram の吸収・プロファイル値、obs/calc のピーク幅比・非対称指標・選択配向指標)を露出
  しなければならない。既存フィールドは非破壊で末尾追加・後方互換の既定値を持つ 🔵 *GAP 前提工事1*
- REQ-002: システムは残差配列(`residual_two_theta/intensity/sigma`)と内省フィールドから診断
  シグネチャを算出する残差解析 diagnose (`refine_loop/diagnose_residual.py`) を提供しなければ
  ならない 🔵 *GAP 前提工事2*
- REQ-003: システムは診断シグナルに対し、**候補パラメータを別々の `ReleaseParams` 提案として
  列挙**しなければならない(結論を焼き込まず、採否は try→revert が決める) 🔵 *serious-flow §6・核心原理*
- REQ-004: システムは「解放」でなく「限定/値固定」を表す新 SafeAction `RestrictUiso(labels)`
  ・`SetAbsorption(hist_id, value, refine)` を提供しなければならない 🔵 *GAP 表B/C P2*
- REQ-005: システムは複数構造モデル変種を精密化し `compare.compare_models` で BIC+妥当性序列化する
  **モデル比較オーケストレータ**を提供しなければならない(単一モデル調律ループの上位) 🔵 *ヒアリング P4*

### 条件付き要件 (診断トリガ)

- REQ-101: **非対称/位置ズレの残差**を検出した場合、システムはシフト(Zero)解放と非対称
  (X線:SH/L、TOF:alpha/beta)解放を**別々の候補**として提案しなければならない 🔵 *serious-flow §6*
- REQ-102: **系統的な obs>calc のピーク強度**を検出した場合、システムは選択配向
  (`preferred_orientation`)解放を提案しなければならない 🔵 *serious-flow §6*
- REQ-103: **ピーク幅の系統ずれ**を検出した場合、システムは Gaussian(U,V,W)・Lorentzian(X,Y)・
  size/mustrain を**別々の候補**として提案しなければならない 🔵 *serious-flow §6・GAP 表B*
- REQ-104: **背景プロファイルの過剰な wiggle(極値過多)**を検出した場合、システムは背景係数の
  **減項**を提案しなければならない(現行は増項のみ) 🔵 *GAP 表B*
- REQ-105: **Uiso の発散/負値**を検出した場合、システムは `RestrictUiso`(重原子/可動イオン/水に
  限定)を提案しなければならない 🔵 *GAP 表B P2*
- REQ-106: **吸収寄与が不確実**な場合、システムは自由精密化・物理値固定・0 の**3 択トライ**を
  `SetAbsorption` 提案として列挙しなければならない 🔵 *GAP 表B P2*

### 状態要件

- REQ-201: 提案アクションを適用している間、システムは **Rwp 改善 ∧ validity 維持**を満たす場合のみ
  採用し、満たさなければ revert して据え置かなければならない(`_accept` 不変) 🔵 *orchestrator 現行*
- REQ-202: モデル比較を実行している間、システムは物理妥当なモデルのうち最小 BIC を選定し、
  妥当なモデルが皆無のときのみ全体最小へフォールバックしなければならない(`best_is_valid`) 🔵
  *compare 現行(PR #35 修正)*

### オプション要件

- REQ-301: システムは経験則 prior(例「TOF は alpha が効きやすい」)を**試す順序の偏り**として
  用いてもよい。ただし非拘束で、採否は try→revert が決めなければならない 🔵 *核心原理*

### 制約要件

- REQ-401: コアは numpy のみに依存し、GSAS-II は runner 内で遅延 import しなければならない 🔵 *CLAUDE.md*
- REQ-402: 提案順序は決定論(safe 優先→優先度降順→型名昇順)で、種・入力が同一ならビット同一で
  なければならない 🔵 *NFR-102・diagnostics 現行*
- REQ-403: SafeAction のみ規則が自律適用してよい。ModelAction は提案のみ(③/人間へ申し送り) 🔵 *policy 現行*
- REQ-404: データリミット(`SetLimits`)は ModelAction のまま(第3層)で、ループ内オートトライに
  しないこと 🔵 *ヒアリング P3*
- REQ-405: 診断規則に**材料固有の結論を焼き込まない**(汎用の try→observe 形で記述する) 🔵 *核心原理*

## 非機能要件

### パフォーマンス

- NFR-001: 高速ティア(`-m "not gsas"`)で診断・提案・モデル比較(runner スタブ注入)が決定論
  テストできること 🔵 *CLAUDE.md テスト方針*

### 保守性

- NFR-101: 大半の新診断は**既存 `ReleaseParams` + engine flag** で表現し、新 Action は
  `RestrictUiso`/`SetAbsorption` のみに限定する 🔵 *GAP 表C*
- NFR-102: 台帳は追記専用でハッシュチェーン `verify()` が常に True 🔵 *NFR-105*

## Edgeケース

### エラー処理

- EDGE-001: 内省フィールドを持たない旧 `AutoRietveldResult`(既定値)でも diagnose が例外を出さず
  縮退動作すること(見えないシグナルは提案しない) 🔵 *後方互換*
- EDGE-002: 提案対象パラメータが既に解放済み/既試行の場合、`RuleBasedPolicy` は再選択せず終了を
  保証すること 🔵 *policy 現行*

### 境界値

- EDGE-101: モデル比較で妥当なモデルが 0 件のとき、`best_is_valid=False` で全体最小 BIC を返す 🔵
  *compare 現行*
- EDGE-102: 残差配列が空/全ノイズのとき、diagnose はシグナルを立てない(false positive を出さない) 🔵
