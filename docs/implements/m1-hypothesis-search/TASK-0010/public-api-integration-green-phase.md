# TASK-0010 公開 API 統合 + E2E — Green フェーズ記録

- **機能名**: 公開 API 統合 + E2E テスト (public-api-integration)
- **タスクID**: TASK-0010 / **要件名**: m1-hypothesis-search
- **作成日時**: 2026-07-03
- **テストファイル**: `tests/test_m1_e2e.py` (13 テスト)

## 1. 実装内容

### 1.1 `src/tsumugin/__init__.py` — M1 公開シンボル re-export 🔵

M1 中核シンボルをトップレベルへ昇格 (サブパッケージ側は re-export 済み):

- `tsumugin.search` から: `HypothesisTreeSearch` / `SearchConfig` / `SearchResult` /
  `PhaseCandidate` / `Peak` / `UnmatchedPeakReport`
- `tsumugin.export` から: `export_gpx`

`__all__` に上記 7 シンボルを追記しアルファベット昇順ソートを維持。M0 分 (19 シンボル) は
削除・改名なし (後方互換 / 要件 §3.2)。合計 26 シンボルを公開。

D6 遅延 import 契約は現行構造のまま維持: `from .export import export_gpx` →
`backends.gsasii` は GSASII を関数内で遅延 import するのみ (`gsasii_available` の `find_spec`、
`_g2sc` の import)。よって `import tsumugin` は fastapi/uvicorn/GSASII 非依存で成功 (TC-010-08 green)。

### 1.2 `src/tsumugin/model/phase.py` — `PhaseInstance.scale` に既定値 🔵

TC-010-13 (README 使用例) は `PhaseInstance(phase_ref=..., lattice=...)` を scale 省略で構築する。
`scale: float` → `scale: float = 1.0` へ変更。既存呼び出しは全 27 箇所が scale を明示するため
後方互換 (要件 §3.2、`sorted()` 検証済み: default 引数の順序制約も満たす)。

### 1.3 `README.md` — 「使い方 (M1): 多仮説木探索」節 + アーキテクチャ表

- M0 使用例の後に M1 最小使用例 (公開 API のみ、candidates→search→ranked→to_summary、
  export_gpx への言及) を追加。TC-010-13 の写経コードと同等。
- 冒頭「状態」を M1 反映へ更新。アーキテクチャ表に `tsumugin.search` / `.export` / `.webui` 行を追加。

### 1.4 `docs/dev/context.md` — M1 反映

Overview スコープ、Project Structure (search/export/webui/pipeline)、公開 API 一覧、
Additional Notes の「M0 スコープ外」→「M1 実装済み / M2+ スコープ外」を更新。

## 2. テスト実行結果

```text
tests/test_m1_e2e.py: 13 passed  (@gsas 2 件は GSAS-II 導入環境で実行)
全体: 218 passed, 3 skipped
カバレッジ (uv run pytest --cov=tsumugin): TOTAL 96% (>= 90%)
uvx ruff@latest check src tests: All checks passed!
```

## 3. 課題・改善点 (Refactor 候補)

- 実装は re-export + 既定値追加のみで最小。追加のリファクタ余地は小さい。
- `PhaseInstance.scale` の既定値追加は公開 API のエルゴノミクス改善であり、Refactor での
  戻しは不要 (テスト契約に必須)。
