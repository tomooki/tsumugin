# m4-joint-mcp アーキテクチャ設計

**作成日**: 2026-07-04
**関連要件定義**: [requirements.md](../../spec/m4-joint-mcp/requirements.md) / [acceptance-criteria.md](../../spec/m4-joint-mcp/acceptance-criteria.md)
**ヒアリング記録**: [design-interview.md](design-interview.md)

**【信頼性レベル凡例】**: 🔵 要件・仕様・M0〜M3 実装に依拠 / 🟡 妥当な推測で確定 / 🔴 根拠なし推測

---

## システム概要 🔵

M0〜M3 の抽象境界 (`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore` /
`HypothesisTreeSearch` / `FinalSelectionEngine` / `Trajectory` / `export_gpx` /
`analyze_single_pattern`) の上に、**3 つの独立した新レイヤ**を非破壊で載せる:

1. **joint 精密化レイヤ** (`joint/`) — 構造共有・ヒスト独立の `JointRefinementModel` を組み、
   GSASIIBackend ではネイティブのマルチヒストグラム経路、SimulatedBackend ではヒストごと χ²
   合算で joint 精密化する。結果は各ヒストの Rwp/scale と共有構造 (±σ) を単一 `RefinementResult`
   へ集約する (FR-242/243)。X 線 f と中性子 b の正規化差でコントラスト十分サイトを検出し、
   joint データがある場合のみ占有率解放を提案する (FR-244)。
2. **ChemPlausibility レイヤ** (`chem/`) — `score(PhaseRef, SynthesisContext) -> PlausibilityResult`
   の Protocol 境界と v1 最小ルール、複数モジュールの重み付き幾何平均合成、そして **降格のみ・
   除外しない** rank 配線 (FR-412)。
3. **MCP Server レイヤ** (`mcp/`) — SDK 非依存の「ツール実処理関数」層 (8 ツールが M0〜M3 資産へ委譲)
   + SDK 依存の薄いアダプタ層。`run_mem` は M5 委譲プレースホルダ (FR-513)。

探索段は不変 (FR-245): 木探索は既存 `HypothesisTreeSearch` をプライマリヒストグラム 1 本で実行し、
生存仮説の**検証精密化のみ** joint に載せる。

## アーキテクチャパターン 🔵

- **パターン**: M0〜M3 と同一 (不変データ + Protocol 境界 + 追記専用ストア + 純関数コア)
- **選択理由**: joint はヒストごとの独立精密化を合算する構成で M3 マルチスタートの純関数構成と同型。
  ChemPlausibility は `MuCalculator` / `RefinementBackend` と同じ Protocol 交換境界。MCP の 2 層分離は
  M1 の `webui` (optional extra `web` + `WebUIUnavailableError` 縮退) の実績パターンを踏襲する 🔵

## コンポーネント構成

### 新規モジュール

| モジュール | 役割 | 要件 | 信頼性 |
|---|---|---|---|
| `model/project.py` 拡張 | `TofBankParams`(DIFC/DIFA/ZERO) 新設 + `HistogramRef.bank_params` 末尾追加 | REQ-001/002/003 | 🔵 |
| `model/phase.py` 拡張 | `PhaseRef`(id + 組成/元素系ヒント) 新設 (`PhaseInstance.phase_ref: str` と整合) | REQ-020 | 🟡 |
| `joint/model.py` | `JointHistogram`(1 ヒスト入力: 2θ/I/w/weight/probe)・`JointRefinementModel`(共有 free + ヒスト独立 free)・`JointRefinementResult` | REQ-004/006 | 🔵 |
| `joint/engine.py` | `refine_joint`: GSASII=ネイティブ / Simulated=χ² 合算 → 集約 `RefinementResult`。1 ヒスト失敗→chi2=inf | REQ-005/007/EDGE-001 | 🔵 (Simulated 合算 🟡) |
| `joint/weights.py` | `HistogramWeighting`(統計/経験)。σ 由来をレポートに明示 | REQ-008/009/301 | 🔵 |
| `joint/contrast.py` | 中性子散乱長 `NEUTRON_B_TABLE`(元素→fm)・X 線 f(Z 近似)・`recommend_occupancy_release`(|f_norm−b_norm| 閾値) | REQ-010/011/012/103/104 | 🔵 (b 表 🟡) |
| `joint/verification.py` | 生存仮説を joint 検証精密化する `verify_survivors`(探索段は不変) | REQ-013/014/202 | 🔵 |
| `chem/base.py` | `ChemPlausibility` Protocol・`PlausibilityResult`・`SynthesisContext` | REQ-015/016 | 🔵 |
| `chem/rules.py` | v1 最小ルール `AlkaliMetalInAirRule`(大気下単体アルカリ金属を降格) | REQ-017 | 🔵 |
| `chem/compose.py` | 複数モジュールの重み付き幾何平均合成 `combine_plausibility` | REQ-018/EDGE-007 | 🔵 |
| `chem/ranking.py` | `rank_with_plausibility`: 素の rank へ降格を配線 (**除外しない**) | REQ-019/105/EDGE-005/006 | 🔵 |
| `mcp/tools.py` | SDK 非依存の 8 ツール実処理関数群 (M0〜M3 資産へ委譲)。`AnalysisSession` で状態束ね | REQ-021/022/023/024/025 | 🔵 |
| `mcp/server.py` | SDK 依存の薄いアダプタ。未導入時 `MCPUnavailableError` 縮退。ローカルバインド | REQ-021/102/303/405 | 🔵 |
| `mcp/mem.py` | `run_mem` の M5 委譲境界 (`MEMUnavailableError` 相当・破壊的操作なし) | REQ-101/EDGE-008 | 🔵 |
| `errors.py` 拡張 | `MCPUnavailableError` / `MEMUnavailableError` を末尾追加 (`WebUIUnavailableError` と対称) | REQ-102/101 | 🔵 |
| `store/serialization.py` 拡張 | `bank_params_to_dict`/`_from_dict` を往復対称で追加 (`phase_*_dict` は不変) | REQ-404/TC-401-04 | 🟡 |

### 再利用する M0〜M3 資産 🔵

- `HypothesisTreeSearch` / `SearchResult` — FR-245 プライマリ探索。**joint 化しない** (探索段不変)
- `SimulatedBackend` / `GSASIIBackend.refine` — joint の各ヒスト精密化の宿主
- `BICBackend` / `evidence.ranking.rank` — joint 後の仮説比較。ChemPlausibility 降格の**前段**に配線
- `FinalSelectionEngine.accept/revert/set_mode/mode` — MCP `accept_hypothesis`/`revert` の委譲先 (P2 準拠)
- `Trajectory` — MCP `get_trajectory` の委譲先 / `export_gpx` — MCP `export_gpx` の委譲先
- `analyze_single_pattern` — MCP `submit_analysis` の単一パターン委譲先
- `Ledger` / `SnapshotStore` (+Persistent) — joint 昇格・コントラスト提案・降格・MCP 全操作の記録
- `_json.finite_or_none` — MCP 応答シリアライズの非有限純化 / `param_name`/`parse_param`(`global.*`) — 占有率解放命名

## 主要設計決定

### D1: joint 結果集約は専用 `JointRefinementResult` + 集約 `RefinementResult` の二段持ち 🔵/🟡
`refine_joint` は最終的に**単一 `RefinementResult` を返す** (REQ-006、既存 rank/evidence 経路と互換)。
共有構造 phases (±σ は `LatticeParams.sigma`) を `RefinementResult.phases` に、ヒスト別 Rwp/scale/σ 由来
警告を `RefinementResult.globals`(例 `{"hist0.rwp": .., "hist0.scale": ..}`) と `warnings`(M3 導入済) に格納する
(D-Q2)。加えて、ヒスト別の詳細を型付きで保持したい呼び出し側のために `JointRefinementResult`
(集約 `RefinementResult` + ヒスト別 `PerHistogramMetrics` タプル) を返すラッパ関数 `refine_joint_detailed`
を併設する。集約 chi2 = Σ(ヒスト χ²)、集約 rwp = 全ヒスト結合 Rwp とし BIC 比較のセマンティクスを統一する。

### D2: SimulatedBackend joint は χ² 合算・GSASIIBackend は将来ネイティブ 🔵/🟡
- **SimulatedBackend**: 共有構造 phases を全ヒストで共有し、各ヒストで scale/背景/プロファイルの
  ヒスト独立 free_params を持つ。`refine_joint` は各ヒストを `backend.refine` (ヒスト独立 free で) 呼び、
  共有構造パラメータは全ヒストの χ² 和を目的関数とする外側ループで更新する。v1 は**構造パラメータを
  共有初期値で固定し scale/独立分のみ各ヒスト精密化 → χ² 合算**の軽量近似を既定とし、共有格子解放は
  ヒスト χ² 和の勾配で 1 パラメータずつ更新する簡易ブロック座標降下とする 🟡 (D-Q3)。
- **GSASIIBackend**: v1 は `refine_joint` が GSAS-II の 1 gpx 複数ヒストグラム機能を利用する経路の
  **接続点のみ** (@gsas smoke 1 本、TC-409-02)。本格ネイティブ配線は実装タスクで確定 🟡。

### D3: 1 ヒスト失敗は chi2=inf 変換で joint 全体を止めない 🔵
既存の「失敗は例外でなく chi2=inf の結果」パターンを踏襲。`refine_joint` は各ヒスト精密化を
try せず backend の inf 結果をそのまま受け、当該ヒストの chi2=inf を集約 χ² に加算 → 集約 chi2=inf。
warnings に該当ヒスト index を明示し、ガードレール/降格に処理させる (EDGE-001)。

### D4: コントラスト判定は静的テーブル + 正規化差の閾値 🔵/🟡
中性子コヒーレント散乱長 b (fm) の**元素代表値静的テーブル** `NEUTRON_B_TABLE: Mapping[str, float]` を
`joint/contrast.py` に同梱 (重依存なし)。X 線散乱因子 f は Z 近似 (原子番号) を静的テーブル
`XRAY_Z_TABLE` から引く。サイトの占有元素対 (A,B) について `f_norm = f_A/(f_A+f_B)`、
`b_norm = b_A/(|b_A|+|b_B|)` を計算し、`|f_norm − b_norm| >= contrast_threshold` (既定 0.15 🟡) で
コントラスト十分と判定する (D-Q5)。**joint データがある場合 (ヒスト数 ≥ 2 かつ probe 種別 ≥ 2) のみ**
提案を発火する (REQ-011/104)。閾値未満は空提案・警告なし続行 (REQ-103)。全提案は
`ledger.append("contrast_occupancy_recommend", {...})` で理由付き記録し、**自動適用しない** (REQ-011/012)。

### D5: ChemPlausibility は「降格のみ・除外しない」を rank の**確率補正**として配線 🔵
`chem/ranking.py::rank_with_plausibility` は、まず既存 `evidence.ranking.rank` で素の順位・確率を得て
から、各仮説の相ごとに登録済み ChemPlausibility モジュール群を評価し重み付き幾何平均で相スコアを
合成する。合成スコア s∈[0,1] を仮説の probability へ `p' = p · s` として乗じ再正規化して並べ替える
(D-Q6)。**候補集合からの除去・rejected 化は一切行わない** ため低スコア相も rank に残る (REQ-019/EDGE-005)。
モジュール未登録時は素の rank をそのまま返す (REQ-105/EDGE-006)。合成順序は module id 昇順・相順は
入力順で決定論化する (REQ-402)。

### D6: PhaseRef は軽量値オブジェクト・既存 `phase_ref: str` と橋渡し 🟡
`PhaseInstance.phase_ref: str`(相 ID) は不変のまま。ChemPlausibility.score の第 1 引数用に
`PhaseRef(id: str, formula: str | None, element_system: tuple[str, ...])` を新設し、
`PhaseRef.from_phase_ref(phase_ref: str, *, formula=None, element_system=())` で既存 str から生成する
橋渡しを提供する (REQ-020)。PhaseInstance へのフィールド追加は行わず疎結合を保つ (D-Q7)。

### D7: MCP は SDK 非依存「実処理関数」+ SDK 依存「アダプタ」の 2 層 🔵
- **実処理層 `mcp/tools.py`**: 8 ツールを**プレーン関数**として実装し `AnalysisSession`
  (project/backend/ledger/snapshots/final_selection_engine/最新 SearchResult を束ねた可変でない
  facade) を第 1 引数に取る。M0〜M3 資産へ委譲するのみで `mcp` SDK を import しない → 通常 pytest で網羅
  (NFR-003)。分割点は「MCP プロトコル (JSON-RPC/スキーマ) を知る/知らない」の境界 (D-Q8)。
- **アダプタ層 `mcp/server.py`**: `create_mcp_server()` / `serve_stdio()` が SDK を遅延 import し、
  各ツールを実処理関数へ配線する。`import tsumugin.mcp.server` 自体は SDK 未導入でも成功し、
  `create_mcp_server`/`serve_*` 呼び出し時のみ `MCPUnavailableError` を送出 (`WebUIUnavailableError` と対称、
  REQ-102/EDGE-009)。バインドは既定 stdio、任意で `127.0.0.1` (REQ-303/405)。

### D8: final_selection_mode は MCP でも `FinalSelectionEngine` を単一経路で適用 🔵
`accept_hypothesis` 実処理は `AnalysisSession.selection.mode` を見て、`human` モードで `by="agent"` の
accept 要求が来たら **accepted 化せず推奨提示のみ**返す (REQ-023/106/201/EDGE-010)。mode 切替も
`set_mode` 経由で ledger 記録。`revert` は `FinalSelectionEngine.revert` (superseded 化・追記型) へ委譲する
だけで破壊的操作を新設しない (REQ-024/TC-407-04/09)。

### D9: run_mem は破壊的操作なしの明示エラー境界 🔵
`mcp/mem.py::run_mem(session, **params)` は MEM バックエンド (M5, FR-601〜606) 未実装を示す
`MEMUnavailableError`("M5 で提供予定") を送出する、または `{"status": "not_implemented",
"milestone": "M5", ...}` のプレースホルダ dict を返す (呼び出し側スキーマは将来互換)。いずれも
**状態変更・ledger への破壊的追記を伴わない** (REQ-101/EDGE-008)。既定は明示エラー方式 (D-Q9)。

### D10: export_gpx の GSAS-II 未導入は MCP エラーへ変換 🟡
`export_gpx` 実処理は `export.gpx.export_gpx` へ委譲し、`GSASUnavailableError` を捕捉して MCP ツール
応答の `{"status": "error", "error": "gsas_unavailable", ...}` へ変換する (クラッシュしない、
EDGE-011/TC-407-10)。他ツールと同じくアダプタ層で SDK 例外へマップする。

## ディレクトリ構造 🔵

```
src/tsumugin/
├── errors.py           # 拡張: MCPUnavailableError / MEMUnavailableError (末尾追加)
├── model/
│   ├── project.py      # 拡張: TofBankParams 新設 + HistogramRef.bank_params 末尾追加
│   └── phase.py        # 拡張: PhaseRef 新設 (PhaseInstance は不変)
├── joint/              # 新規: model / engine / weights / contrast / verification
├── chem/               # 新規: base / rules / compose / ranking
├── mcp/                # 新規: tools (SDK 非依存) / server (SDK 依存アダプタ) / mem
└── store/
    └── serialization.py # 拡張: bank_params_to_dict / _from_dict (往復対称)
tests/  test_joint_model.py / test_joint_engine.py / test_joint_weights.py /
        test_contrast.py / test_joint_verification.py / test_chem.py /
        test_chem_ranking.py / test_mcp_tools.py / test_mcp_server.py (@pytest.mark.mcp) /
        test_m4_e2e.py / test_m4_symbols_sorted.py
```

## 非機能要件の実現方法

- **NFR-001 / TC-409-04**: joint 検証は生存仮説のみ (FR-245)。2 ヒスト合成データで <30 秒 🟡
- **NFR-002**: 探索は不変・joint は生存仮説限定でコスト集中を回避 🔵
- **NFR-102 決定論 (REQ-402)**: ヒスト順は `JointRefinementModel.histograms` の並び順、元素順は
  contrast テーブル評価で元素記号昇順、スコア合成順は module id 昇順で固定。MCP 応答は
  `_json.finite_or_none` で非有限を漏らさず素の型へ写像 🔵
- **NFR-105 / REQ-401 (P2)**: 全新機能 (joint 昇格・コントラスト提案・降格・MCP 操作) は削除/上書き
  API を持たず、`ledger.verify()` が常時 True。`revert` は superseded 化のみ 🔵
- **セキュリティ (REQ-405)**: MCP は既定 stdio / 127.0.0.1 バインド。ネットワーク無認証公開なし 🔵

## 技術的制約 🔵

- **コア依存 numpy のみ (REQ-403)**: `mcp` は optional extra `mcp = ["mcp>=1.0"]`。未導入時は
  `mcp/server.py` の起動 API のみ friendly error、実処理層は SDK 非依存で import 可能。中性子散乱長は
  軽量静的テーブル (xraylib 不要)。`import tsumugin` は `mcp`/xraylib なしで成功 (TC-408-04)
- **後方互換 (REQ-404)**: `TofBankParams`/`PhaseRef`/`JointRefinementModel`/`SynthesisContext`/
  `PlausibilityResult` は既定値付き非破壊追加。`HistogramRef.bank_params` は末尾・既定 None。公開 `__all__`
  は末尾追加 + 昇順維持 (test_m4_symbols_sorted、TC-408-05)
- **chi2/rwp セマンティクス統一**: joint 集約 chi2 = Σ ヒスト χ²、rwp = 結合 Rwp。BIC 比較の一貫性を保つ

## 関連文書

- [dataflow.md](dataflow.md) / [interfaces.py](interfaces.py) / [要件定義](../../spec/m4-joint-mcp/requirements.md)
- DB スキーマ / HTTP API 仕様: なし (M4 は MCP=stdio/ローカル、新規永続 DB なし) 🔵

## 信頼性レベルサマリー

- 🔵: 34 件 (72%) / 🟡: 13 件 (28%) / 🔴: 0 — **品質評価**: 高品質
