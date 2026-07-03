# TASK-0004 動的枝刈り閾値 dynamic_threshold — TDD 要件定義書

- **機能名**: 動的枝刈り閾値 (dynamic_threshold)
- **タスクID**: TASK-0004
- **要件名**: m1-hypothesis-search
- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 2h
- **出力ファイル**: `docs/implements/m1-hypothesis-search/TASK-0004/dynamic-threshold-requirements.md`
- **信頼性サマリー**: 🔵 3 / 🟡 2 — 契約・変曲点方針は FR-112 に依拠、実装式は interview Q8 の妥当推測

> **【信頼性レベル凡例】**
> - 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
> - 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
> - 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 候補相のマッチングスコア列 `scores` を受け取り、スコア**降順ソート列の累積分布の変曲点 (二階差分最大点)** に基づく**枝刈り閾値** (float) を算出する純関数。REQ-101「閾値はスコア累積分布の変曲点で動的決定する」を実装する。
- 🔵 **どのような問題を解決するか**: 多仮説木探索で全候補相をノード展開すると組合せ爆発する (NFR-002)。マッチングスコアが低い相を展開前に枝刈りし、評価ノード数を O(N·K) オーダーに抑制する事前指標を提供する。
- 🟡 **想定されるユーザー (呼び出し側)**: TASK-0006 の木探索コア。各ノード展開時に本関数へ候補相スコア列を渡し、返り値**未満**のスコアの相を展開対象から除外する。エンドユーザーが直接呼ぶ関数ではない (内部純関数)。
- 🔵 **システム内での位置づけ**: `search/` パッケージの状態を持たない**純関数** (`peaks.py` の `find_peaks`, `matcher.py` の `match_score` と同列)。numpy コアのみ依存 (scipy / GSAS-II 非依存)。入力 `scores` は `matcher.py` の `MatchResult.score` 列が渡される想定。
- **参照したEARS要件**: REQ-101 (条件付き要件) 🔵、NFR-002 (組合せ爆発抑制) 🟡
- **参照した設計文書**: `docs/design/m1-hypothesis-search/interfaces.py` L88-95 (`dynamic_threshold` 契約)、`docs/implements/m1-hypothesis-search/TASK-0004/note.md` §4

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 入力パラメータ 🔵 (契約は interfaces.py に準拠)

| 引数 | 型 | 制約 | 説明 |
|------|-----|------|------|
| `scores` | `Sequence[float]` | 順不同・空可・要素は有限 float 想定 | 候補相のマッチングスコア列 (`MatchResult.score` 群) 🔵 |
| `min_candidates` | `int` (キーワード専用 `*`) | 既定 `4`。これ未満は枝刈り無効 | 枝刈りを有効化する最小候補数 🟡 interview Q8 |

- 🔵 `min_candidates` は `*` 区切りのキーワード専用引数 (note.md §開発ルール / interfaces.py L90)。
- 🔵 **入力を破壊しない** (非破壊性 P2/NFR-101)。ソートは関数内でコピーに対して行う。

### 出力値 🔵 (縮退値は 🟡)

- **型**: 素の `float` (numpy スカラーでなく Python `float`)。🔵
- **正常値**: 変曲点位置のスコア。この値**未満**のスコアの相はノード展開しない (REQ-101、境界は「未満」)。閾値そのものは**展開側に含む** (TC-002-02 を満たす境界解釈) 🟡。
- **縮退値**: `float("-inf")`。全スコア >= -inf となり「全展開」を意味する。NaN・例外は返さない 🔵。

### 入出力の関係性・アルゴリズム 🟡 (interview Q8)

1. `scores` を**降順ソート** (関数内、入力非破壊)。
2. 累積分布 (累積和 `cumsum`) を作る。
3. 隣接**二階差分** `d2[i] = c[i+1] - 2·c[i] + c[i-1]` を計算。
4. **二階差分が最大 (最大曲率=変曲点)** となる位置のスコアを閾値とする。
5. タイ (二階差分最大が複数) は一意規則で固定 (例: 最初/最大スコア側) し、入力順で揺れない (決定論)。

- 🔵 **決定論**: ソートは関数内で行い、同一集合なら入力順に依存せずビット同一の閾値を返す (REQ-403 / NFR-102 / 完了条件4)。
- **参照したEARS要件**: REQ-101 (枝刈り閾値未満は展開しない) 🔵、REQ-403 (ビット同一) 🔵
- **参照した設計文書**: `interfaces.py` L88-95 (シグネチャ・docstring)、`interview-record.md` Q8 (実装式 🟡)、`note.md` §4

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🟡 **パフォーマンス (NFR-002)**: 本関数は枝刈りにより評価ノード数を O(N·K) に抑える布石。`np.sort`/`np.diff`/`np.cumsum`/`np.argmax` でベクトル化してよい (peaks.py と同じ numpy コア方針)。
- 🔵 **再現性 (REQ-403 / NFR-102 / NFR-202)**: 同一入力・同一設定でビット同一。浮動小数の等値判定・タイ処理を安定化させ、入力順で結果が揺れないこと。
- 🔵 **失敗の非例外化 (EDGE / M0 規約)**: ドメイン的縮退 (候補不足・全同値) は例外でなく `-inf` で表現する。IndexError 等を発生させない。
- 🔵 **アーキテクチャ制約**: `search/` パッケージの純関数。状態変更なし・値オブジェクト不要。ledger への「枝刈り理由記録」は**呼び出し側 (TASK-0006)** の責務で本関数スコープ外 (REQ-402/405)。
- 🔵 **技術スタック制約**: Python >= 3.12 / numpy >= 1.26 のみ。scipy・GSAS-II 非依存。戻り値は素の `float`。
- 🔵 **コーディング規約 (CLAUDE.md / note.md §2)**: snake_case / 型注釈必須 (`Any` 回避) / キーワード専用引数は `*` / line-length 100 / `uvx ruff check src tests` クリーン。docstring に FR/REQ 番号と 🔵🟡 信頼性を紐づける。実装後 `src/tsumugin/search/__init__.py` の import と `__all__` に `dynamic_threshold` を追加 (アルファベット順維持)。
- 🟡 **二階差分の最小点数**: 二階差分は内部点 (両隣) が最低 1 つ必要 = 実質 3 点以上。`min_candidates=4` 既定はこれをカバーするが、`min_candidates` を小さく指定された場合も IndexError を出さず縮退するガードを入れる。
- **参照したEARS要件**: NFR-002、REQ-403、NFR-102/202、REQ-402/405 🔵/🟡
- **参照した設計文書**: `note.md` §2/§6、`CLAUDE.md`、`interfaces.py` L88-95

---

## 4. 想定される使用例（EARS Edgeケース・受け入れ基準ベース）

### 基本的な使用パターン 🔵 (TC-002-02)

- 高スコア群と低スコア群が明確に分かれる入力 (例: `[0.9, 0.85, 0.8, 0.2, 0.15]`) で、閾値が**両群の間**に決まり、低群 (境界未満) の相が枝刈り対象になる。

### データフロー 🟡

```
matcher.match_score() → scores: list[float]
      → dynamic_threshold(scores, min_candidates=4)
      → threshold: float
      → (TASK-0006 木探索) score < threshold の相をノード展開しない + ledger に prune 記録
```

### エッジケース・縮退ケース

- 🟡 **TC-002-03**: 候補 **3 以下 (`len(scores) < min_candidates=4`)** → `-inf` (枝刈り無効=全展開)。
- 🟡 **TC-002-04 (境界)**: **全候補同スコア** (二階差分が全ゼロ・変曲点が一意に定まらない) → 閾値決定が破綻せず `-inf` へフォールバック。
- 🔵 **完了条件4 (決定論)**: 入力順を入れ替えても**同一閾値** (関数内ソート)。`==` でビット同一を検証。
- 🟡 **空入力** `scores == []`: `len < min_candidates` の縮退経路に含まれ `-inf` を返す (例外なし)。EDGE-001「候補相ゼロ→例外を投げない」の精神に整合。

### エラーケース

- 🔵 NaN・例外・None は返さない。あらゆる縮退は `float("-inf")` に一元化する。

- **参照したEdgeケース**: EDGE-001 (候補ゼロで例外なし) 🔵、TC-002-03 / TC-002-04 (縮退) 🟡
- **参照した受け入れ基準**: `acceptance-criteria.md` L37-40 (TC-002-02〜04)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: M1 多仮説木探索の枝刈り (組合せ爆発抑制) — `user-stories.md` (探索効率)
- **参照した機能要件**:
  - REQ-101 🔵 (枝刈り閾値未満はノード展開しない・閾値は累積分布の変曲点で動的決定) *FR-111/FR-112*
  - REQ-402/405 🔵 (枝刈りは理由付き Ledger 記録 — 呼び出し側責務)
- **参照した非機能要件**:
  - NFR-002 🟡 (組合せ爆発の抑制 O(N·K))
  - REQ-403 / NFR-102 / NFR-202 🔵 (ビット同一・決定論)
  - NFR-101 / P2 🔵 (純関数・非破壊)
- **参照したEdgeケース**: EDGE-001 🔵 (候補ゼロで例外を投げない)
- **参照した受け入れ基準**:
  - TC-002-02 🔵 (変曲点閾値で低群を枝刈り)
  - TC-002-03 🟡 (候補 3 以下で枝刈り無効)
  - TC-002-04 🟡 (全同値で `-inf` フォールバック)
  - 完了条件4 🔵 (入力順非依存の決定論)
- **参照した設計文書**:
  - **型定義 (契約)**: `docs/design/m1-hypothesis-search/interfaces.py` L88-95 (`dynamic_threshold(scores, *, min_candidates=4) -> float`)
  - **アーキテクチャ / 開発ルール**: `docs/implements/m1-hypothesis-search/TASK-0004/note.md` §1〜§6、`CLAUDE.md`
  - **関連実装パターン**: `src/tsumugin/search/peaks.py` (縮退ガード)、`src/tsumugin/search/matcher.py` (キーワード専用引数・決定論ソート・分母0縮退)、`src/tsumugin/search/__init__.py` (公開 API)
  - **アルゴリズム根拠**: `docs/spec/m1-hypothesis-search/interview-record.md` Q8 (二階差分最大=変曲点、実装式 🟡)
- **実装対象 / テスト**:
  - 実装: `src/tsumugin/search/pruning.py` の `dynamic_threshold()`
  - テスト: `tests/test_pruning.py` (新規、`test_matcher.py`/`test_peaks.py` の書式に倣う。GSAS-II 非依存で `@pytest.mark.gsas` 不要)

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (契約・境界セマンティクス・縮退値を明記)
- 入出力定義: 完全 (型・制約・縮退値・アルゴリズム 5 ステップ)
- 制約条件: 明確 (決定論・非例外化・純関数・numpy コア・命名/Lint)
- 実装可能性: 確実 (interfaces.py に契約確定、参照実装 2 件あり)
- 信頼性レベル: 🔵 が多数 (契約・境界・決定論)。実装式のみ 🟡 (interview Q8) でテストにより境界確定
```

- **残る 🟡 (要テスト確定)**: (a) 二階差分最大=変曲点の実装式 (interview Q8 の推測)、(b) 閾値そのものを展開側に含む境界解釈、(c) `min_candidates` 既定 4 の妥当性。いずれも TC-002-02〜04 と決定論テストで挙動を確定させる。
