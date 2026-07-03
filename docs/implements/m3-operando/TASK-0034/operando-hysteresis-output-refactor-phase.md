# TDD Refactor フェーズ記録: operando-hysteresis-output (TASK-0034)

## 実施日時

2026-07-04

## 対象ファイル

- `src/tsumugin/operando/hysteresis.py` (195 行 → 195 行)
- `src/tsumugin/operando/output.py` (191 行 → 183 行)
- テスト: `tests/test_hysteresis_output.py` (15 件) — 変更なし

## リファクタリング方針

Green 直後の実装は既に helper 分割 (`_branch_xy`/`_interp_in_domain`/`_pair_midpoint_sigma`/
`_echem_columns`) と日本語 docstring が充実しており、関数分割・命名・可読性の追加改善は不要と判断。
唯一の実質的改善として **非有限縮退の一貫性 (DRY / 単一情報源化)** を実施した。

## 改善内容

### 1. output.py の私的 `_finite_or_none` 重複を共有 `_json.finite_or_none` へ統合 🔵

**動機**: TASK-0023 (Issue #5) で 3 箇所に散在していた `_finite_or_none` 相当を
`_json.finite_or_none` に単一情報源化済み (`store/serialization.py` / `webui/app.py` /
`search/tree.py` は既に委譲)。output.py の `_finite_or_none` はその真理値表と完全同一
(`None`→`None` / 非有限→`None` / 有限→`float`) の未統合な重複であり、統合対象。

**変更**:
- `_finite_or_none` 関数 (12 行) を削除。
- `from tsumugin._json import finite_or_none` を追記 (下向き葉モジュール import、循環なし)。
- 未使用となった `import math` を削除。
- `_pair_midpoint_sigma` の 4 箇所の呼び出しを `finite_or_none` へ置換。

**振る舞い同一性**: 両実装とも `float | None → float | None`。`_json` 版は `float(value)` 後に
`math.isfinite` 判定、旧版は raw で `math.isfinite` 判定後に `float()` 変換だが、入力は
`tuple[float | None, ...]` の要素 (float/None) のみのためビット同一。

### 2. hysteresis.py `_interp_in_domain` の非有限縮退を共有ユーティリティへ整合 🔵

**変更**: `return value if math.isfinite(value) else None` を `return finite_or_none(value)` へ。
`np.interp` 出力 (Python float) の「万一の非有限→None」縮退を `_json` の共通契約に集約。
`import math` は `split_branches`/`_branch_xy` の隣接ペア有限ガードで引き続き使用のため残置。

**スコープ外 (意図的に非変更)**:
- `split_branches`/`_branch_xy` の `math.isfinite(a) and math.isfinite(b)` は「2 値ペアの
  フィルタガード」であり単一値の None 縮退ではないため、`finite_or_none` 化せず明示ガードのまま維持。
- `sequential/trajectory.py` `_num_cell` (CSV セル用・str 返却) は本タスク対象外かつ返り値型が
  異なるため非変更。

## セキュリティレビュー

- 外部入力の実行/評価・SQL・パス操作なし。`combined_csv` の `open(path, ...)` は呼び出し側指定
  パスへの書き出しのみで、注入経路なし。CSV は stdlib `csv.writer` による自動クオートで
  インジェクション面も限定的。重大な脆弱性なし。

## パフォーマンスレビュー

- `branch_differences`: O(F + G·B) (F=フレーム数, G=n_grid, B=枝点数)。numpy ベクトル演算で決定論。
- `combined_csv`: frame_index 和集合を `set`→`sorted` で O(N log N)、1 パス書き出し。
- 関数呼び出しが 1 段増える (`finite_or_none`) が、いずれも純データ・小規模で影響は無視可能。
  実測: 対象 15 件の全 duration < 0.005s。重大な性能課題なし。

## 決定論・非破壊の再確認

- 非破壊: frozen dataclass のみ生成、入力列の in-place 変更なし。Ledger/Snapshot 非接触。
- 決定論: `split_branches` は走査順 append (set 反復非依存)、`combined_csv` は `sorted(frames)` と
  相 ref sorted・列順固定、`np.interp`/`np.linspace` の決定論演算のみ。N6/N7 で担保継続。

## テスト実行結果

- `uv run pytest tests/test_hysteresis_output.py -q` → **15 passed** (リファクタ前後で不変)。
- `uvx ruff@latest check src/tsumugin/operando/hysteresis.py src/tsumugin/operando/output.py`
  → **All checks passed!** (line-length 100)。

## 品質判定

✅ 高品質: テスト全継続成功 / 重大な脆弱性・性能課題なし / DRY・単一情報源化の目標達成 /
ファイル 500 行未満 / 日本語コメント整合更新済み / ドキュメント完成。
