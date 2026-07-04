# Verification Report: m5-nested-mem-oed

> 作成予定 / TDD 自律実装 (nested/laplace evidence + 階層的裁定 + 確率較正 / MEMBackend + Dysnomia 連携 /
> OED 測定フィードバック提案 / MCP run_mem 実体化 / 公開 API 統合)

**状態**: ⏳ 未着手 (本レポートは実装完了時 TASK-0058 で埋める雛形。M4 verification.md のフォーマット踏襲)

## サマリ (実装完了時に記入)

M5 (nested sampling 裁定・MEM 電子/核密度解析・OED 提案・較正済み確率) スコープの 12 タスク
(TASK-0047〜0058) を TDD で実装完了予定。全タスク `status: done` を目標。

- **テスト**: (実装後記入) passed / skipped (skip は dynesty/ultranest・Dysnomia バイナリ・PyBOED 未導入前提の
  `@pytest.mark.nested` / `@pytest.mark.mem` / `@pytest.mark.oed` 分岐)
- **外部依存 contract / smoke tests**: `-m nested` / `-m mem` / `-m oed` で分離。未導入環境では `conftest.py` が
  自動 skip (REQ-406/NFR-106 のバージョン固定 contract test を含む)。
- **カバレッジ**: (実装後記入・M4 基準 96% 維持目標)
- **Lint**: `uvx ruff check src tests` クリーン (line-length 100) 目標
- **再現性**: MEM 入力生成・OED 提案・較正評価はビット同一。nested は種固定で logZ±誤差範囲一致
  (NFR-102 の nested 例外, REQ-402)

## タスク別テスト内訳 (予定)

| Task | モジュール | テスト | 状態 |
|------|-----------|-------|------|
| 0047 | errors.py 拡張 (NestedUnavailableError / OEDUnavailableError) | test_errors.py 追補 | ⏳ |
| 0048 | nested/laplace (LaplaceBackend・BIC フォールバック) | test_laplace.py | ⏳ |
| 0049 | nested/base + nested/prior (EvidenceProblem・ProblemAware・PriorSpec・build_prior_from_restraints) | test_nested_prior.py / test_nested_base.py | ⏳ |
| 0050 | nested/sampler (NestedBackend・遅延 import・run_with_fallback) | test_nested_sampler.py (@nested) | ⏳ |
| 0051 | nested/arbitration (arbitrate・2 段構え) | test_arbitration.py | ⏳ |
| 0052 | nested/calibration (reliability/ECE・bic/nested 別系列) | test_calibration.py | ⏳ |
| 0053 | mem/base (MEMBackend Protocol・MEMResult 群) | test_mem_base.py | ⏳ |
| 0054 | mem/inputgen (F_obs 抽出・build_mem_input・probe→密度種別) | test_mem_inputgen.py | ⏳ |
| 0055 | mem/dysnomia (DysnomiaBackend・遅延 import・MEMUnavailableError) | test_mem_dysnomia.py (@mem) | ⏳ |
| 0056 | mem/iterate + output + guard + spot (MPF 反復・密度出力・適用ガード・スポット) | test_mem_iterate.py / test_mem_output.py / test_mem_guard.py / test_mem_spot.py | ⏳ |
| 0057 | mcp/mem.py 実体化 (run_mem_boundary MEMBackend 委譲) | test_mcp_mem_impl.py | ⏳ |
| 0058 | oed (proposal/pyboed) + 公開 API 統合 + M5 E2E + ドキュメント | test_oed_proposal.py / test_oed_pyboed.py (@oed) / test_m5_e2e.py / test_m5_symbols_sorted.py | ⏳ |

## TASK-0058 完了条件の適合 (実装完了時に記入)

| 完了条件 | 状態 | 担保 |
|---|---|---|
| ① OED 判別測定提案 (情報利得順 JSON, TC-512-01) | ⏳ | (実装後) |
| ② OED 非破壊 (ledger 追記のみ, TC-512-02) | ⏳ | (実装後) |
| ③ 僅差競合なしで空提案 (TC-512-03) | ⏳ | (実装後) |
| ④ PyBOED 未導入で OEDUnavailableError・提案生成 v1 は動作 (TC-512-04) | ⏳ | (実装後) |
| ⑤ M5 新規シンボル __all__ 追加 + 昇順維持 (TC-514-05/REQ-404) | ⏳ | (実装後) test_m5_symbols_sorted |
| ⑥ nested/MEM/OED/MCP 一気通貫 E2E (TC-515-01/03/05/06) | ⏳ | (実装後) |
| ⑦ 全経路で ledger.verify() True・削除/上書き API 不在 (TC-514-01/02) | ⏳ | (実装後) |
| ⑧ コア import が numpy のみ (TC-514-04/REQ-403) | ⏳ | (実装後) |
| ⑨ 全 green・cov 維持・ruff clean・README/CLAUDE.md/検証レポート | ⏳ | (実装後) 本レポート |

## 仕様適合の要点 (実装完了時に記入)

- **P2 / NFR-101 / NFR-105**: nested 裁定振り分け・MEM 反復サイクル・OED 提案・較正結果は ledger 追記のみ。
  MEM 反復は子スナップショット追記 (SnapshotStore の save/revert のみ・削除/上書き API なし)。
  探索段 `SearchResult` と探索 ledger は不変 (arbitrate は bic 一次を書き換えない)。`ledger.verify()` は
  M5 全操作を通しても True。
- **REQ-404 (公開 API 集約)**: M5 コアシンボルをサブパッケージ名昇順ブロックで re-export し、トップレベル
  `__all__` 全体を昇順維持。すべて `is` 同一実体。実サンプラ/バイナリ非依存分のみコア公開。
- **REQ-403 (依存の縮退)**: `import tsumugin` は dynesty/ultranest/dysnomia/pyboed を引き込まない
  (score_problem/DysnomiaBackend.run/acquire の関数内遅延 import)。コア import は numpy のみ。
- **REQ-031/103 (Dara 教訓)**: MEM 適用ガードは warnings のみで仮説除外しない。多相/低統計でも MEM 実行継続。
- **REQ-101/EDGE-002 (nested 打ち切り)**: 30 分上限超過は例外化せず Laplace 代替へ縮退 (truncated=True + 警告)。
- **NFR-102 (nested 例外)**: nested は種固定でも確率的 → ビット同一でなく logZ±誤差で再現性保証。MEM 入力生成
  (反射昇順)・OED 提案 (利得降順+kind 昇順)・較正 (ビン下端昇順・backend 昇順) はビット同一。

## 設計上の注記 / interfaces.py との差異 (実装完了時に記入)

- (実装時に interfaces.py 契約からの逸脱・非破壊追加フィールド等を記録)

## 見送り事項 (実装完了時に記入)

- (`/code-review` で見送った指摘があれば理由と共に記録。M-later Issue 化候補)

## M5 スコープ外 (次段 M-later)

ab initio 構造決定 / PDF・磁気・2D 方位解析 / MEM-Rietveld 反復の条件付き auto 運転本実装 (v1 は既定オフ) /
PyBOED 獲得関数による能動的次測定「実行」(v1 は提案生成のみ) / Dysnomia 以外の内製 MEM ソルバ /
nested 事前分布の高度な階層モデル / 較正ベンチ公開の CI・公開基盤整備。
