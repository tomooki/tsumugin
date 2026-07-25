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

**⚠ V2c C1 以降の前提変更**: `tauri.conf.json` に `bundle.resources` (sidecar 同梱) を
登録したため、**`desktop/src-tauri/binaries/` が存在しないと `cargo build`/`cargo tauri dev`
自体が失敗する** (`resource path 'binaries' doesn't exist`, tauri-build のビルドスクリプトが
`cargo build` の度に検証する — 「本番のみ」ではなく全プロファイル共通)。CI やビルド確認の前に
必ず下記「本番 sidecar 梱包」の手順 1〜2 (`build_sidecar.ps1`) を一度実行すること。

## アイコン

`icons/` は `npx @tauri-apps/cli icon icons/icon-source.png -o icons` で生成した
プレースホルダ (`icon-source.png`: 1024x1024、accent 色 `#5980a6` の単色地に白 "T")。
本番配布前にブランドアイコンへ差し替えること。モバイル向け (`android/`/`ios/`)
アイコンは v1 では生成していない (デスクトップ配布のみが対象)。

## 本番 sidecar 梱包 (V2c C1, Tier1 実装済み)

FastAPI バックエンドを PyInstaller で固めて Tauri に同梱する (ADR-0001 §1)。**Tier1 =
コア + web extra のみ同梱** — GSAS-II はローカル導入前提のまま (下記「Tier1 の GSAS 前提」)。

### ビルド手順

```
# 1. フロントエンドをビルド (未ビルドなら)
cd frontend && npm run build && cd ..

# 2. PyInstaller sidecar を固めて desktop/src-tauri/binaries/ へ配置
powershell -ExecutionPolicy Bypass -File desktop/sidecar/build_sidecar.ps1

# 3. Rust 側をビルド (cargo build / cargo tauri dev / cargo tauri build のいずれも
#    手順 2 の binaries/ が無いと失敗する — 上の「⚠ V2c C1 以降の前提変更」参照)
cd desktop/src-tauri
cargo tauri build            # または cargo tauri build --debug (高速・未署名確認用)
```

`build_sidecar.ps1` は `uv run pyinstaller desktop/sidecar/sidecar.spec` (one-dir) を実行し、
出力 (`desktop/sidecar/dist/tsumugin-workbench-sidecar/`, exe + `_internal/` 依存フォルダ,
実測 ~80MB) を `desktop/src-tauri/binaries/` へ平置きコピーする。起動 exe は
`tsumugin-workbench-sidecar-<target-triple>.exe` (例:
`tsumugin-workbench-sidecar-x86_64-pc-windows-msvc.exe`) にリネームされ、`_internal/` と
同じディレクトリに置かれる — **PyInstaller one-dir は exe と `_internal/` が同一ディレクトリに
無いと起動できない** (これが下記「externalBin を使わない理由」)。`desktop/src-tauri/binaries/`
は生成物なので `.gitignore` 済み (毎回 `build_sidecar.ps1` で再生成する)。

### 設計判断: `externalBin` ではなく `bundle.resources` + 直接 spawn

Tauri 2 の sidecar 機構 (`bundle.externalBin` + `tauri-plugin-shell` の `.sidecar()`) は
「単一の再配置可能なバイナリ」を前提にしている。PyInstaller one-dir は exe 単体では動かず
依存一式 (`_internal/`) が要るため、この機構と相性が悪い (exe だけを `externalBin` の命名規約で
切り出すと `_internal` が孤立し実行時に壊れる)。そこで `tauri.conf.json` の
`bundle.resources: {"binaries": "sidecar"}` で `binaries/` 全体 (exe + `_internal/`) を
そのまま `<resource_dir>/sidecar/` へバンドルし、`src-tauri/src/lib.rs` が
`app.path().resource_dir()` を解決して `std::process::Command` で直接 spawn する
(`tauri-plugin-shell` は使わない — Rust 側からの直接 spawn は capabilities/ACL の対象外なので
`capabilities/default.json` の変更も不要)。`cargo build`/`cargo tauri dev`/`cargo tauri build`
いずれも `target/<profile>/sidecar/` に同じ相対構造で配置されることを実測確認済み。

### 起動シーケンス (`src-tauri/src/lib.rs`)

1. `setup()` フックが別スレッドで `bootstrap_backend` を起動 (イベントループを塞がない)。
2. **production ビルドのみ** (`!cfg!(debug_assertions)`) sidecar exe を spawn する — dev
   (`cargo tauri dev`) は従来どおり手動起動サーバ (`uv run python -m tsumugin.workbench`) に
   接続する挙動を維持する。spawn 失敗時も即エラーにはせず (「sidecar 不在時フォールバック」)
   次のヘルスチェックへ進む (すでに起動済みのバックエンドを拾える可能性があるため)。
3. `http://127.0.0.1:8770/api/state` を最大 30 秒ポーリング (300ms 間隔, 依存追加を避けるため
   素の `std::net::TcpStream` で HTTP/1.1 リクエストを手組みしステータス行のみ確認)。
4. 成功: メインウィンドウを `window.navigate()` で同 URL へ (再) 読み込みさせる
   (`tauri.conf.json` の `devUrl`/`frontendDist` 宣言だけだとサーバ起動前に一度読み込みを
   試みてしまうため、確実な成功後に navigate し直す)。
5. 失敗: `tauri-plugin-dialog` のエラーダイアログを表示 (`blocking_show`) し、手動起動の
   コマンドを案内する。
6. アプリ終了時 (`RunEvent::Exit`/`ExitRequested`) に spawn した子プロセスを kill する。

### Tier1 の GSAS 前提

Tier1 は **コア + web extra のみ同梱**。`desktop/sidecar/sidecar.spec` の `excludes` で
GSAS-II/pymatgen/mp_api/dynesty/galvani/mcp/periodictable/pycifrw/scipy を明示除外している
(いずれも `tsumugin` 側で遅延 import + `*UnavailableError` フォールバックが実装済みなので、
未同梱でも import 時に静かに機能を諦めるだけで起動は壊れない — CLAUDE.md「実装上の不変条件」)。

- **GSAS-II はローカル導入前提** (このリポジトリの開発機と同じ手順で別途導入する)。
- `GET /api/state` の `status.gsas_available` (毎回動的判定,
  `tsumugin.backends.gsasii.gsasii_available`) で可否を表明する
  (`docs/design/gui-workbench/api-contract.md`)。
- GSAS 必須ジョブ (`POST /api/refine`/`/api/multistart`/`/api/sequential`) は GSAS 不在時
  422 `{"error_type": "GSASUnavailableError"}` へ縮退する
  (`WorkbenchSession._guard_gsas_available`, `src/tsumugin/workbench/session.py`)。
  demo/project 閲覧・プロジェクト編集はそのまま動く。
  **⚠ phaseid (`POST /api/phaseid`, Materials Project 経由の相同定) は Tier1 では動かない** —
  `sidecar.spec` の `excludes` が `pymatgen`/`mp_api` も除外しているため (`_HEAVY_EXCLUDES`)。
  GSAS-II と異なり「ローカル導入すれば動く」形の遅延解決ではなく、Tier1 sidecar exe には
  そもそも同梱されていないので開発機に pymatgen/mp-api を入れても凍結 exe 側は変わらない。
  既知の制限として明記する (mp まで同梱する Tier1.5 相当は M-later)。
- 実測: PyInstaller ビルドした sidecar exe を単体起動すると `gsas_available: false`
  (GSAS-II が exclude されているため。開発機に GSAS-II があっても sidecar プロセス自体には
  同梱していないので反映されない — これは意図した Tier1 の挙動)。

### 未着手 (M-later)

署名・自動更新は未着手 (ADR-0001「差し替え/前倒しのトリガー」参照)。GSAS-II 同梱 (Tier2/3
相当) は依存が大きく別途。

## ディレクトリ構成

```
desktop/
  README.md              このファイル
  sidecar/                V2c C1: PyInstaller sidecar
    tsumugin_workbench_sidecar.py   エントリポイント (__main__.py と同一 CLI 契約)
    sidecar.spec                    PyInstaller one-dir スペック (Tier1 exclude リスト)
    build_sidecar.ps1               ビルド + desktop/src-tauri/binaries/ への配置
    dist/, build/                   PyInstaller 出力 (.gitignore 済み)
  src-tauri/
    Cargo.toml
    build.rs
    tauri.conf.json         bundle.resources: {"binaries": "sidecar"}
    binaries/               build_sidecar.ps1 の出力先 (.gitignore 済み, ~80MB)
      tsumugin-workbench-sidecar-<triple>.exe
      _internal/
    src/
      main.rs             バイナリエントリ (windows_subsystem 切替のみ)
      lib.rs              sidecar spawn + ヘルスチェック + エラーダイアログ (V2c C1)
    capabilities/
      default.json        メインウィンドウ用の最小 core 権限 (sidecar spawn は Rust 直接呼び出し
                           のため ACL 対象外 — 変更不要)
    icons/                プレースホルダアイコン一式 (npx tauri icon 生成)
```
