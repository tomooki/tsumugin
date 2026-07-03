# TASK-0010 公開 API 統合 + E2E — Red フェーズ記録

- **機能名**: 公開 API 統合 + E2E テスト (public-api-integration)
- **タスクID**: TASK-0010 / **要件名**: m1-hypothesis-search
- **作成日時**: 2026-07-03
- **テストファイル**: `tests/test_m1_e2e.py` (新規, 13 テスト)
- **テストケース定義**: `docs/implements/m1-hypothesis-search/TASK-0010/public-api-integration-testcases.md`

## 1. 作成したテストケース一覧 (13 件 / 定義書と 1:1)

| # | ID | テスト関数 | マーカー | 信頼性 |
|---|-----|-----------|----------|--------|
| 1 | TC-010-01 | `test_m1_public_symbols_are_reexported` | なし | 🔵 |
| 2 | TC-010-02 | `test_m1_symbols_in_dunder_all_and_sorted` | なし | 🔵 |
| 3 | TC-010-03 | `test_e2e_simulated_two_phase_ranks_ab_first` | なし | 🔵 |
| 4 | TC-010-04 | `test_e2e_summary_is_json_serializable_with_schema` | なし | 🔵 |
| 5 | TC-010-05 | `test_e2e_ledger_verify_true` | なし | 🔵 |
| 6 | TC-010-06 | `test_e2e_gsasii_search_completes` | @gsas | 🔵 |
| 7 | TC-010-07 | `test_e2e_gsasii_search_then_export_gpx_reopenable` | @gsas | 🔵 |
| 8 | TC-010-08 | `test_import_tsumugin_does_not_require_optional_extras` | なし | 🔵 |
| 9 | TC-010-09 | `test_e2e_empty_candidates_degrades_gracefully` | なし | 🔵 |
| 10 | TC-010-10 | `test_e2e_unknown_phase_flag_and_unmatched_report` | なし | 🔵 |
| 11 | TC-010-11 | `test_e2e_deterministic_summary_bitwise_identical` | なし | 🔵 |
| 12 | TC-010-12 | `test_e2e_single_candidate_single_hypothesis` | なし | 🔵 |
| 13 | TC-010-13 | `test_readme_m1_example_executes` | なし | 🟡 |

信頼性分布: 🔵 12 / 🟡 1 / 🔴 0。

## 2. テストコード

全文は `tests/test_m1_e2e.py` を参照 (単一情報源)。Red の失敗機構となる中核はモジュール冒頭の
公開 import であり、以下の 6 シンボルのトップレベル昇格が Green の実装対象:

```python
# 【Red の失敗点】: M1 シンボルはトップレベル未 re-export のため、この import が
#   collection 時に ImportError となり本ファイルの全テストが失敗する想定。🔵
from tsumugin import (
    HypothesisTreeSearch,
    LatticeParams,
    PhaseCandidate,
    PhaseInstance,
    SearchConfig,
    SearchResult,
    SimulatedBackend,
    UnmatchedPeakReport,
    export_gpx,
)
```

設計上の要点:
- 合成データは `tests/test_tree_search.py` と同一慣習 (`GRID = np.arange(15.0, 60.0, 0.02)`、
  立方相 A(a=5.0)/B(6.0)/C(4.5)/D(7.0))。step 0.02 は clustering 較正上変更禁止。
- SimulatedBackend 正常系 3 件 (TC-03/04/05) は module スコープ fixture `ab_result` で
  探索 1 回を読み取り専用共有 (実行時間抑制)。@gsas 2 件も同様に `gsasii_ab_search` で共有。
- TC-010-08 (D6 遅延 import 契約) は `sys.meta_path` フック `_BlockOptionalImports` で
  fastapi/uvicorn/GSASII の import を人為遮断し「未導入環境」を決定論的に再現、
  `import tsumugin` / M1 シンボル解決 / `import tsumugin.webui` の成功を検証
  (finally で sys.modules を完全復元)。
- 決定論 (TC-010-11) は独立 2 回実行の `json.dumps(to_summary(), sort_keys=True)` を
  `==` でビット同一比較 (pytest.approx 不使用)。
- TC-010-13 は README「使い方 (M1)」節に記載予定の最小使用例 (公開 API のみ) を写経実行。

## 3. テスト実行コマンドと期待される失敗

```bash
uv run pytest tests/test_m1_e2e.py
```

実行結果 (2026-07-03 確認済み):

```text
ERROR tests/test_m1_e2e.py
ImportError while importing test module 'tests/test_m1_e2e.py'.
E   ImportError: cannot import name 'HypothesisTreeSearch' from 'tsumugin'
    (src/tsumugin/__init__.py)
!!!! Interrupted: 1 error during collection !!!!
```

- collection 時 ImportError により **全 13 テストが失敗** (Red 成立)。
- `uvx ruff check tests/test_m1_e2e.py` → All checks passed!
- 既存スイート無退行: `uv run pytest --ignore=tests/test_m1_e2e.py` → exit 0
  (205 passed / 3 skipped、失敗なし)。

## 4. Green フェーズで実装すべき内容

1. `src/tsumugin/__init__.py` に M1 公開シンボルを re-export:
   - `HypothesisTreeSearch` / `SearchConfig` / `SearchResult` / `PhaseCandidate` /
     `UnmatchedPeakReport` (← `tsumugin.search`)、`export_gpx` (← `tsumugin.export`)
   - `__all__` へ追記しアルファベット昇順ソートを維持。M0 分の削除・改名は禁止 (後方互換)。
2. re-export 追加後も D6 遅延 import 契約を破らないこと (TC-010-08):
   - `import tsumugin` が fastapi / uvicorn / GSASII 非依存のまま成功すること
     (`tsumugin.export.gpx` → `backends.gsasii` は GSAS-II を遅延 import 済みのため
     現行構造のままで満たせる見込み)。
3. E2E 本体 (search / to_summary / ledger / export_gpx) は TASK-0002〜0009 で実装済みのため、
   re-export のみで TC-010-01〜13 が green になる想定。@gsas 2 件は GSAS-II 実行時間に注意。
4. README「使い方 (M1)」節 (10-15 行) を TC-010-13 の写経コードと同等内容で追加 (完了条件⑤)。
