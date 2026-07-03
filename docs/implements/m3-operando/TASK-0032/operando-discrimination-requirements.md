# TASK-0032 TDD要件定義: operando/discrimination — 固溶体 vs 二相判別 (FR-313)

**要件名**: m3-operando / **タスクID**: TASK-0032 / **機能名**: operando-discrimination
**タイプ**: TDD / **推定 6h** / **フェーズ**: Phase 4
**前提**: TASK-0026 (absorption) / TASK-0028 (MultistartEngine) / TASK-0030 (FixedPhaseSpec) / TASK-0031 (changepoint 較正) — すべて完了 / **後続**: TASK-0035
**信頼性サマリー**: 🔵 6 / 🟡 1 (FR-313 / 設計 D4 / REQ-010/101 / EDGE-005 / AC TC-204-01〜06 + TC-209-03)

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: operando 時系列の 1 区間 (フレーム範囲) に対し、同一データを説明する
  2 つの競合仮説を構築し、Evidence Engine (bic 一次) で **固溶体 vs 二相反応** を判別する:
  - **仮説 A (固溶体)**: 区間フレームを**単相 warm-start 逐次 direct refine (格子解放)** し、
    区間合計 Σbic_A + 格子トラジェクトリを得る。
  - **仮説 B (二相)**: **端成分 2 相** を区間端点の A 仮説格子で初期化し (**格子固定**)、
    **scale/wt のみ解放**で逐次精密化して区間合計 Σbic_B + 分率トラジェクトリを得る。
  - 両仮説の**区間端点フレームでマルチスタート必須適用** (N=8 既定、TASK-0028 `MultistartEngine`)。
  - `ΔBIC = Σbic_A − Σbic_B` を閾値 (既定 10.0) と比較して
    verdict (`"solid_solution"` / `"two_phase"` / `"undecided"`) を決める。

- 🔵 **どのような問題を解決するか**: operando 計測 (電池の充放電中の回折) では「格子が連続変化する
  固溶体反応」と「端成分 2 相の分率が変化する二相反応」が回折パターン上で競合し、単一仮説の
  精密化では区別を誤りうる。両仮説を同条件で精密化し evidence 比較 + マルチスタート (局所最適
  回避) で判別の信頼性を担保する。僅差は自動確定せず人間へエスカレーション (Review Queue) する。

- 🔵 **想定されるユーザー**: (直接) operando 解析パイプライン — 区間分割 `segment_series`
  (TASK-0033, FR-316) が各区間で本関数を呼ぶ。M3 E2E (TASK-0035)。(間接) 自動解析エージェント・
  Review Queue を確認する人間レビュアー。

- 🔵 **システム内での位置づけ**: `operando` 層の判別エンジン (FR-313)。上流は `FrameSeries`
  (M2 sequential) と初期相、下流は `MultistartEngine` (FR-230) / `BICBackend` (FR-120) /
  `ReviewQueue` (M2 selection) / `Ledger` (P2)。`operando/segmentation.py` (TASK-0033) が消費する。

- **参照したEARS要件**: REQ-010, REQ-101, REQ-004, REQ-102, EDGE-005, FR-313, FR-233, FR-122
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D4 (L71-76) / モジュール表 (L39)、
  `docs/design/m3-operando/dataflow.md` FR-313 判別のシーケンス (L53-77)、
  `docs/design/m3-operando/interfaces.py` L252-284

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 DiscriminationConfig（設定・frozen dataclass）

- 🔵 `close_threshold: float = 10.0` — ΔBIC 僅差閾値 (FR-122)。
- 🔵 `multistart: MultistartConfig = MultistartConfig()` — 必須適用のマルチスタート設定 (FR-233)。
  既定 `n_starts=8, basin_rel_tol=1e-2, ms_max_cycles=15` (`src/tsumugin/multistart/perturb.py`)。
- 🟡 `high_r_threshold: float = 30.0` — 両仮説高 R 判定の Rwp 閾値 (%)。
  `src/tsumugin/selection/engine.py::detect_escalations` の既定 30.0 と一致。
- 🟡 `seq_max_cycles: int = 10` — 区間内逐次 direct refine のサイクル上限
  (`SequentialConfig.seq_max_cycles` と同値の先例)。

### 2.2 discriminate_interval（公開関数）

- 🔵 **シグネチャ** (interfaces.py L274-284):
  ```python
  def discriminate_interval(
      backend: RefinementBackend,
      series: FrameSeries,
      frame_range: tuple[int, int],
      initial_phases: tuple[PhaseInstance, ...],
      *,
      config: DiscriminationConfig = DiscriminationConfig(),
      fixed_phases: tuple[FixedPhaseSpec, ...] = (),
      ledger: Ledger | None = None,
      queue: ReviewQueue | None = None,
  ) -> DiscriminationResult: ...
  ```
- 🔵 **入力**:
  - `backend`: `RefinementBackend` Protocol (`name` + `refine(model, *, max_cycles=20)`)。
  - `series`: `FrameSeries` (共通 2θ グリッド + `(n_frames, n_points)` 強度行列、frozen)。
  - `frame_range`: 判別対象区間 `(start, end)`。🟡 両端 inclusive・`0 <= start <= end < n_frames`
    を要求し、範囲外は `ValueError` (器の契約違反、`sequential/series.py` の慣習)。
  - `initial_phases`: 活物質の初期相 (仮説 A の単相起点)。🟡 仮説 A は単相判別のため
    活物質 1 相を想定 (D4「単相 warm-start」)。
  - `fixed_phases`: セル固定相 (`FixedPhaseSpec`)。両仮説に常駐・構造固定・scale のみ解放
    (`fixed_free_suffixes(spec) == ("scale",)`)。
  - `ledger` / `queue`: 省略可能な依存注入。None なら記録/通知スキップ (結果は不変)。

### 2.3 DiscriminationResult（出力・frozen dataclass）

- 🔵 (interfaces.py L260-271):
  - `verdict: Literal["solid_solution", "two_phase", "undecided"]`
  - `delta_evidence: float` — **ΔBIC = Σbic_A − Σbic_B** (bic は小さいほど良い)。
  - `hypothesis_single: Hypothesis` — 仮説 A (**multistart 記録付き**: `metrics.multistart` に
    `{"n","n_basins","n_diverged"}`)。
  - `hypothesis_two_phase: Hypothesis` — 仮説 B (同上)。
  - `multistart_single: MultistartResult` / `multistart_two_phase: MultistartResult` —
    両仮説の端点マルチスタート結果 (basins / n_diverged / is_global_corroborated / promoted)。
  - `escalations: tuple[str, ...]` — 僅差/高 R のエスカレーション文字列 (REQ-101/EDGE-005)。
  - `warnings: tuple[str, ...] = ()`。
- 🟡 **verdict の判定規約** (ΔBIC 符号と Literal の整合、note.md §6-2):
  - `Σbic_A + close_threshold <= Σbic_B` (ΔBIC ≤ −閾値) → `"solid_solution"` (A 優位)。
  - `Σbic_B + close_threshold <= Σbic_A` (ΔBIC ≥ +閾値) → `"two_phase"` (B 優位)。
  - `|ΔBIC| < close_threshold` → `"undecided"` (暫定優位側は delta_evidence の符号で読める。
    追加フィールドは設けない)。
  - **両仮説高 R (EDGE-005)** → `"undecided"` + `escalations` に高 R/未知相を示す文字列
    (verdict Literal に第 4 値はないため「判別なし」= undecided + エスカレーションで表現)。

### 2.4 データフロー（dataflow.md FR-313 シーケンス L53-77）

- 🔵 1. **仮説 A**: `frame_range` の各フレームを warm-start 逐次 direct refine (格子解放:
  `scale` + `lattice.a/b/c`、`max_cycles=config.seq_max_cycles`)。フレームごとの
  `RefinementResult` から `BICBackend.score` で bic を算出し Σbic_A を得る。
  warm start は直近成功フレームの確定 phases (`sequential/engine.py` の先例パターン)。
- 🔵 2. **仮説 B**: 区間端点の A 仮説格子 (start 端 / end 端の精密化済み格子) で端成分 2 相を
  初期化 (🟡 D4 の「端点格子で初期化」)、**格子は free_params に含めず固定**、
  `scale`/`wt_frac` のみ解放で同区間を逐次精密化 → Σbic_B。
- 🔵 3. **マルチスタート必須**: 両仮説の**区間端点フレーム** (start/end) で
  `MultistartEngine(backend, config=config.multistart, ledger=ledger).run(...)` を適用。
  仮説 A は既定 `free_suffixes` (scale+格子)、仮説 B は 🟡 `("scale", "wt_frac")`
  (格子固定を破らない差し替え、note.md §6-3)。basin 情報を `metrics.multistart` へ記録。
- 🔵 4. **判別**: `ΔBIC = Σbic_A − Σbic_B` → §2.3 の規約で verdict。
- 🔵 5. **僅差** (|ΔBIC| < 閾値): `queue.add("close_competitor", ...)` (queue 提供時のみ) +
  verdict=`"undecided"`。**処理はブロックしない** (例外にしない)。
- 🔵 6. **両仮説高 R**: 未知相フラグ + `escalations` (+ queue 提供時 `"all_high_r"` 通知)、判別しない。
- 🔵 7. **ledger 記録**: 全操作 (`discrimination.*` kind 🟡) を追記。`verify()` 常に True。

- **参照したEARS要件**: REQ-010 (両仮説 + マルチスタート + bic 判別), REQ-004 (判別時必須適用),
  REQ-101 (僅差 → 暫定判別 + Queue), REQ-102 (発散除外・全滅縮退), EDGE-005
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L252-284
  (`DiscriminationConfig`/`DiscriminationResult`/`discriminate_interval`)、
  `docs/design/m3-operando/dataflow.md` L53-77 / エラーハンドリング表 (L106-118)、
  実装済み API: `src/tsumugin/multistart/engine.py` (`MultistartEngine`/`MultistartResult`)、
  `src/tsumugin/backends/base.py` (`RefinementModel`/`RefinementResult`/`param_name`)、
  `src/tsumugin/evidence/ic.py` (`BICBackend`)、`src/tsumugin/operando/cell_phases.py`
  (`FixedPhaseSpec`/`fixed_free_suffixes`)、`src/tsumugin/selection/review_queue.py` (`ReviewQueue`)

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (NFR-102/REQ-402)**: 乱数・時刻・集合反復順に依存しない。`MultistartEngine` /
  `SimulatedBackend` は決定論済み。判別側も安定順で組み、**同一入力で 2 回実行するとビット同一**
  (`DiscriminationResult` 全フィールドが `==`)。`Hypothesis.id` は決定論採番
  (先例: `multistart-basin-{order}`)。
- 🟡 **パフォーマンス (NFR-001 / TC-209-03)**: 判別 1 区間 (N=8) < 30 秒 (合成小グリッド)。
  マルチスタートは**区間端点フレームのみ** (全フレームに掛けない)、逐次は direct refine
  (`seq_max_cycles=10`) — architecture.md 非機能 (L127)。
- 🔵 **非破壊性 (P2/NFR-101)**: 入力 `initial_phases`/`series` を破壊しない。`Ledger` は append のみ
  (削除・上書き API なし)、記録後も `ledger.verify()` が常に True (NFR-105)。`ReviewQueue` は追記型。
- 🔵 **失敗の縮退化 (CLAUDE.md 不変条件)**: バックエンド失敗は例外でなく chi2=inf の結果 →
  判別を放棄せず縮退処理。マルチスタート全滅は `MultistartResult.warnings` + 元仮説維持 (REQ-102/EDGE-002)。
  🟡 区間内逐次 refine の非有限フレームは Σbic に混ぜず (非有限漏洩なし)、警告 + 高 R 経路へ縮退
  (全フレーム非有限は EDGE-005 経路)。
- 🔵 **バックエンド非依存 (P7)**: `RefinementBackend` Protocol のみに依存 (GSAS-II 非依存)。
  テストは `SimulatedBackend` + Fake/Spy。
- 🔵 **僅差でブロックしない (REQ-101/FR-403)**: 僅差・高 R でも例外を投げず
  `DiscriminationResult` を返して処理継続。`queue=None` でも動作 (通知スキップ)。
- 🔵 **固定相の粒度 (FR-312/REQ-009)**: `fixed_phases` は両仮説に連結し、固定相 index は
  `("scale",)` のみ解放 (`fixed_free_suffixes`)。固定相の格子は精密化後もビット不変。
- 🔵 **コア依存 numpy のみ (REQ-403)** / **後方互換 (REQ-404)**: 新規モジュール追加のみ。
  既存 API・既存テスト (580 collected) 無改変 green。`operando/__init__.py` `__all__` へ非破壊追記。
- 🔵 **DB/API 制約**: なし (M3 に新規 HTTP API・永続 DB なし — architecture.md L142)。

- **参照したEARS要件**: NFR-001, NFR-101, NFR-102, NFR-105, REQ-101, REQ-102, REQ-402, REQ-403, REQ-404
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` 非機能 (L125-137) / 技術的制約 (L132-137)、
  `CLAUDE.md` (実装上の不変条件 L63-70)、`docs/implements/m3-operando/TASK-0032/note.md` §6

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本使用パターン

- 🔵 **固溶体データ (TC-204-01)**: 単相の格子 a がフレームで連続変化する合成系列
  (`SimulatedBackend.simulate`、乱数なし) → 仮説 A が良く適合し Σbic_A ≪ Σbic_B →
  `verdict == "solid_solution"`。
- 🔵 **二相データ (TC-204-02)**: 端成分 2 相の分率 (scale) が漸移する合成系列 → 仮説 B 優位 →
  `verdict == "two_phase"`。
- 🔵 **マルチスタート必須 (TC-204-03/REQ-004)**: 判別 1 回で `backend.refine` が区間端点の
  マルチスタート分 (両仮説 × 端点 × n_starts) 呼ばれる (spy 検証)。両仮説の
  `metrics.multistart == {"n": 8, "n_basins": K, "n_diverged": D}` が記録される。
- 🔵 **固定相込み (FR-312)**: `fixed_phases=(CELL_PHASE_PRESETS["Be"],)` を渡すと固定相が両仮説に
  常駐し、格子ビット不変・scale のみ動く。

### 4.2 エッジ・エラーケース

- 🔵 **僅差 (TC-204-04/REQ-101)**: |ΔBIC| < 10 → `verdict == "undecided"`、`queue.unresolved` に
  `"close_competitor"` の ReviewItem が積まれ、**例外なく結果が返る** (ブロックしない)。
- 🔵 **両仮説高 R (TC-204-05/EDGE-005)**: 両仮説の代表 rwp > `high_r_threshold` → 未知相フラグ +
  `escalations` 非空、判別なし (verdict は優位側にしない = `"undecided"`)。
- 🔵 **決定論 (TC-204-06)**: 同一入力で 2 回 `discriminate_interval` → 完全ビット同一。
- 🟡 **マルチスタート一部発散/全滅 (REQ-102/EDGE-002)**: 発散 start は basin から除外・カウント
  (`MultistartResult.n_diverged`)。全滅は警告付きで判別継続 (元仮説維持、クラッシュしない)。
- 🟡 **不正 frame_range**: 範囲外 index・start > end は `ValueError` (器の契約違反)。
- 🟡 **queue/ledger 未提供 (既定 None)**: 通知/記録をスキップして同一の判別結果を返す。
- 🟡 **性能 smoke (TC-209-03)**: 小グリッド合成・区間 N=8 フレームの判別が 30 秒以内。

- **参照したEARS要件**: REQ-010, REQ-101, REQ-102, EDGE-002, EDGE-005
- **参照した設計文書**: `docs/design/m3-operando/dataflow.md` FR-313 シーケンス (L53-77) /
  エラーハンドリング (L106-118)、`docs/spec/m3-operando/acceptance-criteria.md` TC-204-01〜06 (L37-42)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 固溶体 vs 二相反応判別 (FR-313) — operando 電池モードの中核判別。
- **参照した機能要件**:
  - REQ-010: 両仮説をマルチスタート付きで精密化し bic で判別。ΔBIC < 閾値 (既定 10) はエスカレーション 🔵
  - REQ-004: FR-313 判別時はマルチスタート必須適用 🔵
  - REQ-009: 固定相は探索常駐・構造固定・scale のみ解放 🔵
- **参照した非機能要件**:
  - REQ-101: 僅差 → 自動確定せず暫定判別 + Review Queue 通知 🔵
  - REQ-102: 発散 start 除外・カウント、全滅は警告付き継続 🟡
  - NFR-001: 判別 1 区間 < 30 秒 🟡 / NFR-101/105: 非破壊・追記専用 🔵 / NFR-102: ビット同一 🔵
  - REQ-402 (決定論) / REQ-403 (numpy のみ) / REQ-404 (後方互換) 🔵
- **参照したEdgeケース**: EDGE-002 (全滅 → 警告 + 元仮説維持), EDGE-005 (両仮説高 R → 未知相フラグ +
  エスカレーション・判別しない)
- **参照した受け入れ基準**: TC-204-01 (固溶体判別), TC-204-02 (二相判別), TC-204-03 (マルチスタート
  必須 + metrics), TC-204-04 (僅差 → undecided + Queue), TC-204-05 (両仮説高 R), TC-204-06 (決定論),
  TC-209-03 (<30 秒 smoke) — `docs/spec/m3-operando/acceptance-criteria.md` L37-42, L85
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` D4 (L71-76) / 再利用資産 (L47-54) /
    非機能 (L125-137)
  - **データフロー**: `docs/design/m3-operando/dataflow.md` FR-313 判別のシーケンス (L53-77) /
    全体フロー (L10-35) / エラーハンドリング (L106-118)
  - **型定義**: `docs/design/m3-operando/interfaces.py` L252-284
  - **データベース / API 仕様**: なし (M3 対象外)
  - **依存実装 (実 API)**: `src/tsumugin/multistart/engine.py`, `src/tsumugin/multistart/perturb.py`,
    `src/tsumugin/operando/cell_phases.py`, `src/tsumugin/sequential/series.py`,
    `src/tsumugin/sequential/engine.py` (warm-start 先例), `src/tsumugin/evidence/ic.py`,
    `src/tsumugin/selection/review_queue.py`, `src/tsumugin/backends/base.py`,
    `src/tsumugin/backends/simulated.py`, `src/tsumugin/store/ledger.py`,
    `src/tsumugin/model/hypothesis.py`

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: ほぼなし (契約は interfaces.py L252-284 に確定、完了条件 7 項目が TC-204/209 に 1:1 対応)
- 入出力定義: 完全 (DiscriminationConfig / DiscriminationResult / discriminate_interval の型・既定値が確定)
- 制約条件: 明確 (決定論 / 非破壊 / ブロックしない / 端点のみマルチスタート / <30 秒が仕様由来)
- 実装可能性: 確実 (MultistartEngine / FixedPhaseSpec / FrameSeries / BICBackend / ReviewQueue の
  実装済み API のみで構成可能)
- 信頼性レベル: 🔵 が支配的 (🟡 は verdict 符号規約・仮説 B の free_suffixes・非有限フレームの
  縮退・frame_range 検証・ledger kind 等の実装裁量に集中。いずれも要件へ遡及可能)
```

**残る🟡判断ポイント (tdd-testcases / tdd-red で確定)**:
- 仮説 B の端成分初期化の具体 (start 端/end 端の A 格子をどう 2 相へ配るか、初期 scale/wt の値)。
- 仮説 B のマルチスタート `free_suffixes` (`("scale","wt_frac")` が SimulatedBackend `_SCALAR_KEYS` に整合)。
- EDGE-005 の判定位置 (端点マルチスタート代表 rwp か区間逐次の代表 rwp か) と escalations 文字列。
- 逐次 refine 非有限フレームの縮退 (除外 + 警告 / EDGE-005 経路) の細部。
- ledger の kind 文字列 (`"discrimination.*"` 前置) と payload スキーマ。

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m3-operando TASK-0032` でテストケースの洗い出しを行います。
