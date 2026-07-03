# TASK-0033 TDD 要件定義書 — operando/segmentation (FR-316: IC 区間自動分割)

**機能名**: operando-segmentation / **タスクID**: TASK-0033 / **要件名**: m3-operando
**タイプ**: TDD / **フェーズ**: Phase 4 / **信頼性**: 🔵 5 / 🟡 1
**実装対象**: `src/tsumugin/operando/segmentation.py` / **テスト**: `tests/test_segmentation.py`

> 本書のすべてのパスはプロジェクトルートからの相対パス。信頼性レベル 🔵=資料に直接依拠 /
> 🟡=資料からの妥当な推測 / 🔴=資料にない推測。

---

## 1. 機能の概要（EARS 要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: operando (充放電/高温 in-situ) の粉末回折**フレーム列 (FrameSeries) を
  IC (情報量規準 = bic) ペナルティ付きで区間自動分割**する。区間数 k を 1 から貪欲に増やし、
  合計コスト (区間 bic 和 + 境界数ペナルティ) が最小になる境界集合を決定する
  オーケストレーション純関数 `segment_series` を提供する。
  *参照: `docs/tasks/m3-operando/TASK-0033.md`, FR-316, REQ-013*
- 🔵 **解決する問題**: operando 反応 (固溶体反応 → 二相反応など) の**反応機構が切り替わる境界**を
  人手なしで自動特定し、後段の区間別判別 (FR-313 / TASK-0032) と結合出力 (FR-314) の入力を与える。
  境界数ペナルティにより**過分割 (ノイズを境界と誤認)** を抑止する。
  *参照: REQ-013, EDGE-004, `docs/design/m3-operando/dataflow.md` L20*
- 🔵 **想定ユーザー**: operando 電池/高温 in-situ を自動 Rietveld 解析するツール利用者、および
  本機能を上位パイプライン (E2E: echem 同期 → 逐次解析 → **区間分割** → 区間判別 → 結合出力) から呼ぶ
  上位エージェント/オーケストレータ。
  *参照: `docs/spec/m3-operando/acceptance-criteria.md` TC-209-01 (L82)*
- 🔵 **システム内での位置づけ**: `operando/segmentation.py` は**純関数のオーケストレーション層**。
  下位部品 (区間 warm-start 逐次 direct refine / `evidence.ic.BICBackend` / `model.Hypothesis` /
  `store.Ledger`) を束ねる。TASK-0032 (`operando/discrimination.py`) と同型で、区間 Σbic を求める
  warm-start 逐次 refine パターンを再利用する。dataflow 上は SequentialEngine の後段・
  discriminate_interval の前段。
  *参照: `docs/design/m3-operando/architecture.md` D5/D6 (L78-86)・分割表 (L40), dataflow.md L18-22*

- **参照した EARS 要件**: FR-316, REQ-013, REQ-014
- **参照した設計文書**: `architecture.md` D5/D6, `dataflow.md` (FR-316 ノード), `interfaces.py` L287-321

---

## 2. 入力・出力の仕様（EARS 機能要件・型定義ベース）

### 2.1 関数シグネチャ 🔵

*参照: `docs/design/m3-operando/interfaces.py` L313-321*

```python
def segment_series(
    backend: RefinementBackend,
    series: FrameSeries,
    initial_phases: tuple[PhaseInstance, ...],
    *,
    config: SegmentationConfig = SegmentationConfig(),
    fixed_phases: tuple[FixedPhaseSpec, ...] = (),
    ledger: Ledger | None = None,
) -> SegmentationResult: ...
```

### 2.2 入力パラメータ 🔵

| 引数 | 型 | 制約・意味 | 信頼性 |
|---|---|---|---|
| `backend` | `RefinementBackend` (Protocol) | `name` + `refine(model, *, max_cycles) -> RefinementResult`。区間 bic 算出に使用 | 🔵 |
| `series` | `FrameSeries` | `intensities[(n_frames, n_points)]` / `two_theta` / `n_frames`。区間 = フレーム index の連続範囲 | 🔵 |
| `initial_phases` | `tuple[PhaseInstance, ...]` | 区間逐次 refine の初期相 (活物質)。空不可 (相なしは分割対象外) | 🔵 |
| `config` | `SegmentationConfig` | 既定 `SegmentationConfig()` | 🔵 |
| `fixed_phases` | `tuple[FixedPhaseSpec, ...]` | セル固定相 (常駐・構造固定・scale のみ解放)。既定 `()` | 🔵 |
| `ledger` | `Ledger \| None` | 追記専用ストア。`None` なら本関数内で新規生成 (結果不変) | 🔵 |

### 2.3 `SegmentationConfig` (frozen) 🔵

*参照: `interfaces.py` L292-298*

| フィールド | 型 | 既定 | 意味 | 信頼性 |
|---|---|---|---|---|
| `penalty_beta` | float | 5.0 | 合計コストの `β·(境界数)·ln(n_frames)` 係数 | 🔵 (β 較正は 🟡) |
| `improvement_threshold` | float | 10.0 | k 増加の改善打ち切り閾値 (§15-1) | 🔵 |
| `coarse_step` | int | 5 | 粗グリッド刻み G (フレーム) | 🟡 |
| `max_segments` | int | 6 | セグメント数 k の安全上限 | 🟡 |
| `seq_max_cycles` | int | 10 | 区間 direct refine の max_cycles | 🟡 |

### 2.4 `SegmentationResult` (frozen) 🔵

*参照: `interfaces.py` L301-310*

| フィールド | 型 | 意味 | 信頼性 |
|---|---|---|---|
| `boundaries` | `tuple[int, ...]` | 採択境界フレーム index (昇順、端 0/n_frames は含めない) | 🔵 |
| `n_segments` | int | セグメント数 k (= `len(boundaries) + 1`) | 🔵 |
| `evidence_by_k` | `Mapping[int, float]` | k → その k の最良合計コスト (代替閲覧用) | 🔵 |
| `partitions` | `tuple[Hypothesis, ...]` | 各 k の分割仮説 (D6) | 🔵 REQ-014 |
| `ledger` | `Ledger` | 記録済み ledger (入力 or 新規生成) | 🔵 |
| `warnings` | `tuple[str, ...]` | 縮退・打ち切り等の警告。既定 `()` | 🔵 |

### 2.5 コスト定義 (入出力の関係性) 🔵

- 区間コスト `interval_bic(start, end)` = 区間 `[start, end]` を **warm-start 逐次 direct refine
  (格子解放 `scale,lattice.a/b/c`)** した各フレームの bic 和。**`(start, end)` をキーにメモ化**。
  *参照: 設計 D-Q5 (`design-interview.md` L28-32), `interfaces.py` L294*
- 合計コスト `total_cost(boundaries) = Σ_seg interval_bic(seg) + penalty_beta · len(boundaries) · ln(n_frames)`。
  `evidence_by_k[k]` はこの total_cost を保持 (k = セグメント数)。ペナルティは**境界数** (= k−1) に比例。
  *参照: 設計 D5 (`architecture.md` L80)*
- bic は各フレーム `RefinementResult` → `RefinementMetrics` → `BICBackend.score().value`
  (= `chi2 + n_params·ln(max(n_obs,1))`) で算出。
  *参照: `src/tsumugin/evidence/ic.py` L19-21*

### 2.6 データフロー 🔵

*参照: `dataflow.md` L18-22*

`SequentialEngine 逐次解析` → **`segment_series` (k=1,2,… 貪欲挿入 / Σbic + β·境界数·ln n / 粗 G=5 → 細 ±G)** →
各区間 `discriminate_interval` (FR-313)。segment_series は ledger へ境界・evidence を記録。

- **参照した EARS 要件**: REQ-013, REQ-014
- **参照した設計文書**: `interfaces.py` L287-321, `dataflow.md` L18-22, `design-interview.md` D-Q5/D-Q6

---

## 3. 制約条件（EARS 非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (NFR-102)**: 乱数/IO なし・安定ソート・dict 反復順非依存。同一入力 2 回でビット同一
  (`result_a == result_b`)。同コストの境界候補は決定論的 tie-break (小さい index 優先) で確定。
  *参照: `CLAUDE.md` NFR-102, TC-206-07*
- 🔵 **非破壊性 (P2 / NFR-101/105)**: 入力 `series`/`initial_phases`/`fixed_phases` を破壊しない。
  Ledger は append のみ (削除・上書き API なし)、`verify()` は常に True。
  `evidence_by_k`/`partitions` は追記構築。
  *参照: `CLAUDE.md` P2, `interfaces.py` L309*
- 🔵 **非有限を漏らさない (M1 教訓 / ガードレール)**: バックエンド失敗は例外でなく chi2=inf の結果へ変換し、
  inf/NaN を Σbic・合計コストへ混ぜない。全フレーム非有限は分割なし (k=1) + 警告へ縮退。
  *参照: `CLAUDE.md` 不変条件*
- 🟡 **性能 (NFR-002)**: 区間コストのメモ化で同一 `(start,end)` の再評価を回避 (粗→細 2 段でも共用)。
  逐次は direct refine (`seq_max_cycles`)。テストは小グリッド合成で軽量に。
  *参照: `architecture.md` L128 (NFR-002)*
- 🔵 **後方互換 (REQ-404)**: 新規モジュール追加のみ。`operando/__init__.py` の `__all__` へ
  `SegmentationConfig`/`SegmentationResult`/`segment_series` を非破壊追記。既存 export 無改変・全テスト green 維持。
  *参照: `src/tsumugin/operando/__init__.py`*
- 🔵 **アーキテクチャ制約**: 不変データ (frozen dataclass) + `typing.Protocol` 境界 + 追記専用ストア +
  純関数コア。数値は numpy のみ (REQ-403)。型注釈必須・snake_case・日本語 docstring 可・信頼性レベル併記。
  *参照: `CLAUDE.md` コーディング規約, `architecture.md` L18-22*
- 🔵 **セマンティクス統一**: chi2/rwp/bic のセマンティクスをバックエンド間で統一 (BIC 比較の一貫性)。
  区間コストは discrimination (TASK-0032) と同一の bic 算出を用いる。
  *参照: `CLAUDE.md` 不変条件*

- **参照した EARS 要件**: NFR-002, NFR-101/102/105, REQ-403/404
- **参照した設計文書**: `architecture.md` (L18-22, L128), `CLAUDE.md` 不変条件

---

## 4. 想定される使用例（EARS Edge ケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

1. **2 区間反応 (通常系)**: 前半が固溶体 (単相格子連続変化)、後半が二相 (端成分分率変化) のフレーム列 →
   貪欲挿入で k=2 が最良となり、真の切り替わりフレーム近傍 (±2 フレーム) に境界 1 本を採択。
   *参照: TC-206-01*
2. **単一機構 (過分割抑止)**: 全区間が同一機構 (一様データ) → k=1 の合計コストが最良、
   境界を追加しても改善が閾値未満 → k=1 採択 (`boundaries == ()`)。
   *参照: TC-206-02 / EDGE-004*

### 4.2 データフロー 🔵

`segment_series` は k を 1 から増やす:
k 現状態の各セグメントへ粗グリッド候補の境界を試挿入 → 各候補の total_cost を計算 (区間コストはメモ化) →
最小の挿入を採用 → 直前 k からの改善が閾値以上なら確定して k+1 へ、未満なら打ち切り →
採用境界を ±coarse_step で細密スキャン再配置 → 各 k を Hypothesis 化して `partitions` へ、
合計コストを `evidence_by_k` へ、境界/イベントを ledger へ記録。
*参照: `dataflow.md` L20, `architecture.md` D5 (L78-82)*

### 4.3 エッジ・エラーケース

| ケース | 期待動作 | 信頼性 | 参照 |
|---|---|---|---|
| k=1 が最良 (一様) | そのまま採択 (過分割しない)、`boundaries=()` | 🔵 | EDGE-004 / TC-206-02 |
| 改善 < 閾値 | その k で打ち切り (`max_segments` まで走らない)、直前 k を最終採択 | 🔵 | TC-206-03 |
| `n_frames < 2` | 分割不能 → k=1 のみ + warnings | 🟡 | (縮退・派生) |
| `coarse_step >= n_frames` | 挿入候補なし → k=1 確定 | 🟡 | (縮退・派生) |
| 全フレーム非有限 (backend 全滅) | Σbic に inf を出さず分割なし + warnings へ縮退 | 🟡 | M1 教訓・ガードレール |
| `fixed_phases` 指定 | 区間逐次 refine に固定相連結・固定相は `("scale",)` のみ解放 (n_params 整合) | 🔵 | FR-312 連携 |
| `ledger=None` | 内部で新規 Ledger 生成し記録・結果は同一 | 🔵 | `interfaces.py` L320 |

- **参照した EARS 要件**: EDGE-004
- **参照した設計文書**: `dataflow.md` L20, `architecture.md` D5

---

## 5. EARS 要件・設計文書との対応関係

- **参照したユーザストーリー**: operando 反応機構の区間自動分割 (`docs/spec/m3-operando/user-stories.md`
  IC 区間分割 / operando 一気通貫)
- **参照した機能要件**: REQ-013 (IC ペナルティ付き changepoint 分割・k を 1 から逐次追加・改善閾値打ち切り・
  粗→細 2 段), REQ-014 (各分割仮説を Hypothesis 保存・代替閲覧), FR-316
- **参照した非機能要件**: NFR-002 (粗→細 2 段・区間コストメモ化), NFR-102 (決定論/再現性),
  NFR-101/105 (Ledger 非破壊・ハッシュチェーン `verify()`), REQ-403 (numpy のみ), REQ-404 (後方互換)
- **参照した Edge ケース**: EDGE-004 (k=1 最良 → そのまま採択・過分割しない)
- **参照した受け入れ基準**: TC-206-01 (k=2・境界 ±2), TC-206-02 (k=1・過分割しない), TC-206-03 (改善閾値打ち切り),
  TC-206-04 (分割仮説保存・代替閲覧), TC-206-05 (粗→細改善 + 呼び出し抑制/メモ化), TC-206-07 (決定論ビット同一)。
  **スコープ外**: TC-206-06 (Issue #3 新規ピーク持続発火 → TASK-0031 完了済み)、TC-209-01 (E2E → TASK-0035)。
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` D5 (L78-82: 貪欲挿入・合計コスト・粗→細)、
    D6 (L84-86: 分割仮説 Hypothesis 保存)、分割表 (L40)、NFR-002 (L128)
  - **データフロー**: `docs/design/m3-operando/dataflow.md` L18-22 (FR-316 ノード)
  - **型定義**: `docs/design/m3-operando/interfaces.py` L287-321 (`SegmentationConfig` / `SegmentationResult` /
    `segment_series`)
  - **設計ヒアリング**: `docs/design/m3-operando/design-interview.md` D-Q5 (L28-32: 区間コスト = warm-start 逐次
    refine の bic 和・メモ化), D-Q6 (L34-38: 分割仮説は各 k を 1 Hypothesis・境界は ledger/evidence_by_k 保持)
  - **依存実装**: `src/tsumugin/operando/discrimination.py` (区間 Σbic 逐次 refine 先例 `_refine_interval`),
    `src/tsumugin/evidence/ic.py` (BICBackend), `src/tsumugin/model/hypothesis.py` (Hypothesis/RefinementMetrics),
    `src/tsumugin/operando/cell_phases.py` (FixedPhaseSpec/fixed_free_suffixes)

---

## 品質判定

✅ **高品質**:
- 要件の曖昧さ: なし (契約は interfaces.py L287-321 に確定、コスト式・打ち切り・粗→細は D5/D-Q5 に明記)
- 入出力定義: 完全 (シグネチャ・Config/Result 全フィールド・コスト式を明記)
- 制約条件: 明確 (決定論/非破壊/非有限/後方互換/性能を NFR 紐付けで列挙)
- 実装可能性: 確実 (TASK-0032 の `_refine_interval` / BICBackend / Hypothesis が実装済みで再利用可)
- 信頼性レベル: 🔵 主体 (🟡 は coarse_step/max_segments/seq_max_cycles/β の較正値と縮退派生のみ)

**残す設計判断 (tdd-testcases / tdd-red で確定)**: 区間半開/閉区間規約、分割仮説 phases の「区間代表相」の中身、
メモ化呼び出し抑制の spy 検証方法 (→ note.md §6 に整理済み)。
