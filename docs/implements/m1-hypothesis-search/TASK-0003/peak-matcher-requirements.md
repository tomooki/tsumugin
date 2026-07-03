# TASK-0003 PeakMatcher (マッチングスコア / 未マッチピーク) — TDD 要件定義書

- **機能名 (feature)**: peak-matcher (PeakMatcher: マッチングスコア / 未マッチピーク)
- **タスクID**: TASK-0003
- **要件名 (milestone)**: m1-hypothesis-search
- **タスクタイプ**: TDD / **推定工数**: 4h / **フェーズ**: Phase 2 - 探索コンポーネント
- **作成日**: 2026-07-03
- **前工程ノート**: `docs/implements/m1-hypothesis-search/TASK-0003/note.md`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書 (interfaces.py) を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測で確定した
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

> 本タスクは「質問しない・推奨案で確定」方針のため、判断が要る箇所は**推奨案を本文で確定**し、根拠と信頼性レベルを付す。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 1 つの候補相のシミュレートピーク位置列 (`candidate_peaks`) と観測ピーク列 (`observed_peaks`) を突き合わせ、位置一致に基づく **マッチングスコア `MatchResult`** を計算する。加えて、複数候補のマッチ結果を集約し、どの仮説相でも説明できない **未マッチ観測ピーク**・観測に現れない **extra 計算ピーク**・**未知相フラグ** を構造化した `UnmatchedPeakReport` を出力する。
- 🔵 **解決する問題**: 木探索でノードを精密化する前に、候補相が観測パターンをどれだけ説明するかを軽量に事前評価し、無駄な精密化を減らす (枝刈りの事前指標)。探索終了時には観測に残る未説明ピークを可視化し、候補集合の不足 (未知相) を利用者に通知する。
- 🟡 **想定ユーザー**: 直接の呼び出し元は上位の木探索エンジン `HypothesisTreeSearch` (TASK-0004+)。`match_score` の出力は `dynamic_threshold` による枝刈り (TASK-0004) と `SearchResult.unmatched` (TASK-0006) に消費される。エンドユーザーは粉末回折の相同定を行う解析者。
- 🔵 **システム内での位置づけ**: `src/tsumugin/search/matcher.py` (新規)。レイヤ分離アーキテクチャの探索コンポーネント層に属する純関数 + frozen 値オブジェクト。前段 `search/peaks.py` (`Peak`/`find_peaks`, TASK-0002) の出力を入力とし、後段 `search/pruning.py`・`search/tree.py` に結果を渡す。GSAS-II 非依存・scipy 非依存で、numpy のみのプレーン環境で完結する。
- **参照したEARS要件**: REQ-002 (FR-111), REQ-005 (FR-117), REQ-106, EDGE-003
- **参照した設計文書**: `docs/design/m1-hypothesis-search/interfaces.py` (`search/matcher.py` 節: `MatchResult` / `match_score` / `UnmatchedPeakReport`), `SearchConfig.match_tol_deg=0.15`

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 `match_score` — 1 候補相のマッチング (🔵 FR-111)

**入力** (interfaces.py の契約 🔵):
- `candidate_peaks: Sequence[Peak]` — 候補相のシミュレートピーク列。`Peak(position: float, height: float)`。位置は 2θ (度)。生成元は `SimulatedBackend.peak_positions()` (位置のみ返す) を `Peak` に包む。🔵
- `observed_peaks: Sequence[Peak]` — 観測ピーク列。`find_peaks()` (TASK-0002) の出力を渡す。`position` 昇順の不変タプルを想定。🔵
- `tol_deg: float = 0.15` (キーワード専用) — 位置一致許容幅 (度)。`SearchConfig.match_tol_deg` 既定と一致。🟡

**候補 index の扱い (要判断 → 推奨案で確定 🟡)**:
- 設計上 `MatchResult.candidate_index` は必要だが interfaces.py の `match_score` 引数には現れない。**推奨案: `match_score` にキーワード専用引数 `candidate_index: int = 0` を追加**し、呼び出し側 (木探索の候補ループ) が採番して渡す。単体テストでは既定 0 で検証可能。これにより関数純度と `MatchResult` の完全性を両立する。🟡

**出力** `MatchResult` (frozen dataclass 🔵):
- `candidate_index: int` — 入力で渡された候補相の index。🔵
- `score: float` — [0,1]。**候補ピーク一致率と観測強度被覆率の等重み平均** (下記スコア定義)。🟡 (等重み配分は設計 D の推測)
- `matched_observed: tuple[int, ...]` — マッチが成立した **観測ピークの index** を昇順で。🔵 (FR-117 用)
- `unmatched_candidate: tuple[float, ...]` — tol_deg 内に観測相手が無い **候補ピーク位置 (float, 度)** を昇順で (extra 計算ピーク)。🔵

**スコア定義 (設計 D 🟡, note.md §4 に一致)**:
```
score = 0.5 · match_rate + 0.5 · intensity_coverage
  match_rate         = (tol_deg 以内で観測にマッチした候補ピーク数) / (候補ピーク総数)
  intensity_coverage = (マッチした観測ピークの height 合計) / (全観測ピークの height 合計)
```
- 値域 [0,1]。分母 0 (候補 0 or 観測 0) は該当項を 0 とし、結果 `score=0.0` に縮退。🟡
- 強度被覆率は **観測側の height** で算出する (観測強度の説明割合を測る指標)。候補側 `Peak.height` はスコアに用いない。🟡

### 2.2 `unmatched_peaks` — 複数候補の集約 (🔵 FR-117 / REQ-005)

**入力 (要判断 → 推奨案で確定 🟡)**: interfaces.py に `unmatched_peaks()` のシグネチャは無い (タスクで新規命名)。**推奨シグネチャ**:
```python
def unmatched_peaks(
    match_results: Sequence[MatchResult],
    observed_peaks: Sequence[Peak],
    *,
    high_r_flag: bool = False,   # 全仮説高 R のとき True (REQ-106)
) -> UnmatchedPeakReport: ...
```
- `match_results` — 各候補相の `match_score` 結果列。全結果の `matched_observed` の和集合が「説明済み観測 index」。🟡
- `observed_peaks` — 元の観測ピーク列 (未マッチ観測ピークを `Peak` 実体として復元するために必要)。🟡
- `high_r_flag` — 呼び出し側 (木探索) が全仮説高 R 値を判定して渡す (REQ-106 の一因)。🟡

**出力** `UnmatchedPeakReport` (frozen dataclass 🔵):
- `unmatched_observed: tuple[Peak, ...]` — どの候補相の `matched_observed` にも含まれない観測ピーク。**位置と強度を保持**した `Peak` 実体で、位置昇順。🔵
- `extra_calculated: tuple[float, ...]` — いずれかの候補で観測に現れない計算ピーク位置 (各 `MatchResult.unmatched_candidate` を集約)。位置昇順・重複排除して返す。🔵
- `unknown_phase_flag: bool` — **`unmatched_observed` が非空、または `high_r_flag=True` のとき True**。🔵 (FR-117 / REQ-106)

### 2.3 入出力の関係・データフロー

- `find_peaks(2θ, intensity)` → `observed_peaks` → 各候補で `match_score(candidate_peaks_i, observed_peaks)` → `MatchResult_i` 群 → `unmatched_peaks([MatchResult_i], observed_peaks)` → `UnmatchedPeakReport`。🔵
- 決定論性: 同一入力・同一設定で戻り値がビット同一 (タプル順・スコア値とも)。🔵

- **参照したEARS要件**: REQ-002 (FR-111), REQ-005 (FR-117), REQ-106
- **参照した設計文書**: `interfaces.py` の `MatchResult` / `match_score` / `UnmatchedPeakReport` / `Peak`, `SearchConfig.match_tol_deg`; `src/tsumugin/search/peaks.py` (`find_peaks`), `src/tsumugin/backends/simulated.py` (`peak_positions`)

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (NFR-102 / REQ-403)**: 乱数を一切使わない。tol_deg 境界の両側判定・貪欲一致の走査順・戻りタプル順を固定 (位置昇順推奨)。同一入力の 2 回実行でビット同一。
- 🔵 **貪欲一致の重複防止**: 「1 観測ピークは高々 1 候補ピークにマッチ」等の重複防止規則を明文化し、順序依存を排除する。**推奨: 候補ピークを位置昇順に走査し、各候補について tol_deg 内で最近傍かつ未使用の観測ピークを 1 つだけ確保する**。これによりマッチ本数が入力順に依存しない。🟡
- 🔵 **例外を投げない (EDGE-003 / M0 規約「失敗は縮退結果へ」)**: 候補 0・観測 0・全 extra・全未マッチのいずれでも raise せず、`score=0.0` / 空タプル / 適切な `unknown_phase_flag` に縮退する。
- 🔵 **numpy のみ・scipy 非依存・GSAS-II 非依存**: プレーン環境で完結。pytest の `gsas` マーカー不要。
- 🔵 **不変・非破壊 (P2 / REQ-402)**: `MatchResult` / `UnmatchedPeakReport` は frozen dataclass。削除・上書き API を作らない。純関数中心。
- 🟡 **パフォーマンス (NFR-002 / note.md)**: 事前枝刈り指標として軽量計算に留め、O(候補数 × 観測数) 程度の走査で実装 (精密化前の軽量指標)。
- 🔵 **型注釈必須・命名規約**: `any` 回避。関数/変数 `snake_case`、クラス/型 `PascalCase`。日本語 docstring 可、`MatchResult`↔FR-111 / `UnmatchedPeakReport`↔FR-117 を docstring に紐づける。
- 🔵 **公開シンボル集約**: `src/tsumugin/search/__init__.py` の `__all__` (現状 `["Peak", "find_peaks"]`) に `MatchResult` / `match_score` / `UnmatchedPeakReport` / `unmatched_peaks` を追記する。
- 🔵 **Lint**: `uvx ruff check src tests` (line-length 100, target py312) を通す。
- 🟡 **Dara 教訓 (REQ-405)**: マッチングスコアは候補の事前評価/枝刈りに使うが、単独で候補を恒久除外しない (最終判断は evidence)。本タスクは値を返すのみで除外判断は行わない。

- **参照したEARS要件**: NFR-102, NFR-002, REQ-402, REQ-403, REQ-405, EDGE-003
- **参照した設計文書**: `interfaces.py` (frozen dataclass 方針), `CLAUDE.md` (規約・不変条件), `pyproject.toml` (ruff/pytest 設定), `src/tsumugin/search/__init__.py`

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

- **一致相 vs 不一致相 (TC-002-01)**: `simulate(phases)` + `find_peaks` で観測ピークを作り、真の相の `peak_positions` を `Peak` に包んで `match_score` に渡すと、ピーク位置がずれた別相よりスコアが大きくなる。→ 完了条件「一致する相のスコア > 一致しない相のスコア」。🔵
- **matched / unmatched の内容 (FR-117)**: マッチ成立で `matched_observed` に対応観測 index が昇順で入り、観測相手の無い候補位置が `unmatched_candidate` に入る。🔵
- **未マッチ集約 (TC-005-01)**: 真の構成に「候補に無い相」を混ぜた観測で `unmatched_peaks` を呼ぶと、未説明の観測ピークが **位置・強度付き** `Peak` で報告され `unknown_phase_flag=True`。🔵
- **完全説明 (TC-005-02)**: 観測を全候補で説明できる場合、`unmatched_observed` は空・`extra_calculated` は空 (または extra のみ)・`unknown_phase_flag=False`。🔵

### 4.2 エッジ・境界・エラーケース

- 🔵 **EDGE (候補ゼロ)**: `candidate_peaks=()` → `score=0.0`、`matched_observed=()`、`unmatched_candidate=()`、例外なし。TC-E01 系の基盤挙動。
- 🔵 **EDGE-003 (観測ゼロ)**: `observed_peaks=()` → `score=0.0`、全候補が extra 扱い (`unmatched_candidate` に全候補位置)、`matched_observed=()`、例外なし。
- 🟡 **値域確認**: 任意入力で `0.0 <= score <= 1.0`。
- 🟡 **tol_deg 境界 (完了条件)**: ちょうど tol_deg の位置ずれで両側判定が決定論的・安定。**推奨: 判定を `|Δ2θ| <= tol_deg` (閉区間) とし境界を「マッチ」に含める**。浮動小数の等値ぶれを避けるため境界の扱いを一意に固定する。🟡
- 🔵 **REQ-106 (全仮説高 R)**: `high_r_flag=True` が渡されたら `unmatched_observed` が空でも `unknown_phase_flag=True` を強制。
- 🟡 **フラットパターン (EDGE-003 / TC-005-03)**: `find_peaks` が空を返す上流ケースでは observed が空 → `unmatched_observed` 空・`unknown_phase_flag` は `high_r_flag` に従う (未知相フラグは立てず、上位で警告)。

- **参照したEARS要件**: EDGE-003, REQ-106
- **参照した受け入れ基準**: TC-002-01, TC-005-01, TC-005-02, TC-005-03, TC-E01, TC-E02
- **参照した設計文書**: `interfaces.py`; `src/tsumugin/backends/simulated.py` (`simulate` / `peak_positions`), `src/tsumugin/search/peaks.py` (`find_peaks`)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 相同定における「観測に説明されないピーク (未知相) の可視化」および「精密化前の候補事前評価」(user-stories.md / REQ-002・005 由来)
- **参照した機能要件**: REQ-002 (FR-111 マッチングスコア), REQ-005 (FR-117 未マッチ/extra ピークの構造化出力), REQ-106 (全仮説高 R で未知相フラグ強制)
- **参照した非機能要件**: NFR-102 / REQ-403 (決定論・ビット同一), NFR-002 (組合せ爆発回避=軽量指標), REQ-402 (非破壊), REQ-405 (Dara 教訓: 恒久除外しない)
- **参照したEdgeケース**: EDGE-003 (観測ピーク無し→スコア全ゼロ), EDGE-001 相当 (候補ゼロの縮退)
- **参照した受け入れ基準**: TC-002-01 (一致相 > 不一致相 🔵), TC-005-01 (未マッチ観測を位置・強度付き報告 + flag True 🔵), TC-005-02 (完全説明で空・flag False 🔵), TC-005-03 (フラット縮退 🟡)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m1-hypothesis-search/architecture.md` (探索コンポーネント層・レイヤ分離・純関数構成)
  - **型定義**: `docs/design/m1-hypothesis-search/interfaces.py` (`search/matcher.py` 節: `MatchResult` / `match_score` / `UnmatchedPeakReport`, `search/peaks.py` の `Peak`, `SearchConfig.match_tol_deg=0.15`)
  - **前提実装**: `src/tsumugin/search/peaks.py` (`Peak` / `find_peaks`, TASK-0002 完了), `src/tsumugin/backends/simulated.py` (`peak_positions` / `simulate`), `src/tsumugin/search/__init__.py` (`__all__` 追記対象)

---

## 6. 実装・テスト対象ファイル

- **実装 (新規)**: `src/tsumugin/search/matcher.py` — `MatchResult`, `match_score()`, `UnmatchedPeakReport`, `unmatched_peaks()` 🔵
- **公開集約 (更新)**: `src/tsumugin/search/__init__.py` — `__all__` に 4 シンボル追記 🔵
- **テスト (新規)**: `tests/test_matcher.py` — `tests/test_peaks.py` / `tests/test_simulated_backend.py` の書式に準拠 🔵
  - import: `from tsumugin.search.matcher import MatchResult, match_score, UnmatchedPeakReport, unmatched_peaks` (未実装のため collection 時 import 失敗 → Red 成立)
  - モジュールレベルヘルパ `_grid()` / `_backend()` / `_phase()` を既存テストから流用

---

## 7. 判断が必要だった箇所の確定事項（質問しない方針での決定）

| # | 論点 | 確定した推奨案 | 信頼性 |
|---|------|----------------|--------|
| 1 | `candidate_index` の供給 (interfaces に引数無し) | `match_score(..., *, candidate_index: int = 0)` を追加し呼び出し側で採番 | 🟡 |
| 2 | `unmatched_peaks()` のシグネチャ (interfaces に無し) | `unmatched_peaks(match_results, observed_peaks, *, high_r_flag=False) -> UnmatchedPeakReport` | 🟡 |
| 3 | スコア重み配分 | 候補一致率と観測強度被覆率の **等重み平均 (0.5/0.5)** | 🟡 |
| 4 | 強度被覆率の height 出典 | **観測側 height** で算出 (候補 height はスコア不使用) | 🟡 |
| 5 | tol_deg 境界の扱い | `|Δ2θ| <= tol_deg` の **閉区間** (境界はマッチ) | 🟡 |
| 6 | 貪欲一致の重複防止 | 候補を位置昇順走査、1 候補は未使用の最近傍観測 1 つを確保 (1:1) | 🟡 |
| 7 | `unknown_phase_flag` の条件 | `unmatched_observed` 非空 **or** `high_r_flag=True` | 🔵 |
| 8 | 空入力の扱い | 例外を投げず `score=0.0` / 空タプルに縮退 (EDGE-003) | 🔵 |

---

## 8. 品質判定

- **要件の曖昧さ**: なし (判断点は §7 で推奨案を確定済み)
- **入出力定義**: 完全 (型・値域・縮退挙動・タプル順まで規定)
- **制約条件**: 明確 (決定論・numpy 限定・非破壊・例外禁止)
- **実装可能性**: 確実 (前提実装 `Peak`/`find_peaks`/`peak_positions` は完了済み、numpy のみで実装可能)
- **信頼性レベル分布**: 🔵 = 大部分 (構造・契約・要件対応) / 🟡 = チューニング的判断点 (§7 の 5 点=重み・境界・貪欲規則・index/シグネチャ) / 🔴 = 0

**総合品質判定: ✅ 高品質**（骨格・契約・受け入れ基準は仕様/設計に直接依拠。残る 🟡 は実装時較正で確定する既定値のみ）
