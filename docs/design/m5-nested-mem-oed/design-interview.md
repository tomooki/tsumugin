# m5-nested-mem-oed 設計ヒアリング記録

**作成日**: 2026-07-04
**実施形態**: 自律実行モード — 質問は行わず、要件定義書・仕様書・M0〜M4 実装・推奨案で確定。

## 自律確定した設計判断

### D-Q1: EvidenceBackend Protocol の拡張方式 (score(metrics) の狭さをどう克服するか)
**確定**: 既存 `EvidenceBackend` Protocol と `bic`/`aic` の `score(metrics: RefinementMetrics)` は**一切変更
しない**。nested/laplace が必要とする尤度評価関数・事前分布・MAP/Hessian を補助 frozen dataclass
`EvidenceProblem` に束ね、別メソッド `score_problem(problem) -> EvidenceResult` を持つ拡張 Protocol
`ProblemAwareEvidenceBackend`(`score` も要求し `EvidenceBackend` を構造的に包含) を新設する。
`LaplaceBackend`/`NestedBackend` のみがこれを実装し、階層的裁定 `arbitrate` はこの拡張型で受ける。
**根拠**: REQ-003/007「value 小さいほど良い・rank に混在比較」は score(metrics) 不変を要求 🔵。尤度/Hessian は
evidence 値 (BIC) の意味論と直交する追加入力であり、Protocol シグネチャ拡張でなく補助 dataclass に束ねるのが
最小侵襲 🔵。bic/aic は score_problem を実装せず既存のまま (後方互換・REQ-404) 🔵。requirements.md の「別
メソッド or 補助 dataclass 経由で拡張」指示を両採用した形。

### D-Q2: nested の value 符号規約と logZ の持ち方
**確定**: `NestedBackend.score_problem` は `EvidenceResult(backend="nested", value=-logZ, logz_err=誤差)` を
返す。logZ 生値は `NestedOutcome.logz` に付随保持する。既存 `EvidenceResult.logz_err`(M0 定義済) を活用。
**根拠**: REQ-006/007「value=-logZ 相当 + logz_err、logZ 生値は付随情報」🔵。符号統一 (小さいほど良い) で
bic/aic/laplace と rank 混在比較の一貫性を保つ (CLAUDE.md 不変条件・BIC 比較の一貫性) 🔵。

### D-Q3: nested 再現性 (種固定だがビット同一にできない)
**確定**: `NestedConfig.seed` でサンプラ種を固定し、2 回実行で logZ が `logz_err` の範囲内で一致することを
再現性の定義とする (ビット同一でなく誤差範囲一致)。テストは「誤差範囲内で一致」を検証する (TC-502-04)。
**根拠**: NFR-102 の nested 例外・REQ-009/EDGE-014「サンプラの確率性を logz_err で明示」🔵。MEM 入力生成・OED
提案・較正は決定論 (順序固定) でビット同一を保つ (nested のみ例外) 🔵。

### D-Q4: nested 時間上限フォールバック機構 (打ち切りをどう縮退させるか)
**確定**: 30 分上限 (NFR-103) は `NestedBackend.run_with_fallback` が扱う。`time_limit_sec` 超過や
`NestedUnavailableError` を捕捉し、例外を上げず `NestedOutcome(truncated=True, result=Laplace 代替 value,
warnings=[...])` を返す。`arbitrate` はこの縮退値を統合ランキングへ流し解析全体を止めない。代替先の
`LaplaceBackend` を `NestedBackend` が保持する。
**根拠**: REQ-101/EDGE-002「打ち切り + Laplace 代替 + 警告、例外化しない」🔵。CLAUDE.md「失敗は例外でなく
縮退値に変換しガードレールに処理させる」🔵。Laplace を M5 で先に実装する必要 (nested の代替先として必須,
note.md 開発時注意点) 🔵。

### D-Q5: nested 事前分布の構成方式 (restraint 自動構成 + 手動上書き)
**確定**: `build_prior_from_restraints(free_params, restraints, *, overrides)` が各 free_param に restraint
由来の区間/中心から `PriorSpec`(uniform/truncated_normal) を自動構成する。restraint 未指定は種別ごとの既定
区間 (格子=±数%, 占有率=[0,1]) を割り当てる。`overrides` で param_name→PriorSpec を手動置換できる。返す
tuple は param_name 昇順で nested 次元順を固定する。`PriorSpec.transform` が単位超立方体 → 物理量の逆 CDF。
**根拠**: REQ-008/301/FR-125「事前分布は restraint から自動構成、手動オブジェクトで完全上書き可」🔵。既存
free_params 命名 ("phase{i}.{key}"/"global.{key}") と整合 🔵。§15-5「事前分布自動構成は M5 で失敗モード検証の
上で確定」は残課題として実装時に凍結 🟡。

### D-Q6: 階層的裁定の配線 (探索段を nested 化しない 2 段構え)
**確定**: `arbitrate` は (1) `rank`(BICBackend) で一次順位・close_competitor を得て (木探索は bic 固定・不変)、
(2) close_competitor 群のみ `problems` から `EvidenceProblem` を引き `nested.run_with_fallback` で value=-logZ
を得て evidence を差し替え、(3) 統合ランキングを再構成する。`full_nested=True` で全生存仮説を nested 対象に。
close_competitor が無い/problems・nested 未供給なら bic 一次を最終結果とする (下段スキップ)。各仮説の裁定
backend を `ArbitratedHypothesis.adjudicated_by` で明示する。
**根拠**: REQ-010/011/012/102/201/EDGE-003/004 🔵。`rank.close_competitor`(close_threshold=10.0) を再裁定
対象判定に再利用 (note.md) 🔵。木探索 `HypothesisTreeSearch` は bic 固定 (REQ-010/201) 🔵。

### D-Q7: 較正評価の系列分離 (bic と nested を別々に評価)
**確定**: `CalibrationSample` に `backend` フィールドを持たせ、`calibrate_by_backend` が backend でグルーピング
して各系列に `CalibrationReport`(reliability 曲線 + ECE) を生成する。返す tuple は backend 名昇順。
`CalibrationReport.probability_semantics` で確率の意味 (BIC 近似 vs logZ) を明記する。
**根拠**: REQ-016/106/EDGE-012「bic と nested の reliability/ECE を別系列出力」🔵。NFR-004「backend 名と確率
意味の違いをレポート明記」🔵。ビン下端昇順・backend 昇順で決定論化 (REQ-402) 🔵。

### D-Q8: MEM 入力の F_obs 抽出方式 (位相はモデル由来・決定論反射順)
**確定**: `extract_structure_factors(joint_result)` が joint 集約 `RefinementResult` の精密化済み構造から
F_calc の位相を借り、観測強度由来の |F_obs| と組んで `StructureFactor` を構成する (位相=モデル由来)。反射は
(h,k,l) 昇順で固定し同一仮説からビット同一。`build_mem_input(joint_result, probe)` が probe で密度種別を
分岐する (xray→electron / neutron_*→nuclear)。
**根拠**: REQ-021/022/023 🔵。MEM 入力元は `joint/verification.py::verify_survivors` の
`JointRefinementResult` (note.md) 🔵。決定論反射順は NFR-102 のビット同一要件 🔵。F_obs 抽出の GSAS-II 由来
詳細 (実際の反射リスト取得) は実装時に確定 🟡。

### D-Q9: MEM 反復のスナップショット構造 (子スナップショット追記・親不変)
**確定**: `run_mem_rietveld` は `MEMRietveldConfig.enabled=False`(既定) なら反復せず即返す。有効時は MPF
サイクルを回し各サイクルの phases を `SnapshotStore.save(..., label="mem_rietveld_iter{n}")` で**子スナップ
ショット追記**する。`MEMRietveldCycle.snapshot_id` にその ID を保持。削除/上書き API は作らない。収束/max_iter/
発散で停止し停止理由を ledger 記録。発散は当該サイクルを子に残しつつ停止 (`stop_reason="diverged"`)。
**根拠**: REQ-024/025/026/107/202/NFR-005/EDGE-008/009 🔵。`SnapshotStore` は追記型 (save/revert のみ)・親
不変 🔵。発散停止はガードレール思想 (FR-210) から導出・ロールバックは revert 経由で破壊しない 🟡。

### D-Q10: MEM 適用ガードの性質 (警告のみ・除外しない)
**確定**: `check_mem_applicability` は joint 済み単相/主相支配的なら `recommended=True`。多相/低統計でも
`MEMApplicabilityReport(recommended=False, warnings=[...])` を返すのみで MEM 実行を中止せず、仮説の除外・
rejected 化を一切行わない。`run_mem_spot` はガード警告を `MEMResult.warnings` に伝播する。
**根拠**: REQ-030/031/103/EDGE-007「警告のみ・除外しない」= M4 ChemPlausibility(FR-412) と同型の最重要不変
条件 (Dara 教訓) 🔵。

### D-Q11: run_mem 実体化の後方互換 (M4 placeholder 契約維持)
**確定**: `mcp/mem.py::run_mem_boundary` に `mem_backend: MEMBackend | None = None` を末尾追加する。
`placeholder=True` は M4 dict (`{"status":"not_implemented","milestone":"M5","tool":"run_mem"}`) を返す
(契約不変)。`mem_backend` 供給時は `build_mem_input`→`mem_backend.run` で素の型 dict を返す (子スナップショット
追記のみ・破壊操作なし)。`MEMUnavailableError` を捕捉し `{"status":"error","error":"mem_unavailable"}` へ
変換。非有限値は `finite_or_none` で純化する。
**根拠**: REQ-033/034/104/EDGE-006/013 🔵。M4 run_mem placeholder 契約 (mcp/mem.py・mcp/tools.py) と整合 🔵。
`export_gpx` の GSASUnavailableError→error dict 変換 (M4 D10) と対称 🔵。

### D-Q12: optional extra 境界の置き方 (nested/mem/oed をどこで切るか)
**確定**: 遅延 import 境界は「実サンプラ/実バイナリ/獲得関数を起動する/しない」に置く。`NestedBackend.
score_problem`(dynesty/ultranest)・`DysnomiaBackend.run`(バイナリ)・`acquire`(pyboed) のみが実行時に外部を
import し未導入なら friendly error。laplace/arbitration/calibration/inputgen/guard/iterate/output/proposal は
コア (numpy) のみで通常 pytest 網羅。`import tsumugin` は追加依存なしで成功。
**根拠**: REQ-403/NFR-002 「コア import は numpy のみ・境界/入力生成/提案/較正は外部依存なしで網羅」🔵。M4
`mcp/server.py` の遅延 import パターン (import は成功・実行時のみ SDK import) を踏襲 🔵。3 extra + 3 friendly
error は「available + 専用例外」パターン (GSAS/WebUI/MCP/MEM Unavailable) の水平展開 🔵。

### D-Q13: OED 提案の発動条件と非破壊性
**確定**: `propose_measurements(ranked)` は `rank` の close_competitor(ΔBIC/ΔlogZ<閾値) が存在するときのみ
判別測定提案を `estimated_information_gain` 降順で生成する。僅差競合が無ければ空 tuple。仮説の accepted/
rejected 化・データ改変を伴わず ledger 追記記録のみ。`acquire`(PyBOED) は遅延 import 境界 (v1 は提案生成のみ)。
**根拠**: REQ-035/036/037/038/105/304/EDGE-010/011 🔵。close_competitor を OED 発動条件に再利用 (note.md) 🔵。
非破壊は P2/NFR-101 🔵。

### D-Q14: final_selection_mode 整合 (human で推奨提示に留める)
**確定**: `arbitrate`/`propose_measurements`/MEM は情報・推奨を生成するのみで accepted 化しない。human モード
での accepted 化は既存 `FinalSelectionEngine.accept` (M4 accept_hypothesis 経路) の人間操作でのみ行う。M5 は
選択裁定の新経路を新設しない。
**根拠**: REQ-203「human モードでは推奨/情報提示に留まる」= M4 REQ-023 踏襲 🔵。選択裁定は既存
`FinalSelectionEngine` の単一経路に委ねる 🔵。

## 残課題 (実装時確定)

- nested 事前分布の既定区間 (格子 ±%・占有率既定) と `n_live`/`max_calls` は合成ベンチ/失敗モード検証で凍結
  (§15-5 の M5 実装時課題)
- nested の value=-logZ 具体式・logz_err の取得方法は dynesty/ultranest の API に合わせて実装時確定
- Laplace の Hessian 取得元 (GSAS-II 共分散行列 or 数値微分) と特異判定閾値は実装時確定
- MEM の F_obs 抽出 (GSAS-II からの反射リスト/構造因子取得)・MPF 反復の F_calc 更新式は実装時確定
- Dysnomia 入出力ファイル契約は実バイナリで contract test 確立時に固定 (NFR-106)
- OED の `estimated_information_gain` 簡易近似式 (v1) は提案種別ごとに実装時確定 (REQ-304)
- ΔBIC 再裁定閾値・温度較正値は較正ベンチ (§12-5) で数値較正。M5 はテストで既定値 (close_threshold=10.0,
  temperature=1.0) を凍結
- dynesty/ultranest/pyboed のバージョン範囲は導入時に固定 (REQ-406/NFR-106)

## 信頼性レベル分布 (設計文書全体)

- 🔵: 約 70% / 🟡: 約 30% (nested 内部数値・MEM の MPF/F_obs 抽出詳細・Dysnomia 契約・OED 利得近似に集中) / 🔴: 0 件

## 関連文書

- [architecture.md](architecture.md) / [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) /
  [要件定義](../../spec/m5-nested-mem-oed/requirements.md)
