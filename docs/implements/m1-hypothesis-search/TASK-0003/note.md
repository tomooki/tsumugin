# TASK-0003 PeakMatcher (マッチングスコア / 未マッチピーク) — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク概要
`MatchResult` frozen dataclass と `match_score(candidate_peaks, observed_peaks, *, tol_deg=0.15)`、
`UnmatchedPeakReport` frozen dataclass と未マッチ抽出関数 `unmatched_peaks()` を実装する
（TDD, 推定 4h, Phase 2 探索コンポーネント, 信頼性 🔵 FR-111/117）。
スコア = **候補ピーク一致率と観測強度被覆率の等重み平均**（設計 D 参照 🟡）。候補ピークは
backend の `peak_positions()`（`SimulatedBackend` 実装済み）から生成する。前提の観測ピーク抽出
`Peak`/`find_peaks`（TASK-0002）は `src/tsumugin/search/peaks.py` に実装済み。

- 対象実装: `src/tsumugin/search/matcher.py`（新規）
- テスト: `tests/test_matcher.py`（新規）
- 参照元: `docs/tasks/m1-hypothesis-search/TASK-0003.md`, `docs/tasks/m1-hypothesis-search/overview.md`

### 完了条件（TASK-0003.md）
- [ ] 一致する相のスコア > 一致しない相のスコア 🔵 *TC-002-01*
- [ ] score ∈ [0,1]、空入力（候補 or 観測ピークなし）で 0.0 🟡
- [ ] matched_observed / unmatched_candidate (extra) が正しい index / 位置を返す 🔵 *FR-117*
- [ ] 未マッチ観測ピークが位置・強度付きで報告される 🔵 *TC-005-01/02*
- [ ] 許容 tol_deg の境界で両側判定が決定論的 🟡

---

## 1. 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12（uv 管理, src layout + hatchling）
- **コアライブラリ**: numpy >= 1.26 のみ（本タスクは scipy 不使用・GSAS-II 非依存 = プレーン環境で完結）
- **テスト**: pytest >= 8 + pytest-cov（`uv run pytest`）
- **Lint**: `uvx ruff check src tests`（line-length 100, target py312）

### アーキテクチャパターン
- レイヤ分離（Interfaces / Agent / Orchestrator / Workers / Data）。境界は `typing.Protocol` で抽象化
- 値オブジェクトは **frozen dataclass** による不変表現（`MatchResult` / `UnmatchedPeakReport` もこれに準拠）
- 決定論優先（同一入力 → 同一出力, NFR-102）。乱数を一切使わない。純関数中心

- 参照元: `CLAUDE.md`, `docs/spec/m1-hypothesis-search/note.md`, `pyproject.toml`

## 2. 開発ルール

### プロジェクト固有ルール（必須）
- **TDD 厳守**: Red（失敗テスト）→ Green（最小実装）→ Refactor。テストなしの実装コミット禁止
- **タスク毎コミット**: テスト green ごとに 1 コミット（※本ノート生成では commit しない）
- **モデル指定**: kairo/dev の全エージェント（サブエージェント含む）を Opus で実行
- **成果物の保存先**: 要件・設計・タスクは `docs/` 配下

### コーディング規約
- 命名: 変数/関数 `snake_case`、クラス/型 `PascalCase`、定数 `UPPER_SNAKE`、ファイル `snake_case`
- **型注釈必須**（`any` 回避）。frozen dataclass 基本、更新は非破壊（`with_updates()` / `replace()`）
- 日本語 docstring 可。FR/NFR/REQ 番号を docstring に紐づける慣習
- 公開シンボルは各パッケージ `__init__.py` に集約。
  `src/tsumugin/search/__init__.py` は現状 `__all__ = ["Peak", "find_peaks"]`
  — 本タスクで `MatchResult` / `match_score` / `UnmatchedPeakReport` / `unmatched_peaks` を追記する

- 参照元: `CLAUDE.md`（開発ワークフロー/規約/不変条件）, `docs/spec/m1-hypothesis-search/note.md`,
  `src/tsumugin/search/__init__.py`

## 3. 関連実装（本タスクの土台）

### 前提実装 1: 観測ピーク抽出 `Peak` / `find_peaks`（TASK-0002 完了済み）
`src/tsumugin/search/peaks.py` に実装済み。`match_score` の第 2 引数 `observed_peaks` は本関数の出力を消費する。
- `Peak(position: float, height: float)` — frozen dataclass。`position`=2θ(度), `height`=強度。
  matcher の入出力（候補・観測ピーク）は共にこの `Peak` 型を単位とする。
- `find_peaks(two_theta, intensity, *, min_height_frac=0.05) -> tuple[Peak, ...]`
  局所極大 + 高さ閾値。`position` 昇順の不変タプル。フラット/全ゼロは空タプルに縮退（例外化しない）。

### 前提実装 2: 候補ピーク生成元 `SimulatedBackend.peak_positions`（実装済み）
`src/tsumugin/backends/simulated.py`。候補ピーク（`candidate_peaks: Sequence[Peak]`）はここから生成する。
- `peak_positions(phase, two_theta) -> list[float]` — 指定 2θ 範囲内の反射の **2θ 位置（度）のみ** を返す
  （高さは返さない）。→ 候補 `Peak` の `height` はテスト側で一定値等を与える設計判断が必要（要件は位置一致主体）。
  重要: `match_score` の第 1 引数は `Sequence[Peak]` 契約なので、テストで `position` を `Peak` に包んで渡す。
- `simulate(phases, two_theta) -> np.ndarray` — ガウシアン重ね合わせの合成強度。
  観測側パターン生成に使い、`find_peaks` で観測 `Peak` を得る（一致テストの教師データ）。
- 既定反射 `_DEFAULT_HKL`=(100)(110)(111)(200)(210)(211)、既定波長 λ=1.5406Å、FWHM 既定 0.2°。
  ピーク中心 `2θ = 2·asin(λ/2d)`、`1/d² = h²/a² + k²/b² + l²/c²`（直方近似）。

### 参考パターン（M0 由来の設計原則）
- **失敗は例外でなく縮退結果へ**: 空入力（候補 0 or 観測 0）は raise せず score=0.0 / 空タプルを返す
  （find_peaks の EDGE-003 縮退と同一思想）。TC-E01（候補ゼロ）系の基盤挙動。
- **決定論**（NFR-102/REQ-403）: 乱数不使用、tol_deg 境界を含め判定順・戻り順を固定（位置昇順推奨）。
- 貪欲一致は「1 観測ピークは高々 1 候補ピークにマッチ」等の重複防止規則を決め、順序依存を排除して決定論を守る。

- 参照元: `src/tsumugin/search/peaks.py`, `src/tsumugin/backends/simulated.py`
  （`peak_positions` / `simulate` / `_d_spacing` / `_DEFAULT_HKL`）, `tests/test_peaks.py`,
  `tests/test_simulated_backend.py`

## 4. 設計文書（interfaces.py の契約）

### `search/matcher.py` の契約（`docs/design/m1-hypothesis-search/interfaces.py`）
```python
@dataclass(frozen=True)
class MatchResult:                       # 1 候補相のマッチング結果 🔵 FR-111
    candidate_index: int                 # 🔵
    score: float                         # [0,1]。候補一致率と観測強度被覆率の等重み平均 🟡
    matched_observed: tuple[int, ...]    # マッチした観測ピーク index 🔵 FR-117 用
    unmatched_candidate: tuple[float, ...]  # 観測に無い計算ピーク位置 (extra) 🔵 FR-117

def match_score(candidate_peaks: Sequence[Peak], observed_peaks: Sequence[Peak],
                *, tol_deg: float = 0.15) -> MatchResult: ...

@dataclass(frozen=True)
class UnmatchedPeakReport:                # 未マッチピークの構造化出力 🔵 FR-117 (REQ-005)
    unmatched_observed: tuple[Peak, ...]  # どの仮説相でも説明できない観測ピーク 🔵
    extra_calculated: tuple[float, ...]   # 観測に現れない計算ピーク位置 🔵
    unknown_phase_flag: bool              # 🔵 FR-117/REQ-106
```

### スコア定義（設計 D 🟡）と契約上の要点
- **score = 0.5·(候補ピーク一致率) + 0.5·(観測強度被覆率)** の等重み平均。値域 [0,1]。
  - 候補一致率 = tol_deg 以内で観測にマッチした候補ピーク数 / 候補ピーク総数。
  - 観測強度被覆率 = マッチした観測ピークの height 合計 / 全観測ピークの height 合計。
  - 空入力（分母 0）は 0.0 に縮退。→ score が両側の被覆を反映するので TC-002-01（一致相 > 不一致相）を満たす。
- `candidate_index` は `match_score` 呼び出し側が渡す候補相の index（設計上は候補ループで採番）。
  interfaces の引数には現れないため、実装で index 引数を足す or 呼び出し側で採番する設計判断が要る（🟡）。
- `matched_observed` = マッチ成立した **観測ピーク** の index 昇順タプル。
  `unmatched_candidate` = tol_deg 内に観測相手が無い **候補ピーク位置(float)** タプル（extra 計算ピーク）。
- `unmatched_peaks()`（interfaces に関数シグネチャ無し・タスクで新規命名）は複数候補の一致結果を集約し、
  全候補で説明されない観測ピーク（`unmatched_observed`）と extra 計算ピーク（`extra_calculated`）を
  `UnmatchedPeakReport` にまとめる。`unknown_phase_flag` は未マッチ観測ピーク有り or 全仮説高 R（REQ-106）で True。

### 要件・受け入れ基準の対応
- REQ-002（FR-111）: 各候補相のシミュレートピーク位置と観測ピークのマッチングスコア（ノード評価の事前指標）。
- REQ-005（FR-117）: 探索終了時、未マッチ観測 / extra 計算ピークを `UnmatchedPeakReport`（位置・強度・未知相フラグ）で出力。
- REQ-106: 全仮説が高 R 値のとき未知相フラグを強制表示（`unknown_phase_flag` の一因）。
- 対応 AC: **TC-002-01**（一致相スコア > 不一致相スコア 🔵）、**TC-005-01**（候補にない相を混ぜたデータで
  未マッチ観測ピークが位置・強度付き報告 + `unknown_phase_flag=True` 🔵）、**TC-005-02**（完全説明で未マッチ空・フラグ False 🔵）。
  下流: TC-002-02（`dynamic_threshold` による枝刈り, TASK-0004+）が本スコアを消費する。

- 参照元: `docs/design/m1-hypothesis-search/interfaces.py`（search/matcher.py 節, SearchConfig.match_tol_deg=0.15）,
  `docs/spec/m1-hypothesis-search/requirements.md`（REQ-002/005/106）,
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md`（TC-002-01, TC-005-01/02）,
  `docs/tasks/m1-hypothesis-search/TASK-0003.md`

## 5. テスト関連情報

- **フレームワーク/設定**: pytest。設定は `pyproject.toml [tool.pytest.ini_options]`
  （`testpaths=["tests"]`, `addopts="-q"`, marker `gsas`）。本タスクは gsas マーカー不要（純 numpy・GSAS 非依存）。
- **ディレクトリ/命名**: 実装ファイルと 1:1 の `tests/test_*.py`。本タスクは `tests/test_matcher.py` を新規作成。
- **既存テストの書式**（`tests/test_peaks.py` / `tests/test_simulated_backend.py` を範とする）:
  - モジュールレベルヘルパ: `_phase(a, scale, ref)`（`PhaseInstance(phase_ref, LatticeParams(a,a,a), scale)`）,
    `_grid()`=`np.arange(15.0, 80.0, 0.02)`, `_backend()`=`SimulatedBackend(peak_fwhm=0.2)`。
  - 数値比較は `pytest.approx(..., rel=/abs=)`。決定論テストは同一入力の 2 回実行で完全一致を確認。
  - import: `from tsumugin.search.matcher import MatchResult, match_score, UnmatchedPeakReport, unmatched_peaks`
    （未実装のため collection 時 import 失敗 → Red が成立）。
- **推奨テストケース（TDD Red で作る）**:
  - 一致相 vs 不一致相: 一致する候補相の score が、ピーク位置がずれた候補相の score より大（**TC-002-01**）。
    観測は `simulate`+`find_peaks`、候補は `peak_positions` を `Peak` に包んで生成。
  - score ∈ [0,1] の値域確認、および空入力（候補 0 / 観測 0）で score=0.0・例外なし。
  - `matched_observed`（観測 index）/ `unmatched_candidate`（extra 位置）が正しい要素を返す（FR-117）。
  - `unmatched_peaks()`: 候補に無い相を混ぜた観測で未マッチ観測ピークが位置・強度付き報告 + flag True（**TC-005-01**）、
    完全説明データで未マッチ空・flag False（**TC-005-02**）。
  - tol_deg 境界（ちょうど tol の位置ずれ）で両側判定が決定論的・安定。
- **conftest**: `tests/conftest.py` あり（共有フィクスチャ確認先。現状 matcher 専用の準備は不要）。
- E2E/UI 設定: 本タスクでは対象外。

- 参照元: `pyproject.toml`, `tests/test_peaks.py`, `tests/test_simulated_backend.py`, `tests/conftest.py`

## 6. 注意事項

### 技術的制約
- **numpy のみ**で実装（scipy 非依存・GSAS-II 非依存）。マッチングは位置差の tol_deg 判定 + 貪欲対応で十分。
- **決定論必須（NFR-102/REQ-403）**: 乱数不使用。tol_deg 境界の両側判定・戻りタプル順を固定（位置昇順推奨）。
  貪欲一致の走査順を固定し「1 観測ピークは高々 1 候補にマッチ」等の重複防止規則を明文化する。
- **空/エッジ**: 候補 0・観測 0・全 extra・全未マッチのいずれでも例外を出さず、
  score=0.0 / 空タプル / 適切な `unknown_phase_flag` に縮退する（M0 由来「失敗は縮退結果へ」）。
- **候補ピークの height**: `peak_positions` は位置のみ返す。候補 `Peak.height` の与え方（一定値 or simulate 由来）は
  設計判断。強度被覆率は **観測側** の height で計算する点に注意（観測強度の説明割合を測る指標）。
- 型注釈必須・frozen dataclass・日本語 docstring に FR/REQ 番号紐づけ（`MatchResult`↔FR-111, `UnmatchedPeakReport`↔FR-117）。

### 非破壊性・パフォーマンス上の注意
- **P2 非破壊性**: 本タスクは純関数 + frozen dataclass のみで、削除・上書き API を作らない方針に自然合致。
- スコアは木探索の **事前枝刈り指標**（FR-111）— 精密化前の軽量計算に留め、O(候補×観測) 程度の走査で実装する。
- Dara 教訓: マッチングスコアは候補の事前評価/枝刈りに使うが、単独で候補を恒久除外しない（最終判断は evidence）。

- 参照元: `CLAUDE.md`（実装上の不変条件）, `docs/design/m1-hypothesis-search/interfaces.py`,
  `docs/spec/m1-hypothesis-search/note.md`, `docs/tasks/m1-hypothesis-search/TASK-0003.md`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m1-hypothesis-search/TASK-0003.md`, `docs/tasks/m1-hypothesis-search/overview.md`
- 仕様: `docs/spec/m1-hypothesis-search/note.md`, `.../requirements.md`, `.../acceptance-criteria.md`
- 設計: `docs/design/m1-hypothesis-search/interfaces.py`（search/matcher.py 契約）
- ルール: `CLAUDE.md`（`AGENTS.md` / `docs/rule/` は不在 — 追加ルールは CLAUDE.md に集約）
- 前提実装: `src/tsumugin/search/peaks.py`（TASK-0002）, `src/tsumugin/backends/simulated.py`（peak_positions）,
  `src/tsumugin/search/__init__.py`, `src/tsumugin/model/phase.py`
- テスト（雛形）: `tests/test_peaks.py`, `tests/test_simulated_backend.py`, `tests/conftest.py`, `pyproject.toml`

**注意**: 本ノート内のファイルパスはすべてプロジェクトルートからの相対パスで記載。
