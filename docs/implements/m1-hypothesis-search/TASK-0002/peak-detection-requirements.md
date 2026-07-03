# TASK-0002 観測ピーク検出 find_peaks — TDD 要件定義書

**機能名**: 観測ピーク検出 find_peaks
**タスクID**: TASK-0002
**要件名**: m1-hypothesis-search
**作成日**: 2026-07-03
**対象実装**: `src/tsumugin/search/peaks.py`（新規）
**対象テスト**: `tests/test_peaks.py`（新規）

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書（interfaces.py）を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測で確定した
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 観測回折パターン `(two_theta, intensity)` を入力に、局所極大かつ
  「最大強度 × `min_height_frac`」以上の高さを持つ点を**観測ピーク**として抽出し、
  不変な `tuple[Peak, ...]`（各 `Peak(position, height)`）で返す純関数。numpy のみで実装する。
- 🔵 **どのような問題を解決するか**: 多仮説木探索（REQ-001）のノード評価に先立ち、候補相の
  シミュレートピークと突き合わせるための「観測側ピーク集合」を用意する。REQ-002（FR-111）の
  マッチングスコア計算 `search/matcher.py::match_score(candidate_peaks, observed_peaks)` の
  **前段（観測ピーク抽出）**を担う。
- 🔵 **想定されるユーザー**: 直接の呼び出し元は `search/matcher.py` および `search/tree.py`
  （`HypothesisTreeSearch`）。エンドユーザーは相同定を行う解析者だが、本関数は内部コンポーネント。
- 🔵 **システム内での位置づけ**: レイヤ分離アーキテクチャの Workers/探索コンポーネント層（Phase 2）。
  値オブジェクト（frozen dataclass）を返す純関数として、上位の Orchestrator（木探索）から利用される。
  scipy・GSAS-II に非依存で、プレーン環境（numpy のみ）で完結する。
- **参照したEARS要件**: REQ-002（FR-111）, REQ-403（NFR-102 決定論）, EDGE-003
- **参照した設計文書**: `docs/design/m1-hypothesis-search/interfaces.py`（`search/peaks.py` 節: `Peak` /
  `find_peaks`、`search/matcher.py` 節: `match_score` の下流契約、`SearchConfig.min_peak_height_frac`）

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 入力パラメータ 🔵（interfaces.py に準拠）

| 引数 | 型 | 制約・既定 | 説明 |
|------|----|-----------|------|
| `two_theta` | `np.ndarray` | 1 次元・`intensity` と同長・昇順（回折角グリッド） | 2θ 軸（度）。🔵 |
| `intensity` | `np.ndarray` | 1 次元・`two_theta` と同長 | 各 2θ での観測強度。🔵 |
| `min_height_frac` | `float` | キーワード専用・既定 `0.05` | 最大強度に対する検出下限比率。🟡（実装式は推測） |

- 🔵 `min_height_frac` は**キーワード専用引数**（`*` 以降）。既定 `0.05` は `SearchConfig.min_peak_height_frac`
  の既定値と一致し、下流の木探索設定と整合する（interfaces.py）。
- 🟡 入力は内部で `np.asarray(..., dtype=float)` により float 配列へ正規化する（note.md 6 章の方針）。

### 出力値 🔵（interfaces.py に準拠）

- 🔵 戻り値: `tuple[Peak, ...]`（不変タプル）。各要素は `Peak` frozen dataclass。
  - `Peak.position: float` — ピークの 2θ 位置（度）。FR-111 のマッチング単位。🔵
  - `Peak.height: float` — ピーク位置の観測強度。🔵
- 🟡 **並び順は位置（`position`）昇順**（決定論のため順序を固定。note.md 4 章「位置昇順が自然」）。
- 🔵 ピークが検出されない場合は**空タプル `()`**（例外を送出しない）。

### 入出力の関係性・データフロー 🟡（note.md の手本アルゴリズムに基づく）

1. `y = np.asarray(intensity, float)`、`x = np.asarray(two_theta, float)` に正規化。
2. 高さ閾値 `min_height = min_height_frac * y.max()` を算出（`y.max() <= 0` はゼロ扱いで安全処理）。
3. 内部点の局所極大を numpy ベクトル比較で抽出:
   `interior = (y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)`
   （`tests/test_simulated_backend.py::_count_local_maxima` を直接の手本とする）。
4. 該当インデックスから `Peak(position=x[i], height=y[i])` を生成し、位置昇順のタプルで返す。

- **参照したEARS要件**: REQ-002（FR-111）
- **参照した設計文書**: `interfaces.py`（`Peak`, `find_peaks` シグネチャ, `SearchConfig.min_peak_height_frac`）
- **参照した実装（手本）**: `src/tsumugin/backends/simulated.py`（`simulate` / `peak_positions`）,
  `tests/test_simulated_backend.py::_count_local_maxima`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

### 実装制約 🔵

- 🔵 **numpy のみで実装**。`scipy.signal.find_peaks` 等は使用禁止（TASK-0002.md / interfaces.py の明示制約）。
  局所極大は `(y[1:-1] > y[:-2]) & (y[1:-1] > y[2:])` 型のベクトル比較で求め、**端点は極大判定から除外**する。
- 🔵 **決定論必須（REQ-403 / NFR-102）**: 乱数を一切使わず、同一入力 → 同一出力（戻り順序も固定）。
- 🔵 **値オブジェクトは frozen dataclass**（`Peak`）。`find_peaks` は**純関数**（副作用・状態なし）。
  削除・上書き API を作らない（P2 非破壊性に自然に合致）。
- 🔵 **型注釈必須**（`any` 回避、CLAUDE.md 規約）。命名は `snake_case` 関数 / `PascalCase` 型。
- 🟡 公開シンボルは `src/tsumugin/search/__init__.py` の `__all__` に `Peak` / `find_peaks` を追加
  （現状 `__all__ = []`。note.md 2 章）。

### 失敗時の設計原則 🔵（M0 由来）

- 🔵 **失敗は例外でなく空/縮退結果に変換する**（EDGE-003 / M0 規約）。フラット・全ゼロで `raise` しない。
- 🔵 `intensity.max() <= 0` のとき閾値計算で例外を出さず（**ゼロ除算・比較破綻を回避**）、空タプルを返す。

### パフォーマンス要件 🟡

- 🟡 ベクトル化により **O(N) 走査**（N = グリッド点数）。ソートは検出ピーク数程度で軽微。
  M1 の全体目標（NFR-103 の 3 分/300 相）に対し本関数はボトルネックにならない設計（note.md 6 章）。

### 互換性・下流契約 🔵

- 🔵 戻り値 `tuple[Peak, ...]` は `search/matcher.py::match_score(candidate_peaks, observed_peaks, *, tol_deg=0.15)`
  がそのまま消費する（interfaces.py）。`Peak` の属性名 `position` / `height` を変更しない。

- **参照したEARS要件**: REQ-403（NFR-102）, EDGE-003, P2（REQ-402 非破壊）
- **参照した設計文書**: `interfaces.py`（`Peak` / `find_peaks` / `match_score`）,
  `CLAUDE.md`（実装上の不変条件・コーディング規約）

---

## 4. 想定される使用例（Edgeケース・データフローベース）

### 基本的な使用パターン 🔵

- 🔵 **単相合成パターン**: `backend = SimulatedBackend(); y = backend.simulate([phase], tt)` に対し、
  `len(find_peaks(tt, y)) == len(backend.peak_positions(phase, tt))` が成立し、各ピーク位置が
  真の位置 `peak_positions` から **±1 グリッド以内**（`tt` の刻み ≈ 0.02°）に一致する。
  （完了条件 1 / TC-002 系）
- 🔵 **多相合成パターン**: 複数相を重ねると検出ピーク数が増加する（相ごとのピーク列が加わる）。

### データフロー 🟡

- 🟡 入力配列 → float 正規化 → 高さ閾値算出 → 局所極大マスク → `Peak` 生成（位置昇順）→ タプル返却。

### エッジケース 🔵🟡

- 🔵 **EDGE-003 / フラット・全ゼロパターン**: `intensity` が全ゼロまたは一定値 → 内部極大なし・
  `max()<=0` → **空タプル `()` を返し、例外を送出しない**（完了条件 2 / TC-005-03 の基盤挙動）。
- 🟡 **微小ピークの除外**: `min_height_frac` を上げると閾値未満の微小ピークが検出結果から落ちる
  （閾値挙動の単調性。完了条件 3）。
- 🟡 **プラトー頂点**: 隣接サンプルが等値の平坦な山（`y[i] == y[i±1]`）は厳密不等号 `>` により
  極大とみなされない（端の扱いに注意。過検出を避ける保守的挙動）。
- 🟡 **極小入力**: 配列長 < 3（内部点が存在しない）→ 局所極大は空 → 空タプル。
- 🔵 **決定論**: 同一入力で 2 回呼び出すと戻り値が完全一致（順序・値ともビット同一。完了条件 4 / REQ-403）。

### エラーケース 🟡

- 🟡 本関数はドメイン的な失敗（ピークなし）を**例外化しない**（EDGE-003 / M0 規約）。
  なお `two_theta` と `intensity` の**長さ不一致**は前提違反であり、テスト対象外（同長前提。note.md 6 章）。

- **参照したEARS要件**: EDGE-003, REQ-403, REQ-002
- **参照した受け入れ基準**: TC-002 系（REQ-002/101）, TC-005-03（EDGE-003 の基盤挙動）
- **参照した設計文書 / 実装**: `src/tsumugin/backends/simulated.py`（`simulate` / `peak_positions`）,
  `tests/test_simulated_backend.py::_count_local_maxima`（`_grid = np.arange(15.0, 80.0, 0.02)`）

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 多仮説木探索による相同定（M1）— 観測ピーク抽出はその基盤処理
- **参照した機能要件**: REQ-002（FR-111 マッチングスコアの前段）, REQ-001（木探索の入力整備）
- **参照した非機能要件**: REQ-403（NFR-102 決定論・ビット同一）, REQ-402（P2 非破壊性）
- **参照したEdgeケース**: EDGE-003（フラット/ノイズのみ → 空良好解の基盤挙動）
- **参照した受け入れ基準**:
  - TC-002-01（一致相スコア > 不一致相スコア）の前提となる観測ピーク抽出
  - TC-005-03（フラットパターンで例外なく空 + 警告）の基盤（本タスクは空タプル返却まで）
- **参照した設計文書**:
  - **型定義**: `docs/design/m1-hypothesis-search/interfaces.py` の `Peak`（`position`, `height`）,
    `find_peaks(two_theta, intensity, *, min_height_frac=0.05) -> tuple[Peak, ...]`,
    `SearchConfig.min_peak_height_frac = 0.05`, 下流 `match_score(...)`
  - **アーキテクチャ**: レイヤ分離 / frozen dataclass / Protocol 抽象化（CLAUDE.md, note.md 1 章）
  - **データフロー**: 観測パターン → 局所極大 + 高さ閾値 → 観測 `Peak` 列 → matcher（REQ-002）
  - **実装の手本**: `src/tsumugin/backends/simulated.py`, `tests/test_simulated_backend.py`

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし（シグネチャ・戻り型・エッジ挙動が interfaces.py と完了条件で確定）
- 入出力定義: 完全（型・制約・順序・空タプル規約まで明記）
- 制約条件: 明確（numpy のみ・決定論・純関数・非破壊・失敗の縮退）
- 実装可能性: 確実（局所極大の numpy 式が既存テストに実在、手本コードあり）
- 信頼性レベル: 🔵 が多数（コアの機能・入出力・制約・決定論・EDGE-003 は 🔵）。
               🟡 は主にチューニング式（min_height_frac の適用式・位置昇順の順序決定・
               プラトー/極小入力の細部）に限定、🔴 なし
```

### 信頼性レベル分布（本要件定義書）

- 🔵 コア要件（機能概要・Peak 型・入出力・numpy制約・決定論・EDGE-003・下流契約）
- 🟡 実装細部（`min_height` 適用式・戻り順序の昇順決定・プラトー/短配列の扱い・O(N) 性能・`__all__` 追記）
- 🔴 なし

**総合品質評価**: 高品質

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m1-hypothesis-search TASK-0002` でテストケースの洗い出しを行います。
