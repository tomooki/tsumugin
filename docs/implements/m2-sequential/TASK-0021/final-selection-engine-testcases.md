# TASK-0021 テストケース定義 — FinalSelectionEngine (agent/human 2 モード裁定)

**要件名**: m2-sequential / **タスクID**: TASK-0021 / **機能名**: final-selection-engine
**対象実装**: `src/tsumugin/selection/engine.py` (Decision / FinalSelectionEngine 追記)
**テストファイル**: `tests/test_selection.py` (既存 21 テストに**追記**、TASK-0020 分は無改変)
**テストケース総数**: 17 件 (正常系 8 / 異常系 4 / 境界値 5)

> パスはプロジェクトルート相対。信頼性: 🔵 資料準拠 / 🟡 妥当な推測 / 🔴 資料外推測。

---

## 前提 / テストダブル方針

- 既存ヘルパ `_ranked(hyp_id, rwp, close)` と `_result(ranked, *, unknown_phase=False)`
  (`tests/test_selection.py` L43-68) を流用する。木探索を回さず `ranked` / `unmatched` のみ最小構成。
- `_ranked` の `metrics.rwp` は既定小さめ (例 10.0) にして `all_high_r` を誤発火させない。
- ledger 検証は engine に注入した `Ledger()` の `.entries` の `kind` / `payload` を確認する
  (`result.ledger` でなく engine 側 = 非破壊 D5)。
- best = `ranked[0]`。agent 自動 accept 成立条件 (Q8, AND): best 存在 / `ranked[0].close_competitor is False`
  / `unknown_phase_flag is False` / `detect_escalations(...) == ()`。

---

## 1. 正常系テストケース（基本的な動作）

### N-01: agent モード + 明確な最良 → 自動 accepted 🔵 *TC-107-01 / REQ-102 / Q8*

- **何をテストするか**: agent モードでエスカレーションゼロかつ best が僅差でないとき自動 accept される。
- **入力値**: `engine = FinalSelectionEngine(mode="agent", ledger=Ledger())`、
  `result = _result([_ranked("h1", rwp=10.0, close=False), _ranked("h2", rwp=12.0, close=False)])`
  (unknown_phase=False)。
- **期待結果**: `d = engine.decide(result)` で `d.accepted is not None` /
  `d.accepted.status == "accepted"` / `d.accepted.accepted_by == "agent"` / `d.accepted.id == "h1"` /
  `d.escalations == ()` / `d.provisional_id is None` / ledger に accept 系 kind が根拠付きで記録 /
  `engine.accepted["h1"].status == "accepted"`。
- **確認ポイント**: 自動 accept が best (ranked[0]) を対象にし、accepted_by="agent" と ledger 記録が伴う。
- 🔵 信頼性: TC-107-01 / REQ-102 / interview Q8 に直接対応。

### N-02: agent モード + 僅差競合 → 暫定裁定 + Review Queue + 処理完了 🔵 *TC-107-02 / REQ-102/FR-403*

- **何をテストするか**: エスカレーションありでも例外を投げず、accept せず provisional + Queue 通知で完了。
- **入力値**: `queue = ReviewQueue()`、`engine = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)`、
  `result = _result([_ranked("h1", 10.0, close=False), _ranked("h2", 10.0, close=True)])`
  (2 位 close_competitor=True → detect_escalations が `close_competitor` を返す)。
- **期待結果**: `d = engine.decide(result)` で `d.accepted is None` / `d.provisional_id == "h1"` /
  `"close_competitor" in d.escalations` / `len(queue.items) >= 1` かつ該当 reason が Queue に入る /
  例外送出なし (処理完了) / `engine.accepted` は空。
- **確認ポイント**: ブロックしない (FR-403)。provisional は best、Queue 追加、accepted 化はしない。
- 🔵 信頼性: TC-107-02 / REQ-102 / FR-403 に対応。

### N-03: human モード decide → 推奨のみ (accepted 化しない) 🔵 *TC-107-03 前半 / REQ-103*

- **何をテストするか**: human モードでは decide が推奨提示のみで自動 accept しない。
- **入力値**: `engine = FinalSelectionEngine(mode="human", ledger=Ledger())`、
  `result = _result([_ranked("h1", 10.0, close=False)])`。
- **期待結果**: `d = engine.decide(result)` で `d.mode == "human"` / `d.recommended_id == "h1"` /
  `d.accepted is None` / `engine.accepted` は空。
- **確認ポイント**: human では自動 accept が絶対に発生しない (REQ-103)。recommended_id に best を提示。
- 🔵 信頼性: TC-107-03 / REQ-103 に対応。

### N-04: human accept API → accepted_by="human" 🔵 *TC-107-03 後半 / REQ-013/014*

- **何をテストするか**: human モードで明示 accept API を呼ぶと accepted_by="human" になり登録される。
- **入力値**: N-03 の engine/result に続けて `h = engine.accept(result, "h1", by="human")`。
- **期待結果**: `h.status == "accepted"` / `h.accepted_by == "human"` / `h.id == "h1"` /
  `engine.accepted["h1"] == h` / ledger に accept 記録。
- **確認ポイント**: accepted 化は単一 accept API 経由 (REQ-013)。accepted_by を仮説へ記録 (REQ-014)。
- 🔵 信頼性: TC-107-03 / REQ-013/014 に対応。

### N-05: set_mode がモード切替を ledger 記録 🔵 *TC-107-04 / REQ-104*

- **何をテストするか**: 実行中のモード切替が ledger に記録される。
- **入力値**: `led = Ledger()`、`engine = FinalSelectionEngine(mode="agent", ledger=led)`、
  `engine.set_mode("human")`。
- **期待結果**: `engine` の現在 mode が "human" / `led.entries` に mode 切替の kind (例 "set_mode") が存在し
  payload に `{"mode": "human"}` 相当を含む / `led.verify() is True` (ハッシュチェーン整合)。
- **確認ポイント**: 切替が追記され、payload は素の型のみ。
- 🔵 信頼性: TC-107-04 / REQ-104 に対応。

### N-06: revert → superseded + 履歴保持 🟡 *TC-107-05 / REQ-202*

- **何をテストするか**: accept 済み仮説の差し戻しで status=superseded になり旧裁定履歴が ledger に残る。
- **入力値**: agent で "h1" を accept 済みの engine に対し `h = engine.revert("h1", note="再検討")`。
- **期待結果**: `h.status == "superseded"` / `engine.accepted["h1"].status == "superseded"` /
  ledger に元の accept エントリ + revert エントリ (from_status/to_status 等) が**両方**残る (件数が減らない) /
  `led.verify() is True`。
- **確認ポイント**: 削除でなく状態遷移 (P2)。旧裁定を保持 (REQ-202)。
- 🟡 信頼性: TC-107-05 は 🟡 (status 遷移詳細)。REQ-202 に準拠。

### N-07: accept の根拠 (rationale/evidence/probability/close/unknown_phase) が ledger 記録 🔵 *REQ-014*

- **何をテストするか**: 裁定が evidence 値・確率・僅差競合・未知相フラグを根拠として記録される。
- **入力値**: N-01 の agent 自動 accept 後、`d.rationale` と ledger の accept payload を検査。
- **期待結果**: `d.rationale` が非空文字列で best.id を含む / ledger の accept エントリ payload に
  hypothesis_id・by・rationale 相当が含まれる。
- **確認ポイント**: 根拠の追跡可能性 (REQ-014)。payload は canonical JSON 可能な素の型のみ。
- 🔵 信頼性: REQ-014 に対応。

### N-08: accepted レジストリは追記型ビュー (複数 accept) 🔵 *REQ-013 / P2*

- **何をテストするか**: 複数仮説を accept すると accepted に追記され、読み取り専用 Mapping で公開される。
- **入力値**: human モードで `engine.accept(result_a, "h1", by="human")` と別 result の "h2" を accept。
- **期待結果**: `set(engine.accepted.keys()) == {"h1", "h2"}` / 各 status="accepted" /
  `engine.accepted` は Mapping (直接変更で元レジストリが壊れない読み取り専用ビュー)。
- **確認ポイント**: 追記のみ・削除 API 不在 (P2)。
- 🔵 信頼性: REQ-013 / P2 に対応。

---

## 2. 異常系テストケース（エラーハンドリング）

### E-01: ranked 空 (裁定対象ゼロ) → accept なし + エスカレーションのみ 🟡 *TC-107-08 / EDGE-004*

- **エラーケース概要**: agent モードで裁定対象仮説がゼロ (候補が全滅した縮退経路)。
- **入力値**: `engine = FinalSelectionEngine(mode="agent", ledger=Ledger())`、`result = _result([])`。
- **期待結果**: `d = engine.decide(result)` で `d.accepted is None` / `d.provisional_id is None` /
  例外を投げず完了 / `engine.accepted` は空 (accept API 未呼び)。
- **安全性**: best 不在で accept を試みず、エスカレーションのみ (処理は落ちない)。
- 🟡 信頼性: EDGE-004 / TC-107-08 は 🟡。

### E-02: 未知 hypothesis_id で accept → 例外 🟡 *REQ-013 誤操作防御*

- **エラーケース概要**: result に存在しない ID を accept しようとする API 誤用。
- **入力値**: `engine.accept(_result([_ranked("h1", 10.0, False)]), "nope", by="human")`。
- **期待結果**: `KeyError` (または明示例外) を送出し、`engine.accepted` に登録されない / ledger に記録しない。
- **安全性**: 存在しない仮説を「採択した」と誤認させない。
- 🟡 信頼性: 明示要件なし・ReviewQueue.resolve の防御方針からの妥当な推測。

### E-03: 未 accept / 未知 id で revert → 例外 🟡 *REQ-202 誤操作防御*

- **エラーケース概要**: accepted レジストリに無い仮説を差し戻そうとする。
- **入力値**: 何も accept していない engine で `engine.revert("h1")`。
- **期待結果**: `KeyError` (または明示例外) を送出し、ledger に revert を記録しない。
- **安全性**: 存在しない裁定を superseded にしない (履歴の一貫性)。
- 🟡 信頼性: REQ-202 からの妥当な推測。

### E-04: Decision は frozen (再代入で例外) 🔵 *interfaces.py L328 frozen*

- **エラーケース概要**: Decision の値を後から書き換えようとする。
- **入力値**: `d = engine.decide(result)` 後に `d.accepted = None` 代入。
- **期待結果**: `dataclasses.FrozenInstanceError` を送出。
- **安全性**: 裁定結果の不変性を保証 (値オブジェクト)。
- 🔵 信頼性: interfaces.py で `@dataclass(frozen=True)` 明記。

---

## 3. 境界値テストケース（最小値、最大値、状態不変等）

### B-01: agent + best.close_competitor=True のみ (detect 空) → 暫定裁定 🔵 *Q8 (b) 欠如*

- **境界の意味**: Q8 自動 accept 条件 (b) `ranked[0].close_competitor is False` の境界。detect_escalations の
  close_competitor は 2 位基準なので単一 ranked では発火せず、best 自身の close フラグだけが自動 accept を阻む。
- **入力値**: `result = _result([_ranked("h1", 10.0, close=True)])` (単一 ranked, best.close=True,
  unknown_phase=False)。agent モード。
- **期待結果**: `d.accepted is None` / `d.provisional_id == "h1"` (best が僅差扱いで暫定)。
- **一貫性**: detect_escalations が空でも Q8 (b) が欠ければ自動 accept しないことを保証。
- 🔵 信頼性: interview Q8 の (b) 条件 / note の「detect と Q8 close の意味差」に対応。

### B-02: agent + unknown_phase_flag=True のみ → 暫定裁定 (unknown_phase reason) 🔵 *Q8 (c) 欠如*

- **境界の意味**: Q8 条件 (c) `unknown_phase_flag is False` の境界。未知相フラグ単独で自動 accept を阻む。
- **入力値**: `result = _result([_ranked("h1", 10.0, close=False)], unknown_phase=True)`。agent モード。
- **期待結果**: `d.accepted is None` / `"unknown_phase" in d.escalations` / `d.provisional_id == "h1"` /
  ReviewQueue に unknown_phase が入る。
- **一貫性**: 未知相フラグが立つと accept を保留し要確認へ回す。
- 🔵 信頼性: interview Q8 (c) / REQ-102 に対応。

### B-03: SearchResult 非破壊 (decide/accept 前後で不変) 🔵 *D5 / P2*

- **境界の意味**: 状態変更の境界 = 「入力を一切変えない」保証。
- **入力値**: `result = _result([_ranked("h1", 10.0, close=False)])` を保持し、decide → accept を実行。
- **期待結果**: 実行前後で `result.ranked[0].hypothesis.status == "refined"` /
  `result.ranked[0].hypothesis.accepted_by is None` が不変 (accepted 化は engine 側の**新** Hypothesis に反映) /
  `result.ledger.entries` の件数が不変 (engine 注入 ledger にのみ記録)。
- **堅牢性**: accepted 化は `dataclasses.replace` の新インスタンスで、共有された SearchResult を汚さない。
- 🔵 信頼性: architecture.md D5 / CLAUDE.md P2 に直接対応。

### B-04: rationale の決定論 (同一入力で同一文字列) 🔵 *NFR-102*

- **境界の意味**: 再現性の境界 = 同一入力でビット同一。
- **入力値**: 同一 `result` で `engine1.decide(result)` と `engine2.decide(result)` を独立に実行。
- **期待結果**: 両 `Decision.rationale` が完全一致 / `escalations` タプルも一致 (順序含む)。
- **堅牢性**: 乱数・時刻を使わず rationale を固定順で組む (NFR-102)。
- 🔵 信頼性: NFR-102 / REQ-402 に対応。

### B-05: revert 後も ledger 件数が減らない (追記型) 🔵 *P2 / NFR-105*

- **境界の意味**: 追記型ストアの境界 = 操作しても件数が単調増加。
- **入力値**: accept 済み仮説を revert した前後の `led.entries` 件数を比較。
- **期待結果**: revert 後の件数 > revert 前の件数 (revert エントリが追記され、元 accept エントリは残る) /
  `led.verify() is True`。
- **堅牢性**: 削除・上書き不在 (P2)。ハッシュチェーン整合維持 (NFR-105)。
- 🔵 信頼性: CLAUDE.md P2/NFR-105 / REQ-202 に対応。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **選択理由**: 既存 `src/tsumugin` は Python (uv 管理, src layout + hatchling)。frozen dataclass +
    型注釈で不変値オブジェクトを表現するプロジェクト方針に一致。
- **テストフレームワーク**: pytest >= 8 + pytest-cov 🔵
  - **選択理由**: 既存全テスト (`tests/test_*.py`) が pytest。frozen 検証は
    `with pytest.raises(dataclasses.FrozenInstanceError):`、例外検証は `pytest.raises`。
  - **実行環境**: `uv run pytest tests/test_selection.py` (本タスク) / `uv run pytest` (全体回帰)。
    依存導入は `uv sync --extra gsas`。
- 🔵 信頼性: `pyproject.toml` / 既存テスト構成に準拠。

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下を付す (既存 test_selection.py / test_model_m2.py の慣習):

```python
def test_agent_clear_best_auto_accepts():
    # 【テスト目的】: agent モードでエスカレーションゼロかつ best が僅差でないとき自動 accept される 🔵
    # 【テスト内容】: decide が accepted_by="agent" の新 Hypothesis を返し ledger に根拠を記録する
    # 【期待される動作】: accepted!=None / status=="accepted" / escalations==() / SearchResult 非破壊
    # 【テストデータ準備】: rwp 低め・close=False の 2 仮説で all_high_r/close を誤発火させない
    led = Ledger()
    engine = FinalSelectionEngine(mode="agent", ledger=led)
    result = _result([_ranked("h1", 10.0, False), _ranked("h2", 12.0, False)])
    # 【実際の処理実行】: 単一 SearchResult に対し agent 裁定を実行
    d = engine.decide(result)
    # 【結果検証】: 自動 accept と accepted_by / 非破壊を確認
    assert d.accepted is not None                       # 【検証項目】: 自動 accept 成立 🔵
    assert d.accepted.accepted_by == "agent"            # 【検証項目】: 採択主体が agent 🔵
    assert result.ranked[0].hypothesis.status == "refined"  # 【検証項目】: 入力非破壊 (D5) 🔵
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `final-selection-engine-requirements.md` §1 (agent/human 2 モード)
- **参照した入力・出力仕様**: 同 §2 (Decision 6 フィールド / FinalSelectionEngine 6 メンバ / SearchResult 読取属性)
- **参照した制約条件**: 同 §3 (D5 非破壊 / REQ-013 単一経路 / REQ-014 ledger / NFR-102 決定論 / P2 追記)
- **参照した使用例**: 同 §4 (基本 4 パターン + EDGE-004 / revert / 誤操作防御)
- **完了条件対応**: TC-107-01→N-01 / TC-107-02→N-02 / TC-107-03→N-03,N-04 / TC-107-04→N-05 /
  TC-107-05→N-06,B-05 / TC-107-08(EDGE-004)→E-01 / D5 非破壊→B-03

---

## 7. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 8 / 異常系 4 / 境界値 5 を網羅 (17 件)
- 期待値定義: 各ケースで accepted/status/accepted_by/escalations/provisional_id/ledger を明示
- 技術選択: Python 3.12 + pytest 確定 (既存テストと同構成)
- 実装可能性: 既存 _ranked/_result ヘルパ + detect_escalations/ReviewQueue/Hypothesis.replace で実現可能
- 信頼性レベル: 🔵 13 / 🟡 4 (裁定対象ゼロ・誤操作防御・revert 詳細のみ 🟡)
```

判定: **高品質**。7 完了条件すべてにテストケースが 1:1 以上で対応し、非破壊 (D5) と決定論 (NFR-102) を
独立検証。次フェーズ (tdd-red 失敗テスト作成) へ進行可能。
