# TASK-0021 TDD 要件定義書 — FinalSelectionEngine (agent/human 2 モード裁定)

**要件名**: m2-sequential / **タスクID**: TASK-0021 / **機能名**: final-selection-engine
**タイプ**: TDD / **フェーズ**: Phase 3 - エンジン / **信頼性**: 🔵 6 / 🟡 1
**出力実装**: `src/tsumugin/selection/engine.py` (拡張) / **テスト**: `tests/test_selection.py` (追加)

> すべてのファイルパスはプロジェクトルートからの相対パス。信頼性: 🔵 資料準拠 / 🟡 妥当な推測 / 🔴 資料外推測。

---

## 1. 機能の概要（EARS 要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 木探索結果 (`SearchResult`) に対し、**agent / human 2 モード**で最終的な仮説採択
  (裁定) を行う最終選択エンジン。agent モードはエスカレーション条件が無い明確な最良仮説を**自動 accept**
  し、条件がある場合は**暫定裁定 + Review Queue 通知**で処理をブロックせず継続する。human モードは
  **推奨提示のみ**で、accepted 化は明示 API 呼び出しでのみ行う。
- 🔵 **解決する問題**: 「AI エージェントの完全自動採択」と「専門家による確認・介入」を同一エンジンで
  両立し、介入点を明示設計する (仕様の中核思想)。誤り採択のリスクをエスカレーション+Review Queue で緩和する。
- 🔵 **想定ユーザー**: (agent) 自動解析パイプライン / (human) 粉末回折の解析専門家 (Web UI・API 経由で確認)。
- 🔵 **システム内の位置づけ**: `tsumugin.selection` パッケージの裁定コア。M1 木探索 (`SearchResult`) と
  TASK-0020 の `detect_escalations` / `ReviewQueue` を組み合わせ、`Ledger` に理由付きで裁定を記録する
  オーケストレータ。後続 TASK-0022 が本エンジンを利用する。
- **参照した EARS 要件**: REQ-013, REQ-014, REQ-102, REQ-103, REQ-104, REQ-202, EDGE-004, interview Q8
- **参照した設計文書**: `docs/design/m2-sequential/architecture.md` D5 (L79-83) / 役割表 L42,
  `docs/design/m2-sequential/interfaces.py` L328-362

---

## 2. 入力・出力の仕様（EARS 機能要件・型定義ベース）

### 2.1 `Decision` (frozen dataclass, 出力値オブジェクト) 🔵 *interfaces.py L328-337*

| フィールド | 型 | 意味 |
|---|---|---|
| `mode` | `Literal["agent","human"]` | 裁定を行ったモード |
| `accepted` | `Hypothesis \| None` | accepted 化された**新** Hypothesis (自動 accept 成立時のみ非 None) |
| `provisional_id` | `str \| None` | 暫定裁定の仮説 ID (agent+エスカレーション時) |
| `recommended_id` | `str \| None` | 推奨仮説 ID (human モード / 暫定時の best) |
| `escalations` | `tuple[EscalationReason, ...]` | 検出されたエスカレーション条件 (空なら無し) |
| `rationale` | `str` | 自然言語 + 定量根拠 (best.id / probability / evidence / close / unknown_phase) |

### 2.2 `FinalSelectionEngine` メソッド 🔵 *interfaces.py L345-361*

| メソッド | シグネチャ | 入出力 |
|---|---|---|
| `__init__` | `(*, mode="agent", ledger: Ledger\|None=None, queue: ReviewQueue\|None=None)` | mode / 注入 ledger / 注入 ReviewQueue を保持 |
| `set_mode` | `(mode: Literal["agent","human"]) -> None` | mode を切替し ledger に記録 (REQ-104) |
| `decide` | `(result: SearchResult, *, frame_index: int\|None=None) -> Decision` | 裁定結果を返す。SearchResult 非破壊 |
| `accept` | `(result: SearchResult, hypothesis_id: str, *, by: Literal["agent","human"]) -> Hypothesis` | 明示 accept。accepted 化した新 Hypothesis を返す |
| `revert` | `(hypothesis_id: str, *, note="") -> Hypothesis` | superseded 化した新 Hypothesis を返す (REQ-202) |
| `accepted` | `@property -> Mapping[str, Hypothesis]` | 裁定レジストリ (追記のみ・読み取り専用ビュー) |

### 2.3 入力 `SearchResult` から読む属性 🔵 *search/tree.py L94-111*

- `result.ranked: tuple[RankedHypothesis, ...]` (良い順)。**best = `ranked[0]`**。空なら裁定対象ゼロ。
  - 各要素の `.hypothesis` (id/status/accepted_by/metrics) / `.close_competitor` / `.probability` / `.evidence`。
- `result.unmatched.unknown_phase_flag: bool` (未知相フラグ)。
- `result.hypotheses: Mapping[str, Hypothesis]` (accept 対象の引き当て)。

### 2.4 データフロー 🔵 *dataflow.md / architecture.md D5-D6*

```
SearchResult ──▶ decide()
                  ├─ detect_escalations(result, staged_escalated) ─▶ escalations: tuple
                  ├─ [agent] Q8 4条件AND判定
                  │     ├─ 全条件成立 ─▶ accept(by="agent") ─▶ Decision(accepted=新Hyp, ledger記録)
                  │     └─ いずれか欠如 ─▶ provisional_id=best.id + ReviewQueue.add(各reason)
                  │                        ─▶ Decision(accepted=None, provisional_id, escalations)
                  └─ [human] ─▶ recommended_id=best.id + ReviewQueue通知 ─▶ Decision(accepted=None, recommended_id)
accept()/revert() は dataclasses.replace で新 Hypothesis を生成し accepted レジストリ + ledger に追記
(入力 SearchResult は不変)
```

- **参照した EARS 要件**: REQ-013 (単一 accept 経路), REQ-014 (根拠 + accepted_by 記録), REQ-102/103
- **参照した設計文書**: `docs/design/m2-sequential/interfaces.py` (Decision / FinalSelectionEngine),
  `docs/design/m2-sequential/dataflow.md`, `docs/design/m2-sequential/architecture.md` D5/D6

---

## 3. 制約条件（EARS 非機能要件・アーキテクチャ設計ベース）

- 🔵 **非破壊性 D5 / P2**: `decide` / `accept` は入力 `SearchResult` を変更しない。accepted 化は
  `dataclasses.replace(hyp, status="accepted", accepted_by=by)` の**新 Hypothesis** で表現し、engine の
  `accepted` レジストリと**注入 ledger** に記録する。`result.ledger` には書かない (result を汚さない)。
  *参照: architecture.md D5 (L79-83), CLAUDE.md P2*
- 🔵 **単一 accept 経路 (REQ-013)**: 仮説の accepted 化は `accept()` に集約。agent 自動 accept も内部で
  同経路 (by="agent") を通す。抜け道を作らない。
- 🔵 **根拠付き ledger 記録 (REQ-014)**: 裁定は evidence 値・確率・僅差競合・未知相フラグを根拠として
  ledger に記録し、`accepted_by: agent|human` を仮説に記録する。payload は canonical JSON 可能な素の型
  (str/int/float/bool/None) のみ (Ledger.append 制約)。dataclass を payload に入れない。
- 🔵 **ブロックしない (REQ-102/FR-403)**: agent モードでエスカレーションがあっても例外を投げず、暫定裁定 +
  Review Queue 通知で処理を完了する。
- 🔵 **決定論 (NFR-102)**: 乱数・時刻不使用。decide の分岐・rationale 文字列・返り値は同一入力でビット同一。
- 🔵 **追記型レジストリ (P2/REQ-202)**: `accepted` は削除・上書き API を持たない。revert は削除でなく
  status=`superseded` への遷移で表現し、旧裁定は ledger に履歴として残す (件数を減らさない)。
- 🔵 **アーキテクチャ制約**: `src/tsumugin/selection/engine.py` に追記 (detect_escalations は無改変)。
  `selection/__init__.py` に `Decision` / `FinalSelectionEngine` を re-export 追加。frozen dataclass +
  型注釈必須 + line-length 100 (`uvx ruff check`)。
- 🟡 **スコープ制約**: 自動 accept は Q8 の M2 利用可能材料 (rank/close/unknown_phase/escalated) のみで判定。
  ChemPlausibility (M4) / マルチスタート (M3) / native sequential / Web UI (FR-421) は対象外。
- **参照した EARS 要件**: REQ-013, REQ-014, REQ-102, REQ-202, NFR-102 (REQ-402)
- **参照した設計文書**: `docs/design/m2-sequential/architecture.md` D5, `CLAUDE.md` (P2/NFR-102/規約),
  `src/tsumugin/store/ledger.py` (Ledger.append), `src/tsumugin/model/hypothesis.py` (status/accepted_by)

---

## 4. 想定される使用例（EARS Edge ケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

1. **agent + 明確な最良** (*REQ-102 / TC-107-01 / Q8*):
   best が close_competitor=False かつ unknown_phase_flag=False かつ detect_escalations が空 →
   `decide` が自動 accept。`Decision.accepted != None` / `accepted.status=="accepted"` /
   `accepted.accepted_by=="agent"` / rationale が ledger に記録される。
2. **agent + 僅差** (*REQ-102 / TC-107-02*):
   close_competitor 等でエスカレーションあり → `accepted is None` / `provisional_id=best.id` /
   `escalations` 非空 / ReviewQueue に該当 reason 追加 / **decide は例外なく完了する**。
3. **human モード** (*REQ-103 / TC-107-03*):
   `decide` は `recommended_id=best.id` を返すのみ (accepted なし)。その後
   `accept(result, id, by="human")` で `accepted_by=="human"` の新 Hypothesis を得て `engine.accepted` に登録。
4. **モード切替** (*REQ-104 / TC-107-04*):
   `set_mode("human")` で mode 切替が ledger に記録される。実行中いつでも切替可能。

### 4.2 エッジケース / エラーケース 🔵🟡

- 🟡 **裁定対象ゼロ (EDGE-004 / TC-107-08)**: `result.ranked` が空 → agent モードでも accept せず、
  エスカレーションのみ (accept API を呼ばない)。`Decision.accepted is None` / best 不在で provisional なし。
- 🔵 **revert (REQ-202 / TC-107-05)**: accept 済み仮説を `revert` → 返り値 `status=="superseded"`。
  旧 accept エントリ + revert 操作履歴が ledger に残る (削除しない・件数減らない)。
- 🟡 **未知 hypothesis_id での accept/revert**: 存在しない ID → 誤操作防御として例外 (KeyError 等)。
  ledger には記録しない (ReviewQueue.resolve と同じ防御方針)。
- 🔵 **非破壊検証 (D5)**: decide/accept 前後で `result.ranked` の各 Hypothesis (id/status/accepted_by) が不変。
- **参照した EARS 要件**: EDGE-004, REQ-202
- **参照した設計文書**: `docs/spec/m2-sequential/requirements.md` (EDGE-004 L118, REQ-202 L89-90),
  `docs/design/m2-sequential/dataflow.md`

---

## 5. EARS 要件・設計文書との対応関係

- **参照したユーザストーリー**: `docs/spec/m2-sequential/user-stories.md` (最終選択 2 モード / 専門家介入)
- **参照した機能要件**: REQ-013 (単一 accept API), REQ-014 (根拠 + accepted_by), REQ-102 (agent 自動/暫定),
  REQ-103 (human 明示 accept), REQ-104 (モード切替 + ledger), REQ-202 (revert → superseded + 履歴)
- **参照した非機能要件**: NFR-102 / REQ-402 (決定論・ビット同一), P2 (追記・非破壊)
- **参照した Edge ケース**: EDGE-004 (裁定対象ゼロ → accept なし + エスカレーションのみ)
- **参照した受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md`
  TC-107-01 (agent 自動 accept), TC-107-02 (agent 僅差 → 暫定 + Queue), TC-107-03 (human 推奨のみ + 明示 accept),
  TC-107-04 (set_mode → ledger), TC-107-05 (revert → superseded + 履歴), TC-107-08 (裁定対象ゼロ)
- **参照したインタビュー**: `docs/spec/m2-sequential/interview-record.md` Q8 (agent 自動 accept 4 条件)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md` D5 (最終選択エンジン非破壊, L79-83), 役割表 L42
  - **データフロー**: `docs/design/m2-sequential/dataflow.md` (SearchResult → mode 分岐)
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L328-362 (Decision / FinalSelectionEngine)
  - **既存実装**: `src/tsumugin/selection/engine.py` (detect_escalations), `.../review_queue.py` (ReviewQueue),
    `src/tsumugin/model/hypothesis.py` (Hypothesis.status/accepted_by), `src/tsumugin/store/ledger.py`

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (7 完了条件が TC-107-01〜05/08 + D5 に 1:1 対応)
- 入出力定義: 完全 (Decision 6 フィールド / FinalSelectionEngine 6 メンバを interfaces.py L328-362 から確定)
- 制約条件: 明確 (D5 非破壊 / REQ-013 単一経路 / REQ-014 ledger / NFR-102 決定論 / P2 追記)
- 実装可能性: 確実 (detect_escalations / ReviewQueue / Hypothesis.replace は既存で利用可)
- 信頼性レベル: 🔵 6 / 🟡 1 (裁定対象ゼロ・スコープ境界のみ 🟡)
```

判定: **高品質**。7 完了条件すべてが受け入れ基準または設計 D5 に遡及可能で、実装契約 (interfaces.py) と
依存実装 (TASK-0020) が確定済み。次フェーズ (テストケース洗い出し) へ進行可能。
