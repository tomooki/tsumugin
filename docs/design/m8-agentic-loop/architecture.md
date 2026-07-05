# M8 Agentic 閉ループ解析 アーキテクチャ設計 (3層分離版)

作成: 2026-07-05 / 改訂: 2026-07-05 (3層分離 + RuleBasedPolicy スコープ再検討)
前提: M7 で実構造自動 Rietveld (`tsumugin.autorietveld`) が完成し実データ (T1–T4) で
チュートリアル同等の解を得た。しかし「フィット結果を観測し、事前知識・構造モデルの判断を
**AI エージェントが下して再実行する**」閉ループ層は未実装 (M7 現状評価)。

## 0. 設計判断: 判断者はハーネス側に置く (3層分離)

ユーザーは Claude Code / Codex という **エージェントハーネスの中**で実行する可能性が高い。
そこでは「判断する AI」が既に存在するため、ライブラリ側が `AgentPolicy`→LLM を呼び返す構造は
**二重反転**（Claude Code が MCP を呼ぶ→そのツールが内部で LLM に判断を投げ返す）になり不適切。

よって責務を 3 層に分離する:

| 層 | 実体 | 責務 | 判断者 |
|---|---|---|---|
| ① 決定論コア (ライブラリ, numpy) | `autorietveld` + `refine_loop` (規則部) | R1 実行 / R2 診断 / R4 適用 / **限定的な R3 (規則)** | 規則 (headless/CI/cron) |
| ② MCP = 計器＋アクチュエータ | `mcp.tools` に薄い 3 ツール | R1/R2/R4 を **構造化して露出** | — (返すだけ) |
| ③ ハーネス/プラグイン = agentic 判断 | Claude Code plugin (skill/command) | **R3 開放的判断 / R5 構造改訂・事前知識** | Claude Code 本体 / 人間 |

責務の記号: R1 実行, R2 観測(診断), R3 判断, R4 適用, R5 事前知識・構造改訂。
**R1/R2/R4 は決定論の計器＋アクチュエータ、R3/R5 が知能**。知能の大半は ③ に置く。

**MCP は共有ポータブル核**。③ の Claude Code プラグインは Claude Code 固有の糖衣で、Codex では
同じ MCP ツールを `AGENT_PLAYBOOK`（移植可能な指示書）で駆動する。

## 1. 設計原則

- **提案 ≠ 適用** (Dara/OED 教訓): 診断は候補を返すのみ。適用はループが ledger 記録の上で可逆に行う。
- **規則の判断は「安全部分集合」に厳格に限定** (§4 で再検討): 構造/相集合/事前知識に踏み込む
  判断は規則で行わず、③ に委ねる。規則は自己検証可能でパラメトリックな手だけを実行する。
- **受理基準は Rwp だけでなく物理妥当性も見る**: Rwp を下げても validity を壊す手 (過剰適合) は棄却。
- **不変条件を継承**: P2 非破壊 (ledger 追記 + snapshot revert)・NFR-102 再現性 (規則ポリシー+種
  固定でビット同一)・NFR-105 ハッシュチェーン・コア import は numpy のみ (GSAS/LLM は遅延/境界外)。

## 2. モジュール / 成果物構成

```
tsumugin/refine_loop/        # ① 決定論コアの判断ループ ("agentic" は capability/③ に限定)
├── action.py               # AnalysisAction 群 (frozen, safe/unsafe を型で区別)
├── diagnostics.py          # propose_next_actions + propose_initial_limits (R2)
├── policy.py               # AnalysisPolicy Protocol + RuleBasedPolicy (安全部分集合のみ)
└── orchestrator.py         # run_refinement_loop (観測→規則判断→適用→再実行, headless)

tsumugin/autorietveld/
└── backend_adapter.py      # AutoRietveldBackend (RefinementBackend Protocol) — 要素4

tsumugin/mcp/tools.py       # 要素3: +auto_rietveld / +propose_next_actions / +refine_with_revisions
                            #        (agentic_analyze=ループ丸ごとは MCP に出さない)

plugins/tsumugin/           # ③ Claude Code プラグイン (別成果物)
├── skills/analyze/SKILL.md # AGENT_PLAYBOOK を操作手順化 (R3/R5 を Claude が判断)
└── commands/analyze.md     # /tsumugin-analyze — MCP 3 ツールを Claude が反復駆動
```

核 (action/diagnostics/policy 規則部/orchestrator) は numpy のみ。GSAS 駆動は
`run_auto_rietveld` 内、LLM 判断は ③（ライブラリ外）。

---

## 3. 要素1 — 判断層 (決定論コアループ + 規則ポリシー)

### 3.1 AnalysisAction (action.py) — 安全/非安全を型で区別

次手を宣言的に表す frozen dataclass。**規則が実行してよい安全部分集合と、③ 専用の非安全集合を
型レベルで分ける**（`SafeAction` / `ModelAction` の基底を分離）。

**SafeAction (規則が実行可・自己検証可・パラメトリック):**

| Action | 意味 | 受理基準 |
|---|---|---|
| `AdjustBackground(hist_id, coeffs)` | 背景項を段階的に増項 (3→6→9…, 上限あり) | Rwp 改善 ∧ validity 維持 |
| `ReleaseParams(stage_flags)` | 次のパラメータ群を追加解放 (recipe 準拠) | Rwp 改善 ∧ validity 維持 |
| `Stop(reason)` | 目標到達/停滞/上限 | — |

**ModelAction (③ 専用・規則は提案のみで実行しない):**

| Action | 意味 | なぜ規則不可 |
|---|---|---|
| `SetLimits(hist_id, low, high)` | データ範囲制限 | 適切な切り位置は判断 (§4.3)。Rwp 比較不能 (範囲が変わる) |
| `AddPhase(spec\|element_hint)` | 未指数ピークに相追加 | どの相かは相同定＋化学/文脈判断 |
| `RemovePhase(name)` | 寄与ゼロ相の除去 | 誤除去のリスク、判断要 |
| `ReviseStructure(phase, edits)` | 空間群/原子座標/占有の改訂 | 開放的な結晶学判断 (事前知識 R5) |
| `SetMixedOccupancy(phase, groups)` | 混合占有サイト指定 | サイト化学の割当は残差だけから導けない |

全 Action は `apply(specs, recipe) -> (specs, recipe)` 相当の純関数変換で表現しテスト可能に保つ。

### 3.2 AnalysisPolicy Protocol + RuleBasedPolicy (policy.py)

```python
@runtime_checkable
class AnalysisPolicy(Protocol):
    def decide(self, state: AnalysisState) -> AnalysisAction:
        """観測状態から次の 1 アクション。Stop で終了。"""
```

- `AnalysisState` (frozen): `result: AutoRietveldResult`, `proposals: tuple[ActionProposal, ...]`,
  `history: tuple[AnalysisStep, ...]`, `iteration: int`, `budget: PolicyBudget`。
- **`RuleBasedPolicy`**: `proposals` のうち **SafeAction のみ**を優先度順に選ぶ。ModelAction 提案は
  無視（③ に委ねる）。目標 Rwp 到達 / 改善停滞 (ΔRwp<ε が K 回) / 反復上限で `Stop`。**決定論**。
- **AI 判断者 (③)**: `AnalysisPolicy` を Claude Code が担う。ライブラリは AgentPolicy→LLM の
  外呼びを **持たない**（0 節の反転回避）。③ は MCP 3 ツール (要素3) を反復駆動して同じ役割を果たす。

### 3.3 run_refinement_loop (orchestrator.py) — headless/決定論ループ

```python
def run_refinement_loop(
    histograms, phases, *, policy: AnalysisPolicy = RuleBasedPolicy(),
    ledger=None, max_iterations=8, target_rwp=None, seed=0,
) -> RefinementLoopResult:
    ...
```

各反復を ledger 追記 + snapshot:
1. `result = run_auto_rietveld(specs, recipe)`（要素4 backend でも可）
2. `proposals = propose_next_actions(result, ...)`（要素2）
3. `action = policy.decide(AnalysisState(...))`
4. `Stop` で終了。SafeAction なら `apply` して再実行し、**受理基準 (Rwp 改善 ∧ validity 維持)** を
   満たさなければ棄却して履歴に記録（可逆）。
- 返り値 `RefinementLoopResult`: 最良 `AutoRietveldResult` + `steps`(反復履歴) + `open_proposals`
  (未適用の ModelAction 提案 = ③/人間への申し送り) + `ledger`。
- **再現性**: RuleBasedPolicy + 種固定でビット同一 (NFR-102)。

---

## 4. RuleBasedPolicy が担える範囲の慎重な再検討 【本改訂の主眼】

> 「規則で自動化できる」と誤って広く見積もると、**構造モデルを壊す/過剰適合する自動手**を
> 生む。規則の権限は「安全・自己検証可能・パラメトリック」な手に**厳格に限定**する。

### 4.1 規則が担ってよいもの (SafeAction)

条件: (a) 構造/相集合を変えない、(b) revert ガード＋validity で自己検証できる、(c) 単調・有界。

- **背景増項** `AdjustBackground`: 3→6→9→12 と有界に段階増。各増項後 Rwp 改善かつ validity 維持で
  受理、さもなくば棄却。M7 T1/T4 の「背景項数不足で平坦」を自動化できる代表例。
- **パラメータ解放の追加** `ReleaseParams`: recipe の次段階を投入して停滞を打破。同じ受理基準。
- **停止判断** `Stop`: 目標 Rwp / 停滞 / 反復・予算上限。純粋に規則。

いずれも「間違えても revert される」ため安全。ただし §4.4 の過剰適合ガードが前提。

### 4.2 規則が担ってはいけないもの (ModelAction, ③ 専用)

- **構造改訂** `ReviseStructure`: 空間群変更・原子の追加削除・座標大移動・原点選択は開放的な
  結晶学判断。残差からは一意に決まらない (同じ残差が複数原因と両立)。**規則は原因を断定できない**。
- **相の追加/削除** `AddPhase`/`RemovePhase`: 未指数ピーク→「どの相か」は相同定＋化学的文脈。
  規則は「未指数強度あり→相追加**候補**」を**提案**するに留め、採否は ③。
- **混合占有サイトの割当** `SetMixedOccupancy`: サイト化学の知識依存。残差非依存。
- **事前知識 (R5) 全般**: 定義上、規則化不能。

### 4.3 「グレー」で判断を要するもの — 慎重に扱う

- **データリミット** `SetLimits`: M7 T4 の平坦化の主因で自動化したくなるが、(i) 適切な切り位置は
  「明瞭なピーク可視域」という**目視判断**、(ii) 範囲を変えると **Rwp が別データ上の値になり
  受理基準に使えない**。したがって規則は **`propose_initial_limits`（S/N が閾値を下回る端を切る
  保守的初期提案）を setup 段階で出すのみ**とし、ループ内の可変アクションにはしない。採用・微調整は
  ③/人間。headless の決定論経路では「保守的初期リミット」を既定適用しつつ、上書き可能とする
  (完全自律の T4 収束はこの保守リミットで近似、最適は ③ が詰める)。
- **mustrain/size の初期値**: チュートリアルの mustrain=100 のような**手動初期値**は事前知識。
  規則は「初期値を置く」のでなく「解放して LSQ に探させる」(+ 減衰) に留める。多くの場合これで足りるが、
  極端に鋭い相などは ③ の初期値投入が有効 (M7 T4 の対 6.83% 残差がこれ)。

### 4.4 受理基準の再定義 — Rwp 単独では不十分

- 規則の各手は **Rwp 改善 ∧ ValidityReport.passed 維持** を満たすときのみ受理。Rwp を下げても
  Uiso<0・占有率逸脱・格子逸脱を生む手は**過剰適合**として棄却 (validity ゲートを二重チェックに使う)。
- リミット変更のように観測集合が変わる手は Rwp 比較不能なので受理基準を別立て (§4.3 の通りループ外)。

### 4.5 まとめ (権限境界)

| 判断 | 規則 (①) | ③ (Claude/人間) |
|---|---|---|
| 背景増項・パラメータ追加解放・停止 | ✅ 実行 | 監督・上書き可 |
| 保守的初期リミット | 🟡 提案+既定適用 | 採否・微調整 |
| mustrain/size の解放 | ✅ 実行 | 初期値投入は ③ |
| リミット精密化・相追加/削除・混合占有割当 | ❌ 提案のみ | ✅ 判断・実行 |
| 構造改訂 (空間群/原子/原点)・事前知識 | ❌ | ✅ 判断・実行 |

---

## 5. 要素2 — 提案出力 (diagnostics.py)

`propose_next_actions(result, observed, calc, phases, ...) -> tuple[ActionProposal, ...]`
`propose_initial_limits(histograms, patterns) -> Mapping[hist_id, (low, high)]` (setup 用, §4.3)

`ActionProposal` (frozen): `action: AnalysisAction`, `rationale: str`, `priority: float`,
`evidence: Mapping`, **`safe: bool`** (SafeAction か = 規則が実行可能か)。規則は `safe=True` のみ実行、
③ は全提案を判断材料にする。残差シグネチャ→提案は §3.1 の表と対応 (numpy, GSAS 非依存テスト)。

- 低周波系統残差→`AdjustBackground` (safe)。端の低 S/N→`SetLimits` 提案 (unsafe)。
- obs/calc FWHM 比の系統ずれ→`ReleaseParams`(size/mustrain, safe)。
- 未指数 obs ピーク→`AddPhase`/`ReviseStructure` (unsafe, 相同定へのハンドオフ情報付き)。
- validity fail→`ReviseStructure`/制約追加 (unsafe)。
- 決定論・安定順 (safe 優先→優先度降順→種別昇順, NFR-102)。適用はしない。

---

## 6. 要素3 — 薄い MCP (計器＋アクチュエータ)

MCP_TOOLS に **3 ツールのみ**追加（ループ丸ごとの `agentic_analyze` は出さない = ③ が回す）:

| ツール | 入力 | 出力 (構造化 = ③ の判断入力) |
|---|---|---|
| `auto_rietveld` | histograms/phases spec (JSON) + 任意 recipe | 段階別 Rwp/GOF/nvar/reverted・per-hist Rwp・格子・validity 項目別・**spec ハンドル** |
| `propose_next_actions` | 直前結果ハンドル | `ActionProposal[]` (rationale/priority/**safe**/evidence)・未指数ピーク・FWHM 比・背景残差 |
| `refine_with_revisions` | spec ハンドル + `AnalysisAction[]` (③ が決めた改訂) | 改訂適用して再実行した `auto_rietveld` 相当出力 |

- 既存パターン踏襲: SDK 非依存の実処理層 + 遅延 import アダプタ。`HistogramSpec`/`PhaseSpec` に
  `to_dict`/`from_dict` を追加 (Enum は値文字列)。
- **閉ループの実体**: Claude Code (③) が `auto_rietveld`→結果を読む→`propose_next_actions`→
  **自ら次手を判断** (SafeAction は自明、ModelAction=構造改訂は Claude/ユーザーが決定)→
  `refine_with_revisions`→反復。反転なし。ユーザー承認 (構造変更) は Claude Code UI で自然に挟める。
- 非破壊/認可境界は既存 MCP と同一 (accept/revert は既存ツール)。
- **オプション**: headless 用に `run_refinement_loop(policy=rule)` を呼ぶ薄いツールは追加可能だが、
  それは「規則ループを回す」ものであり LLM を呼び返さない (§0 の反転を作らない)。

---

## 7. 要素4 — 実構造への配線 (autorietveld/backend_adapter.py)

現状 `pipeline`/`search` はダミー `SimulatedBackend`。実構造多仮説解析のためのアダプタを追加。

### 7.1 AutoRietveldBackend (RefinementBackend Protocol 実装)

```python
class AutoRietveldBackend:  # backends.base.RefinementBackend を満たす
    def refine(self, model, *, max_cycles=20) -> RefinementResult:
        # model の相・観測を PhaseSpec/HistogramSpec 化 → run_auto_rietveld へ委譲。
        # 最終 Rwp/chi2 を RefinementResult へ写像 (失敗は chi2=inf, 既存規約)。
```

- `HypothesisTreeSearch`/`analyze_single_pattern` が **実構造**で多仮説を精密化・ランキング可能に。
  木探索の枝刈り (dynamic_threshold) と evidence ランキングが実 Rwp に基づく。既存 `SimulatedBackend`
  は高速スクリーニング用に温存 (注入で選択)。

### 7.2 判断プリミティブの接続

- **evidence**: 実構造 refine 群の BIC/softmax でランキング。
- **chem**: 実構造候補の化学的妥当性で降格 (除外せず)。
- **oed** `propose_measurements`: 僅差競合時に次の**測定**を提案。M8 の `AnalysisAction` (=解析内の
  次手) とは別軸 (=次の実験) として `RefinementLoopResult`/③ に併記。
- **search** `HypothesisTreeSearch`: 実構造で相の追加/削除を木探索として実行。③ の `AddPhase`/
  `RemovePhase` 判断はこの木探索 1 手に対応づく (相の探索と相内適応を実構造上で統合)。

---

## 8. 要素③ — Claude Code プラグイン (別成果物, agentic 判断層)

```
plugins/tsumugin/
├── skills/analyze/SKILL.md   # AGENT_PLAYBOOK を操作手順化: 入力の集め方・MCP 3 ツールの使い方・
│                             #   残差の読み方・SafeAction は自動 / ModelAction は Claude が判断し
│                             #   構造改訂・相追加はユーザー承認を挟む・収束判定
└── commands/analyze.md       # /tsumugin-analyze <data...> — 上記 skill を起動する slash command
```

- ③ が **R3 開放的判断 / R5 構造改訂・事前知識**を担う実体。Claude Code のネイティブな計画・記憶・
  サブエージェント・ユーザー介入をそのまま使う。
- **Codex 等**: プラグインは Claude Code 固有。Codex では同じ MCP 3 ツールを AGENT_PLAYBOOK
  (ポータブル指示書) で駆動する。プラグインは各ハーネスの薄い操作層。
- skill には §4.5 の権限境界を明記し、Claude が「どこまで自動でどこから確認を挟むか」を守る。

## 9. データフロー

```
                         ┌───────────── ③ Claude Code plugin / Codex (R3/R5 判断) ─────────────┐
                         │  skill = AGENT_PLAYBOOK 手順化 ; SafeAction 自動 / ModelAction は確認  │
histograms/phases ──▶ MCP│  auto_rietveld ──▶ 構造化結果 (Rwp段階/validity/未指数ピーク/FWHM比)   │
                         │        ▲                    │                                        │
                         │        │             propose_next_actions ──▶ ActionProposal[] (safe?)│
                         │        │                    │  Claude が次手決定 (構造改訂は user 承認) │
                         │  refine_with_revisions ◀────┘                                        │
                         └──────────────────────────────────────────────────────────────────────┘
   headless/CI 経路:  run_refinement_loop(policy=RuleBasedPolicy) ── SafeAction のみ自律・ModelAction は open_proposals へ
   共通核: run_auto_rietveld (要素4 backend 可) / propose_next_actions / apply(action) / ledger+snapshot
```

## 10. 不変条件

- P2 非破壊 (ledger 追記・snapshot・削除 API なし)・NFR-102 (RuleBasedPolicy+種固定でビット同一)・
  NFR-105 (ハッシュチェーン `verify()` True)・コア numpy-only (GSAS は run_auto_rietveld 内、LLM は ③)。
- 提案≠適用。受理は Rwp 改善 ∧ validity 維持 (過剰適合ガード)。

## 11. 段階計画

- **Phase A — Action + 診断**: `action.py`(safe/unsafe 型分け) + `propose_next_actions` +
  `propose_initial_limits`。純 numpy テスト (残差→提案、safe フラグ)。
- **Phase B — 規則ポリシー + オーケストレータ**: `RuleBasedPolicy`(SafeAction のみ) +
  `run_refinement_loop` + 受理基準 (Rwp∧validity)。T1/T4 の背景増項を規則で自動化して検証。
  **T4 は保守的初期リミット + 規則ループで自律収束、最適化残は open_proposals に出す**。
- **Phase C — 薄い MCP (要素3)**: `auto_rietveld`/`propose_next_actions`/`refine_with_revisions`
  + spec の to_dict/from_dict。決定論スタブで e2e。
- **Phase D — 実構造配線 (要素4)**: `AutoRietveldBackend` + search/evidence/chem/oed 接続。
- **Phase E — ③ プラグイン + 指示書**: Claude Code plugin (skill/command) + AGENT_PLAYBOOK に
  「MCP 3 ツール閉ループ」「権限境界 §4.5」節を追記。構造改訂を要する新規例を ③ で検証。

## 12. テスト戦略

- 診断・Action・規則ポリシー・オーケストレータ: **純テスト** (モック結果、GSAS 不要)。safe/unsafe の
  権限境界 (規則が ModelAction を実行しないこと) を明示テスト。
- 実構造ループ: `@pytest.mark.gsas`。T4 を規則ポリシー+保守リミットで収束させる回帰。
- MCP 3 ツール: 決定論スタブ判断者 (固定 Action 列) で e2e 再現。
- 再現性: 同一種・同一規則ポリシーで `RefinementLoopResult` ビット同一・ledger `verify()` True。
- ③ プラグイン: skill 手順の乾式レビュー + MCP 契約テスト (実 LLM は手動)。

## 13. スコープ外 (M-later)

- 実 LLM 判断者の自動評価・プロンプト最適化。原子位置の大域探索・空間群決定は `ReviseStructure` の
  入力として外部ソルバに委譲。Codex 向けネイティブ操作層。
- **マルチスタート大域最適確認 (シーケンシャル) は実装済み** (`autorietveld.run_multistart_rietveld`,
  Issue #13): 初期格子摂動の複数開始点→ベイスン一致で `is_global_corroborated`。**並列**
  オーケストレーションと原子座標摂動軸のみ M-later。agentic ループは開始点ごとに multistart を
  呼ぶか、`is_global_corroborated=False` を「収束先分岐」の提案根拠に使える。
