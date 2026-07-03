# TASK-0007 探索後処理 (Jenks 良好解 / 最終フル精密化 / 未知相フラグ / to_summary) — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク要約
`src/tsumugin/search/tree.py` を**拡張**し、TASK-0006 でスタブ (空値/骨格) だった `SearchResult` の
後処理フィールドを実体化する (FR-116/117, REQ-005/104/106, EDGE-002/003, 設計 D3):

1. **Jenks 良好解** (`good_cluster_ids`): `jenks_breaks` で ranked 仮説の evidence(BIC) 値を 2 群へ分割し、
   低 evidence 群 (良好解) の**仮説 ID タプル**を格納する 🔵 *TC-004-03 統合*
2. **最終フル精密化** (`final_reports` + metrics 更新 + 再ランキング, D3): 良好解上位 `max_final_refine` 件 (既定 3) に
   `StagedRefinementEngine` (M0, `refinement/staged.py`) のフルテンプレートを適用し、`metrics` を更新して再ランクする。
   `config.final_full_refine=False` で無効化 🟡 *D3*
3. **未マッチ相 / 未知相フラグ** (`unmatched`): 最良仮説の相を観測とマッチングして `unmatched_peaks()` で
   `UnmatchedPeakReport` を構築。`unknown_phase_flag` = 未マッチ観測非空 **or** 全仮説 Rwp > `high_r_threshold` (既定 30.0) 🔵 *TC-005-01/E02*
4. **警告** (`warnings`): フラットパターン等の縮退で例外なく警告文字列を積む (EDGE-003) 🟡 *TC-005-03*
5. **`to_summary()`**: `api-endpoints.md` の `/api/result` スキーマに一致する JSON 化可能な純 dict を返す 🟡

- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 3 探索エンジン
- **主要実装**: `src/tsumugin/search/tree.py` (拡張) + `src/tsumugin/search/__init__.py` は re-export 済み (追加不要)
- **テスト**: `tests/test_tree_search.py` に**追加ケース** (TC-005-01/02/03, TC-E02, TC-004-03 統合, to_summary スキーマ, フル精密化)
- **依存**: 前提 TASK-0006 (探索コア完成) / 後続 TASK-0009 (Web UI が to_summary を配信), TASK-0010 (公開 API 統合)
- **信頼性**: 🔵 4 / 🟡 3 (完了条件 7 件、いずれも acceptance-criteria の TC へ遡及)
- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0007.md`, `docs/tasks/m1-hypothesis-search/overview.md`

---

## 1. 技術スタック
- **言語**: Python >= 3.12 (CPython)。コア依存は **numpy >= 1.26 のみ** (scipy / GSAS-II 非依存 — 本タスクは `SimulatedBackend` で完結)
- **パッケージマネージャー**: uv 0.9.x (src layout + hatchling)。テスト実行 `uv run pytest`
- **アーキテクチャ**: 木探索は M0 資産 (`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore` /
  **`StagedRefinementEngine`**) の上の**純オーケストレーション層**。本タスクは探索コア (TASK-0006) の後段に
  「良好解抽出 → フル精密化 → 再ランク → 未マッチ集約 → summary 化」を追加する
- **参照元**: `pyproject.toml`, `CLAUDE.md`, `docs/spec/m1-hypothesis-search/note.md` (§技術スタック), `docs/design/m1-hypothesis-search/architecture.md`

## 2. 開発ルール
- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしのコミット禁止。**git commit は本セッションでは行わない**
- **決定論 (NFR-102 / REQ-403 / TC-001-05)**: 乱数不使用。**全ソートはキー明示、同点は ID/index 昇順**で固定。
  再ランク後も 2 回実行でビット同一 (`==` 比較)。良好解抽出・フル精密化対象の選出順も入力順非依存の一意規則にする
- **非破壊性 (P2 / NFR-101 / TC-008-03)**: `SearchResult` / エンジンに**削除・上書き API を追加しない**。フル精密化での
  metrics 更新は `dataclasses.replace` / `Hypothesis.with_updates` 相当の**新インスタンス生成**で行い、ledger は追記のみ。
  `StagedRefinementEngine` の revert は Snapshot 経由 (既存の非破壊機構)
- **失敗の非例外化 (M0 規約 / EDGE-003/004)**: フラット・全高 R・候補ゼロは例外化せず縮退 (空良好解 + 警告 / フラグ) へ倒す
- **命名/型**: snake_case / PascalCase / UPPER_SNAKE。型注釈必須 (`any` 回避)。キーワード専用引数は `*` 区切り
- **docstring**: 日本語可。FR/REQ 番号と 🔵🟡 信頼性レベルを紐づける (`search/` 配下・`tree.py` 既存の慣習を踏襲)
- **Lint**: `uvx ruff check src tests` (line-length 100, target py312)
- **参照元**: `CLAUDE.md` (実装上の不変条件/規約), `docs/spec/m1-hypothesis-search/note.md` (§開発ルール), `docs/tasks/m1-hypothesis-search/TASK-0007.md`

## 3. 関連実装

### 3.1 拡張対象と直接呼ぶ Phase 2 部品 (呼び出しは本タスクで初めて解禁)
- **`src/tsumugin/search/tree.py`** (拡張対象): TASK-0006 で `SearchConfig` / `HypothesisTreeSearch` / `_explore` / `_rank` 等は完成。
  `search()` L249-259 の `SearchResult(...)` 構築で `good_cluster_ids=()` / `unmatched=_EMPTY_UNMATCHED` / `final_reports={}` /
  `warnings=()` を**実体へ差し替え**、`to_summary()` L104-110 のスタブを**本実装へ置換**する。`_empty_result` (候補ゼロ) も整合維持
- **`src/tsumugin/search/clustering.py::jenks_breaks`**: `jenks_breaks(values, *, n_classes=2) -> tuple[float, ...]` —
  1 次元 Jenks natural breaks の**境界値**を昇順で返す (DP, numpy)。**空/単一/過大群数は空タプル `()` へ縮退** (例外なし)。
  低 evidence 群 (良好解) は「値 <= 境界値」で判定する
- **`src/tsumugin/search/matcher.py`**:
  - `match_score(candidate_peaks, observed_peaks, *, tol_deg=0.15, candidate_index=0) -> MatchResult` — 1:1 貪欲一致。
    `MatchResult(candidate_index, score, matched_observed, unmatched_candidate)`
  - `unmatched_peaks(match_results, observed_peaks, *, high_r_flag=False) -> UnmatchedPeakReport` (**本タスクで初呼び出し**) —
    `matched_observed` の和集合で説明済み観測を除き、残りを `Peak` 実体で位置昇順に復元。`extra_calculated` は
    `unmatched_candidate` を昇順・重複排除で集約。`unknown_phase_flag = 未マッチ観測非空 or high_r_flag`
  - `UnmatchedPeakReport(unmatched_observed: tuple[Peak,...], extra_calculated: tuple[float,...], unknown_phase_flag: bool)`
- **`src/tsumugin/search/peaks.py`**: `find_peaks(two_theta, intensity, *, min_height_frac=0.05) -> tuple[Peak,...]`。
  `Peak(position, height)`。空入力・フラットは `()`。**最良仮説の相を simulate → find_peaks で計算ピーク化**して match するのに再利用

### 3.2 M0 資産 (フル精密化・再ランク・summary に利用)
- **`src/tsumugin/refinement/staged.py::StagedRefinementEngine`** (D3 の中核):
  - `StagedRefinementEngine(backend, store: SnapshotStore, ledger: Ledger, *, template=DEFAULT_STAGE_TEMPLATE, config=GuardConfig(), max_retries=3)`
  - `.run(phases: tuple[PhaseInstance,...], two_theta, intensity, *, weights=None) -> RefinementReport`
  - `RefinementReport(final_phases, metrics: RefinementMetrics, stage_outcomes, escalated, free_params)` → `SearchResult.final_reports` の**値型**
  - `DEFAULT_STAGE_TEMPLATE`: scale_bg → lattice_zero → profile → texture → occupancy → coordinates → adp。
    **SimulatedBackend は scale/lattice のみ認識、profile 以降は no-op で通過**。`_gof(result)=sqrt(chi2/max(n_obs-n_params,1))`
  - 探索の**同一 `ledger` / `snapshots`** を渡して全遷移を追記記録する (非破壊・監査一貫性)
- **`src/tsumugin/evidence/ranking.py::rank(hypotheses, backend, *, temperature=1.0, close_threshold=10.0) -> tuple[RankedHypothesis,...]`**:
  evidence 昇順 + softmax(-value/2T) + close_competitor。**`metrics=None` は ValueError** → フル精密化後も metrics 必須。
  `RankedHypothesis(hypothesis, evidence: EvidenceResult, probability, close_competitor)`。再ランクはこれを再実行
- **`src/tsumugin/evidence/base.py` / `ic.py`**: `EvidenceResult(backend: str, value: float, logz_err=None)` / `BICBackend` (name="bic")。
  フル精密化で metrics が変われば BIC も変わる → `replace(metrics, evidence={ev.backend: ev.value})` で再計算して再ランク
- **`tree.py::_FiniteGuardedEvidence`** (既存): 全仮説 evidence 非有限時の softmax NaN 縮退ガード。再ランクでも流用

### 3.3 参考パターン
- **`tree.py::_rank` / `_evaluate_node`** (既存, TASK-0006): `rank(...)` 呼び出し・`ledger.append("ranking", {...})`・
  `replace(base_metrics, evidence={ev.backend: ev.value})` の書式の範。フル精密化後の再ランクはこれを再利用/踏襲する
- **`src/tsumugin/pipeline.py::analyze_single_pattern`**: `StagedRefinementEngine.run` → evidence → rank の M0 統合フロー (D3 の範)
- **参照元**: `src/tsumugin/search/{tree,clustering,matcher,peaks}.py`, `src/tsumugin/refinement/staged.py`,
  `src/tsumugin/evidence/{base,ic,ranking}.py`, `src/tsumugin/model/{hypothesis,phase}.py`, `src/tsumugin/pipeline.py`

## 4. 設計文書 (契約)

### 4.1 SearchResult 完成形 (interfaces.py L160-176)
```python
@dataclass(frozen=True)
class SearchResult:
    ranked: tuple[RankedHypothesis, ...]            # refined のみ、良い順 (再ランク後) 🔵
    hypotheses: Mapping[str, Hypothesis]            # 全評価ノード (フル精密化で metrics 更新済み含む) 🔵
    good_cluster_ids: tuple[str, ...]               # ← Jenks 良好クラスタの仮説 ID 🔵 FR-116
    alternatives: Mapping[int, tuple[int, ...]]     # 代表候補idx -> 代替候補idx (TASK-0006 済) 🔵
    unmatched: UnmatchedPeakReport                  # ← 最良仮説基準の未マッチ集約 🔵 FR-117
    final_reports: Mapping[str, RefinementReport]   # ← フル精密化した仮説 ID -> RefinementReport 🟡 D3
    ledger: Ledger; snapshots: SnapshotStore        # 実体 (TASK-0006 済) 🔵
    warnings: tuple[str, ...] = ()                  # ← EDGE-003 等の警告 🟡
    def to_summary(self) -> dict: ...               # ← /api/result スキーマ準拠 🟡 D6
```

### 4.2 D3 最終検証精密化 (architecture.md L100-106, 🟡)
- Jenks 良好クラスタの仮説 (**上位 `max_final_refine` 件, 既定 3**) にのみ `StagedRefinementEngine` のフルテンプレートを適用し、
  metrics を更新して**再ランキング**する。`config.final_full_refine=False` で無効化可能 (その場合 `final_reports={}`・metrics 不変)
- 「上位」= 良好解のうち evidence(BIC) 昇順 (良い順)。フル精密化後に BIC を再計算し `rank()` を再実行して `ranked` を確定する

### 4.3 未知相フラグの条件 (REQ-106 / EDGE-002 / FR-117)
- `unknown_phase_flag = (最良仮説で説明できない未マッチ観測が非空) or (全仮説 Rwp > high_r_threshold)`
- `high_r_flag` (= 全仮説高 R) は `all(h.metrics.rwp > config.high_r_threshold for h in ...)` を `unmatched_peaks(high_r_flag=...)` へ渡す
- EDGE-002/TC-E02: 全仮説高 R → フラグ True + 最良仮説を「要確認」として返す (例外なし)

### 4.4 to_summary() スキーマ (api-endpoints.md `/api/result`, D6)
`SearchResult` → 純 dict のフィールド対応:
```
ranked[i] = {
  "id": rk.hypothesis.id, "rank": i+1, "probability": rk.probability,
  "close_competitor": rk.close_competitor,
  "rwp": rk.hypothesis.metrics.rwp, "gof": rk.hypothesis.metrics.gof,
  "evidence": {"backend": rk.evidence.backend, "value": rk.evidence.value},
  "phases": [{"phase_ref": p.phase_ref, "wt_frac": p.wt_frac,
              "lattice": {"a": p.lattice.a, "b": p.lattice.b, "c": p.lattice.c}} for p in rk.hypothesis.phases],
  "parent_id": rk.hypothesis.parent_id,
  "in_good_cluster": rk.hypothesis.id in good_cluster_ids,
}
unknown_phase_flag = unmatched.unknown_phase_flag
unmatched_observed = [{"position": pk.position, "height": pk.height} for pk in unmatched.unmatched_observed]
extra_calculated   = list(unmatched.extra_calculated)
warnings           = list(warnings)
n_hypotheses       = len(hypotheses)
```
- 値はすべて素の型 (str/int/float/bool/None/list/dict) — numpy スカラー・dataclass を露出しない (JSON 化可能・TC-007-01/04)
- 候補ゼロ (`_empty_result`) でも同スキーマの空 summary を返せること (ranked=[], n_hypotheses=0)

### 4.5 データフロー上の位置
`... _explore → _rank`(TASK-0006 完了)`→ 【本タスク】good_cluster 抽出 (jenks) → フル精密化 (staged, 上位 max_final_refine) →`
`再ランク → unmatched 集約 (最良仮説) → warnings 判定 → SearchResult 完成`。全操作は既存 `ledger` へ理由付き追記
- **参照元**: `docs/design/m1-hypothesis-search/interfaces.py` (L143-176), `architecture.md` (D3 L100-106, D6 L124-131),
  `docs/design/m1-hypothesis-search/api-endpoints.md` (`/api/result` L24-52), `docs/design/m1-hypothesis-search/dataflow.md`

## 5. テスト関連情報
- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。現状全 green (M0 70 + M1 探索)
- **テストコマンド**: `uv run pytest tests/test_tree_search.py` / `uv run pytest --cov=tsumugin`
- **配置/命名**: `tests/test_tree_search.py` に**追加**。TASK-0006 の 20 ケース (TC-N/E/B) と共存 (import は既に成功する状態なので
  新ケースは個別に fail させる Red から始める)
- **既存の共通データ/ヘルパ (再利用)**: `GRID = np.arange(15.0, 60.0, 0.02)`、`_phase(a, ref, scale=1.0)` (立方格子)、
  `PHASE_A(a=5)/B(6)/C(4.5)/D(7)/A_PRIME(5.001)/G(6.5)`、`_refs(hyp)`, `_node_with_refs(result, refs)`。
  真の相は A/B、無関係相は C/D (score≈0 に較正済み)。`SimulatedBackend.simulate(phases, tt)` で合成データ生成
- **backend**: 原則 `SimulatedBackend` (GSAS-II 非依存)。Rwp/chi2 を厳密制御する境界・全高 R (TC-E02) は
  既存の `FakeBackend` (RefinementBackend Protocol スタブ) パターン、精密化呼び出し観測は `RecordingSpyBackend` を流用
- **本タスクで追加すべき受け入れ基準** (`acceptance-criteria.md`):
  - **TC-004-03** 🔵: Jenks natural breaks が良好クラスタ (低 evidence 群) を分離し `good_cluster_ids` に入る (統合確認)
  - **TC-005-01** 🔵: 真の構成に「候補にない相」を混ぜたデータ → 未マッチ観測ピークが**位置・強度付き**で報告、`unknown_phase_flag=True`
  - **TC-005-02** 🔵: 完全に説明できるデータ → 未マッチ空・`unknown_phase_flag=False`
  - **TC-005-03** 🟡 (EDGE-003): フラットパターン → 例外なし・空良好解・`warnings` 非空 (未知相フラグは立てない)
  - **TC-E02** 🔵 (EDGE-002): 全仮説高 R (Rwp > high_r_threshold) → `unknown_phase_flag=True` + 最良仮説を要確認として返す
  - **フル精密化 (D3)**: `final_full_refine=True` で良好解上位の `metrics` が更新され `final_reports` に記録 / `=False` で無効・不変 🟡
  - **to_summary スキーマ** 🟡: 返り値が `/api/result` の全キー (ranked[].id/rank/probability/close_competitor/rwp/gof/evidence/
    phases/parent_id/in_good_cluster, unknown_phase_flag, unmatched_observed, extra_calculated, warnings, n_hypotheses) を持ち、
    `json.dumps(result.to_summary())` が成功する (JSON 化可能)
- **回帰**: TASK-0006 の全 20 ケース (特に決定論 TC-001-05 / ledger.verify TC-008-01 / 非破壊 TC-008-03) が
  引き続き green であること (再ランク・追記で崩さない)
- **書式の範**: `tests/test_tree_search.py` 冒頭 docstring / `tests/test_clustering.py` — 【テスト目的/内容/期待/信頼性レベル】コメント、
  `pytest.approx` (物理量近似) と `==` (決定論ビット同一) の使い分け
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_tree_search.py`, `tests/test_clustering.py`,
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-004-03 L53, TC-005 L58-61, TC-E02 L86)

## 6. 注意事項
- **jenks_breaks の入力と縮退**: 良好解判定は ranked 仮説の **evidence(BIC) 値** (低いほど良い) に対して行う。
  `jenks_breaks` は境界タプルを返し、**要素 0/1・全同値では `()` を返す** (境界不能)。この縮退時のフォールバック
  (例: 全仮説を良好解にする / 単一仮説はそのまま良好解 / 空なら空) を**実装時に確定しテストで固定**する。
  低 evidence 群の抽出は「value <= breaks[0]」で行い、`good_cluster_ids` は該当仮説の **ID タプル** (index でなく ID)
- **フル精密化の非破壊反映**: `StagedRefinementEngine.run` は `RefinementReport(final_phases, metrics, ...)` を返す。
  `Hypothesis` は frozen なので `hypotheses` の該当ノードを `replace(hyp, phases=report.final_phases, metrics=replace(report.metrics, evidence={ev.backend: ev.value}))`
  等で**新インスタンスに差し替え**る (元は破壊しない)。BIC を再計算してから再ランク。`final_reports` は `{hyp_id: report}`
- **同一 ledger/snapshots の共有**: フル精密化に渡す `SnapshotStore` / `Ledger` は search() が保持する単一インスタンスにし、
  探索記録とフル精密化記録を 1 本の監査チェーンに保つ (TC-008-01 `verify()`=True を維持)。engine 生成時に `store=snapshots, ledger=ledger`
- **決定論 (再ランク後も TC-001-05)**: フル精密化対象の選出・再ランク・summary の ranked 列すべてで
  ソートキーを明示 (evidence 昇順、同点は ID 昇順)。2 回実行で `to_summary()` までビット同一を確認する
- **最良仮説の未マッチ算出**: `unmatched` は**最良仮説 (rank1) の相**を対象に、各相を `simulate → find_peaks` で計算ピーク化し
  `match_score` → その `MatchResult` 群を `unmatched_peaks()` へ集約する (探索時の per-candidate MatchResult を再利用してもよい —
  方式を TDD で確定)。`high_r_flag` は全 refined 仮説の Rwp > `high_r_threshold` で判定
- **EDGE-003 フラット vs EDGE-002 全高 R の区別**: フラット (観測ピーク 0) は `warnings` を積み **unknown_phase_flag は False**
  (説明対象が無い)。全高 R は `unknown_phase_flag=True`。両者を取り違えないこと (TC-005-03 vs TC-E02)
- **候補ゼロ経路との整合**: `_empty_result` も `good_cluster_ids=()` / `unmatched=_EMPTY_UNMATCHED` / `final_reports={}` /
  `warnings=(...)` を返し、`to_summary()` が空スキーマで成立すること (TC-E01 を壊さない)
- **__init__.py**: `search/__init__.py` は既に `SearchConfig` / `SearchResult` / `HypothesisTreeSearch` / `unmatched_peaks` /
  `jenks_breaks` を re-export 済み。**本タスクで追加変更は不要**
- **スコープ外**: `.gpx` 書き出し (TASK-0008)・Web UI/FastAPI 本体 (TASK-0009)・公開 API 統合と E2E (TASK-0010)
- **参照元**: `docs/spec/m1-hypothesis-search/note.md` (§技術的制約/§注意事項), `docs/spec/m1-hypothesis-search/requirements.md`
  (REQ-104/106, EDGE-002/003), `docs/design/m1-hypothesis-search/architecture.md` (D3/D6), `src/tsumugin/search/tree.py` (拡張点), `CLAUDE.md`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m1-hypothesis-search/TASK-0007.md`, `docs/tasks/m1-hypothesis-search/overview.md`
- 仕様: `docs/spec/m1-hypothesis-search/note.md`, `docs/spec/m1-hypothesis-search/requirements.md` (REQ-104/106, EDGE-002/003),
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-005 系 / TC-E02 / TC-004-03)
- 設計: `docs/design/m1-hypothesis-search/interfaces.py` (SearchResult 完成形 L160-176), `docs/design/m1-hypothesis-search/architecture.md` (D3/D6),
  `docs/design/m1-hypothesis-search/api-endpoints.md` (`/api/result` スキーマ = to_summary の契約), `docs/design/m1-hypothesis-search/dataflow.md`
- 拡張対象/前提実装: `src/tsumugin/search/tree.py` (TASK-0006 完成・後処理スタブ), `src/tsumugin/search/clustering.py` (`jenks_breaks`),
  `src/tsumugin/search/matcher.py` (`unmatched_peaks` / `UnmatchedPeakReport`), `src/tsumugin/search/peaks.py`, `src/tsumugin/search/__init__.py`
- M0 資産: `src/tsumugin/refinement/staged.py` (`StagedRefinementEngine` / `RefinementReport`), `src/tsumugin/evidence/{base,ic,ranking}.py`,
  `src/tsumugin/model/{hypothesis,phase}.py`, `src/tsumugin/store/{ledger,snapshot}.py`, `src/tsumugin/pipeline.py`
- テスト範/設定: `tests/test_tree_search.py` (既存 20 ケース + 追加), `tests/test_clustering.py`, `tests/conftest.py`, `pyproject.toml`
- 前タスクノート (書式の範): `docs/implements/m1-hypothesis-search/TASK-0006/note.md`
- (`AGENTS.md`, `docs/rule/` は不在 — 追加ルールは `CLAUDE.md` / `docs/spec/m1-hypothesis-search/note.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
