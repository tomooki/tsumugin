# TASK-0005 Jaccard クラスタリング + FoM 代表選出 + Jenks natural breaks — TDD 要件定義書

- **機能名**: 相候補クラスタリング (phase-clustering: `jaccard_clusters` / FoM / `jenks_breaks`)
- **タスクID**: TASK-0005
- **要件名**: m1-hypothesis-search
- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 2 探索コンポーネント
- **出力ファイル**: `docs/implements/m1-hypothesis-search/TASK-0005/phase-clustering-requirements.md`
- **信頼性サマリー**: 🔵 6 / 🟡 1 — 契約・FoM 式・Jaccard 方針・完了条件は FR-114/FR-116・REQ-103/REQ-104 に依拠。代表同点タイ処理規則のみ 🟡

> **【信頼性レベル凡例】**
> - 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
> - 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
> - 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: `src/tsumugin/search/clustering.py` に 4 シンボルを実装する純関数 + 値オブジェクト群。
  (1) `PhaseCandidate` / `ClusterResult` の frozen dataclass、
  (2) `jaccard_clusters()` — 各候補相のピーク位置集合を `bin_width_deg` で bin 化し、**Jaccard 類似 |A∩B|/|A∪B| ≥ similarity_threshold** の候補対を union-find で同一クラスタに結合、各クラスタ内で **FoM = 1/((1−fit)+ΔU)** 最大の候補を代表に選ぶ (REQ-103 / FR-114)、
  (3) `jenks_breaks()` — 1 次元 Jenks natural breaks の**境界値**を DP で返す (REQ-104 / FR-116)。
- 🔵 **どのような問題を解決するか**: 等構造 (ピーク位置がほぼ同一) の候補相が探索空間に複数現れると、実質同一の仮説が重複展開され木が肥大化する。これを 1 クラスタに縮約し FoM 最大を代表に据えることで探索を効率化する。同時に、**代替解を削除せず** `members` に保持することで非破壊性 (P2 / NFR-101 / Dara 教訓) を守る。探索完了後の良好解 (低 evidence 群) 抽出には `jenks_breaks` を用いる。
- 🟡 **想定されるユーザー (呼び出し側)**: `jaccard_clusters` は TASK-0006 (木探索コア) が等構造縮約に、`jenks_breaks` は TASK-0007 (良好解抽出) が良好解クラスタ分離に用いる。いずれもエンドユーザーが直接呼ぶ関数ではない内部純関数。
- 🔵 **システム内での位置づけ**: `search/` パッケージの状態を持たない**純関数 + 値オブジェクト** (`peaks.py` / `matcher.py` / `pruning.py` と同列)。numpy コアのみ依存 (scipy / jenkspy / scikit-learn 非依存)。`peak_sets` の各要素は `peaks.py` の `Peak`、`fits` は `matcher.py` の `MatchResult.score` [0,1] 列が渡される想定。
- **参照したEARS要件**: REQ-103 (等構造の FoM 代表選出・代替解保持) 🔵、REQ-104 (Jenks 良好解抽出) 🔵、EDGE-103 (全候補同一構造) 🔵
- **参照した設計文書**: `docs/design/m1-hypothesis-search/interfaces.py` L103-135 (clustering 契約)、`docs/design/m1-hypothesis-search/architecture.md` D4 (FoM L108-114 / データフロー §(3)(7))、`docs/implements/m1-hypothesis-search/TASK-0005/note.md` §4

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 値オブジェクト 🔵 (契約は interfaces.py L103-118 に準拠)

| 型 | フィールド | 型 | 説明 |
|----|-----------|-----|------|
| `PhaseCandidate` (frozen) | `phase` | `PhaseInstance` | 候補相 🔵 |
| | `delta_u` | `float` = `0.0` | hull エネルギー ΔU (eV/atom)。M1 では常に 0 🟡 |
| | `label` | `str \| None` = `None` | 探索メタラベル 🟡 |
| `ClusterResult` (frozen) | `representative` | `int` | 代表候補 index (FoM 最大) 🔵 |
| | `members` | `tuple[int, ...]` | クラスタ全 index。代表以外は代替解として保持 — 削除しない (REQ-103) 🔵 |

### 2.2 `jaccard_clusters` の入力パラメータ 🔵

| 引数 | 型 | 制約 | 説明 |
|------|-----|------|------|
| `peak_sets` | `Sequence[Sequence[Peak]]` | 候補 index 順。各要素は `Peak` 列 (空可) | 各候補相の (計算)ピーク集合。bin 化対象は `Peak.position` (2θ deg) 🔵 |
| `fits` | `Sequence[float]` | `peak_sets` と同長・各値 [0,1] 想定 | 各候補のマッチングスコア (= FoM の fit) 🔵 |
| `delta_us` | `Sequence[float]` | `peak_sets` と同長・各値 ≥ 0 想定 | 各候補の ΔU (M1 は既定 0.0) 🔵 |
| `similarity_threshold` | `float` (`*` 専用) | 既定 `0.85` | Jaccard 類似の同一クラスタ判定閾値 🟡 実装時較正 |
| `bin_width_deg` | `float` (`*` 専用) | 既定 `0.2` | ピーク位置の離散化幅 (deg) 🟡 |

- 🔵 `similarity_threshold` / `bin_width_deg` は `*` 区切りのキーワード専用引数 (note.md §2 / interfaces.py L125-127)。
- 🔵 **入力を破壊しない** (非破壊性 P2 / NFR-101)。

### 2.3 `jaccard_clusters` の出力 🔵

- **型**: `tuple[ClusterResult, ...]`。各クラスタ 1 要素。
- **正規化**: 各 `ClusterResult.members` は **index 昇順**、`representative` はクラスタ内 FoM 最大 (同点は index 小優先)。出力タプルは**代表 index 昇順**に並べる (決定論)。🔵 (正規化規則の一部は 🟡)
- **FoM 定義 (architecture.md D4 / FR-114)**: `FoM = 1 / ((1 − fit) + ΔU)`。fit が高く ΔU が小さいほど大。**delta_u が大きい候補は FoM が下がり代表になれない** (完了条件3)。🔵

### 2.4 `jenks_breaks` の入出力 🔵 (interfaces.py L133 / FR-116)

| 引数 | 型 | 制約 | 説明 |
|------|-----|------|------|
| `values` | `Sequence[float]` | 順不同・空/少数可 | 分割対象の 1 次元数値列 (例: evidence 値) 🔵 |
| `n_classes` | `int` (`*` 専用) | 既定 `2` | 分割する群数 🔵 |

- **出力**: `tuple[float, ...]` — 群間の**境界値** (`n_classes=2` なら区切り中心 1 個)。🔵
- **アルゴリズム**: `values` を**昇順ソート**してから、`n_classes` 群への分割で群内二乗偏差和 (SDCM) を最小化する DP。外部ライブラリ (jenkspy) を追加せず numpy で自前実装。🔵

### 2.5 データフロー 🟡

```
matcher.match_score() → fits: list[float]
peaks(各候補相)        → peak_sets: list[list[Peak]]
      → jaccard_clusters(peak_sets, fits, delta_us, *, similarity_threshold=0.85, bin_width_deg=0.2)
      → tuple[ClusterResult, ...]   # 代表 index + 代替解 members
      → (TASK-0006 木探索) 代表のみ展開・members は代替解として ledger 追記

探索完了後: evidence 列 → jenks_breaks(values, n_classes=2) → 境界値 → (TASK-0007) 良好解群を抽出
```

- **参照したEARS要件**: REQ-103 (FoM 代表・代替解保持) 🔵、REQ-104 (Jenks) 🔵、REQ-403/NFR-102 (ビット同一) 🔵
- **参照した設計文書**: `interfaces.py` L103-135、`architecture.md` D4 (FoM L108-114 / フロー §(3)(7))、`note.md` §4

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (REQ-403 / NFR-102)**: 同一入力でビット同一。union-find の走査順・クラスタ出力順を**入力順に依存させない** (代表/members を index 昇順で正規化、クラスタは代表 index 昇順に並べる)。**FoM 同点は index 小優先**で代表決定 (完了条件6 🟡)。`jenks_breaks` も入力順非依存 (関数内で昇順ソート)。
- 🔵 **非破壊性 (P2 / NFR-101 / REQ-103)**: 代替解を削除しない。全 index を `members` に保持し代表以外も後段で参照可能にする (Dara 教訓: 候補除外はしない、降格のみ)。
- 🔵 **失敗の非例外化 (M0 規約)**: ドメイン的縮退 (空入力・全同一・空ピーク集合) は例外でなく縮退値/自然な結果で表現する。IndexError / ZeroDivisionError を発生させない。
- 🔵 **FoM 分母ゼロのガード (note.md §6)**: `fit=1.0` かつ `delta_u=0.0` のとき `(1−fit)+ΔU = 0` → ゼロ除算。`float("inf")` へ落とす (inf は最大 FoM として代表選出に整合)。等値タイは決定論規則 (index 小優先) で固定。
- 🟡 **空ピーク集合の Jaccard**: 両空の `|A∪B|=0` で 0/0。縮退規則 (両空は類似 1 or 別扱い) を決めテストで確定する (note.md §6)。
- 🔵 **アーキテクチャ制約 (architecture.md L36/L65)**: `tsumugin/search/clustering.py` に配置。`search/` の純関数 + 値オブジェクト。ledger への「代表選出/クラスタ理由」記録は**呼び出し側 (TASK-0006/0007)** の責務で本関数スコープ外。
- 🔵 **技術スタック制約**: Python ≥ 3.12 / numpy ≥ 1.26 のみ。scipy / jenkspy / scikit-learn / GSAS-II 非依存。公開戻り値は素の `tuple` / `int` / `float` (numpy スカラーを露出しない)。
- 🔵 **コーディング規約 (CLAUDE.md / note.md §2)**: snake_case / PascalCase / 型注釈必須 (`Any` 回避) / キーワード専用引数は `*` / line-length 100 / `uvx ruff check src tests` クリーン。docstring に FR/REQ 番号と 🔵🟡 信頼性を紐づける。実装後 `src/tsumugin/search/__init__.py` の import と `__all__` に `ClusterResult` / `PhaseCandidate` / `jaccard_clusters` / `jenks_breaks` を**アルファベット順維持**で追加。
- **参照したEARS要件**: REQ-103 / REQ-104 / REQ-403 / NFR-101 / NFR-102 / P2 🔵、完了条件6 🟡
- **参照した設計文書**: `note.md` §2/§6、`architecture.md` D4/L36/L65、`interfaces.py` L103-135、`CLAUDE.md`

---

## 4. 想定される使用例（EARS Edgeケース・受け入れ基準ベース）

### 4.1 基本的な使用パターン 🔵 (TC-004-01 / TC-004-02)

- **TC-004-01**: ピーク位置がほぼ同一の 2 候補 → 1 クラスタに縮約。FoM (fit) 最大が `representative`、他方が `members` に保持される。
- **TC-004-02**: ピーク位置が異なる候補 → 別クラスタ (Jaccard < `similarity_threshold`)。

### 4.2 FoM 代表選出 🔵 (完了条件3 / FR-114 式)

- 同一クラスタ内で `delta_u` が大きい候補は `FoM = 1/((1−fit)+ΔU)` が下がり代表になれない。fit 同値でも ΔU で代表が変わることを検証。

### 4.3 Jenks natural breaks 🔵 (TC-004-03)

- 既知 2 群 (例 `[1, 2, 3, 100, 110]`) を `jenks_breaks(values, n_classes=2)` が正しく分離し、境界値が両群の間 (例 3〜100 の間) に入る。

### 4.4 エッジケース・縮退ケース

- 🔵 **TC-004-04 / EDGE-103 (境界)**: 全候補同一構造 (完全 Jaccard 重複) → クラスタ 1 個 (代表 1 + 代替 N−1)。`members` 長 = N。
- 🟡 **空/単一入力**: `peak_sets == []` → 空タプル。候補 1 個 → クラスタ 1 個 (代表 = members = その 1 index)。例外を投げない (EDGE-102 の精神)。
- 🟡 **空ピーク集合**: 空 `Peak` 列を含む候補の Jaccard 縮退規則を適用 (§3 参照)。
- 🟡 **FoM 分母ゼロ**: `fit=1.0, delta_u=0.0` → FoM = inf として最大扱い。
- 🟡 **`jenks_breaks` 縮退**: 空/単一/`n_classes ≥ 要素数` 等は例外でなく自然な境界 (空 or 全境界) に縮退。
- 🔵 **決定論 (完了条件6)**: 入力順を入れ替えても同一クラスタ構造・同一代表 (`==` でビット同一検証)。

### 4.5 エラーケース

- 🔵 例外・NaN・None を返さない。あらゆるドメイン縮退は縮退値/自然な結果に一元化する。

- **参照したEdgeケース**: EDGE-103 (全同一構造) 🔵、EDGE-102 (候補 1 相) 🟡
- **参照した受け入れ基準**: `acceptance-criteria.md` TC-004-01〜04 (L48-54)、完了条件3/6

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: M1 多仮説木探索の等構造縮約 (探索効率) と良好解抽出 (`user-stories.md`)
- **参照した機能要件**:
  - REQ-103 🔵 (等構造の FoM 代表選出・代替解 `alternatives` 保持=削除しない) *FR-114*
  - REQ-104 🔵 (探索完了後 Jenks natural breaks で良好解クラスタ抽出) *FR-116*
- **参照した非機能要件**:
  - REQ-403 / NFR-102 🔵 (ビット同一・決定論)
  - NFR-101 / P2 🔵 (純関数・非破壊・代替解保持)
- **参照したEdgeケース**: EDGE-103 🔵 (全候補同一構造 → 代表 1 + 代替 N−1)、EDGE-102 🟡 (候補 1 相)
- **参照した受け入れ基準**:
  - TC-004-01 🔵 (ほぼ同一 2 候補 → 1 クラスタ・FoM 最大が代表・他方 members)
  - TC-004-02 🔵 (異なるピーク → 別クラスタ)
  - TC-004-03 🔵 (`jenks_breaks` が既知 2 群を分離)
  - TC-004-04 🔵 (全同一構造 → クラスタ 1 個)
  - 完了条件3 🔵 (delta_u 大 → 代表になれない)、完了条件6 🟡 (決定論・同点 index 小優先)
- **参照した設計文書**:
  - **型定義 (契約)**: `docs/design/m1-hypothesis-search/interfaces.py` L103-135 (`PhaseCandidate` / `ClusterResult` / `jaccard_clusters` / `jenks_breaks`)
  - **アーキテクチャ / FoM**: `docs/design/m1-hypothesis-search/architecture.md` D4 (FoM L108-114 / データフロー §(3) Jaccard 等構造縮約・§(7) 良好解クラスタ / 表 L36 / ツリー L65)
  - **開発ルール / 制約**: `docs/implements/m1-hypothesis-search/TASK-0005/note.md` §1〜§6、`docs/spec/m1-hypothesis-search/note.md`、`CLAUDE.md`
  - **関連実装パターン**: `src/tsumugin/search/peaks.py` (`Peak` / 縮退ガード / numpy 純関数)、`src/tsumugin/search/matcher.py` (`MatchResult.score` / キーワード専用引数 / 決定論ソート / 分母0縮退)、`src/tsumugin/search/pruning.py` (縮退時 `-inf` / 入力順非依存)、`src/tsumugin/search/__init__.py` (公開 API)
- **実装対象 / テスト**:
  - 実装: `src/tsumugin/search/clustering.py` (新規: `PhaseCandidate`, `ClusterResult`, `jaccard_clusters()`, `jenks_breaks()`)
  - テスト: `tests/test_clustering.py` (新規、`test_matcher.py` / `test_peaks.py` / `test_pruning.py` の書式に倣う。GSAS-II 非依存で `@pytest.mark.gsas` 不要)

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (契約・FoM 式・正規化規則・縮退値を明記)
- 入出力定義: 完全 (2 値オブジェクト + 2 関数の型・制約・縮退値・アルゴリズム)
- 制約条件: 明確 (決定論・非破壊・非例外化・分母0ガード・numpy コア・命名/Lint)
- 実装可能性: 確実 (interfaces.py に契約確定、参照実装 3 件あり)
- 信頼性レベル: 🔵 6 / 🟡 1 — 契約・FoM 式・Jaccard/Jenks 方針は要件に依拠
```

- **残る 🟡 (要テスト確定)**: (a) 代表 FoM 同点のタイ処理 (index 小優先の妥当性・完了条件6)、(b) `similarity_threshold=0.85` / `bin_width_deg=0.2` の較正値、(c) 空ピーク集合同士の Jaccard 縮退規則、(d) `delta_u` M1 既定 0 前提。いずれも TC-004-01〜04 と決定論テストで挙動を確定させる。
