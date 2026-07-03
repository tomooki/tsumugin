# TASK-0008 export_gpx — Refactor フェーズ記録

- **日時**: 2026-07-03 / **要件名**: m1-hypothesis-search / **機能名**: export-gpx

## リファクタリング方針

機能・公開 API・テストの意味は不変。Green フェーズで混入したレビュー向けコメント整理、
docstring の責務明確化、型注釈の精緻化に限定 (YAGNI 厳守)。

## 改善内容

### 1. `_build_project` の責務明確化 (`src/tsumugin/backends/gsasii.py`) 🔵
- docstring を「【責務】」記述へ刷新。担当範囲 (instprm/xye 書き出し → G2Project 生成 →
  観測ヒストグラム追加 → 全相追加) と、呼び出し側 (refine / export_gpx) が担う用途固有処理
  (精密化フラグ設定・do_refinements・保存・読み戻し) の境界を明示。
- 抽出リファクタの経緯コメント (`【実装方針】: refine() にあった…挙動不変のまま移動した抽出リファクタ`)
  と `【テスト対応】: …TC-006-13 / 既存 contract test 非退行` を削除 (レビュー向け・履歴情報)。
- 全パラメータ (phases/two_theta/intensity/weights) の docstring を補完。

### 2. Green フェーズ・レビュー向けコメントの整理 🔵
- `refine()` の gpx 構築ブロック: `【挙動不変】: 抽出前と同一の手順…` を削除し、生成物 (一時 refine.gpx)
  と後続処理の所在を述べる説明へ置換。
- `_build_project` 本体: `(抽出前と同一手順)` の注記を削除。
- `export/gpx.py` `export_gpx` docstring: `【テスト対応】: …TC-006-01〜11 を通すための実装` を削除。
- `export_gpx` 入力正規化コメント: `(挙動一貫性)` を削除 (`refine と同様に` が意図を保持)。

### 3. 型注釈の精緻化 🔵
- `_build_project` 戻り値: `tuple[object, object, list]` → `tuple[object, object, list[object]]`。
- 型エイリアス導入は 2 呼び出しのみの内部ヘルパにつき過剰と判断し YAGNI で見送り (GSAS-II 型スタブ
  不在のため要素型は `object` が正直な上限)。

## セキュリティレビュー
- 外部入力・信頼境界なし。書き出しは `tempfile.TemporaryDirectory` (補助ファイル) とユーザ指定 path
  (gpx 本体) のみ。今回の変更はコメント/docstring/型注釈に限られ、新規脆弱性なし。

## パフォーマンスレビュー
- 実行パス・計算量は完全に不変 (非機能変更のみ)。ボトルネックなし。

## テスト実行結果
- `uv run pytest`: **188 passed, 3 skipped** (skip は GSAS-II 未導入経路 TC-006-03/08 と既存
  unavailable 1 件のみ。@gsas マーカーのケースは導入済み本環境で実行済み)。
- `uvx ruff@latest check src tests`: **All checks passed!**

## 品質判定: ✅ 高品質
- テスト: 全継続成功 / セキュリティ: 重大な脆弱性なし / パフォーマンス: 重大な課題なし
- リファクタ品質: 目標 (責務明確化・コメント整理・型注釈) 達成 / コード品質: 適切
- ファイルサイズ: gsasii.py 約 320 行 / gpx.py 約 75 行 (500 行制限内)
