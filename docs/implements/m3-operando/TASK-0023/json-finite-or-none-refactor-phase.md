# TASK-0023 Refactor フェーズ: `_json.finite_or_none` 統合 (Issue #5)

**機能名**: json-finite-or-none / **タスクID**: TASK-0023 / **要件名**: m3-operando
**タイプ**: TDD (挙動不変リファクタ) / **実施日時**: 2026-07-03
**信頼性**: 🔵 (REQ-022 / D-Q9 / interfaces.py L24-32 / TC-208-03)

> すべてのパスはプロジェクトルートからの相対パス。

---

## 0. 結論サマリー

**判定: コード変更不要 (YAGNI)**。Green フェーズ完了時点で成果物は既に高品質であり、
リファクタリング観点 8 項目のいずれも「改善余地なし」または「変更するとかえって品質を損なう」と評価。
挙動不変リファクタの絶対条件 (既存テスト無改変 green) を維持するため、**意味のない差分は入れない**方針を採用した。

- テスト: 関連 90 件 (test_json_util 12 + test_serialization 15 + test_webui + test_tree_search) 全 green 🔵
- Lint: `uvx ruff check` 対象 5 ファイル **All checks passed!** 🔵
- レイヤ制約: `_json.py` は `math` のみ import の無依存な葉 (test_json_module_is_dependency_free_leaf で機械的に固定) 🔵
- 単一情報源: tree / webui / serialization の 3 実装が `_json.finite_or_none` へ委譲済み (`is` 同一性テストで担保) 🔵

---

## 1. リファクタ前テスト実行 (安全性確認)

- **コマンド**: `uv run pytest tests/test_json_util.py tests/test_serialization.py tests/test_webui.py tests/test_tree_search.py -q`
- **結果**: 90 passed / 0 failed / 0 error (dots 72+18、非有限系・センチネル系・委譲同一性を含む)。
- **実行時間**: 2 秒未満の警告なし (純関数 + 軽量 API テストのみ、遅いテストなし)。
- **除外チェック**: `describe.skip` / `it.skip` / `test.skip` / xfail は新規テストに**なし**。
  `pyproject.toml` は `testpaths=["tests"]` / `addopts="-q"` のみで、テスト除外パターンなし。
- **開発時生成ファイル**: `debug-*` / `temp-*` / `*.tmp` / `*.bak` / `*.orig` / `*~` / `.DS_Store` は**検出ゼロ** (クリーンアップ不要)。

## 2. 最終コード (変更なし・現状を記録)

### 2.1 `src/tsumugin/_json.py` (単一情報源・50 行・葉モジュール)

```python
from __future__ import annotations

import math

__all__ = ["finite_or_none"]


def finite_or_none(value: float | None) -> float | None:
    # None は float 変換前に早期 return し TypeError を防ぐ (serialization の None 経路を保存)
    if value is None:
        return None
    # 非有限 (inf/-inf/NaN) を None へ、有限は float へ正規化 (0.0 等 falsy 有限値も潰さない)
    v = float(value)
    return v if math.isfinite(v) else None
```

- 【評価】: 分岐は `None` 早期 return と `isfinite` 判定の 2 段のみで最小。可読性・時間計算量 O(1) ともに最適。
  日本語 docstring に機能概要 / 実装方針 / テスト対応 / 信頼性レベルを網羅済みで**追記の必要なし**。
- 【docstring テスト参照の注記】: モジュール docstring 内のテストファイル名は `tests/test_json_util.py` を指す
  (要件・testcases 文書上の想定名 `tests/test_json.py` ではなく実ファイル名で正しい)。整合済み。

### 2.2 `src/tsumugin/search/tree.py` (委譲 + センチネル残置)

```python
from .._json import finite_or_none          # L42: 非有限判定を単一情報源へ委譲

_EVIDENCE_SENTINEL = 1e18                    # L179: 探索固有センチネル (tree に残す)

def _finite_or_none(value: float) -> float | None:   # L182: tree ラッパ
    v = finite_or_none(value)                          # 非有限判定は委譲
    if v is None or v >= _EVIDENCE_SENTINEL:           # センチネル閾値のみ tree 側
        return None
    return v
```

- 【評価】: D-Q9 の確定方針 (非有限は委譲・センチネルは tree 残置) に厳密一致。
  `_FiniteGuardedEvidence._SENTINEL = _EVIDENCE_SENTINEL` (L214) との定数共有も維持され、
  softmax NaN ガードとの値契約が保たれる。ラッパ名 `_finite_or_none` は既存呼び出し (L151/152/156) との
  互換のため保持が正しく、**改名はしない** (無意味な差分回避)。

### 2.3 `src/tsumugin/webui/app.py` (私的横断 import の解消)

```python
from .._json import finite_or_none   # L26: 旧 `from ..search.tree import _finite_or_none` を置換
```

- 【評価】: webui → search の**レイヤ逆依存を解消**。detail API は evidence を素の `finite_or_none` で純化し、
  センチネル純化は to_summary (tree) 経由で受ける契約 (L87-88 コメント) が明示済み。改善余地なし。

### 2.4 `src/tsumugin/store/serialization.py` (ローカル定義の廃止)

```python
from tsumugin._json import finite_or_none   # L17: ローカル _finite_or_none を廃止し委譲
# _finite_map / phase_to_dict が finite_or_none を直接使用 (None 入力経路も保存)
```

- 【評価】: store 最下層から search への暗黙の挙動共有を解消し、葉モジュールへの一方向下向き依存へ是正。
  `None` 入力許容契約 (wt_frac=None 等) も統合先 `finite_or_none` が受理するため挙動不変。

## 3. セキュリティレビュー

- 【入力検証】: 純関数。入力は数値 / None のみを想定し、`None` 早期 return で `float(None)` の TypeError を回避。
  非数値型は責務外 (既存呼び出し元はすべて数値/None を渡す) で妥当。🔵
- 【インジェクション類】: SQL / XSS / CSRF いずれも無関係 (I/O・文字列連結・外部入力・DB アクセスなし)。
- 【データ漏洩】: 副作用なし・ログ出力なし・グローバル状態なし。機微情報を扱わない。
- 【結論】: **重大な脆弱性なし** 🔵。むしろ非有限値を JSON 配信前に `None` へ縮退させることで
  `json.dumps(allow_nan=False)` の ValueError (M1 教訓 EDGE-004) を防ぐ安全側の設計。

## 4. パフォーマンスレビュー

- 【計算量】: 時間 O(1) / 空間 O(1)。分岐 2 段 + `float()` + `math.isfinite()` のみ。
- 【ホットパス性】: JSON 配信・直列化時の値純化であり探索ホットループ外。性能要件なし (note.md §パフォーマンス)。
- 【最適化余地】: `serialization._finite_map` は dict 内包で O(n) だが本タスク対象の純化関数自体は O(1)。
  過剰最適化 (キャッシュ等) は純関数の決定論性・可読性を損なうため**不採用** (YAGNI)。
- 【結論】: **重大な性能課題なし** 🔵。

## 5. 改善計画と適用結果 (リファクタ観点 8 項目)

| # | 観点 | 評価 | 適用 |
|---|---|---|---|
| 1 | 可読性 | docstring/コメントが機能概要・方針・テスト対応・信頼性まで網羅済み | 変更不要 🔵 |
| 2 | 重複除去 (DRY) | 3 実装 → 1 実装へ統合済み (本タスクの本質・達成済み) | 変更不要 🔵 |
| 3 | 設計改善 | 葉モジュール化で逆依存解消・単一責任 (純化のみ)・センチネルは tree に局所化 | 変更不要 🔵 |
| 4 | ファイルサイズ | `_json.py` 50 行 (500 行制限に対し余裕十分)、分割不要 | 変更不要 🔵 |
| 5 | コード品質 | `uvx ruff check` clean (line-length 100 / py312)、型注釈完備 | 変更不要 🔵 |
| 6 | セキュリティ | 脆弱性なし (§3) | 変更不要 🔵 |
| 7 | パフォーマンス | O(1) 純関数・ホットパス外 (§4) | 変更不要 🔵 |
| 8 | エラーハンドリング | `None` 早期 return で TypeError 回避、非有限は例外を投げず None 縮退 | 変更不要 🔵 |

**適用したリファクタリング**: なし (全観点で高品質を確認)。挙動不変の絶対条件下では、
意味のない差分を入れずに現状を最終形とすることが最善と判断。

## 6. 品質判定

```
✅ 高品質:
- テスト結果: 関連 90 件 全 green (無改変)、遅いテストなし、skip/xfail での無効化なし
- セキュリティ: 重大な脆弱性なし (純関数・副作用なし・非有限を安全に縮退)
- パフォーマンス: 重大な性能課題なし (O(1)・ホットパス外)
- リファクタ品質: 目標 (3 実装の単一情報源化 + レイヤ逆依存解消) 達成済み
- コード品質: ruff clean・型注釈完備・50 行の葉モジュール・日本語コメント充実
- ドキュメント: 本フェーズ文書 + memo 更新で完成
```

## 7. 次のステップ

`/tsumiki:tdd-verify-complete m3-operando TASK-0023` で完全性検証 (16 定義網羅・全体回帰・完了条件確認) を実行する。
