# TASK-0004 動的枝刈り閾値 dynamic_threshold — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク要約
`dynamic_threshold(scores, *, min_candidates=4) -> float` を実装する (FR-112 / REQ-101)。
スコア**降順ソート列**の累積分布に対する**二階差分最大点 (変曲点)** で枝刈り閾値を返す。
縮退時 (候補 < min_candidates / 全同値など変曲点が定まらない) は `-inf` を返し全展開へフォールバック。
入力順に依存しない (ソートは関数内で行う) 決定論的純関数。

- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 2h
- **主要実装**: `src/tsumugin/search/pruning.py` の `dynamic_threshold()`
- **テスト**: `tests/test_pruning.py` (新規)
- **依存**: 前提 TASK-0003 (完了) / 後続 TASK-0006 (木探索コアが本関数を利用)
- **信頼性**: 🔵 3 / 🟡 2 (契約・変曲点方針は FR-112 に依拠、実装式は interview Q8 の推測)
- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0004.md`, `docs/tasks/m1-hypothesis-search/overview.md`

---

## 1. 技術スタック
- **言語**: Python >= 3.12 (CPython)。コア依存は **numpy >= 1.26 のみ** (scipy・GSAS-II 非依存)
- **パッケージマネージャー**: uv 0.9.x (src layout + hatchling)。テスト実行 `uv run pytest`
- **アーキテクチャ**: レイヤ分離 + `typing.Protocol` 抽象化。値オブジェクトは frozen dataclass。
  本関数は `search/` パッケージの**純関数** (状態を持たず、`peaks.py` / `matcher.py` と同列)
- **参照元**: `pyproject.toml`, `docs/spec/m1-hypothesis-search/note.md`

## 2. 開発ルール
- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしのコミット禁止
- **決定論 (NFR-102 / REQ-403)**: 同一入力でビット同一。**ソートは関数内**で行い入力順非依存にする (完了条件4)
- **失敗の非例外化 (EDGE / M0 規約)**: ドメイン的縮退は例外でなく `-inf` 返却で表現する
- **命名**: 関数/変数 snake_case、定数 UPPER_SNAKE。型注釈必須 (`any` 回避)、キーワード専用引数は `*` で区切る
- **docstring**: 日本語可。FR/REQ 番号と 🔵🟡 信頼性レベルを紐づける慣習 (peaks.py / matcher.py 参照)
- **Lint/Format**: `uvx ruff check src tests` (line-length 100, target py312)。緑 + ruff clean で 1 コミット
- **__init__.py 公開**: 実装後 `src/tsumugin/search/__init__.py` の import と `__all__` に `dynamic_threshold` を追加 (アルファベット順維持)
- **参照元**: `CLAUDE.md`, `docs/spec/m1-hypothesis-search/note.md` (§開発ルール), `src/tsumugin/search/__init__.py`

## 3. 関連実装 (完了済み前提・同パッケージの範とすべきパターン)
- **`src/tsumugin/search/peaks.py`** (`find_peaks`, TASK-0002 完了): numpy ベクトル演算による純関数。
  極小入力 (`size < 3`) や max<=0 を**空/縮退へ落とす**ガードのパターンが本タスクの `min_candidates` 未満 / 全同値縮退の範
- **`src/tsumugin/search/matcher.py`** (`match_score` / `unmatched_peaks`, TASK-0003 完了): キーワード専用引数・
  frozen dataclass・分母 0 の `-> 0.0` 縮退・決定論的ソートの実装スタイル。**入力 `scores` はこの `MatchResult.score` 列が渡される想定**
- **参照パターン**: 「失敗は例外でなく縮退値に変換」(M0 全体)、決定論のためのソート固定 (matcher.py の `order = sorted(...)`)
- **参照元**: `src/tsumugin/search/peaks.py`, `src/tsumugin/search/matcher.py`, `src/tsumugin/search/__init__.py`

## 4. 設計文書 (dynamic_threshold の契約)
`docs/design/m1-hypothesis-search/interfaces.py` L88-95 の契約:
```python
def dynamic_threshold(scores: Sequence[float], *, min_candidates: int = 4) -> float:
    """スコア降順の累積分布の変曲点 (二階差分最大) で枝刈り閾値を返す。
    縮退時 (全同値等) は -inf (全展開)。🔵 FR-112 (実装式は 🟡)"""
```
- **引数**: `scores: Sequence[float]` (候補相のマッチングスコア列、順不同)、`min_candidates: int = 4` (キーワード専用)
- **戻り値**: `float` の閾値。**この値未満**のスコアの相はノード展開しない (REQ-101、境界は「未満」)
- **アルゴリズム (interview Q8, 🟡)**: スコアを**降順ソート** → 累積分布 (累積和) を作り → 隣接**二階差分** `d2[i] = c[i+1]-2c[i]+c[i-1]` を計算 → **二階差分が最大 (最大曲率=変曲点)** となる位置のスコアを閾値とする
- **縮退 → `-inf`**: (a) `len(scores) < min_candidates`、(b) 全スコア同値等で変曲点が一意に定まらない/二階差分が全ゼロ。`-inf` は「どのスコアも閾値以上=全展開」を意味する
- **参照元**: `docs/design/m1-hypothesis-search/interfaces.py` (L88-95), `docs/spec/m1-hypothesis-search/interview-record.md` (Q8), `docs/spec/m1-hypothesis-search/requirements.md` (REQ-101 L48-49)

## 5. テスト関連情報
- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts="-q"`)
- **テストコマンド**: `uv run pytest` / `uv run pytest tests/test_pruning.py` / `uv run pytest --cov=tsumugin`
- **配置/命名**: 実装 1:1 対応の `tests/test_pruning.py` を**新規作成** (実装ファイル `search/pruning.py` は Red で未作成→ import 失敗で全テスト fail)
- **書式の範**: `tests/test_matcher.py` / `tests/test_peaks.py` — モジュールレベルヘルパ、`pytest.approx` (数値) と `==` (決定論のビット同一検証) の使い分け、`@pytest.mark.parametrize`、各テストに【テスト目的/内容/期待/信頼性レベル】コメント
- **fixture/mock**: `tests/conftest.py` は `gsas` マーカーの自動 skip のみ。**本タスクは GSAS-II 非依存** (`@pytest.mark.gsas` 不要)。`scores` は素の `list[float]` で直接構築でき backend 不要
- **カバーすべき受け入れ基準 (acceptance-criteria.md, TC-002-02〜04)**:
  - **TC-002-02** 🔵: 高スコア群と低スコア群が明確に分かれる入力で、閾値が両群の**間**に決まる (境界未満の相が枝刈り対象になる)
  - **TC-002-03** 🟡: 候補 **3 以下 (< min_candidates=4)** で `-inf` (枝刈り無効=全展開)
  - **TC-002-04** 🟡 (境界): **全候補同スコア**で閾値決定が破綻せず `-inf` へフォールバック
  - 加えて完了条件4 🔵: **入力順を入れ替えても同一閾値** (関数内ソートによる決定論)
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_matcher.py`, `tests/test_peaks.py`, `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (L34-41)

## 6. 注意事項
- **決定論の要 (NFR-102/REQ-403)**: 浮動小数の等値判定・タイ処理を安定させる。二階差分最大が複数タイのとき採用位置を一意規則で固定 (例: 最初/最大スコア側) し、入力順で結果が揺れないこと
- **境界セマンティクス**: REQ-101 は「スコアが閾値**未満**なら展開しない」。閾値そのものはギリギリ**展開側**に含む解釈で TC-002-02 を満たす (実装式は 🟡 なのでテストで境界を確定させる)
- **`-inf` の意味**: `float("-inf")`。全スコア >= -inf なので全展開になる。NaN や例外は返さない
- **二階差分に必要な最小点数**: 二階差分は内部点 (両隣が要る) が最低 1 つ必要 = 実質 3 点以上。`min_candidates=4` 既定はこれをカバーするが、`min_candidates` を小さく指定された場合も IndexError を出さず縮退するガードを入れる
- **numpy 使用可**: `np.sort`/`np.diff`/`np.cumsum`/`np.argmax` でベクトル化してよい (peaks.py と同じ numpy コア方針)。ただし戻り値は素の `float`
- **非破壊性 (P2/NFR-101)**: 本関数は純関数で状態変更なし。ledger への「枝刈り理由記録」は**呼び出し側 (TASK-0006 木探索コア)** の責務であり本関数のスコープ外
- **参照元**: `docs/spec/m1-hypothesis-search/note.md` (§技術的制約/§注意事項), `docs/spec/m1-hypothesis-search/requirements.md` (REQ-101/402/403), `CLAUDE.md`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m1-hypothesis-search/TASK-0004.md`, `docs/tasks/m1-hypothesis-search/overview.md`
- 仕様: `docs/spec/m1-hypothesis-search/note.md`, `.../requirements.md`, `.../acceptance-criteria.md`, `.../interview-record.md`
- 設計: `docs/design/m1-hypothesis-search/interfaces.py` (dynamic_threshold の契約 L88-95)
- 完了済み前提実装: `src/tsumugin/search/peaks.py`, `src/tsumugin/search/matcher.py`, `src/tsumugin/search/__init__.py`
- テスト範/設定: `tests/test_matcher.py`, `tests/test_peaks.py`, `tests/conftest.py`, `pyproject.toml`
- (`AGENTS.md`, `docs/rule/` は不在 — 追加ルールは `CLAUDE.md` / 上記 note.md に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
