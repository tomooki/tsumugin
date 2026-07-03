# TASK-0005 Jaccard クラスタリング + FoM 代表選出 + Jenks natural breaks — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク要約
`src/tsumugin/search/clustering.py` に以下 4 シンボルを実装する (FR-114 / FR-116, REQ-103 / REQ-104):
- `PhaseCandidate(phase: PhaseInstance, delta_u: float = 0.0, label: str | None = None)` — frozen dataclass。候補相 + 探索メタ
- `ClusterResult(representative: int, members: tuple[int, ...])` — frozen dataclass。代表 index (FoM 最大) と クラスタ全 index。**代表以外は代替解として `members` に保持し削除しない** (REQ-103)
- `jaccard_clusters(peak_sets, fits, delta_us, *, similarity_threshold=0.85, bin_width_deg=0.2) -> tuple[ClusterResult, ...]`
  — ピーク位置を `bin_width_deg` で bin 化した集合の **Jaccard 類似** で union-find クラスタリングし、各クラスタ内で **FoM = 1/((1−fit)+ΔU)** 最大の候補を代表に選ぶ純関数
- `jenks_breaks(values, *, n_classes=2) -> tuple[float, ...]` — 1 次元 Jenks natural breaks の **境界値** を DP で返す (numpy 可、外部ライブラリ非依存)

- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 2 探索コンポーネント
- **主要実装**: `src/tsumugin/search/clustering.py` (新規)
- **テスト**: `tests/test_clustering.py` (新規)
- **依存**: 前提 TASK-0003 (matcher.py 完了) / 後続 TASK-0006・0007 (木探索コア・良好解抽出が本関数を利用)
- **信頼性**: 🔵 6 / 🟡 1 (契約・FoM 式・完了条件は FR-114/116 に依拠、代表同点タイ処理規則のみ 🟡)
- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0005.md`, `docs/tasks/m1-hypothesis-search/overview.md`

---

## 1. 技術スタック
- **言語**: Python >= 3.12 (CPython)。コア依存は **numpy >= 1.26 のみ**。**scipy / jenkspy / scikit-learn は非依存** — Jenks natural breaks は自前 DP で実装する (外部クラスタリングライブラリを追加しない)
- **パッケージマネージャー**: uv 0.9.x (src layout + hatchling)。テスト実行 `uv run pytest`
- **アーキテクチャ**: レイヤ分離 + frozen dataclass 値オブジェクト。本モジュールは `search/` パッケージの**純関数 + 値オブジェクト**で、`peaks.py` / `matcher.py` / `pruning.py` と同列 (状態を持たない)
- **参照元**: `pyproject.toml`, `docs/spec/m1-hypothesis-search/note.md` (§技術スタック), `docs/design/m1-hypothesis-search/architecture.md`

## 2. 開発ルール
- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしのコミット禁止
- **決定論 (NFR-102 / REQ-403)**: 同一入力でビット同一。クラスタ順・代表選出を一意規則で固定する。**FoM 同点は index 小優先** (完了条件6 🟡)。bin 化・union-find の走査順を入力順に依存させない
- **非破壊性 (P2 / NFR-101 / Dara 教訓)**: 代替解を**除外しない**。代表以外は `ClusterResult.members` に保持 (候補除外は禁止、降格のみ)
- **失敗の非例外化 (M0 規約)**: ドメイン的縮退 (空入力・全同一) は例外でなく縮退値/自然な結果で表現する
- **命名**: 関数/変数 snake_case、クラス/型 PascalCase、定数 UPPER_SNAKE。型注釈必須 (`any` 回避)、キーワード専用引数は `*` で区切る
- **docstring**: 日本語可。FR/REQ 番号と 🔵🟡 信頼性レベルを紐づける慣習 (peaks.py / matcher.py 参照)
- **Lint/Format**: `uvx ruff check src tests` (line-length 100, target py312)。緑 + ruff clean で 1 コミット
- **__init__.py 公開**: 実装後 `src/tsumugin/search/__init__.py` の import と `__all__` に `ClusterResult` / `PhaseCandidate` / `jaccard_clusters` / `jenks_breaks` を**アルファベット順維持**で追加
- **参照元**: `CLAUDE.md`, `docs/spec/m1-hypothesis-search/note.md` (§開発ルール), `src/tsumugin/search/__init__.py`

## 3. 関連実装 (完了済み前提・同パッケージの範とすべきパターン)
- **`src/tsumugin/search/peaks.py`** (`Peak`, `find_peaks`, TASK-0002 完了): `Peak(position: float, height: float)` frozen dataclass。**本タスクの bin 化対象は `Peak.position` (2θ deg)**。numpy ベクトル演算による純関数・縮退ガードの範
- **`src/tsumugin/search/matcher.py`** (`match_score` / `MatchResult`, TASK-0003 完了): `MatchResult.score` が [0,1] のマッチングスコア。**`jaccard_clusters` の `fits` 引数にはこの score 列が渡される想定** (= FoM の fit)。キーワード専用引数・frozen dataclass・分母 0 の縮退・決定論的ソート (`order = sorted(...)`) の実装スタイルを踏襲
- **`src/tsumugin/search/pruning.py`** (`dynamic_threshold`, TASK-0004 完了): 縮退時 `-inf` 返却、**関数内ソートで入力順非依存**にするパターン。本タスクの決定論要件の範
- **参照パターン**: 「失敗は例外でなく縮退値/自然結果に変換」(M0 全体)、決定論のためのタイ処理固定
- **参照元**: `src/tsumugin/search/peaks.py`, `src/tsumugin/search/matcher.py`, `src/tsumugin/search/pruning.py`, `src/tsumugin/search/__init__.py`

## 4. 設計文書 (clustering.py の契約)
`docs/design/m1-hypothesis-search/interfaces.py` L103-135 の契約:
```python
@dataclass(frozen=True)
class PhaseCandidate:
    phase: PhaseInstance          # 🔵
    delta_u: float = 0.0          # hull エネルギー ΔU (eV/atom)。M1 では常に 0 🟡
    label: str | None = None      # 🟡

@dataclass(frozen=True)
class ClusterResult:
    representative: int           # 代表候補 index (FoM 最大) 🔵
    members: tuple[int, ...]      # クラスタ全 index (代表以外は代替解として保持=削除しない) 🔵

def jaccard_clusters(
    peak_sets: Sequence[Sequence[Peak]], fits: Sequence[float], delta_us: Sequence[float],
    *, similarity_threshold: float = 0.85, bin_width_deg: float = 0.2,
) -> tuple[ClusterResult, ...]:
    """ピーク位置集合の Jaccard 類似で候補をクラスタし FoM=1/((1-fit)+ΔU) で代表選出。🔵"""

def jenks_breaks(values: Sequence[float], *, n_classes: int = 2) -> tuple[float, ...]:
    """1 次元 Jenks natural breaks の境界値を返す (DP 実装, numpy)。🔵 FR-116"""
```
- **FoM (architecture.md D4 🔵)**: `FoM = 1 / ((1 − fit) + ΔU)`。fit = マッチングスコア [0,1]。M1 は hull エネルギー (FR-103) 不在のため ΔU = `PhaseCandidate.delta_u` (既定 0.0)。**delta_u が大きい候補は FoM が下がり代表になれない** (完了条件3 / FR-114 式)
- **Jaccard クラスタ (D4 上流)**: 各候補のピーク位置集合を `bin_width_deg` (既定 0.2°) で離散化 → bin index の集合を作り、**Jaccard 類似 = |A∩B|/|A∪B| ≥ similarity_threshold (既定 0.85)** の候補対を同一クラスタへ union-find で結合
- **Jenks (FR-116)**: データフロー §(7) 良好解 (低 evidence 群) クラスタ抽出に使う。1 次元 DP で群内分散和 (SDCM) 最小の分割を求め、その**境界値**を返す。`n_classes=2` 既定
- **配置 (architecture.md L36/L65)**: `tsumugin/search/clustering.py` に `jaccard_clusters(), fom(), jenks_breaks()` (REQ-103/104, FR-114/116)。データフロー §(3) Jaccard 等構造縮約
- **参照元**: `docs/design/m1-hypothesis-search/interfaces.py` (L103-135), `docs/design/m1-hypothesis-search/architecture.md` (D4 L108-114, フロー L13-16, 表 L36, ツリー L65)

## 5. テスト関連情報
- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts` に `-q`)
- **テストコマンド**: `uv run pytest` / `uv run pytest tests/test_clustering.py` / `uv run pytest --cov=tsumugin`
- **配置/命名**: 実装 1:1 対応の `tests/test_clustering.py` を**新規作成** (実装 `search/clustering.py` は未作成 → Red で import 失敗し全テスト fail)
- **書式の範**: `tests/test_matcher.py` / `tests/test_peaks.py` / `tests/test_pruning.py` — モジュールレベルヘルパ、`pytest.approx` (数値) と `==` (決定論のビット同一検証) の使い分け、`@pytest.mark.parametrize`、各テストに【テスト目的/内容/期待/信頼性レベル】コメント
- **fixture/mock**: `tests/conftest.py` は `gsas` マーカーの自動 skip のみ。**本タスクは GSAS-II 非依存** — `Peak` リストと `fits`/`delta_us` を素の `list` で直接構築でき backend 不要 (`@pytest.mark.gsas` 不要)
- **カバーすべき受け入れ基準 (acceptance-criteria.md TC-004-01〜04)**:
  - **TC-004-01** 🔵: ピーク位置がほぼ同一の 2 候補が 1 クラスタに縮約、FoM (fit) 最大が代表・他方が `members` に保持
  - **TC-004-02** 🔵: ピーク位置が異なる候補は別クラスタ (Jaccard < threshold)
  - **TC-004-03** 🔵: `jenks_breaks` が既知 2 群 (例 `[1,2,3, 100,110]`) を正しく分離
  - **TC-004-04** 🔵 (境界 / EDGE-103): 全候補同一構造 → クラスタ 1 個 (代表 1 + 代替 N−1)
  - 加えて完了条件3: **delta_u が大きい候補は FoM で代表になれない**、完了条件6 🟡: **クラスタ順・代表選出が決定論** (同点は index 小優先)
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_matcher.py`, `tests/test_peaks.py`, `tests/test_pruning.py`, `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-004 L48-54)

## 6. 注意事項
- **FoM の分母ゼロ**: `fit=1.0` かつ `delta_u=0.0` のとき `(1−fit)+ΔU = 0` → ゼロ除算。`float("inf")` へ落とす等でガードし ZeroDivisionError を出さない (inf は最大 FoM として代表選出に整合)。値の等値比較・タイは決定論規則で固定
- **決定論の要 (NFR-102/REQ-403)**: union-find の走査順・クラスタ出力順を入力順に依存させない (例: 代表/members を index 昇順で正規化、クラスタは代表 index 昇順で並べる)。FoM 同点は **index 小優先** で代表決定 (完了条件6 🟡)
- **非破壊性 (P2/NFR-101/REQ-103)**: 代替解を削除しない。全 index を `members` に保持し、代表以外も後段で参照可能にする (Dara 教訓: 候補除外はしない)
- **bin 化の意味論**: ピーク位置 (deg) を `bin_width_deg` で量子化し集合化。許容誤差内の近接ピークが同一 bin に落ちて Jaccard が上がる設計。`similarity_threshold`/`bin_width_deg` は 🟡 (実装時にテストで較正)。空ピーク集合同士の Jaccard は 0/0 → 縮退規則を決める (例: 両空は類似 1 or 別扱い、テストで確定)
- **Jenks は自前 DP**: `n_classes` 群への 1 次元分割で群内二乗偏差和 (SDCM) を最小化する DP。**入力は昇順ソートしてから**処理し、返すのは**境界値のタプル** (`n_classes=2` なら区切り 1 個中心)。既知 2 群テストで境界が両群の間に入ることを検証。外部ライブラリ (jenkspy) を追加しない
- **numpy 使用可**: 距離/集合/DP のベクトル化に numpy 可 (peaks.py と同じコア方針)。ただし公開戻り値は素の `tuple`/`int`/`float`
- **スコープ外**: 木探索 (TASK-0006) と良好解抽出 (TASK-0007) が本関数を呼ぶ。ledger への「代表選出/クラスタ理由」記録は呼び出し側の責務で本関数のスコープ外
- **参照元**: `docs/spec/m1-hypothesis-search/note.md` (§技術的制約/§注意事項), `docs/design/m1-hypothesis-search/architecture.md` (D4), `docs/tasks/m1-hypothesis-search/TASK-0005.md` (完了条件), `CLAUDE.md`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m1-hypothesis-search/TASK-0005.md`, `docs/tasks/m1-hypothesis-search/overview.md`
- 仕様: `docs/spec/m1-hypothesis-search/note.md`, `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-004)
- 設計: `docs/design/m1-hypothesis-search/interfaces.py` (clustering 契約 L103-135), `docs/design/m1-hypothesis-search/architecture.md` (D4 FoM L108-114)
- 完了済み前提実装: `src/tsumugin/search/peaks.py`, `src/tsumugin/search/matcher.py`, `src/tsumugin/search/pruning.py`, `src/tsumugin/search/__init__.py`
- テスト範/設定: `tests/test_matcher.py`, `tests/test_peaks.py`, `tests/test_pruning.py`, `tests/conftest.py`, `pyproject.toml`
- 前タスクノート (書式の範): `docs/implements/m1-hypothesis-search/TASK-0004/note.md`
- (`AGENTS.md`, `docs/rule/` は不在 — 追加ルールは `CLAUDE.md` / `docs/spec/m1-hypothesis-search/note.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
