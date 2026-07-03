# TASK-0008 export_gpx — Green フェーズ記録

- **日時**: 2026-07-03 / **要件名**: m1-hypothesis-search / **機能名**: export-gpx

## 実装内容

### 1. `src/tsumugin/backends/gsasii.py` — `_build_project()` 抽出 (挙動不変リファクタ) 🔵
- `refine()` の gpx 構築ブロック (instprm/xye 書き出し → `G2Project(newgpx=...)` →
  `add_powder_histogram` → `_add_phases`) を `_build_project(gpx_path, work_dir, phases,
  two_theta, intensity, weights) -> (gpx, hist, g2phases)` へ移動。
- `refine` は `gpx_path = tmp_path / "refine.gpx"` (一時) を渡し、以降の refinement フラグ
  設定・`do_refinements`・読み戻しは従来どおり `_build_project` の外 (要件定義 §2.3)。
- 抽出前後で `tests/test_gsasii_backend.py` を実行し非退行を確認 (完了条件④)。

### 2. `src/tsumugin/export/gpx.py` — `export_gpx()` 新規実装 🔵
- シグネチャ: `export_gpx(path, phases, two_theta, intensity, *, weights=None,
  wavelength=_DEFAULT_WAVELENGTH) -> str` (interfaces.py 契約準拠、kw-only 引数)。
- 未導入判定: `GSASIIBackend(wavelength=wavelength)` 生成を介し `__init__` の既存
  `GSASUnavailableError` raise を利用 (書き出し前・副作用ゼロ、REQ-105 / 要件定義 §3.3 推奨経路)。
- 一時/永続分離: instprm/xye/cif は `TemporaryDirectory`、gpx 本体は永続 `path` (§3.4)。
- Ycalc 埋め込み: `max cyc = 0` → `do_refinements([{}])` → `gpx.save()` を with 内で完了 (§3.5)。

### 3. `src/tsumugin/export/__init__.py` — re-export 🔵
- `from .gpx import export_gpx` + `__all__ = ["export_gpx"]` (TC-006-07)。

## テスト実行結果
- `uv run pytest tests/test_gpx_export.py`: **11 passed, 2 skipped** (skip は未導入経路
  TC-006-03/08 — 導入済み環境のため設計どおり skip)。
- `uv run pytest` (全体): **全 green** (fail 0、skip 3 = 上記 2 + 既存 unavailable 1)。
  既存 contract test 群 (`test_gsasii_backend.py`) 非退行 (TC-006-12)。
- `uvx ruff@latest check src tests`: **All checks passed!**

## 品質判定: ✅ 高品質
- テスト: 全成功 / 実装: シンプル (薄い書き出し層 + 単一情報源ヘルパ) / 機能的問題: なし
- ファイルサイズ: gsasii.py 約 320 行・gpx.py 約 80 行 (800 行制限内) / モック: 実装コードに無し

## 課題・改善点 (Refactor 候補)
- `export_gpx` 内の `backend._build_project(...)` は private メソッドのモジュール間アクセス。
  Refactor フェーズで公開度の整理 (もしくは現状維持の明示) を検討。
- `_build_project` の戻り値型注釈 `tuple[object, object, list]` は GSAS-II 型スタブ不在による
  暫定。より説明的な型エイリアス導入を検討可。
