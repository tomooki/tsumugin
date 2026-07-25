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
| `session.py` | `WorkbenchSession` — Ledger / SnapshotStore / ReviewQueue / FinalSelectionEngine / SearchResult(任意) / transcript・承認・ステージ状態を束ねる可変セッション。numpy-only。 |
| `seed.py` | 決定論シードデータ (プロトタイプ同値の view-model: fit/params/phase-id/sequence/structure/transcript)。純 dict を返す関数群。 |
| `app.py` | `create_workbench_app(session) -> FastAPI` + `serve()`。fastapi 遅延 import (`web` extra)。ビルド済み frontend があれば静的配信。 |

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
  + コンポーネント別 plain CSS。radius 0 / blueprint corner / 反転警告の規約を common
  コンポーネント (`BlueprintCard`, `Chip`, `CornerFrame`) に集約。
- i18n: `src/i18n/strings.ts` — プロトタイプの `L(en, ja)` 全ペアを抽出した辞書 +
  `useI18n()`。キー欠落は型で防ぐ (en/ja 同一キー集合を型検査)。
- 元素表: `src/data/elements.ts` — GSAS-II 原子番号順 98 元素 + H 直後に D (99 択)。
- API: `src/api/client.ts` — 型付き fetch ラッパ。ベース URL は同一オリジン
  (Tauri でも localhost sidecar と同一オリジン)。

### コンポーネント分割

```
components/shell/   TitleBar (モードトグル・言語・チップ) / ContextBar / StatusBar / LeftRail
components/common/  BlueprintCard / Chip / MetricCard / PlaceholderPlot / MonoTable ...
components/tabs/    FitTab / ParametersTab / HypothesesTab / PhaseIdTab /
                    SequenceTab / StructureTab / LedgerTab
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

## Tauri `desktop/`

- Tauri 2 最小 shell。`frontendDist` = `../frontend/dist`、
  開発時は `beforeDevCommand` で vite、本番は FastAPI sidecar
  (`externalBin` に PyInstaller 生成物を登録する構成だけ用意し、v1 は
  `desktop/sidecar/build_sidecar.md` に梱包手順を文書化)。
- v1 受け入れ = `cargo build` (debug) が通り、dev 構成でウィンドウが UI を表示できる。

## 決定と根拠 (要点)

- **webui と分離**: read-only 保証 (REQ-007) は「変更系ルートを定義しない」ことで構造的に
  担保されている。同一アプリへの POST 追加はその保証を壊すため、新パッケージに分離。
- **シードもバックエンド供給**: フロントにデータを持たせると実 API 差し替え時に view を
  書き直すことになる。`/api/viewmodel` の形を実データの契約として先に凍結する
  (ADR-0001 規律 1: バックエンド安定契約の先行)。
- **チャート v1 placeholder**: ハンドオフの明示指定。枠geometry と軸ラベルを保持し、
  後続で Plotly 等に差し替える。
- **NiceGUI 等の中間物なし**: ADR-0001 決定の履行。
