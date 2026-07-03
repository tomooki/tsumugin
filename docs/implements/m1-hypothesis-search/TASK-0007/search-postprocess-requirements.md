# TASK-0007 探索後処理 — TDD 要件定義書

- **機能名**: 探索後処理 (Jenks 良好解抽出 / 最終フル精密化・再ランク / 未マッチ集約・未知相フラグ / warnings / to_summary)
- **タスクID**: TASK-0007
- **要件名**: m1-hypothesis-search
- **実装ファイル**: `src/tsumugin/search/tree.py` (拡張 — TASK-0006 の後処理スタブを実体化)
- **テストファイル**: `tests/test_tree_search.py` (追加ケース。既存 20 ケースと共存)
- **公開 API**: `src/tsumugin/search/__init__.py` は re-export 済み (**追加変更不要**)
- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 3 探索エンジン
- **信頼性サマリー**: 🔵 4 / 🟡 3 / 🔴 なし — 品質評価: 高品質

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: TASK-0006 の探索コア (`_explore → _rank`) の**後段**として、`SearchResult` の
  後処理フィールドを実体化する。具体的には (1) Jenks natural breaks による良好解クラスタ抽出
  (`good_cluster_ids`)、(2) 良好解上位への `StagedRefinementEngine` フル精密化と metrics 更新・再ランキング
  (`final_reports` / `ranked`)、(3) 最良仮説を基準とした未マッチ観測ピーク集約と未知相フラグ判定
  (`unmatched`)、(4) 縮退時の警告蓄積 (`warnings`)、(5) `/api/result` スキーマ準拠の純 dict 化
  (`to_summary()`) を行う。(REQ-005/104/106, FR-116/117, 設計 D3/D6)
- 🔵 **解決する問題**: 探索で得た多数の仮説から「実務的に良好な少数解」を統計的に切り出し (Jenks)、
  それらだけを重点的に精密化して評価精度を上げ (D3)、観測パターンのうち候補相で説明できない部分を
  可視化 (未マッチピーク・未知相フラグ) することで、解析者が「未知相の混入」や「要確認ケース」を
  見落とさないようにする。結果は JSON 化して Web UI へそのまま配信できる形に整える。
- 🔵 **想定ユーザー**: 粉末 XRD 解析を行う研究者・解析パイプライン。直接の呼び出し元は
  `HypothesisTreeSearch.search()` を叩く上位モジュール、および `to_summary()` の出力を配信する
  後続 TASK-0009 (Web UI) / TASK-0010 (公開 API 統合)。
- 🔵 **システム内での位置づけ**: M0 資産 (`StagedRefinementEngine` / `evidence.ranking.rank` /
  `Ledger` + `SnapshotStore`) と Phase 2 部品 (`jenks_breaks` / `unmatched_peaks` / `find_peaks` /
  `match_score`) の上に立つ**純オーケストレーション層**。TASK-0006 の探索結果に対する後処理であり、
  新規モジュールは作らず `tree.py` を拡張する。
- **本タスクのスコープ境界**: `SearchResult` の完成 (`good_cluster_ids` / `unmatched` /
  `final_reports` / `warnings` / `to_summary()` の実体化) まで。`_empty_result` (候補ゼロ経路) との
  整合維持も含む。**スコープ外**: `.gpx` 書き出し (TASK-0008)、Web UI / FastAPI 本体 (TASK-0009)、
  公開 API 統合・E2E (TASK-0010)。
- **参照したEARS要件**: REQ-005, REQ-104, REQ-106, EDGE-002, EDGE-003, EDGE-001(整合)
- **参照した設計文書**: `architecture.md` D3 (L100-106) / D6 (L124-131)、`interfaces.py` (SearchResult L160-176)、
  `api-endpoints.md` (`/api/result` L24-52)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 入力（後処理層が受け取る文脈）

- 🔵 **ranked 仮説列** (`tuple[RankedHypothesis, ...]`): TASK-0006 の `_rank` 出力。各 `RankedHypothesis`
  は `hypothesis` / `evidence: EvidenceResult(backend, value)` / `probability` / `close_competitor` を持つ。
  Jenks 良好解抽出はこの列の **evidence(BIC) 値** を入力とする。
- 🔵 **hypotheses** (`Mapping[str, Hypothesis]`): 全評価ノード。フル精密化で該当ノードを**新インスタンス
  へ差し替え**て metrics を更新する対象。
- 🔵 **観測データ** (`two_theta: np.ndarray`, `intensity: np.ndarray`, `weights: np.ndarray | None`):
  フル精密化 (`StagedRefinementEngine.run`) と未マッチ算出 (`simulate → find_peaks → match_score`) に使用。
- 🔵 **設定** (`SearchConfig`): `final_full_refine`(既定 True) / `max_final_refine`(既定 3) /
  `high_r_threshold`(既定 30.0) / `close_threshold`(既定 10.0) / `match_tol_deg`(既定 0.15) /
  `min_peak_height_frac`(既定 0.05) を参照。
- 🔵 **単一 `ledger: Ledger` / `snapshots: SnapshotStore`**: search() が保持するインスタンスを共有し、
  後処理の全操作を理由付き追記する (監査チェーン一貫性)。

### 2.2 出力（`SearchResult` 完成形 — interfaces.py L160-176）

- 🔵 `good_cluster_ids: tuple[str, ...]` — Jenks 低 evidence 群 (良好解) の**仮説 ID タプル** (index でなく ID)。
- 🔵 `ranked: tuple[RankedHypothesis, ...]` — フル精密化後に**再ランクした** refined 仮説列 (良い順)。
- 🔵 `hypotheses: Mapping[str, Hypothesis]` — フル精密化で metrics 更新済みノードを含む全ノード。
- 🔵 `unmatched: UnmatchedPeakReport(unmatched_observed: tuple[Peak,...], extra_calculated: tuple[float,...],
  unknown_phase_flag: bool)` — 最良仮説基準の未マッチ集約。
- 🟡 `final_reports: Mapping[str, RefinementReport]` — フル精密化した仮説 ID → `RefinementReport`
  (`final_phases`, `metrics`, `stage_outcomes`, `escalated`, `free_params`)。無効時は `{}`。
- 🟡 `warnings: tuple[str, ...]` — EDGE-003 等の縮退警告文字列 (既定 `()`)。
- 🟡 `to_summary() -> dict` — `/api/result` スキーマ準拠の JSON 化可能な純 dict (下記 §3.6 / §4.4)。

### 2.3 入出力の関係性・データフロー（dataflow / D3 / note §4.5）

🔵 `... _explore → _rank`(TASK-0006 完了)`→ 【本タスク】good_cluster 抽出 (jenks_breaks) →`
`フル精密化 (staged, 上位 max_final_refine 件) → 再ランク (rank 再実行) → unmatched 集約 (最良仮説) →`
`warnings 判定 → SearchResult 完成 → to_summary()`。全ステップは共有 `ledger` へ理由付き追記。

- **参照したREQ**: REQ-005 (`UnmatchedPeakReport` 出力), REQ-104 (Jenks 良好解), REQ-106 (未知相フラグ)
- **参照した設計文書**: `interfaces.py` SearchResult / UnmatchedPeakReport / RefinementReport、
  `architecture.md` D3、`api-endpoints.md` `/api/result`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

### 3.1 決定論 / 再現性 (NFR-102 / REQ-403 / TC-001-05) 🔵

- 乱数不使用。**全ソートはキー明示、同点は ID 昇順** (evidence 昇順 → 同点は仮説 ID 昇順) で固定。
- フル精密化対象の選出順・再ランク・summary の ranked 列すべてで一意規則を用い、**入力順非依存**。
- 2 回実行で `to_summary()` までビット同一 (`==` 比較で確認)。

### 3.2 非破壊性 (P2 / NFR-101 相当 / REQ-402 / TC-008-03) 🔵

- `SearchResult` / エンジンに**削除・上書き API を追加しない**。フル精密化の metrics 反映は
  `dataclasses.replace` による**新インスタンス生成**で行う (元 `Hypothesis` は破壊しない)。
  例: `replace(hyp, phases=report.final_phases, metrics=replace(report.metrics, evidence={ev.backend: ev.value}))`。
- ledger は**追記のみ**。`StagedRefinementEngine` の revert は Snapshot 経由 (既存の非破壊機構)。
- 探索とフル精密化を**単一 ledger / snapshots** で共有し `verify()` = True を維持 (TC-008-01)。

### 3.3 失敗の非例外化 (M0 規約 / EDGE-002/003/004) 🔵

- フラット (観測ピーク 0)・全高 R・候補ゼロ・Jenks 境界不能は**例外化せず縮退**へ倒す
  (空良好解 + 警告 / フラグ設定)。EDGE-003 (フラット) と EDGE-002 (全高 R) を取り違えない (§4)。

### 3.4 API / スキーマ制約 (D6 / api-endpoints.md) 🟡

- `to_summary()` の値は**すべて素の型** (str/int/float/bool/None/list/dict)。numpy スカラー・dataclass を
  露出しない → `json.dumps(result.to_summary())` が成功すること (TC-007-01/04)。
- キー集合は `/api/result` スキーマと完全一致 (§4.4)。候補ゼロでも同スキーマの空 summary が成立。

### 3.5 コーディング / 品質制約 (CLAUDE.md) 🔵

- Python >= 3.12 / コア依存 numpy のみ (scipy / GSAS-II 非依存、本タスクは `SimulatedBackend` で完結)。
- 型注釈必須 (`any` 回避)、キーワード専用引数は `*` 区切り、snake_case / PascalCase / UPPER_SNAKE。
- docstring は日本語可、FR/REQ 番号 + 🔵🟡 信頼性レベルを紐づける。
- Lint: `uvx ruff check src tests` (line-length 100, target py312)。TDD 厳守・**本セッションで git commit しない**。

### 3.6 アルゴリズム契約 🔵/🟡

- 🔵 **Jenks 良好解**: `jenks_breaks(values, *, n_classes=2)` は境界タプルを昇順で返し、**要素 0/1・全同値は
  `()`** へ縮退。良好解は「evidence 値 <= `breaks[0]`」で判定 (低いほど良い)。境界不能時のフォールバック
  (単一仮説はそのまま良好解 / 全同値は全て良好解 / 空は空) を**実装時に確定しテストで固定**する。
- 🟡 **フル精密化 (D3)**: 良好解のうち **evidence(BIC) 昇順の上位 `max_final_refine` 件** に
  `StagedRefinementEngine(backend, store=snapshots, ledger=ledger).run(...)` を適用。BIC を再計算して
  `rank()` を再実行し `ranked` を確定。`final_full_refine=False` で無効 (`final_reports={}`・metrics 不変)。
- 🔵 **未知相フラグ (REQ-106 / EDGE-002)**: `unknown_phase_flag = (最良仮説で説明できない未マッチ観測が非空)
  or (全 refined 仮説 Rwp > high_r_threshold)`。`high_r_flag = all(h.metrics.rwp > high_r_threshold)` を
  `unmatched_peaks(..., high_r_flag=high_r_flag)` に渡す。

- **参照したNFR/REQ**: NFR-102, REQ-402, REQ-403, REQ-104, REQ-106, EDGE-002/003/004
- **参照した設計文書**: `architecture.md` D3 / 非機能要件 (再現性/セキュリティ)、`api-endpoints.md`、`CLAUDE.md`

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本パターン（REQ-104/005） 🔵

- 真の相 (A/B) を含む合成データで探索 → 良好解が Jenks で分離され `good_cluster_ids` に該当 ID が入る
  (TC-004-03 統合)。`final_full_refine=True` で良好解上位の metrics が更新され `final_reports` に記録。

### 4.2 未マッチあり（TC-005-01 / REQ-005） 🔵

- 真の構成に「候補にない相」を混ぜたデータ → 未マッチ観測ピークが**位置・強度付き** (`Peak(position, height)`)
  で `unmatched.unmatched_observed` に報告され、`unknown_phase_flag=True`。

### 4.3 完全説明（TC-005-02） 🔵

- 候補相で完全に説明できるデータ → `unmatched.unmatched_observed` 空・`extra_calculated` 空・
  `unknown_phase_flag=False`。

### 4.4 to_summary スキーマ（D6 / api-endpoints.md `/api/result`） 🟡

`json.dumps(result.to_summary())` が成功し、以下のキーを持つ：
```
ranked[i] = {
  "id", "rank"(=i+1), "probability", "close_competitor",
  "rwp"(=metrics.rwp), "gof"(=metrics.gof),
  "evidence": {"backend", "value"},
  "phases": [{"phase_ref", "wt_frac", "lattice": {"a","b","c"}}, ...],
  "parent_id", "in_good_cluster"(= id in good_cluster_ids),
}
unknown_phase_flag = unmatched.unknown_phase_flag
unmatched_observed = [{"position", "height"}, ...]
extra_calculated   = list(unmatched.extra_calculated)
warnings           = list(warnings)
n_hypotheses       = len(hypotheses)
```

### 4.5 エッジ / エラーケース

- 🟡 **EDGE-003 フラットパターン (TC-005-03)**: 観測ピーク 0 → 例外なし・空良好解・`warnings` 非空・
  **`unknown_phase_flag` は False** (説明対象が無い)。
- 🔵 **EDGE-002 全仮説高 R (TC-E02)**: 全 refined 仮説の Rwp > `high_r_threshold` → `unknown_phase_flag=True` +
  最良仮説を「要確認」として返す (例外なし)。EDGE-003 と混同しない。
- 🔵 **EDGE-001 候補ゼロ (整合維持)**: `_empty_result` も `good_cluster_ids=()` / `unmatched=_EMPTY_UNMATCHED` /
  `final_reports={}` / `warnings=(...)` を返し、`to_summary()` が空スキーマ (ranked=[], n_hypotheses=0) で成立
  (TC-E01 を壊さない)。
- 🟡 **Jenks 境界不能**: 仮説 0/1 件・全 evidence 同値 → `jenks_breaks` が `()` を返す → §3.6 のフォールバックに従う。
- 🔵 **決定論退行防止 (TC-001-05)**: 再ランク・追記後も 2 回実行で `to_summary()` までビット同一。

- **参照したEDGE**: EDGE-001, EDGE-002, EDGE-003, EDGE-004(整合), EDGE-101/102(整合)
- **参照した設計文書**: `dataflow.md` (後処理フロー)、`architecture.md` D3、`api-endpoints.md`

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 「未知相を含む混合試料の解析者が、良好解と未説明ピークを一望する」
  (user-stories.md / M1 概要)
- **参照した機能要件**: REQ-005 (UnmatchedPeakReport 出力), REQ-104 (Jenks 良好解抽出),
  REQ-106 (全仮説高 R → 未知相フラグ強制), REQ-201/402 (整合), FR-116/117
- **参照した非機能要件**: NFR-102 / REQ-403 (再現性・ビット同一), REQ-402 (追記 ledger・非破壊)
- **参照した Edge ケース**: EDGE-001 (候補ゼロ整合), EDGE-002 (全高 R → フラグ + 要確認),
  EDGE-003 (フラット → 警告・フラグなし), EDGE-004 (発散降格・整合)
- **参照した受け入れ基準** (acceptance-criteria.md):
  - TC-004-03 🔵 — Jenks が良好クラスタを分離し `good_cluster_ids` に入る (統合確認)
  - TC-005-01 🔵 — 候補にない相を含むデータ → 未マッチピーク (位置・強度) 報告 + `unknown_phase_flag=True`
  - TC-005-02 🔵 — 完全説明データ → 未マッチ空・`unknown_phase_flag=False`
  - TC-005-03 🟡 (EDGE-003) — フラット → 例外なし・空良好解・`warnings` 非空・フラグなし
  - TC-E02 🔵 (EDGE-002) — 全仮説高 R → `unknown_phase_flag=True` + 最良仮説を要確認として返す
  - フル精密化 (D3) 🟡 — `final_full_refine=True` で良好解上位の metrics 更新・`final_reports` 記録 /
    `=False` で無効・不変
  - to_summary スキーマ 🟡 — `/api/result` の全キーを持ち `json.dumps()` 成功
  - 回帰 — TASK-0006 の全 20 ケース (TC-001-05 決定論 / TC-008-01 verify / TC-008-03 非破壊) が green 維持
- **参照した設計文書**:
  - **アーキテクチャ**: `architecture.md` D3 (最終検証精密化 L100-106), D6 (Web UI / to_summary L124-131)
  - **データフロー**: `dataflow.md` (探索後の good_cluster → 精密化 → 再ランク → unmatched → summary フロー)
  - **型定義**: `interfaces.py` SearchResult (L160-176) / SearchConfig (L143-157) / jenks_breaks (L133) /
    UnmatchedPeakReport / RefinementReport
  - **データベース**: なし (M1 は永続 DB 非導入)
  - **API 仕様**: `api-endpoints.md` `/api/result` (L24-52 — to_summary の契約)
- **拡張対象 / 前提実装**: `src/tsumugin/search/tree.py` (TASK-0006 完成・後処理スタブ L88-110),
  `src/tsumugin/search/clustering.py` (`jenks_breaks`), `src/tsumugin/search/matcher.py`
  (`unmatched_peaks` / `UnmatchedPeakReport` / `match_score`), `src/tsumugin/search/peaks.py`
  (`find_peaks` / `Peak`), `src/tsumugin/refinement/staged.py` (`StagedRefinementEngine` / `RefinementReport`),
  `src/tsumugin/evidence/{base,ic,ranking}.py`

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (Jenks 境界不能フォールバック・未マッチ算出方式のみ「TDD で確定」と明示)
- 入出力定義: 完全 (SearchResult 全フィールド + to_summary スキーマを型付きで規定)
- 制約条件: 明確 (決定論 / 非破壊 / 非例外化 / JSON 化 / lint を条番号付きで規定)
- 実装可能性: 確実 (拡張点・依存部品・M0 資産の呼び出し契約が特定済み)
- 信頼性レベル: 🔵 4 / 🟡 3 / 🔴 0 — 🔵 優勢
```

- **要改善点 (実装時に TDD で確定すべき事項)**:
  1. 🟡 Jenks 境界不能時 (仮説 0/1・全同値) のフォールバック規則 (推奨: 単一はそのまま良好解 / 全同値は全良好解 / 空は空)
  2. 🟡 最良仮説の未マッチ算出方式 (探索時の per-candidate MatchResult 再利用 vs 最良仮説の相を `simulate→find_peaks→match_score` で再計算) — 決定論を保つ方を選択
  3. 🟡 フル精密化後 metrics 反映の replace 経路 (Hypothesis frozen 前提の新インスタンス差し替え書式)

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m1-hypothesis-search TASK-0007` でテストケースの洗い出しを行います。
