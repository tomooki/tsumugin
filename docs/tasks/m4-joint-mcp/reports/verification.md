# Verification Report: m4-joint-mcp

> 2026-07-04 / TDD 自律実装 (joint + ChemPlausibility + MCP + 公開 API 統合)

## サマリ

M4 (中性子/マルチヒストグラム joint・ChemPlausibility IF・MCP server) スコープの 11 タスク
(TASK-0036〜0046) を TDD で実装完了。全タスク `status: done`。

- **テスト**: 803 passed, 5 skipped (skip は GSAS-II 未導入前提の分岐・Web UI optional extra 経路等)
- **GSAS-II contract / smoke tests**: `-m gsas` で 21 passed (2 ヒスト joint smoke TC-409-02 を含む)。
  未導入環境では `conftest.py` が自動 skip。
- **カバレッジ**: 96% (3598 stmts / 132 miss)
- **Lint**: `uvx ruff check src tests` クリーン (line-length 100)
- **再現性**: joint 検証・降格 rank・MCP フローで同一入力 → ビット同一出力を検証 (NFR-102/REQ-402)

## タスク別テスト内訳

| Task | モジュール | テスト | 状態 |
|------|-----------|-------|------|
| 0036 | model/project (TofBankParams + HistogramRef.bank_params + serialization 往復) | test_model.py / test_serialization.py 追補 | ✅ |
| 0037 | model/phase PhaseRef + errors 2 例外 (MCP/MEMUnavailableError) | test_model.py / test_errors.py 追補 | ✅ |
| 0038 | joint/model + joint/weights | test_joint_model.py (22) | ✅ |
| 0039 | joint/engine (refine_joint / refine_joint_detailed) | test_joint_engine.py (13) | ✅ |
| 0040 | joint/contrast (散乱長/Z テーブル + recommend_occupancy_release) | test_joint_contrast.py (10) | ✅ |
| 0041 | joint/verification (verify_survivors) | test_joint_verification.py (10) | ✅ |
| 0042 | chem/base + chem/rules + chem/compose | test_chem.py (23) | ✅ |
| 0043 | chem/ranking (rank_with_plausibility・降格のみ) | test_chem_ranking.py (10) | ✅ |
| 0044 | mcp/tools + mcp/mem (8 ツール実処理・SDK 非依存) | test_mcp_tools.py (26) | ✅ |
| 0045 | mcp/server (遅延 import アダプタ・stdio/local) | test_mcp_server.py (11) | ✅ |
| 0046 | 公開 API 統合 + M4 E2E + ドキュメント | test_m4_e2e.py (11) | ✅ |

## TASK-0046 完了条件の適合

| 完了条件 | 状態 | 担保 |
|---|---|---|
| ① M4 API がトップレベル import で利用可能 (TC-408-05) | ✅ | `test_m4_public_symbols_are_reexported` / `test_m4_reexports_are_same_object` |
| ② 新規シンボル __all__ 追加 + 昇順維持 (REQ-404) | ✅ | `test_m4_symbols_in_dunder_all_and_sorted` (__all__ 111 件・全昇順) |
| ③ joint 一気通貫 E2E (TC-409-01) | ✅ | `test_m4_joint_pipeline_end_to_end` / `test_m4_joint_pipeline_is_deterministic` |
| ④ MCP E2E (TC-409-03) | ✅ | `test_m4_mcp_end_to_end` (submit→list→compare→accept→revert→get_trajectory→export_gpx) |
| ⑤ 全経路で ledger.verify() True・削除/上書き API 不在 (TC-408-01/02) | ✅ | `test_no_destructive_api_after_m4` |
| ⑥ コア import が numpy のみ (TC-408-04/REQ-403) | ✅ | `test_core_imports_numpy_only` (mcp SDK を sys.modules に載せない) |
| ⑦ (@gsas) 2 ヒスト joint smoke (TC-409-02) | ✅ | `test_m4_two_histogram_joint_smoke` (GSASIIBackend・未導入 auto-skip) |
| ⑧ 全 green・cov 90%+・ruff clean・README/CLAUDE.md/検証レポート | ✅ | 803 passed / cov 96% / ruff clean / 本レポート |

## 仕様適合の要点

- **P2 / NFR-101 / NFR-105**: joint 昇格 (`verify_survivors`) は探索段 `SearchResult` と探索 ledger を
  一切書き換えず、検証用 ledger にのみ追記する (探索の `verify()` 不変)。MCP `revert` は削除でなく
  `FinalSelectionEngine.revert` の superseded 化 (追記型・件数不減)。公開面のシンボル名に破壊的動詞なし。
- **REQ-404 (公開 API 集約)**: M4 コア 26 シンボルをサブパッケージ名昇順ブロックで re-export し
  (`chem`→`errors`→`joint`→`mcp`→`model`)、トップレベル `__all__` (111 件) 全体を昇順維持。
  すべて `is` 同一実体 (二重実装なし)。8 ツール実処理関数は mcp サブパッケージ側公開のままとし
  トップレベル `__all__` には `AnalysisSession` / `create_mcp_server` のみ載せる (interfaces.py 指示)。
- **REQ-403 (依存の縮退)**: `create_mcp_server` はトップレベル import 可能だが、`import tsumugin`
  自体は mcp SDK を引き込まない (mcp.server の関数内遅延 import)。中性子コントラストは軽量静的テーブル
  (`NEUTRON_B_TABLE`/`XRAY_Z_TABLE`) で xraylib 非依存。コア import は numpy のみ。
- **REQ-019/EDGE-005 (Dara 教訓)**: `rank_with_plausibility` は確率の降格のみ。低スコア相・低スコア仮説も
  rank から消えず出力件数 = 入力件数で不変。evidence 値 (BIC) 自体は補正しない。
- **REQ-006/009**: joint 結果は集約 `RefinementResult` (rank/evidence 経路互換) + ヒスト別
  `PerHistogramMetrics` (probe 種別・σ 由来明示) の双方を保持。

## 設計上の注記 / interfaces.py との差異

- **`AnalysisSession` の観測パターン拡張**: interfaces.py の契約フィールドに加え、TASK-0044 で
  `two_theta`/`intensity` を末尾・既定 None で非破壊追加済み。MCP フロー (submit → … → export_gpx)
  が facade 経由で単一観測パターンをスレッドするための最小追加 (後方互換・P2)。TASK-0046 は本拡張を
  そのまま利用し、interfaces.py の公開 API 節 (__all__ 追加シンボル一覧) と E2E は完全一致。
- **公開 API 節の逸脱なし**: TASK-0046 では新規シンボルの新設は行わず、TASK-0036〜0045 の実装済み
  シンボルを集約するのみ。interfaces.py 公開 API 節に列挙された 26 シンボルと `__init__.py` re-export が
  1:1 一致することを `test_m4_public_symbols_are_reexported` / `_M4_PROMOTED_SYMBOLS` で固定した。

## 見送り事項

- なし (TASK-0046 完了条件 8 項目すべて green)。M5 委譲境界 (`run_mem` → `MEMUnavailableError` /
  プレースホルダ) は M4 スコープの契約どおり実装済み (状態変更・破壊的追記なし)。

## M4 スコープ外 (次段 M5)

nested sampling、MEM バックエンド本体 (`run_mem` の実処理)、OED (最適実験計画)。
