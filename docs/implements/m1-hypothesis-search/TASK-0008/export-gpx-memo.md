# TASK-0008 export_gpx — TDD 開発メモ

## 概要
- 機能名: .gpx 書き出し export_gpx + GSASIIBackend._build_project() 抽出
- 開発開始: 2026-07-03
- 現在のフェーズ: 完了 (Refactor まで完了)

## 関連ファイル
- 要件定義: `docs/implements/m1-hypothesis-search/TASK-0008/export-gpx-requirements.md`
- テストケース定義: `docs/implements/m1-hypothesis-search/TASK-0008/export-gpx-testcases.md`
- 実装ファイル: `src/tsumugin/export/gpx.py` / `src/tsumugin/backends/gsasii.py` /
  `src/tsumugin/export/__init__.py`
- テストファイル: `tests/test_gpx_export.py`

## Redフェーズ（失敗するテスト作成）
- 作成日時: 2026-07-03 (tests/test_gpx_export.py 13 関数、`from tsumugin.export.gpx import
  export_gpx` の ImportError で失敗する状態から開始)

## Greenフェーズ（最小実装）
- 実装日時: 2026-07-03
- 実装方針:
  1. `refine()` の gpx 構築ブロックを `_build_project()` へ挙動不変で抽出 (D-Q8 単一情報源)。
  2. `export_gpx` は `GSASIIBackend()` 生成 (未導入時に既存 raise) → `_build_project` を
     永続パスで実行 → `max cyc=0` の `do_refinements([{}])` で Ycalc 埋め込み → `gpx.save()`。
  3. `export/__init__.py` に re-export 追加。
- テスト結果: `tests/test_gpx_export.py` 11 passed / 2 skipped (未導入経路)。全体 pytest 無退行
  (fail 0)。ruff All checks passed。
- 課題・改善点: private `_build_project` のモジュール間アクセスの整理、戻り値型注釈の精緻化
  (詳細は `export-gpx-green-phase.md`)。

## Refactorフェーズ（品質改善）
- 実施日時: 2026-07-03
- 改善内容 (機能・公開 API・テスト意味は不変):
  1. `_build_project` docstring を「責務」記述に刷新。抽出リファクタの経緯 (挙動不変のまま移動)
     と TC 参照を削除し、担当範囲 (補助ファイル書き出し〜相追加) と呼び出し側責務 (精密化/保存/
     読み戻し) を明示。全 param の docstring を補完。
  2. Green フェーズのレビュー向けコメントを整理: `refine` の「挙動不変」注記、`_build_project` 本体の
     「(抽出前と同一手順)」、`export_gpx` docstring の「テスト対応: …を通すための実装」、入力正規化の
     「(挙動一貫性)」を削除/簡潔化。
  3. 型注釈精緻化: `_build_project` 戻り値 `tuple[object, object, list]` → `tuple[object, object,
     list[object]]` (型エイリアス導入は 2 呼び出しの内部ヘルパにつき YAGNI で見送り)。
- セキュリティレビュー: 入力検証・外部入力なし。書き出しは tempfile + ユーザ指定 path のみ。新規リスクなし。
- パフォーマンスレビュー: 計算量不変 (コメント/docstring/型注釈のみの変更)。
- テスト結果: `uv run pytest` 188 passed / 3 skipped (未導入経路のみ skip、@gsas 実行済み)。
  `uvx ruff@latest check src tests` All checks passed。
- 品質評価: ✅ 高品質 (テスト全継続成功・脆弱性なし・性能課題なし・目標達成)。
