# GUI Workbench アーキテクチャ (gui-workbench)

**要件**: `docs/spec/gui-workbench/requirements.md` / **UI 正**: `handoff/README.md` +
`handoff/Tsumugin Workbench.dc.html` (プロトタイプが look & interaction の正)

## 全体構成

```
frontend/            React + Vite + TypeScript (表示/操作層のみ)
src/tsumugin/workbench/   操作系 FastAPI (① エンジン直結 + シード供給)
desktop/             Tauri 2 シェル (sidecar = FastAPI, ADR-0001)
```

- 既存 `src/tsumugin/webui/` (read-only, REQ-007) は**不変更**。
- フロントは OpenAPI 化された workbench API のみを叩く。ロジック (裁定・検証・整形・
  ledger 追記) は全てバックエンド側 (ADR-0001 規律 2)。

## バックエンド `tsumugin.workbench`

### モジュール

| ファイル | 役割 |
|---|---|
| `session.py` | `WorkbenchSession` — Ledger / SnapshotStore / ReviewQueue / FinalSelectionEngine / SearchResult(任意) / transcript・承認・ステージ状態を束ねる可変セッション。numpy-only。`create_demo()` (シード) と `from_project()` (実プロジェクト) の 2 系統。変更は内部 `threading.Lock` で直列化 (FastAPI sync ハンドラは threadpool 実行 + refine ジョブスレッドが並走するため)。 |
| `seed.py` | 決定論シードデータ (プロトタイプ同値の view-model: fit/params/phase-id/sequence/structure/transcript)。純 dict を返す関数群。demo モード専用。 |
| `project.py` | **実プロジェクト境界**: JSON プロジェクト spec (histograms/phases は ② `auto_rietveld` と同一スキーマ = `HistogramSpec.from_dict`/`PhaseSpec.from_dict` を再利用) のロード + 検証 + 精密化前プレビュー (`reference.io.load_pattern`, numpy-only) + viewmodel 構築。 |
| `jobs.py` | **精密化ジョブ**: `RefinementJobManager` — `run_auto_rietveld` を `threading.Thread` で実行 (先例なしの新設計)。状態 `idle/running/done/failed`、進捗は ledger 追記 (engine に session ledger を渡す) の最新エントリで報告。完了時に lock 下で session を更新 (metrics/history/validity/wt%/曲線) + snapshot + ledger。runner は callable 注入可 (**テスト専用**、実運用既定は `run_auto_rietveld`、§4.5)。 |
| `curves.py` | **プロット曲線抽出**: 精密化済み gpx から `hist.data["data"][1]` = [x, Yobs, weight, Ycalc, Ybkg, Ydiff] と `Reflection Lists` を読み、`{x, yobs, ycalc, ybkg, residual, ticks}` に構造化。**≤2000 点へ間引き** (大配列を境界で無制限に跨がせない)。GSAS 遅延 import。workbench (FOUNDATIONAL) 内に置くことで ① への機能追加を避ける。 |
| `app.py` | `create_workbench_app(session) -> FastAPI` + `serve()`。fastapi 遅延 import (`web` extra)。ビルド済み frontend があれば静的配信。`POST /api/refine` (202/409) + `GET /api/refine/status` (ポーリング)。 |

### モード制御 (FR-402)

`final_selection_mode` の実行時単一情報源は既存どおり `FinalSelectionEngine.mode`。
`POST /api/mode` は `engine.set_mode()` を呼び (エンジン側が ledger 追記)、GUI 語彙
manual/auto ↔ エンジン語彙 human/agent の写像はバックエンドで行う
(`manual→human`, `auto→agent`)。

### API 表面 (v1)

| Method Path | 動作 | 配線先 |
|---|---|---|
| GET `/api/state` | シェル状態 (project, mode, ledger count+verify, snapshots, tokens/wall-time) | 実 |
| POST `/api/mode` `{mode}` | モード切替 + ledger | 実 (`set_mode`) |
| GET `/api/viewmodel` | タブ表示用シードデータ一式 (fit/params/phaseid/sequence/structure/transcript/stages/review) | シード+実混成 |
| GET `/api/hypotheses` | ランキング | 実 (`SearchResult`) / シード fallback |
| POST `/api/hypotheses/{id}/accept` `{by}` | accepted 化 | 実 (`engine.accept`; human モードで by=agent は recommend_only) |
| POST `/api/revert` `{hypothesis_id, note}` | 裁定差し戻し | 実 (`engine.revert`) |
| GET `/api/review-queue` | 未解決含む一覧 | 実 (`ReviewQueue`) |
| POST `/api/review-queue/{id}/resolve` `{action, note}` | ACCEPT / SEND BACK | 実 (`resolve` + ledger) |
| GET `/api/ledger` | 追記専用エントリ列 | 実 |
| POST `/api/structure/apply` `{sites}` | ReviseStructure: 子スナップショット + ledger | 実 (`SnapshotStore.save`) |
| POST `/api/approval/{id}` `{decision}` | ModelAction 承認/却下 (両経路 ledger) | 実 (approve 時のみ snapshot) |
| POST `/api/stages/{nn}` `{action}` | ステージ release/revert 記録 | セッション状態 + ledger |
| POST `/api/refine` | 精密化要求の受理 (202 + ledger)。実 runner は M-later | 記録のみ |
| POST `/api/transcript/message` `{text}` | composer 送信の記録 | セッション状態 |

規約 (② と同じ流儀): ハンドラは例外を送出させず、既知の失敗は
`{"error": ..., "error_type": ...}` + 4xx に縮退。不正入力を「正常」と返さない。
変更系は必ず ledger 追記を伴う (NFR-GUI-001)。削除系ルートは定義しない。

## フロントエンド `frontend/`

- Vite + React 18 + TypeScript strict。テスト: vitest + @testing-library/react (jsdom)。
- 状態: React context + reducer (`src/state/`)。ハンドオフ「State」節の形をそのまま採用
  (lang/mode/tab/hist/hyp/sites/edits/paramRel/stageOn/approval/review/draft...)。
- スタイル: `src/styles/tokens.css` に Industry トークンを 1:1 移植 (唯一 hex を持つ場所)
  + コンポーネント別 plain CSS。radius 0 / blueprint hairline 枠 / 反転警告の規約を common
  コンポーネント (`BlueprintCard`, `Chip`) に集約。※四隅の `+` レジストレーションマークは
  Claude Design プロトタイプの演出であり製品には載せない (2026-07-25 全削除)。
- i18n: `src/i18n/strings.ts` — プロトタイプの `L(en, ja)` 全ペアを抽出した辞書 +
  `useI18n()`。キー欠落は型で防ぐ (en/ja 同一キー集合を型検査)。
- 元素表: `src/data/elements.ts` — GSAS-II 原子番号順 98 元素 + H 直後に D (99 択)。
- API: `src/api/client.ts` — 型付き fetch ラッパ。ベース URL は同一オリジン
  (Tauri でも localhost sidecar と同一オリジン)。

- **可変幅レイアウト** (2026-07-27 改訂): 元の UI 設計は固定 1920x1080 だったが、実機の狭い
  ウィンドウで右側が見切れて操作できなかったため、ビューポート追従へ変更した。`.shell` は
  `grid-template-columns: minmax(0, 1fr)` を明示する (暗黙列が auto = 中身の max-content に
  なり、nowrap テキストがグリッド全体をビューポートより広げていた)。段階的に畳む:
  1500px 以下で右ペインを絞る → 1180px 以下で左レールを畳む (同じ情報は PROJECT タブにある)
  → 820px 以下で右ペインも畳み中央 1 カラム。**中央の解析キャンバスを最後まで残す**のが原則。
  タブ列と 3 本のバーは畳まず横スクロール、広い表は表単位で横スクロールさせる。

### コンポーネント分割

```
components/shell/   TitleBar (モードトグル・言語・チップ) / ContextBar / StatusBar / LeftRail
components/common/  BlueprintCard / Chip / MetricCard / PlaceholderPlot / MonoTable ...
components/tabs/    ProjectTab / PhasesTab / FitTab / ParametersTab / HypothesesTab /
                    PhaseIdTab / SequenceTab / StructureTab / LedgerTab
components/right/   OperatorConsole (recipe+gating+review) / AgentSession (transcript+composer)
```

### 重要な UI 不変条件 (テストで担保)

1. モード切替で差し替わる DOM は右ペイン+モードチップ+ステータス文のみ (センターの
   state 保持)。
2. DISCARD は pending edits ゼロで disabled、適用済みベースラインへは触れない。
3. ステージゲート: 対応グループのチェックが空なら `gated · …` 行 (neutral-900) を表示し
   RELEASE を送らない。
4. EN/JA 辞書はキー集合一致 (型 + テスト)。数値・ツール名・JSON は辞書外。
5. 破壊的コントロール不在 (LEDGER に削除 UI が無い、承認 REJECT も ledger 追記表示)。
6. 元素ドロップダウンは 99 要素・D は H 直後。
7. **プロトタイプ由来の固定表記を製品に残さない** (2026-07-27)。ハンドオフの `L(en, ja)` 辞書は
   デモ系列 (K₂Mn[Fe(CN)₆] operando) の具体値を文字列に焼き込んでおり、そのまま出すと**どの
   プロジェクトを開いても同じ数値・相名・元素系が表示される**。実データと食い違う表示は
   empty-state 規律 (シード値で実データを偽装しない) の裏返しの違反である。既知の対処:
   - PHASE ID の元素系 → `viewmodel.phase_id.elements` (実 CIF 由来。空なら元素の記述自体を出さない)
   - STRUCTURE の相名/空間群 → `viewmodel.phases`
   - タイトルバー `ledger.verify()` → `state.ledger.verified` (**常時 TRUE 表示は改竄検知を無効にする**)
   - タイトルバーのトークン/経過時間 → `state.agent.tokens`/`wall_time_s` (FR-404)
   - FIT プロット注記の λ と "log y"、HYPOTHESES の "14 nodes"、SEQUENCE の "63 frames" → 削除
     (λ はプロジェクト毎に異なり、LinePlot は線形軸)
   恒久ガードは各タブのテスト (`*.test.tsx` の "never hard-codes …") に置く。**変異させて fail
   することを実証済**。
8. **PHASES タブは相スコープの解放だけを扱う** (2026-07-27)。左レールの PHASES IN MODEL が
   「どの相が居るか」を示すのに対し、こちらは「相ごとに何を解放するか」。編集できるのは
   `PhaseSpec.refine_cell` **のみ** — engine (`_apply_stage`) が相単位で読む唯一の解放スイッチ
   だからである。`size_strain`/`preferred_orientation`/`hydrostatic_strain` は物理的には相
   スコープだが engine が全相へ一律適用しており、**チェックボックスを置くと「触れるのに効かない」
   コントロールになる**ため読み取り専用 (「触れる段」列) に留める。相単位化はレシピのルール化と
   同じ作業単位。
9. **相同定は元素選択から始められる** (2026-07-27)。PHASE ID タブに元素セレクタを置き、
   `POST /api/phaseid` の `elements` へ渡す。「CIF を読み込んでから相同定」は未知試料の単一解析で
   成り立たない動線 (相の CIF は同定の**結果**) — 相 0 件のプロジェクトでも同定でき、ADD AS PHASE
   の物質化も同じ元素系を使う。`elements` 省略時のみ CIF 由来導出 (operando 経路の互換)。
   D は元素表にあるが MP の chemsys に無い同位体なのでセレクタに出さず、② 経由で来ても
   「H を指定せよ」と個別に案内する。
10. LEDGER 行は精密化由来のエントリにのみ Rwp / BIC を出す (`GET /api/ledger` の `rwp`/`bic`)。
   値のないエントリは**空欄** — `―` は「あるはずの値が欠けている」に予約する。BIC は
   `insitu.anchor.select.frame_bic` と同一式 (相数の比較は Rwp でなく BIC、CLAUDE.md の規律)。

## Tauri `desktop/`

- Tauri 2 最小 shell。**リモート URL 方式**: `devUrl` = `frontendDist` =
  `http://127.0.0.1:8770` — UI は FastAPI (workbench) が配信するビルド済み
  `frontend/dist` をそのまま見る (API と同一オリジンになり、sidecar 本番構成と
  開発構成が一致する)。vite dev server は Tauri 経路では使わない。
  本番は FastAPI sidecar (`externalBin` に PyInstaller 生成物を登録する構成は
  v1 ではバイナリ不在でビルドが落ちるため未設定とし、`desktop/README.md` に
  梱包手順を文書化)。
- v1 受け入れ = `cargo build` (debug) が通り、dev 構成でウィンドウが UI を表示できる。

## 決定と根拠 (要点)

- **webui と分離**: read-only 保証 (REQ-007) は「変更系ルートを定義しない」ことで構造的に
  担保されている。同一アプリへの POST 追加はその保証を壊すため、新パッケージに分離。
- **シードもバックエンド供給**: フロントにデータを持たせると実 API 差し替え時に view を
  書き直すことになる。`/api/viewmodel` の形を実データの契約として先に凍結する
  (ADR-0001 規律 1: バックエンド安定契約の先行)。
- **チャートは自前 SVG コンポーネント** (`frontend/src/components/charts/`): ランタイム依存
  react のみの規律を維持し、Industry トークンで描く軽量 SVG (LinePlot: yobs 点列 + ycalc 線 +
  残差パネル + 反射 tick 行 / SeriesChart: 折れ線・散布)。series/plot が null のときは
  ハンドオフと同じ破線 empty-state 枠に縮退 (「実チャート = データがあれば描く・無ければ
  枠」)。Plotly 等の導入は 3D/対話要件が出た時点で再検討 (ADR-0001)。
- **実プロジェクト接続 (v1 実用形)**: 起動 `python -m tsumugin.workbench --project <spec.json>`。
  spec の histograms/phases は ② `auto_rietveld` ツールと同一 JSON スキーマ (from_dict 共有)。
  起動直後は load_pattern による yobs のみのプロット + 実相リスト。RUN REFINEMENT →
  バックグラウンドで実 `run_auto_rietveld` (数十秒〜数百秒) → 完了で実 metrics / stage 履歴
  (ΔRwp は隣接差分で計算) / validity (`ValidityReport.checks`) / wt%(esd) / 実曲線 + 子スナップ
  ショット + ledger。デモ project は git 管理済みの CaTeO3 (m9, 既知 Rwp ~13.4%) を
  `docs/benchmark/testdata/m9/cateo3/` から使用 (`examples/cateo3_project.json`)。
- **v1 で残る表示制約 (明示)**: project モードの STRUCTURE 座標 (x/y/z) は
  `AutoRietveldResult` に含まれないため「―」表示 (occ/Uiso±esd は実値)。PARAMETERS の
  実値反映は radiation (spec 由来) + 精密化後の `hist_profile` のみ。SEQUENCE 実系列は
  逐次解析 (M9/M10) の接続後。MEM 密度マップは実 MEM 実行 (FR-601) の配線後。
  いずれも空データ empty-state として正直に表示する (シード値でごまかさない)。
- **NiceGUI 等の中間物なし**: ADR-0001 決定の履行。
