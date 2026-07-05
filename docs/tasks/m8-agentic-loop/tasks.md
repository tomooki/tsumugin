# M8 タスク分割 (kairo-tasks)

設計: `docs/design/m8-agentic-loop/architecture.md` / 計画: `PLAN.md`

各タスクは TDD (Red→Green→Refactor)・完了=テスト green で 1 コミット。コア (action/diagnostics/
policy/orchestrator) は numpy-only、GSAS 駆動は `run_auto_rietveld` 内、LLM 判断は ③ (ライブラリ外)。

## Phase A — Action + 診断 (純 numpy)

- **TASK-0801** `refine_loop/action.py`: `AnalysisAction` 群 (frozen)。`SafeAction` (AdjustBackground/
  ReleaseParams/Stop) と `ModelAction` (SetLimits/AddPhase/RemovePhase/ReviseStructure/
  SetMixedOccupancy) を基底で型分け。各 Action は `apply(specs, recipe) -> (specs, recipe)` 純変換。
- **TASK-0802** `refine_loop/diagnostics.py`: `propose_next_actions(result, ...) -> tuple[ActionProposal,...]`
  (残差シグネチャ→提案, `safe` フラグ, 決定論安定順) + `propose_initial_limits(histograms, patterns)`
  (保守的初期リミット, setup 用)。`ActionProposal` frozen (action/rationale/priority/evidence/safe)。

## Phase B — 規則ポリシー + オーケストレータ

- **TASK-0803** `refine_loop/policy.py`: `AnalysisPolicy` Protocol + `RuleBasedPolicy` (SafeAction のみ
  優先度順選択、ModelAction は無視、目標到達/停滞/上限で Stop、決定論)。`AnalysisState` frozen。
- **TASK-0804** `refine_loop/orchestrator.py`: `run_refinement_loop` (観測→規則判断→適用→再実行、
  受理基準 Rwp 改善 ∧ validity 維持、棄却は可逆記録、ledger+snapshot)。`RefinementLoopResult` frozen
  (best result + steps + open_proposals + ledger)。決定論スタブ backend で純テスト。
- **TASK-0805** (gsas) T1/T4 規則ループ回帰: 背景増項を規則で自動化。T4 は保守初期リミット+規則で
  自律収束、最適化残は open_proposals に出す。`@pytest.mark.gsas`。

## Phase C — 薄い MCP (計器+アクチュエータ)

- **TASK-0806** `HistogramSpec`/`PhaseSpec` に `to_dict`/`from_dict` (Enum は値文字列)。TDD。
- **TASK-0807** `mcp/tools.py` に 3 ツール追加: `auto_rietveld` / `propose_next_actions` /
  `refine_with_revisions` (SDK 非依存実処理層 + 遅延 import アダプタ)。決定論スタブ判断者で e2e。

## Phase D — 実構造配線

- **TASK-0808** `autorietveld/backend_adapter.py`: `AutoRietveldBackend` (RefinementBackend Protocol)。
  model の相/観測を spec 化→`run_auto_rietveld` 委譲、Rwp/chi2 を RefinementResult へ写像 (失敗 chi2=inf)。
  search/evidence/chem を実構造に接続。純テスト (スタブ委譲) + gsas 統合。

## Phase E — ③ Claude Code プラグイン + 指示書

- **TASK-0809** `plugins/tsumugin/` (skills/analyze/SKILL.md + commands/analyze.md) + AGENT_PLAYBOOK に
  「MCP 3 ツール閉ループ」「権限境界 §4.5」節を追記。skill 手順の乾式レビュー + MCP 契約テスト。

## 品質確認・戻り

各 Phase 完了で `uv run pytest` green + `uvx ruff check` clean を確認。マイルストーン完了で PR →
`/code-review` セルフレビュー修正ループ → マージ (ユーザー判断)。
