# m4-joint-mcp 設計ヒアリング記録

**作成日**: 2026-07-04
**実施形態**: 自律実行モード — 質問は行わず、要件定義書・仕様書・M0〜M3 実装・推奨案で確定。

## 自律確定した設計判断

### D-Q1: 新規モジュール分割方針 (joint / chem / mcp を分ける粒度)
**確定**: 3 レイヤを独立サブパッケージに分ける。`joint/`(model/engine/weights/contrast/verification)・
`chem/`(base/rules/compose/ranking)・`mcp/`(tools/server/mem)。データモデル拡張は既存
`model/project.py`・`model/phase.py` の末尾追加とし新パッケージを増やさない。
**根拠**: M3 の `multistart/`・`operando/`・`absorption/` が「機能=1 パッケージ」で分かれた実績に倣う 🔵。
joint と chem と mcp は依存方向が独立 (mcp が joint/chem を委譲するのみ) でパッケージ境界が自然 🔵。

### D-Q2: joint 結果集約フィールドの持ち方
**確定**: `refine_joint` は**単一 `RefinementResult` を返す** (共有構造 phases・Σχ²・結合 Rwp)。
ヒスト別 Rwp/scale は既存 `RefinementResult.globals`("hist0.rwp" 等) と `warnings`(σ 由来明示) に格納。
型付き詳細が要る呼び出し側には `refine_joint_detailed` が `JointRefinementResult`(集約 + `PerHistogramMetrics`
タプル) を返す。
**根拠**: REQ-006 は「単一 RefinementResult に集約」を明記 🔵。M3 で `globals`/`warnings` を導入済みで
そのまま流用でき、既存 rank/evidence/BIC 経路 (単一 RefinementResult/RefinementMetrics 前提) を壊さない 🔵。
型付き詳細を別ラッパにすることで既存経路互換と豊かな詳細を両立 🟡。

### D-Q3: SimulatedBackend joint の合算アルゴリズム
**確定**: 各ヒストをヒスト独立 free で `backend.refine` → χ² 合算。共有構造 (格子等) は χ² 和を目的関数と
する簡易ブロック座標降下で 1 パラメータずつ更新する。v1 既定は「共有構造を共有初期値で固定し
scale/独立分のみ各ヒスト精密化 → χ² 合算」の軽量近似を採り、共有格子解放は段階的に足す。
**根拠**: REQ-005 は Simulated では「ヒストごと χ² の合算で検証可能」を要件化 (🟡 明記) 🔵。真値回収
(TC-402-02) は 2 ヒスト合成データで足り、フル同時最適化はコスト過大。NFR-001(<30 秒) を満たす 🟡。
共有格子の同時解放は実装タスクで合成ベンチにより凍結 (残課題)。

### D-Q4: 1 ヒスト失敗時の集約セマンティクス
**確定**: 当該ヒストの chi2=inf をそのまま集約 χ²(Σ) に加算 → 集約 chi2=inf。例外は投げず warnings に
失敗ヒスト index を明示し、ガードレール/降格に処理させる。
**根拠**: CLAUDE.md 不変条件「失敗は例外でなく chi2=inf」+ REQ-007/EDGE-001 🔵。M1 木探索の
`_FiniteGuardedEvidence` が全 inf softmax を吸収するため rank も安全 🔵。

### D-Q5: コントラスト閾値の既定と正規化差の定義
**確定**: `|f_norm − b_norm| >= 0.15` を既定閾値とし `ContrastConfig` で設定化。f は Z 近似
(`XRAY_Z_TABLE`)、b は元素代表値静的テーブル (`NEUTRON_B_TABLE`, fm)。サイトの占有元素対 (A,B) で
`f_norm=f_A/(f_A+f_B)`、`b_norm=b_A/(|b_A|+|b_B|)` (b は負値を取りうるため絶対値正規化)。
**根拠**: FR-244 は「散乱コントラストが十分なサイトを自動検出」のみ規定し閾値は未定 🔵。中性子 b が
元素で符号反転する物理 (例 H は負) を絶対値正規化で扱う 🟡。閾値 0.15 は木探索 `match_tol` 等と同様に
設定へ逃がし合成ベンチで凍結 (残課題)。

### D-Q6: ChemPlausibility 降格の rank 配線点 (rank 前段 vs 後段)
**確定**: 素の `evidence.ranking.rank` で確率 p を得た**後段**で、相スコア s∈[0,1] を `p' = p·s` として
確率補正し再正規化・並べ替える。候補集合の除去・rejected 化は一切しない。
**根拠**: REQ-019 最重要不変条件「降格のみ・除外しない、低スコア相も rank から消えない」🔵。evidence
値 (BIC) 自体を歪めると BIC 比較の一貫性 (CLAUDE.md) を壊すため、evidence は不変にして確率だけ補正する
のが最小侵襲 🟡。モジュール未登録なら素通し (REQ-105) は「後段補正をスキップ」で自然に満たせる 🔵。

### D-Q7: PhaseRef を PhaseInstance に足すか別型にするか
**確定**: `PhaseInstance.phase_ref: str` は不変。別値オブジェクト `PhaseRef(id, formula, element_system)` を
新設し `from_phase_ref` で橋渡し。PhaseInstance へフィールド追加しない。
**根拠**: REQ-020 は「PhaseInstance.phase_ref: str と整合」を要求するが型追加は指定せず 🔵。PhaseInstance
はホットパス (精密化/serialization/CSV) を多数持ち、フィールド追加は往復対称テストや列レイアウトへ波及する。
疎結合の別型なら ChemPlausibility 境界に閉じ影響最小 🟡。

### D-Q8: MCP 2 層の分割点 (どこで SDK 依存を切るか)
**確定**: 分割点は「MCP プロトコル (JSON-RPC/ツールスキーマ) を知る/知らない」。`mcp/tools.py` は
`AnalysisSession` を第 1 引数に取るプレーン関数群で SDK を import しない (通常 pytest で網羅)。
`mcp/server.py` が SDK を遅延 import し各ツールを配線する薄いアダプタ。
**根拠**: REQ-022/NFR-003 が「実処理は SDK 非依存・アダプタは薄い」を要件化 🔵。M1 `webui`(create_app/serve
の遅延 import + WebUIUnavailableError) の実績パターンをそのまま踏襲 🔵。決定論 (REQ-402) のためツール応答は
`_json.finite_or_none` で非有限を漏らさない 🔵。

### D-Q9: run_mem 境界の返し方 (例外 vs プレースホルダ)
**確定**: 既定は `MEMUnavailableError`("M5 で提供予定") 送出。`placeholder=True` でスキーマ将来互換の
`{"status": "not_implemented", "milestone": "M5"}` dict も返せる。いずれも状態変更・破壊的追記なし。
**根拠**: REQ-101/EDGE-008 は「明示エラー (NotImplementedError 相当) or プレースホルダ、破壊的操作なし」
の両許容 🔵。既定を明示エラーにするのは `MuCalculator`/`BiologicMprLoader` の NotImplementedError 境界
(M3) と一貫 🔵。専用例外 `MEMUnavailableError` は `GSASUnavailableError`/`WebUIUnavailableError` と対称 🔵。

### D-Q10: MCP トランスポートの既定
**確定**: 既定は stdio (`serve_stdio`)。任意で `127.0.0.1` ローカルバインド (`serve_local`)。ネットワーク
無認証公開はしない。
**根拠**: REQ-303/405/P2「既定ローカル・無認証ネットワーク公開しない」🔵。Review Queue Web UI の
既定 127.0.0.1 バインド方針と一貫 🔵。

### D-Q11: TofBankParams のシリアライズ拡張
**確定**: `store/serialization.py` に `bank_params_to_dict`/`_from_dict` を往復対称で追加。既存
`phase_to_dict`/`phase_from_dict` は不変。HistogramRef 自体の永続化は M4 スコープ外だが、TofBankParams
単体の往復対称は TC-401-04 のため実装する。
**根拠**: REQ-404 非破壊追加 + TC-401-04「TofBankParams シリアライズが往復対称」🔵。phase_* の既存 15
テストを壊さないため別関数で足す 🔵。

## 残課題 (実装時確定)

- コントラスト閾値 0.15 / SimulatedBackend joint の共有格子同時解放アルゴリズムは合成ベンチのテストで凍結
- `NEUTRON_B_TABLE` / `XRAY_Z_TABLE` の同梱元素範囲 (v1 は主要 ~40 元素で足るか) は実装時に確定
- GSASIIBackend の joint ネイティブ本配線 (v1 は @gsas smoke の接続点のみ、TC-409-02) は実装タスクで拡充
- `mcp` SDK のバージョン範囲 (`mcp>=1.0`) は導入時に固定
- ChemPlausibility 合成の重み (`weights` 未指定時の等重み) は v1 既定。将来モジュール毎重みは接続時

## 信頼性レベル分布 (設計文書全体)

- 🔵: 約 66% / 🟡: 約 34% / 🔴: 0 件

## 関連文書

- [architecture.md](architecture.md) / [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) /
  [要件定義](../../spec/m4-joint-mcp/requirements.md)
