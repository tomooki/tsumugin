# M8: Agentic 閉ループ解析 — 結果駆動で AI エージェントが判断する自動解析

作成: 2026-07-05 / 設計: `docs/design/m8-agentic-loop/architecture.md`

## 1. 目的

M7 で実構造自動 Rietveld (`tsumugin.autorietveld`) が実データ (T1–T4) でチュートリアル同等の
解を得た。しかし「フィット結果を観測し、事前知識・構造モデルの判断を **AI エージェントが下して
再実行する**」閉ループ層は未実装。M8 でこれを実装し、**AI エージェントによる真の自律解析**を達成する。

M7 の T4 収束改善で私 (Claude) が手動で行った判断 — 「48%平坦→データリミット設定」「背景項数
調整」「mustrain 初期値」「相の追加判断」— を、**システムが結果から自動で提案・実行**できるようにする。

## 2. 実装する 4 要素 (M7 現状評価の Gap)

1. **判断層** — 観測→判断→適用→再実行のオーケストレータ + 差し替え可能な `AnalysisPolicy`
   (規則ベース = 決定論/CI用、AI エージェント = 開放的判断)。
2. **提案出力** — 残差診断から次アクション候補 (`ActionProposal`) を構造化して返す。
3. **MCP 露出** — `auto_rietveld`/`propose_next_actions`/`agentic_analyze` を MCP 境界に出し、
   Claude が判断者として閉ループを回せるようにする。
4. **実構造への配線** — `AutoRietveldBackend` (RefinementBackend Protocol) で search/evidence/
   chem/oed を実構造 `autorietveld` に接続 (現状ダミー SimulatedBackend)。

## 3. 達成目標

- **規則ポリシーで T4 を自律収束**: M7 で手動判断した背景増項/リミット/解放順を、ループが
  `propose_next_actions` → `RuleBasedPolicy` で自動選択して収束させる。
- **Claude 判断者で構造改訂を要する例を解く**: `ReviseStructure`/`AddPhase` を含む、事前知識・
  構造モデル変更が必要な新規実データ例を、MCP + `AgentPolicy` の閉ループで解析。
- 不変条件 (P2/NFR-102/NFR-105/numpy-only コア) を維持。

## 4. フェーズ

| Phase | 内容 | 検証 |
|---|---|---|
| A | Action + 診断 (`propose_next_actions`) | 純テスト (残差→提案の写像) |
| B | ポリシー + オーケストレータ | T4 を規則ポリシーで自律収束 (gsas) |
| C | MCP 露出 + spec JSON 化 + AgentPolicy | Claude 判断者の閉ループ e2e |
| D | 実構造配線 (`AutoRietveldBackend` + 多仮説機構接続) | 実構造多仮説 e2e (gsas) |
| E | 洗練 + AGENT_PLAYBOOK 更新 (閉ループ節) | T1–T4 agentic 再現 + 新規例 |

## 5. 設計上の要点 (詳細は architecture.md)

- **知能は Protocol 背後**: ループは決定論、判断だけ `AnalysisPolicy` で注入。規則/AI の 2 実装。
- **提案≠適用**: 診断・oed は提案のみ。適用はループが ledger 記録の上で可逆に行う。
- **「解析内の次手」(agentic) と「次の実験」(oed) を分離**しつつ `AgenticResult` に併記。
- **MCP + AgentPolicy が「AI エージェントによる解析」の実体**。
