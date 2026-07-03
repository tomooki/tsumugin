# m2-sequential 開発コンテキストノート

## 作成日時
2026-07-03

## プロジェクト概要

### プロジェクト名
Tsumugin — 多仮説・全自動 Rietveld 解析プラットフォーム

### プロジェクトの目的
粉末回折(X線・中性子)の相同定・多相 Rietveld 精密化・時系列(operando / in situ 高温)解析を、
**AI エージェントと人間の介入点を明示的に設計した上で**全自動化する。Dara の中核思想
(多仮説主義 / 精密化の前倒し / null hypothesis testing / 解釈可能性)を継承し、精密解析・
operando・高温・joint・MEM へ拡張する。バックエンドは GSAS-II (`GSASIIscriptable`)。

**本ノートの対象マイルストーン = M2**(仕様 §13 の行: 「シーケンシャル基盤+高温モード+ledger/snapshot+最終選択2モード」):
> (1) シーケンシャル基盤 FR-301〜306 / (2) 高温モード FR-321〜323(FR-324/325 は外部委譲出口のみ) /
> (3) ledger・snapshot 永続化(P2 / NFR-101 / NFR-105 を維持したまま)/
> (4) 最終選択 2 モード FR-402/403 + Review Queue 最小版(FR-421 縮小版)

**スコープ外(M3 以降)**: Operando 電気化学同期・吸収補正・FR-313/316 固溶体/二相判別・マルチスタート(M3)、
joint/ChemPlausibility/MCP(M4)、nested/MEM/OED(M5)。M2 では operando の CellConfig / ExternalChannel(echem)、
FR-317 吸収補正は扱わない(温度チャネル同期 FR-321 に必要な範囲のみ ExternalChannel 相当を導入)。

**参照元**: `README.md`, `CLAUDE.md`, `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`(仕様の正)

## 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12(uv 管理, src layout + hatchling ビルド)
- **数値**: numpy >= 1.26(コア)。GSAS-II は optional extra `gsas`(scipy / pycifrw / requests)
- **ランタイム**: CPython 3.12。Rietveld バックエンド = GSAS-II 2.0(`from GSASII import GSASIIscriptable`、導入済み)
- **Web UI(M1 導入済)**: FastAPI + uvicorn(optional extra `web`)。read-only。M2 は Review Queue 最小版をここに追加
- **永続化(M2 新規)**: 未選定。仕様 §3 Data Layer は Project Store = **HDF5 + SQLite**。M2 で ledger/snapshot 永続化を実装時に確定
  (**追記専用 + ハッシュチェーン + 非破壊 revert の不変条件を保ったまま**シリアライズ層を足す。削除/上書き API は作らない)

### アーキテクチャパターン
- **スタイル**: レイヤ分離(Interfaces / Agent / Orchestrator / Workers / Data、仕様§3)。境界はすべて
  `typing.Protocol` で抽象化しバックエンド交換可能(P7)
- **設計パターン**: frozen dataclass の不変値オブジェクト + `with_updates()` / `dataclasses.replace()` による非破壊更新。
  全状態遷移は追記専用 Ledger(ハッシュチェーン)+ SnapshotStore(revert 可能)に記録(P2 / NFR-101 / NFR-105)
- **ディレクトリ構造(実装済み)**:
  ```
  src/tsumugin/
  ├── model/       # project.py(Project/Dataset/Frame/HistogramRef), phase.py(PhaseInstance/LatticeParams),
  │                #   hypothesis.py(Hypothesis/RefinementMetrics)
  ├── backends/    # base.py(RefinementBackend Protocol/RefinementModel/RefinementResult/param_name/parse_param)
  │                #   + simulated.py(SimulatedBackend) + gsasii.py(GSASIIBackend)
  ├── refinement/  # staged.py(StagedRefinementEngine/Stage/RefinementReport/DEFAULT_STAGE_TEMPLATE) + guardrails.py
  ├── evidence/    # base.py(EvidenceBackend Protocol/EvidenceResult) + ic.py(BICBackend/AICBackend) + ranking.py(rank)
  ├── store/       # ledger.py(Ledger/LedgerEntry) + snapshot.py(SnapshotStore/Snapshot) ← いずれもインメモリ
  ├── search/      # peaks/matcher/clustering/pruning/tree(HypothesisTreeSearch/SearchConfig/SearchResult) — M1
  ├── export/      # gpx.py(export_gpx) — M1
  ├── webui/       # app.py(create_app/serve, read-only FastAPI) — M1
  └── pipeline.py  # analyze_single_pattern(単一パターン自動多相精密化) — M0
  tests/           # 実装ファイルと 1:1、GSAS-II 依存は @pytest.mark.gsas(現状 19 テストファイル)
  docs/spec/       # kairo 要件・設計・タスク(本ノートを含む)。docs/dev/plans/ は dev/kairo 実装計画
  ```

**参照元**: `CLAUDE.md`(アーキテクチャ表), `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`§3〜§4

## 開発ルール

### プロジェクト固有のルール(必須・違反禁止)
- **TDD 厳守**: Red(失敗テスト)→ Green(最小実装)→ Refactor。テストなしの実装コミット禁止
- **タスク毎コミット**: kairo/dev のタスク 1 件完了(テスト green)ごとに 1 コミット。**git commit はユーザー判断(本セッションでは commit 禁止)**
- **ブランチ運用**: マイルストーン毎にブランチ。現在 `milestone/m2-sequential`。完了時に PR → `/pr-review-cycle`
  (HIGH 以上の指摘ゼロまで)→ マージはユーザー判断
- **モデル指定**: kairo/dev の全エージェント(サブエージェント含む)を Opus で実行する
- **成果物の保存先**: 要件定義・設計・タスク分割は `docs/` 配下

### コーディング規約
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE
- **型チェック**: 型注釈必須(`any` 回避)。境界は `typing.Protocol`(`@runtime_checkable`)
- **コメント/docstring**: 日本語 docstring 可。FR/NFR/REQ 番号を docstring に紐づける慣習
- **フォーマット/Lint**: `uvx ruff check src tests`(line-length 100, target py312)
- **データモデリング**: frozen dataclass 基本。更新は新インスタンス生成 + Snapshot 追記のみ

### テスト要件
- **フレームワーク**: pytest >= 8 + pytest-cov(+ httpx, dev グループ)。設定は `pyproject.toml [tool.pytest.ini_options]`
- **コマンド**: `uv run pytest`(既定)/ `uv run pytest --cov=tsumugin` / `uv run pytest -m gsas`(GSAS-II 契約)
- **依存導入**: `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるため禁止**)。Web は `--extra web` 併用
- **現状ベースライン**: **223 passed / 3 skipped**(GSAS-II 導入済み。M0 実績 cov 95%)
- **マーカー**: `gsas`(GSAS-II 導入環境でのみ実行、未導入は自動 skip)。実装ファイルと 1:1 の `tests/test_*.py`

**参照元**: `CLAUDE.md`(開発ワークフロー/規約/不変条件), `docs/dev/context.md`, `pyproject.toml`
(注: `AGENTS.md`, `docs/rule/`, `docs/rule/kairo/`, `README` 以外の追加ルールファイルはいずれも**不在** — 規約は CLAUDE.md に集約)

## 既存の要件定義

### 要件定義書
M2 専用の要件定義書(`docs/spec/m2-sequential/requirements.md` 等)は**未作成**(本ノートの後工程 kairo-requirements で作成)。
正の要件は `docs/tsumugin_spec_v0.3.md` の FR/NFR 番号。M2 スコープに対応する主要 FR を以下に抜粋する。

**参照元**: `docs/tsumugin_spec_v0.3.md`§7(FR-300/320), §8(FR-400/420), §13(M2 行)

### 主要な機能要件(M2 スコープ、仕様 FR 番号)
- **FR-300 シーケンシャル共通基盤**
  - FR-301: warm start(継承対象は戦略で指定)。前フレームの精密化結果を次フレーム初期値に継承
  - FR-302: GSAS-II ネイティブ sequential モードと独自オーケストレーションの**選択制**
  - FR-303: changepoint 検出 — 残差時系列・格子微分・新規未マッチピークの**複合指標**(新規アルゴリズム)
  - FR-304: changepoint 近傍のみ残差ピークに対する**局所木探索**(M1 `HypothesisTreeSearch` を近傍で再利用)
  - FR-305: 相ライフサイクル(birth/death + 確信度、ヒステリシスで点滅抑制)
  - FR-306: 相トラジェクトリグラフ、格子 ±σ トラジェクトリ、R 値時系列の出力
- **FR-320 高温シーケンシャルモード**
  - FR-321: 温度チャネル同期(`Dataset.sequence_axis="temperature"` / `Frame.axis_value` / ExternalChannel 相当)
  - FR-322: 熱膨張ベースライン分離(多項式 / Debye-Grüneisen 近似)
  - FR-323: 相転移検出と転移温度(onset / midpoint)±σ。**区間分割は FR-316 の枠組みを温度軸で再利用**
  - FR-324: 等温セグメントの α(t) 抽出 — **JMAK 等は外部委譲、parquet/CSV 出力のみ(M2 は出口のみ)**
  - FR-325: 反応経路グラフ自動構成 + 外部予測モジュール(FR-412)照合フック — **照合フック=出口のみ(M2)**
- **FR-402/403 最終選択の 2 モード + エスカレーション**
  - FR-402: `final_selection_mode`(`Project` に実装済フィールド)。`agent`=AI が根拠付きで `accepted` 化(revert 可)/
    `human`=推奨提示のみ、`accepted` 化は人間操作。モードは実行中いつでも切替可・ledger 記録
  - FR-403: エスカレーション条件(両モード共通)= 全仮説高 R 値 / 未知相フラグ / 僅差競合(ΔlogZ < 閾値)/
    ガード 3 連続発動 / 吸収補正の経験推定モード発動。**`agent` でも Review Queue に通知(処理はブロックしない:暫定裁定+要確認フラグ)**
- **FR-421 Review Queue(最小版)**: エスカレーション・要確認フラグ・`human` モードの裁定待ちを列挙。モバイル要約カード
  (M2 は M1 read-only Web UI への最小追加。FR-422 diff / FR-423 裁定反映 / FR-424 遡及リンクの縮小版で足りる部分を実装)

### 主要な非機能要件
- **NFR-101 / P2**: 破壊的操作の API 非実装。全出力追記型(**永続化層でも削除・上書き API を作らない**)
- **NFR-102**: 再現性 — 乱数種固定でビット同一。GSAS-II はノイズ付き Yobs でなく Ycalc を使う
- **NFR-103**(参考・努力目標): シーケンシャル**非探索区間 ≤ 10 秒/フレーム**、単一パターン(候補 300 相)中央値 ≤ 3 分
- **NFR-105**: ledger 追記専用 + ハッシュチェーン(`verify()` が常に True)。**永続化後も verify() を維持**
- **NFR-106**: GSAS-II バージョン固定 + contract test。**NFR-107**: σの由来をレポートに明示

## 既存の設計文書

### アーキテクチャ設計
`docs/design/` は未作成(kairo-design で生成予定)。設計の実体は M0/M1 実装(`src/tsumugin/`)。
M2 は M0/M1 の抽象境界(`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore` / `HypothesisTreeSearch`)を
共有インターフェースとして再利用し、その上に**フレーム列オーケストレーション層**を新設する。

### データフロー(M2 が新設する層のイメージ)
```
Dataset(kind="sequence", sequence_axis="temperature"/…, frames=[Frame(axis_value=T_i)])
  └─> SequentialOrchestrator(新設, FR-300)
        frame i ごと:
          warm start(前フレーム PhaseInstance 継承, FR-301)
            → StagedRefinementEngine.run または backend 側 sequential(FR-302 選択制)
            → SnapshotStore.save + Ledger.append(理由付き)
          複合指標で changepoint 判定(残差/格子微分/新規未マッチ, FR-303)
            → changepoint 近傍のみ HypothesisTreeSearch で局所再探索(FR-304)
          相ライフサイクル更新(birth/death + confidence, ヒステリシス, FR-305)
        └─> トラジェクトリ出力(相系譜グラフ / 格子±σ(axis) / R 値時系列, FR-306)
              + 高温: 熱膨張ベースライン分離(FR-322) + 転移温度 onset/midpoint±σ(FR-323)
              + 外部委譲出口: α(t) parquet/CSV(FR-324) / 反応経路グラフ・照合フック(FR-325)
  └─> 最終選択(final_selection_mode, FR-402) + エスカレーション → Review Queue(FR-403/421)
```

### 型/インターフェース定義(**実 API 署名を検証済み** — 2026-07-03 時点のソース)

M2 が依存・拡張する M0/M1 の実インターフェース(すべて frozen dataclass / Protocol):

- **backends**(`backends/base.py`):
  - `RefinementBackend`(Protocol, `@runtime_checkable`): `name: str`, `refine(model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult`
    — **注: `simulate` は Protocol に無い**が `SimulatedBackend` / `GSASIIBackend` 双方に実装があり search 層が委譲利用。
    `simulate(phases: Sequence[PhaseInstance], two_theta: np.ndarray) -> np.ndarray`(noise-free Ycalc)
  - `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)`。free_params は `"phase{i}.{suffix}"` 形式
  - `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params=frozenset())`
  - `param_name(phase_index, key) -> str` / `parse_param(name) -> (int, str)`
- **refinement**(`refinement/staged.py`):
  - `StagedRefinementEngine(backend, store: SnapshotStore, ledger: Ledger, *, template=DEFAULT_STAGE_TEMPLATE, config=GuardConfig(), max_retries=3, worsen_tol=1e-9)`
  - `.run(phases, two_theta, intensity, *, weights=None) -> RefinementReport`(FR-301 warm start は「初期 phases に前フレーム結果を渡す」形で活用可)
  - `RefinementReport(final_phases, metrics: RefinementMetrics, stage_outcomes, escalated: bool, free_params=frozenset())` — **`escalated` が FR-403「ガード3連続発動」判定の材料**
  - `DEFAULT_STAGE_TEMPLATE`: scale_bg → lattice_zero → profile → texture → occupancy → coordinates → adp(profile 以降は Simulated では no-op)
- **evidence**(`evidence/base.py`, `ic.py`, `ranking.py`):
  - `EvidenceBackend`(Protocol): `score(metrics: RefinementMetrics) -> EvidenceResult(backend, value, logz_err=None)`
  - `BICBackend`(name="bic", 既定) / `AICBackend`。`rank(hypotheses, backend, *, temperature=1.0, close_threshold=10.0) -> tuple[RankedHypothesis, ...]`
  - `RankedHypothesis(hypothesis, evidence, probability, close_competitor)` — **`close_competitor` が FR-403「僅差競合」判定の材料**
- **search**(`search/tree.py`, M1):
  - `HypothesisTreeSearch(backend, *, evidence=None, config=SearchConfig(), ledger=None, snapshots=None)`
  - `.search(two_theta, intensity, candidates: Sequence[PhaseCandidate|PhaseInstance], *, weights=None) -> SearchResult`
    — **ledger/snapshots を外から注入可能**。FR-304 局所木探索でシーケンシャルの共有 ledger をそのまま渡せる
  - `SearchConfig(max_phases=5, r_improve_pct=2.0, match_tol_deg=0.15, min_peak_height_frac=0.05, prune_min_candidates=4, jaccard_threshold=0.85, explore_max_cycles=5, final_full_refine=True, max_final_refine=3, high_r_threshold=30.0, close_threshold=10.0)`
  - `SearchResult(ranked, hypotheses: Mapping[str,Hypothesis], good_cluster_ids, alternatives, unmatched: UnmatchedPeakReport, final_reports, ledger, snapshots, warnings=())` + `.to_summary() -> dict`(/api/result スキーマ準拠)
  - `UnmatchedPeakReport(unmatched_observed, extra_calculated, unknown_phase_flag)` — **`unknown_phase_flag` が FR-403「未知相フラグ」判定の材料**
- **model**(`model/*.py`, **spec §4 との差分に注意 — 後述**):
  - `Project(id, datasets: tuple[Dataset,...]=(), final_selection_mode: "agent"|"human" = "agent")` — **FR-402 のフィールドは既に定義済**
  - `Dataset(id, kind: "single"|"sequence", frames: tuple[Frame,...]=(), sequence_axis: "none"|"time"|"temperature"|"potential"|"capacity"|"custom" = "none")` — **kind/sequence_axis は M0 定義済・M1 未使用**
  - `Frame(id, index, histograms: tuple[HistogramRef,...]=(), axis_value: float|None = None)` — **`axis_value` は M0 定義済・M1 未使用(温度軸=FR-321 の器)**
  - `HistogramRef(probe, data_ref, instprm_ref=None, bank_id=None)`
  - `Hypothesis(id, phases, parent_id=None, metrics: RefinementMetrics|None = None, status: candidate|refined|accepted|rejected|superseded, accepted_by: agent|human|None = None)`
  - `PhaseInstance(phase_ref, lattice: LatticeParams, scale=1.0, wt_frac=None, occupancies={})` + `.with_updates(**changes)`
  - `LatticeParams(a, b, c, alpha=90, beta=90, gamma=90, sigma: Mapping={})` + `.volume()`
  - `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence: Mapping[str,float]={})`
- **store**(`store/ledger.py`, `snapshot.py` — **いずれもインメモリ**):
  - `Ledger()`: `.append(kind: str, payload: Mapping) -> LedgerEntry` / `.entries -> tuple` / `.verify() -> bool`。**削除・改変 API なし**
  - `LedgerEntry(index, kind, payload, prev_hash, hash)` + `.to_dict()`。`GENESIS_HASH="0"*64`、`_canonical_json`/`_compute_hash`(sha256)で決定論的チェーン
  - `SnapshotStore(ledger: Ledger|None = None)`: `.save(phases, *, label) -> Snapshot` / `.load(id) -> Snapshot` / `.revert(id) -> tuple[PhaseInstance,...]` / `.snapshots` / `.current_id`。revert は前方履歴を消さず現在位置を移すだけ
  - `Snapshot(id, label, phases, parent_id)`
- **webui**(`webui/app.py`, M1): `create_app(result: SearchResult) -> FastAPI`(GET `/`, `/api/result`, `/api/hypotheses/{id}` の read-only 3 本のみ)/ `serve(result, *, host="127.0.0.1", port=8765)`

**参照元(実 API 確認元)**: `src/tsumugin/model/{project,phase,hypothesis}.py`, `backends/base.py`, `backends/simulated.py`,
`refinement/staged.py`, `evidence/{base,ic,ranking}.py`, `search/tree.py`, `store/{ledger,snapshot}.py`, `webui/app.py`, `__init__.py`

### ⚠️ spec §4 データモデルと現行実装の差分(M2 で埋める必要のある要素)
仕様 §4 のエンティティ定義に対し、現行 dataclass は縮約版。M2 の FR に必要な**未実装フィールド/型**は以下:

| 仕様 §4 の要素 | 現行実装 | M2 で必要な FR | 対応方針(推奨) |
|---|---|---|---|
| `Hypothesis.frame_range: [start,end]` | **未定義** | FR-304/305/306(区間仮説) | Hypothesis に optional フィールドを非破壊追加 or 別 dataclass |
| `Hypothesis.refinement_state`(gpx_snapshot_ref) / `provenance: [LedgerRef]` | **未定義** | FR-306 / 監査 | 既存 SnapshotStore.current_id / Ledger と紐付け |
| `PhaseInstance.lifecycle{birth_frame, death_frame, confidence}` | **未定義** | FR-305 相ライフサイクル | lifecycle 用の frozen dataclass を新設し PhaseInstance か Hypothesis に付与 |
| `Frame.axis_value(s)`(複数軸) | `axis_value: float` 単数 | FR-321 温度同期 | 単数で足りるか要確認(温度単軸なら現状可) |
| `ExternalChannel{kind, sync_map}` | **未定義** | FR-321 温度チャネル同期 | temperature チャネルのみ最小実装(echem/CellConfig は M3) |
| `RefinementMetrics.peak_match_score / unmatched_peaks / multistart` | evidence のみ | (multistart は M3) | M2 では既存 evidence で足りる |

### データベース設計 / API 仕様
- **永続化 = M2 の主要新規スコープ**。仕様 §3 Data Layer は Project Store = **HDF5 + SQLite**。現行 Ledger/SnapshotStore は
  インメモリ list のため、M2 で**シリアライズ/デシリアライズ**を追加する。**追記専用 + ハッシュチェーン(NFR-105)+ 非破壊(P2/NFR-101)を保つこと**
  (永続化フォーマット選定は kairo-design/実装時に確定。JSON Lines + SQLite の軽量案から HDF5 まで幅がある)
- REST/MCP は M4(FR-512/513)。M2 の外部境界は Python API + Review Queue を載せた最小 Web UI(FR-421)+ α(t)/経路グラフの CSV/parquet 出口(FR-324/325)

## 関連実装

### M2 が土台にする M0/M1 資産(再利用ポイント)
- **単一パターンのオーケストレーション** — `src/tsumugin/pipeline.py::analyze_single_pattern`
  (フレーム列オーケストレーションはこの構造をフレーム軸へ拡張。ledger/store を共有)
- **段階解放 + ガード + revert** — `src/tsumugin/refinement/staged.py::StagedRefinementEngine.run`
  (FR-301 warm start = 前フレーム `final_phases` を次フレームの初期 phases に渡す。`escalated` を FR-403 材料に)
- **多仮説木探索** — `src/tsumugin/search/tree.py::HypothesisTreeSearch.search`
  (FR-304 changepoint 近傍の局所再探索でそのまま利用。`ledger`/`snapshots` を注入して共有可)
- **ランキング/僅差検出** — `src/tsumugin/evidence/ranking.py::rank`(FR-403 `close_competitor` 材料)
- **未マッチ/未知相** — `search/matcher.py::unmatched_peaks` / `UnmatchedPeakReport.unknown_phase_flag`(FR-403 材料 & FR-303 新規未マッチ指標の素材)
- **追記専用 store** — `store/ledger.py::Ledger` / `store/snapshot.py::SnapshotStore`(永続化を**この上に**足す。API 削除禁止)
- **read-only Web UI** — `webui/app.py::create_app`(Review Queue 最小版をエンドポイント追加で載せる。変更系は ledger 追記経由で非破壊に)
- **GSAS-II 実バックエンド** — `backends/gsasii.py::GSASIIBackend`(FR-302 の「GSAS-II ネイティブ sequential」選択肢の受け皿。現状は単一フレーム refine/simulate)

**参照元**: `src/tsumugin/{pipeline,search/tree,refinement/staged,evidence/ranking,search/matcher,store/ledger,store/snapshot,webui/app,backends/gsasii}.py`

### 参考パターン(M2 でも踏襲)
- **失敗は例外でなく chi2=inf の結果に変換**しガードレール/降格で処理(バックエンド境界の原則)
- **ガード発動・枝刈り・降格・裁定はすべて理由付きで ledger 記録**(FR-214 / FR-424 遡及リンク)
- **エスカレーションは処理をブロックしない**(FR-403: 暫定裁定 + 要確認フラグ。staged エンジンも escalate して次段へ進む設計)
- **決定論的順序**(ledger kind 順・canonical JSON ソート・ID 評価順連番 `hyp-XXXX`)で NFR-102 を担保
- **降格のみ・候補除外しない**(Dara 教訓、ChemPlausibility は M4 だが原則は共通)

### 共通モジュール・ユーティリティ
- `backends/base.py::param_name(i,key)` / `parse_param(name)` — 相インデックス⇔パラメータ名の正準変換
- `store/ledger.py::_canonical_json` / `_compute_hash` — 決定論的ハッシュチェーン(永続化時もこの正準化を再利用)
- `refinement/guardrails.py::GuardConfig` / `check_guards` — 発散/負占有率/格子暴走/負 ADP/相分率ゼロ張り付き検知
- 公開 API は `src/tsumugin/__init__.py::__all__`(アルファベット昇順を維持。`test_m1_symbols_in_dunder_all_and_sorted` が固定)。M2 追加シンボルもここへ

### 依存関係・インポートパス
- 公開 import 例: `from tsumugin import HypothesisTreeSearch, SimulatedBackend, PhaseInstance, LatticeParams, Ledger, SnapshotStore, Project`
- GSAS-II: `from GSASII import GSASIIscriptable`。ソースツリー `C:\Users\tomoo\G2` + venv `gsas2-source.pth` + バイナリ `~/.GSASII/GSASII-bin/win_64_p3.12_n2.2`
- 依存導入は `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるので禁止**)。Review Queue Web には `--extra web` 併用

## 技術的制約

### パフォーマンス制約
- **NFR-103(努力目標)**: シーケンシャル**非探索区間 ≤ 10 秒/フレーム**。changepoint 近傍のみ局所木探索(FR-304)でコストを抑える設計が前提
- warm start(FR-301)で収束を速める。全フレーム cold restart は避け、定期 cold restart で誤り伝播を抑制(§14 リスク緩和)

### セキュリティ制約(= 非破壊性制約 P2 / NFR-101 / NFR-105)
- **破壊的操作(生データ削除・上書き・履歴改変)の API をシステムに実装しない**。永続化層でも Ledger/SnapshotStore に削除・上書きメソッドを追加禁止
- **ledger は追記専用 + ハッシュチェーン。永続化(HDF5/SQLite 等)後も `verify()` が常に True であること**
- 人間裁定(FR-402 `human` / 差し戻し FR-423)・モード切替(FR-402)もすべて**追記 ledger 記録**として表現し、revert 可能に保つ
- Review Queue Web UI に認証はない。既定 `127.0.0.1` バインドを維持(`0.0.0.0` 変更は解析データ全量の無認証公開になる)

### 互換性制約
- Python >= 3.12 固定。GSAS-II バージョン固定 + contract test(NFR-106)
- FR-302 の GSAS-II ネイティブ sequential は `GSASIIscriptable` のシーケンシャル API に準拠する必要(GSASIIBackend は現状単一フレーム)

### データ制約
- chi2/rwp のセマンティクスはバックエンド間で統一(BIC 比較の一貫性)。精密化失敗は chi2=inf の結果に変換
- 温度チャネル同期(FR-321)は `sequence_axis="temperature"` + `Frame.axis_value` を単一温度軸として扱う想定(複数軸は要確認)
- FR-324/325 の外部委譲出口は **parquet/CSV**(JMAK フィッティング・反応経路予測の本体は外部モジュール)

**参照元**: `CLAUDE.md`(実装上の不変条件), `docs/tsumugin_spec_v0.3.md`§3, §7, §11, §14

## 注意事項

### 開発時の注意点
- **spec §4 と実装モデルの差分を先に埋める**(上表): `Hypothesis.frame_range`、`PhaseInstance.lifecycle`(birth/death/confidence)、
  `ExternalChannel`(temperature) は M2 の FR-305/321 に必須。既存 frozen dataclass への**非破壊なフィールド追加 or 別 dataclass**で対応
- **FR-323 の区間分割は「FR-316 の枠組みを温度軸で再利用」**とあるが、FR-316(IC ペナルティ付き changepoint 分割 PELT/binseg)自体は
  §13 上 M3 スコープ。M2 では FR-303 の複合指標 changepoint を基盤に、転移温度 onset/midpoint±σ を出す最小分割で足りるかを
  kairo-requirements で切り分ける(**推奨案で確定**: §15-1 の「k を逐次追加し evidence 改善が閾値未満で打ち切り」方針を温度軸に適用)
- **FR-324/325 は本体実装せず出口のみ**(α(t) の parquet/CSV 出力、反応経路グラフのデータ構造 + FR-412 照合フックのインターフェース定義まで)
- **永続化は「既存インメモリ store の上にシリアライズを重ねる」**方針が安全。Ledger の `_canonical_json`/hash を再利用し、
  ロード後 `verify()==True` をテストで固定する。フォーマット(JSON Lines / SQLite / HDF5)は kairo-design で確定
- FR-302 選択制: 「独自オーケストレーション(既存 StagedRefinementEngine をフレーム列に回す)」を主、
  「GSAS-II ネイティブ sequential」を選択肢として抽象境界を切る。M2 の主実装は独自オーケストレーションで良い

### デプロイ・運用時の注意点
- GSAS-II 起動時の `~/.GSASII/config.ini` 読込警告(cp932)は無害(upstream 表示バグ)
- Review Queue を足す際 `docs/dev/context.md` の Tech Stack / 公開 API を更新すること

### セキュリティ/非破壊上の注意点
- 新規永続化・裁定・モード切替・Review Queue 操作でも**削除/上書き API を作らない**(P2 の構造的保証)。全て追記 + revert
- 相の birth/death 判定・降格・エスカレーションはすべて理由付きで ledger 記録(FR-214 / FR-424)

### パフォーマンス上の注意点
- 非探索区間は warm start + 段階精密化のみで軽量に、changepoint 近傍のみ局所木探索(FR-304)へコストを集中
- ヒステリシス(FR-305)で相の点滅(birth/death 振動)を抑制し、無駄な再探索を減らす

## Git情報

### 現在のブランチ
`milestone/m2-sequential`(clean。`main` = M1 マージ済み 6265266 から分岐)

### 最近のコミット(抜粋)
```
6265266 Merge pull request #1 from tomooki/milestone/m1-hypothesis-search
4b7c508 fix: PR #1 レビュー指摘対応 (XSS シンク排除 / 非有限値の JSON 契約化)
561ffa0 M1 TASK-0010: 公開 API 統合 + E2E + ドキュメント (TDD, 13ケース green)
...(M1 TASK-0001〜0010 / M0 e02275e)
```

### 開発状況
M0 + M1 完了・main にマージ済み。**223 passed / 3 skipped**、GSAS-II 導入済み。
M2 ブランチを切った直後で、これから kairo-requirements → kairo-design → kairo-tasks → kairo-implement を回す。

## 収集したファイル一覧

### プロジェクト基本情報
- `CLAUDE.md`
- `README.md`
- `docs/dev/context.md`
- `pyproject.toml`
- (`AGENTS.md`, `docs/rule/`, `docs/rule/kairo/` は不在 — 規約は CLAUDE.md に集約)

### 仕様書(正)
- `docs/tsumugin_spec_v0.3.md`(FR/NFR の正。M2 = §7 FR-300/320, §8 FR-400/420, §3〜§4 データモデル, §13 M2 行, §15 課題確定状況)

### 参考(M1 の同種成果物)
- `docs/spec/m1-hypothesis-search/{note,requirements,user-stories,acceptance-criteria,prep,interview-record}.md`

### 関連実装(M2 の土台となる M0/M1 資産・実 API 確認済み)
- `src/tsumugin/__init__.py`(公開 API `__all__`)
- `src/tsumugin/model/{project,phase,hypothesis}.py`
- `src/tsumugin/backends/{base,simulated,gsasii}.py`
- `src/tsumugin/refinement/{staged,guardrails}.py`
- `src/tsumugin/evidence/{base,ic,ranking}.py`
- `src/tsumugin/store/{ledger,snapshot}.py`
- `src/tsumugin/search/{tree,matcher,peaks,clustering,pruning}.py`
- `src/tsumugin/{pipeline}.py`, `src/tsumugin/export/gpx.py`, `src/tsumugin/webui/app.py`

---

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
設計文書(`docs/design/*`)・M2 要件定義(`docs/spec/m2-sequential/requirements.md` 等)は本ノートの後工程で生成されます。
