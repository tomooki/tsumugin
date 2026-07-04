# m5-nested-mem-oed アーキテクチャ設計

**作成日**: 2026-07-04
**関連要件定義**: [requirements.md](../../spec/m5-nested-mem-oed/requirements.md) / [acceptance-criteria.md](../../spec/m5-nested-mem-oed/acceptance-criteria.md)
**ヒアリング記録**: [design-interview.md](design-interview.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様・M0〜M4 実装に依拠 / 🟡 妥当な推測で確定 / 🔴 根拠なし推測

---

## システム概要 🔵

M0〜M4 の抽象境界 (`EvidenceBackend` / `RefinementBackend` / `Ledger`+`SnapshotStore` /
`rank`(close_competitor) / `JointVerificationResult` / `FrameSeries` / `AnalysisSession`+`run_mem_boundary`)
の上に、**3 つの独立した新レイヤ**を非破壊で載せる:

1. **nested/laplace evidence + 階層的裁定レイヤ** (`nested/`) — 既存 `EvidenceBackend` Protocol を
   壊さず、Hessian 由来の `LaplaceBackend` と dynesty/ultranest 遅延 import の `NestedBackend` を新設。
   木探索は `bic` のまま維持し (探索段不変・FR-122)、`rank` の `close_competitor` 群のみを nested で
   再裁定する 2 段構え `arbitrate` を提供する。reliability diagram / ECE の較正評価 (`calibration.py`) は
   `bic` と `nested` を別系列で出力する (FR-124/§12-5)。
2. **MEMBackend + Dysnomia 連携レイヤ** (`mem/`) — `MEMBackend` Protocol + `MEMResult` の交換可能境界、
   Dysnomia 外部バイナリラッパ (`DysnomiaBackend`, 遅延 import)、joint 結果からの F_obs 抽出・MEM 入力生成
   (X線=電子密度/中性子=核密度)、既定オフの MEM-Rietveld 反復 (子スナップショット追記)、密度マップ/断面/
   ボンド経路最小密度の出力、適用ガード (警告のみ・除外しない)、フレームスポット解析 (FR-600〜606)。
3. **OED / 測定フィードバック提案レイヤ** (`oed/`) — 僅差競合時の判別測定提案を情報利得順 JSON で生成
   (`propose_measurements`)、PyBOED 獲得関数接続境界 (`acquire`, v1 は提案生成のみ)。非破壊 (ledger 追記のみ)
   (FR-430/431/432)。

加えて、M4 の `run_mem` MCP 委譲境界 (`mcp/mem.py::run_mem_boundary`, プレースホルダ) を MEMBackend 委譲へ
**実体化**する (placeholder=True の M4 dict スキーマは後方互換維持, FR-513)。

探索段は不変 (FR-122/REQ-010/201): 木探索は既存 `HypothesisTreeSearch` を `bic` で実行し、nested は
`rank` の close_competitor 群への**再裁定のみ**に限定する。

## アーキテクチャパターン 🔵

- **パターン**: M0〜M4 と同一 (不変データ + Protocol 境界 + 追記専用ストア + 純関数コア + 遅延 import アダプタ)
- **選択理由**: nested/laplace は `EvidenceBackend` と同じ Protocol 交換境界。MEMBackend は
  `RefinementBackend` / `EvidenceBackend` / `ChemPlausibility` と同型の Protocol。外部依存の遅延 import は
  M1 `webui` (extra `web` + `WebUIUnavailableError` 縮退) / M4 `mcp.server` (extra `mcp` +
  `MCPUnavailableError` 縮退) の実績パターンを踏襲する。nested/mem/oed の 3 extra + 3 friendly error は
  この「available + 専用例外」パターンの水平展開である 🔵

## コンポーネント構成

### 新規モジュール

| モジュール | 役割 | 要件 | 信頼性 |
|---|---|---|---|
| `errors.py` 拡張 | `NestedUnavailableError` / `OEDUnavailableError` を末尾追加 (`MEMUnavailableError` と対称) | REQ-005/036 | 🔵 |
| `nested/laplace.py` | `LaplaceBackend`(Hessian 由来 Laplace 近似・特異時 BIC フォールバック+警告) | REQ-001/002/003/EDGE-005 | 🔵 (行列演算 🟡) |
| `nested/base.py` | `EvidenceProblem`(尤度+prior+Hessian)・`PriorSpec`・`ProblemAwareEvidenceBackend` Protocol (score(metrics) を壊さない拡張, D1) | REQ-004/008/D1 | 🔵 |
| `nested/prior.py` | `RestraintSpec`・`build_prior_from_restraints`(restraint 自動構成+手動上書き) | REQ-008/301/FR-125 | 🔵 |
| `nested/sampler.py` | `NestedBackend`(dynesty/ultranest 遅延 import・logZ+logz_err・value=-logZ 符号統一・種固定)・`NestedConfig`・`NestedOutcome`・`run_with_fallback`(30 分打ち切り→Laplace 代替) | REQ-004〜009/101/301/EDGE-001/002/004/014 | 🔵 (n_live 🟡) |
| `nested/arbitration.py` | `arbitrate`(bic 一次 rank→close_competitor 群のみ nested 再裁定→統合)・`ArbitrationConfig`(full_nested)・`ArbitrationResult`・`ArbitratedHypothesis`(adjudicated_by) | REQ-010〜013/102/201/EDGE-003 | 🔵 |
| `nested/calibration.py` | `reliability_diagram`/`expected_calibration_error`/`calibrate_by_backend`・`CalibrationReport`(bic/nested 別系列)・`CalibrationSample`・`ReliabilityBin` | REQ-014〜017/106/EDGE-012 | 🔵 |
| `mem/base.py` | `MEMBackend` Protocol・`MEMResult`・`MEMDensityMap`・`DensityCrossSection`・`BondPathDensity` | REQ-018/027〜029 | 🔵 |
| `mem/inputgen.py` | `StructureFactor`・`MEMInput`・`extract_structure_factors`(F_obs 位相モデル由来)・`build_mem_input`(probe→密度種別・決定論反射順) | REQ-021/022/023 | 🔵 (F_obs 抽出 🟡) |
| `mem/dysnomia.py` | `DysnomiaBackend`(外部バイナリラッパ・遅延起動・未導入時 `MEMUnavailableError`・入出力契約固定) | REQ-019/020/406/EDGE-006 | 🔵 (契約 🟡) |
| `mem/guard.py` | `check_mem_applicability`・`MEMApplicabilityReport`(推奨条件判定・**警告のみ・除外しない**) | REQ-030/031/103/EDGE-007 | 🔵 |
| `mem/iterate.py` | `run_mem_rietveld`(MPF 反復・既定オフ・子スナップショット追記・収束/max_iter/発散停止・親不変)・`MEMRietveldConfig`/`Cycle`/`Result` | REQ-024/025/026/107/202/EDGE-008/009 | 🔵 (MPF 🟡) |
| `mem/output.py` | `write_density_map`(.grd)・`extract_cross_section`(1D/2D)・`bond_path_min_density`(伝導パス) | REQ-027/028/029 | 🔵 |
| `mem/spot.py` | `run_mem_spot`(sequential Frame 指定スポット解析・全フレーム反復しない) | REQ-032/405/FR-606 | 🔵 |
| `mcp/mem.py` 実体化 | `run_mem_boundary` を MEMBackend 委譲へ接続 (placeholder=True 契約維持・未導入→error dict) | REQ-033/034/104/EDGE-006/013 | 🔵 |
| `oed/proposal.py` | `OEDProposal`・`propose_measurements`(僅差競合時の判別測定提案・情報利得順・非破壊 ledger 記録)・`proposals_to_json` | REQ-035/037/038/304/EDGE-010 | 🔵 |
| `oed/pyboed.py` | `acquire`(PyBOED 獲得関数接続境界・遅延 import・未導入時 `OEDUnavailableError`・v1 は提案生成のみ) | REQ-036/105/EDGE-011 | 🔵 |

### 再利用する M0〜M4 資産 🔵

- `EvidenceBackend` Protocol / `EvidenceResult`(**logz_err フィールド既存・M0 定義**) — laplace/nested の宿主
- `BICBackend` / `evidence.ranking.rank`(**close_competitor=nested 再裁定 + OED 発動の単一情報源**) — 階層的裁定の一次段
- `RefinementMetrics` / `RefinementResult` — Laplace/nested のフォールバック入力・joint 集約から MEM F_obs 抽出
- `JointVerificationResult` / `JointRefinementResult` — MEM 入力元 (F_obs 抽出)・適用ガード判定入力
- `SnapshotStore`(**追記型・save/revert のみ**) — MEM-Rietveld 反復の子スナップショット追記先 (P2)
- `Ledger`(**append/verify・ハッシュチェーン**) — nested 裁定振り分け・MEM サイクル・OED 提案の理由付き記録
- `FrameSeries` — MEM フレームスポット解析のフレーム指定元 (`frame_index`)
- `AnalysisSession` / `run_mem_boundary`(**M4 プレースホルダ**) — run_mem 実体化の接続点 (placeholder 契約維持)
- `MEMUnavailableError`(**M4 定義済**) — Dysnomia 未導入時の縮退先
- `_json.finite_or_none` — nested logZ・MEM 密度統計・OED 情報利得の非有限純化 (MCP 応答安全化)
- `backends.base.param_name`/`parse_param`(`"global.{key}"` 対応) — nested 事前分布パラメータ命名

## 主要設計決定

### D1: EvidenceBackend Protocol は不変・`EvidenceProblem` + `score_problem` で拡張 🔵

**問題**: `EvidenceBackend.score(metrics: RefinementMetrics)` の狭いシグネチャでは、nested/laplace が必要と
する尤度評価関数・パラメータ空間 (事前分布)・MAP/Hessian を渡せない。

**確定**: 既存 `EvidenceBackend` Protocol と `bic`/`aic` の `score(metrics)` は**一切変更しない**。追加入力を
補助 frozen dataclass `EvidenceProblem`(metrics + `log_likelihood` + `priors` + `map_point` + `hessian`)
に束ね、別メソッド `score_problem(problem) -> EvidenceResult` を持つ拡張 Protocol
`ProblemAwareEvidenceBackend`(`score` も要求し構造的に `EvidenceBackend` を包含) を新設する。
`LaplaceBackend`/`NestedBackend` はこの拡張 Protocol を実装し、階層的裁定 `arbitrate` はこの型で受ける。

**根拠**: REQ-003/007 は「value 小さいほど良い・rank に混在比較」を要求 (score は不変必須) 🔵。ヘッセ行列/
尤度は evidence 値 (BIC) の意味論と独立の追加入力であり、Protocol 拡張でなく補助 dataclass に束ねるのが
最小侵襲 🔵。`bic`/`aic` は `score_problem` を実装せず既存のまま (後方互換) 🔵。

### D2: nested の value は `-logZ`・logZ 生値は付随情報・種固定は誤差併記 🔵

**確定**: `NestedBackend.score_problem` は `EvidenceResult(backend="nested", value=-logZ, logz_err=誤差)` を
返す。logZ 生値は `NestedOutcome.logz` に付随保持する。`NestedConfig.seed` でサンプラ種を固定し、2 回実行で
logZ が `logz_err` の範囲内で一致する (ビット同一でなく誤差範囲一致, NFR-102 の nested 例外)。

**根拠**: REQ-006/007「value=-logZ 相当 + logz_err」🔵。REQ-009/EDGE-014「種固定・logZ±誤差」🔵。既存
`EvidenceResult.logz_err`(M0 定義済) をそのまま活用する。符号統一 (小さいほど良い) で bic/aic/laplace と
rank 混在比較の一貫性を保つ (CLAUDE.md 不変条件) 🔵。

### D3: 時間上限は `run_with_fallback` で打ち切り→Laplace 代替に縮退 (例外化しない) 🔵

**確定**: nested の 30 分上限 (NFR-103) は `NestedBackend.run_with_fallback` が扱う。`time_limit_sec` 超過や
`NestedUnavailableError` を捕捉し、例外を上げず `NestedOutcome(truncated=True, result=laplace 代替 value,
warnings=[...])` を返す。`arbitrate` はこの縮退値を統合ランキングへ流し解析全体を止めない。

**根拠**: REQ-101/EDGE-002「打ち切り + Laplace 代替 + 警告 (例外化しない)」🔵。CLAUDE.md「失敗は例外でなく
縮退値に変換」🔵。Laplace を代替先とするため `NestedBackend` は `laplace: LaplaceBackend` を保持する。
Laplace を M5 で先に実装する (nested の代替先として必須, note.md) 🔵。

### D4: 階層的裁定は bic 一次 rank → close_competitor 群のみ nested → 統合 🔵

**確定**: `arbitrate` は (1) `rank`(BICBackend) で一次順位・確率・close_competitor を得て (探索段は不変)、
(2) `close_competitor=True`(ΔBIC<10) の群のみ `problems` から `EvidenceProblem` を引き
`nested.run_with_fallback` で value=-logZ を得て evidence を差し替え、(3) 統合ランキングを再構成 (確率再計算)
する。`full_nested=True` なら全生存仮説を nested 対象にする。close_competitor が無い/problems 未供給なら
nested を発動せず bic 一次を最終結果とする (下段スキップ)。

**根拠**: REQ-010/011/012/102/201/EDGE-003/004 🔵。`rank.close_competitor`(close_threshold=10.0) を再裁定
対象判定に再利用 🔵。木探索 `HypothesisTreeSearch` は bic 固定・不変 (REQ-010/201) 🔵。各仮説を bic/nested の
どちらで裁定したかを `ArbitratedHypothesis.adjudicated_by` で明示しレポート・ledger に残す (REQ-013/015)。

### D5: MEM 入力生成は joint 結果から F_obs 抽出・probe で密度種別分岐・決定論反射順 🔵

**確定**: `extract_structure_factors(joint_result)` が joint 集約 `RefinementResult` の精密化済み構造から
F_calc の位相を借り、観測強度由来の |F_obs| と組んで `StructureFactor` を構成する (位相はモデル由来)。
`build_mem_input(joint_result, probe)` が probe で密度種別を分岐する (xray→electron / neutron_*→nuclear)。
反射は (h,k,l) 昇順で固定し同一仮説からビット同一 `MEMInput` を生成する。

**根拠**: REQ-021/022/023 🔵。MEM 入力元は `joint/verification.py::verify_survivors` の
`JointRefinementResult`(note.md) 🔵。決定論反射順は NFR-102 のビット同一要件 🔵。

### D6: MEM-Rietveld 反復は既定オフ・各サイクルは子スナップショット追記 (親不変) 🔵

**確定**: `run_mem_rietveld` は `MEMRietveldConfig.enabled=False`(既定) なら反復せず
`stop_reason="disabled"` を即返す。有効時は MEM 密度→F_calc 更新→再精密化の MPF サイクルを回し、各サイクルの
phases を `SnapshotStore.save(..., label="mem_rietveld_iter{n}")` で**子スナップショットとして追記**する。
削除・上書き API は作らない (P2)。収束 (R/密度変化<tol) or max_iter で停止し停止理由を ledger 記録。発散
(密度負値/R 悪化) は当該サイクルを子スナップショットに残しつつ停止 (`stop_reason="diverged"`, ledger 記録)。

**根拠**: REQ-024/025/026/107/202/NFR-005/EDGE-008/009 🔵。`SnapshotStore` は追記型 (save/revert のみ・
削除 API なし) で親 joint 結果は不変 🔵。発散停止はガードレール思想 (FR-210) から導出 🟡。ロールバックは
revert 経由で破壊しない (REQ-107) 🔵。

### D7: MEM 適用ガードは警告のみ・除外しない (Dara 教訓) 🔵

**確定**: `check_mem_applicability` は joint 済み単相/主相支配的なら `recommended=True` を返す。多相/低統計
でも `MEMApplicabilityReport(recommended=False, warnings=[...])` を返すのみで MEM 実行を中止せず、仮説の
除外・rejected 化を一切行わない。`run_mem_spot` はガード警告を `MEMResult.warnings` に伝播する。

**根拠**: REQ-030/031/103/EDGE-007「警告のみ・除外しない」= M4 ChemPlausibility(FR-412) と同型の最重要
不変条件 (Dara 教訓) 🔵。

### D8: run_mem 実体化は M4 placeholder 契約維持・MEMBackend 委譲・未導入は error dict 🔵

**確定**: `mcp/mem.py::run_mem_boundary` に `mem_backend: MEMBackend | None = None` を末尾追加する。
`placeholder=True` は M4 dict (`{"status":"not_implemented","milestone":"M5","tool":"run_mem"}`) を返す
(後方互換不変)。`mem_backend` 供給時は `build_mem_input`→`mem_backend.run` で密度マップパス・断面・最小密度・
警告を**素の型 dict** で返す (子スナップショット追記のみ・破壊操作なし)。`MEMUnavailableError` を捕捉し
`{"status":"error","error":"mem_unavailable"}` へ変換する。非有限値は `finite_or_none` で純化する。

**根拠**: REQ-033/034/104/EDGE-006/013 🔵。M4 run_mem placeholder 契約 (mcp/mem.py・mcp/tools.py) と整合 🔵。
`export_gpx` の `GSASUnavailableError`→error dict 変換パターン (M4 D10) と対称 🔵。

### D9: OED 提案は close_competitor 発動・情報利得順・非破壊 (ledger 追記のみ) 🔵

**確定**: `propose_measurements(ranked)` は `rank` の `close_competitor`(ΔBIC/ΔlogZ<閾値) が存在するときのみ
判別測定提案 (高統計再測定/追加温度点/joint 用中性子測定/組成分析) を `estimated_information_gain` 降順で
生成する。僅差競合が無ければ空 tuple。仮説の accepted/rejected 化・データ改変を伴わず、ledger 非 None のとき
`oed_proposal` 追記記録のみ。PyBOED 獲得関数 `acquire` は遅延 import 境界 (未導入→`OEDUnavailableError`)。

**根拠**: REQ-035/036/037/038/105/304/EDGE-010/011 🔵。close_competitor を OED 発動条件に再利用 (note.md) 🔵。
非破壊は P2/NFR-101 🔵。v1 は提案生成のみ (獲得関数実行はスコープ外・REQ-036) 🔵。

### D10: final_selection_mode は human で nested/OED/MEM を推奨提示に留める 🔵

**確定**: `arbitrate`/`propose_measurements`/MEM は情報・推奨を生成するのみで accepted 化しない。human
モードでの accepted 化は既存 `FinalSelectionEngine.accept` (M4 の accept_hypothesis 経路) の人間操作でのみ
行われる。M5 の新レイヤは選択裁定の単一経路を新設しない。

**根拠**: REQ-203「human モードでは推奨/情報提示に留まる」= M4 REQ-023 踏襲 🔵。M5 は評価・提案レイヤであり
選択裁定は既存 `FinalSelectionEngine` に委ねる (単一経路維持) 🔵。

## ディレクトリ構造 🔵

```
src/tsumugin/
├── errors.py            # 拡張: NestedUnavailableError / OEDUnavailableError (末尾追加)
├── nested/              # 新規: base(EvidenceProblem/ProblemAwareEvidenceBackend) / laplace /
│                        #        prior / sampler(遅延 import) / arbitration / calibration
├── mem/                 # 新規: base(MEMBackend/MEMResult) / inputgen / dysnomia(遅延 import) /
│                        #        guard / iterate / output / spot
├── oed/                 # 新規: proposal / pyboed(遅延 import)
└── mcp/
    └── mem.py           # 実体化: run_mem_boundary を MEMBackend 委譲へ (placeholder 契約維持)
tests/  test_laplace.py / test_nested_sampler.py (@pytest.mark.nested) / test_nested_prior.py /
        test_arbitration.py / test_calibration.py / test_mem_base.py /
        test_mem_inputgen.py / test_mem_dysnomia.py (@pytest.mark.mem) / test_mem_guard.py /
        test_mem_iterate.py / test_mem_output.py / test_mem_spot.py / test_mcp_mem_impl.py /
        test_oed_proposal.py / test_oed_pyboed.py (@pytest.mark.oed) /
        test_m5_e2e.py / test_m5_symbols_sorted.py
```

## レイヤ構成 (境界 Protocol / 実装 / 遅延 import アダプタ) 🔵

| レイヤ | 内容 | 外部依存 | import 時挙動 |
|---|---|---|---|
| 境界 Protocol | `ProblemAwareEvidenceBackend`・`MEMBackend`・補助 dataclass 群 | なし | コア (numpy) のみで成功 |
| コア実装 | `LaplaceBackend`・`arbitrate`・`calibration`・`inputgen`・`guard`・`iterate`・`output`・`proposal` | なし | コアのみで成功・通常 pytest で網羅 |
| 遅延 import アダプタ | `NestedBackend.score_problem`(dynesty/ultranest)・`DysnomiaBackend.run`(バイナリ)・`acquire`(pyboed) | optional extra | import は成功・**実行時のみ** 未導入で friendly error |

M4 `mcp/server.py` の遅延 import パターン (import 自体は成功、実行時のみ SDK import して未導入なら
Unavailable) をそのまま踏襲する。

## optional extra 戦略 🔵

```toml
# pyproject.toml [project.optional-dependencies] へ追加
nested = ["dynesty>=2.1"]   # or ultranest (REQ-303 で選択可)
mem = []                    # Dysnomia 本体はバイナリ導入 (README 手順)・ラッパ依存があれば列挙
oed = ["pyboed>=..."]       # v1 は提案生成のみ・獲得関数接続のみ依存

# pytest マーカー (M4 @pytest.mark.mcp の前例踏襲)
markers = ["nested", "mem", "oed"]
```

- **コア import (`import tsumugin`) は numpy のみで成功** (REQ-403/TC-514-04)。nested/mem/oed の実処理層
  (laplace/arbitration/calibration/inputgen/guard/iterate/output/proposal) は SDK/バイナリ非依存で通常
  pytest 網羅 (NFR-002)。
- 実サンプラ (dynesty/ultranest)・実バイナリ (Dysnomia)・PyBOED は `@pytest.mark.{nested,mem,oed}` で分離し
  未導入環境では自動 skip する (contract test は REQ-406/NFR-106 でバージョン固定)。

## CLAUDE.md アーキテクチャ表への追加行案 🔵

CLAUDE.md「アーキテクチャ (実装済み)」表へ以下 3 行を末尾追加する:

| モジュール | 役割 | 仕様 |
|---|---|---|
| `tsumugin.nested` | Laplace/nested evidence(EvidenceProblem 経由・logZ±誤差・種固定) + 階層的裁定(bic 一次+競合のみ nested) + 確率較正(reliability/ECE, bic/nested 別系列) | FR-121/122/124/125 |
| `tsumugin.mem` | MEMBackend 境界 + Dysnomia 連携(遅延 import) + F_obs 抽出/MEM 入力生成(probe→密度種別) + MEM-Rietveld 反復(既定オフ・子スナップショット) + 密度出力/断面/ボンド経路 + 適用ガード(警告のみ) + フレームスポット | FR-600〜606 |
| `tsumugin.oed` | 測定フィードバック提案(僅差競合時の判別測定を情報利得順・非破壊) + PyBOED 獲得関数接続境界(v1 提案のみ) | FR-430/431/432 |

## 非機能要件の実現方法

- **NFR-001/REQ-101/405 (nested 時間上限)**: `NestedBackend.run_with_fallback` が 30 分上限を守り超過時は
  Laplace 代替へ縮退。MEM スポットは spot 単位で完結 (全フレーム反復しない) 🔵
- **NFR-102 決定論 (REQ-402)**: nested はサンプラ種固定 + logZ±誤差 (ビット同一でなく誤差範囲一致)。MEM 入力
  生成 (反射 (h,k,l) 昇順)・OED 提案 (利得降順+kind 昇順)・較正 (ビン下端昇順・backend 昇順) はビット同一 🔵
- **NFR-105/REQ-401 (P2)**: nested 裁定振り分け・MEM 反復サイクル・OED 提案は ledger 追記のみ。MEM 反復は
  子スナップショット追記 (削除/上書き API なし)。`ledger.verify()` は常時 True 🔵
- **NFR-004 (較正明示)**: `CalibrationReport.backend` + `probability_semantics` で bic/nested を別系列・確率の
  意味 (BIC 近似 vs logZ) を明記 🔵
- **REQ-031/103 (除外しない)**: MEM 適用ガードは warnings のみで仮説除外しない (Dara 教訓) 🔵

## 技術的制約 🔵

- **コア依存 numpy のみ (REQ-403)**: nested/mem/oed の外部依存 (dynesty/ultranest/dysnomia/pyboed) は全て
  optional extra + 遅延 import + friendly error。`import tsumugin` は追加依存なしで成功 (TC-514-04)
- **後方互換 (REQ-404)**: 新規 dataclass/例外/Protocol は既定値付き非破壊追加。`EvidenceBackend`・
  `EvidenceResult`・`run_mem_boundary`(placeholder 契約) は不変。公開 `__all__` は末尾追加 + 昇順維持
  (test_m5_symbols_sorted, TC-514-05)
- **evidence セマンティクス統一**: value は小さいほど良い (bic/aic/laplace/nested 全て)。nested は -logZ 相当。
  BIC 比較の一貫性を保つ
- **バージョン固定 + contract test (REQ-406/NFR-106)**: Dysnomia/dynesty/ultranest/pyboed はバージョン固定。
  Dysnomia は入出力ファイル契約を固定した contract test を用意 (実バイナリ導入時に凍結)

## 関連文書

- [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) / [design-interview.md](design-interview.md) /
  [要件定義](../../spec/m5-nested-mem-oed/requirements.md)
- DB スキーマ / HTTP API 仕様: なし (M5 は既存 ledger/snapshot 永続化を流用・新規永続 DB なし) 🔵

## 信頼性レベルサマリー

- 🔵: 主要判断 (D1〜D10)・レイヤ/extra 戦略は要件・M0〜M4 実装に依拠 / 🟡: nested の内部数値 (n_live)・MEM の
  MPF/F_obs 抽出詳細・Dysnomia 入出力契約は実装/合成ベンチで凍結 / 🔴: 0 — **品質評価**: 高品質
