# TASK-0003 PeakMatcher (マッチングスコア / 未マッチピーク) — TDD テストケース定義

- **機能名 (feature)**: peak-matcher (PeakMatcher: マッチングスコア / 未マッチピーク)
- **タスクID**: TASK-0003
- **要件名 (milestone)**: m1-hypothesis-search
- **タスクタイプ**: TDD / **フェーズ**: Phase 2 - 探索コンポーネント
- **作成日**: 2026-07-03
- **前工程**: `docs/implements/m1-hypothesis-search/TASK-0003/note.md`, `.../peak-matcher-requirements.md`
- **テスト対象 (新規)**: `src/tsumugin/search/matcher.py`
- **テストファイル (新規)**: `tests/test_matcher.py`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: 要件定義書・設計文書 (`interfaces.py`) ・受け入れ基準に直接依拠、ほぼ推測なし
- 🟡 **黄信号**: 要件定義書・設計文書からの妥当な推測 (§7 の確定事項含む)
- 🔴 **赤信号**: 元資料にない推測

---

## 0. 開発言語・フレームワーク

### プログラミング言語: **Python (>= 3.12)**
- **言語選択の理由**: プロジェクト全体が Python / uv 管理 (src layout + hatchling) で統一されており、前提実装 (`Peak`/`find_peaks`, `SimulatedBackend.peak_positions`) がすべて Python。本タスクは numpy のみで完結し scipy・GSAS-II 非依存。🔵
- **テストに適した機能**: frozen dataclass の値等価 (`==`) による決定論比較、`dataclasses.FrozenInstanceError` による不変性検証、numpy のベクトル演算が容易。🔵

### テストフレームワーク: **pytest (>= 8) + pytest-cov**
- **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` で pytest が既定。既存 `tests/test_peaks.py` / `tests/test_simulated_backend.py` が pytest で書かれており書式を踏襲できる。`pytest.approx` で浮動小数比較、`pytest.mark.parametrize` で境界値を網羅できる。🔵
- **テスト実行環境**: `uv run pytest`（`testpaths=["tests"]`, `addopts="-q"`）。本タスクは `gsas` マーカー不要のプレーン numpy 環境で実行。Lint は `uvx ruff check src tests` (line-length 100, target py312)。🔵

🔵 この内容の信頼性レベル: note.md §1/§5・requirements §3・`pyproject.toml` に直接依拠。

### 共通テストヘルパ (既存テストから流用)
```python
# tests/test_matcher.py の想定モジュールレベルヘルパ (test_peaks.py / test_simulated_backend.py 準拠)
def _phase(a=5.0, scale=1.0, ref="P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)
def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)
def _backend() -> SimulatedBackend:
    return SimulatedBackend(peak_fwhm=0.2)
def _candidate(positions, height=1.0) -> tuple[Peak, ...]:
    # peak_positions は位置のみ返すため、一定 height で Peak に包む (候補 height はスコア不使用)
    return tuple(Peak(position=p, height=height) for p in positions)

# import (未実装のため collection 時に失敗 → Red 成立)
from tsumugin.search.matcher import MatchResult, match_score, UnmatchedPeakReport, unmatched_peaks
from tsumugin.search.peaks import Peak, find_peaks
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance
```
🔵 note.md §5「モジュールレベルヘルパ流用」・requirements §6 に依拠。

---

## 1. 正常系テストケース（基本的な動作）

### TC-N01: 一致相のスコアが不一致相のスコアより大きい (TC-002-01)

- **テスト名**: 一致相 vs 不一致相のマッチングスコア比較
  - **何をテストするか**: 観測パターンを生成した「真の相」の候補ピークで計算した `score` が、ピーク位置がずれた「別相」の `score` より厳密に大きいこと。
  - **期待される動作**: `match_score(真相候補, 観測).score > match_score(不一致候補, 観測).score`。
- **入力値**:
  - 観測: `observed = find_peaks(_grid(), _backend().simulate((_phase(a=5.0),), _grid()))`
  - 一致候補: `_candidate(_backend().peak_positions(_phase(a=5.0), _grid()))`
  - 不一致候補: `_candidate(_backend().peak_positions(_phase(a=4.3), _grid()))`（格子定数を変え位置をずらす）
  - `tol_deg=0.15`（既定）
  - **入力データの意味**: 観測は a=5.0 の単相から生成した「教師データ」。同じ a=5.0 の候補は位置一致、a=4.3 の候補は位置が系統的にずれ、代表的な「正解 vs 不正解」を表す。
- **期待される結果**: `score_match > score_mismatch`（両者とも [0,1]、一致相は 1.0 に近く、不一致相は明確に小さい）。
  - **期待結果の理由**: スコア定義 `0.5·match_rate + 0.5·intensity_coverage` により、位置が揃う一致相は候補一致率・観測強度被覆率がともに高く、位置がずれた相は両項が低下するため。これが木探索の事前枝刈り指標 (FR-111) の中核要件。
- **テストの目的**: 完了条件「一致する相のスコア > 一致しない相のスコア」(TC-002-01) の充足を確認。
  - **確認ポイント**: スコアの絶対値ではなく相対的な大小関係。`>` が成立し、かつ両スコアが値域 [0,1] に収まること。
- 🔵 信頼性レベル: 受け入れ基準 TC-002-01・完了条件1・note.md §5 に直接依拠。

### TC-N02: matched_observed が正しい観測ピーク index を昇順で返す (FR-117)

- **テスト名**: マッチ観測ピーク index の正確性
  - **何をテストするか**: 一致相を渡したとき、`MatchResult.matched_observed` にマッチが成立した観測ピークの index が昇順で格納されること。
  - **期待される動作**: 真相候補に対して、観測ピークの大半 (理想的には全て) の index が昇順タプルで返る。
- **入力値**: TC-N01 の一致候補・観測を使用。`observed` の各 index は 0..len-1。
  - **入力データの意味**: index 対応の検証には、観測列と一致する候補が必要。
- **期待される結果**: `result.matched_observed` は `tuple[int, ...]`、`sorted(matched) == list(matched)`（昇順）、各要素は `0 <= i < len(observed)` の有効 index。マッチ数 >= 1。
  - **期待結果の理由**: FR-117 で未マッチ集約に「マッチ済み観測 index の和集合」を使うため、index が正確かつ昇順・重複なしである必要がある。
- **テストの目的**: `matched_observed` が観測 index を正しく返す (FR-117) ことを確認。
  - **確認ポイント**: index が観測列の範囲内・昇順・重複なし。1 観測ピークが高々 1 回だけ現れる (1:1 貪欲一致)。
- 🔵 信頼性レベル: 完了条件3・interfaces.py の `matched_observed` 契約・FR-117 に依拠。

### TC-N03: unmatched_candidate が観測相手のない候補位置を昇順で返す (extra)

- **テスト名**: 未マッチ候補ピーク位置 (extra 計算ピーク) の抽出
  - **何をテストするか**: 観測に対応相手が無い候補ピーク位置が `MatchResult.unmatched_candidate` に float の昇順タプルで格納されること。
  - **期待される動作**: 観測に存在しない位置の候補ピークだけが `unmatched_candidate` に入り、マッチした候補位置は含まれない。
- **入力値**:
  - 観測: `find_peaks` で 2 本だけピークを持つ合成パターン (例: 主要反射のみ)。
  - 候補: 観測 2 本に一致する位置 + 観測に無い位置 (例: `[観測位置0, 観測位置1, 25.0(観測に無い)]`) を `Peak` に包む。
  - **入力データの意味**: 「一部一致 + 一部 extra」という現実的な候補相を表す。
- **期待される結果**: `result.unmatched_candidate == (25.0,)`（観測に無い候補位置のみ、昇順 float タプル）。マッチした候補位置は含まれない。
  - **期待結果の理由**: FR-117 の「観測に現れない計算ピーク (extra)」を可視化するため。tol_deg 内に観測が無い候補だけが extra。
- **テストの目的**: `unmatched_candidate` が extra 候補位置を正しく返す (FR-117) ことを確認。
  - **確認ポイント**: float タプル・昇順・マッチ済み位置を除外していること。
- 🔵 信頼性レベル: 完了条件3・interfaces.py の `unmatched_candidate` 契約・FR-117 に依拠。

### TC-N04: score が値域 [0,1] に収まる

- **テスト名**: スコア値域の保証
  - **何をテストするか**: 一致相・不一致相・部分一致相のいずれでも `0.0 <= score <= 1.0` であること。
  - **期待される動作**: 等重み平均の各項が [0,1] のため合成も [0,1]。
- **入力値**: TC-N01 の一致候補・不一致候補、および部分一致候補 (半数一致) の 3 パターンを parametrize。
  - **入力データの意味**: スコア範囲の代表点 (高・低・中間) を網羅。
- **期待される結果**: すべてのケースで `0.0 <= score <= 1.0`。一致相は約 1.0、不一致相は約 0.0〜低値、部分一致は中間値。
  - **期待結果の理由**: 下流の `dynamic_threshold` (TASK-0004) がスコアを [0,1] 前提で消費するため値域逸脱は許されない。
- **テストの目的**: 完了条件「score ∈ [0,1]」の充足を確認。
  - **確認ポイント**: 上限 1.0・下限 0.0 を超えないこと。NaN/inf が出ないこと。
- 🟡 信頼性レベル: 完了条件2・requirements §4.2「値域確認」からの妥当な推測 (スコア定義式に依存)。

### TC-N05: candidate_index が渡した値で MatchResult に反映される

- **テスト名**: 候補 index の伝搬
  - **何をテストするか**: `match_score(..., candidate_index=k)` で渡した `k` が `MatchResult.candidate_index` にそのまま格納されること。既定は 0。
  - **期待される動作**: `match_score(cand, obs, candidate_index=3).candidate_index == 3`、既定呼び出しでは 0。
- **入力値**: 任意の候補・観測に対し `candidate_index=0`（既定）と `candidate_index=3` の 2 通り。
  - **入力データの意味**: 木探索の候補ループが採番する index を単体で検証する (§7 確定事項#1)。
- **期待される結果**: 既定で `candidate_index == 0`、明示指定で `candidate_index == 3`。
  - **期待結果の理由**: `MatchResult` の完全性 (どの候補相の結果かを保持) と関数純度を両立する設計判断のため。
- **テストの目的**: 推奨案 (キーワード専用引数 `candidate_index: int = 0`) が正しく機能することを確認。
  - **確認ポイント**: キーワード専用であること・既定値 0・伝搬の正確性。
- 🟡 信頼性レベル: requirements §2.1・§7 確定事項#1 (interfaces に引数なし → 推奨案で確定) の妥当な推測。

### TC-N06: 決定論 — 同一入力の 2 回実行でビット同一

- **テスト名**: match_score / unmatched_peaks の決定論性
  - **何をテストするか**: 同一入力・同一設定で `match_score` と `unmatched_peaks` を 2 回呼び出し、戻り値が完全一致すること。
  - **期待される動作**: frozen dataclass の値等価により `r1 == r2`（score・タプル順まで一致）。
- **入力値**: TC-N01 の一致候補・観測。`match_score` を 2 回、続けて `unmatched_peaks([r], observed)` を 2 回。
  - **入力データの意味**: 乱数不使用・純関数の決定論契約 (NFR-102 / REQ-403) を代表。
- **期待される結果**: `match_score(...) == match_score(...)` かつ `unmatched_peaks(...) == unmatched_peaks(...)`（score・タプル要素・順序すべて一致）。
  - **期待結果の理由**: 探索全体の再現性 (TC-001-05 の基盤) を支えるため、マッチングも決定論でなければならない。
- **テストの目的**: 決定論 (NFR-102 / REQ-403) の充足を確認。
  - **確認ポイント**: score の浮動小数もビット同一 (approx でなく `==`)、タプル順の固定。
- 🔵 信頼性レベル: requirements §3 (NFR-102/REQ-403)・note.md §6・既存 `test_deterministic_same_input_returns_equal` に依拠。

### TC-N07: unmatched_peaks が未マッチ観測ピークを位置・強度付きで報告 + flag True (TC-005-01)

- **テスト名**: 候補にない相を混ぜたデータの未マッチ観測ピーク報告
  - **何をテストするか**: 真の構成に「候補集合に含まれない相」を混ぜた観測に対し、どの候補でも説明できない観測ピークが `Peak` 実体 (位置・強度付き) で `unmatched_observed` に報告され、`unknown_phase_flag=True` となること。
  - **期待される動作**: 未説明ピークが位置昇順の `tuple[Peak, ...]` で返り、フラグが立つ。
- **入力値**:
  - 観測: `simulate((_phase(a=5.0, ref="A"), _phase(a=4.3, ref="B")), grid)` を `find_peaks`（A+B の 2 相）。
  - 候補: A のみ (`_candidate(peak_positions(_phase(a=5.0), grid))`) の `match_score` 結果 1 件。B は候補に含めない。
  - `unmatched_peaks([result_A], observed, high_r_flag=False)`
  - **入力データの意味**: 観測は A+B だが候補は A のみ → B 由来のピークが「未知相」として残る、TC-005-01 の典型シナリオ。
- **期待される結果**: `report.unmatched_observed` が非空 (B 由来ピークを含む)、各要素は `Peak` で `position`・`height` を保持し位置昇順。`report.unknown_phase_flag is True`。
  - **期待結果の理由**: REQ-005 (FR-117)「未マッチ観測ピークを位置・強度付きで構造化出力」＋「未説明ピーク有り → 未知相フラグ」の直接要件。
- **テストの目的**: TC-005-01 の充足 (未マッチ観測を `Peak` で報告・フラグ True) を確認。
  - **確認ポイント**: `Peak` 型で height が保持されていること (float の位置だけでない)、昇順、フラグが True。
- 🔵 信頼性レベル: 受け入れ基準 TC-005-01・requirements §4.1・interfaces.py の `UnmatchedPeakReport` 契約に直接依拠。

### TC-N08: unmatched_peaks が完全説明データで未マッチ空・flag False (TC-005-02)

- **テスト名**: 完全説明データでの未マッチ空・フラグ False
  - **何をテストするか**: 観測を全候補で説明できる場合、`unmatched_observed` が空タプルで `unknown_phase_flag=False` となること。
  - **期待される動作**: すべての観測ピークがいずれかの候補にマッチし、未説明が残らない。
- **入力値**:
  - 観測: `simulate((_phase(a=5.0),), grid)` を `find_peaks`（単相 A）。
  - 候補: A の `match_score` 結果 1 件 (全観測にマッチ)。
  - `unmatched_peaks([result_A], observed, high_r_flag=False)`
  - **入力データの意味**: 観測 = 候補 A で完全説明できるケース、TC-005-02 の典型。
- **期待される結果**: `report.unmatched_observed == ()`、`report.unknown_phase_flag is False`。`extra_calculated` は空または extra のみ。
  - **期待結果の理由**: 説明済みなら未知相フラグを立ててはならない (誤警告防止)。REQ-005 の対の要件。
- **テストの目的**: TC-005-02 の充足 (完全説明で空・フラグ False) を確認。
  - **確認ポイント**: 空タプル・フラグ False。`high_r_flag=False` のときフラグが立たないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-005-02・requirements §4.1 に直接依拠。

### TC-N09: MatchResult / UnmatchedPeakReport が frozen dataclass (不変)

- **テスト名**: 戻り値の型と不変性
  - **何をテストするか**: `match_score` が `MatchResult` を、`unmatched_peaks` が `UnmatchedPeakReport` を返し、いずれも属性再代入で `FrozenInstanceError` を送出すること。
  - **期待される動作**: 非破壊・不変な値オブジェクト (P2 / REQ-402)。
- **入力値**: 任意の候補・観測から得た `MatchResult` / `UnmatchedPeakReport` インスタンス。
  - **入力データの意味**: frozen dataclass 契約の代表確認。
- **期待される結果**: `isinstance(result, MatchResult)`・`isinstance(report, UnmatchedPeakReport)`。`result.score = 0.0` 等で `dataclasses.FrozenInstanceError`。各タプルフィールドが `tuple` 型。
  - **期待結果の理由**: 不変・非破壊 (P2 / REQ-402) の保証。削除・上書き API を作らない方針の検証。
- **テストの目的**: interfaces.py の frozen dataclass 契約の充足を確認。
  - **確認ポイント**: 型の正しさ・`FrozenInstanceError`・フィールドが不変タプル。
- 🔵 信頼性レベル: interfaces.py の `@dataclass(frozen=True)`・requirements §3 (REQ-402)・既存 `test_returns_sorted_immutable_tuple_of_peaks` に依拠。

### TC-N10: スコアが等重み平均式に一致する (数値検証)

- **テスト名**: スコア定義式 (0.5·match_rate + 0.5·intensity_coverage) の数値一致
  - **何をテストするか**: 手計算可能な小規模入力で `score` が `0.5·(マッチ候補数/候補総数) + 0.5·(マッチ観測 height 和/全観測 height 和)` に一致すること。
  - **期待される動作**: 定義式どおりの値を返す。
- **入力値**:
  - 観測: `(Peak(20.0, 10.0), Peak(30.0, 30.0))`（height 合計 40）を直接構成。
  - 候補: `(Peak(20.0, 1.0), Peak(25.0, 1.0))`（20.0 は観測にマッチ、25.0 は extra）。
  - `tol_deg=0.15`
  - **入力データの意味**: 手計算で検算できる最小構成。match_rate=1/2=0.5、intensity_coverage=10/40=0.25。
- **期待される結果**: `score == pytest.approx(0.5*0.5 + 0.5*0.25)` = `pytest.approx(0.375)`。`matched_observed == (0,)`、`unmatched_candidate == (25.0,)`。
  - **期待結果の理由**: §7 確定事項#3 (等重み)・#4 (観測側 height で被覆率) の実装式を数値レベルで固定するため。
- **テストの目的**: スコア定義 (設計 D) の実装が仕様式と一致することを確認。
  - **確認ポイント**: 重み 0.5/0.5・被覆率が観測側 height で計算されること (候補 height=1.0 はスコアに寄与しない)。
- 🟡 信頼性レベル: requirements §2.1 スコア定義・§7 確定事項#3/#4 からの妥当な推測 (等重み配分は設計 D の推測)。

---

## 2. 異常系テストケース（エラーハンドリング / EDGE-003 縮退）

### TC-E01: 候補ゼロで score=0.0・空タプル・例外なし (EDGE / TC-E01 系基盤)

- **テスト名**: 候補ピークゼロの縮退
  - **エラーケースの概要**: `candidate_peaks=()`（候補相にピークが 1 本も無い）で `match_score` を呼ぶケース。
  - **エラー処理の重要性**: 候補生成が空を返す上流ケース (範囲内反射ゼロ等) で探索全体を止めないため、例外でなく縮退結果を返す必要がある (M0 規約「失敗は縮退結果へ」)。
- **入力値**: `match_score((), observed)`（`observed` は非空の任意観測列）。
  - **不正な理由**: 候補総数 0 で match_rate の分母が 0 になる縮退入力。
  - **実際の発生シナリオ**: `peak_positions` が 2θ 範囲内に反射を返さない相を候補にしたとき。
- **期待される結果**: `score == 0.0`、`matched_observed == ()`、`unmatched_candidate == ()`、例外送出なし。
  - **エラーメッセージの内容**: 例外を出さない (メッセージ不要)。値で縮退を表現する。
  - **システムの安全性**: ゼロ除算を回避し、下流が [0,1] スコアとして安全に扱える 0.0 を返す。
- **テストの目的**: 候補ゼロの安全な縮退 (EDGE-001 相当 / TC-E01 系基盤) を確認。
  - **品質保証の観点**: 空入力でクラッシュしない堅牢性を保証し、探索の完走性 (TC-E03 系) を支える。
- 🔵 信頼性レベル: requirements §4.2 EDGE (候補ゼロ)・完了条件2・note.md §6 に直接依拠。

### TC-E02: 観測ゼロで score=0.0・全候補 extra・例外なし (EDGE-003)

- **テスト名**: 観測ピークゼロの縮退
  - **エラーケースの概要**: `observed_peaks=()`（観測ピークが 1 本も無い）で `match_score` を呼ぶケース。
  - **エラー処理の重要性**: フラット/全ゼロパターンで `find_peaks` が空を返す上流ケース (EDGE-003) を安全に処理するため。
- **入力値**: `match_score(candidate, ())`（`candidate` は非空の候補列、例: 3 本）。
  - **不正な理由**: 観測総数 0 で intensity_coverage の分母が 0 になる縮退入力。
  - **実際の発生シナリオ**: 空試料・全ゼロパターン・極端なノイズ除去で観測ピークが検出されない場合。
- **期待される結果**: `score == 0.0`、`matched_observed == ()`、`unmatched_candidate` に全候補位置 (昇順 float タプル)、例外送出なし。
  - **エラーメッセージの内容**: 例外なし。全候補が「観測に相手が無い extra」として扱われる。
  - **システムの安全性**: ゼロ除算回避、`unmatched_candidate` が全候補位置を保持し extra として可視化される。
- **テストの目的**: 観測ゼロの安全な縮退 (EDGE-003) を確認。
  - **品質保証の観点**: 上流 `find_peaks` の空縮退 (EDGE-003) と一貫した挙動で、パイプライン全体の縮退整合を保証。
- 🔵 信頼性レベル: 受け入れ基準 TC-E01/EDGE-003・requirements §4.2 EDGE-003・完了条件2 に直接依拠。

### TC-E03: high_r_flag=True で未マッチ空でも unknown_phase_flag=True (REQ-106)

- **テスト名**: 全仮説高 R による未知相フラグ強制
  - **エラーケースの概要**: 未マッチ観測ピークが無くても、呼び出し側が `high_r_flag=True`（全仮説が高 R 値）を渡したとき、`unknown_phase_flag` を強制的に True にするケース。
  - **エラー処理の重要性**: 位置マッチは取れても精密化 R が全滅する「見かけ上説明できるが実は不適合」な状況を利用者に通知するため (REQ-106 / TC-E02)。
- **入力値**: 完全説明データ (TC-N08 相当、`unmatched_observed` が空になる入力) に対し `unmatched_peaks([result_A], observed, high_r_flag=True)`。
  - **不正な理由**: 通常なら `unmatched_observed` 空 → フラグ False だが、high_r_flag が優先されるべきケース。
  - **実際の発生シナリオ**: 全候補仮説の精密化 R 値が閾値超で、位置一致だけでは信頼できないと木探索が判断した場合。
- **期待される結果**: `report.unmatched_observed == ()` でも `report.unknown_phase_flag is True`。
  - **エラーメッセージの内容**: フラグで「要確認 (未知相の可能性)」を伝達。
  - **システムの安全性**: 誤って「完全説明」と報告するのを防ぎ、利用者に確認を促す。
- **テストの目的**: `unknown_phase_flag` の条件「未マッチ非空 or high_r_flag」(§7#7) と REQ-106 の充足を確認。
  - **品質保証の観点**: 偽陰性 (未知相の見逃し) を防ぐ安全側フェイルの検証。
- 🔵 信頼性レベル: 受け入れ基準 TC-E02 (EDGE-002)・requirements §4.2 REQ-106・§7 確定事項#7 に直接依拠。

### TC-E04: フラットパターン (observed 空) で未マッチ空・フラグは high_r_flag に従う (TC-005-03)

- **テスト名**: フラットパターンの縮退 (未知相フラグを立てない)
  - **エラーケースの概要**: `find_peaks` が空を返すフラットパターンで observed が空 → `unmatched_peaks` を呼ぶケース。
  - **エラー処理の重要性**: 観測ピークが無いことを「未知相あり」と誤認しないため。空良好解 + 上位警告に委ねる (TC-005-03)。
- **入力値**: `unmatched_peaks([], observed=(), high_r_flag=False)`（観測空・候補結果も無し）。加えて `high_r_flag=True` の対も検証。
  - **不正な理由**: 観測空は「説明対象が無い」状態で、未マッチも定義できない縮退。
  - **実際の発生シナリオ**: 全ゼロ/フラットな入力パターン (EDGE-003)。
- **期待される結果**: `report.unmatched_observed == ()`、`report.extra_calculated == ()`。`high_r_flag=False` なら `unknown_phase_flag is False`、`high_r_flag=True` なら True。例外なし。
  - **エラーメッセージの内容**: 例外なし。未知相フラグは high_r_flag のみに従う (未マッチ由来では立てない)。
  - **システムの安全性**: 空観測で誤フラグを立てず、上位の警告機構に判断を委ねる。
- **テストの目的**: TC-005-03 (フラット縮退) の充足を確認。
  - **品質保証の観点**: 空入力の一貫縮退 (例外なし・誤警告なし) を保証。
- 🟡 信頼性レベル: 受け入れ基準 TC-005-03・requirements §4.2 (フラットパターン) からの妥当な推測。

---

## 3. 境界値テストケース（tol_deg 境界 / 貪欲一致 / 集約）

### TC-B01: tol_deg ちょうどの位置ずれは閉区間でマッチに含める

- **テスト名**: tol_deg 境界 (閉区間 `|Δ2θ| <= tol_deg`) の内側判定
  - **境界値の意味**: 位置差がちょうど `tol_deg` の候補が「マッチ」に含まれるか否かで検出本数が変わる決定的境界。
  - **境界値での動作保証**: 境界の扱いを一意 (閉区間) に固定し、浮動小数の等値ぶれによる非決定を排除する (§7#5)。
- **入力値**:
  - 観測: `(Peak(30.0, 10.0),)`
  - 候補: `(Peak(30.15, 1.0),)`（位置差 = 0.15 = tol_deg ちょうど）
  - `tol_deg=0.15`
  - **境界値選択の根拠**: `|30.15 - 30.0| = 0.15` は許容幅の下限境界そのもの。
  - **実際の使用場面**: 装置ゼロ点ずれや格子微差でピークが許容幅ぎりぎりに来る現実的ケース。
- **期待される結果**: 候補がマッチ扱い → `matched_observed == (0,)`、`unmatched_candidate == ()`、`score > 0`。
  - **境界での正確性**: 閉区間 `<=` により境界値がマッチ側に確定的に分類される。
  - **一貫した動作**: 境界の内側 (0.15) はマッチ、外側 (TC-B02) は非マッチで一貫。
- **テストの目的**: tol_deg 境界の閉区間判定 (§7#5) と決定論を確認。
  - **堅牢性の確認**: 浮動小数境界での分類が一意に定まること。
- 🟡 信頼性レベル: requirements §4.2 tol_deg 境界・§7 確定事項#5 (閉区間) からの妥当な推測。

### TC-B02: tol_deg を僅かに超える位置ずれは非マッチ (extra)

- **テスト名**: tol_deg 境界の外側判定
  - **境界値の意味**: 位置差が `tol_deg` を僅かに超えると非マッチ (extra) になる境界外の確認。
  - **境界値での動作保証**: 閉区間の外側が確実に非マッチへ分類されること。
- **入力値**:
  - 観測: `(Peak(30.0, 10.0),)`
  - 候補: `(Peak(30.16, 1.0),)`（位置差 = 0.16 > tol_deg=0.15）
  - **境界値選択の根拠**: 許容幅を明確に超える最小近傍点。
  - **実際の使用場面**: 別相由来で本来一致すべきでないピーク。
- **期待される結果**: 非マッチ → `matched_observed == ()`、`unmatched_candidate == (30.16,)`、観測は未マッチ扱い。
  - **境界での正確性**: `0.16 > 0.15` が非マッチに確定分類される。
  - **一貫した動作**: TC-B01 (内側=マッチ) と対で境界の内外が一貫。
- **テストの目的**: 境界外の非マッチ分類と extra 抽出を確認。
  - **堅牢性の確認**: 境界を越えた点を誤ってマッチしないこと (オフバイワン防止)。
- 🟡 信頼性レベル: requirements §4.2 tol_deg 境界・§7#5 からの妥当な推測。

### TC-B03: tol_deg 境界入力でも決定論 (2 回実行でビット同一)

- **テスト名**: 境界近傍の決定論安定性
  - **境界値の意味**: 境界近傍は浮動小数比較が不安定になりやすく、決定論が最も破れやすい点。
  - **境界値での動作保証**: 境界ちょうどの入力でも 2 回実行で完全一致すること。
- **入力値**: TC-B01 の入力 (`Peak(30.15)` vs `Peak(30.0)`, tol_deg=0.15) を 2 回。
  - **境界値選択の根拠**: 完了条件「tol_deg の境界で両側判定が決定論的」を直接検証。
  - **実際の使用場面**: 再現性が要求される探索の再実行。
- **期待される結果**: `match_score(...) == match_score(...)`（score・matched・unmatched すべてビット同一）。
  - **境界での正確性**: 境界判定順・戻りタプル順が固定。
  - **一貫した動作**: 何度実行しても同一結果。
- **テストの目的**: 完了条件「許容 tol_deg の境界で両側判定が決定論的」の充足を確認。
  - **堅牢性の確認**: 境界近傍でも乱れず決定論を維持。
- 🟡 信頼性レベル: 完了条件5・requirements §3 (NFR-102)・§4.2 からの妥当な推測。

### TC-B04: 貪欲一致で 1 観測ピークは高々 1 候補にマッチ (1:1 重複防止)

- **テスト名**: 貪欲一致の 1:1 重複防止
  - **境界値の意味**: 複数の候補ピークが 1 つの観測ピークの tol_deg 内に入る競合ケースで、重複マッチを防ぐ規則の境界。
  - **境界値での動作保証**: 1 観測ピークが 2 回カウントされず、マッチ本数が入力順に依存しないこと (§7#6)。
- **入力値**:
  - 観測: `(Peak(30.0, 10.0),)`（1 本のみ）
  - 候補: `(Peak(29.95, 1.0), Peak(30.05, 1.0))`（2 本とも観測 30.0 の tol_deg 内）
  - **境界値選択の根拠**: 1 観測に対し複数候補が競合する最小構成。
  - **実際の使用場面**: 近接反射を持つ候補相。
- **期待される結果**: `matched_observed == (0,)`（観測 index 0 は 1 回のみ）、マッチ候補は 1 本だけ (最近傍の 30.05 か走査順先頭)、残り 1 本は `unmatched_candidate` に入る。`matched_observed` に重複なし。
  - **境界での正確性**: 1 観測ピークが高々 1 候補にマッチ、重複カウントなし。
  - **一貫した動作**: 候補の入力順を入れ替えてもマッチ本数が不変 (決定論)。
- **テストの目的**: §7 確定事項#6 (1:1 貪欲・重複防止) と順序非依存の決定論を確認。
  - **堅牢性の確認**: match_rate/coverage が重複カウントで水増しされないこと。
- 🟡 信頼性レベル: requirements §3 (貪欲一致重複防止)・§7 確定事項#6 からの妥当な推測。

### TC-B05: unmatched_peaks が extra_calculated を昇順・重複排除で集約

- **テスト名**: 複数候補 extra の集約 (昇順・重複排除)
  - **境界値の意味**: 複数の `MatchResult.unmatched_candidate` を集約する際、重複位置の排除と昇順整列が正しく行われる境界。
  - **境界値での動作保証**: 同一 extra 位置が複数候補から来ても 1 回だけ・昇順で返る。
- **入力値**:
  - `match_results = [MatchResult(0, ..., unmatched_candidate=(25.0, 40.0)), MatchResult(1, ..., unmatched_candidate=(25.0, 60.0))]`（25.0 が重複）
  - `observed` は任意 (未マッチ観測は別途)。
  - **境界値選択の根拠**: 重複位置 (25.0) と非重複位置 (40.0, 60.0) を混在させ集約規則を検証。
  - **実際の使用場面**: 複数候補相が同じ位置に extra 計算ピークを持つ場合。
- **期待される結果**: `report.extra_calculated == (25.0, 40.0, 60.0)`（昇順・25.0 は 1 回のみ）。
  - **境界での正確性**: 重複排除と昇順が両立。
  - **一貫した動作**: 入力 `match_results` の順序に依存しない出力。
- **テストの目的**: requirements §2.2「extra_calculated は昇順・重複排除」の充足を確認。
  - **堅牢性の確認**: 重複が残らず・順序が固定 (決定論)。
- 🔵 信頼性レベル: requirements §2.2 (extra_calculated 昇順・重複排除)・interfaces.py に直接依拠。

---

## 4. テストケース実装時の日本語コメント指針

各テストケース実装時に以下の日本語コメントを必ず含める (既存 `tests/test_peaks.py` の書式に準拠)。

### テストケース開始時のコメント
```python
# 【テスト目的】: [このテストで確認する内容を日本語で明記]
# 【テスト内容】: [具体的にどのような処理をテストするか]
# 【期待される動作】: [正常に動作した場合の結果]
# 🔵🟡🔴 信頼性レベル
```

### Given（準備フェーズ）のコメント
```python
# 【テストデータ準備】: [なぜこのデータを用意するかの理由]
# 【初期条件設定】: [テスト実行前の状態]
# 【前提条件確認】: [テスト実行に必要な前提条件]
```

### When（実行フェーズ）のコメント
```python
# 【実際の処理実行】: [呼び出す関数 match_score / unmatched_peaks の説明]
# 【処理内容】: [実行される処理の内容]
```

### Then（検証フェーズ）のコメント
```python
# 【結果検証】: [何を検証するか]
# 【期待値確認】: [期待される結果とその理由]
# 【品質保証】: [この検証がシステム品質にどう貢献するか]
```

### 各 assert ステートメントのコメント例
```python
assert result.score > mismatch.score  # 【確認内容】: 一致相スコアが不一致相を上回る (TC-002-01) 🔵
assert report.unknown_phase_flag is True  # 【確認内容】: 未マッチ観測ありで未知相フラグが立つ (TC-005-01) 🔵
assert list(report.unmatched_observed) == sorted(...)  # 【確認内容】: 位置昇順で報告される 🔵
```

---

## 5. 要件定義との対応関係

- **参照した機能概要**: peak-matcher-requirements.md §1 (match_score / unmatched_peaks の役割), note.md §4 (契約)
- **参照した入力・出力仕様**: requirements §2.1 (`match_score` 入出力・スコア定義式), §2.2 (`unmatched_peaks` シグネチャ・`UnmatchedPeakReport`)
- **参照した制約条件**: requirements §3 (決定論 NFR-102/REQ-403, 貪欲 1:1, 例外禁止 EDGE-003, 非破壊 REQ-402), §7 確定事項 (index/シグネチャ/重み/境界/貪欲)
- **参照した使用例**: requirements §4.1 (基本パターン), §4.2 (エッジ・境界・エラー)
- **参照した受け入れ基準**: acceptance-criteria.md TC-002-01, TC-005-01, TC-005-02, TC-005-03, TC-E01(EDGE-001), TC-E02(EDGE-002/REQ-106)
- **参照した設計文書**: `docs/design/m1-hypothesis-search/interfaces.py` (`search/matcher.py` 節: `MatchResult`/`match_score`/`UnmatchedPeakReport`, `SearchConfig.match_tol_deg=0.15`)
- **前提実装**: `src/tsumugin/search/peaks.py` (`Peak`/`find_peaks`), `src/tsumugin/backends/simulated.py` (`peak_positions`/`simulate`)

---

## 6. テストケース一覧サマリー

| # | ID | 分類 | テスト内容 | 対応 AC / 要件 | 信頼性 |
|---|-----|------|-----------|----------------|--------|
| 1 | TC-N01 | 正常系 | 一致相スコア > 不一致相スコア | TC-002-01 / FR-111 | 🔵 |
| 2 | TC-N02 | 正常系 | matched_observed が観測 index 昇順 | FR-117 | 🔵 |
| 3 | TC-N03 | 正常系 | unmatched_candidate が extra 位置昇順 | FR-117 | 🔵 |
| 4 | TC-N04 | 正常系 | score ∈ [0,1] 値域 | 完了条件2 | 🟡 |
| 5 | TC-N05 | 正常系 | candidate_index の伝搬 | §7#1 | 🟡 |
| 6 | TC-N06 | 正常系 | 決定論 (2 回実行ビット同一) | NFR-102/REQ-403 | 🔵 |
| 7 | TC-N07 | 正常系 | 未マッチ観測を位置・強度付き報告 + flag True | TC-005-01 | 🔵 |
| 8 | TC-N08 | 正常系 | 完全説明で未マッチ空・flag False | TC-005-02 | 🔵 |
| 9 | TC-N09 | 正常系 | MatchResult/Report が frozen 不変 | REQ-402 | 🔵 |
| 10 | TC-N10 | 正常系 | スコア等重み平均式の数値一致 | §7#3/#4 | 🟡 |
| 11 | TC-E01 | 異常系 | 候補ゼロで score=0.0・空・例外なし | EDGE-001/完了条件2 | 🔵 |
| 12 | TC-E02 | 異常系 | 観測ゼロで score=0.0・全 extra・例外なし | EDGE-003 | 🔵 |
| 13 | TC-E03 | 異常系 | high_r_flag=True で flag 強制 True | TC-E02/REQ-106/§7#7 | 🔵 |
| 14 | TC-E04 | 異常系 | フラット (observed 空) で未マッチ空 | TC-005-03 | 🟡 |
| 15 | TC-B01 | 境界値 | tol_deg ちょうど → 閉区間でマッチ | §7#5 | 🟡 |
| 16 | TC-B02 | 境界値 | tol_deg 超過 → 非マッチ (extra) | §7#5 | 🟡 |
| 17 | TC-B03 | 境界値 | 境界入力でも決定論ビット同一 | 完了条件5/NFR-102 | 🟡 |
| 18 | TC-B04 | 境界値 | 貪欲 1:1 重複防止 (1 観測≤1 候補) | §7#6 | 🟡 |
| 19 | TC-B05 | 境界値 | extra_calculated 昇順・重複排除集約 | §2.2 | 🔵 |

### ケース数内訳
- **正常系**: 10 件 (TC-N01〜N10)
- **異常系 (EDGE 縮退)**: 4 件 (TC-E01〜E04)
- **境界値**: 5 件 (TC-B01〜B05)
- **合計**: **19 件**

### 信頼性レベル分布
- 🔵 青信号: 10 件 (53%) — 構造・契約・受け入れ基準に直接依拠
- 🟡 黄信号: 9 件 (47%) — §7 確定事項 (重み・境界・貪欲・index) に基づく較正的判断
- 🔴 赤信号: 0 件

**品質評価: 高品質** — 正常系・異常系・境界値を網羅。全ケースに期待値が明確に定義され、言語 (Python) / フレームワーク (pytest) が確定済み。前提実装が完了しているため現技術スタックで実装可能。🟡 は仕様が推奨案で確定済みの較正点のみで、実装時に一意に定まる。

---

## 7. 次のステップ

- **次のお勧めステップ**: `/tsumiki:tdd-red m1-hypothesis-search TASK-0003` で Red フェーズ（失敗テスト作成）を開始する。
- 上記 19 ケースを `tests/test_matcher.py` に実装。冒頭の `from tsumugin.search.matcher import ...` が未実装のため collection 時 import 失敗 → Red 成立。
