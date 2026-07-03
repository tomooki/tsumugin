# Verification Report: m1-hypothesis-search

> 2026-07-03 / TDD 自律実装 (M1: 多仮説木探索 — 全 10 タスク完了)

## サマリ

M1 (多仮説木探索) スコープの 10 タスク (DIRECT 1 / TDD 9) を TDD で実装完了。全タスク完了。
M0 (PoC) の全公開面を非破壊で維持したまま、候補相集合からの best-first 木探索・
Evidence(BIC) ランキング・`.gpx` 書き出し・read-only Web UI・公開 API 統合を積み上げた。

- **テスト**: 218 passed, 3 skipped (221 collected)。skip 3 件はいずれも「GSAS-II 導入済みのため
  *未導入時に例外* 経路を実行しない」正しい skip (test_gpx_export.py ×2 / test_gsasii_backend.py ×1)。
- **GSAS-II 経路 (`@pytest.mark.gsas`)**: 17 本すべて実 GSAS-II (2.0, win_64_p3.12_n2.2 バイナリ) で green。
- **カバレッジ**: 96% (1300 stmts / 53 miss)。M1 追加分 (`search` / `export` / `webui`) を含め 90% 基準を充足。
- **Lint**: `uvx ruff check src tests` クリーン (line-length 100, target py312)。
- **決定論**: 同一入力 → `to_summary()` の canonical JSON がビット同一を E2E で検証 (REQ-403 / NFR-102)。
- **公開 API**: `from tsumugin import HypothesisTreeSearch, SearchConfig, SearchResult, PhaseCandidate,`
  `UnmatchedPeakReport, export_gpx, ...` がトップレベルで解決。`__all__` は M0+M1 統合・アルファベット昇順。

## タスク別テスト内訳

| Task | 種別 | モジュール | テスト | 状態 |
|------|------|-----------|-------|------|
| 0001 | DIRECT | web extra + パッケージ骨格 (`pyproject.toml` / `search`・`export`・`webui` 骨格) | import/`test_webui.py` 経由で担保 | ✅ |
| 0002 | TDD | search.peaks (find_peaks) | test_peaks.py (17) | ✅ |
| 0003 | TDD | search.matcher (PeakMatcher スコア/未マッチ) | test_matcher.py (22) | ✅ |
| 0004 | TDD | search.pruning (dynamic_threshold) | test_pruning.py (13) | ✅ |
| 0005 | TDD | search.clustering (Jaccard + FoM + Jenks) | test_clustering.py (19) | ✅ |
| 0006 | TDD | search.tree (木探索コア: 展開/探索精密化/ledger) | test_tree_search.py (36)* | ✅ |
| 0007 | TDD | search.tree (後処理: 良好解/フル精密化/未知相/summary) | test_tree_search.py (36)* | ✅ |
| 0008 | TDD | export.gpx (export_gpx) | test_gpx_export.py (13 + 2 skip) | ✅ |
| 0009 | TDD | webui.app (FastAPI read-only) | test_webui.py (17) | ✅ |
| 0010 | TDD | `__init__` 公開 API 統合 + E2E | test_m1_e2e.py (13) | ✅ |

*`test_tree_search.py` の 36 件は TASK-0006 (木探索コア) と TASK-0007 (探索後処理) を合わせて担保する
(両タスクが同一 `search/tree.py` に積層するため、テストファイルを共有)。

**M1 テスト計**: 150 件 (peaks 17 + matcher 22 + pruning 13 + clustering 19 + tree 36 + gpx 13 + webui 17 + e2e 13)。
M0 から継続の 71 件 (68 passed + 3 skip の内 1 は M0 gsasii、2 は M1 gpx) と合わせ 221 collected。

## TASK-0010 完了条件の充足 (本タスク)

| # | 完了条件 | 根拠 | 状態 |
|---|---------|------|------|
| ① | `from tsumugin import HypothesisTreeSearch, ...` で M1 API 利用可能 | `src/tsumugin/__init__.py` re-export + `__all__` 昇順 / TC-010-01,02 | ✅ |
| ② | E2E: 合成 2 相 search が真構成 {A,B} を 1 位・summary が JSON 化可 | TC-010-03,04 (`test_m1_e2e.py`) | ✅ |
| ③ | (@gsas) GSASIIBackend での search E2E 完走 | TC-010-06,07 (実 GSAS-II で green) | ✅ |
| ④ | 全テスト green・カバレッジ 90% 以上・ruff clean | 218 passed/3 skip・96%・ruff clean | ✅ |
| ⑤ | README に M1 使用例 (10-15 行)・context.md 実装済みモジュール表更新 | `README.md` §使い方(M1) L84-105 + アーキ表 / `docs/dev/context.md` | ✅ |
| ⑥ | 検証レポート (本ファイル) | `docs/tasks/m1-hypothesis-search/reports/verification.md` | ✅ |

## E2E テストケース (TC-010-01〜13) の網羅

`tests/test_m1_e2e.py` にテストケース定義書の全 13 件を 1:1 実装、全 green。

- **正常系 7**: 公開シンボル re-export (01) / `__all__` 昇順・後方互換 (02) / SimulatedBackend E2E で
  {A,B} 1 位 (03) / summary の JSON 化 + `/api/result` スキーマ (04) / ledger.verify True (05) /
  @gsas search 完走 (06) / @gsas search→export_gpx→再オープンで相数一致 (07)。
- **異常系 3**: D6 遅延 import 契約 — fastapi/uvicorn/GSASII 遮断下でも `import tsumugin` 成功 (08) /
  候補ゼロで空 `SearchResult` へ縮退 (09) / 未知相混入で `unknown_phase_flag` + 未マッチ報告 (10)。
- **境界値 3**: 決定論ビット同一 (11) / 候補 1 相で深さ 1・単一仮説 (12) / README 使用例の実行可能性 (13)。

## 仕様適合の要点

- **FR-110〜117 (多仮説木探索)**: find_peaks → PeakMatcher → Jaccard クラスタ (Jenks FoM) → 動的枝刈り →
  best-first 展開 → 段階精密化 → BIC → softmax ランキング → 後処理 (良好解クラスタ / フル精密化 /
  未知相フラグ / summary) を `search/` に実装。E2E で真の 2 相構成が 1 位になることを検証。
- **P2 / NFR-101 / NFR-105 (非破壊・監査)**: 探索の全操作 (match/cluster/prune/node_refine/
  branch_prune/ranking) を追記専用ハッシュチェーン Ledger に理由付き記録。E2E で `verify()` True + entries 非空。
- **NFR-102 / REQ-403 (決定論)**: 乱数種固定 + canonical JSON ソートで `to_summary()` がビット同一。
- **FR-117 (未知相)**: 候補で説明できない観測ピークを黙殺せず `unknown_phase_flag` + 位置・強度付き
  `unmatched_observed` として構造化提示。
- **FR-505 (相互運用)**: `export_gpx` で相集合 + 観測を GSAS-II GUI 再オープン可能な `.gpx` へ書き出し。
  @gsas E2E で再オープン後の相数一致を担保。
- **FR-421〜424 (Web UI)**: FastAPI ベースの read-only UI (`webui`)。optional `web` extra は遅延 import
  (D6 契約) で、コア (numpy のみ) 利用者の `import tsumugin` を汚染しない。
- **後方互換 (要件 §3.2)**: M0 公開シンボル 18 件を 1 つも削除・改名せず、M1 の 6 シンボルを昇格追加。

## 設計上の注記 / 実装時に確定した事項

- **昇格シンボル**: 必須 5 (`HypothesisTreeSearch` / `SearchConfig` / `SearchResult` / `PhaseCandidate` /
  `export_gpx`) に summary 解釈用の `UnmatchedPeakReport` と `Peak` を加えトップレベル公開。
- **`PhaseInstance.scale`**: README 使用例 (TC-010-13) が `scale` 省略で構築するため既定値 1.0 を付与
  (後方互換、M0 の位置引数呼び出しに影響なし)。
- **@gsas E2E の実行コスト**: 実 GSAS-II 精密化を伴う探索は module スコープ fixture で 1 回だけ実行し、
  TC-010-06/07 の 2 ケースで共有 (実行時間の抑制)。
- **既知の無害警告**: 起動時の "Error reading {cfgfile}" は GSAS-II が既存 `~/.GSASII/config.ini` (cp932)
  を UTF-8 で読む upstream 表示バグ。テスト実行・結果に影響なし (context.md に記録済み)。

## M1 スコープ外 (次段 M2+)

シーケンシャル/operando (FR-300/310)、中性子 joint (FR-240)、MEM (FR-600)、nested sampling、
REST/MCP、永続化 DB。M1 の Web UI は read-only 最小版に留め、書き込み・実行トリガは M2+ で本格化する。
