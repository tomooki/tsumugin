# TASK-0020 ReviewQueue + detect_escalations TDD要件定義書

**機能名**: ReviewQueue + detect_escalations (最終選択エンジンのエスカレーション基盤)
**タスクID**: TASK-0020
**要件名**: m2-sequential
**タスクタイプ**: TDD / **推定工数**: 3h / **フェーズ**: Phase 3 - エンジン
**作成日**: 2026-07-03
**出力ファイル**: `docs/implements/m2-sequential/TASK-0020/review-queue-escalation-requirements.md`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M2 最終選択エンジンの土台となる 2 つの部品を実装する。
  (1) **`detect_escalations`** — `SearchResult` を入力に取り、エスカレーションが必要な 4 条件を検出して
  `tuple[EscalationReason, ...]` を返す**純粋関数**。(2) **`ReviewQueue` + `ReviewItem`** — 検出された
  エスカレーションを人間の後追い確認のために蓄積する**追記型キュー** (削除 API を持たない)。
- 🔵 **どのような問題を解決するか**: 全自動 Rietveld 解析では「AI が自動裁定してよいケース」と「人間の
  確認が要るケース」を明示分離する必要がある (FR-402/403)。本タスクはその判定材料 (エスカレーション条件の
  検出) と通知先 (Review Queue) を用意し、**処理をブロックせずに** 要確認事項を後から見直せるようにする。
- 🔵 **想定されるユーザー**: 直接の利用者は後続 TASK-0021 の `FinalSelectionEngine` (裁定時に
  `detect_escalations` を呼び、非ゼロなら暫定裁定 + `ReviewQueue.add`)。間接的には解析結果を後追い確認する
  研究者 (Review Queue を見て resolve する)。
- 🔵 **システム内での位置づけ**: `src/tsumugin/selection/` パッケージ (**新規**) の
  `review_queue.py` (ReviewQueue/ReviewItem) と `engine.py` (detect_escalations)。M0/M1 で確立した
  frozen dataclass 値オブジェクト + 追記専用コレクション (Ledger 思想) + 純粋関数のパターンに準拠する。
  `SearchResult` (search/tree.py) を読み取り専用で参照し、`Ledger` (store/ledger.py) へ任意で追記する。
- **参照したEARS要件**: REQ-015 (エスカレーション条件検出 + Review Queue)、REQ-013/014 (最終選択エンジン/
  根拠 ledger 記録の文脈)、FR-403 (エスカレーション + Review Queue、処理ブロックなし)
- **参照した設計文書**: `docs/design/m2-sequential/architecture.md` D6 (L84-87)・アーキテクチャ表 (L41)、
  `docs/design/m2-sequential/design-interview.md` D-Q7 (L41-45)、
  `docs/design/m2-sequential/dataflow.md` (L84-98)、
  `docs/design/m2-sequential/interfaces.py` (L299-342)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 EscalationReason（型エイリアス / `src/tsumugin/selection/engine.py` または `review_queue.py`）🔵

- 🔵 **定義**: `Literal["all_high_r", "unknown_phase", "close_competitor", "guard_escalated"]`。
  M2 で利用可能な 4 条件のみ (吸収補正モードは M3 スコープ外のため含めない)。
- **参照**: interfaces.py L299-301。

### 2.2 detect_escalations（純粋関数 / `src/tsumugin/selection/engine.py`）🔵

- 🔵 **シグネチャ**:
  `detect_escalations(result: SearchResult, *, staged_escalated: bool = False, high_r_threshold: float = 30.0) -> tuple[EscalationReason, ...]`
- 🔵 **入力パラメータ**:
  - `result: SearchResult` — 木探索結果 (search/tree.py)。本関数が読むのは `result.ranked`
    (各 `RankedHypothesis.hypothesis.metrics.rwp` と `.close_competitor`) と
    `result.unmatched.unknown_phase_flag` のみ。**非破壊で読むだけ**。
  - `staged_escalated: bool = False` — 段階的精密化の `RefinementReport.escalated` (ガード N 連続で True)。
    キーワード専用。呼び出し側 (TASK-0021/フレーム精密化) が供給する。
  - `high_r_threshold: float = 30.0` — 全高 R 判定の Rwp 閾値 (%)。既定は `SearchConfig.high_r_threshold`
    と一致 (search/tree.py L90)。キーワード専用。
- 🔵 **出力**: `tuple[EscalationReason, ...]`。発火した reason のみを**決定論的順序**で含む。
  条件なしなら空タプル `()`。
- 🔵 **4 条件の判定ロジック** (D6 / REQ-015):
  - 🔵 **(a) `all_high_r`**: `result.ranked` が**非空**かつ全 `RankedHypothesis` の
    `hypothesis.metrics.rwp` が `high_r_threshold` を**厳密超過** (`> `) するとき。全仮説が高 R = どれも
    観測を十分説明できていない。空 ranked では発火しない (真空的 True を回避)。`metrics is None` はガード。
  - 🔵 **(b) `unknown_phase`**: `result.unmatched.unknown_phase_flag` が True のとき。未知相フラグ =
    最良仮説で説明できない観測ピークが残っている (SearchResult 側の集約結果をそのまま信頼)。
  - 🔵 **(c) `close_competitor`**: 1-2 位の ΔBIC が閾値未満 (僅差競合)。判定は
    `len(result.ranked) >= 2 and result.ranked[1].close_competitor` で行う。**最良 (ranked[0]) 自身は
    rank() 実装上つねに close_competitor=True になる**ため 1 件目では判定せず、**2 位** の
    close_competitor フラグを見る (D6「1-2 位 ΔBIC < 閾値」)。
  - 🔵 **(d) `guard_escalated`**: 引数 `staged_escalated` が True のとき (ガード N 連続発動 = staged
    エンジンが escalated report を返した)。本関数は bool を受け取るだけで staged に依存しない。
- 🔵 **返り値順序の決定論**: reason は `EscalationReason` の宣言順
  (all_high_r → unknown_phase → close_competitor → guard_escalated) で並べる。同一入力でビット同一 (NFR-102)。
- 🔵 **例**: 全 ranked の rwp=45.0 (>30) の SearchResult → `("all_high_r",)`。
  4 条件すべて満たす → `("all_high_r", "unknown_phase", "close_competitor", "guard_escalated")`。
  条件なし → `()`。
- **参照**: interfaces.py L340-342、architecture.md D6 (L84-87)、search/tree.py `_compute_unmatched`
  (L827-886)、evidence/ranking.py `rank`/`close_competitor` (L54-58)。

### 2.3 ReviewItem（新設 frozen dataclass / `src/tsumugin/selection/review_queue.py`）🔵

- 🔵 **フィールド**:
  - `item_id: str` — "rq-0000" 形式の**追加順連番** (rq-0000, rq-0001, …)。
  - `reason: EscalationReason` — エスカレーション理由。
  - `hypothesis_id: str | None` — 関連仮説 ID (無ければ None)。
  - `frame_index: int | None` — 関連フレーム index (単一パターン解析等では None)。
  - `detail: str` — 補足説明 (自然言語)。既定は空文字を許容。
  - `resolved: bool = False` — 解決済みか。resolve は追記で表現 (P2)。
- 🔵 **振る舞い**: `@dataclass(frozen=True)`。生成・等価比較 (`==`) 可能。再代入は
  `dataclasses.FrozenInstanceError`。resolve は `dataclasses.replace(item, resolved=True)` で新インスタンス化。
- **参照**: interfaces.py L304-313。

### 2.4 ReviewQueue（新設クラス / `src/tsumugin/selection/review_queue.py`）🔵

- 🔵 **コンストラクタ**: `ReviewQueue(ledger: Ledger | None = None)`。ledger 注入時は add/resolve を
  ledger にも記録する (D-Q7)。未注入 (None) でもキュー単体として機能する。
- 🔵 **`add(reason, *, hypothesis_id=None, frame_index=None, detail="") -> ReviewItem`**:
  - 追加順連番 item_id ("rq-{n:04d}") を採番して `ReviewItem(resolved=False)` を生成し内部列へ追記。
  - 生成した ReviewItem を返す。
  - ledger 注入時は `kind="review_add"` を append (payload に item_id/reason/hypothesis_id/frame_index/detail
    の素の型)。
- 🔵 **`resolve(item_id, *, note="") -> ReviewItem`**:
  - 指定 item_id の ReviewItem を `resolved=True` の新インスタンスへ差し替える (件数不変、追記表現)。
  - 差し替え後の ReviewItem を返す。
  - ledger 注入時は `kind="review_resolve"` を append (payload に item_id/note)。
  - 🟡 存在しない item_id を渡した場合の扱いは要件外の縮退。妥当な設計として `KeyError`/`ValueError`
    を送出 (誤操作の防御)。ただし本タスクの完了条件・受け入れ基準はこのケースを要求しない。
- 🔵 **`items` (property)**: これまでに add された全 ReviewItem の不変タプル (resolve 済み含む、**減らない**)。
- 🔵 **`unresolved` (property)**: `items` のうち `resolved is False` のみを絞り込んだ不変タプル (派生ビュー)。
- 🔵 **削除・上書き API を実装しない** (P2 構造的非破壊性。Ledger/Snapshot と同思想)。
- **参照**: interfaces.py L316-325、design-interview.md D-Q7、store/ledger.py `Ledger.append` (L70-83)。

### 2.5 データフロー 🔵

- 🔵 `SearchResult` (またはフレーム裁定要求) → `detect_escalations(result, staged_escalated=...)` →
  `tuple[EscalationReason, ...]`。非ゼロなら後続 (TASK-0021) が `ReviewQueue.add(reason, ...)` で追記 +
  暫定裁定を行い、**処理をブロックしない**。後から `ReviewQueue.unresolved` を見て人間が `resolve` する。
- **参照**: dataflow.md L84-98 (detect_escalations → mode 分岐 → provisional + ReviewQueue 追記)。

- **参照したEARS要件**: REQ-015、FR-403
- **参照した設計文書**: interfaces.py L299-342、architecture.md D6、dataflow.md L84-98、
  既存実装 search/tree.py・evidence/ranking.py・store/ledger.py

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **P2 構造的非破壊性 (最重要 / NFR-101)**: `ReviewQueue` は Ledger/Snapshot と同様、**削除・pop・clear・
  上書き API を一切実装しない**。resolve は削除でなく resolved=True への状態遷移 (件数不変)。ReviewItem は
  frozen で in-place 変更不可。
- 🔵 **detect_escalations は完全な純粋関数 (D6 / NFR-102)**: `SearchResult` を変更しない、ledger に書かない、
  乱数を使わない、グローバル状態を触らない。同一入力で毎回ビット同一のタプルを返す。ledger 記録を行うのは
  `ReviewQueue.add/resolve` 側と後続 `FinalSelectionEngine`。
- 🔵 **決定論 (NFR-102 / REQ-402)**: item_id は追加順連番、detect_escalations の返り値順序は
  EscalationReason 宣言順に固定。乱数不使用。
- 🔵 **処理をブロックしない (FR-403)**: エスカレーション検出は例外送出でなく tuple 返却。上位は暫定裁定 +
  Queue 追記で解析を継続する (本関数はブロック判断をしない、材料を返すのみ)。
- 🔵 **frozen dataclass 制約**: `ReviewItem` は `@dataclass(frozen=True)`。生成・等価比較可能・再代入不可。
- 🔵 **境界の厳密比較**: all_high_r の Rwp 判定は厳密超過 `>` (閾値ちょうどは高 R に含めない)。
  search/tree.py `_compute_unmatched` L855 (`rwp > high_r_threshold`) と表現を統一する。
- 🔵 **型注釈必須**: `Literal` / `SearchResult` / `Ledger | None` / `str | None` / `int | None` /
  `tuple[..., ...]` を正しく付す。`any` 回避。`from __future__ import annotations` を用いる。
- 🔵 **命名規則**: クラス/型は PascalCase、フィールド/関数は snake_case、ファイルは snake_case
  (`review_queue.py` / `engine.py`)。定数は UPPER_SNAKE。
- 🔵 **Lint/フォーマット**: `uvx ruff check src tests` (line-length 100, target py312) 準拠。
- 🔵 **アーキテクチャ制約**: `src/tsumugin/selection/` 配下の新規パッケージ。engine.py には本タスクでは
  detect_escalations のみを置き、`FinalSelectionEngine` は後続 TASK-0021 で追記する。ledger payload は
  canonical JSON 可能な素の型 (str/int/None) に限る。
- 🟡 **ledger 記録の kind 名**: `review_add` / `review_resolve` は interfaces.py に明示はなく D-Q7
  「add/resolve を ledger にも記録」からの妥当な命名 (M0/M1 の kind 命名慣習に倣う)。
- 🔴 **git commit しない** (ユーザー判断。本セッション制約。仕様外の運用指示)。

- **参照したEARS要件**: REQ-015、FR-403、NFR-101、NFR-102、REQ-402
- **参照した設計文書**: interfaces.py、architecture.md (D6/不変条件)、design-interview.md (D-Q7)、
  `CLAUDE.md` (P2/NFR-102 不変条件)、store/ledger.py (追記専用の作法)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

- **エスカレーション検出 (agent 裁定前)**: `reasons = detect_escalations(result, staged_escalated=report.escalated)`
  → 空なら自動 accept、非空なら暫定裁定 + Queue 追記 (TASK-0021)。
- **Queue 追記**: `item = queue.add("close_competitor", hypothesis_id="hyp-0003", frame_index=12,
  detail="ΔBIC=4.2 < 10")` → `ReviewItem(item_id="rq-0000", resolved=False, ...)`。
- **後追い解決**: `queue.resolve("rq-0000", note="人間が hyp-0003 を採択")` →
  `items` に残り `resolved=True`、`unresolved` から外れる。

### 4.2 データフロー 🔵

- `SearchResult` → `detect_escalations` → `tuple[EscalationReason, ...]` → (非ゼロ) → `ReviewQueue.add` ×N +
  ledger `review_add` → 解析継続 (ブロックなし) → 後日 `unresolved` 確認 → `resolve` + ledger `review_resolve`。

### 4.3 エッジケース 🔵🟡

- 🔵 **条件なし → 空タプル**: 全 ranked の rwp が閾値以下・unknown_phase_flag=False・2 位 close_competitor=
  False・staged_escalated=False → `detect_escalations` は `()` を返す (完了条件②)。
- 🔵 **空 ranked (候補ゼロ経路)**: `result.ranked == ()` のとき all_high_r・close_competitor は発火しない
  (all() の真空的 True を回避、2 位不在)。unknown_phase は `unmatched.unknown_phase_flag` 次第、
  guard_escalated は引数次第で独立に立ち得る。
- 🔵 **4 条件同時**: 全高 R かつ未知相かつ 2 位僅差かつ staged_escalated=True →
  `("all_high_r", "unknown_phase", "close_competitor", "guard_escalated")` を宣言順で返す。
- 🔵 **Queue 追記型検証 (TC-107-07)**: add を複数回 → resolve 1 件 → `items` 件数不変・該当のみ
  `resolved=True`・削除 API が `hasattr` で不在。
- 🟡 **resolve の未知 item_id**: 完了条件外。防御的に例外送出 (KeyError/ValueError) を妥当挙動とする。

### 4.4 エラーケース 🔵

- 🔵 **ReviewItem frozen 再代入**: `item.resolved = True` → `dataclasses.FrozenInstanceError`。
- 🔵 **削除 API 不在 (P2)**: `hasattr(queue, "delete")` 等が False (構造的非破壊性の担保)。

- **参照したEARS要件**: REQ-015、FR-403、TC-107-06/07
- **参照した設計文書**: dataflow.md L84-98、interfaces.py (ReviewItem/ReviewQueue/detect_escalations)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: m2-sequential 最終選択 2 モード + エスカレーション/Review Queue
  (user-stories.md / requirements.md L9)
- **参照した機能要件**:
  - REQ-015 (requirements.md L66-68): エスカレーション条件 (a)全仮説高R / (b)未知相フラグ /
    (c)僅差競合(ΔBIC<閾値) / (d)ガード 3 連続発動(escalated report) を検出し Review Queue(追記型)へ通知。
    処理はブロックしない。← 本タスクの中核。
  - REQ-013 (L62-64): final_selection_mode を持つ最終選択エンジン (エンジン本体は TASK-0021)。
  - REQ-014 (L64-65): 裁定は根拠付きで ledger に記録 (Queue の ledger 連携が対応)。
- **参照した非機能要件**: NFR-101 (追記/非破壊 P2)、NFR-102 (再現性/決定論)、REQ-402 (ビット同一)
- **参照したEdgeケース**: 条件なし空タプル / 空 ranked / 4 条件同時 (dataflow・acceptance-criteria 由来)
- **参照した受け入れ基準** (`docs/spec/m2-sequential/acceptance-criteria.md`):
  - TC-107-06 (L77): エスカレーション 4 条件 (高R/未知相/僅差/ガード3連続) がそれぞれ Queue に入る。
  - TC-107-07 (L78): Review Queue は追記型 (resolve はマーク追記、削除 API なし)。
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md` D6 (L84-87、detect_escalations 純粋関数
    4 条件)・アーキテクチャ表 (L41、selection/review_queue.py = ReviewQueue + ReviewItem, REQ-015)
  - **データフロー**: `docs/design/m2-sequential/dataflow.md` L84-98 (detect_escalations → mode 分岐 →
    provisional + ReviewQueue 追記、ブロックなし)
  - **設計判断**: `docs/design/m2-sequential/design-interview.md` D-Q7 (L41-45、ReviewQueue は独立追記型
    コレクション、ledger 注入時は add/resolve を記録、専用永続化は M2 不要)
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L299-342 (EscalationReason / ReviewItem /
    ReviewQueue / detect_escalations)
  - **既存実装**: `src/tsumugin/search/tree.py` (SearchResult / _compute_unmatched)、
    `src/tsumugin/evidence/ranking.py` (RankedHypothesis / rank / close_competitor)、
    `src/tsumugin/refinement/staged.py` (RefinementReport.escalated)、
    `src/tsumugin/store/ledger.py` (Ledger.append)
  - **タスク定義**: `docs/tasks/m2-sequential/TASK-0020.md`
  - **コンテキストノート**: `docs/implements/m2-sequential/TASK-0020/note.md`

---

## 完了条件（タスク定義より）

- [ ] 4 条件 (all_high_r / unknown_phase / close_competitor / guard_escalated) それぞれが単独で検出される
      (SearchResult のテストダブル) 🔵 *TC-107-06*
- [ ] 条件なしで空タプル `()` 🔵
- [ ] Queue は追記型: resolve 後も items に残り resolved=True、削除 API 不在 🔵 *TC-107-07*
- [ ] ledger 連携時 review_add / review_resolve が記録される 🔵 *D-Q7*
- [ ] item_id 連番の決定論 (rq-0000, rq-0001, …) 🔵

## 信頼性レベルサマリー

- 🔵 青信号: 大多数 (機能概要・4 条件の判定ロジック・入出力・主要制約・完了条件は interfaces.py /
  requirements.md REQ-015 / architecture.md D6 / design-interview.md D-Q7 / 既存実装に直接依拠)
- 🟡 黄信号: 少数 (ledger の kind 名 review_add/review_resolve、resolve の未知 item_id 縮退挙動)
- 🔴 赤信号: git commit しない旨のセッション制約のみ (仕様外の運用指示)
- **品質判定**: 高品質 — 要件の曖昧さなし / 入出力定義完全 / 制約条件明確 / 実装可能性確実
