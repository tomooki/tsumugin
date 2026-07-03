# TASK-0020 TDD 開発コンテキストノート

**タスク**: ReviewQueue + detect_escalations (最終選択エンジンのエスカレーション基盤)
**要件名**: m2-sequential / **タスクID**: TASK-0020 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 3 - エンジン / **信頼性**: 🔵 FR-403 / REQ-015 / 設計 D6・D-Q7
**作成日時**: 2026-07-03 / **ブランチ**: milestone/m2-sequential

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

`selection/` パッケージ (**新規**) を作り 2 つの成果物を実装する:

1. `selection/review_queue.py`: `ReviewItem` (frozen dataclass) と `ReviewQueue` (追記型クラス)。
   - `ReviewItem`: `item_id`("rq-0000" 連番) / `reason`(EscalationReason) / `hypothesis_id`(str|None) /
     `frame_index`(int|None) / `detail`(str) / `resolved`(bool=False)。
   - `ReviewQueue(ledger=None)`: `add(reason, *, hypothesis_id=None, frame_index=None, detail="")` /
     `resolve(item_id, *, note="")`(解決マーク**追記**) / `items`(property, 全件) /
     `unresolved`(property, 未解決のみ)。**削除 API を実装しない** (P2)。ledger 注入時は
     `add`→"review_add" / `resolve`→"review_resolve" を ledger にも記録 (D-Q7)。
2. `selection/engine.py` (**新規、本タスクは detect_escalations のみ**): 純粋関数
   `detect_escalations(result, *, staged_escalated=False, high_r_threshold=30.0) -> tuple[EscalationReason, ...]`。
   - 4 条件を検出: (a) `all_high_r`(全 ranked 仮説 Rwp > 閾値) / (b) `unknown_phase`
     (`result.unmatched.unknown_phase_flag`) / (c) `close_competitor`(1-2 位 ΔBIC < 閾値、
     `result.ranked[1].close_competitor`) / (d) `guard_escalated`(引数 `staged_escalated=True`)。

**🚨 絶対制約 (完了条件と直結)**:
- **4 条件それぞれが単独で検出される** (SearchResult のテストダブルで) 🔵 *TC-107-06*
- **条件なしで空タプル** `()` を返す 🔵
- **Queue は追記型**: `resolve` 後も `items` に残り `resolved=True`、**削除 API 不在** 🔵 *TC-107-07*
- **ledger 連携時** `review_add` / `review_resolve` が記録される 🔵 *D-Q7*
- **item_id 連番の決定論**: 追加順に `rq-0000`, `rq-0001`, … (乱数不使用) 🔵
- **detect_escalations は純粋関数**: SearchResult 非破壊・副作用なし・同一入力でビット同一 🔵 *D6/NFR-102*
- **git commit しない** (ユーザー判断。本セッション制約)。

**参照元**: `docs/tasks/m2-sequential/TASK-0020.md`, `docs/spec/m2-sequential/requirements.md`(REQ-015),
`docs/design/m2-sequential/architecture.md`(D6), `docs/design/m2-sequential/design-interview.md`(D-Q7)

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは純データ構造 + 純粋関数のみで
  numpy にも Protocol にも依存しない (SearchResult を読むだけ)。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト (ReviewItem) + 追記専用コレクション
  (ReviewQueue、Ledger と同じ「append のみ・削除 API なし」思想) + 純粋関数 (detect_escalations)。
- **モジュール配置**: `src/tsumugin/selection/` 配下 (**新規パッケージ**、`__init__.py` / `review_queue.py` /
  `engine.py`)。architecture.md ディレクトリ構造では `selection/` = engine(2モード) + review_queue。
- **参照元**: `docs/spec/m2-sequential/note.md`, `pyproject.toml`, `CLAUDE.md`,
  `docs/design/m2-sequential/architecture.md`(L89-97 ディレクトリ構造)

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE。
- **型注釈必須** (`any` 回避)。docstring 日本語可、FR/NFR/REQ 番号を docstring に紐づける慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` (line-length 100, target py312)。
- **P2 非破壊性 (最重要)**: Ledger/Snapshot と同様、ReviewQueue に**削除・上書き API を実装しない**。
  resolve は「解決フラグを立てた新 ReviewItem を items へ反映」する追記表現 (元 item は履歴として残す
  か、resolved=True の新インスタンスで置換だが件数は減らさない — TC-107-07 は「resolve 後も items に
  残り resolved=True、削除 API 不在」を要求)。
- **NFR-102 再現性/決定論**: 乱数不使用。item_id は追加順連番、detect_escalations の返り値順序は固定。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `docs/spec/m2-sequential/note.md`, `CLAUDE.md`(実装上の不変条件 P2/NFR-102)

---

## 3. 関連実装 (拡張・参考パターン)

### 依拠する既存実装 (再利用・読み取り対象)

- `src/tsumugin/search/tree.py`:
  - `SearchResult` (frozen dataclass, L94-174): `ranked: tuple[RankedHypothesis, ...]` /
    `hypotheses: Mapping[str, Hypothesis]` / `unmatched: UnmatchedPeakReport` / `ledger` / `snapshots` 他。
    detect_escalations の入力。**このうち読むのは `ranked` と `unmatched` のみ**。
  - `_compute_unmatched` (L827-886): `unknown_phase_flag` は「未マッチ非空」**または**「全 refined 仮説
    Rwp > high_r_threshold」で立つ。→ detect_escalations では `all_high_r` と `unknown_phase` は
    別 reason だが、SearchResult 側では all-high-R が既に unknown_phase_flag を True にしうる点に注意。
    テストダブルでは両者を独立に構成して単独検出を検証する。
  - `high_r_threshold` 既定は SearchConfig でも `30.0` (L90)。detect_escalations の既定引数と一致。
- `src/tsumugin/evidence/ranking.py`:
  - `RankedHypothesis` (frozen, L13-18): `hypothesis` / `evidence: EvidenceResult` / `probability` /
    `close_competitor: bool`。
  - `rank()` (L21-60): `close_competitor = (res.value - best_value) < close_threshold`。
    **最良 (ranked[0]) 自身は 0 < 閾値 で常に close_competitor=True**。よって「僅差競合」判定は
    `ranked[1]`(2 位) が close_competitor=True かどうかで見る (D6「1-2 位 ΔBIC < 閾値」)。
    → detect_escalations は `len(result.ranked) >= 2 and result.ranked[1].close_competitor` で (c) を判定。
- `src/tsumugin/refinement/staged.py`:
  - `RefinementReport.escalated: bool` (L57-62): max_retries(既定 3)回ガード違反で `escalated=True`
    (`run()` L177-188 で "escalate" ledger 記録)。→ これが detect_escalations の `staged_escalated`
    引数の供給源 (REQ-015 (d)「ガード 3 連続発動」)。本タスクは bool を受けるだけで staged 依存はしない。
- `src/tsumugin/store/ledger.py`:
  - `Ledger.append(kind, payload) -> LedgerEntry` (L70-83)。ReviewQueue は注入された ledger に
    `review_add` / `review_resolve` を append する (D-Q7)。payload は canonical JSON 可能な素の型に限る
    (`default=str` で保険はあるが item_id/reason/detail 等の str/int/None に留める)。追記専用・削除なし。

### 参考にする M2 既存パターン (同時期タスクの実装済み)

- `src/tsumugin/sequential/` (series/changepoint/lifecycle/thermal/trajectory/engine.py): M2 で先行実装済みの
  パッケージ。`selection/` も同じ「1 モジュール 1 責務 + frozen dataclass + 純粋関数」構成に倣う。
- `src/tsumugin/model/channel.py` (TASK-0011): 新規モジュール + `__init__.py` re-export の作法。

### 設計契約 (interfaces.py 準拠、そのまま実装可)

```python
# docs/design/m2-sequential/interfaces.py L299-342
EscalationReason = Literal[
    "all_high_r", "unknown_phase", "close_competitor", "guard_escalated"
]  # FR-403 (M2 で利用可能な 4 条件。吸収補正は M3)

@dataclass(frozen=True)
class ReviewItem:                         # selection/review_queue.py
    item_id: str                          # "rq-0000" 連番
    reason: EscalationReason
    hypothesis_id: str | None
    frame_index: int | None
    detail: str
    resolved: bool = False                # resolve は追記で表現 (P2)

class ReviewQueue:                        # 追記型キュー。削除 API なし
    def __init__(self, ledger: Ledger | None = None) -> None: ...
    def add(self, reason, *, hypothesis_id=None, frame_index=None, detail="") -> ReviewItem: ...
    def resolve(self, item_id, *, note="") -> ReviewItem: ...   # 解決マーク追記
    @property
    def items(self) -> tuple[ReviewItem, ...]: ...
    @property
    def unresolved(self) -> tuple[ReviewItem, ...]: ...

def detect_escalations(                   # selection/engine.py  (D6 純粋関数)
    result: SearchResult, *, staged_escalated: bool = False, high_r_threshold: float = 30.0
) -> tuple[EscalationReason, ...]: ...
```

- **参照元**: `docs/design/m2-sequential/interfaces.py`(L299-342),
  `src/tsumugin/search/tree.py`, `src/tsumugin/evidence/ranking.py`,
  `src/tsumugin/refinement/staged.py`, `src/tsumugin/store/ledger.py`

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m2-sequential/interfaces.py` L299-342
  (EscalationReason / ReviewItem / ReviewQueue / detect_escalations)。L345-362 の
  `FinalSelectionEngine` / `Decision` は**後続 TASK-0021 のスコープ**で本タスクでは実装しない。
- **アーキテクチャ D6**: `docs/design/m2-sequential/architecture.md` L84-87 —
  `detect_escalations(result, staged_escalated) -> tuple[EscalationReason, ...]` は純粋関数。
  4 条件 = (a) 全仮説 Rwp > 閾値 / (b) unknown_phase_flag / (c) 1-2 位 ΔBIC < 閾値 (close_competitor) /
  (d) ガードエスカレーション。「M2 で利用可能な材料のみ (吸収補正モードは M3)」。
  L41 アーキテクチャ表: `selection/review_queue.py` = ReviewQueue(追記型) + ReviewItem (REQ-015)。
- **設計判断 D-Q7**: `docs/design/m2-sequential/design-interview.md` L41-45 —
  ReviewQueue は独立の追記型コレクション (ledger 注入時は add/resolve を ledger にも記録)。
  キュー自体の専用永続化は M2 では**実装しない** (ledger 経由の再構築で足りる)。
- **データフロー**: `docs/design/m2-sequential/dataflow.md` L84-98 — SearchResult → detect_escalations
  (高R/未知相/僅差/ガード) → mode 分岐。エスカレーション非ゼロ時は provisional + ReviewQueue 追記で
  **処理をブロックしない**。ReviewQueue は追記型ストア。
- **要件**: `docs/spec/m2-sequential/requirements.md`
  - REQ-013 (L62-64): final_selection_mode: agent|human を持つ最終選択エンジン (エンジン本体は TASK-0021)。
  - REQ-014 (L64-65): 裁定は根拠付きで ledger に記録。
  - REQ-015 (L66-68): エスカレーション条件 (a)全仮説高R / (b)未知相フラグ / (c)僅差競合(ΔBIC<閾値) /
    (d)ガード 3 連続発動(escalated report) を検出し Review Queue(追記型)へ通知。**処理はブロックしない**。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` FR-403 (エスカレーション + Review Queue)。
- **参照元**: 上記各ファイル

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest tests/test_selection.py` (本タスク単体) / `uv run pytest` (全体回帰) /
  `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。
- **本タスクのテストファイル**: `tests/test_selection.py` (**新規**)。既存テストは 1 行も変更しない。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py` (現状 27 ファイル)。
  `tests/conftest.py` に共通フィクスチャ。
- **テストダブル方針** (完了条件「SearchResult のテストダブル」):
  - detect_escalations の入力 SearchResult は**完全な木探索を回さず**、`ranked` / `unmatched` だけを
    最小構成した軽量ダブルを作る。方法は 2 案:
    (1) 実 `SearchResult` を最小フィールドで直接構築 (frozen なので値を渡すだけ。ranked に
        `RankedHypothesis(hypothesis=Hypothesis(...metrics=RefinementMetrics(rwp=...)), evidence=..., 
        probability=..., close_competitor=...)`、unmatched に `UnmatchedPeakReport(..., unknown_phase_flag=...)`)。
    (2) 必要 3 属性 (`ranked` / `unmatched` / `hypotheses`) だけ持つ軽量スタブオブジェクト。
    → detect_escalations が読むのは `result.ranked` (各 `.hypothesis.metrics.rwp` と `.close_competitor`) と
      `result.unmatched.unknown_phase_flag` のみなので、この 2 経路を組めるダブルで 4 条件を独立に発火できる。
  - `RefinementMetrics` は `src/tsumugin/model/hypothesis.py`、`UnmatchedPeakReport` は
    `src/tsumugin/search/matcher.py`、`RankedHypothesis`/`EvidenceResult` は
    `src/tsumugin/evidence/ranking.py`・`base.py`。
  - ledger 連携テストは実 `Ledger()` を渡し `ledger.entries` の kind を検証 (review_add/review_resolve)。
- **命名/記述パターン** (`tests/test_model_m2.py` / M1 テスト群に準拠):
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - docstring/コメントに 【テスト目的】【テスト内容】【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で既存テストを無改変 green のまま維持 + 新規 test_selection.py green。
- **参照元**: `pyproject.toml`, `tests/test_model_m2.py`, `tests/conftest.py`,
  `docs/spec/m2-sequential/acceptance-criteria.md`(TC-107-06/07)

---

## 6. 注意事項

### 技術的制約

- **close_competitor の落とし穴 (最重要)**: `rank()` では最良 `ranked[0]` 自身も
  `(0 < close_threshold)` で **close_competitor=True になる**。よって「1 件でも close_competitor=True」で
  判定すると必ず発火してしまう。D6 は「1-2 位 ΔBIC < 閾値」なので、**2 位以降に close_competitor=True が
  あるか** (= `len(ranked) >= 2 and ranked[1].close_competitor`) で (c) を判定すること。
- **all_high_r の空ガード**: `ranked` が空のとき `all(...)` は真空的に True を返す。空 ranked (候補ゼロ経路)
  では all_high_r を**発火させない** (`ranked` 非空 かつ 全件 rwp > 閾値 のときのみ)。
  また `metrics is None` の仮説を混ぜない (rwp 参照前に None ガード)。境界は厳密比較 `>` (閾値ちょうどは
  高 R に含めない。tree.py `_compute_unmatched` L855 と統一)。
- **unknown_phase は SearchResult 側の集約結果を信頼**: `result.unmatched.unknown_phase_flag` を
  そのまま (b) の真偽として使う。detect_escalations 内で未マッチ再計算はしない (D6「純粋関数」・材料の再利用)。
- **返り値順序の決定論**: 4 reason を返す順序を固定する (推奨: EscalationReason Literal の宣言順
  all_high_r → unknown_phase → close_competitor → guard_escalated)。同一入力でビット同一 (NFR-102)。
- **detect_escalations は完全な純粋関数**: SearchResult を変更しない、ledger に書かない、乱数を使わない。
  ledger 記録を行うのは ReviewQueue 側 (add/resolve) と後続 FinalSelectionEngine (TASK-0021)。
- **ReviewQueue の追記性 (P2)**: `resolve` は削除でなく resolved=True への状態遷移。`items` の件数は
  resolve で減らない。`unresolved` は `items` から resolved=False を絞り込む派生ビュー。削除・pop・clear の
  類の API を**一切生やさない** (Ledger/Snapshot と同じ構造的非破壊保証)。
- **frozen dataclass**: `ReviewItem` は `@dataclass(frozen=True)`。resolve 時は `dataclasses.replace(item,
  resolved=True)` で新インスタンスを作り内部リストの該当要素を差し替える (件数不変、元 item は不変)。

### スコープ境界 (やり過ぎ防止)

- 本タスクは **ReviewQueue + ReviewItem + detect_escalations の 3 点のみ**。
  `FinalSelectionEngine` / `Decision` / agent・human モード裁定 / accept / revert は
  **後続 TASK-0021** のスコープ (interfaces.py L328-362)。engine.py には detect_escalations だけ置く
  (FinalSelectionEngine は TASK-0021 で同ファイルに追記)。
- ReviewQueue の**専用永続化はしない** (D-Q7: ledger 経由再構築で足りる)。Web UI 表示 (FR-421) は M3。
- 吸収補正モードのエスカレーション条件は M3 (EscalationReason は 4 値に留める)。

### 後続タスクへの影響

- **後続**: TASK-0021 (FinalSelectionEngine) が本タスクの `detect_escalations` と `ReviewQueue` を
  利用する。`EscalationReason` の 4 値・`detect_escalations` シグネチャ・`ReviewQueue.add/resolve`
  シグネチャは interfaces.py の契約どおりに固定すること。
- `selection/__init__.py` で `ReviewItem` / `ReviewQueue` / `detect_escalations` / `EscalationReason` を
  re-export しておくと TASK-0021 が参照しやすい。

- **参照元**: `docs/spec/m2-sequential/note.md`, `docs/design/m2-sequential/interfaces.py`,
  `docs/design/m2-sequential/architecture.md`(D6), `docs/design/m2-sequential/design-interview.md`(D-Q7),
  `CLAUDE.md`(不変条件 P2/NFR-102), `src/tsumugin/search/tree.py`, `src/tsumugin/evidence/ranking.py`

---

## 収集したファイル一覧

- タスク: `docs/tasks/m2-sequential/TASK-0020.md` (+ 後続 `TASK-0021.md` でスコープ境界確認)
- 仕様/要件: `docs/spec/m2-sequential/{requirements,acceptance-criteria,note}.md` (REQ-013/014/015, TC-107-06/07)
- 設計: `docs/design/m2-sequential/{interfaces.py,architecture.md,dataflow.md,design-interview.md}`
  (interfaces L299-342, architecture D6, dataflow L84-98, design-interview D-Q7)
- 既存実装 (依拠): `src/tsumugin/search/tree.py` (SearchResult/_compute_unmatched),
  `src/tsumugin/evidence/ranking.py` (RankedHypothesis/rank/close_competitor),
  `src/tsumugin/refinement/staged.py` (RefinementReport.escalated),
  `src/tsumugin/store/ledger.py` (Ledger.append)
- 参考パターン: `src/tsumugin/sequential/*` (M2 新規パッケージ構成), `src/tsumugin/model/channel.py` (新規モジュール作法)
- テスト参考: `tests/test_model_m2.py`, `tests/conftest.py`, `pyproject.toml`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
