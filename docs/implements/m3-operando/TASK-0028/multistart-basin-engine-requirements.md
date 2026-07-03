# TASK-0028 TDD要件定義: multistart/basin + MultistartEngine (FR-230/232)

**要件名**: m3-operando / **タスクID**: TASK-0028 / **機能名**: multistart-basin-engine
**タイプ**: TDD / **推定 5h** / **フェーズ**: Phase 2
**前提**: TASK-0026 / TASK-0027 (perturb 完了) / **後続**: TASK-0032 / TASK-0033
**信頼性サマリー**: 🔵 5 / 🟡 1 (FR-230/232 / 設計 D2/D3 / REQ-002〜006・102 / AC TC-201-02〜06)

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 候補仮説の初期値を系統摂動した N 本の独立精密化を実行し、収束解を
  **パラメータ空間で basin (吸引域) にクラスタリング**して、大域最適の傍証／多峰性を報告する
  マルチスタート大域最適確認エンジン。2 サブモジュールで構成:
  - `src/tsumugin/multistart/basin.py`: 収束解を正規化パラメータ距離 (< `basin_rel_tol`) で
    **union-find クラスタ**し、各クラスタを `BasinInfo` (代表 = chi2 最小解) にまとめる。
  - `src/tsumugin/multistart/engine.py`: `MultistartEngine.run` が `generate_starts` (TASK-0027) →
    各 start の `backend.refine` (direct) → 発散除外 → basin クラスタ → `MultistartResult` を返す。
    複数 basin は `Hypothesis` へ昇格 (`metrics.multistart` 付き)、全操作を ledger 記録。

- 🔵 **どのような問題を解決するか**: 単一初期値からの Rietveld 精密化は局所最適に捕われうる。
  複数の摂動初期値から収束させ basin を数えることで、(a) 単一 basin なら「大域最適の傍証あり」、
  (b) 複数 basin なら多峰性を隠さず各解を別仮説として evidence 比較へ回す。FR-313 判別
  (固溶体 vs 二相) の信頼性をこのマルチスタートで担保する。

- 🔵 **想定されるユーザー**: (直接) FR-313 判別エンジン (TASK-0032, `discrimination.py`) と
  accepted 候補の最終精密化フロー。(間接) 自動解析パイプライン・エージェント・人間レビュアー。

- 🔵 **システム内での位置づけ**: `multistart` 層 (FR-230〜234)。上流は `perturb.py` (決定論摂動列)、
  下流は `RefinementBackend` (精密化) / `BICBackend` (evidence) / `Hypothesis` (昇格) / `Ledger` (記録)。
  汎用エンジンとして提供し、判別ロジック自体は持たない (TASK-0032 が消費)。

- **参照したEARS要件**: REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-102, FR-230, FR-232, FR-234
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D2 (L62-64) / D3 (L66-69) /
  モジュール表 (L35-36)、`docs/design/m3-operando/interfaces.py` L143-191

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 basin.py（basin クラスタリング）

- 🔵 **入力**:
  - `results: Sequence[RefinementResult]` — 各 start の収束解 (発散を除いた有限 chi2 のもの、
    または全件で内部的に発散除外)。`RefinementResult` は
    `(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params, globals, warnings)`。
  - `basin_rel_tol: float` (キーワード専用, 既定 1e-2) — 正規化相対距離の同一 basin 閾値。
  - (必要に応じ) 各 start の初期値 phases / start index — 正規化 (初期値スケールで無次元化) の基準。
- 🔵 **出力**: `tuple[BasinInfo, ...]` (evidence 昇順)。`BasinInfo` =
  `(representative: RefinementResult, member_starts: tuple[int, ...], chi2: float, evidence: float)`。
  - `representative`: クラスタ内 chi2 最小解 (同点は start index 小優先で決定論)。
  - `member_starts`: 属する start index 群 (昇順)。
  - `chi2`: 代表の chi2。 `evidence`: 代表の bic (`BICBackend`)。
- 🟡 **入出力関係**: 収束解を正規化パラメータベクトルへ変換 (格子は相対、scale は対数比、占有率は差分) →
  相対距離 < `basin_rel_tol` を union-find で連結 → クラスタごとに代表・evidence を算出 → evidence 昇順。
  空入力は空タプルへ縮退 (例外化しない)。

### 2.2 engine.py（MultistartEngine）

- 🔵 **コンストラクタ**: `MultistartEngine(backend: RefinementBackend, *,
  config: MultistartConfig = MultistartConfig(), ledger: Ledger | None = None)`。
- 🔵 **run シグネチャ**: `run(phases: tuple[PhaseInstance, ...], two_theta: np.ndarray,
  intensity: np.ndarray, *, free_suffixes: tuple[str, ...] =
  ("scale", "lattice.a", "lattice.b", "lattice.c"), weights: np.ndarray | None = None) -> MultistartResult`。
- 🔵 **出力 `MultistartResult`** =
  `(basins: tuple[BasinInfo, ...], n_starts: int, n_diverged: int, promoted: tuple[Hypothesis, ...],
    is_global_corroborated: bool, warnings: tuple[str, ...] = ())`:
  - `basins`: evidence 昇順の basin 群 (発散除外後)。
  - `n_starts`: 実行 start 総数 (= `config.n_starts`)。
  - `n_diverged`: 発散除外した start 数。
  - `promoted`: **複数 basin 時のみ** 各 basin を昇格した `Hypothesis` 群 (単一 basin なら空)。
  - `is_global_corroborated`: `n_basins == 1` (単一 basin = 大域最適の傍証あり)。
  - `warnings`: 全滅時の警告等。
- 🔵 **データフロー** (dataflow / D2/D3):
  1. `generate_starts(phases, config=config)` で N 組の初期値 (i=0 無摂動)。
  2. 各 start を `RefinementModel(phases_i, free_params, two_theta, intensity, weights)` に包み
     `backend.refine(model, max_cycles=config.ms_max_cycles)` を **direct** で呼ぶ (純関数ループ = map 置換可能)。
     `free_params` は `free_suffixes` × 各相 index を `param_name(j, suffix)` で構築。
  3. `math.isfinite(result.chi2)` が False の start を除外し `n_diverged` に加算。
  4. 残りを `cluster_basins(..., basin_rel_tol=config.basin_rel_tol)` で basin 化。
  5. 単一 basin → `is_global_corroborated=True`, `promoted=()`。複数 basin → 各 basin を `Hypothesis`
     へ昇格 (`metrics.multistart={"n":N,"n_basins":K,"n_diverged":D}`)、`promoted` に evidence 昇順。
  6. 全滅 (残 0) → `basins=()`, `warnings` に警告, `is_global_corroborated=False`, `promoted=()` (元仮説維持)。
  7. `ledger` 提供時は各操作を `append("multistart.*", {...})` で記録 (追記のみ)。

- **参照したEARS要件**: REQ-002 (basin 報告), REQ-003 (昇格/傍証), REQ-005 (純関数), REQ-006 (metrics), REQ-102 (発散除外)
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L143-191 (`BasinInfo`/`MultistartResult`/
  `MultistartEngine`), `src/tsumugin/backends/base.py` (`RefinementModel`/`RefinementResult`/`param_name`),
  `src/tsumugin/evidence/ic.py` (`BICBackend`), `src/tsumugin/model/hypothesis.py`
  (`Hypothesis`/`RefinementMetrics.multistart`)

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (NFR-102 / REQ-402)**: `random`/`np.random` 不使用。start 順・union-find (根は index 小へ寄せる)・
  代表選出 (chi2 同点は start index 小)・basins ソート (evidence 同点は代表 start index 小) すべて安定順。
  **同一入力で 2 回 `run` するとビット同一** (basins / member_starts / promoted すべて `==`)。
- 🔵 **非破壊性 (P2 / NFR-101 / REQ-404)**: 入力 `phases` を破壊しない。`Ledger` は `append` のみ
  (削除・上書き API を実装しない)。`RefinementMetrics.multistart` は既定 None の非破壊フィールド (TASK-0025 済) を使う。
- 🔵 **ledger 追記専用 + ハッシュチェーン (NFR-105)**: `ledger` 提供時、記録後も `ledger.verify()` が常に True。
  `ledger=None` なら記録スキップ (エンジンは ledger 非依存で動作)。
- 🔵 **精密化はバックエンド非依存 (P7)**: `RefinementBackend` Protocol のみに依存。テストは FakeBackend (GSAS-II 非依存)。
- 🔵 **失敗の縮退化**: バックエンド失敗は例外でなく **chi2=inf の結果** に変換し発散除外で処理
  (CLAUDE.md 不変条件)。空入力・全滅は例外化せず縮退値 (空 basins) へ。
- 🔵 **direct refine (D2)**: 各 start は `backend.refine` を **1 回だけ** (staged 解放ループなし)、
  `max_cycles=config.ms_max_cycles` (既定 15) で呼ぶ。探索モード精密化と同等コストに抑える (FR-234)。
- 🔵 **コア依存 numpy のみ (REQ-403)**: 正規化距離計算は numpy or math。追加依存禁止。
- 🟡 **パフォーマンス (NFR-001)**: 判別は区間端点のみマルチスタート・direct refine で単一判別 < 30 秒
  (合成小グリッド)。本エンジン自体は N 回 refine の逐次実行 (M3 は並列化しない、REQ-005 は map 置換可能な構造まで)。
- 🔵 **後方互換 (REQ-404)**: 既存 API・既存テストを無改変。新規シンボルは `multistart/__init__.py` の
  `__all__` へ非破壊追記。

- **参照したEARS要件**: NFR-102, NFR-101, NFR-105, NFR-001, REQ-402, REQ-403, REQ-404, REQ-005
- **参照した設計文書**: `docs/design/m3-operando/architecture.md` D2/D3 (L62-69) / 非機能 (L125-137)、
  `CLAUDE.md` (実装上の不変条件), `src/tsumugin/store/ledger.py` (append/verify),
  `src/tsumugin/search/clustering.py` (`_UnionFind` 決定論パターン)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本使用パターン

- 🔵 **単峰 (TC-201-02 / EDGE-001)**: 全 start が同一解へ収束 → `n_basins == 1`,
  `is_global_corroborated == True` (「大域最適の傍証あり」), `promoted == ()`。
- 🔵 **双峰 (TC-201-03)**: 2 つの局所解を持つ初期値域 → `n_basins == 2`, 各 `BasinInfo` の
  chi2/evidence を報告。basins は evidence 昇順。
- 🔵 **複数 basin 昇格 (TC-201-04 / FR-232)**: 複数 basin が各々 `Hypothesis` へ昇格され `promoted` に入り
  evidence で rank 可能 (多峰性を隠蔽しない、REQ-003)。
- 🔵 **metrics 記録 (TC-201-06 / REQ-006)**: 仮説の `metrics.multistart` に `{"n","n_basins","n_diverged"}`
  が記録される。

### 4.2 エッジ・エラーケース

- 🟡 **発散 start 除外 (TC-201-05 / REQ-102 / EDGE-002)**: chi2=inf の start は basin から除外し `n_diverged`
  にカウント。**全滅** (全 start 発散) → `warnings` に警告 + `basins == ()` (元仮説維持) +
  `is_global_corroborated == False` + `promoted == ()`。
- 🟡 **N=1 縮退 (TC-201-07 / EDGE-101)**: `config.n_starts == 1` → 摂動なし 1 本 (基準解のみ)、`n_basins == 1`。
- 🔵 **空/縮退**: basin クラスタへの入力が空 (全滅後) → 空タプルへ縮退、例外を投げない。
- 🔵 **決定論再実行**: 同一 `(phases, two_theta, intensity, config)` で 2 回 `run` → 完全ビット同一。

- **参照したEARS要件**: EDGE-001, EDGE-002, EDGE-101, REQ-102
- **参照した設計文書**: `docs/design/m3-operando/dataflow.md` (マルチスタートフロー)、
  `docs/spec/m3-operando/acceptance-criteria.md` TC-201-02〜07

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: マルチスタート大域最適確認 (FR-230) — 局所最適回避・多峰性の可視化。
- **参照した機能要件**:
  - REQ-002: 収束解のパラメータ空間クラスタリング / basin 数・chi2・evidence・代表解の報告 🔵
  - REQ-003: 複数 basin → 別仮説昇格 (evidence 比較) / 単一 basin → 傍証あり報告 🔵
  - REQ-004: 適用範囲は設定可能 (既定: accepted 最終精密化 + FR-313 判別で必須) 🔵
  - REQ-005: 各 start は独立な純関数構成 (map 置換可能、Worker 並列化非阻害) 🔵
  - REQ-006: `RefinementMetrics.multistart {n, n_basins}` として仮説に記録 (非破壊) 🔵
- **参照した非機能要件**:
  - REQ-102: 発散 (chi2=inf) start は basin から除外しカウント報告 🟡
  - REQ-402: マルチスタート出力は同一入力でビット同一 🔵
  - REQ-403: コア依存は numpy のみ 🔵 / REQ-404: 非破壊追加 🔵
  - NFR-001: 単一判別 < 30 秒 🟡 / NFR-101: 非破壊性 🔵 / NFR-102: 決定論 🔵 / NFR-105: ledger 追記+検証 🔵
- **参照したEdgeケース**: EDGE-001 (単一 basin 傍証), EDGE-002 (発散全滅→警告+元仮説維持), EDGE-101 (N=1 縮退)
- **参照した受け入れ基準**: TC-201-02 (単峰/傍証), TC-201-03 (双峰/両 basin 報告), TC-201-04 (昇格/rank),
  TC-201-05 (発散除外/全滅警告), TC-201-06 (metrics 記録), TC-201-07 (N=1 縮退) —
  `docs/spec/m3-operando/acceptance-criteria.md` L14-20
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` D2 (direct refine, L62-64) /
    D3 (basin クラスタ, L66-69) / モジュール表 (L35-36) / 非機能 (L125-137)
  - **データフロー**: `docs/design/m3-operando/dataflow.md` (マルチスタートフロー)
  - **型定義**: `docs/design/m3-operando/interfaces.py` L143-191
    (`BasinInfo` L143-151 / `MultistartResult` L153-162 / `generate_starts` L165-169 / `MultistartEngine` L172-191)
  - **依存実装**: `src/tsumugin/multistart/perturb.py` (generate_starts/MultistartConfig),
    `src/tsumugin/backends/base.py` (RefinementModel/RefinementResult/param_name),
    `src/tsumugin/evidence/ic.py` (BICBackend), `src/tsumugin/model/hypothesis.py`
    (Hypothesis/RefinementMetrics.multistart), `src/tsumugin/store/ledger.py` (Ledger),
    `src/tsumugin/search/clustering.py` (`_UnionFind` パターン)

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (契約は interfaces.py L143-191 に確定、完了条件は TC-201-02〜06 に 1:1 対応)
- 入出力定義: 完全 (BasinInfo / MultistartResult / MultistartEngine.run のシグネチャ・型が確定)
- 制約条件: 明確 (決定論 / 非破壊 / direct refine / 発散縮退 / ledger 追記が仕様由来で確定)
- 実装可能性: 確実 (perturb / clustering(_UnionFind) / BICBackend / Ledger の既存 API で構成可能)
- 信頼性レベル: 🔵 が支配的 (🟡 は basin 正規化距離式の詳細と N=1/発散全滅の細部のみ)
```

**残る🟡判断ポイント (tdd-testcases / tdd-red で確定)**:
- 正規化パラメータベクトルの構成 (格子相対 / scale 対数比 / 占有率差分) と距離ノルム (L2 / L∞)、
  `basin_rel_tol` の具体的意味づけ (D3 は「正規化相対距離 < tol」まで、式は 🟡)。
- `basin.py` の公開関数シグネチャ (例 `cluster_basins(results, *, basin_rel_tol)`、初期値 phases を
  渡すか代表 index 群をどう受けるか) — interfaces.py は `BasinInfo` のみ規定、関数名は本タスク裁量。
- ledger の `kind` 文字列と payload スキーマ (例 `"multistart.start"` / `"multistart.basin"` / `"multistart.promote"`)。

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m3-operando TASK-0028` でテストケースの洗い出しを行います。
