# TASK-0001 設定作業実行

## 作業概要

- **タスクID**: TASK-0001 (web extra 追加とパッケージ骨格)
- **作業内容**: M1 新規パッケージ骨格 (`search/`, `export/`, `webui/`) と optional extra `web` の追加、依存同期
- **実行日時**: 2026-07-03
- **実行者**: direct-setup (Claude)

## 設計文書参照

- **参照文書**: `docs/tasks/m1-hypothesis-search/TASK-0001.md`, `docs/design/m1-hypothesis-search/architecture.md`, `docs/spec/m1-hypothesis-search/note.md`, `CLAUDE.md`
- **関連要件**: FR-110〜117 (search), FR-505 (export), FR-421〜424 縮小版 (webui)

## 実行した作業

### 1. 依存関係の追加 (pyproject.toml)

`[project.optional-dependencies]` に `web` extra を追加:

```toml
# M1 Web UI 最小版 (read-only): FastAPI アプリ + uvicorn 起動。
web = [
    "fastapi>=0.110",
    "uvicorn>=0.29",
]
```

`[dependency-groups]` dev に `httpx>=0.27` を追加 (webui のテストクライアント用):

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "httpx>=0.27",
]
```

### 2. パッケージ骨格の作成

docstring のみの空パッケージ (既存モジュールの単一行日本語 docstring スタイルに準拠):

- `src/tsumugin/search/__init__.py` — `"""多仮説木探索 (FR-110〜117)。"""`
- `src/tsumugin/export/__init__.py` — `""".gpx 書き出し (FR-505)。"""`
- `src/tsumugin/webui/__init__.py` — `"""Web UI 最小版 (read-only, FR-421〜424 縮小版)。"""`

いずれも `from __future__ import annotations` と `__all__: list[str] = []` を持つ。

### 3. 依存関係のインストール

```bash
uv sync --extra gsas --extra web
```

**重要**: `--extra gsas` を必ず併用 (プレーン `uv sync` は GSAS-II 依存が外れるため禁止 — CLAUDE.md 参照)。

結果 (抜粋):

```
Resolved 34 packages in 265ms
Prepared 7 packages / Installed 15 packages
 + fastapi==0.139.0
 + uvicorn==0.49.0
 + httpx==0.28.1
 + starlette==1.3.1  + pydantic==2.13.4  + anyio==4.14.1  + click==8.4.2 ほか
```

### 4. README.md への記録

「Web UI (M1 最小版, 任意)」サブセクションを追加し、`uv sync --extra gsas --extra web` の導入手順と gsas 併用の注意を記載。

## 作業結果

- [x] pyproject.toml に `web` extra + dev group `httpx` 追加完了
- [x] `search/`, `export/`, `webui/` パッケージ骨格作成完了
- [x] `uv sync --extra gsas --extra web` 成功
- [x] 新規パッケージの import 確認 (`tsumugin.search/export/webui`) OK
- [x] gsas extra 維持確認 (scipy 1.18.0 import OK)
- [x] README.md 更新完了

## 遭遇した問題と解決方法

なし。uv sync は警告・エラーなく完了。

## 次のステップ

- `/tsumiki:direct-verify` を実行して import 確認 + 全テスト (既存 70 tests) の green を確認
- git commit は親エージェントが実施 (本タスクでは未実施)
