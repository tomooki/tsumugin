# GUI Workbench 要件 (gui-workbench)

**根拠**: `docs/tsumugin_spec_v0.3.md` FR-402/403/404, FR-420–424 / ADR-0001 /
デザインハンドオフ `docs/design/gui-workbench/handoff/README.md`

**目的**: 操作系デスクトップワークベンチ (FastAPI × React、Tauri 配布)。
③ 層 (最終判断者) を **人間 (MANUAL)** と **LLM (AUTO)** で切り替える GUI。
①決定論コア・② MCP 32+ ツールは両モードで同一。

## 機能要件

- **REQ-GUI-001 (FR-402)**: モードトグル MANUAL/AUTO はプロジェクト設定
  `final_selection_mode` (`human`|`agent`) に束縛される。切替はそれ自体が ledger 追記
  (`HUMAN · mode switch manual → auto`)。切替で変わるのは右ペイン+モードチップ+
  ステータス文のみ。センター/左ペインの状態は不変。
- **REQ-GUI-002 (FR-421/423)**: MANUAL 右ペインに Review Queue。項目の
  ACCEPT / SEND BACK は ①`ReviewQueue.resolve` へ配線され ledger 記録される。
- **REQ-GUI-003 (FR-422)**: HYPOTHESES タブに仮説ランキング表 + 選択仮説の DIFF +
  EVIDENCE & BASIN 表示。僅差競合 (close) と demoted (chem) を可視化。
- **REQ-GUI-004 (FR-424)**: LEDGER タブは追記専用エントリ列を表示し、actor 別色分け・
  ハッシュ・`REVERT TO` リンクを持つ。削除・編集 UI は存在しない。
- **REQ-GUI-005 (FR-403)**: AUTO transcript にエスカレーションカード。エスカレーションは
  ループをブロックしない (暫定裁定 + 要確認フラグ) ことを表示で明示。
- **REQ-GUI-006 (FR-404)**: エージェントコスト表示は **tokens + wall-time のみ**。
  $ 表示は置かない (ハンドオフ指定)。
- **REQ-GUI-007**: 7 タブ (FIT / PARAMETERS / HYPOTHESES / PHASE ID / SEQUENCE /
  STRUCTURE / LEDGER) をハンドオフの高忠実度指定どおり再現。プロット/マップ領域は
  v1 では枠+軸ラベルの placeholder (実チャートは後続)。
- **REQ-GUI-008**: STRUCTURE タブの `APPLY AS ReviseStructure` は子スナップショット +
  ledger 追記 (提案≠適用、適用は明示操作)。DISCARD は**未適用編集のみ**破棄し、
  適用済みモデルには触れない。編集ゼロ時は disabled。
- **REQ-GUI-009**: AUTO の ModelAction 承認カード — APPROVE & APPLY / REJECT の両経路とも
  提案を ledger に残す。SafeAction は自動適用可、ModelAction は必ず人間の承認を要する。
- **REQ-GUI-010**: EN/日本語切替。数値・ツール名・JSON・パラメータ記号は翻訳しない
  (API 表面)。
- **REQ-GUI-011**: MANUAL の staged release recipe は PARAMETERS / STRUCTURE の
  チェック状態にゲートされる (gated 状態をライブ表示)。

## 非機能・不変条件

- **NFR-GUI-001 (P2)**: 破壊的コントロールを一切置かない。全状態変更 = 追記 + revert。
  バックエンドに削除・上書き API を作らない。
- **NFR-GUI-002 (ADR-0001 §2)**: ロジックをビュー層へ漏らさない。判断・検証・整形は
  FastAPI/コア側。GUI は薄い表示/操作層。
- **NFR-GUI-003 (NFR-101)**: バインドは localhost 既定。認証なし公開はしない。
- **NFR-GUI-004**: 既存 read-only webui (REQ-007) は変更しない。操作系は別アプリ
  (`tsumugin.workbench`) として追加し、read-only 保証を構造的に維持する。
- **NFR-GUI-005**: コア import 非汚染 — fastapi/uvicorn は遅延 import (`web` extra)。
- **NFR-GUI-006**: デザイントークンは Industry DS を 1:1 移植。生 hex をコンポーネントに
  書かない (トークン CSS のみが値を持つ)。警告状態は色相追加でなく明度反転
  (neutral-900 反転チップ)。

## v1 スコープ (実用形 — 2026-07-25 改訂)

- **REQ-GUI-012 実プロジェクト接続**: `--project <spec.json>` で実データ (パターン +
  CIF + instprm) に接続する。spec の histograms/phases は ② `auto_rietveld` と同一
  JSON スキーマ (`HistogramSpec/PhaseSpec.from_dict` 共有 — §4.5 到達可能性)。起動直後に
  実測パターン (yobs) を表示。demo モード (シード) は引数なし起動として維持。
- **REQ-GUI-013 実 RUN REFINEMENT**: project モードの RUN REFINEMENT は実
  `run_auto_rietveld` をバックグラウンド実行 (202 + status ポーリング、二重起動 409)。
  完了で実 Rwp/GOF/stage 履歴/validity/wt%±esd/フィット曲線に更新 + 子スナップショット +
  ledger。失敗は status=failed + error 文字列 (例外を境界に貫通させない)。
- **REQ-GUI-014 実チャート**: プロット領域は実 SVG チャート (FIT: yobs/ycalc/残差/反射
  ticks、SEQUENCE: 系列折れ線、EVIDENCE: basin 散布)。**データが無い領域は破線
  empty-state 枠に縮退し、シード値で実データを偽装しない**。
- **シードデータ**: demo モード専用。フロントにデータをハードコードしない原則は不変。
- **LLM チャットループ**: AUTO の実 LLM 駆動は本 GUI の外 (③ = Claude Code / MCP)。
  transcript の表示・承認カード操作・composer 送信の記録まで。
- **v1 残存制約 (明示)**: project モードの STRUCTURE 座標表示は「―」 (result 未収録)、
  PARAMETERS 実値は radiation + 精密化後 profile のみ、SEQUENCE 実系列は M9/M10 接続後、
  MEM 密度マップは FR-601 配線後。Tauri は scaffold + dev 構成 (sidecar 梱包 M-later)。
