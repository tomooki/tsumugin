# Tsumugin Workbench — Desktop shell (Tauri 2)

デスクトップ配布用の薄い Tauri 2 シェル。設計判断の背景は
`docs/design/adr/0001-gui-frontend-stack.md` と
`docs/design/gui-workbench/architecture.md` §Tauri を参照。

このシェルにビジネスロジックは無い。全ロジックは FastAPI バックエンド
(`src/tsumugin/workbench/`) と React フロントエンド (`frontend/`, FastAPI が
静的配信) にあり、Tauri はシステム WebView でそれを表示するだけ (ADR-0001 規律 2)。

## Dev で起動する

Tauri は **vite dev server を起動しない** (`beforeDevCommand` 未設定)。
`tauri.conf.json` の `build.devUrl` は FastAPI が配信するビルド済み UI
(`http://127.0.0.1:8770`) を直接指す。手順:

1. フロントエンドをビルドする (未ビルドなら):

   ```
   cd frontend
   npm install
   npm run build
   ```

2. FastAPI バックエンドを起動する (別ターミナル、リポジトリルートから):

   ```
   uv run python -m tsumugin.workbench
   ```

   既定でポート 8770、`frontend/dist` を静的配信する
   (`src/tsumugin/workbench/__main__.py` 参照)。

3. Tauri シェルを起動する:

   ```
   cd desktop/src-tauri
   cargo tauri dev
   ```

   (`cargo tauri` サブコマンドが無ければ `cargo install tauri-cli --version "^2"`
   で一度だけ導入するか、`npx @tauri-apps/cli dev` を使う。ビルドのみ確認したい
   場合は `cargo build` で足りる — ウィンドウは開かない。)

手順 2 のサーバが立っていない状態で `cargo tauri dev`/`cargo run` を実行すると、
WebView は `http://127.0.0.1:8770` への接続に失敗する (これは Tauri 側の不具合
ではなく、サーバ未起動が原因)。

## ビルド確認のみ (CI / v1 受け入れ)

UI を実際に開かず、Rust 側のコンパイルだけを確認する場合:

```
cd desktop/src-tauri
cargo build
```

`v1` の受け入れ基準はこれが exit 0 で通ることと、dev 構成 (上記手順) でウィンドウが
UI を表示できること (`docs/design/gui-workbench/architecture.md` §Tauri)。

## アイコン

`icons/` は `npx @tauri-apps/cli icon icons/icon-source.png -o icons` で生成した
プレースホルダ (`icon-source.png`: 1024x1024、accent 色 `#5980a6` の単色地に白 "T")。
本番配布前にブランドアイコンへ差し替えること。モバイル向け (`android/`/`ios/`)
アイコンは v1 では生成していない (デスクトップ配布のみが対象)。

## 本番 sidecar 梱包 (M-later)

v1 は `externalBin` を設定していない (バイナリが実在しないと `tauri build` が
失敗するため、未導入のまま `cargo build` を通す方を優先した)。本番配布時の設計
(ADR-0001 §1) は以下の通り:

1. **FastAPI バックエンドを PyInstaller で単一実行体に固める。**
   `uv run python -m tsumugin.workbench` 相当のエントリポイントを
   (デモセッションではなく実プロジェクトを読み込む形に差し替えて) one-file 化する。
   GSAS-II 同梱 (バイナリ + `GSASII-bin`) は依存が大きく **M-later** — v1 では
   sidecar 側は GSAS 抜きのコアのみか、開発機の GSAS-II 導入に依存する運用とする。
2. **Tauri の `externalBin` に登録する**: `tauri.conf.json` の `bundle.externalBin`
   に PyInstaller 出力 (`tsumugin-workbench-x86_64-pc-windows-msvc.exe` のような
   target-triple サフィックス付き命名, Tauri の sidecar 命名規約に従う) を追加し、
   Rust 側 (`src-tauri/src/lib.rs`) の `setup` フックでプロセスを spawn して
   `http://127.0.0.1:8770` (または動的に空きポートを選び `frontendDist` 相当の
   URL を Tauri 側で構築) を待ち受けてからウィンドウを開く。
3. **`build.frontendDist` は本番も同一オリジンの URL 方式のまま**
   (Tauri 2 は `frontendDist` に URL を許す) — sidecar が同じ静的 UI (`frontend/dist`)
   を同じポートで配信する設計なので、dev/prod でフロント側の API ベース URL
   切り替えが不要になる (`frontend/src/api/client.ts` の「同一オリジン」前提を参照)。
4. 署名・自動更新・インストーラは未着手 (ADR-0001「差し替え/前倒しのトリガー」参照)。

## ディレクトリ構成

```
desktop/
  README.md              このファイル
  src-tauri/
    Cargo.toml
    build.rs
    tauri.conf.json
    src/
      main.rs             バイナリエントリ (windows_subsystem 切替のみ)
      lib.rs              tauri::Builder 起動 (カスタム IPC コマンド無し)
    capabilities/
      default.json        メインウィンドウ用の最小 core 権限
    icons/                プレースホルダアイコン一式 (npx tauri icon 生成)
```
