# Verification Report: m5-nested-mem-oed

> 2026-07-04 / TDD 自律実装 (nested/laplace evidence + 階層的裁定 + 確率較正 / MEMBackend + Dysnomia 連携 /
> OED 測定フィードバック提案 / MCP run_mem 実体化 / 公開 API 統合)

**状態**: ✅ 完了 (TASK-0047〜0058 全タスク `status: done`)

## サマリ

M5 (nested sampling 裁定・MEM 電子/核密度解析・OED 提案・較正済み確率) スコープの 12 タスク
(TASK-0047〜0058) を TDD で実装完了。

- **テスト**: 1028 passed, 10 skipped, exit=0。skip は外部依存未導入前提の分岐
  (`@pytest.mark.gsas` / `@pytest.mark.mcp` / `@pytest.mark.nested` / `@pytest.mark.mem` /
  `@pytest.mark.oed` = dynesty/ultranest・Dysnomia バイナリ・PyBOED・mcp SDK・GSAS-II 未導入)。
- **外部依存 contract / smoke tests**: `-m nested` / `-m mem` / `-m oed` で分離。未導入環境では
  `conftest.py` が自動 skip する (gsas/mcp と同型の `pytest_collection_modifyitems` 配線)。
- **カバレッジ**: 95% (4527 stmts / 216 miss)。未カバー分は外部依存で auto-skip される gated 経路に集中
  (`nested/sampler.py` 59% / `mcp/server.py` 29% / `mem/dysnomia.py` 65% 等、実サンプラ/SDK/バイナリ導入
  環境でのみ通る経路)。コアの提案生成 `oed/proposal.py` は 100%。
- **Lint**: `uvx ruff check src tests` クリーン (line-length 100)。
- **再現性**: MEM 入力生成 (反射昇順)・OED 提案 (利得降順+kind 昇順)・較正評価 (ビン下端昇順・backend 昇順)
  はビット同一。nested は種固定でも確率的なため logZ±誤差での再現 (NFR-102 の nested 例外, REQ-402)。

## タスク別テスト内訳

| Task | モジュール | テスト | 件数 | 状態 |
|------|-----------|-------|------|------|
| 0047 | errors.py 拡張 (NestedUnavailableError / OEDUnavailableError) | test_errors.py 追補 | 3 | ✅ |
| 0048 | nested/laplace (LaplaceBackend・BIC フォールバック) | test_nested_laplace.py | 17 | ✅ |
| 0049 | nested/base + nested/prior (EvidenceProblem・ProblemAware・PriorSpec・build_prior_from_restraints) | test_nested_base.py / test_nested_prior.py | 12 / 13 | ✅ |
| 0050 | nested/sampler (NestedBackend・遅延 import・run_with_fallback) | test_nested_sampler.py (@nested) | 11 | ✅ |
| 0051 | nested/arbitration (arbitrate・2 段構え) | test_nested_arbitration.py | 22 | ✅ |
| 0052 | nested/calibration (reliability/ECE・bic/nested 別系列) | test_nested_calibration.py | 20 | ✅ |
| 0053 | mem/base (MEMBackend Protocol・MEMResult 群) | test_mem_base.py | 9 | ✅ |
| 0054 | mem/inputgen (F_obs 抽出・build_mem_input・probe→密度種別) | test_mem_inputgen.py | 15 | ✅ |
| 0055 | mem/dysnomia (DysnomiaBackend・遅延 import・MEMUnavailableError) | test_mem_dysnomia.py (@mem) | 12 | ✅ |
| 0056 | mem/iterate + output + guard + spot (MPF 反復・密度出力・適用ガード・スポット) | test_mem_iterate.py / test_mem_output.py / test_mem_guard.py / test_mem_spot.py | 9 / 11 / 9 / 5 | ✅ |
| 0057 | mcp/mem.py 実体化 (run_mem_boundary MEMBackend 委譲) | test_mcp_mem.py | 12 | ✅ |
| 0058 | oed (proposal/pyboed) + 公開 API 統合 + M5 E2E + ドキュメント | test_oed.py / test_m5_e2e.py | 24 / 13 | ✅ |

## TASK-0058 完了条件の適合

| 完了条件 | 状態 | 担保 |
|---|---|---|
| ① OED 判別測定提案 (情報利得順 JSON, TC-512-01) | ✅ | `test_proposes_when_close_competitor_exists` / `test_proposals_to_json_shape_and_order` / `test_proposals_sorted_by_information_gain_descending` |
| ② OED 非破壊 (ledger 追記のみ, TC-512-02) | ✅ | `test_propose_is_non_destructive_on_hypotheses` / `test_propose_records_only_appends_to_ledger` |
| ③ 僅差競合なしで空提案 (TC-512-03/EDGE-010) | ✅ | `test_no_close_competitor_returns_empty_tuple` / `test_propose_no_close_competitor_does_not_touch_ledger` |
| ④ PyBOED 未導入で OEDUnavailableError・提案生成 v1 は動作 (TC-512-04) | ✅ | `test_acquire_raises_oed_unavailable_when_pyboed_missing` / `test_propose_does_not_depend_on_pyboed` |
| ⑤ M5 新規シンボル __all__ 追加 + 昇順維持 (TC-514-05/REQ-404) | ✅ | `test_m5_symbols_in_dunder_all_and_sorted` (__all__ 151 件・全昇順) / `test_m5_reexports_are_same_object` |
| ⑥ nested/MEM/OED/MCP 一気通貫 E2E (TC-515-01/03/05/06) | ✅ | `test_m5_nested_pipeline_end_to_end` / `test_m5_mem_pipeline_end_to_end` / `test_m5_oed_pipeline_end_to_end` / `test_m5_mcp_run_mem_end_to_end` |
| ⑦ 全経路で ledger.verify() True・削除/上書き API 不在 (TC-514-01/02) | ✅ | `test_m5_no_destructive_api` (nested 裁定 + OED 提案 + MEM 反復を 1 本の ledger に集約・破壊的動詞走査) |
| ⑧ コア import が numpy のみ (TC-514-04/REQ-403) | ✅ | `test_m5_core_imports_numpy_only` (dynesty/ultranest/pyboed を sys.modules に載せない) |
| ⑨ 全 green・cov 維持・ruff clean・README/CLAUDE.md/検証レポート | ✅ | 1028 passed / cov 95% / ruff clean / README M5 節 (実行検証済み) / 本レポート |

## 仕様適合の要点

- **P2 / NFR-101 / NFR-105**: nested 裁定振り分け・OED 提案・較正結果は ledger 追記のみ。MEM-Rietveld 反復は
  子スナップショット追記 (SnapshotStore の save のみ・削除/上書き API なし)。`arbitrate` は bic 一次を
  書き換えず入力 Hypothesis の status/metrics 不変。`ledger.verify()` は M5 全操作を通しても True。
- **REQ-404 (公開 API 集約)**: M5 コア 40 シンボルを `mem`→`nested`→`oed` のサブパッケージ名昇順ブロックで
  re-export し、トップレベル `__all__` (既存 111 + 40 = 151 件) 全体を完全昇順維持。すべて `is` 同一実体
  (二重実装なし)。8 ツール実処理関数 (`run_mem` 等) はトップレベル `__all__` に載せない (mcp 側公開のまま)。
- **REQ-403 (依存の縮退)**: `import tsumugin` は dynesty/ultranest/dysnomia/pyboed を引き込まない
  (`NestedBackend.score_problem` / `DysnomiaBackend.run` / `oed.pyboed.acquire` の関数内/遅延 import)。
  コア import は numpy のみ (`test_m5_core_imports_numpy_only` / `test_import_pyboed_module_succeeds_without_pyboed`)。
- **REQ-035〜038/304/EDGE-010 (OED v1)**: `propose_measurements` は close_competitor が 2 件以上のときのみ
  4 種の判別測定 (高統計再測定/中性子 joint/組成分析/追加温度点) を情報利得順に提案。情報利得は僅差競合数・
  evidence 差から決定論導出 (乱数不使用)。僅差競合が無ければ空 tuple + ledger 不変。
- **REQ-036/105/EDGE-011 (OED 境界)**: `acquire` は pyboed を遅延 import し未導入で `OEDUnavailableError`。
  v1 の提案生成は本境界に非依存でコアのみで動作。
- **NFR-102 (nested 例外)**: nested は種固定でも確率的 → ビット同一でなく logZ±誤差で再現。MEM 入力生成
  (反射昇順)・OED 提案 (利得降順+kind 昇順)・較正 (ビン下端昇順・backend 昇順) はビット同一。

## 設計上の注記 / interfaces.py との差異

- **OED 発動条件の明確化**: interfaces.py は「close_competitor が存在するときのみ提案」と記す。実装では
  判別対象 (競合相手) が成立するために **僅差競合 2 件以上** を発動条件とした (best のみ close の単独ケースや
  単一仮説では判別対象が無いため空 tuple)。E2E / OED テスト (`test_single_hypothesis_returns_empty_tuple`)
  で固定。interfaces.py の非破壊・情報利得順・決定論の契約からの逸脱はない。
- **pyproject `oed`/`mem` extra**: pyboed / Dysnomia はいずれも PyPI 未公開のため、extra は runtime python
  依存のみを置き (現状空)、導入手順をコメントで案内する (gsas extra と同型)。`nested` extra は dynesty を
  主依存として指定。既存 gsas/web/mcp extra は不変。
- **公開 API 節の逸脱なし**: TASK-0058 では新規公開シンボルの新設は OED (proposal/pyboed) のみで、その他は
  TASK-0047〜0057 の実装済みシンボルを集約するのみ。interfaces.py 公開 API 節の 40 シンボルと `__init__.py`
  re-export が 1:1 一致することを `_M5_PROMOTED_SYMBOLS` で固定した。

## 見送り事項

- なし (TASK-0058 完了条件 9 項目すべて green)。

## M5 スコープ外 (次段 M-later)

ab initio 構造決定 / PDF・磁気・2D 方位解析 / MEM-Rietveld 反復の条件付き auto 運転本実装 (v1 は既定オフ) /
PyBOED 獲得関数による能動的次測定「実行」(v1 は提案生成のみ) / Dysnomia 以外の内製 MEM ソルバ /
nested 事前分布の高度な階層モデル / 較正ベンチ公開の CI・公開基盤整備。
