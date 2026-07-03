# TASK-0020 ReviewQueue + detect_escalations TDDテストケース定義書

**機能名**: ReviewQueue + detect_escalations (最終選択エンジンのエスカレーション基盤)
**タスクID**: TASK-0020 / **要件名**: m2-sequential
**作成日**: 2026-07-03
**要件定義**: `docs/implements/m2-sequential/TASK-0020/review-queue-escalation-requirements.md`
**出力ファイル**: `docs/implements/m2-sequential/TASK-0020/review-queue-escalation-testcases.md`
**テスト対象実装**: `src/tsumugin/selection/{engine,review_queue,__init__}.py`
**テストファイル**: `tests/test_selection.py` (新規。既存テストは無改変)

**【信頼性レベル凡例】**:
- 🔵 **青信号**: 要件定義・既存実装・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: 元の資料から妥当な推測
- 🔴 **赤信号**: 元の資料にない推測

---

## テストケース一覧サマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 | 10 | N-01〜N-10 |
| 異常系 | 3 | E-01〜E-03 |
| 境界値 | 6 | B-01〜B-06 |
| **合計** | **19** | |

**内訳**: detect_escalations 系 = N-01〜N-06 / B-01〜B-03 / B-05〜B-06 (11)、
ReviewQueue+ReviewItem 系 = N-07〜N-10 / E-01〜E-03 / B-04 (8)。

**信頼性分布**: 🔵 17 / 🟡 2 / 🔴 0 — 品質評価: 高品質

---

## テストダブル設計方針（共通）🔵

detect_escalations の入力 `SearchResult` は**完全な木探索を回さず**、`ranked` と `unmatched` だけを
最小構成する。ヘルパ関数で軽量に組み立てる (以下擬似コード):

```python
from tsumugin.model import Hypothesis, RefinementMetrics
from tsumugin.evidence.base import EvidenceResult
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.search.matcher import UnmatchedPeakReport
from tsumugin.search.tree import SearchResult
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

def _ranked(hyp_id: str, rwp: float, close: bool) -> RankedHypothesis:
    # 【テストデータ準備】: rwp と close_competitor だけ意味を持つ最小 RankedHypothesis
    m = RefinementMetrics(rwp=rwp, gof=1.0, chi2=1.0, n_obs=100, n_params=5, evidence={"bic": 0.0})
    h = Hypothesis(id=hyp_id, phases=(), metrics=m, status="refined")
    ev = EvidenceResult(backend="bic", value=0.0)
    return RankedHypothesis(hypothesis=h, evidence=ev, probability=0.5, close_competitor=close)

def _result(ranked, *, unknown_phase=False) -> SearchResult:
    led = Ledger()
    return SearchResult(
        ranked=tuple(ranked), hypotheses={r.hypothesis.id: r.hypothesis for r in ranked},
        good_cluster_ids=(), alternatives={},
        unmatched=UnmatchedPeakReport(unmatched_observed=(), extra_calculated=(),
                                      unknown_phase_flag=unknown_phase),
        final_reports={}, ledger=led, snapshots=SnapshotStore(ledger=led), warnings=(),
    )
```

detect_escalations が読むのは `result.ranked[*].hypothesis.metrics.rwp` /
`result.ranked[*].close_competitor` / `result.unmatched.unknown_phase_flag` のみのため、この 2 経路で
4 条件を独立に発火できる。`RefinementMetrics` / `UnmatchedPeakReport` の正確なフィールドは実装時に
`src/tsumugin/model/hypothesis.py` / `src/tsumugin/search/matcher.py` を確認して合わせる。🔵

---

## 1. 正常系テストケース（基本的な動作）

### N-01: all_high_r 条件の単独検出
- **何をテストするか**: 全 ranked 仮説の Rwp が閾値超過のとき `detect_escalations` が `("all_high_r",)` を返す。
- **期待される動作**: 全高 R を検出し、他 3 条件は発火しない。
- **入力値**: `ranked=[_ranked("h0",45.0,False), _ranked("h1",50.0,False)]`、unknown_phase=False、
  `detect_escalations(result, staged_escalated=False, high_r_threshold=30.0)`
  - **入力データの意味**: どの仮説も観測を説明できていない (Rwp 45/50% > 30%) 高 R 状況。
- **期待される結果**: `("all_high_r",)`
  - **期待結果の理由**: (a) 全 Rwp > 30 で発火、(b) unknown_phase_flag=False、(c) 2 位 close=False、
    (d) staged_escalated=False のため他は非発火。
- **テストの目的**: 条件 (a) の単独検出 (TC-107-06)。
  - **確認ポイント**: 全件が閾値超過のときのみ発火すること。
- 🔵 (要件定義 2.2 / D6 (a) / TC-107-06 / tree.py L855 の厳密比較)

### N-02: unknown_phase 条件の単独検出
- **何をテストするか**: `result.unmatched.unknown_phase_flag=True` のとき `("unknown_phase",)` を返す。
- **期待される動作**: 未知相フラグを検出し他は非発火。
- **入力値**: `ranked=[_ranked("h0",5.0,False), _ranked("h1",8.0,False)]`、unknown_phase=True
  - **入力データの意味**: Rwp は低い (良好) が最良仮説で説明できない観測ピークが残る = 未知相示唆。
- **期待される結果**: `("unknown_phase",)`
  - **期待結果の理由**: (b) のみ True。全 Rwp ≤ 30、2 位 close=False、staged=False。
- **テストの目的**: 条件 (b) の単独検出 (TC-107-06)。
  - **確認ポイント**: SearchResult 側の集約結果 unknown_phase_flag をそのまま信頼すること。
- 🔵 (要件定義 2.2 / D6 (b) / TC-107-06)

### N-03: close_competitor 条件の単独検出
- **何をテストするか**: 2 位仮説が close_competitor=True のとき `("close_competitor",)` を返す。
- **期待される動作**: 1-2 位僅差を検出し他は非発火。
- **入力値**: `ranked=[_ranked("h0",5.0,True), _ranked("h1",6.0,True)]`、unknown_phase=False
  - **入力データの意味**: 最良と 2 位の ΔBIC が閾値未満 (両者 close=True) の僅差競合。
- **期待される結果**: `("close_competitor",)`
  - **期待結果の理由**: (c) は `ranked[1].close_competitor=True` で発火。全 Rwp ≤ 30、unknown False、staged False。
- **テストの目的**: 条件 (c) の単独検出 (TC-107-06)。
  - **確認ポイント**: **2 位** のフラグで判定すること (ranked[0] の close=True 単独では発火しない)。
- 🔵 (要件定義 2.2 / D6 (c) / ranking.py rank / TC-107-06)

### N-04: guard_escalated 条件の単独検出
- **何をテストするか**: `staged_escalated=True` のとき `("guard_escalated",)` を返す。
- **期待される動作**: ガードエスカレーションを検出し他は非発火。
- **入力値**: `ranked=[_ranked("h0",5.0,False)]`、unknown_phase=False、`staged_escalated=True`
  - **入力データの意味**: staged 精密化がガード N 連続で escalated report を返した状況。
- **期待される結果**: `("guard_escalated",)`
  - **期待結果の理由**: (d) のみ True。他 3 条件の材料は非発火。
- **テストの目的**: 条件 (d) の単独検出 (TC-107-06)。
  - **確認ポイント**: 引数 bool を受けるだけで staged に依存しないこと。
- 🔵 (要件定義 2.2 / D6 (d) / staged.py escalated / TC-107-06)

### N-05: 条件なしで空タプル
- **何をテストするか**: 4 条件すべて非該当のとき `detect_escalations` が `()` を返す。
- **期待される動作**: エスカレーションなし = 空タプル。
- **入力値**: `ranked=[_ranked("h0",5.0,False), _ranked("h1",7.0,False)]`、unknown_phase=False、staged=False
  - **入力データの意味**: 明確な最良仮説あり・良好 Rwp・未知相なし・僅差なし・ガード正常 (自動 accept 相当)。
- **期待される結果**: `()`
  - **期待結果の理由**: (a)〜(d) すべて False。
- **テストの目的**: 空タプル返却 (完了条件②)。
  - **確認ポイント**: 過検出しないこと (agent 自動 accept 経路の前提)。
- 🔵 (要件定義 4.3 / 完了条件② / dataflow.md L88-89)

### N-06: 4 条件同時発火時の宣言順タプル
- **何をテストするか**: 4 条件すべて満たすとき宣言順のタプルを返す。
- **期待される動作**: 決定論的順序 (all_high_r → unknown_phase → close_competitor → guard_escalated)。
- **入力値**: `ranked=[_ranked("h0",45.0,True), _ranked("h1",50.0,True)]`、unknown_phase=True、staged=True
  - **入力データの意味**: 全高 R + 未知相 + 僅差 + ガード発動が同時に起きる最悪ケース。
- **期待される結果**: `("all_high_r", "unknown_phase", "close_competitor", "guard_escalated")`
  - **期待結果の理由**: 全条件発火 + 返り値順序は EscalationReason 宣言順に固定 (NFR-102 決定論)。
- **テストの目的**: 複数発火時の順序決定論 (TC-107-06 + NFR-102)。
  - **確認ポイント**: 順序がビット同一で固定されること。
- 🔵 (要件定義 2.2 返り値順序 / NFR-102 / interfaces.py L299-301 宣言順)

### N-07: ReviewQueue.add による ReviewItem 生成
- **何をテストするか**: `add(reason, ...)` が item_id="rq-0000"・resolved=False の ReviewItem を生成し返す。
- **期待される動作**: 追加順連番 item_id を採番し全フィールドを保持。
- **入力値**: `q = ReviewQueue(); item = q.add("close_competitor", hypothesis_id="hyp-0003", frame_index=12, detail="ΔBIC=4.2")`
  - **入力データの意味**: 僅差競合を Queue へ通知する代表的な追記。
- **期待される結果**: `item.item_id=="rq-0000"`、`item.reason=="close_competitor"`、
  `item.hypothesis_id=="hyp-0003"`、`item.frame_index==12`、`item.detail=="ΔBIC=4.2"`、
  `item.resolved is False`。`q.items==(item,)`。
  - **期待結果の理由**: interfaces.py L316-323 の add 契約 + ReviewItem フィールド定義。
- **テストの目的**: 追記の基本動作と item_id 採番を確認。
  - **確認ポイント**: 初回 item_id が rq-0000、resolved 既定 False。
- 🔵 (要件定義 2.3/2.4 / interfaces.py L304-323)

### N-08: ReviewQueue.resolve で resolved=True かつ items に残存
- **何をテストするか**: `resolve(item_id)` 後、当該 item が `items` に残り resolved=True になる (件数不変)。
- **期待される動作**: 解決は削除でなく resolved=True への状態遷移 (追記表現, P2)。
- **入力値**: `q.add("all_high_r"); r = q.resolve("rq-0000", note="確認済み")`
  - **入力データの意味**: 人間が Review Queue の 1 件を後追い解決する実運用フロー (TC-107-07)。
- **期待される結果**: `r.resolved is True`、`r.item_id=="rq-0000"`、`len(q.items)==1`、
  `q.items[0].resolved is True`。
  - **期待結果の理由**: resolve は `dataclasses.replace(item, resolved=True)` で件数を減らさない (P2)。
- **テストの目的**: 追記型キューの解決挙動を確認 (TC-107-07)。
  - **確認ポイント**: items 件数が resolve で減らないこと・resolved が True になること。
- 🔵 (要件定義 2.4 / 完了条件③ / TC-107-07 / P2)

### N-09: unresolved が未解決のみを返す派生ビュー
- **何をテストするか**: 複数 add + 一部 resolve の後、`unresolved` が未解決の item のみを返す。
- **期待される動作**: `items` から resolved=False を絞り込む。
- **入力値**: `q.add("all_high_r"); q.add("unknown_phase"); q.resolve("rq-0000")`
  - **入力データの意味**: 2 件通知し 1 件解決した状態。
- **期待される結果**: `len(q.items)==2`、`len(q.unresolved)==1`、`q.unresolved[0].item_id=="rq-0001"`、
  `q.unresolved[0].resolved is False`。
  - **期待結果の理由**: unresolved は items の resolved=False 部分集合。
- **テストの目的**: 未解決ビューの正しさを確認。
  - **確認ポイント**: items は全件・unresolved は未解決のみ、で件数が食い違うこと。
- 🔵 (要件定義 2.4 / interfaces.py L323-325)

### N-10: ledger 連携で review_add / review_resolve が記録される
- **何をテストするか**: `Ledger()` を注入した ReviewQueue で add/resolve が ledger に記録される。
- **期待される動作**: add→"review_add"、resolve→"review_resolve" を append し verify() が True を保つ。
- **入力値**: `led = Ledger(); q = ReviewQueue(ledger=led); q.add("close_competitor", hypothesis_id="h1"); q.resolve("rq-0000", note="ok")`
  - **入力データの意味**: D-Q7「ledger 注入時は add/resolve を ledger にも記録」を検証。
- **期待される結果**: `led.entries` の kind に `"review_add"` と `"review_resolve"` が含まれる (順序もこの順)。
  `led.verify() is True`。review_add payload に item_id/reason、review_resolve payload に item_id/note を含む。
  - **期待結果の理由**: D-Q7 の ledger 連携仕様 + 追記専用ハッシュチェーンの整合性維持。
- **テストの目的**: ledger 連携の記録を確認 (完了条件④)。
  - **確認ポイント**: kind 名と追記順・verify() True。
- 🟡 (要件定義 2.4 / D-Q7。kind 名 review_add/review_resolve は D-Q7 からの妥当な命名)

---

## 2. 異常系テストケース（エラーハンドリング）

### E-01: ReviewItem の frozen 再代入禁止
- **エラーケースの概要**: frozen dataclass ReviewItem のフィールドへ再代入を試みる。
- **エラー処理の重要性**: 不変値オブジェクト (P2) の不変性保証。in-place 変更を防ぐ。
- **入力値**: `item = q.add("all_high_r"); item.resolved = True`
  - **不正な理由**: frozen=True では属性再代入が禁止。
  - **実際の発生シナリオ**: 実装者が誤って resolve を直接代入で行おうとした場合の防御。
- **期待される結果**: `dataclasses.FrozenInstanceError` が送出される
  (`with pytest.raises(dataclasses.FrozenInstanceError):`)。
  - **システムの安全性**: 状態変更は必ず replace 経由 (新インスタンス) に強制される。
- **テストの目的**: frozen 制約の確認。
  - **品質保証の観点**: 不変性違反の混入を CI で検出。
- 🔵 (要件定義 2.3/3 frozen 制約 / test_model_m2.py の frozen 検証パターン)

### E-02: 削除・上書き API が存在しない（P2 構造的非破壊性）
- **エラーケースの概要**: ReviewQueue に削除系メソッドが生えていないことを確認する。
- **エラー処理の重要性**: P2 (NFR-101)。Ledger/Snapshot と同じく削除 API を持たないことで構造的に
  非破壊性を保証する。
- **入力値**: `q = ReviewQueue()` に対する `hasattr(q, "delete")` / `"remove"` / `"pop"` / `"clear")`
  - **不正な理由**: これらの API はキューから項目を削除し追記性を破壊するため実装してはならない。
  - **実際の発生シナリオ**: 誤って削除 API を追加した場合の回帰検出。
- **期待される結果**: すべて False。`hasattr(q, "add")` / `"resolve")` は True (正規 API は存在)。
  - **システムの安全性**: 履歴が構造的に消せないことを担保。
- **テストの目的**: 削除 API 不在の確認 (完了条件③ / TC-107-07)。
  - **品質保証の観点**: 非破壊性の構造的保証を CI で固定。
- 🔵 (要件定義 3 P2 制約 / TC-107-07 / ledger.py の削除 API 不在パターン)

### E-03: resolve に未知 item_id を渡した場合の防御
- **エラーケースの概要**: 存在しない item_id を `resolve` に渡す。
- **エラー処理の重要性**: 誤操作の防御。存在しない項目を「解決した」と誤認させない。
- **入力値**: `q = ReviewQueue(); q.resolve("rq-9999")`
  - **不正な理由**: item_id="rq-9999" は add されておらず対象が存在しない。
  - **実際の発生シナリオ**: 上位が誤った item_id を渡す実装バグ。
- **期待される結果**: 例外 (`KeyError` または `ValueError`) を送出する。ledger 注入時も
  review_resolve を追記しない (存在しない解決を記録しない)。
  - **エラーメッセージの内容**: 未知の item_id である旨を示す。
  - **システムの安全性**: 誤った解決記録の混入を防ぐ。
- **テストの目的**: 未知 item_id の防御挙動を確認。
  - **品質保証の観点**: 完了条件・受け入れ基準は本ケースを要求しないため妥当な設計判断として明示化。
- 🟡 (要件定義 2.4/4.3 の縮退記述からの妥当な推測。完了条件外の防御的挙動)

---

## 3. 境界値テストケース（最小値、最大値、null等）

### B-01: 空 ranked で all_high_r / close_competitor が発火しない
- **境界値の意味**: `result.ranked == ()` (候補ゼロ経路) という最小データ境界。
- **境界値での動作保証**: 空集合で `all(...)` が真空的 True を返す罠を回避する。
- **入力値**: `ranked=[]`、unknown_phase=False、staged=False
  - **境界値選択の根拠**: EDGE-004 (裁定対象ゼロ) 相当。空 ranked での過検出を防ぐ。
  - **実際の使用場面**: 候補が枝刈りされ ranked が空になったフレームの裁定。
- **期待される結果**: `()`。all_high_r は非発火 (ranked 非空条件を満たさない)、close_competitor は
  非発火 (2 位不在)。
  - **境界での正確性**: 空集合で誤って all_high_r を立てない。
  - **一貫した動作**: unknown_phase / guard_escalated は空 ranked でも引数/フラグ次第で独立に立ち得る
    (別テストで担保)。
- **テストの目的**: 空 ranked の縮退挙動を確認 (真空的 True 回避)。
  - **堅牢性の確認**: 空入力でクラッシュ・過検出しない。
- 🔵 (要件定義 2.2 (a) 空ガード / 4.3 / tree.py 空縮退パターン)

### B-02: all_high_r の閾値ちょうど（Rwp == threshold）は発火しない
- **境界値の意味**: Rwp が `high_r_threshold` と厳密一致する境界。
- **境界値での動作保証**: 厳密超過 `>` で判定し、閾値ちょうどは高 R に含めない。
- **入力値**: `ranked=[_ranked("h0",30.0,False), _ranked("h1",30.0,False)]`、high_r_threshold=30.0
  - **境界値選択の根拠**: `>` と `>=` の差が現れる唯一の境界点 (30.0)。
  - **実際の使用場面**: Rwp がちょうど閾値のフレーム。
- **期待される結果**: all_high_r は発火しない → (他条件なしなら) `()`。
  - **境界での正確性**: `rwp > 30.0` は 30.0 で False。
  - **一貫した動作**: search/tree.py `_compute_unmatched` L855 の `rwp > high_r_threshold` と表現統一。
- **テストの目的**: 境界の厳密比較を確認。
  - **堅牢性の確認**: 境界値でのオフバイワンを防ぐ。
- 🔵 (要件定義 3 境界の厳密比較 / tree.py L855)

### B-03: ranked 1 件のみでは close_competitor が発火しない
- **境界値の意味**: ranked が 1 件 (2 位不在) という境界。
- **境界値での動作保証**: `ranked[0]` は rank() 実装上つねに close=True だが、2 位不在では僅差競合と
  みなさない。
- **入力値**: `ranked=[_ranked("h0",5.0,True)]`、unknown_phase=False、staged=False
  - **境界値選択の根拠**: 「唯一の最良仮説」= 競合が存在しないケース。ranked[0].close=True の罠を検証。
  - **実際の使用場面**: 候補が 1 つに絞られた明確な裁定。
- **期待される結果**: `()`。close_competitor は `len(ranked) >= 2` を満たさず非発火。
  - **境界での正確性**: ranked[0] の close=True を無視し 2 位のフラグで判定する。
  - **一貫した動作**: N-03 (2 件僅差) と対になり、1 件では発火しないことを担保。
- **テストの目的**: close_competitor 判定が 2 位基準であることを確認。
  - **堅牢性の確認**: 単一最良仮説を僅差競合と誤検出しない (D6「1-2 位」の正確な解釈)。
- 🔵 (要件定義 2.2 (c) / D6 (c) / ranking.py rank ranked[0] は常に close=True)

### B-04: item_id 連番の決定論（rq-0000 → rq-0001 → rq-0002）
- **境界値の意味**: 連続追加時の連番採番の決定論 (0 起点・4 桁ゼロ埋め)。
- **境界値での動作保証**: 追加順に単調増加する一意 item_id を採番する。
- **入力値**: `q = ReviewQueue(); [q.add("all_high_r") for _ in range(3)]`
  - **境界値選択の根拠**: 採番規則の起点と桁埋めを最小連続で検証。
  - **実際の使用場面**: 1 回の裁定で複数エスカレーションが同時に Queue へ入る。
- **期待される結果**: `[i.item_id for i in q.items] == ["rq-0000", "rq-0001", "rq-0002"]`。
  - **境界での正確性**: 0 起点・"rq-{n:04d}" 形式・連番。
  - **一貫した動作**: 乱数不使用でビット同一 (NFR-102)。
- **テストの目的**: item_id 連番の決定論を確認 (完了条件⑤)。
  - **堅牢性の確認**: 同一操作列で毎回同一 ID 列。
- 🔵 (要件定義 2.4 / 完了条件⑤ / NFR-102)

### B-05: high_r_threshold 引数のカスタム値が反映される
- **境界値の意味**: 既定 30.0 と異なる閾値を渡したときの判定切替。
- **境界値での動作保証**: キーワード引数 high_r_threshold が判定に効く。
- **入力値**: `ranked=[_ranked("h0",25.0,False)]` に対し
  `detect_escalations(result, high_r_threshold=20.0)` と `high_r_threshold=30.0` の 2 通り。
  - **境界値選択の根拠**: 同じ Rwp=25 が閾値 20 では高 R・閾値 30 では非高 R に分かれる点。
  - **実際の使用場面**: 呼び出し側が SearchConfig の閾値等を渡すケース。
- **期待される結果**: `high_r_threshold=20.0` → `("all_high_r",)` (25 > 20)、
  `high_r_threshold=30.0` → `()` (25 ≤ 30)。
  - **境界での正確性**: 引数が判定式に正しく渡ること。
  - **一貫した動作**: 既定値 30.0 は SearchConfig.high_r_threshold と一致。
- **テストの目的**: 閾値引数の反映を確認。
  - **堅牢性の確認**: パラメータ化された判定が正しく切り替わる。
- 🔵 (要件定義 2.2 引数仕様 / interfaces.py L341 / tree.py L90)

### B-06: detect_escalations の純粋性（SearchResult 非破壊 + 2 回ビット同一）
- **境界値の意味**: 純粋関数の不変条件 (副作用なし・冪等) という質的境界。
- **境界値での動作保証**: 同一 SearchResult を 2 回渡して結果がビット同一、かつ入力が変化しない。
- **入力値**: 任意の `result` (例: N-06 の 4 条件同時) を用意し `detect_escalations` を 2 回呼ぶ。
  呼び出し前後で `result.ranked` / `result.unmatched` / `len(result.ledger.entries)` を記録。
  - **境界値選択の根拠**: D6「純粋関数」・NFR-102「ビット同一」の直接検証。
  - **実際の使用場面**: 再現性 (REQ-402) を担保する解析パイプライン。
- **期待される結果**: 2 回の返り値が `==`。呼び出し前後で `result.ranked` / `result.unmatched` が不変、
  `result.ledger.entries` の件数が増えていない (ledger に書かない)。
  - **境界での正確性**: 副作用ゼロ・冪等。
  - **一貫した動作**: ledger 記録は ReviewQueue 側の責務であり detect_escalations は行わない。
- **テストの目的**: 純粋関数性を確認 (D6 / NFR-102)。
  - **堅牢性の確認**: 決定論・非破壊性の担保。
- 🔵 (要件定義 3 純粋関数制約 / D6 / NFR-102 / REQ-402)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12 (uv 管理, src layout + hatchling)。本タスクは
    selection パッケージのため既存言語に一致。
  - **テストに適した機能**: `@dataclass(frozen=True)` の `FrozenInstanceError`、`Literal` 型、
    `dataclasses.replace`、純粋関数の冪等検証。
- **テストフレームワーク**: pytest >= 8 + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` で設定済み。既存
    `tests/test_model_m2.py` / `test_tree_search.py` が pytest 準拠。
  - **テスト実行環境**: `uv run pytest tests/test_selection.py` (単体) / `uv run pytest` (全体回帰)。
    依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。本タスクは GSAS-II 非依存のため
    `gsas` マーカー不要。
- 🔵 (note.md §5 テスト関連情報 / pyproject.toml)

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下の形式で日本語コメントを付す (既存 M1/M2 テスト test_model_m2.py / test_tree_search.py の慣習に準拠)。

```python
# 【テスト目的】: close_competitor が「2 位」の僅差でのみ発火することを確認 (D6 (c))
# 【テスト内容】: 2 件僅差 (両者 close=True) の SearchResult を detect_escalations に渡す
# 【期待される動作】: ("close_competitor",) を返す
# 🔵 信頼性: D6 (c) / TC-107-06
def test_detect_close_competitor_single():
    # 【テストデータ準備】: ΔBIC が閾値未満の 1-2 位 (ともに close_competitor=True)
    # 【初期条件設定】: Rwp は低く unknown_phase=False、staged=False で (c) のみ発火させる
    result = _result([_ranked("h0", 5.0, True), _ranked("h1", 6.0, True)], unknown_phase=False)

    # 【実際の処理実行】: エスカレーション条件を検出
    # 【処理内容】: 2 位 close_competitor フラグを読み取り (c) を判定
    reasons = detect_escalations(result, staged_escalated=False)

    # 【結果検証】: close_competitor のみが返ること
    # 【検証項目】: 単独検出 (他条件は非発火)
    # 🔵 信頼性: TC-107-06
    assert reasons == ("close_competitor",)  # 【確認内容】: 2 位僅差の単独検出
```

frozen / 削除 API 不在の標準形:

```python
import dataclasses
import pytest

def test_review_item_is_frozen():
    q = ReviewQueue()
    item = q.add("all_high_r")
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.resolved = True  # 【確認内容】: frozen のため再代入不可

def test_review_queue_has_no_delete_api():
    q = ReviewQueue()
    # 【確認内容】: 削除系 API を構造的に持たない (P2 / TC-107-07)
    assert not hasattr(q, "delete") and not hasattr(q, "pop") and not hasattr(q, "clear")
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (detect_escalations 純粋関数 + ReviewQueue/ReviewItem 追記型)
- **参照した入力・出力仕様**: 要件定義 §2.1〜2.5 (EscalationReason / detect_escalations 4 条件 /
  ReviewItem / ReviewQueue / データフロー)
- **参照した制約条件**: 要件定義 §3 (P2 非破壊 / 純粋関数 / 決定論 / 処理ブロックなし / frozen /
  厳密比較 / 型注釈)
- **参照した使用例**: 要件定義 §4 (基本パターン・データフロー・エッジケース・エラーケース)
- **参照した受け入れ基準**: TC-107-06 (エスカレーション 4 条件がそれぞれ Queue に入る) →
  N-01〜N-04 (単独検出) + N-06 (同時) + N-07 (Queue 追記)、TC-107-07 (追記型・resolve マーク・削除 API なし) →
  N-08/N-09 + E-01/E-02 + B-04
- **参照した完了条件**: ①4 条件単独検出 → N-01〜N-04、②条件なし空タプル → N-05 / B-01〜B-03、
  ③Queue 追記型/削除 API 不在 → N-08/N-09/E-02、④ledger 連携 review_add/review_resolve → N-10、
  ⑤item_id 連番決定論 → B-04
- **回帰ゲート (テスト外)**: `uv run pytest` 全体で既存テストを無改変 green のまま維持 +
  新規 `tests/test_selection.py` green。既存テストファイルは 1 行も変更しない。

---

## 品質判定結果

- **テストケース分類**: 正常系 10 / 異常系 3 / 境界値 6 を網羅 ✅
  (detect_escalations 4 条件の単独 + 同時 + 空 + 境界、ReviewQueue の add/resolve/unresolved/ledger/frozen/
  削除 API 不在/連番 を網羅)
- **期待値定義**: 各ケースに具体的期待値 (タプル内容・item_id・resolved・件数・kind 名) を明記 ✅
- **技術選択**: Python 3.12 + pytest で確定 ✅
- **実装可能性**: 純データ構造 + 純粋関数 + テストダブルで現行スタックにより確実に実現可能 ✅
- **信頼性レベル**: 🔵 17 / 🟡 2 / 🔴 0 — **✅ 高品質**
