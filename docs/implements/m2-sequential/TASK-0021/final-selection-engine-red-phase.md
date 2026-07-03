# TASK-0021 Red フェーズ記録 — FinalSelectionEngine / Decision

**要件名**: m2-sequential / **タスクID**: TASK-0021 / **機能名**: final-selection-engine
**フェーズ**: TDD Red (失敗テスト作成) / **作成日時**: 2026-07-03
**テストファイル**: `tests/test_selection.py` (既存 19 件に追記、TASK-0020 分は無改変)
**対象実装 (未実装)**: `tsumugin.selection.Decision` / `tsumugin.selection.FinalSelectionEngine`

> パスはプロジェクトルート相対。信頼性: 🔵 資料準拠 / 🟡 妥当な推測 / 🔴 資料外推測。

---

## 1. 作成したテストケース一覧 (17 件: 正常系 8 / 異常系 4 / 境界値 5)

| # | テスト関数 | 対応 | 信頼性 |
|---|---|---|---|
| N-01 | `test_agent_clear_best_auto_accepts` | TC-107-01 / REQ-102 / Q8 | 🔵 |
| N-02 | `test_agent_close_competitor_provisional_and_queue` | TC-107-02 / FR-403 | 🔵 |
| N-03 | `test_human_decide_recommends_only` | TC-107-03 前半 / REQ-103 | 🔵 |
| N-04 | `test_human_explicit_accept_sets_accepted_by_human` | TC-107-03 後半 / REQ-013/014 | 🔵 |
| N-05 | `test_set_mode_records_to_ledger` | TC-107-04 / REQ-104 | 🔵 |
| N-06 | `test_revert_marks_superseded_and_keeps_history` | TC-107-05 / REQ-202 | 🟡 |
| N-07 | `test_accept_rationale_recorded_in_ledger` | REQ-014 | 🔵 |
| N-08 | `test_accepted_registry_is_append_only_mapping` | REQ-013 / P2 | 🔵 |
| E-01 | `test_empty_ranked_no_accept_escalation_only` | TC-107-08 / EDGE-004 | 🟡 |
| E-02 | `test_accept_unknown_hypothesis_id_raises` | REQ-013 誤操作防御 | 🟡 |
| E-03 | `test_revert_unknown_hypothesis_id_raises` | REQ-202 誤操作防御 | 🟡 |
| E-04 | `test_decision_is_frozen` | interfaces.py L328 frozen | 🔵 |
| B-01 | `test_agent_best_close_only_provisional` | Q8 (b) 欠如 | 🔵 |
| B-02 | `test_agent_unknown_phase_only_provisional` | Q8 (c) 欠如 | 🔵 |
| B-03 | `test_decide_and_accept_do_not_mutate_search_result` | D5 / P2 | 🔵 |
| B-04 | `test_rationale_is_deterministic` | NFR-102 / REQ-402 | 🔵 |
| B-05 | `test_revert_ledger_count_never_decreases` | P2 / NFR-105 / REQ-202 | 🔵 |

信頼性内訳: 🔵 13 / 🟡 4。

---

## 2. テストコードの配置と方針

- `tests/test_selection.py` の末尾 (既存 19 テストの後) に追記。既存の module-level
  `from tsumugin.selection import ReviewItem, ReviewQueue, detect_escalations` と
  ヘルパ `_ranked` / `_result` を流用する。
- **関数内 import (重要)**: `Decision` / `FinalSelectionEngine` は各テスト関数の内部で import する。
  冒頭 (module-level) で未実装シンボルを import すると collection が失敗し、TASK-0020 の既存 19 件まで
  巻き込んで fail する。関数内 import なら新規 17 件のみ ImportError で fail し、既存 19 件は pass を維持する。
- ledger 検証は engine 注入 `Ledger()` の `.entries` を確認 (`result.ledger` でなく engine 側 = 非破壊 D5)。
- agent 自動 accept 成立条件 (Q8, AND): best 存在 / `ranked[0].close_competitor is False` /
  `unknown_phase_flag is False` / `detect_escalations(...) == ()`。

---

## 3. 期待される失敗内容 (Red 確認)

```
$ uv run pytest tests/test_selection.py
17 failed, 19 passed in 0.88s
```

- 新規 17 件はいずれも
  `ImportError: cannot import name 'FinalSelectionEngine' from 'tsumugin.selection'`
  (E-04 は `Decision` も) により FAILED。
- 既存 19 件 (detect_escalations 6 + ReviewQueue/ReviewItem 系 13) は無改変で pass 維持。
- `uvx ruff check tests/test_selection.py` → All checks passed! (line-length 100)。

---

## 4. Green フェーズで実装すべき内容

`src/tsumugin/selection/engine.py` に追記 (detect_escalations は無改変):

1. `Decision` (frozen dataclass): `mode` / `accepted: Hypothesis|None` / `provisional_id: str|None` /
   `recommended_id: str|None` / `escalations: tuple[EscalationReason, ...]` / `rationale: str`。
2. `FinalSelectionEngine`:
   - `__init__(*, mode="agent", ledger=None, queue=None)` — mode / 注入 ledger / 注入 ReviewQueue 保持。
   - `set_mode(mode)` — mode 切替を ledger に `{"mode": ...}` 付きで記録 (REQ-104)。
   - `decide(result, *, frame_index=None) -> Decision`:
     - agent + Q8 4 条件成立 → `accept(by="agent")` で自動 accept (`accepted != None`)。
     - agent + いずれか欠如 → `provisional_id = best.id` + 各 escalation reason を `queue.add()`、accepted は None。
     - human → `recommended_id = best.id` のみ (accepted は None)。
     - ranked 空 → best 不在で accept を試みず accepted/provisional とも None。
   - `accept(result, hypothesis_id, *, by) -> Hypothesis` — `replace(hyp, status="accepted", accepted_by=by)`。
     未知 id は KeyError。ledger へ `{"hypothesis_id","by","rationale"}` を記録。単一 accept 経路 (REQ-013)。
   - `revert(hypothesis_id, *, note="") -> Hypothesis` — `replace(hyp, status="superseded")`。未 accept は KeyError。
     元 accept エントリを残したまま revert を追記 (件数を減らさない, REQ-202/P2)。
   - `accepted` (property) → 読み取り専用 `Mapping[str, Hypothesis]` (追記のみ)。
   - `rationale` は best.id / probability / evidence / close / unknown_phase / escalations を固定順で組む
     決定論的文字列 (NFR-102, 乱数・時刻不使用)。
3. `selection/__init__.py` に `Decision` / `FinalSelectionEngine` を re-export 追加。
4. 非破壊 D5: `decide` / `accept` は入力 `SearchResult` を変更せず、記録は engine 注入 ledger にのみ書く。
