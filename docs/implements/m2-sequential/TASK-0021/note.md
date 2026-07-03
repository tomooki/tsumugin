# TASK-0021 TDD 開発コンテキストノート

**タスク**: FinalSelectionEngine + Decision (最終選択 agent/human 2 モード裁定)
**要件名**: m2-sequential / **タスクID**: TASK-0021 / **タイプ**: TDD / **推定 4h**
**フェーズ**: Phase 3 - エンジン / **信頼性**: 🔵 FR-402/403 / REQ-013/014/102〜104/202 / 設計 D5
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`selection/engine.py` を**拡張**し、`Decision` (frozen dataclass) と `FinalSelectionEngine`
(agent/human 2 モードの最終選択裁定クラス) を追加する。detect_escalations / ReviewQueue
(TASK-0020) の上に構築する。**engine.py への追記**であり detect_escalations は無改変。

### 実装する 2 成果物 (interfaces.py L328-362 契約準拠)

1. `Decision` (frozen dataclass): 1 回の裁定結果。
   - `mode: Literal["agent","human"]` / `accepted: Hypothesis | None` (accepted 化した新インスタンス) /
     `provisional_id: str | None` (agent+エスカレーション時の暫定) / `recommended_id: str | None`
     (human の推奨) / `escalations: tuple[EscalationReason, ...]` / `rationale: str` (自然言語+定量根拠)。
2. `FinalSelectionEngine`:
   - `__init__(*, mode="agent", ledger=None, queue=None)` — mode / 注入 ledger / 注入 ReviewQueue を保持。
   - `set_mode(mode)` → mode 切替を ledger に記録 (REQ-104)。
   - `decide(result, *, frame_index=None) -> Decision` — 2 モード分岐の中核。
   - `accept(result, hypothesis_id, *, by) -> Hypothesis` — 明示 accept API (単一経路)。
   - `revert(hypothesis_id, *, note="") -> Hypothesis` — superseded 化 + 履歴保持 (REQ-202)。
   - `accepted` (property) → `Mapping[str, Hypothesis]` (裁定レジストリ、追記のみ)。

### 🚨 絶対制約 (完了条件 7 項目と直結)

- **agent + 明確な最良** → 自動 accepted / `accepted_by="agent"` / rationale が ledger に記録 🔵 *TC-107-01*
- **agent + 僅差 (エスカレーションあり)** → accepted なし・`provisional_id` 設定 + ReviewQueue 追加・
  **処理は完了する (ブロックしない)** 🔵 *TC-107-02*
- **human モード** → `recommended_id` のみ (自動 accept なし)。`accept` API 呼び出しで `accepted_by="human"` 🔵 *TC-107-03*
- **set_mode が ledger 記録される** 🔵 *TC-107-04*
- **revert** → status `superseded` + 元の裁定履歴が ledger に残る (削除しない) 🔵 *TC-107-05*
- **ranked 空 (裁定対象ゼロ)** → accept なし + エスカレーションのみ 🟡 *TC-107-08/EDGE-004*
- **SearchResult が変更されない (非破壊)** — accepted 化は `dataclasses.replace` の新 Hypothesis 🔵 *D5*
- **git commit しない** (ユーザー判断。本セッション制約)。

### agent 自動 accept の 4 条件 (interview Q8、AND 判定)

(a) ランキング 1 位 (best = `ranked[0]`) / (b) `close_competitor=False` / (c) `unknown_phase_flag=False` /
(d) `escalated=False` (= `detect_escalations` が空タプル)。**4 条件すべて満たすときのみ自動 accept**。
いずれか欠けたら暫定裁定 (best を provisional 記録) + Review Queue 通知。M2 で利用可能な材料のみ
(ChemPlausibility は M4、マルチスタートは M3 のため未使用)。

**参照元**: `docs/tasks/m2-sequential/TASK-0021.md`, `docs/spec/m2-sequential/requirements.md`(REQ-013/014/102〜104/202),
`docs/spec/m2-sequential/interview-record.md`(Q8), `docs/design/m2-sequential/architecture.md`(D5),
`docs/design/m2-sequential/interfaces.py`(L328-362)

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは純データ構造 + 状態保持クラスのみ。
  numpy 非依存 (SearchResult / Hypothesis を読み、`dataclasses.replace` で新インスタンスを作るだけ)。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト (Decision) + 追記専用レジストリ
  (`accepted` は上書きせず追記/差し替えで表現) + 依存性注入 (ledger / ReviewQueue を外部注入)。
  detect_escalations (純粋関数) と ReviewQueue (追記型) を組み合わせるオーケストレータ。
- **モジュール配置**: `src/tsumugin/selection/engine.py` に **追記** (既存 detect_escalations の下)。
  `selection/__init__.py` に `Decision` / `FinalSelectionEngine` を re-export 追加。
- **参照元**: `docs/spec/m2-sequential/note.md`, `pyproject.toml`, `CLAUDE.md`,
  `docs/design/m2-sequential/architecture.md`(L42 selection/engine.py 役割行)

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE。
- **型注釈必須** (`any` 回避)。docstring 日本語可、FR/NFR/REQ 番号を docstring に紐づける慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` (line-length 100, target py312)。
- **P2 非破壊性 (最重要)**: `accepted` レジストリは追記のみ (削除 API なし)。accept/revert は
  `dataclasses.replace` の新 Hypothesis 生成で表現し、**入力 SearchResult は 1 バイトも変更しない** (D5)。
  revert は削除でなく status=`superseded` への遷移で、旧裁定は ledger に履歴として残す (REQ-202)。
- **単一 accept 経路 (REQ-013)**: 仮説の accepted 化は `accept()` (および agent 自動時に内部的に同経路)
  だけで行い、他の抜け道を作らない。
- **NFR-102 再現性/決定論**: 乱数不使用。decide の分岐・rationale 文字列・返り値は同一入力でビット同一。
- **ledger 記録 (REQ-014/104)**: set_mode / accept / revert / provisional は ledger に理由付きで追記。
  payload は canonical JSON 可能な素の型 (str/int/float/bool/None) に限る (Ledger.append の制約)。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `docs/spec/m2-sequential/note.md`, `CLAUDE.md`(P2/NFR-102/コーディング規約), 要件 REQ-013/014/104

---

## 3. 関連実装 (拡張・参考パターン)

### 直接依拠する既存実装 (本タスクが利用)

- `src/tsumugin/selection/engine.py` (**拡張対象**, TASK-0020):
  - `detect_escalations(result, *, staged_escalated=False, high_r_threshold=30.0) -> tuple[EscalationReason, ...]`
    (L16-60)。純粋関数。**decide 内でこれを呼び**、返り値の空/非空で自動 accept 可否を判定する
    ((d) escalated 条件 = 返り値が空か否か)。同関数は無改変。
- `src/tsumugin/selection/review_queue.py` (TASK-0020):
  - `ReviewQueue(ledger=None)`: `.add(reason, *, hypothesis_id=None, frame_index=None, detail="")` /
    `.resolve(item_id, *, note="")` / `.items` / `.unresolved` (追記型、削除 API なし)。
    decide でエスカレーション時に各 reason を `.add()` する。engine が queue を注入されなければ内部生成。
  - `EscalationReason` = `Literal["all_high_r","unknown_phase","close_competitor","guard_escalated"]`。
    Decision.escalations の要素型。
- `src/tsumugin/model/hypothesis.py`:
  - `Hypothesis` (frozen, L25-36): `id` / `phases` / `parent_id` / `metrics: RefinementMetrics|None` /
    **`status: HypothesisStatus`** (L33) / **`accepted_by: Literal["agent","human",None]`** (L34) / `frame_range`。
  - `HypothesisStatus` (L10) = `Literal["candidate","refined","accepted","rejected","superseded"]`。
    accept 時は `replace(h, status="accepted", accepted_by=by)`、revert 時は `replace(h, status="superseded")`。
  - **`with_updates()` は Hypothesis に無い** — CLAUDE.md の「with_updates」は他モデルの慣習。ここは
    素の `dataclasses.replace(hyp, ...)` で非破壊更新する (frozen dataclass のため再代入不可)。
- `src/tsumugin/search/tree.py`:
  - `SearchResult` (frozen, L94-111): `ranked: tuple[RankedHypothesis, ...]` (良い順) /
    `hypotheses: Mapping[str, Hypothesis]` (全ノード) / `unmatched` / `ledger` / `snapshots`。
    - **best = `result.ranked[0]`** (良い順先頭)。空なら裁定対象ゼロ (TC-107-08)。
    - accept(result, hypothesis_id) の対象は `result.hypotheses[hypothesis_id]` または ranked から引く。
    - **decide/accept は result.ledger でなく engine 注入 ledger に記録**する (result 非破壊、D5)。
- `src/tsumugin/evidence/ranking.py`:
  - `RankedHypothesis` (frozen, L13-18): `hypothesis` / `evidence: EvidenceResult` / `probability` /
    **`close_competitor: bool`**。自動 accept 条件 (b) は `ranked[0].close_competitor is False`。
    rationale の定量根拠 (probability / evidence.value) の供給源。
  - **落とし穴**: `rank()` では最良 `ranked[0]` 自身も `(0 < close_threshold)` で
    `close_competitor=True` になりうる (L54)。Q8 条件 (b) は「best が僅差競合でない」=
    `ranked[0].close_competitor is False` を素直に見る (detect_escalations の close_competitor は
    2 位基準だが、Q8 自動 accept 判定は best 自身のフラグを見る点に留意。両者の意味差をテストで固定する)。
- `src/tsumugin/store/ledger.py`:
  - `Ledger.append(kind, payload) -> LedgerEntry` (L70-83)。set_mode / accept / revert / provisional を
    追記。payload は素の型に限る (item_id/mode/hypothesis_id/rationale 等は str/None)。追記専用・削除なし。

### 参考にする既存パターン

- `src/tsumugin/selection/review_queue.py` の `ReviewQueue`: 「追記型 + 内部 list を tuple で公開 +
  ledger 注入時のみ記録」パターン。`FinalSelectionEngine.accepted` レジストリも同じ思想 (dict を
  Mapping で公開、追記のみ)。
- `src/tsumugin/store/snapshot.py` の非破壊 revert 思想 (revert は追記で表現、元を消さない)。

### 設計契約 (interfaces.py 準拠、そのまま実装可)

```python
# docs/design/m2-sequential/interfaces.py L328-362
@dataclass(frozen=True)
class Decision:                               # selection/engine.py に追記
    mode: Literal["agent", "human"]
    accepted: Hypothesis | None               # accepted 化された新インスタンス
    provisional_id: str | None                # 暫定裁定 (agent+エスカレーション時) FR-403
    recommended_id: str | None                # human モードの推奨
    escalations: tuple[EscalationReason, ...]
    rationale: str                            # 自然言語 + 定量根拠 FR-402

class FinalSelectionEngine:                   # selection/engine.py に追記
    def __init__(self, *, mode="agent", ledger: Ledger | None = None,
                 queue: ReviewQueue | None = None) -> None: ...
    def set_mode(self, mode) -> None: ...                       # ledger 記録 REQ-104
    def decide(self, result: SearchResult, *, frame_index=None) -> Decision: ...
    def accept(self, result: SearchResult, hypothesis_id: str, *, by) -> Hypothesis: ...
    def revert(self, hypothesis_id: str, *, note="") -> Hypothesis: ...  # superseded REQ-202
    @property
    def accepted(self) -> Mapping[str, Hypothesis]: ...         # 裁定レジストリ (追記のみ)
```

- **参照元**: `docs/design/m2-sequential/interfaces.py`(L328-362),
  `src/tsumugin/selection/{engine,review_queue}.py`, `src/tsumugin/model/hypothesis.py`,
  `src/tsumugin/search/tree.py`, `src/tsumugin/evidence/ranking.py`, `src/tsumugin/store/ledger.py`

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py` L328-362
  (Decision / FinalSelectionEngine)。L299-325 の EscalationReason / ReviewItem / ReviewQueue と
  L340-342 の detect_escalations は TASK-0020 実装済みで、本タスクはそれらの上に構築する。
- **アーキテクチャ D5**: `docs/design/m2-sequential/architecture.md` L79-83 —
  `FinalSelectionEngine.decide(result)` は **SearchResult を変更せず** `Decision` を返す。accepted 化は
  **新しい Hypothesis インスタンス** (status/accepted_by 更新) を自身のレジストリと ledger に記録。
  revert は superseded 化の追記 (REQ-202)。L42 表: `selection/engine.py` = FinalSelectionEngine+Decision
  (REQ-013/014/102〜104/202)。
- **データフロー**: `docs/design/m2-sequential/dataflow.md` — SearchResult → detect_escalations →
  mode 分岐 (agent 自動 accept / human 推奨のみ)。エスカレーション非ゼロ時は provisional + ReviewQueue
  追記で処理をブロックしない。
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-013 (L62-63): final_selection_mode: agent|human。accepted 化は**単一 API 経由でのみ**。
  - REQ-014 (L64-65): 裁定は根拠 (evidence 値・確率・僅差競合・未知相フラグ) 付きで ledger 記録。
    `accepted_by: agent|human` を仮説に記録。
  - REQ-102 (L75-77): agent モードは最良が僅差競合なし・未知相なしのとき自動 accepted。
    エスカレーション条件下では暫定裁定 + Review Queue 通知。
  - REQ-103 (L78-79): human モードは推奨順位と根拠の提示のみ。accepted 化は human 明示 API のみ。
  - REQ-104 (L80): モードは実行中いつでも切替可能。切替は ledger 記録。
  - REQ-202 (L89-90): accepted 仮説の差し戻し → status=superseded、履歴 (旧裁定) は ledger 保持 (削除しない)。
  - EDGE-004 (L118): agent モードで裁定対象仮説ゼロ → accept せずエスカレーションのみ。
- **インタビュー Q8**: `docs/spec/m2-sequential/interview-record.md` L47-51 — agent 自動 accept の
  4 条件 (rank 1 / close_competitor=False / unknown_phase_flag=False / escalated=False)。欠けたら
  暫定裁定 (best を provisional 記録) + Review Queue。ChemPlausibility は M4・マルチスタートは M3 で未使用。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` FR-402 (最終選択 2 モード) / FR-403 (エスカレーション + Review Queue)。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest tests/test_selection.py` (本タスク) / `uv run pytest` (全体回帰) /
  `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。
- **本タスクのテストファイル**: `tests/test_selection.py` (**既存に追記**)。TASK-0020 の 21 テスト
  (detect_escalations 6 + ReviewQueue/ReviewItem 系) は 1 行も変更せず green を維持する。
- **既存ヘルパの再利用** (L43-68): `_ranked(hyp_id, rwp, close)` と `_result(ranked, *, unknown_phase=False)`
  が既にある。TASK-0021 のテストダブルもこれを流用/拡張する。
  - `_ranked`: `metrics.rwp` と `close_competitor` だけ意味を持つ最小 RankedHypothesis を作る。
    Q8 自動 accept 判定 (close_competitor) と rationale の定量根拠に使える。
  - `_result`: 木探索を回さず `ranked` / `unmatched(unknown_phase_flag)` だけ最小構成した SearchResult。
    ledger/snapshots は空。**decide/accept が result を変更しないこと (D5) をこのダブルで検証**する。
    - `hypotheses` は `{r.hypothesis.id: r.hypothesis for r in ranked}` で自動生成される
      → `accept(result, hypothesis_id)` の対象引き当てにそのまま使える。
- **テスト観点 (完了条件 → テストケース対応)**:
  - agent + 明確な最良 (close_competitor=False, unknown_phase=False, escalated なし) → decide が
    `accepted != None` / `accepted.accepted_by=="agent"` / `accepted.status=="accepted"` / ledger に根拠記録。
  - agent + 僅差 (`_ranked(..., close=True)` を 2 位に or best.close_competitor=True) → `accepted is None` /
    `provisional_id` 設定 / `escalations` 非空 / queue.items 追加 / decide が例外なく完了。
  - human モード → decide が `accepted is None` / `recommended_id` 設定。その後 `accept(result, id, by="human")`
    → 返り値 `accepted_by=="human"` / `engine.accepted[id]` に登録。
  - set_mode → `engine.set_mode("human")` 後 ledger.entries に mode 切替 kind が存在。
  - revert → accept 済み仮説を revert → 返り値 `status=="superseded"` / ledger に旧裁定 + revert 履歴が残る
    (件数が減らない)。
  - ranked 空 → `_result([])` を decide → `accepted is None` かつ escalation のみ (accept API 未呼び)。
  - 非破壊 → decide/accept 前後で `result.ranked` の要素 (id/status/accepted_by) が不変であること。
- **命名/記述パターン** (既存 test_selection.py / test_model_m2.py に準拠):
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
  - ledger 検証は engine 注入 `Ledger()` の `.entries` の kind を確認 (`result.ledger` でなく engine 側)。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で既存 (test_selection.py 21 件含む) を無改変 green +
  新規 TASK-0021 テスト green。
- **参照元**: `pyproject.toml`, `tests/test_selection.py`(L1-68 ヘルパ), `tests/test_model_m2.py`,
  `docs/spec/m2-sequential/acceptance-criteria.md`(TC-107-01〜05/08)

---

## 6. 注意事項

### 技術的制約

- **非破壊性 D5 (最重要)**: `decide` / `accept` は入力 `SearchResult` を絶対に変更しない。accepted 化は
  `dataclasses.replace(hyp, status="accepted", accepted_by=by)` で**新 Hypothesis** を作り、engine の
  `accepted` レジストリと注入 ledger に記録するだけ。`result.ranked` / `result.hypotheses` の要素は不変。
  ledger も `result.ledger` でなく **engine 注入 ledger** に書く (result を汚さない)。
- **agent 自動 accept は AND 4 条件 (Q8)**: (a) best 存在 (ranked 非空) / (b) `ranked[0].close_competitor
  is False` / (c) `unmatched.unknown_phase_flag is False` / (d) `detect_escalations(...)` が空タプル。
  4 条件すべて満たすときのみ auto accept。1 つでも欠ければ **暫定裁定** (provisional_id = best.id 記録 +
  各 escalation reason を ReviewQueue.add) とし、**accepted は None のまま処理を完了する** (ブロック禁止)。
- **detect_escalations と Q8 close の意味差**: detect_escalations の `close_competitor` reason は 2 位基準
  (`ranked[1].close_competitor`)、Q8 自動 accept 条件 (b) は best 自身 (`ranked[0].close_competitor`) を見る。
  混同しないこと。escalated 判定 (d) は detect_escalations の返り値が空か否かで見る (staged_escalated は
  呼び出し側から decide に渡せる経路を用意するか、当面 False 既定でよい — interfaces では decide 引数に
  staged_escalated は無いため、ガード起因のエスカレーションは呼び出し側が別途 queue.add する設計余地)。
- **human モードは自動 accept しない (REQ-103)**: decide は `recommended_id = best.id` を返すのみ。
  accepted 化は `accept(result, id, by="human")` 明示呼び出しでのみ発生。decide 時点で escalation 検出は
  行い ReviewQueue へ通知してよい (human でも根拠提示のため)。
- **単一 accept 経路 (REQ-013)**: 仮説 accepted 化のロジックは `accept()` に集約。agent 自動 accept も
  内部で同じ accept 経路 (by="agent") を通す実装が望ましい (重複ロジック回避)。
- **revert は superseded 追記 (REQ-202)**: `revert(hypothesis_id)` は `accepted` レジストリの当該仮説を
  `replace(hyp, status="superseded")` にし、旧裁定 + revert 操作を ledger に追記する。**元の accept 履歴
  (ledger エントリ) は削除しない**。accepted レジストリ自体も件数を減らさず状態遷移で表現 (P2)。
- **rationale の決定論 (NFR-102)**: rationale は自然言語 + 定量根拠 (best.id / probability / evidence 値 /
  close_competitor / unknown_phase / escalations) を固定順で組む文字列。同一入力でビット同一 (乱数・時刻不使用)。
- **ledger payload は素の型のみ**: set_mode → `{"mode": ...}`、accept → `{"hypothesis_id":..., "by":...,
  "rationale":...}`、revert → `{"hypothesis_id":..., "note":..., "from_status":..., "to_status":"superseded"}` 等。
  Hypothesis や dataclass を payload に入れない (canonical JSON 化のため str/int/float/bool/None に限る)。

### スコープ境界 (やり過ぎ防止)

- 本タスクは **Decision + FinalSelectionEngine (set_mode/decide/accept/revert/accepted) のみ**。
  detect_escalations / ReviewQueue / ReviewItem は TASK-0020 実装済みで**無改変で利用**する。
- **changepoint 局所探索・シーケンシャル実行との統合 (REQ-101/105) は本タスク外** (別タスク)。
  decide は単一 SearchResult に対する裁定のみ。frame_index は ReviewItem への付与用の受け渡し引数。
- **native sequential・Web UI 表示 (FR-421)・ChemPlausibility (M4)・マルチスタート (M3) は対象外**。
  自動 accept は Q8 の 4 材料のみで判定 (M2 利用可能材料に限定)。
- **専用永続化はしない**: accepted レジストリの永続化は ledger 経由再構築で足りる (D-Q7 と同思想)。

### 後続タスクへの影響

- **後続**: TASK-0022 が本エンジンを利用。`Decision` 各フィールド・`FinalSelectionEngine` の 6 メンバ
  シグネチャは interfaces.py L328-362 の契約どおりに固定する。
- `selection/__init__.py` に `Decision` / `FinalSelectionEngine` を re-export 追加しておく
  (現状は EscalationReason / ReviewItem / ReviewQueue / detect_escalations の 4 つを export)。

- **参照元**: `docs/spec/m2-sequential/note.md`, `docs/design/m2-sequential/interfaces.py`(L328-362),
  `docs/design/m2-sequential/architecture.md`(D5), `docs/spec/m2-sequential/interview-record.md`(Q8),
  `CLAUDE.md`(P2/NFR-102/コーディング規約), `src/tsumugin/selection/{engine,review_queue}.py`,
  `src/tsumugin/model/hypothesis.py`

---

## 収集したファイル一覧

- タスク: `docs/tasks/m2-sequential/TASK-0021.md` (完了条件 7 項目)
- 仕様/要件: `docs/spec/m2-sequential/requirements.md` (REQ-013/014/102〜104/202, EDGE-004),
  `docs/spec/m2-sequential/interview-record.md` (Q8 自動 accept 4 条件),
  `docs/spec/m2-sequential/acceptance-criteria.md` (TC-107-01〜05/08)
- 設計: `docs/design/m2-sequential/interfaces.py` (L328-362 Decision/FinalSelectionEngine),
  `docs/design/m2-sequential/architecture.md` (D5, L42 役割表), `docs/design/m2-sequential/dataflow.md`
- 既存実装 (依拠): `src/tsumugin/selection/engine.py` (detect_escalations, TASK-0020),
  `src/tsumugin/selection/review_queue.py` (ReviewQueue/ReviewItem/EscalationReason, TASK-0020),
  `src/tsumugin/model/hypothesis.py` (Hypothesis.status/accepted_by, HypothesisStatus),
  `src/tsumugin/search/tree.py` (SearchResult), `src/tsumugin/evidence/ranking.py` (RankedHypothesis),
  `src/tsumugin/store/ledger.py` (Ledger.append)
- テスト参考: `tests/test_selection.py` (L1-68 ヘルパ _ranked/_result, 既存 21 テスト),
  `tests/test_model_m2.py`, `pyproject.toml`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
