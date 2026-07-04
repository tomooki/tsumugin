# ADR-0001: GUI / フロントエンド技術選定

**作成日**: 2026-07-04
**ステータス**: Accepted
**関連要件**: FR-402 (最終選択2モード) / FR-403 (エスカレーション) / FR-404 (コスト追跡) /
FR-420〜424 (人間介入インターフェース: Review Queue・仮説diff・ledger遡及) / REQ-007 (read-only Web UI)
**関連実装**: `src/tsumugin/webui/` (M1 read-only), TASK-0020/0021 (ReviewQueue / FinalSelectionEngine エンジン)

**【信頼性レベル凡例】**: 🔵 要件・仕様・既存実装に依拠 / 🟡 妥当な推測で確定 / 🔴 根拠なし推測

---

## 背景 🔵

GUI には 2 つの層が並存する。

1. **結果閲覧 (read-only)** — M1 で実装済み。`FastAPI + uvicorn` + 同梱静的 HTML 1 枚
   (optional extra `web`, localhost バインド, ビルドツール無し)。閲覧のみ。
2. **本格的な操作 GUI** — Review Queue、human モードの裁定/差し戻し、仮説 diff 表示
   (フィット・残差・basin 構造)、ledger 遡及リンク、エージェント進捗/コストのライブ表示。
   FR-420〜424。**技術選定は未実施だった。**

さらに将来、本プロジェクトを **GSAS-II のような対話的科学可視化を伴うデスクトップアプリ**として
配布する構想がある。

## 決定 🔵

### 1. 最終形フロントエンド = **FastAPI × React(+ Tauri でデスクトップ配布)**

- バックエンドは既存の **FastAPI** を安定契約 (OpenAPI) として据え置く。
- フロントエンドは **React**(構造・密度の 3D 可視化を見据え、three.js / react-three-fiber /
  Plotly / deck.gl 等のエコシステムが最大)。
- デスクトップ配布は **Tauri** で行う。FastAPI を PyInstaller で固め **sidecar** として同梱し、
  Tauri のシステム WebView から localhost を開く。Electron は不採用(Chromium 同梱で重い)。
- **根拠**: GSAS-II 級の目標はクライアント側に重い対話状態を持つ領域であり、サーバ駆動 UI が
  不利になるケースに合致する。「デスクトップ配布」自体はフロント選定を強制しない
  (パッケージングと直交)が、「**対話的科学可視化を伴う配布製品**」という目標が React を正当化する。

### 2. 中間の **NiceGUI は採用しない(飛ばす)** 🔵

- 検討したが、終着点が React+Tauri で確定している以上 NiceGUI は定義上の中間物であり、
  YAGNI の観点で導入しない。
- **成立条件**: 「React 製品ができる前に人が対話操作する GUI が必要か」= **不要**と判断。
  - Review Queue / FinalSelectionEngine / detect_escalations は **エンジンとして実装済み**
    (TASK-0020/0021)。未実装は presentation 層のみ。
  - human-in-the-loop は当面 **Python API / CLI / 既存 read-only Web UI** で運用可能。
- これにより中間フロントの throwaway 実装がゼロになる。

### 3. Streamlit / Dash / Panel / Electron は不採用 🟡

- Streamlit: スクリプト再実行モデルが長時間非同期・細粒度 UI・accept/revert と相性が悪い。
- Dash/Panel: 独自サーバで既存 FastAPI と二重化。科学プロットは強いが本要件の主成分ではない。
- Electron: Tauri 比で重く、Node ランタイム直利用の必然性が無い。

## 守るべき規律 🔵

1. **バックエンドを安定契約として先行させる。** FastAPI の OpenAPI スキーマを意図的に凍結・
   バージョン管理し、React はこの文書化済み表面に対して書く。
2. **ロジックをビュー層へ漏らさない。** 全ロジックは FastAPI / コアに置く。GUI は薄い表示/操作層。
3. **操作 UX の検証が必要になった場合**でも、恒久 UI としての NiceGUI ではなく使い捨て前提の
   薄い手段(HTMX ページ / ノートブック等)で行う。

## 差し替え/前倒しのトリガー 🟡

以下が現実になった時点で React+Tauri フロントの着手を前倒す:

- 配布製品化が具体化し、署名付きインストーラ・自動更新・深い OS 統合が要件化した。
- 開発中に人手操作 GUI が必要になった(その場合は上記「規律 3」の軽量手段を優先検討)。

## 影響 🔵

- M2 以降の「Review Queue 最小版」等は、当面 **エンジン + API/CLI** で満たし、恒久 GUI 実装は
  React 着手時にまとめて行う。
- コア依存 (numpy のみ) は不変。`web` extra (fastapi/uvicorn) は read-only Web UI 用として継続。
