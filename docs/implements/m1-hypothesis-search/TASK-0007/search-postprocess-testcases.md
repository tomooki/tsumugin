# TASK-0007 探索後処理 — TDD テストケース定義書

- **機能名**: 探索後処理 (Jenks 良好解抽出 / 最終フル精密化・再ランク / 未マッチ集約・未知相フラグ / warnings / to_summary)
- **タスクID**: TASK-0007 / **要件名**: m1-hypothesis-search
- **実装ファイル**: `src/tsumugin/search/tree.py` (拡張 — 後処理スタブの実体化)
- **テストファイル**: `tests/test_tree_search.py` (**追加** — 既存 20 ケース TC-N01〜10 / TC-E01〜04 / TC-B01〜06 と共存するため、本タスクは **TC-N11〜18 / TC-E05〜07 / TC-B07〜11 の継番**を用いる)
- **作成日**: 2026-07-03
- **信頼性レベル凡例**: 🔵 元資料 (要件定義・受け入れ基準・既存実装) に直接依拠 / 🟡 元資料からの妥当な推測 / 🔴 元資料にない推測

## 共通前提 (Given の共通部)

- 観測グリッド `GRID = np.arange(15.0, 60.0, 0.02)`、候補相 `PHASE_A(a=5)/B(6)/C(4.5)/D(7)/G(6.5)`
  (真の相 A/B、無関係相 C/D — `tests/test_tree_search.py` 既存ヘルパを再利用) 🔵
- backend は原則 `SimulatedBackend`。Rwp を厳密制御する TC-E05 / TC-B09 は既存 `FakeBackend` を流用 🔵
- 合成データは `SimulatedBackend.simulate(phases, GRID)` で生成し `HypothesisTreeSearch(...).search(...)` を実行 🔵
- 決定論検証は `==` ビット同一、物理量近似は `pytest.approx` (既存書式の範に従う) 🔵

---

## 1. 正常系テストケース（基本的な動作） — 8 件

### TC-N11: Jenks 良好解抽出 — good_cluster_ids に真の構成仮説が入る (TC-004-03 統合) 🔵

- **テスト名**: 2 相合成データの探索で Jenks が低 evidence 群を分離し `good_cluster_ids` に格納される
  - **何をテストするか**: `jenks_breaks` (n_classes=2) による ranked 仮説の evidence(BIC) 2 群分割と、低 evidence 群 (良好解) の**仮説 ID タプル**化
  - **期待される動作**: 良好解 (真の構成 {A,B} 系) の ID が `good_cluster_ids` に含まれ、無関係相のみの劣位仮説 ID は含まれない
- **入力値**: A+B の 2 相合成パターン、候補 [A, B, C, D]
  - **入力データの意味**: evidence が明確に 2 群 (良好 vs 劣位) に分かれる代表構成 (受け入れ基準 TC-004-03 / 既存 TC-N01 と同一データで統合確認)
- **期待される結果**:
  - `result.good_cluster_ids` が非空の `tuple[str, ...]` で、`result.ranked[0].hypothesis.id` を含む
  - `good_cluster_ids` の全要素が `result.hypotheses` のキーに存在する (index でなく ID であること)
  - 最劣位 (evidence 最大) の仮説 ID は含まれない
  - **期待結果の理由**: FR-116 / REQ-104 — 良好解は「evidence 値 <= breaks[0]」の低 evidence 群 (要件定義 §3.6)
- **テストの目的**: Jenks 良好解抽出の統合確認
  - **確認ポイント**: ID タプルであること (interfaces.py L165)、ranked 上位との整合
- 🔵 acceptance-criteria TC-004-03 + note §5 に直接依拠

### TC-N12: 最終フル精密化 — final_reports 記録と metrics 更新 (D3) 🟡

- **テスト名**: `final_full_refine=True` (既定) で良好解上位に `StagedRefinementEngine` フル精密化が適用される
  - **何をテストするか**: 良好解上位 `max_final_refine` 件への フルテンプレート適用、`final_reports` への記録、`hypotheses` の metrics 更新 (新インスタンス差し替え)
  - **期待される動作**: `final_reports` のキーが `good_cluster_ids` の上位 (evidence 昇順) と一致し、値は `RefinementReport` (final_phases / metrics / stage_outcomes / escalated / free_params を持つ)
- **入力値**: TC-N11 と同じ A+B 合成データ・候補 [A, B, C, D]、`SearchConfig()` 既定 (final_full_refine=True, max_final_refine=3)
  - **入力データの意味**: 良好解が存在する基本ケースで D3 の既定動作を確認
- **期待される結果**:
  - `result.final_reports` が非空で、全キーが `good_cluster_ids` に含まれる
  - 各キーの `result.hypotheses[key].metrics` が `final_reports[key].metrics` と整合する (rwp/gof 反映)
  - `result.hypotheses[key].metrics.evidence` に "bic" キーが存在する (再計算済み)
  - **期待結果の理由**: architecture.md D3 (L100-106) + 要件定義 §3.6 — フル精密化後は BIC 再計算・metrics 差し替え
- **テストの目的**: D3 フル精密化の配線確認
  - **確認ポイント**: `final_reports` の値型が `RefinementReport` であること、元 `Hypothesis` の破壊がないこと (frozen + replace)
- 🟡 設計 D3 (architecture.md 🟡) からの妥当な導出

### TC-N13: フル精密化後の再ランキング — ranked が evidence 昇順で確定する (D3) 🟡

- **テスト名**: フル精密化後に `rank()` が再実行され `ranked` が更新後 evidence の昇順 (良い順) になる
  - **何をテストするか**: metrics 更新 → BIC 再計算 → 再ランクのフロー (dataflow §4.5)
  - **期待される動作**: `result.ranked` の evidence 値列が非減少 (昇順) で、rank1 は真の構成 {A,B}
- **入力値**: TC-N11 と同じ A+B 合成データ・候補 [A, B, C, D]
  - **入力データの意味**: 再ランク後も真の構成が 1 位を維持する代表ケース (TC-001-01 の後処理版)
- **期待される結果**:
  - `[rk.evidence.value for rk in result.ranked]` が昇順
  - `_refs(result.ranked[0].hypothesis) == {"A", "B"}` を維持
  - 各 `rk.evidence.value` が対応する `hypotheses[rk.hypothesis.id].metrics.evidence["bic"]` と一致 (更新後の値で整列)
  - **期待結果の理由**: 要件定義 §2.2 「ranked = フル精密化後に再ランクした列 (良い順)」
- **テストの目的**: 再ランクの正しさと整合性確認
  - **確認ポイント**: ranked と hypotheses の evidence 値がフル精密化後の値で一致すること
- 🟡 設計 D3 + ranking 既存契約からの妥当な導出

### TC-N14: フル精密化の無効化 — final_full_refine=False で final_reports 空・metrics 不変 🟡

- **テスト名**: `SearchConfig(final_full_refine=False)` でフル精密化がスキップされる
  - **何をテストするか**: config による D3 の無効化経路
  - **期待される動作**: `final_reports == {}` かつ探索モード精密化時の metrics から変化しない
- **入力値**: TC-N11 と同じデータ・候補、`SearchConfig(final_full_refine=False)`
  - **入力データの意味**: 有効時 (TC-N12) と同一データで無効化の差分だけを観測する対照実験
- **期待される結果**:
  - `result.final_reports == {}` (Mapping として空)
  - `final_full_refine=True` の実行結果と比べ、`good_cluster_ids` は同一だが精密化由来の metrics 更新が起きない (無効時の rank1 の rwp が探索モード精密化の値のまま)
  - `good_cluster_ids` / `unmatched` / `to_summary()` は例外なく成立する
  - **期待結果の理由**: 要件定義 §3.6 「`final_full_refine=False` で無効 (`final_reports={}`・metrics 不変)」
- **テストの目的**: 設定フラグの効力確認
  - **確認ポイント**: 無効化してもその他の後処理 (Jenks / unmatched / summary) は動作すること
- 🟡 設計 D3 (無効化仕様) に依拠した妥当な導出

### TC-N15: 完全説明データ — 未マッチ空・unknown_phase_flag=False (TC-005-02) 🔵

- **テスト名**: 候補相で完全に説明できるデータでは未マッチピークが空でフラグが立たない
  - **何をテストするか**: 最良仮説基準の未マッチ集約 (`unmatched_peaks`) の「全説明」経路
  - **期待される動作**: `unmatched.unmatched_observed == ()`、`unmatched.extra_calculated == ()`、`unknown_phase_flag is False`
- **入力値**: A+B の 2 相合成パターン、候補 [A, B, C, D] (真の構成が候補に完全に含まれる)
  - **入力データの意味**: 観測の全ピークが最良仮説 {A,B} で説明される理想ケース (受け入れ基準 TC-005-02)
- **期待される結果**:
  - `result.unmatched.unmatched_observed == ()`
  - `result.unmatched.unknown_phase_flag is False`
  - **期待結果の理由**: REQ-005/106 — 未マッチ観測が空かつ全仮説高 R でなければフラグは False
- **テストの目的**: 偽陽性 (不要な未知相フラグ) がないことの確認
  - **確認ポイント**: bool 型での厳密比較 (`is False`)
- 🔵 acceptance-criteria TC-005-02 に直接依拠

### TC-N16: 候補にない相の混入 — 未マッチピーク報告 + unknown_phase_flag=True (TC-005-01) 🔵

- **テスト名**: 真の構成に「候補にない相」を混ぜたデータで未マッチ観測ピークが位置・強度付きで報告される
  - **何をテストするか**: 未知相混入時の `UnmatchedPeakReport` 構築と未知相フラグ (FR-117 / REQ-106)
  - **期待される動作**: 未説明ピークが `Peak(position, height)` 実体・位置昇順で報告され、フラグが True
- **入力値**: A+B+G の 3 相合成パターン (G は候補に**含めない**)、候補 [A, B, C, D]
  - **入力データの意味**: G (a=6.5) のピークはどの候補でも説明できない — 実運用の「未知相の混入」を模擬 (受け入れ基準 TC-005-01)
- **期待される結果**:
  - `result.unmatched.unmatched_observed` が非空で、各要素が `position` (float, G のピーク位置近傍) と `height` (float > 0) を持つ
  - `unmatched_observed` が位置昇順に整列している
  - `result.unmatched.unknown_phase_flag is True`
  - **期待結果の理由**: REQ-005 — 未マッチ観測ピークは位置・強度付き報告。REQ-106 — 未マッチ非空でフラグ True
- **テストの目的**: 未知相の見落とし防止 (本機能の中核価値) の確認
  - **確認ポイント**: 位置が G 由来ピークと `pytest.approx` (match_tol_deg 内) で対応すること、強度が正値であること
- 🔵 acceptance-criteria TC-005-01 に直接依拠

### TC-N17: to_summary() — /api/result スキーマ準拠と JSON 化可能性 🔵🟡

- **テスト名**: `to_summary()` が `/api/result` スキーマの全キーを持つ純 dict を返し `json.dumps` が成功する
  - **何をテストするか**: D6 契約 — キー集合・値の素の型 (str/int/float/bool/None/list/dict)・JSON 化
  - **期待される動作**: numpy スカラー・dataclass を露出しない完全な純 dict
- **入力値**: TC-N11 と同じ A+B 合成データ・候補 [A, B, C, D] の探索結果
  - **入力データの意味**: ranked / good_cluster / unmatched / warnings が全て埋まり得る代表ケース
- **期待される結果**:
  - トップレベルキー: `{"ranked", "unknown_phase_flag", "unmatched_observed", "extra_calculated", "warnings", "n_hypotheses"}` が全て存在
  - `summary["ranked"][i]` が `{"id", "rank", "probability", "close_competitor", "rwp", "gof", "evidence", "parent_id", "phases", "in_good_cluster"}` を持ち、`rank == i+1`、`evidence == {"backend": ..., "value": ...}`、`phases[j]` が `{"phase_ref", "wt_frac", "lattice"}`・`lattice` が `{"a","b","c"}` を持つ
  - `summary["ranked"][0]["in_good_cluster"] is True` (rank1 は良好解)、`in_good_cluster` の真偽が `good_cluster_ids` と一致
  - `summary["n_hypotheses"] == len(result.hypotheses)`、`summary["unknown_phase_flag"] is False`
  - `json.dumps(result.to_summary())` が例外なく成功 (往復 `json.loads` で同値)
  - **期待結果の理由**: api-endpoints.md `/api/result` (L24-52) + note §4.4 のフィールド対応表
- **テストの目的**: TASK-0009 (Web UI) への配信契約の固定
  - **確認ポイント**: 値型が素の Python 型であること (`type(v) is float` 等、np.float64 の混入検出)
- 🔵 スキーマのキー集合は api-endpoints.md に直接依拠 / 🟡 D6 自体の信頼性は設計由来

### TC-N18: 後処理の監査一貫性 — 単一 ledger への追記と verify()=True 維持 🔵

- **テスト名**: フル精密化・再ランクを含む後処理後も `ledger.verify()` が True で、後処理の記録が同一 ledger に追記される
  - **何をテストするか**: 探索とフル精密化が単一 `Ledger`/`SnapshotStore` を共有し監査チェーンが 1 本であること (TC-008-01 の後処理拡張)
  - **期待される動作**: `result.ledger.verify() is True`、後処理由来のエントリ (良好解抽出/フル精密化/再ランク等) が探索記録の後に追記されている
- **入力値**: TC-N11 と同じ A+B 合成データ・候補 [A, B, C, D]、`final_full_refine=True`
  - **入力データの意味**: フル精密化が実際に走る (= ledger 追記が発生する) 代表ケース
- **期待される結果**:
  - `result.ledger.verify() is True`
  - 後処理有効時のエントリ総数 > `final_full_refine=False` 時のエントリ総数 (追記のみで記録が増える)
  - **期待結果の理由**: 要件定義 §3.2 「探索とフル精密化を単一 ledger/snapshots で共有し verify()=True を維持」
- **テストの目的**: 非破壊性・監査一貫性の退行防止
  - **確認ポイント**: 既存 TC-008-01 (`test_ledger_verify_true_after_search`) を壊さず後処理分が上乗せされること
- 🔵 REQ-402 / note §6 (同一 ledger/snapshots の共有) に直接依拠

---

## 2. 異常系テストケース（エラーハンドリング） — 3 件

### TC-E05: 全仮説高 R — unknown_phase_flag=True + 最良仮説を要確認として返す (TC-E02 / EDGE-002) 🔵

- **テスト名**: 全 refined 仮説の Rwp が `high_r_threshold` を超えるとき未知相フラグが強制的に立つ
  - **エラーケースの概要**: どの候補仮説も観測をまともに説明できない (全滅) 状況
  - **エラー処理の重要性**: 「最も良い仮説」でも信頼できないことを解析者へ明示しないと誤採択を招く
- **入力値**: `FakeBackend(default_rwp=50.0)` (全組合せ Rwp=50 > 既定閾値 30.0) + A+B 合成データ・候補 [A, B]
  - **不正な理由**: Rwp > high_r_threshold は「解として不十分」の規約 (REQ-106)
  - **実際の発生シナリオ**: 候補データベースに真の相が 1 つも入っていない試料の解析
- **期待される結果**:
  - 例外が発生せず `search()` が完走する
  - `result.unmatched.unknown_phase_flag is True` (未マッチの有無に**依らず**強制 True)
  - `result.ranked` が非空で最良仮説が返る (要確認情報として利用可能)
  - `result.to_summary()["unknown_phase_flag"] is True`
  - **エラーメッセージの内容**: 例外ではなくフラグで伝達 (失敗の非例外化)
  - **システムの安全性**: 全滅時も結果構造は完全な形で返る
- **テストの目的**: EDGE-002 の縮退経路確認
  - **品質保証の観点**: `high_r_flag = all(h.metrics.rwp > threshold)` の配線ミス (any との取り違え等) を検出
- 🔵 acceptance-criteria TC-E02 / EDGE-002 / REQ-106 に直接依拠

### TC-E06: フラットパターン — 例外なし・空良好解・warnings 非空・フラグ False (TC-005-03 / EDGE-003) 🟡

- **テスト名**: 観測ピーク 0 のフラットパターンで例外なく縮退し警告が積まれる
  - **エラーケースの概要**: 強度がほぼ一定 (ピーク検出 0 件) の縮退入力
  - **エラー処理の重要性**: 前処理ミス・空測定のデータでもパイプライン全体を止めない
- **入力値**: `intensity = np.full_like(GRID, 100.0)` (完全フラット)、候補 [A, B]
  - **不正な理由**: `find_peaks` が `()` を返しマッチング・説明の対象が存在しない
  - **実際の発生シナリオ**: 測定失敗・バックグラウンドのみのデータ投入
- **期待される結果**:
  - 例外が発生せず `search()` が完走する
  - `result.good_cluster_ids == ()` (空の良好解)
  - `result.warnings` が非空 (`len(result.warnings) >= 1`、縮退理由を含む文字列)
  - `result.unmatched.unknown_phase_flag is False` (**説明対象が無いのでフラグは立てない** — EDGE-002 との区別)
  - `result.to_summary()["warnings"]` に同警告が現れ `json.dumps` 成功
  - **エラーメッセージの内容**: warnings の文字列が縮退 (フラット/ピーク 0) を示すこと
  - **システムの安全性**: 空スキーマの summary が成立し後続 (Web UI) が安全に扱える
- **テストの目的**: EDGE-003 の縮退経路と EDGE-002 との取り違え防止
  - **品質保証の観点**: 「フラット → warnings、全高 R → フラグ」の対応関係を固定 (note §6)
- 🟡 acceptance-criteria TC-005-03 (🟡) — フラグ False の扱いは note §6 の設計判断由来

### TC-E07: 候補ゼロ経路の整合 — _empty_result でも to_summary() が空スキーマで成立 (EDGE-001 整合) 🔵

- **テスト名**: 候補ゼロで空の SearchResult が返り、`to_summary()` が同一スキーマの空 summary を返す
  - **エラーケースの概要**: `candidates=[]` での探索 (既存 TC-E01 の後処理拡張)
  - **エラー処理の重要性**: 上流の候補生成が空を返しても API 応答契約 (キー集合) を破らない
- **入力値**: A+B 合成データ、`candidates=[]`
  - **不正な理由**: 探索対象が存在しない
  - **実際の発生シナリオ**: 候補フィルタが全滅した場合の呼び出し
- **期待される結果**:
  - `result.good_cluster_ids == ()` / `result.final_reports == {}` (Mapping として空) / `result.unmatched.unmatched_observed == ()`
  - `summary = result.to_summary()` が TC-N17 と**同一のトップレベルキー集合**を持ち、`summary["ranked"] == []`、`summary["n_hypotheses"] == 0`
  - `json.dumps(summary)` が成功
  - 既存 TC-E01 (`test_zero_candidates_returns_empty_result_without_error`) が引き続き green
  - **エラーメッセージの内容**: 例外なし (空スキーマで伝達)
  - **システムの安全性**: 空でもスキーマ互換 → Web UI 側の分岐不要
- **テストの目的**: `_empty_result` と本実装の整合維持
  - **品質保証の観点**: スタブ実体化時に候補ゼロ経路を壊す退行の検出
- 🔵 EDGE-001 + note §6 (候補ゼロ経路との整合) に直接依拠

---

## 3. 境界値テストケース（最小値、最大値、縮退等） — 5 件

### TC-B07: 仮説 1 件 — Jenks 境界不能 () 縮退時のフォールバック (単一仮説はそのまま良好解) 🟡

- **テスト名**: 候補 1 相 (refined 仮説 1 件) で `jenks_breaks` が `()` を返しても単一仮説が良好解になる
  - **境界値の意味**: Jenks 2 群分割の最小成立数を下回る入力 (要素 1)
  - **境界値での動作保証**: 境界不能でも例外なく決定論的なフォールバックへ倒れる
- **入力値**: A 単相合成データ、候補 [A] (既存 TC-B03 の単一候補構成を流用)
  - **境界値選択の根拠**: `jenks_breaks` は「要素 0/1 で `()` へ縮退」(clustering.py 契約)。1 件は最小の非空ケース
  - **実際の使用場面**: 候補が 1 つしか無い既知試料の確認解析
- **期待される結果**:
  - `result.good_cluster_ids == (result.ranked[0].hypothesis.id,)` (単一仮説がそのまま良好解)
  - `final_full_refine=True` なら `final_reports` にその 1 件が記録される
  - 例外なし・`to_summary()` 成立
  - **境界での正確性**: フォールバック規則「単一はそのまま良好解」を**この テストで固定**する (要件定義 §3.6 の「実装時に確定」事項)
  - **一貫した動作**: 2 件以上の通常経路 (TC-N11) と結果構造が同型
- **テストの目的**: Jenks 縮退フォールバックの規則固定
  - **堅牢性の確認**: 空タプル `breaks` へのインデックスアクセス等による IndexError がないこと
- 🟡 縮退条件は clustering.py 契約 🔵、フォールバック規則自体は要件定義が「実装時に確定」とする推奨案 (🟡)

### TC-B08: 全 evidence 同値 — Jenks 境界不能時は全仮説を良好解にする 🟡

- **テスト名**: 全 refined 仮説の evidence(BIC) が同値のとき全仮説が `good_cluster_ids` に入る
  - **境界値の意味**: 分散 0 の入力では 2 群分割が定義不能 (`jenks_breaks` → `()`)
  - **境界値での動作保証**: 「区別できない場合は落とさず全て残す」安全側の縮退
- **入力値**: `FakeBackend` で全相組合せに同一 (rwp, chi2) を返す設定 + 候補 [A, B] (既存 TC-B05 の同スコア構成を流用)
  - **境界値選択の根拠**: 全同値は Jenks の縮退条件として明記されている (要件定義 §3.6)
  - **実際の使用場面**: 判別力のないデータ・候補群 (どれも同程度に合う/合わない)
- **期待される結果**:
  - `set(result.good_cluster_ids) == set(h.id for 全 refined 仮説)` (全て良好解)
  - `good_cluster_ids` の並びが決定論的 (evidence 同値 → ID 昇順等の一意規則)
  - 例外なし
  - **境界での正確性**: フォールバック「全同値は全て良好解」をこのテストで固定
  - **一貫した動作**: 通常分離時 (TC-N11) の部分集合抽出と型・構造が一致
- **テストの目的**: 縮退フォールバック第 2 規則の固定と決定論の担保
  - **堅牢性の確認**: 同値時のソート安定性 (同点は ID 昇順)
- 🟡 要件定義 §3.6 の推奨フォールバック (実装時確定事項) に基づく

### TC-B09: high_r_threshold ちょうど — Rwp == 閾値では高 R フラグが立たない (厳密比較 >) 🟡

- **テスト名**: 全仮説の Rwp が `high_r_threshold` と**等値**のとき `unknown_phase_flag` は立たない
  - **境界値の意味**: 「Rwp > high_r_threshold」の比較演算子の境界 (>= との取り違え検出)
  - **境界値での動作保証**: 閾値ちょうどは「高 R でない」側に倒れる
- **入力値**: `FakeBackend(default_rwp=30.0)` (== 既定閾値 30.0)、完全説明データ (A+B 合成・候補 [A, B]、未マッチ観測なし)
  - **境界値選択の根拠**: REQ-106 の条件式が「Rwp > high_r_threshold」と**厳密不等号**で規定されている
  - **実際の使用場面**: 閾値近傍の中庸な適合度での判定安定性
- **期待される結果**:
  - `result.unmatched.unknown_phase_flag is False` (未マッチも空・高 R フラグも立たない)
  - 対照: `default_rwp=30.0 + ε` (例 30.1) にすると True になる (境界の両側を確認)
  - **境界での正確性**: `all(rwp > threshold)` の等値除外
  - **一貫した動作**: TC-N15 (低 R・False) / TC-E05 (高 R・True) と単調に整合
- **テストの目的**: 比較演算子境界の固定
  - **堅牢性の確認**: 閾値設定変更 (`SearchConfig(high_r_threshold=...)`) がフラグ判定へ正しく伝播すること
- 🟡 条件式 (>) は要件定義 §3.6 🔵 由来、等値ケースの挙動指定はそこからの論理的導出 (🟡)

### TC-B10: max_final_refine 境界 — フル精密化対象は「良好解上位 min(max_final_refine, 良好解数) 件」 🟡

- **テスト名**: 良好解が `max_final_refine` を超えるとき上位のみ、下回るとき全良好解が精密化される
  - **境界値の意味**: フル精密化件数の上限クリップの両側
  - **境界値での動作保証**: 件数が過不足なく決定論的に選出される
- **入力値**:
  - (a) `SearchConfig(max_final_refine=1)` + 良好解が 2 件以上できる構成 (A+B 合成・候補 [A, B, C, D])
  - (b) `SearchConfig(max_final_refine=3)` (既定) + 良好解 1 件の構成 (TC-B07 と同じ単一候補)
  - **境界値選択の根拠**: D3 「良好解上位 `max_final_refine` 件 (既定 3)」の上限適用有無が切り替わる境界
  - **実際の使用場面**: 計算コスト制御のための件数制限運用
- **期待される結果**:
  - (a) `len(result.final_reports) == 1` で、キーは良好解のうち evidence 最小 (最良) の仮説 ID
  - (b) `len(result.final_reports) == 1` (= 良好解数、上限に達しない)
  - 選出順が evidence 昇順・同点 ID 昇順で決定論的
  - **境界での正確性**: `min(max_final_refine, len(good))` 件の厳密性
  - **一貫した動作**: 既定値 3 (SearchConfig 既定確認は既存 TC-B03 に委譲) との整合
- **テストの目的**: 上限クリップと選出規則の固定
  - **堅牢性の確認**: off-by-one (上位 N+1 件精密化等) の検出
- 🟡 設計 D3 「上位 max_final_refine 件」🟡 からの境界導出

### TC-B11: 決定論 — 再ランク・後処理を含めて 2 回実行で to_summary() までビット同一 (TC-001-05 拡張) 🔵

- **テスト名**: 同一入力で 2 回探索し、`good_cluster_ids` / `final_reports` キー / `ranked` / `to_summary()` が完全一致する
  - **境界値の意味**: 浮動小数演算・辞書順序の非決定性が混入し得る全経路の網羅境界 (再現性の総合検証)
  - **境界値での動作保証**: フル精密化・再ランク追加後も REQ-403 のビット同一性が退行しない
- **入力値**: A+B 合成データ・候補 [A, B, C, D] で `search()` を独立に 2 回実行
  - **境界値選択の根拠**: TASK-0006 の TC-B04 (既存 `test_deterministic_bit_identical_across_runs`) が対象としない後処理フィールドまで拡張
  - **実際の使用場面**: 解析結果の監査・再現要求 (NFR-102)
- **期待される結果**:
  - `r1.good_cluster_ids == r2.good_cluster_ids` (`==` ビット同一)
  - `tuple(r1.final_reports.keys()) == tuple(r2.final_reports.keys())`
  - `[(rk.hypothesis.id, rk.probability, rk.evidence.value) for rk in r1.ranked] == [同 r2]`
  - `r1.to_summary() == r2.to_summary()` (dict 完全一致)
  - **境界での正確性**: 全ソートのキー明示・同点 ID 昇順規則の徹底
  - **一貫した動作**: 既存 TC-B04 (ranking の決定論) の上位互換
- **テストの目的**: 決定論退行防止 (後処理版)
  - **堅牢性の確認**: `pytest.approx` でなく `==` を用いる (ビット同一の要求)
- 🔵 NFR-102 / REQ-403 / 要件定義 §3.1 に直接依拠

---

## 回帰条件 (新規ケースではなく維持条件)

- 🔵 既存 `tests/test_tree_search.py` の **20 ケース (TC-N01〜10 / TC-E01〜04 / TC-B01〜06) が全て green を維持**すること。
  特に TC-001-05 決定論 (`test_deterministic_bit_identical_across_runs`)、TC-008-01 (`test_ledger_verify_true_after_search`)、
  TC-008-03 (`test_no_destructive_api_on_engine_and_result`)、骨格契約 (`test_search_result_skeleton_contract`) は
  本タスクのスタブ実体化で挙動が変わり得るため要注意 (契約テストは実体値でも成立する記述である前提。矛盾すれば
  スタブ前提のアサーションのみ実体仕様へ更新する)。
- 🔵 M0 テスト群 (70 件) と他 M1 テスト (`test_clustering.py` / `test_matcher.py` 等) も green 維持。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 (CPython)
  - **言語選択の理由**: プロジェクト規定 (pyproject.toml / CLAUDE.md)。コア依存は numpy >= 1.26 のみ
  - **テストに適した機能**: dataclass の `==` 比較でビット同一検証が簡潔、`json` 標準ライブラリで JSON 化検証が完結
- **テストフレームワーク**: pytest >= 8 (+ pytest-cov)
  - **フレームワーク選択の理由**: 既存全テスト (M0 70 件 + M1) が pytest。設定は `pyproject.toml [tool.pytest.ini_options]`
  - **テスト実行環境**: `uv run pytest tests/test_tree_search.py` / カバレッジは `uv run pytest --cov=tsumugin`。
    GSAS-II 非依存 (`SimulatedBackend` / `FakeBackend` で完結)
- 🔵 pyproject.toml / note.md §1・§5 に直接依拠

---

## 5. テストケース実装時の日本語コメント指針

各テストケースの実装時には以下の日本語コメントを必ず含める (既存 `tests/test_tree_search.py` の書式の範に従う):

```python
def test_jenks_good_cluster_ids_contains_top_hypothesis():
    # 【テスト目的】: Jenks natural breaks が低 evidence 群 (良好解) を分離し good_cluster_ids に ID が入ることを確認
    # 【テスト内容】: A+B 合成データ・候補 [A,B,C,D] で search() を実行し good_cluster_ids を検証
    # 【期待される動作】: rank1 仮説の ID が含まれ、最劣位仮説の ID は含まれない
    # 🔵 acceptance-criteria TC-004-03 に直接依拠

    # 【テストデータ準備】: 真の相 A/B と無関係相 C/D で evidence が 2 群に分かれる構成を作る
    # 【初期条件設定】: SimulatedBackend で A+B 合成パターンを生成
    # 【前提条件確認】: 既存 TC-N01 で {A,B} が rank1 になることは保証済み
    intensity = backend.simulate((PHASE_A, PHASE_B), GRID)

    # 【実際の処理実行】: HypothesisTreeSearch.search() を呼び出す (後処理込み)
    # 【処理内容】: _explore → _rank → good_cluster 抽出 → フル精密化 → 再ランク → unmatched → summary
    result = HypothesisTreeSearch(backend=backend, config=SearchConfig()).search(...)

    # 【結果検証】: good_cluster_ids の内容と型を検証する
    # 【期待値確認】: 低 evidence 群の仮説 ID タプル (FR-116)
    # 【品質保証】: 良好解の取りこぼし/混入は後続のフル精密化対象選定を誤らせるため中核検証
    # 【検証項目】: rank1 仮説 ID の包含 🔵
    assert result.ranked[0].hypothesis.id in result.good_cluster_ids  # 【確認内容】: 最良仮説が良好解に含まれる
    # 【検証項目】: ID が hypotheses のキーであること (index でないこと) 🔵
    assert all(i in result.hypotheses for i in result.good_cluster_ids)  # 【確認内容】: ID タプルである
```

- セットアップ/クリーンアップ: モジュールレベル不変データ (GRID / PHASE_*) を共有する既存方式を踏襲し、
  原則 `beforeEach` 相当 (fixture) は追加しない。fixture を追加する場合は
  `# 【テスト前準備】` / `# 【テスト後処理】` コメントを付す。
- 検証の使い分け: 決定論 (TC-B11) は `==` ビット同一、ピーク位置等の物理量は `pytest.approx`。

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `search-postprocess-requirements.md` §1 (機能の概要 — 後処理 5 項目)
- **参照した入力・出力仕様**: 同 §2 (SearchResult 完成形 / SearchConfig / データフロー §2.3)
- **参照した制約条件**: 同 §3 (決定論 §3.1 → TC-B11、非破壊 §3.2 → TC-N18、非例外化 §3.3 → TC-E05/E06/E07、
  スキーマ §3.4 → TC-N17、アルゴリズム契約 §3.6 → TC-N11〜14/B07〜10)
- **参照した使用例**: 同 §4 (基本 §4.1 → TC-N11/N12、未マッチ §4.2 → TC-N16、完全説明 §4.3 → TC-N15、
  スキーマ §4.4 → TC-N17、エッジ §4.5 → TC-E05/E06/E07/B07/B08/B11)
- **参照した受け入れ基準** (`docs/spec/m1-hypothesis-search/acceptance-criteria.md`):
  TC-004-03 → TC-N11 / TC-005-01 → TC-N16 / TC-005-02 → TC-N15 / TC-005-03 → TC-E06 / TC-E02 → TC-E05
- **参照した設計文書**: `architecture.md` D3 (→ TC-N12/N13/N14/B10) / D6 (→ TC-N17)、
  `api-endpoints.md` `/api/result` (→ TC-N17/E07)、`interfaces.py` SearchResult L160-176 (全ケースの型契約)
- **参照したコンテキスト**: `docs/implements/m1-hypothesis-search/TASK-0007/note.md` (§5 テスト関連情報・§6 注意事項)

---

## 7. テストケースサマリー

| 分類 | ケース番号 | 件数 |
|------|-----------|------|
| 正常系 | TC-N11〜TC-N18 | 8 |
| 異常系 | TC-E05〜TC-E07 | 3 |
| 境界値 | TC-B07〜TC-B11 | 5 |
| **新規合計** | | **16** |
| (回帰維持) | 既存 TC-N01〜10 / E01〜04 / B01〜06 | (20) |

### 信頼性レベル分布 (新規 16 件)

- 🔵 7 件 (44%): TC-N11, N15, N16, N17(スキーマ), N18, E05, E07, B11 のうちキー根拠が仕様直依拠のもの
- 🟡 9 件 (56%): TC-N12, N13, N14, E06, B07, B08, B09, B10 (+ N17 の D6 由来部分) — いずれも
  architecture.md D3/D6・要件定義 §3.6 の「実装時に確定」事項という**文書化済みの設計**からの導出であり、
  文書にない推測 (🔴) は 0 件
- 🔴 0 件

### 受け入れ基準カバレッジ

TASK-0007 完了条件 7 項目 (TC-004-03 / D3 有効・無効 / TC-005-01 / TC-005-02 / TC-E02 / TC-005-03 / to_summary) を
全て 1 つ以上のテストケースでカバー。加えて横断制約 (決定論 / 非破壊・ledger / 候補ゼロ整合 / 縮退フォールバック /
閾値・件数境界) を境界値・異常系で固定。

**品質評価**: ✅ 高品質
- テストケース分類: 正常系・異常系・境界値を網羅 (完了条件 7 項目 + 横断制約を全カバー)
- 期待値定義: 各ケースにアサーション水準の具体的期待値を明記
- 技術選択: Python 3.12 + pytest (確定・既存環境で実行可能)
- 実装可能性: 既存ヘルパ (GRID / PHASE_* / FakeBackend) の再利用で確実に実装可能
- 信頼性レベル: 🔴 0 件。🟡 は全て文書化済み設計 (D3/D6・§3.6) からの導出で、要件定義書 (🔵4/🟡3・高品質) と整合

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m1-hypothesis-search TASK-0007` でRedフェーズ（失敗テスト作成）を開始します。
