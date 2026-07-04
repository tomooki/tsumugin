# m4-joint-mcp ヒアリング記録

**作成日**: 2026-07-04
**実施形態**: 自律実行モード — 対話ヒアリングは行わず、仕様書 (§6 FR-240系 / §8 FR-412 / §10 FR-513 / §11 / §13)・
M0〜M3 実装・推奨案で自己解決した。以下は論点と自律確定の根拠 (Q&A 形式)。

## 自律確定した論点

### Q1: 作業規模
**確定**: フル機能開発。
**根拠**: M4 は Dara 非対応領域 (中性子 joint・エージェント接続) の中核で、FR-240系/FR-412/FR-513 が
仕様に明記済み。ADR-0001 (GUI 技術選定) 済で MS 順序も確定 🔵。

### Q2: 中性子 joint の入力モデル設計
**確定**: 既存 `RefinementModel` (単一ヒスト前提) は不変のまま、joint 用に `JointRefinementModel`
(ヒストごと (2θ, I, w) 群 + 共有構造 free_params + ヒスト独立 free_params) を新設する。
**根拠**: 既存 API 非破壊 (REQ-404)。M3 で `RefinementResult.globals`/`warnings` を非破壊追加した前例に倣う 🔵。
FR-242「構造共有・scale/背景/プロファイル独立」をそのまま型で表現 🔵。

### Q3: joint 精密化の検証バックエンド
**確定**: GSASIIBackend は GSAS-II ネイティブのマルチヒストグラム機能へ配線。SimulatedBackend は
**ヒストごと χ² の合算**で joint を近似し、テストは Simulated で完結させる。
**根拠**: FR-242「GSAS-II ネイティブ機能を利用」🔵。合成データ検証は既存パターン (Simulated 主・@gsas smoke) 🟡。

### Q4: TOF マルチバンクのパラメータ管理
**確定**: `HistogramRef` (probe/instprm_ref/bank_id の器は M1 導入済) に、バンク別 DIFC/DIFA/ZERO を
持つ `TofBankParams` 相当を**末尾・既定値付き**で非破壊追加。
**根拠**: FR-241「TOF はバンクごとの instprm・DIFC 系」🔵。既存 `HistogramRef` を壊さない (REQ-404) 🔵。

### Q5: コントラスト判定のデータ源
**確定**: 中性子散乱長 b は**元素代表値の軽量静的テーブルを同梱**。X線散乱因子 f は Z 近似。
コントラスト = |f_norm − b_norm| が閾値超のサイトを検出し、**推奨のみ (自動適用しない)**。
**根拠**: FR-244「散乱コントラスト十分なサイトを自動検出・joint 時のみ戦略追加」🔵。
b は同位体で変わりうるが v1 推奨判定には元素代表値で足る (重依存 xraylib 不要・REQ-403) 🟡。

### Q6: ChemPlausibility の適用位置 (最重要)
**確定**: スコアは **rank の順位補正 (降格) としてのみ配線**。rejected 化・候補集合からの除外は**実装しない**。
低スコア相も rank から消えないことをテストで固定。
**根拠**: FR-412「スコアは降格のみに使い候補の除外は行わない (Dara 教訓)」— M4 の最重要不変条件 🔵。

### Q7: ChemPlausibility の合成規則
**確定**: 複数モジュールのスコア合成 = **重み付き幾何平均 (既定)**。モジュール未登録時は降格なし (素の順位)。
**根拠**: FR-412「複数モジュールのスコア合成規則 (重み付き幾何平均、既定)」🔵。任意プラグイン境界のため未登録許容 🟡。

### Q8: `.mpr` より汎用出力を優先するか (MCP get_trajectory / export 系)
**確定**: MCP `get_trajectory` は既存 `Trajectory.to_csv` (CSV/parquet 汎用) へ委譲。装置固有バイナリは扱わない。
`export_gpx` は既存 `export.gpx.export_gpx` へ委譲 (GSAS-II .gpx は FR-505 保証済)。
**根拠**: FR-504 出力は parquet/CSV 第一級。M3 で .mpr は optional・後回しと確定した方針を踏襲 🔵。

### Q9: MCP SDK の依存方式
**確定**: `mcp` パッケージを **optional extra `mcp`** として追加 (`uv sync --extra mcp`)。
MCP 層を「SDK 非依存のツール実処理関数」+「SDK 依存の薄いアダプタ」の 2 層に分離。
未導入環境ではアダプタ起動のみ friendly error (`MCPUnavailableError` 相当)、実処理関数は通常テストで網羅。
**根拠**: GSAS-II/xraylib と同じ optional extra 方式 (コア依存 numpy のみ・REQ-403) 🔵。
テスト容易性・NFR-102 決定論のため実処理を SDK から分離 🟡。

### Q10: `run_mem` の実装範囲
**確定**: MCP ツールとしての受け口は作るが、内部は MEM バックエンド未実装 →
`NotImplementedError` 相当の明示エラー or 「M5 で提供予定」プレースホルダ応答。**破壊的操作を伴わない**。
将来 (M5) の MEMBackend と互換なスキーマにしておく。
**根拠**: FR-600系 (MEM/Dysnomia) は M5 スコープ。指示で「M4 は薄い委譲/スタブ境界に留める」と確定 🔵。

### Q11: final_selection_mode の MCP 経由適用
**確定**: MCP `accept_hypothesis`/`revert` は既存 `FinalSelectionEngine.accept/.revert` へ委譲し、
現在の `final_selection_mode` を同一適用。human モードでは agent 権限の accepted 化を拒否 (推奨提示のみ)。
**根拠**: FR-402/FR-513「final_selection_mode は MCP 経由でも同一に適用」🔵。既存 accept(by=...) 経路を再利用 🔵。

### Q12: MCP Server のバインド既定
**確定**: 既定はローカル (stdio トランスポート or `127.0.0.1`)。無認証ネットワーク公開はしない。
公開時認証は M4 スコープ外 (既定安全側)。
**根拠**: P2/セキュリティ制約 (解析データ全量の無認証公開回避)。Web UI が既定 127.0.0.1 の前例に倣う 🟡。

## 残課題 (実装時確定 / 後続)

- コントラスト閾値・b テーブルの数値はベンチ (§12-6 joint ベンチ) で較正 — M4 はテストで既定値を凍結
- MCP SDK のバージョン範囲は導入時に固定 (`mcp>=1.0` 目安)。API は SDK メジャー変化に追随
- 中性子吸収/多重散乱補正 (FR-317 末項) の本実装・xraylib 連携は M-later (M4 は境界のみ)
- MEMBackend (FR-601〜606) 本体は M5 (`run_mem` の実処理を差し替え)

## 信頼性レベル分布 (要件定義書全体)

- 🔵 青信号: REQ 27 / NFR 2 / EDGE 6 相当 — 仕様・既存実装に直接依拠
- 🟡 黄信号: REQ 6 / NFR 3 / EDGE 5 相当 — 妥当な推測 (根拠併記)
- 🔴 赤信号: 0 件
- **総括**: 仕様書 (FR-240系/FR-412/FR-513) が具体的かつ既存の器 (Probe/HistogramRef/FinalSelectionEngine) が
  揃っているため 🔵 が支配的。設計裁量部 (joint 入力型・Simulated 検証・MCP 2 層分離・散乱長テーブル) が 🟡。

## 関連文書

- [requirements.md](requirements.md) / [user-stories.md](user-stories.md) /
  [acceptance-criteria.md](acceptance-criteria.md)
