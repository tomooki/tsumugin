# TASK-0001 設定確認・動作テスト

## 確認概要

- **タスクID**: TASK-0001 (web extra 追加とパッケージ骨格)
- **確認内容**: pyproject の web extra / dev httpx、新規パッケージ骨格の import、既存全テスト green、ruff clean
- **実行日時**: 2026-07-03
- **実行者**: direct-verify (Claude)

## 設定確認結果

### 1. pyproject.toml の依存定義

**確認ファイル**: `pyproject.toml`

- [x] `[project.optional-dependencies].web = ["fastapi>=0.110", "uvicorn>=0.29"]` 存在 (L20-23)
- [x] `[dependency-groups].dev` に `httpx>=0.27` 存在 (L29)
- [x] `[tool.ruff] line-length = 100` 存在 (L46-48)

### 2. パッケージ骨格の確認

- [x] `src/tsumugin/search/__init__.py` 存在 (`"""多仮説木探索 (FR-110〜117)。"""`)
- [x] `src/tsumugin/export/__init__.py` 存在 (`""".gpx 書き出し (FR-505)。"""`)
- [x] `src/tsumugin/webui/__init__.py` 存在 (`"""Web UI 最小版 (read-only, FR-421〜424 縮小版)。"""`)
- [x] いずれも `from __future__ import annotations` + `__all__: list[str] = []`

### 3. 依存関係インストール状況

```bash
uv pip show fastapi uvicorn httpx
```

- [x] fastapi==0.139.0 (>=0.110)
- [x] uvicorn==0.49.0 (>=0.29)
- [x] httpx==0.28.1 (>=0.27)

## コンパイル・構文チェック結果

### 1. 新規パッケージ import

```bash
uv run python -c "import tsumugin.search, tsumugin.export, tsumugin.webui"
```

**結果**: `IMPORT_OK` — 構文/import エラーなし

### 2. web extra 依存 import

```bash
uv run python -c "import fastapi, httpx"
```

**結果**: `DEPS_OK 0.139.0 0.28.1`

### 3. Lint (ruff)

```bash
uvx ruff@latest check src tests
```

**結果**: `All checks passed!` (line-length 100 設定は pyproject 準拠)

## 動作テスト結果

### 全テスト実行

```bash
uv run pytest
```

**結果**: `70 passed, 1 skipped in 5.49s` — 完了条件の想定 (70 passed / 1 skipped) と一致。

> 注: 起動時の GSAS-II `config.ini` cp932 読込警告 (`'utf-8' codec can't decode byte 0x83`) は
> CLAUDE.md 記載の既知・無害な警告でありテスト結果に影響なし。

## 品質チェック結果

- [x] 既存テスト回帰なし (70 passed / 1 skipped)
- [x] Lint クリーン
- [x] 新規パッケージは空骨格 (docstring + `__all__` のみ) で副作用なし
- [x] gsas extra 維持 (setup-report にて scipy import 確認済み)

## 全体的な確認結果

- [x] 設定作業が正しく完了している
- [x] 全ての動作テストが成功している
- [x] 品質基準を満たしている
- [x] 次のタスク (TASK-0002〜) に進む準備が整っている

## 発見された問題と解決

なし。修正を要する問題は検出されなかった。

## CLAUDE.md への記録内容

追記不要。ルート `CLAUDE.md`「技術スタック / コマンド」表に必要な実行方法
(`uv sync --extra gsas`, `uv run pytest`, `uvx ruff check src tests`) が既に記載済み。

## 次のステップ

- git commit は親エージェント / ユーザー判断で実施 (本タスクでは未実施)
- TASK-0002 (観測ピーク検出 find_peaks) の実装へ
