# TASK-0010 公開 API 統合 + E2E + ドキュメント — TDD テストケース定義書

- **機能名**: 公開 API 統合 + E2E テスト + ドキュメント (M1 総仕上げ統合)
- **タスクID**: TASK-0010 / **要件名**: m1-hypothesis-search
- **テストファイル**: `tests/test_m1_e2e.py` (新規)
- **要件定義**: `docs/implements/m1-hypothesis-search/TASK-0010/public-api-integration-requirements.md`
- **信頼性サマリー (テストケース)**: 🔵 12 / 🟡 1 / 🔴 0 — 品質評価: 高品質

## テストケース一覧 (全 13 件)

| # | ID | 分類 | 概要 | マーカー | 完了条件/TC | 信頼性 |
|---|-----|------|------|----------|-------------|--------|
| 1 | TC-010-01 | 正常系 | M1 公開シンボル 6 件が `from tsumugin import ...` で解決 | なし | ① | 🔵 |
| 2 | TC-010-02 | 正常系 | `tsumugin.__all__` に昇格シンボル包含 + 昇順ソート維持 | なし | ① | 🔵 |
| 3 | TC-010-03 | 正常系 | SimulatedBackend E2E: `ranked[0]` が真の 2 相 {A,B} | なし | ② / TC-001-01 | 🔵 |
| 4 | TC-010-04 | 正常系 | SimulatedBackend E2E: `to_summary()` が JSON 化可 + スキーマ | なし | ② | 🔵 |
| 5 | TC-010-05 | 正常系 | E2E: `ledger.verify()` True + entries 非空 | なし | ④ / TC-008-01 | 🔵 |
| 6 | TC-010-06 | 正常系 | @gsas E2E: GSASIIBackend `search` 完走・ranked 非空 | @gsas | ③ | 🔵 |
| 7 | TC-010-07 | 正常系 | @gsas E2E: `search`→`export_gpx`→再オープンで相数一致 | @gsas | ③ / TC-006-01 | 🔵 |
| 8 | TC-010-08 | 異常系 | 遅延 import 契約: `import tsumugin` が web/gsas 非依存 | なし | (D6) | 🔵 |
| 9 | TC-010-09 | 異常系 | 候補ゼロ E2E: 空 `SearchResult`・例外なし・summary JSON 化 | なし | EDGE-001 | 🔵 |
| 10 | TC-010-10 | 異常系 | 未知相混入 E2E: `unknown_phase_flag=True` + 未マッチ報告 | なし | TC-005-01 | 🔵 |
| 11 | TC-010-11 | 境界値 | 決定論: 2 回実行で `to_summary()` がビット同一 | なし | TC-001-05 / REQ-403 | 🔵 |
| 12 | TC-010-12 | 境界値 | 候補 1 相 E2E: 単一仮説・深さ 1 の木 | なし | EDGE-102 | 🔵 |
| 13 | TC-010-13 | 境界値 | README の M1 使用例コードが実際に動作する | なし | ⑤ | 🟡 |

> **検証内訳**: 正常系 7 / 異常系 3 / 境界値 3。うち `@gsas` 2 件 (GSAS-II 未導入環境は `tests/conftest.py` が自動 skip)。
> **非テスト検証項目 (verify-complete で担保、テストケース化しない)**: カバレッジ 90% 以上 (`uv run pytest --cov=tsumugin`)、
> ruff clean (`uvx ruff check src tests`) = 完了条件④; `docs/dev/context.md` / `reports/verification.md` の内容整合 = 完了条件⑤⑥。

---

## 共通テストデータ・前提 (`tests/test_tree_search.py` の慣習を踏襲)

```python
# 【観測グリッド】: 全候補ピークが収まる 15–60° / step 0.02。step 0.02 は clustering の bin 較正上必須 (変更禁止)。🔵
GRID = np.arange(15.0, 60.0, 0.02)

def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンス (格子定数 a を変えるとピーク位置が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)

PHASE_A = _phase(5.0, "A")   # 真の相 1
PHASE_B = _phase(6.0, "B")   # 真の相 2 (2 相合成は A+B を重ねる)
PHASE_C = _phase(4.5, "C")   # 無関係相 (ピーク位置が合わない)
PHASE_D = _phase(7.0, "D")   # 無関係相
```

- **E2E は実バックエンドを使う** (統合の裏取りが目的): SimulatedBackend (マーカー無し) / GSASIIBackend (`@pytest.mark.gsas`)。
  FakeBackend 等の単体スタブは使わない (要件 §3.5)。
- `@gsas` は `tests/conftest.py::pytest_collection_modifyitems` が未導入環境で自動 skip。本環境は GSAS-II 導入済みで実行される。

---

## 1. 正常系テストケース（基本的な動作）

### TC-010-01: M1 公開シンボルのトップレベル再エクスポート

- **テスト名**: `test_m1_public_symbols_are_reexported`
  - **何をテストするか**: `from tsumugin import HypothesisTreeSearch, SearchConfig, SearchResult, PhaseCandidate, export_gpx, UnmatchedPeakReport` が例外なく解決し、各シンボルが期待の型 (クラス / dataclass / 関数) であること。
  - **期待される動作**: トップレベル `tsumugin` 名前空間から M1 中核シンボルへ到達できる。
- **入力値**: `import tsumugin` および上記の from-import 文 (引数なし)。
  - **入力データの意味**: 完了条件①「`from tsumugin import HypothesisTreeSearch, ...` で M1 API が利用可能」の直接検証。`test_export_gpx_is_reexported` (TASK-0008) と同じ公開面確認パターン。
- **期待される結果**: 全 import が成功。`HypothesisTreeSearch` は class、`SearchConfig`/`SearchResult`/`PhaseCandidate`/`UnmatchedPeakReport` は `dataclasses.is_dataclass` True、`export_gpx` は `callable`。
  - **期待結果の理由**: サブパッケージ側 (`tsumugin.search`/`export`) では re-export 済みだが、トップレベルへの昇格が本タスクの中核作業のため。
- **テストの目的**: 公開 API 統合 (完了条件①) の達成確認。
  - **確認ポイント**: 最小必須 5 シンボル + `UnmatchedPeakReport` (summary 解釈に必要) が昇格されていること。
- 🔵 信頼性: 要件定義 §2.1 / 完了条件① / `tests/test_gpx_export.py::test_export_gpx_is_reexported` に直接依拠

### TC-010-02: `__all__` への追記と昇順ソート維持

- **テスト名**: `test_m1_symbols_in_dunder_all_and_sorted`
  - **何をテストするか**: 昇格した M1 シンボルが `tsumugin.__all__` に含まれ、かつ `__all__` が昇順ソートを維持していること。
  - **期待される動作**: `__all__` が既存 M0 分と M1 分を統合し、アルファベット昇順のまま。
- **入力値**: `tsumugin.__all__` (リスト)。
  - **入力データの意味**: 既存 `__init__.py` の「`__all__` はソート維持」慣習 (M0 の `__all__` は昇順) の遵守確認。
- **期待される結果**: `{"HypothesisTreeSearch", "SearchConfig", "SearchResult", "PhaseCandidate", "export_gpx", "UnmatchedPeakReport"} <= set(tsumugin.__all__)` かつ `list(tsumugin.__all__) == sorted(tsumugin.__all__)`。
  - **期待結果の理由**: 公開面の一貫性・可読性の維持 (要件 §2.1)。
- **テストの目的**: 公開面の配線と規約遵守の確認。
  - **確認ポイント**: 既存 M0 シンボルが 1 つも削除・改名されていない (後方互換維持 / 要件 §3.2)。
- 🔵 信頼性: 要件定義 §2.1 / §3.2 / 既存 `src/tsumugin/__init__.py` の `__all__` 慣習に直接依拠

### TC-010-03: SimulatedBackend E2E — 真の 2 相構成が 1 位

- **テスト名**: `test_e2e_simulated_two_phase_ranks_ab_first`
  - **何をテストするか**: 合成 2 相 (A+B) データ・4 候補に対し `HypothesisTreeSearch(SimulatedBackend()).search(...)` を実行し `ranked[0]` の相集合が {A,B} になること。
  - **期待される動作**: find_peaks → match → cluster → prune → best-first 展開 → BIC → rank のフルパイプラインが公開 API 経由で完走。
- **入力値**: `backend.simulate([PHASE_A, PHASE_B], GRID)` を観測、候補 `[PHASE_A, PHASE_B, PHASE_C, PHASE_D]`。
  - **入力データの意味**: 完了条件②「合成 2 相データの search が真の構成を 1 位にする」の直接再現 (TC-001-01 の E2E 版、公開 API 経由で呼ぶ点が TASK-0006 版と異なる)。
- **期待される結果**: `result.ranked` が非空、`{p.phase_ref for p in result.ranked[0].hypothesis.phases} == {"A", "B"}`。
  - **期待結果の理由**: 真の 2 相構成が BIC ランキングで最上位になるのが正答 (REQ-001)。
- **テストの目的**: E2E 統合 (完了条件②) の中核達成確認。
  - **確認ポイント**: 公開 `from tsumugin import HypothesisTreeSearch` 経由で TASK-0006 と同一結果が得られること。
- 🔵 信頼性: 完了条件② / 受け入れ基準 TC-001-01 / `tests/test_tree_search.py::test_two_phase_truth_ranks_ab_first` に直接依拠

### TC-010-04: SimulatedBackend E2E — summary の JSON 化とスキーマ

- **テスト名**: `test_e2e_summary_is_json_serializable_with_schema`
  - **何をテストするか**: `result.to_summary()` が `json.dumps` 可能な純 dict であり、`/api/result` スキーマの必須キーを持つこと。
  - **期待される動作**: summary が canonical な素の型 (dict/list/str/int/float/bool/None) のみで構成される。
- **入力値**: TC-010-03 と同じ 2 相合成データの `result`。
  - **入力データの意味**: 完了条件②「summary が JSON 化できる」の直接検証。
- **期待される結果**: `json.dumps(result.to_summary())` が例外を投げない。キー集合が `{"ranked", "unknown_phase_flag", "unmatched_observed", "extra_calculated", "warnings", "n_hypotheses"}` を包含。`ranked[0]` が `id/rank/probability/close_competitor/rwp/gof/evidence/phases/parent_id/in_good_cluster` を持つ。
  - **期待結果の理由**: `api-endpoints.md` GET /api/result のスキーマ準拠 (Web UI / 外部連携の契約)。
- **テストの目的**: summary の機械可読性と契約適合の確認。
  - **確認ポイント**: `json.dumps(..., sort_keys=True)` が 2 回とも同一 (決定論。TC-010-11 と連動)。
- 🔵 信頼性: 完了条件② / 要件定義 §2.2 / `docs/design/m1-hypothesis-search/api-endpoints.md` GET /api/result に直接依拠

### TC-010-05: E2E — ledger.verify() が True

- **テスト名**: `test_e2e_ledger_verify_true`
  - **何をテストするか**: 探索実行後の `result.ledger.verify()` が True で、`entries` が非空 (空 ledger の自明 True でない) こと。
  - **期待される動作**: 全操作 (match_score/cluster/prune/node_refine/branch_prune/ranking) が追記専用ハッシュチェーンに理由付きで記録される。
- **入力値**: TC-010-03 と同じ 2 相合成データの `result`。
  - **入力データの意味**: NFR-105/201 (ledger 追記 + ハッシュチェーン、verify 常に True) の E2E 担保。
- **期待される結果**: `result.ledger.verify() is True` かつ `len(result.ledger.entries) > 0`。
  - **期待結果の理由**: 非破壊性・監査可能性 (P2 / REQ-402) を統合レベルで保証。
- **テストの目的**: 非破壊性契約の E2E 確認 (完了条件④の一部 + TC-008-01)。
  - **確認ポイント**: 統合経路 (公開 API 経由) でも ledger 連鎖が無傷であること。
- 🔵 信頼性: 受け入れ基準 TC-008-01 / 要件定義 §3.2 / `tests/test_tree_search.py::test_ledger_verify_true_after_search` に直接依拠

### TC-010-06: @gsas E2E — GSASIIBackend での search 完走

- **テスト名**: `test_e2e_gsasii_search_completes` (`@pytest.mark.gsas`)
  - **何をテストするか**: `HypothesisTreeSearch(GSASIIBackend()).search(...)` が実バックエンドで例外なく完走し、ランキングを返すこと。
  - **期待される動作**: GSAS-II の実精密化を用いた探索が破綻せず `SearchResult` を返す。
- **入力値**: `GSASIIBackend().simulate([PHASE_A, PHASE_B], GRID)` を観測、候補 `[PHASE_A, PHASE_B, PHASE_C, PHASE_D]`。GSAS-II が確実に計算できる立方 (CIF 簡約) 相を使用。
  - **入力データの意味**: 完了条件③「GSASIIBackend での search E2E が完走」の直接検証。
- **期待される結果**: `result.ranked` が非空、`result.ledger.verify() is True`、各 refined 仮説の `metrics.evidence` に "bic" キー。
  - **期待結果の理由**: バックエンド交換 (P7) しても探索パイプラインが同契約で完走することを保証。
- **テストの目的**: 実バックエンド統合 (完了条件③) の完走確認。
  - **確認ポイント**: GSAS-II 特有の失敗 (発散) が chi2=inf 変換され探索全体をクラッシュさせないこと (EDGE-004 相当)。
- 🔵 信頼性: 完了条件③ / `tests/test_gsasii_backend.py` の @gsas パターンに直接依拠。GSAS-II 未導入環境は自動 skip

### TC-010-07: @gsas E2E — search → export_gpx → 再オープン連携

- **テスト名**: `test_e2e_gsasii_search_then_export_gpx_reopenable` (`@pytest.mark.gsas`)
  - **何をテストするか**: GSASIIBackend の search 結果から代表仮説の相を取り出し `export_gpx` で `.gpx` を書き出し、`G2sc.G2Project(<path>)` で再オープンして相数が一致すること。
  - **期待される動作**: 探索 → 書き出し → GSAS-II GUI 互換ファイルの一連連携が公開 API 経由で成立。
- **入力値**: TC-010-06 の `result.ranked[0].hypothesis.phases`、`export_gpx(tmp_path/"m1.gpx", phases, GRID, y)`。`tmp_path` フィクスチャで隔離。
  - **入力データの意味**: 完了条件③・②の「gpx 連携」(note §3.3 の E2E 設計方針: 書き出した .gpx が再オープン可能) の統合検証。
- **期待される結果**: `export_gpx` の戻り値パスが実在し、再オープンした `project.phases()` の長さが書き出した相数と一致 (TC-006-01 と同じ再オープン契約)。
  - **期待結果の理由**: Tsumugin の探索結果を GSAS-II ワークフローへ橋渡しできることの end-to-end 保証。
- **テストの目的**: search と export_gpx の結線検証 (完了条件③)。
  - **確認ポイント**: 探索で得た `PhaseInstance` 群が `export_gpx` の入力契約 (`Sequence[PhaseInstance]`) と整合すること。
- 🔵 信頼性: 完了条件③ / 要件定義 §4.3 / 受け入れ基準 TC-006-01 / `tests/test_gpx_export.py` の再オープン検証に直接依拠。未導入は自動 skip

---

## 2. 異常系テストケース（エラーハンドリング・縮退動作）

### TC-010-08: 遅延 import 契約 — オプション依存非導入でも import 成功

- **テスト名**: `test_import_tsumugin_does_not_require_optional_extras`
  - **エラーケースの概要**: FastAPI (web extra) / GSAS-II (gsas extra) を実際に使う前の `import tsumugin` 段階で、これらの未導入により import が失敗してはならない (D6 遅延 import 契約)。
  - **エラー処理の重要性**: コア (numpy のみ) 利用者が M1 公開シンボルを import しただけで ImportError になると、公開 API 統合が破綻する。
- **入力値**: `import tsumugin` および `from tsumugin import HypothesisTreeSearch, export_gpx`。加えて `tsumugin.export.gpx` モジュールの import が GSAS-II 非依存であることの確認。
  - **不正な理由**: (擬似異常) optional extra 未導入という縮退環境を想定。本環境は導入済みのため、import 成功そのものを検証 (webui は app 内遅延 import で `tsumugin.webui` の import 自体は FastAPI 不要である契約を確認)。
  - **実際の発生シナリオ**: `uv sync`(extra 無し) だけでインストールしたユーザーが `import tsumugin` する場面。
- **期待される結果**: `import tsumugin` が例外なく成功。`export_gpx` は import 時点で GSAS-II を要求しない (実行時に初めて `GSASUnavailableError`)。`import tsumugin.webui` が FastAPI 非導入でも成功 (遅延 import)。
  - **エラーメッセージの内容**: 該当なし (import は成功すべき)。GSAS-II 依存は実行時に `GSASUnavailableError` として明示 (TC-006-03 で別途担保)。
  - **システムの安全性**: 公開面の import がオプション依存に汚染されない。
- **テストの目的**: 遅延 import 契約 (D6) の回帰防止。
  - **品質保証の観点**: 最小依存でのインストール可能性を保証し、公開 API の裾野を守る。
- 🔵 信頼性: 要件定義 §3.4 (D6 遅延 import 契約) / note §1 (web extra 遅延 import) に直接依拠

### TC-010-09: 候補ゼロ E2E — 空 SearchResult へ縮退

- **テスト名**: `test_e2e_empty_candidates_degrades_gracefully`
  - **エラーケースの概要**: 候補相ゼロ (`candidates=[]`) で search を呼んでも例外を投げず、空のランキングを返す。
  - **エラー処理の重要性**: 上流が候補を用意できないケースでもパイプラインがクラッシュしない (M0 pipeline 規約の踏襲)。
- **入力値**: `HypothesisTreeSearch(SimulatedBackend()).search(GRID, y, [])` (`y` は任意の観測)。
  - **不正な理由**: 候補ゼロは探索対象がない縮退入力。
  - **実際の発生シナリオ**: 候補フィルタで全相が除外された、または候補未指定の呼び出し。
- **期待される結果**: 例外を投げず `result.ranked == ()` (空)、`result.ledger.verify() is True`、`json.dumps(result.to_summary())` が成功し `n_hypotheses == 0`。
  - **エラーメッセージの内容**: 例外を出さない (EDGE-001: 空ランキングを返す契約)。
  - **システムの安全性**: 空入力でも summary/ledger が健全な状態を保つ。
- **テストの目的**: 縮退動作 (EDGE-001) の E2E 確認。
  - **品質保証の観点**: 境界的な空入力での堅牢性を統合レベルで保証。
- 🔵 信頼性: 要件定義 §4.5 / 受け入れ基準 TC-E01 (EDGE-001) / note §3 (候補ゼロで空 SearchResult へ縮退) に直接依拠

### TC-010-10: 未知相混入 E2E — unknown_phase_flag と未マッチ報告

- **テスト名**: `test_e2e_unknown_phase_flag_and_unmatched_report`
  - **エラーケースの概要**: 真の構成に「候補にない相」を混ぜた観測データで、候補では説明できない観測ピークが未マッチとして構造化報告され、未知相フラグが立つ。
  - **エラー処理の重要性**: 相ライブラリに無い相の存在をユーザーに提示する (見逃し防止)。
- **入力値**: 観測 = `backend.simulate([PHASE_A, PHASE_B], GRID)` (2 相)、候補 = `[PHASE_A, PHASE_C, PHASE_D]` (真の相 B を候補から除外)。
  - **不正な理由**: (擬似異常) 候補集合が観測を完全説明できない不足状態。
  - **実際の発生シナリオ**: 候補相ライブラリに未登録の相が試料に含まれる実務ケース。
- **期待される結果**: `summary = result.to_summary()` で `summary["unknown_phase_flag"] is True` かつ `summary["unmatched_observed"]` が非空 (各要素が位置・強度を持つ dict)。
  - **エラーメッセージの内容**: 例外でなく summary のフラグ + 未マッチ配列で提示 (構造化出力)。
  - **システムの安全性**: 説明不能ピークを黙殺せず明示 (FR-117)。
- **テストの目的**: 未知相検出 (TC-005-01 / REQ-005) の E2E 確認。
  - **品質保証の観点**: 相同定の網羅性・信頼性の担保。
- 🔵 信頼性: 受け入れ基準 TC-005-01 / REQ-005 / 要件定義 §4.5 に直接依拠

---

## 3. 境界値テストケース（決定論・最小候補・ドキュメント整合）

### TC-010-11: 決定論 — 2 回実行で summary がビット同一

- **テスト名**: `test_e2e_deterministic_summary_bitwise_identical`
  - **境界値の意味**: 同一入力・同一設定での 2 回実行結果が「ビット同一」であること (再現性の下限保証)。
  - **境界値での動作保証**: 乱数種固定 + canonical JSON ソートにより、ランキング・確率・summary が完全再現される。
- **入力値**: 同一の 2 相合成データ・同一候補で `search` を 2 回実行し、それぞれ `json.dumps(to_summary(), sort_keys=True)` を取る。
  - **境界値選択の根拠**: REQ-403 (NFR-102)「同一入力・同一設定での探索結果はビット同一」の直接検証。物理量近似ではなく `==` 完全一致を要求する境界。
  - **実際の使用場面**: 解析の再実行・監査・回帰比較で結果の同一性が前提となる。
- **期待される結果**: 2 回の `json.dumps(sort_keys=True)` 文字列が `==` で完全一致。`ranked` の id/rank/probability も一致。
  - **境界での正確性**: 浮動小数の非決定性・辞書順の揺れが混入しないこと。
  - **一貫した動作**: 実行回数に依存しない出力。
- **テストの目的**: 決定論 (REQ-403 / NFR-102) の統合確認。
  - **堅牢性の確認**: 公開 API 経由でも決定論が崩れないこと。
- 🔵 信頼性: 受け入れ基準 TC-001-05 / REQ-403 / NFR-102 / note §6 (canonical JSON ソート) に直接依拠

### TC-010-12: 候補 1 相 E2E — 深さ 1 の単一仮説

- **テスト名**: `test_e2e_single_candidate_single_hypothesis`
  - **境界値の意味**: 候補が 1 相のみ = 探索木の最小構成 (深さ 1、単一仮説)。
  - **境界値での動作保証**: 最小候補数でも search が単一仮説のランキングを破綻なく返す。
- **入力値**: 観測 = `backend.simulate([PHASE_A], GRID)`、候補 = `[PHASE_A]`。
  - **境界値選択の根拠**: EDGE-102「候補が 1 相のみ → 木は深さ 1、単一仮説のランキングを返す」の直接検証。候補数の下限 (非ゼロ最小)。
  - **実際の使用場面**: 単一相の同定・検証だけを行う最小ケース。
- **期待される結果**: `len(result.ranked) == 1`、`{p.phase_ref for p in result.ranked[0].hypothesis.phases} == {"A"}`、`result.ledger.verify() is True`。
  - **境界での正確性**: 枝刈り (prune_min_candidates=4 未満で無効) が単相探索を阻害しないこと。
  - **一貫した動作**: 候補ゼロ (TC-010-09) と候補複数 (TC-010-03) の中間で連続的に動作。
- **テストの目的**: 最小候補境界 (EDGE-102) の E2E 確認。
  - **堅牢性の確認**: 極小入力での安定動作。
- 🔵 信頼性: 受け入れ基準 TC-E04 (EDGE-102) / 要件定義 §4.5 に直接依拠

### TC-010-13: README の M1 使用例コードが実際に動作する

- **テスト名**: `test_readme_m1_example_executes`
  - **境界値の意味**: ドキュメント (README の M1 使用例) と実装の境界整合。使用例が「絵に描いた餅」でなく実行可能であることの下限保証。
  - **境界値での動作保証**: README に記載する 10-15 行の最小使用例と同等のコードが例外なく完走し、期待の型を返す。
- **入力値**: README「使い方 (M1)」節に記載する最小例と同等のコード (公開 import → `SimulatedBackend` で合成 → `HypothesisTreeSearch(...).search(...)` → `to_summary()`)。
  - **境界値選択の根拠**: 完了条件⑤「README に M1 使用例 (10-15 行)」の実効性検証。ドキュメント成果物のうち唯一コードで自動検証可能な部分。
  - **実際の使用場面**: 新規ユーザーが README を写経して最初の解析を走らせる場面。
- **期待される結果**: 使用例コードが例外なく実行され、最終的に `to_summary()` の dict (または `json.dumps` 可能な結果) が得られる。
  - **境界での正確性**: 公開シンボル名・シグネチャが README と実装で一致していること (import 名の乖離を防止)。
  - **一貫した動作**: README 更新時にコード例が壊れたら本テストが検知する。
- **テストの目的**: ドキュメントと公開 API の同期 (完了条件⑤) を回帰防止。
  - **堅牢性の確認**: 使用例が公開 API の実シグネチャに追従していること。
- 🟡 信頼性: 完了条件⑤ / 要件定義 §2.3 からの妥当な推測 (README 例の「コードによる」検証は実装時に確定。使用例の文面自体は README 側で確定するため 🟡)。
  - **備考**: 本ケースは「使用例の実行可能性」を担保する推奨ケース。README 文面の細部 (アーキテクチャ表の行) は verify-complete のレビューで担保し、テスト対象外。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12
  - **言語選択の理由**: プロジェクト全体が Python 3.12 固定 (`target-version = "py312"`)。M0/M1 実装・既存テストと同一言語。
  - **テストに適した機能**: frozen dataclass の値等価比較、`json.dumps(sort_keys=True)` による決定論検証、`pytest.approx` による物理量近似。
- **テストフレームワーク**: pytest >= 8 + pytest-cov >= 5
  - **フレームワーク選択の理由**: 既存全テストが pytest。マーカー (`@pytest.mark.gsas`) と `conftest.py` の自動 skip、`tmp_path` フィクスチャ、`importorskip` を活用できる。
  - **テスト実行環境**: `uv run pytest` (既定) / `uv run pytest --cov=tsumugin` (カバレッジ) / `uv run pytest -m gsas` (GSAS 経路)。依存導入は `uv sync --extra gsas --extra web` (プレーン `uv sync` は禁止)。
- 🔵 信頼性: `pyproject.toml [tool.pytest.ini_options]` / note §5 / `tests/conftest.py` に直接依拠

### テスト実装方針 (Red フェーズ)

- `tests/test_m1_e2e.py` を新規作成。モジュール冒頭で `from tsumugin import HypothesisTreeSearch, SearchConfig, SearchResult, PhaseCandidate, export_gpx` を試みる — **M1 シンボルが `__init__.py` に未昇格の間は collection 時 ImportError で全テスト失敗 (Red)**。`tests/test_tree_search.py` / `test_gpx_export.py` と同一の Red 方針。
- 実装コメントは各テストに「【テスト目的】/【テスト内容】/【期待される動作】+ 信頼性レベル」と Given/When/Then コメントを付す (プロジェクト慣習 / 既存テストの書式)。
- `@gsas` 2 件は GSAS-II 導入環境でのみ実行 (本環境は導入済み)。`tmp_path` で `.gpx` を隔離 (afterEach 不要)。

---

## 5. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (M1 成果物の公開面配線 + E2E + ドキュメント)
- **参照した入力・出力仕様**: 要件定義 §2.1 (re-export シンボル表) / §2.2 (E2E の search / to_summary 契約) / §2.3 (ドキュメント成果物)
- **参照した制約条件**: 要件定義 §3.1 (品質ゲート) / §3.2 (非破壊) / §3.3 (決定論) / §3.4 (遅延 import) / §3.5 (テスト運用)
- **参照した使用例**: 要件定義 §4.1-§4.5 (再エクスポート確認 / SimulatedBackend E2E / @gsas E2E / データフロー / エッジ)
- **参照した受け入れ基準** (`docs/spec/m1-hypothesis-search/acceptance-criteria.md`): TC-001-01 (2 相 1 位), TC-001-05 (決定論), TC-005-01 (未知相), TC-006-01/02 (@gsas gpx), TC-008-01 (ledger.verify), TC-E01 (EDGE-001 候補ゼロ), TC-E04 (EDGE-102 候補 1 相)
- **参照した完了条件** (`docs/tasks/m1-hypothesis-search/TASK-0010.md`): ① 公開 API (TC-010-01/02), ② E2E summary (TC-010-03/04), ③ @gsas (TC-010-06/07), ④ 全 green・カバレッジ・ruff (TC-010-05 + 非テスト検証項目), ⑤ README/context.md (TC-010-13 + verify-complete), ⑥ verification.md (verify-complete)
- **参照した既存実装・テスト**: `src/tsumugin/__init__.py` (公開面), `tests/test_tree_search.py` (合成データ・search 呼び出し・ledger 検証の範), `tests/test_gpx_export.py` (@gsas 再オープン・再エクスポート確認の範), `tests/test_webui.py` (importorskip・to_summary スキーマの範), `tests/conftest.py` (@gsas 自動 skip)

---

## 6. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 7 / 異常系 3 / 境界値 3 を網羅 (公開面・E2E・@gsas・決定論・縮退・ドキュメント整合)
- 期待値定義: 全ケースで具体的な assert 対象 (相集合 / json.dumps 成否 / __all__ / verify() / フラグ / ビット同一) を特定
- 技術選択: Python 3.12 + pytest 8 + pytest-cov / @gsas 自動 skip / tmp_path で確定
- 実装可能性: 全 13 件が既存テストパターン (test_tree_search / test_gpx_export) の組合せで実装可能
- 信頼性レベル: 🔵 12 / 🟡 1 / 🔴 0 — 🔵 優勢
```

- **要改善点 (実装時に TDD で確定すべき事項)**:
  1. 🔵 昇格シンボルの最終集合 (TC-010-01/02) — 推奨: 必須 5 + `UnmatchedPeakReport`。Green で確定
  2. 🟡 TC-010-13 (README 例のコード検証) を厳密テスト化するか doctest 相当に留めるか — Red で確定 (推奨: 独立テスト関数として実装)

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m1-hypothesis-search TASK-0010` で Red フェーズ（失敗テスト作成）を開始します。
