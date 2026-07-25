# GUI Workbench v2 実装計画

**前提**: v1 (PR #138, 2026-07-25 マージ) — 実プロジェクト接続・実 RUN REFINEMENT
(CaTeO3 実走 Rwp 12.57%)・実チャート・Tauri scaffold まで完了。
**方針**: v1 で確立した規律 (契約先行 `api-contract.md` / enum 語彙の両側固定 /
empty-state 原則 = シードで偽装しない / 変更系は ledger / ガードは変異実証) を全タスクに適用。
ブランチは wave 毎に `milestone/gui-workbench-v2a` 等、1 wave = 1 PR。

## 現状の実装ギャップ (v1 残存制約より)

| 領域 | v1 の状態 | 使う既存 ① / ② 資産 |
|---|---|---|
| PARAMETERS | 表示のみ (release チェックは UI 状態) | `recipe.build_recipe` / `HistogramSpec.profile_bounds` |
| STRUCTURE | 座標「―」・ReviseStructure は snapshot 記録まで | gpx 読取 (curves.py 同様) / ② `refine_with_revisions` (M8) |
| PHASE ID | シード表示のみ | ② `identify_phases` / `identify_pattern` (M11) / `insitu.phaseid` 物質化 |
| HYPOTHESES/basin | シード表示・basin 未配線 | `run_multistart_rietveld` (#13) / ② `compare_structure_models` |
| SEQUENCE | empty-state | ② `sequential_rietveld` / `anchored_sequential` (M9/M10, JSON spec 済) |
| echem | 表示のみ | ② `align_echem` (#103) / `alkali_budget` (FR-318) |
| AUTO transcript | シード表示 + custody 操作のみ | ③ = Claude Code + MCP (ブリッジ未設計) |
| MEM マップ | empty-state | ② `mem_density` + `.grd` リーダ (FR-601) |
| 配布 | Tauri scaffold + dev 構成のみ | ADR-0001 sidecar 設計 (README 文書化済) |

## 方針転換 (2026-07-25, ユーザー指示)

**プロトタイプはデザインイメージであり「正」ではない**。以後は通常の Rietveld 解析
アプリとして必要な機能・画面を要件が正として設計する (Industry トークンの見た目の
骨格は維持)。これに伴い V2a を「アプリ基盤」に再定義し、旧 V2a (解析ループ完成) は
V2a' として後続させる。

## V2a — アプリ基盤: プロジェクト管理・ファイル読み込み・画面再構成 (最優先)

GUI からプロジェクトを作成し、データ/装置/構造ファイルを読み込み、設定して精密化まで
到達できる「普通のアプリ」の骨格。契約は api-contract.md §プロジェクトライフサイクル。

| # | タスク | 内容 |
|---|---|---|
| P1 | プロジェクトライフサイクル (backend) | create/open/close/demo/recent + project.json 自動保存 + **PersistentLedger/PersistentSnapshotStore** をプロジェクトディレクトリに配線 (再起動しても監査履歴が残る)。セッション切替、refine 実行中の変更 409 |
| P2 | ファイル取り込み | multipart upload → プロジェクト `data/` へコピー (自己完結)。histograms/phases の追加・除去・settings 変更 API (全て ledger 記録・DELETE ルート不使用) |
| P3 | Welcome 画面 (frontend) | source=none 時に 3 ペインの代わりに表示: 新規作成フォーム (名前+保存先) / 開く (パス入力+recent 一覧) / サンプル (demo)。プロジェクト読込で workbench 本体へ |
| P4 | PROJECT タブ (frontend) | センターペイン先頭に新設: ヒストグラム表 (追加=ファイル選択+radiation/geometry フォーム, 除去)、相表 (CIF 追加, 除去)、精密化設定 (2θ 範囲/背景項数/max_cyc)。LeftRail の DATASETS/PHASES に + ボタン (PROJECT タブへ誘導) |
| P5 | 統合 | CaTeO3 を GUI だけで新規プロジェクト作成→ファイル読込→精密化→再起動→再オープン (ledger 継続) の通し実証 |

## V2a' — 単一フレーム解析ループの完成 (旧 V2a)

「読み込む → 精密化 → 診る → モデルを直す → 再精密化」を GUI だけで閉じる。

| # | タスク | 内容 / 受け入れ基準 |
|---|---|---|
| A1 | PARAMETERS → recipe 実接続 | release チェック集合を `POST /api/refine` の recipe 構築に反映 (ゲート済ステージの実スキップ)。受け入れ: チェックを外した群が実 run で解放されないことを stage 履歴で確認 |
| A2 | STRUCTURE 実座標 | 精密化済み gpx から SITES (label/el/x/y/z/occ±esd/Uiso/特殊位置 lock) を抽出し実表示。`GetCSxinel` 相当の対称ロックを実データで反映 |
| A3 | ReviseStructure → 再精密化ループ | APPLY 済みモデルで ② `refine_with_revisions` 経路の再 run (提案≠適用の維持・revert 可能)。受け入れ: occ 編集 → 再精密化 → Rwp/占有率が実際に変わる |
| A4 | PHASE ID 実配線 | 残差 (`residual_report`) → `identify_pattern` 実行ジョブ → 候補表。`ADD AS PHASE` = CIF 物質化 (`insitu.phaseid` 再利用) → PhaseSpec 追加 → 再精密化。化学ガード表示は実スコア |
| A5 | basin 実配線 | `run_multistart_rietveld` ジョブ → basin 散布 + `is_global_corroborated` 表示 |
| A6 | gpx エクスポート | `GET /api/export/gpx` (keep_gpx 生成物のダウンロード)。FR-424: ledger 遡及リンク付き |

推定: 実装 6-9 日相当。リスク: A2/A3 の gpx ↔ モデル往復 (GSAS ラベル規約)。
検証データ: CaTeO3 (単相) + CandAt (二相, PHASE ID 用 — testdata fetch 必要)。

## V2b — 逐次 / operando (ユーザーの主用途)

| # | タスク | 内容 / 受け入れ基準 |
|---|---|---|
| B1 | フレーム列 project spec | spec に frames (ファイル列/温度/時間) を追加。ContextBar の frame chip 実動 (フレームナビ) |
| B2 | 逐次ジョブ | ② `sequential_rietveld` JSON spec 経路をジョブ化 (フレーム進捗 = ledger)。SEQUENCE 実系列 (Rwp/格子/相分率 vs frame) が実チャートに載る |
| B3 | anchored 経路 | ② `anchored_sequential` + anchor チップ実表示 (crossover = bic 最小)。**operando 既定手順に M10 を含める** (CLAUDE.md 不変条件) |
| B4 | echem 同期 | ② `align_echem` / `alkali_budget` → EXTERNAL CHANNELS 実値 + 相分率チャートの x_echem overlay + infeasible 発火の review queue 連携 (FR-403) |
| B5 | 新相受理 UI | 逐次中の新相提案 (identify_and_add_phase) を ModelAction 承認カードに接続 (提案≠適用の実運用) |

推定: 5-8 日相当。検証: CaTeO3 14 フレーム (git 管理内は 2 フレームのみ — 残りは
ローカル既存データ or fetch)、K-10 operando (echem, ローカル)。

## V2c — 配布 (Tauri sidecar)

| # | タスク | 内容 |
|---|---|---|
| C1 | sidecar Tier1 | PyInstaller で **コア + web extra のみ** を固める (GSAS はローカル導入前提、パス検出は既存の `gsas2-source.pth` 方式)。Tauri `externalBin` 登録 + spawn→health check→load |
| C2 | GSAS 同梱調査 | GSAS-II バイナリ + scriptable のフル同梱可否 (サイズ/ライセンス/バイナリ解決) を検証しレポート。可なら Tier2 実装、不可なら導入ガイド同梱で確定 |
| C3 | 配布物 | Windows インストーラ (署名なし)。自動更新は M-later |

推定: 3-5 日相当 + C2 は調査次第。**C1 と C2 の判断が最大の不確実性** — C2 調査を
wave 冒頭に前倒しする。

## V3 候補 (v2 スコープ外と明示)

- **AUTO 実 LLM ブリッジ**: ③ (Claude Code / claude-agent-sdk) のセッションを workbench
  transcript に接続する境界。設計文書を先に (`docs/design/gui-workbench/agent-bridge.md`)。
  それまでの AUTO は「custody UI + 記録」のまま
- MEM 密度マップ (FR-601 `.grd` → 断面 heatmap)、OED 提案タブ (FR-700)
- Review Queue モバイル要約カード (FR-421)、複数プロジェクト同時セッション
- nested 再裁定の可視化 (FR-500, ② 露出は Issue #130 系の続き)

## 横断の不変条件 (v2 全タスク)

1. 新エンドポイント/フィールドは **api-contract.md 更新が先** (enum 語彙は §語彙 へ)
2. 実データが無い領域は empty-state (シード偽装禁止)。数値は null 安全フォーマッタ経由
3. 変更系は ledger 追記 + revert 可能。長時間処理はジョブ (409/status ポーリング) 型を踏襲
4. ガード系テストは変異実証 (並行系は `sys.setswitchinterval(1e-6)` の教訓を適用)
5. ② に既にある機能を GUI 側で再実装しない — JSON spec 経路の再利用を第一候補にする
