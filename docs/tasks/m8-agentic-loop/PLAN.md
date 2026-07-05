# M8: Agentic 閉ループ解析 — 結果駆動で AI エージェントが判断する自動解析

作成: 2026-07-05 / 設計: `docs/design/m8-agentic-loop/architecture.md`

## 1. 目的

M7 で実構造自動 Rietveld (`tsumugin.autorietveld`) が実データ (T1–T4) でチュートリアル同等の
解を得た。しかし「フィット結果を観測し、事前知識・構造モデルの判断を **AI エージェントが下して
再実行する**」閉ループ層は未実装。M8 でこれを実装し、**AI エージェントによる真の自律解析**を達成する。

M7 の T4 収束改善で私 (Claude) が手動で行った判断 — 「48%平坦→データリミット設定」「背景項数
調整」「mustrain 初期値」「相の追加判断」— を、**システムが結果から自動で提案・実行**できるようにする。

## 2. 3層分離 (M7 現状評価の Gap → 責務分離)

ユーザーは Claude Code / Codex というエージェントハーネス内で実行する可能性が高い。判断する AI が
既に存在するため、ライブラリが `AgentPolicy`→LLM を呼び返す**二重反転**を避け、責務を 3 層に分ける:

| 層 | 実体 | 責務 | 判断者 |
|---|---|---|---|
| ① 決定論コア | `autorietveld` + `agentic`(規則部) | 実行/診断/適用 + **限定的な規則判断** | 規則 (headless/CI) |
| ② MCP | 薄い 3 ツール | 判断入力を**構造化して露出** | — |
| ③ ハーネス/プラグイン | Claude Code plugin | **開放的判断・構造改訂・事前知識** | Claude/人間 |

要素 (M7 評価の 4 Gap を 3 層へ):
1. **判断層** — 決定論ループ (`run_agentic_analysis`) + `RuleBasedPolicy` (**安全部分集合のみ**)。
   AI 判断は ③ に委譲 (AgentPolicy→LLM 外呼びは持たない)。
2. **提案出力** — `propose_next_actions` (残差診断→`ActionProposal`, safe/unsafe を型分け)。
3. **MCP 露出 (薄い)** — `auto_rietveld` / `propose_next_actions` / `refine_with_revisions` の
   3 ツールのみ (ループ丸ごとは出さない = ③ が回す)。MCP が共有ポータブル核。
4. **実構造への配線** — `AutoRietveldBackend` (RefinementBackend Protocol) で search/evidence/
   chem/oed を実構造に接続 (現状ダミー SimulatedBackend)。
5. **③ Claude Code プラグイン** (別成果物) — AGENT_PLAYBOOK を skill/command 化。R3/R5 の実体。

## 2.1 RuleBasedPolicy が担える範囲 (慎重に線引き — 詳細 architecture.md §4)

**規則が実行してよい (SafeAction, 自己検証可・パラメトリック)**: 背景増項・パラメータ追加解放・
停止判断。受理は **Rwp 改善 ∧ validity 維持** (過剰適合ガード)。間違えても revert される。

**規則が実行してはいけない (ModelAction, ③ 専用・提案のみ)**: 構造改訂 (空間群/原子/原点)・相の
追加削除・混合占有割当・事前知識。残差からは一意に決まらず、規則は原因を断定できない。

**グレー (慎重に)**: データリミットは範囲変更で Rwp 比較不能かつ切り位置が判断。規則は保守的な
**初期リミット提案** (setup) に留め、精密化はループ外・③。mustrain 初期値は事前知識のため規則は
「解放して LSQ に探させる」に留める (極端に鋭い相の初期値投入は ③)。

## 3. 達成目標

- **規則ポリシーで T4 を自律収束**: M7 で手動判断した背景増項/リミット/解放順を、ループが
  `propose_next_actions` → `RuleBasedPolicy` で自動選択して収束させる。
- **Claude 判断者で構造改訂を要する例を解く**: `ReviseStructure`/`AddPhase` を含む、事前知識・
  構造モデル変更が必要な新規実データ例を、MCP + `AgentPolicy` の閉ループで解析。
- 不変条件 (P2/NFR-102/NFR-105/numpy-only コア) を維持。

## 4. フェーズ

| Phase | 内容 | 検証 |
|---|---|---|
| A | Action(safe/unsafe 型分け) + 診断 (`propose_next_actions`/`propose_initial_limits`) | 純テスト (残差→提案, safe フラグ) |
| B | `RuleBasedPolicy`(SafeAction のみ) + `run_agentic_analysis` + 受理基準(Rwp∧validity) | T1/T4 の背景増項を規則で自動化。T4 は保守リミット+規則で自律収束 (gsas) |
| C | 薄い MCP 3 ツール + spec JSON 化 | 決定論スタブ判断者で閉ループ e2e |
| D | 実構造配線 (`AutoRietveldBackend` + search/evidence/chem/oed 接続) | 実構造多仮説 e2e (gsas) |
| E | ③ Claude Code plugin (skill/command) + AGENT_PLAYBOOK に閉ループ・権限境界節 | 構造改訂を要する新規例を ③ で検証 |

## 5. 設計上の要点 (詳細は architecture.md)

- **判断者はハーネス側**: ライブラリは AgentPolicy→LLM 外呼びを持たない (二重反転回避)。R3/R5 は ③。
- **規則の権限は安全部分集合に厳格限定** (§2.1): 構造/相集合/事前知識に踏み込まない。
- **受理は Rwp だけでなく validity も見る** (過剰適合ガード)。リミット変更は Rwp 比較不能につきループ外。
- **提案≠適用**: 診断・oed は提案のみ。適用はループが ledger 記録の上で可逆に行う。
- **MCP + ③ (Claude Code plugin / Codex) が「AI エージェントによる解析」の実体**。MCP が共有核。
