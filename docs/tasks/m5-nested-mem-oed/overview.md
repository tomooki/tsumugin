# m5-nested-mem-oed タスク概要

**作成日**: 2026-07-04 / **総タスク数**: 12 件 (全 TDD) / **推定工数**: 約 51 時間

## 関連文書

- [📋 requirements.md](../../spec/m5-nested-mem-oed/requirements.md) /
  [✅ acceptance-criteria.md](../../spec/m5-nested-mem-oed/acceptance-criteria.md) /
  [📐 architecture.md](../../design/m5-nested-mem-oed/architecture.md) /
  [📝 interfaces.py](../../design/m5-nested-mem-oed/interfaces.py) /
  [🔄 dataflow.md](../../design/m5-nested-mem-oed/dataflow.md) /
  [💬 design-interview.md](../../design/m5-nested-mem-oed/design-interview.md)

## フェーズ構成

| フェーズ | 成果物 | タスク | 工数 |
|---------|--------|--------|------|
| Phase 1: 例外拡張 | errors.py に NestedUnavailableError / OEDUnavailableError (末尾追加・MEMUnavailableError と対称) | TASK-0047 | 2h |
| Phase 2: evidence 拡張基盤 | LaplaceBackend (score/score_problem・BIC フォールバック) / EvidenceProblem・ProblemAwareEvidenceBackend・PriorSpec・RestraintSpec・build_prior_from_restraints | TASK-0048〜0049 | 8h |
| Phase 3: nested サンプラ + 裁定 + 較正 | NestedBackend (遅延 import・run_with_fallback) / arbitrate (2 段構え・ledger) / reliability_diagram・ECE・calibrate_by_backend | TASK-0050〜0052 | 15h |
| Phase 4: MEM 境界 + 入力生成 | MEMBackend Protocol・MEMResult 群 / StructureFactor・MEMInput・extract_structure_factors・build_mem_input | TASK-0053〜0054 | 9h |
| Phase 5: MEM 実行系 (Dysnomia + 反復 + 出力 + ガード + スポット) | DysnomiaBackend (遅延 import) / run_mem_rietveld・output・guard・spot | TASK-0055〜0056 | 10h |
| Phase 6: MCP run_mem 実体化 + OED | run_mem_boundary MEMBackend 委譲 / propose_measurements・proposals_to_json・acquire | TASK-0057〜0058 | 7h |
| Phase 7: 統合 | 公開 API __all__ 昇順 + M5 E2E + ドキュメント | (TASK-0058 に統合) | — |

> 注: 統合 (公開 API / M5 E2E / ドキュメント) は独立タスクとして最終に置く。以下の一覧参照。

## タスク一覧と依存関係

- [ ] [TASK-0047: errors.py 拡張 (NestedUnavailableError / OEDUnavailableError)](TASK-0047.md) - 2h (TDD) 🔵
- [ ] [TASK-0048: nested/laplace (LaplaceBackend・score/score_problem・BIC フォールバック)](TASK-0048.md) - 4h (TDD) 🔵
- [ ] [TASK-0049: nested/base + nested/prior (EvidenceProblem・ProblemAwareEvidenceBackend・PriorSpec・RestraintSpec・build_prior_from_restraints)](TASK-0049.md) - 4h (TDD) 🔵
- [ ] [TASK-0050: nested/sampler (NestedBackend・NestedConfig・NestedOutcome・遅延 import・run_with_fallback)](TASK-0050.md) - 6h (TDD) 🔵
- [ ] [TASK-0051: nested/arbitration (arbitrate・ArbitrationConfig/Result・ArbitratedHypothesis・2 段構え・ledger)](TASK-0051.md) - 5h (TDD) 🔵
- [ ] [TASK-0052: nested/calibration (reliability_diagram・expected_calibration_error・calibrate_by_backend・CalibrationReport/Sample・ReliabilityBin)](TASK-0052.md) - 4h (TDD) 🔵
- [ ] [TASK-0053: mem/base (MEMBackend Protocol・MEMResult・MEMDensityMap・DensityCrossSection・BondPathDensity)](TASK-0053.md) - 3h (TDD) 🔵
- [ ] [TASK-0054: mem/inputgen (StructureFactor・MEMInput・extract_structure_factors・build_mem_input)](TASK-0054.md) - 6h (TDD) 🔵
- [ ] [TASK-0055: mem/dysnomia (DysnomiaBackend・遅延 import・未導入 MEMUnavailableError・入出力契約)](TASK-0055.md) - 4h (TDD) 🔵
- [ ] [TASK-0056: mem/iterate + output + guard + spot (run_mem_rietveld・密度出力・適用ガード・スポット解析)](TASK-0056.md) - 6h (TDD) 🔵
- [ ] [TASK-0057: mcp/mem.py 実体化 (run_mem_boundary MEMBackend 委譲・placeholder 後方互換・mcp/tools run_mem)](TASK-0057.md) - 3h (TDD) 🔵
- [ ] [TASK-0058: oed (proposal/pyboed) + 公開 API 統合 + M5 E2E + ドキュメント](TASK-0058.md) - 4h (TDD) 🔵

### 依存グラフ

```
0047: 先行依存なし (既存 errors.py + TsumuginError のみ)
0048: 先行依存なし (既存 EvidenceBackend/EvidenceResult/RefinementMetrics のみ)
0047 → 0050              (NestedBackend の score_problem 未導入経路が NestedUnavailableError)
0048 → 0049              (EvidenceProblem は Laplace のフォールバック入力を束ねる — 型参照)
0048, 0049 → 0050        (NestedBackend は laplace 代替先 + EvidenceProblem/PriorSpec を受ける)
0050 → 0051              (arbitrate は nested.run_with_fallback を配線)
(0048, 0049 → 0051 も可 : arbitrate は EvidenceProblem を引数に取る)
0048 → 0052 は不要        (calibration は evidence 値に非依存・独立)
0053 → 0054              (MEMInput は mem/base の型に依存しないが同レイヤ・inputgen は MEMBackend 非依存)
0053 → 0055              (DysnomiaBackend は MEMBackend Protocol を実装)
0053, 0054, 0055 → 0056  (iterate は MEMBackend + build_mem_input + SnapshotStore を配線)
0053, 0054, 0055 → 0057  (run_mem_boundary は build_mem_input → mem_backend.run へ委譲)
全タスク → 0058          (OED + 公開 API __all__ 昇順 + E2E + ドキュメント)
```

**クリティカルパス**: 0048 → 0049 → 0050 → 0051 → 0058

### 並列実行可能な独立タスク

- **0047** (errors 拡張) と **0048** (laplace) と **0053** (mem/base) は先行依存がなく並列着手可能。
- **0052** (calibration) は evidence 値・nested サンプラに非依存 (CalibrationSample の予測確率入力のみ) で、
  0048〜0051 と並列に実装できる。
- nested 系 (0048〜0052) と mem 系 (0053〜0056) は互いに独立し、2 系統を並列に進められる。
- OED 提案 (0058 内) は `rank` の close_competitor のみに依存し nested/mem に非依存。

### 直列化が必要な共有ホットスポット (M4 の __init__.py 競合教訓を反映)

- **`src/tsumugin/__init__.py` の `__all__`**: M4 では複数タスクが同一 `__all__` を編集して競合した。
  M5 では **各サブパッケージの新規シンボルの `__all__` 集約・トップレベル `__all__` 末尾追加を TASK-0058
  に一元化**する。0048〜0057 の各タスクは**自パッケージの `__init__.py` (nested/mem/oed) 内に閉じた
  re-export のみ**を行い、トップレベル `tsumugin/__init__.py` は編集しない (直列化ポイントを 0058 に集約)。
- **`pyproject.toml` の optional extra + pytest marker** (`nested`/`mem`/`oed`): 複数タスクが編集すると
  競合するため、**TASK-0058 が一括で `[project.optional-dependencies]` (nested/mem/oed) と
  `[tool.pytest.ini_options] markers` を追加**する。0050/0055/0058 が各マーカーを使うテストを書くが、
  マーカー登録自体は 0058 に集約 (先行タスクは登録前提でテストを書き、0058 マージ時に確定)。
  ※ 実装順で 0050/0055 が 0058 より先行するため、**marker 未登録による pytest warning 回避のためだけに
  `conftest.py` へのマーカー登録 (または pyproject への marker 行追加) を最小限、0050 着手時に前倒しで
  行ってよい** (extra 本体列挙は 0058)。この前倒しも `pyproject`/`conftest` の同一箇所編集となるため、
  1 タスクずつ順に触る (0050 → 0055 → 0058 の直列)。
- **`mcp/mem.py` / `mcp/tools.py`**: run_mem 実体化 (0057) のみが編集。M4 実装との後方互換ホットスポット
  のため単独タスクに隔離する。

## タスク番号管理

**使用済み**: TASK-0001〜0046 (M0〜M4) / **本 M5**: TASK-0047〜0058 / **次回開始**: TASK-0059

## 不変条件チェックリスト (全タスク横断・CLAUDE.md / 仕様由来)

- [ ] **P2 非破壊 / NFR-101 / NFR-105**: nested 裁定振り分け・MEM 反復サイクル・OED 提案・較正は ledger
  追記のみ。MEM 反復は子スナップショット追記 (SnapshotStore の save/revert のみ・削除/上書き API 新設なし)。
  `ledger.verify()` は M5 全操作を通しても常時 True。
- [ ] **NFR-102 決定論**: MEM 入力生成 (反射 (h,k,l) 昇順)・OED 提案 (利得降順 + kind 昇順)・較正
  (ビン下端昇順・backend 昇順) はビット同一。nested は種固定で logZ±誤差 (ビット同一でなく誤差範囲一致
  = nested 例外)。
- [ ] **REQ-403 コア numpy のみ**: `import tsumugin` は追加依存なしで成功。dynesty/ultranest (nested) /
  dysnomia (mem) / pyboed (oed) は全て optional extra + 遅延 import + friendly error。実処理層
  (laplace/arbitration/calibration/inputgen/guard/iterate/output/proposal) は SDK/バイナリ非依存で通常
  pytest 網羅。
- [ ] **REQ-404 後方互換**: 新規 dataclass/例外/Protocol は既定値付き非破壊追加。`EvidenceBackend`・
  `EvidenceResult`・`run_mem_boundary` (M4 placeholder 契約) は不変。公開 `__all__` は末尾追加 + 昇順維持
  (test_m5_symbols_sorted)。
- [ ] **降格思想 (Dara 教訓)**: MEM 適用ガードは警告のみ・仮説除外しない (FR-412 ChemPlausibility と同型)。
- [ ] 各タスク完了で全テスト green・`uvx ruff check src tests` クリーン・カバレッジ維持 (M4 基準 96%)。

## 運用ルール (CLAUDE.md 準拠)

- タスク完了 (全テスト green + ruff clean) ごとに 1 コミット。TDD 厳守 (Red→Green→Refactor)・実装エージェントは Opus。
- 非破壊追加のみ (既存 API 後方互換 / `__all__` は末尾追加 + 昇順維持)。削除・上書き API を新設しない (P2/NFR-101)。
- 決定論・ビット同一 (NFR-102)、ledger は追記 + ハッシュチェーン (`verify()` 常に True, NFR-105)。
- コア依存は numpy のみを維持 (nested/mem/oed は optional extra + 遅延 import + friendly error, REQ-403)。
- MEM 適用ガードは警告のみ (候補除外禁止, REQ-031)、nested 打ち切りは Laplace 代替へ縮退 (例外化しない, REQ-101)。

## 信頼性レベルサマリー

- 🔵: 12 / 🟡: 0 / 🔴: 0 — **品質評価**: 高品質

## 次のステップ

`/tsumiki:kairo-implement TASK-0047` から順に実装 (kairo-loop で自動実行)
