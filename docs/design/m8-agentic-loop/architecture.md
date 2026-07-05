# M8 Agentic 閉ループ解析 アーキテクチャ設計

作成: 2026-07-05 / 前提: M7 で実構造自動 Rietveld (`tsumugin.autorietveld`) が完成し、
実データ (T1–T4) でチュートリアル同等の解を得た。ただし「フィット結果を見て事前知識・
構造モデルを **AI エージェントが判断する**」閉ループ層は未実装 (M7 現状評価より)。

本書は未実装の 4 要素を設計する:
1. **判断層** — 結果を観測し次アクションを決めて再実行するオーケストレータ
2. **提案出力** — 精密化結果 (残差) から次アクション候補を構造化して返す診断
3. **MCP 露出** — `run_auto_rietveld` と提案・ループを MCP 境界に出す
4. **実構造への配線** — evidence/oed/chem/search を `autorietveld` に接続

## 1. 設計原則

- **知能は差し替え可能なポリシー**: ループ (観測→判断→適用→再実行) は決定論。判断だけを
  `AnalysisPolicy` Protocol の背後に置き、以下 2 実装を同一ループへ挿せるようにする。
  - `RuleBasedPolicy` — AGENT_PLAYBOOK §6 の症状→対処を規則化。決定論・再現可能・CI 用 (NFR-102)。
  - `AgentPolicy` — 外部 LLM/Claude が判断者 (MCP 経由 or コールバック)。構造モデル変更や事前知識
    の投入といった **開放的判断** を担う。核は決定論のまま、知能は外から注入する。
- **不変条件を継承**: P2 非破壊 (ledger 追記 + snapshot revert)・NFR-102 再現性 (種固定 +
  ポリシー固定でビット同一)・NFR-105 ハッシュチェーン・コア import は numpy のみ (GSAS/LLM は遅延)。
- **提案と適用の分離** (Dara/OED 教訓): 診断は「提案」を返すのみ。適用はループが ledger 記録の
  上で行い、悪化時は revert。候補は除外せず降格・再試行する。

## 2. モジュール構成

```
tsumugin/agentic/
├── __init__.py        # 公開シンボル
├── action.py          # AnalysisAction 群 (frozen dataclass, 次手の宣言的表現)
├── diagnostics.py     # propose_next_actions — 残差診断 → ActionProposal 列 (要素2)
├── policy.py          # AnalysisPolicy Protocol + RuleBasedPolicy + AgentPolicy 境界 (要素1)
└── orchestrator.py    # AgenticOrchestrator — 観測→判断→適用→再実行ループ (要素1)

tsumugin/autorietveld/
└── backend_adapter.py # AutoRietveldBackend — RefinementBackend Protocol 実装 (要素4)

tsumugin/mcp/
└── tools.py           # +auto_rietveld / +propose_next_actions / +agentic_analyze (要素3)
```

核 (action/diagnostics/policy/orchestrator の規則部) は numpy のみ。GSAS 駆動 (`run_auto_rietveld`)
と LLM (`AgentPolicy`) は境界の内側で遅延 import。

---

## 3. 要素1 — 判断層 (orchestrator + policy)

### 3.1 AnalysisAction (action.py)

次手を宣言的に表す frozen dataclass 群。オーケストレータがこれを解釈して入力 (HistogramSpec/
PhaseSpec/recipe) を改訂し再実行する。**構造モデル変更を含む**のが M8 の要点。

| Action | 意味 | 改訂対象 |
|---|---|---|
| `AdjustBackground(hist_id, coeffs)` | 背景項数を変更 (REQ-201 の動的増項) | recipe/engine 背景フラグ |
| `SetLimits(hist_id, low, high)` | データ範囲制限 (ノイズ域除外) | HistogramSpec.two_theta_limits |
| `AdjustPeakShape(phase, hist_id, kind, init)` | mustrain/size の初期値・解放 | PhaseSpec 拡張 (初期プロファイル) |
| `AddPhase(phase_spec \| element_hint)` | 未指数ピークに相を追加 | phases に追加 (相同定 or 供給元経由) |
| `RemovePhase(phase_name)` | 寄与ゼロの相を除去 | phases から除去 |
| `ReviseStructure(phase, edits)` | 空間群/原子座標/占有の改訂 (**事前知識**) | PhaseSpec.structure 差し替え |
| `SetMixedOccupancy(phase, groups)` | 混合占有サイトの指定 | PhaseSpec.mixed_occupancy_groups |
| `RefineExtra(stage_flags)` | 追加パラメータ段階の投入 | recipe に段階追加 |
| `Stop(reason)` | 収束/上限到達で終了 | — |

全 Action は `apply(specs, recipe) -> (specs, recipe)` 相当の純関数変換で表現し、テスト可能に保つ。

### 3.2 AnalysisPolicy Protocol (policy.py)

```python
@runtime_checkable
class AnalysisPolicy(Protocol):
    def decide(self, state: AnalysisState) -> AnalysisAction:
        """観測状態から次の 1 アクションを決める。Stop で終了。"""
```

- `AnalysisState` (frozen): `result: AutoRietveldResult`, `proposals: tuple[ActionProposal, ...]`
  (要素2 の診断), `history: tuple[AnalysisStep, ...]` (過去の (action, result) 列),
  `iteration: int`, `budget: PolicyBudget` (最大反復・Rwp 目標)。
- **`RuleBasedPolicy`**: `proposals` を優先度順に見て最初の適用可能 Action を返す。閾値
  (Rwp 目標到達/改善停滞/反復上限) で `Stop`。AGENT_PLAYBOOK §6 の表を実装。決定論。
- **`AgentPolicy`**: `decide` を外部判断者へ委譲する境界。`state` を JSON 化して
  `advisor(state_json) -> action_json` コールバック (MCP アダプタ/LLM) に渡し、返った Action を
  検証して適用する。Claude が判断者になる場合はこの経路。**構造モデル変更・事前知識投入を担う**。

### 3.3 AgenticOrchestrator (orchestrator.py)

```python
def run_agentic_analysis(
    histograms, phases, *, policy: AnalysisPolicy,
    ledger=None, max_iterations=8, target_rwp=None, seed=0,
) -> AgenticResult:
    ...
```

ループ (各反復を ledger 追記・snapshot 保存):
1. `result = run_auto_rietveld(specs, recipe)` (要素4 の backend 経由でも可)
2. `proposals = propose_next_actions(result, ...)` (要素2)
3. `action = policy.decide(AnalysisState(result, proposals, history, ...))`
4. `Stop` なら終了。それ以外は `specs, recipe = action.apply(specs, recipe)`
5. **ガード**: 適用後の再実行が悪化 → その action を棄却し履歴に記録 (revert 相当) して継続
   (P2/既存 revert 思想の反復版)。改善が閾値未満の連続で打ち切り。
- 返り値 `AgenticResult`: 最良 `AutoRietveldResult` + `steps` (反復履歴) + `ledger`。
- **再現性**: `RuleBasedPolicy` + 種固定でビット同一 (NFR-102)。`AgentPolicy` 使用時は
  判断者応答を履歴に記録し、同一応答列で再現可能 (リプレイ)。

---

## 4. 要素2 — 提案出力 (diagnostics.py)

`propose_next_actions(result, observed, calc, phases, ...) -> tuple[ActionProposal, ...]`

`ActionProposal` (frozen): `action: AnalysisAction`, `rationale: str`, `priority: float`,
`evidence: Mapping` (診断根拠の数値)。ポリシーと外部エージェント双方が消費する。

残差シグネチャ → Action の対応 (numpy で計算、GSAS 非依存にテスト可能):

| 診断 (残差の兆候) | 提案 Action | 根拠指標 |
|---|---|---|
| 低周波の系統残差 (背景のうねり) | `AdjustBackground` (増項) | 平滑化残差の分散寄与 |
| 端 (高角/低d) の大残差・低 S/N | `SetLimits` | 端領域の残差/強度比 |
| calc ピーク幅の系統的過小/過大 | `AdjustPeakShape` (mustrain/size) | obs/calc の FWHM 比中央値 |
| obs ピークに対応 calc 無し (未指数) | `AddPhase` / `ReviseStructure` | 未マッチ obs ピークの強度和 |
| calc ピークに対応 obs 無し (過剰) | `RemovePhase` / `ReviseStructure` | 過剰 calc ピーク数 |
| 全ピークの系統的位置ずれ | (格子/ゼロ/変位は既存レシピで対応) | ピーク位置残差の符号一貫性 |
| `validity` の項目 fail (Uiso<0 等) | `ReviseStructure` / 制約追加 | ValidityReport.checks |
| Rwp 停滞かつ高値 | `RefineExtra` / multi-start 提案 | 反復間 ΔRwp |

- 未指数ピーク検出は既存 `reference.find_peaks` + `reference.background` (SNIP) を再利用。
- 提案は決定論・安定順 (優先度降順→種別昇順、NFR-102)。**適用はしない** (提案のみ)。

---

## 5. 要素3 — MCP 露出 (mcp/tools.py)

外部 AI エージェント (Claude) が実構造精密化を反復駆動できるよう、MCP_TOOLS に追加:

| ツール | 入力 | 出力 | 用途 |
|---|---|---|---|
| `auto_rietveld` | histograms/phases spec (JSON) | `AutoRietveldResult` の summary (段階別 Rwp/GOF・格子・validity) | 1 回の実構造精密化 |
| `propose_next_actions` | 直前結果 (ハンドル or JSON) | `ActionProposal` 列 (rationale/priority 付き) | 次手候補の取得 |
| `agentic_analyze` | histograms/phases + policy 指定 + budget | `AgenticResult` summary | ループ一括実行 (policy=rule で自律, policy=agent で Claude が判断者) |

- 既存パターン踏襲: SDK 非依存の実処理層 (`tools.py`) + 遅延 import アダプタ (`server.py`)。
- **spec の JSON 化**: `HistogramSpec`/`PhaseSpec` に `to_dict`/`from_dict` を追加 (Enum は値文字列)。
- **Claude を判断者にする閉ループ**: Claude が `auto_rietveld` → 結果を読む →
  `propose_next_actions` → §3.2 `AgentPolicy` として次 Action を決める → `auto_rietveld` 再呼び。
  つまり **MCP + AgentPolicy が「AI エージェントによる解析」の実体**になる。
- 非破壊/認可境界は既存 MCP と同一 (accept/revert は既存ツール)。

---

## 6. 要素4 — 実構造への配線 (autorietveld/backend_adapter.py)

現状 `pipeline`/`search` はダミー `SimulatedBackend` を使う (格子同定用)。実構造の多仮説解析を
可能にするアダプタを追加する。

### 6.1 AutoRietveldBackend (RefinementBackend Protocol 実装)

```python
class AutoRietveldBackend:  # backends.base.RefinementBackend を満たす
    def refine(self, model: RefinementModel, *, max_cycles=20) -> RefinementResult:
        # model.phases (実構造 PhaseSpec 化) + model の観測を run_auto_rietveld に委譲し、
        # 最終 Rwp/chi2 を RefinementResult へ写像 (失敗は chi2=inf, 既存規約)。
```

- これで `HypothesisTreeSearch` / `analyze_single_pattern` が **実構造**で多仮説を精密化・ランキング
  できる (現状はダミー構造)。木探索の枝刈り (dynamic_threshold) と evidence ランキングが実 Rwp に基づく。
- 既存 `SimulatedBackend` は温存 (高速スクリーニング用)。バックエンドは注入で選択。

### 6.2 判断プリミティブの接続

- **evidence**: 実構造 refine 群の BIC/softmax でランキング (既存 `evidence` をそのまま実 Rwp に適用)。
- **chem**: 実構造候補の化学的妥当性で降格 (除外せず)。
- **oed** `propose_measurements`: 僅差競合時に次の **測定** を提案 (M8 の `AnalysisAction` とは別軸:
  「解析内の次手」= agentic、「次の実験」= oed。両者を `AgenticResult` に併記)。
- **search** `HypothesisTreeSearch`: 実構造バックエンドで相の追加/削除 (`AddPhase`/`RemovePhase`
  Action) を木探索として実行。agentic ループの `AddPhase` はこの木探索 1 手に対応づける。

これにより「相の探索 (search/evidence/chem/oed)」と「相内パラメータ・構造の適応 (agentic)」が
実構造上で統合される。

---

## 7. データフロー

```
histograms/phases ─┐
                   ▼
        ┌── AgenticOrchestrator (要素1) ──────────────────────────┐
        │  run_auto_rietveld (要素4 backend 可) → AutoRietveldResult│
        │        │                                                 │
        │        ▼                                                 │
        │  propose_next_actions (要素2) → ActionProposal[]          │
        │        │                                                 │
        │        ▼                                                 │
        │  AnalysisPolicy.decide (要素1)                            │
        │     ├ RuleBasedPolicy (決定論)                            │
        │     └ AgentPolicy ⇄ MCP/LLM (要素3, Claude が判断)         │
        │        │ AnalysisAction (背景/リミット/mustrain/相追加/構造改訂)│
        │        ▼ apply → 改訂 specs/recipe → (ledger 追記, snapshot) │
        └────────┴── ループ (悪化 revert, 目標/上限で Stop) ──────────┘
                   ▼
             AgenticResult (最良結果 + 反復履歴 + oed 次実験提案 + ledger)
```

## 8. 不変条件の維持

- **P2 非破壊**: 各反復を ledger に追記、適用前に snapshot。棄却/revert のみ (削除 API なし)。
- **NFR-102 再現性**: RuleBasedPolicy + 種固定でビット同一。AgentPolicy は判断者応答をログしリプレイ可能。
- **NFR-105**: ledger ハッシュチェーン維持 (`verify()` 常に True)。
- **コア numpy-only**: action/diagnostics/policy(規則)/orchestrator は純 numpy。GSAS は
  `run_auto_rietveld` 内、LLM は `AgentPolicy` 境界内で遅延 import。
- **提案≠適用**: 診断・oed は提案のみ。適用はループが記録の上で行い可逆。

## 9. 段階計画 (Phase)

- **Phase A — Action + 診断 (要素2 基盤)**: `action.py` + `diagnostics.propose_next_actions`。
  純 numpy・GSAS 非依存でユニットテスト (残差シグネチャ→提案の写像)。
- **Phase B — ポリシー + オーケストレータ (要素1)**: `AnalysisPolicy` Protocol + `RuleBasedPolicy`
  + `AgenticOrchestrator`。T4 を規則ポリシーで駆動し **48%→自動で背景増項/リミット提案→収束**を検証
  (M7 で手動判断した背景項数調整をループが自動化)。
- **Phase C — MCP 露出 (要素3)**: `auto_rietveld`/`propose_next_actions`/`agentic_analyze` +
  spec の to_dict/from_dict。`AgentPolicy` の MCP アダプタ。Claude を判断者にした閉ループ e2e。
- **Phase D — 実構造配線 (要素4)**: `AutoRietveldBackend` + search/evidence/chem/oed 接続。
  実構造多仮説 e2e (相同定→実構造精密化→ランキング→相追加判断)。
- **Phase E — 洗練 + 指示書更新**: AGENT_PLAYBOOK に「MCP + AgentPolicy 閉ループ」節を追加。
  T1–T4 を agentic ループで再現 (規則ポリシー) + Claude ポリシーで構造改訂を要する新規例を検証。

## 10. テスト戦略

- 診断・Action・規則ポリシー・オーケストレータ (SimulatedBackend/モック結果): **純テスト** (GSAS 不要)。
- 実構造ループ: `@pytest.mark.gsas`。T4 を規則ポリシーで収束させる回帰。
- `AgentPolicy`: 決定論スタブ判断者 (固定 Action 列) で e2e を再現テスト。実 LLM は手動/契約テスト。
- 再現性: 同一種・同一ポリシーで `AgenticResult` がビット同一・ledger `verify()` True。

## 11. スコープ外 (M-later)

- 実 LLM 判断者の自動評価・プロンプト最適化。
- 構造探索 (原子位置の大域探索・空間群決定) は `ReviseStructure` の入力として外部ソルバに委譲。
- multi-start の並列オーケストレーション。
