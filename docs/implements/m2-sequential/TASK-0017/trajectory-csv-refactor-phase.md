# TDD Refactor フェーズ記録: trajectory-csv (TASK-0017)

## 実施日時

2026-07-03

## 対象

- 実装ファイル: `src/tsumugin/sequential/trajectory.py`
- テスト: `tests/test_trajectory.py` (17 件)

## リファクタ前の状態確認

- Green フェーズの実装は既に高品質 (frozen dataclass 2 種 + `to_csv` + ヘルパ 3 関数、日本語コメント充実)。
- リファクタ前テスト: `uv run pytest tests/test_trajectory.py` → 17 passed (0.77s、2 秒超の遅いテストなし)。
- `uvx ruff check` → All checks passed。ファイルサイズ 189 行 (500 行制限内)。
- `describe.skip`/`test.skip` 等の無効化なし。`.gitignore` によるコード/テスト除外なし。
- 開発時一時ファイル (`debug-*`/`temp-*`/`*.bak` 等) の混入なし。

## セキュリティレビュー結果

- 🔵 **入力/インジェクション**: 出力は stdlib `csv.writer` のみ (エスケープは csv モジュール責務)。`eval`/`exec`/シェル起動なし。
- 🔵 **パス**: `path` は内部利用者 (TASK-0019) 供給の出力先。ライブラリ出力関数として妥当、追加の検証責務なし。
- 🔵 **データ漏洩**: 非有限 (inf/-inf/NaN) は `_num_cell` で空欄化しファイルに漏らさない (完了条件③、T-E01/T-E02 で担保)。
- 重大な脆弱性なし。

## パフォーマンスレビュー結果

- 🔵 **計算量**: O(フレーム数 × 相数)。CSV 形状 (行×列) に対して最適で不要走査なし。
- 🔵 **メモリ**: 行を逐次 `writerow` で書き出し、全行のバッファリングなし。`phase_by_ref` は 1 行分のみ。
- 重大な性能課題なし。

## リファクタリング内容 (機能変更なし・出力バイト不変)

### 改善: 相ごと列接尾辞の「フレーム由来 / lifecycle 由来」分離 (DRY・保守性)

- **Before**: `_PHASE_FIELD_SUFFIXES` は 8 要素の単一リスト。相なし行の空欄プレースホルダは
  `["", "", "", "", ""]` (5) と `["", "", ""]` (3) のマジックな個数で、8=5+3 の分割はコメントにのみ存在。
  列定義を変更すると空欄個数と静かに desync する潜在リスクがあった。
- **After**: `_PHASE_FRAME_SUFFIXES` (a/b/c/scale/wt_frac) と `_PHASE_LIFECYCLE_SUFFIXES`
  (birth_frame/death_frame/confidence) に分割し、`_PHASE_FIELD_SUFFIXES` は両者の連結で合成。
  空欄は `[""] * len(_PHASE_FRAME_SUFFIXES)` / `[""] * len(_PHASE_LIFECYCLE_SUFFIXES)` で導出。
- **効果**: マジック個数を排除し「列定義の単一情報源」を確立。フレーム由来/相メタ由来の区分が構造として明示化。
  出力バイト列は完全不変 (5 空欄+3 空欄・ヘッダ順とも同一) のため T-B05 (バイト同一) を含む全テスト継続 green。
- 🔵 信頼性レベル: 要件 §2.3 の列レイアウト定義に依拠。分割は既存コメントの構造化のみで新規推測なし。

## リファクタ後テスト実行結果

- `uv run pytest tests/test_trajectory.py` → **17 passed** (0.77s)。
- `uvx ruff check src/tsumugin/sequential/trajectory.py` → **All checks passed**。

## 品質判定

✅ 高品質
- テスト: 全 17 件継続成功 (回帰なし)
- セキュリティ: 重大な脆弱性なし
- パフォーマンス: 重大な性能課題なし
- リファクタ品質: DRY/保守性の目標達成 (マジック個数排除・単一情報源化)
- コード品質: ruff クリーン / 197 行 (500 行制限内)
- ドキュメント: 本ファイルおよびメモを更新済み

## 補足 (変更を見送った判断 — YAGNI)

- `from typing import Mapping` はコードベース全体 (model/phase.py, changepoint.py, lifecycle.py 等) の
  慣習に一致。この 1 ファイルのみ `collections.abc.Mapping` へ変更すると一貫性を損なうため据え置き。
- `_num_cell` (非有限純化) は `store/serialization.py._finite_or_none` と同思想だが、レイヤ横断 import を
  避けるため意図的に局所化している (M1 教訓・memo 参照)。`search/tree.py` でも同様に複製されており、
  この「重複」はレイヤ独立性を優先した設計判断のため統合しない。
