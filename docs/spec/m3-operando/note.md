# m3-operando 開発コンテキストノート

## 作成日時
2026-07-03

## プロジェクト概要

### プロジェクト名
Tsumugin — 多仮説・全自動 Rietveld 解析プラットフォーム

### プロジェクトの目的
粉末回折(X線・中性子)の相同定・多相 Rietveld 精密化・時系列(operando / in situ 高温)解析を、
**AI エージェントと人間の介入点を明示的に設計した上で**全自動化する。Dara の中核思想
(多仮説主義 / 精密化の前倒し / null hypothesis testing / 解釈可能性)を継承し、精密解析・
operando・高温・joint・MEM へ拡張する。バックエンドは GSAS-II (`GSASIIscriptable`、導入済み)。

**本ノートの対象マイルストーン = M3**(仕様 §13 の行:
「Operando モード(電気化学同期・吸収補正・FR-313/316 判別)+マルチスタート」):
> (1) マルチスタート大域最適確認 **FR-230〜234**(§6)/ (2) operando 電池モード **FR-311〜315**(§7)/
> (3) 判別区間の IC 自動分割 **FR-316** / (4) 吸収補正 v1 **FR-317**。
> 併せて既存 Issue **#3**(changepoint 感度較正)・**#4**(thermal onset 意味論)・**#5**(finite_or_none 共有化)を解消する。

**スコープ外(M4 以降)**: 中性子 / マルチヒストグラム joint(FR-240〜245)・ChemPlausibility インターフェース・
MCP server(M4)、nested sampling 裁定・MEM(Dysnomia)・OED 提案・較正済み確率(M5)。
- **FR-122 `nested` 裁定は M5**。M3 の FR-313 は既定 `bic` 一次判定 + マルチスタート(FR-233)までで確定し、
  「競合時 `nested` 裁定」は M5 へ委譲する(境界を要件で明記する)。
- **FR-314 の dQ/dV 重ね描き等の可視化本体は最小限**。M3 は結合出力データ(wt_frac(x)/格子(x)/転移点 x·V±σ)の
  CSV/構造化出力までを主とし、リッチ可視化は Web UI 最小追加に留める。

**参照元**: `README.md`, `CLAUDE.md`, `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`(仕様の正)

## 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12(uv 管理, src layout + hatchling ビルド)
- **数値**: numpy >= 1.26(コア)。GSAS-II は optional extra `gsas`(scipy / pycifrw / requests、導入済み)
- **ランタイム**: CPython 3.12。Rietveld バックエンド = GSAS-II 2.0(`from GSASII import GSASIIscriptable`)
- **Web UI(M1 導入済)**: FastAPI + uvicorn(optional extra `web`、read-only)。M2 で Review Queue 最小版を追加済
- **永続化(M2 導入済)**: JSONL 追記(`PersistentLedger` / `PersistentSnapshotStore`)。追記専用 + ハッシュチェーン + 非破壊 revert
- **M3 新規で検討が要る外部依存(未導入)**:
  - **吸収補正 μt のエネルギー依存計算(FR-317)**: `xraylib` 等(層の組成・厚み・密度 → μt)。
    **GSAS-II と同じ optional extra 方式**(未導入環境では自動 skip / 経験推定モードへ縮退)で足すのが安全。
  - **電気化学同期(FR-311)**: Biologic `.mpr`(独自バイナリ)/ 北斗・HZ / CSV 汎用。
    `.mpr` パーサは重い外部依存になるため **CSV 汎用を第一級**にし、`.mpr` は optional / 後回し可(推奨)。

### アーキテクチャパターン
- **スタイル**: レイヤ分離(Interfaces / Agent / Orchestrator / Workers / Data、仕様 §3)。境界はすべて
  `typing.Protocol` で抽象化しバックエンド交換可能(P7)
- **設計パターン**: frozen dataclass の不変値オブジェクト + `with_updates()` / `dataclasses.replace()` による非破壊更新。
  全状態遷移は追記専用 Ledger(ハッシュチェーン)+ SnapshotStore(revert 可能)に記録(P2 / NFR-101 / NFR-105)
- **ディレクトリ構造(M2 まで実装済み・M3 が土台にする範囲)**:
  ```
  src/tsumugin/
  ├── model/       # project.py(Project/Dataset/Frame/HistogramRef), phase.py(PhaseInstance/LatticeParams/PhaseLifecycle),
  │                #   hypothesis.py(Hypothesis/RefinementMetrics), channel.py(ExternalChannel) ← operando で拡張対象
  ├── backends/    # base.py(RefinementBackend Protocol/RefinementModel/RefinementResult/param_name/parse_param)
  │                #   + simulated.py + gsasii.py
  ├── refinement/  # staged.py(StagedRefinementEngine/RefinementReport/DEFAULT_STAGE_TEMPLATE) + guardrails.py
  ├── evidence/    # base.py(EvidenceBackend Protocol) + ic.py(BICBackend/AICBackend) + ranking.py(rank)
  ├── store/       # ledger.py + snapshot.py(インメモリ) + persistent.py(JSONL) + serialization.py(phase_to/from_dict)
  ├── search/      # peaks/matcher/clustering/pruning/tree(HypothesisTreeSearch) — M1
  ├── export/      # gpx.py(export_gpx) — M1
  ├── webui/       # app.py(create_app/serve, read-only FastAPI + Review Queue) — M1/M2
  ├── sequential/  # engine/changepoint/lifecycle/thermal/trajectory/series — M2(FR-300/320)
  ├── selection/   # engine(FinalSelectionEngine/detect_escalations) + review_queue — M2(FR-402/403/421)
  └── pipeline.py  # analyze_single_pattern(単一パターン自動多相精密化) — M0
  tests/           # 実装ファイルと 1:1、GSAS-II 依存は @pytest.mark.gsas(現状 29 テストファイル)
  docs/spec/       # kairo 要件・設計・タスク(本ノートを含む)
  ```
  **M3 が新設する見込みの層**: `operando/`(電気化学同期 / CellConfig / 吸収補正 / 固溶体-二相判別)、
  `refinement/multistart.py`(FR-230)、`sequential/segmentation.py`(FR-316 IC 分割)+ 共有ユーティリティ `_json.py`(Issue #5)。

**参照元**: `CLAUDE.md`, `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`§3〜§4

## 開発ルール

### プロジェクト固有のルール(必須・違反禁止)
- **TDD 厳守**: Red(失敗テスト)→ Green(最小実装)→ Refactor。テストなしの実装コミット禁止
- **タスク毎コミット**: タスク 1 件完了(テスト green)ごとに 1 コミット。**git commit はユーザー判断(本セッションでは commit 禁止)**
- **ブランチ運用**: マイルストーン毎にブランチ。現在 `milestone/m3-operando`。完了時に PR → `/pr-review-cycle`
  (HIGH 以上の指摘ゼロまで)→ マージはユーザー判断
- **モデル指定**: kairo/dev の全エージェント(サブエージェント含む)を **Opus** で実行する
- **成果物の保存先**: 要件定義・設計・タスク分割は `docs/` 配下

### コーディング規約
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE
- **型チェック**: 型注釈必須(`any` 回避)。境界は `typing.Protocol`(`@runtime_checkable`)
- **コメント/docstring**: 日本語 docstring 可。FR/NFR/REQ 番号を docstring に紐づける慣習(信頼性レベル 🔵🟡🔴 表記)
- **フォーマット/Lint**: `uvx ruff check src tests`(line-length 100, target py312)
- **データモデリング**: frozen dataclass 基本。更新は新インスタンス生成 + Snapshot 追記のみ。**新フィールドは末尾・既定値付きで非破壊追加**(REQ-404)

### テスト要件
- **フレームワーク**: pytest >= 8 + pytest-cov(+ httpx, dev グループ)。設定は `pyproject.toml [tool.pytest.ini_options]`
- **コマンド**: `uv run pytest`(既定)/ `uv run pytest --cov=tsumugin` / `uv run pytest -m gsas`(GSAS-II 契約)
- **依存導入**: `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるため禁止**)。Web は `--extra web` 併用
- **現状ベースライン(タスク提示)**: **430 passed / 3 skipped**(GSAS-II 導入済み。3 skip は未導入環境用 gsas マーカー分)
- **マーカー**: `gsas`(GSAS-II 導入環境でのみ実行、未導入は自動 skip)。M3 で `xraylib` 依存が入るなら**同種の optional マーカー**を検討

**参照元**: `CLAUDE.md`, `docs/dev/context.md`, `pyproject.toml`
(注: `AGENTS.md`, `docs/rule/`, `docs/rule/kairo/` はいずれも**不在** — 規約は CLAUDE.md に集約)

## 既存の要件定義

### 要件定義書
M3 専用の要件定義書(`docs/spec/m3-operando/requirements.md` 等)は**未作成**(本ノートの後工程 kairo-requirements で作成)。
正の要件は `docs/tsumugin_spec_v0.3.md` の FR/NFR 番号。M3 スコープに対応する主要 FR を以下に抜粋する。

**参照元**: `docs/tsumugin_spec_v0.3.md`§6(FR-230), §7(FR-310/316/317), §4(データモデル), §13(M3 行), §15(課題確定)

### 主要な機能要件(M3 スコープ、仕様 FR 番号)
- **FR-230 マルチスタート大域最適確認**(§6, v0.2 新設)
  - FR-231: 最終候補仮説に初期値を**系統摂動**(格子±設定幅 / scale 対数一様 / プロファイル摂動 / 占有率のラテン超方格)した
    **N 本(既定 8–16)**の独立精密化を実行
  - FR-232: 収束解をパラメータ空間でクラスタリング → **basin 数・各 basin の χ²/evidence を報告**。単一 basin=「大域最適の傍証あり」、
    複数 basin=**それぞれを別仮説へ昇格**して evidence 比較に回す(多峰性を隠さない)
  - FR-233: 適用範囲は設定可。**既定 = accepted 候補の最終精密化時 + FR-313 判別時は必須**
  - FR-234: Worker プールで並列化。1 本のコストは探索モード精密化と同等に抑える(**NFR-102 決定論と両立させること**)
- **FR-310 Operando 電池モード**(§7)
  - FR-311: 電気化学同期(Biologic `.mpr` / 北斗・HZ / CSV 汎用)。**容量→組成 x 換算則**を定義可
  - FR-312: セル固定相(Be 窓・Al 集電体・グラファイト等)の**テンプレート管理**
  - FR-313: **固溶体 vs 二相反応の判別** — 同一区間に (a) 単相・格子連続変化 / (b) 二相共存・分率変化 の両仮説を
    **マルチスタート付き(FR-233)**で精密化し Evidence Engine で判別。既定 `bic` 一次判定(**競合時 `nested` 裁定は M5**)
  - FR-314: 電気化学量との**結合出力**(wt_frac(x)、格子(x)、dQ/dV 重ね描き、転移点 x/V±σ)
  - FR-315: **充放電往復のヒステリシス解析**
  - **FR-316 判別区間の自動分割**(v0.2 新設):区間境界を人手で与えず **IC ペナルティ付き changepoint 分割**
    (PELT / binary segmentation、ペナルティ=BIC 項)で区間数と境界を自動決定。各分割仮説(区間数 k=1,2,…)の
    合計 evidence を比較して最良分割を採択。**分割自体も Hypothesis として保存**され代替分割を閲覧・選択可。
    粗い格子スキャン → 境界近傍の細密化の 2 段で計算量を抑える
  - **FR-317 吸収補正 v1**(v0.2 新設・v0.3 改定):
    - **層状(積層)セルは透過法のみ**(反射配置はスコープ外)。キャピラリは円筒吸収モデル
    - **CellConfig(§4)** 入力 → 各層の組成・厚み・密度から μt をエネルギー依存で計算(xraylib 等)→ 透過吸収補正項を初期化
    - 補正パラメータ(**実効 μt**)は**フィット変数として精密化**。CellConfig 由来値は**事前分布/restraint** として拘束。**v1 は実効 μt の 1 パラメータ + restraint で確定**
    - **CellConfig 未提供時は経験的推定モード** — 弱 restraint で精密化 + **レポートに明示警告**(→ FR-403 エスカレーション条件に該当)。推定 μt を提示し CellConfig 入力を促す
    - 充放電に伴う電極の μ 変化はフレーム依存の**緩慢変化として平滑 restraint 付きで追跡**
    - 中性子ヒストグラムには該当吸収/多重散乱補正を**同一インターフェースで切替**
- **参考: FR-320 高温モード(M2 実装済)との接続** — FR-323 は「区間分割は FR-316 の枠組みを温度軸で再利用」。
  M3 で FR-316 を実装したら**温度軸の転移検出(M2 の `estimate_transition`)を FR-316 分割に一般化**できる(Issue #4 とも連動)。

### 主要な非機能要件
- **NFR-101 / P2**: 破壊的操作の API 非実装。マルチスタート basin 昇格・吸収補正・判別も**全て追記 + revert**で表現
- **NFR-102**: 再現性 — **乱数種固定でビット同一**。FR-231 の系統摂動(ラテン超方格等)・FR-234 の並列化でも
  **start ごとの決定論的シード + basin の安定ソート**でビット同一を保つこと(M3 最大の設計上の緊張点)
- **NFR-105**: ledger 追記専用 + ハッシュチェーン(`verify()` 常時 True)。永続化後も維持
- **NFR-107**: σの由来(共分散 / 逐次相関 / **マルチスタート分散**)をレポートに明示 ← FR-230 が直接寄与

## 既存の設計文書

### アーキテクチャ設計
`docs/design/` は本ブランチ時点で未作成(kairo-design で `docs/design/m3-operando/` を生成予定)。
設計の実体は M0/M1/M2 実装(`src/tsumugin/`)。M3 は M0/M1/M2 の抽象境界
(`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore` / `HypothesisTreeSearch` /
`SequentialEngine` / `FinalSelectionEngine`)を共有インターフェースとして再利用し、その上に
**マルチスタート層・operando(電気化学同期/CellConfig/吸収補正/判別)層・IC 区間分割層**を新設する。

### データフロー(M3 が新設する層のイメージ)
```
Dataset(kind="sequence", sequence_axis="potential"/"capacity",
        external_channels=[ExternalChannel(kind="echem", ...)],   # ← §4 に有るが Dataset 未実装(下表)
        cell_config_ref=CellConfig(...))                          # ← §4 に有るが未実装(下表)
  └─> echem 同期(FR-311: .mpr/HZ/CSV → frame_index→(V,I,Q,x)、容量→x 換算則)
  └─> 吸収補正初期化(FR-317: CellConfig→μt(E)、無ければ経験推定モード+警告→FR-403 エスカレーション)
  └─> SequentialEngine(M2)で逐次精密化(warm start + changepoint)
        └─> IC 区間自動分割(FR-316: PELT/binseg + BIC ペナルティ、k 逐次追加で打ち切り)
              各区間で 固溶体 vs 二相 の 2 仮説を
        └─> MultiStart(FR-230: N 本摂動精密化 → basin クラスタリング → 複数 basin は別仮説昇格)
        └─> Evidence(bic 一次判定, FR-313)で (a)単相連続 vs (b)二相共存 を判別
  └─> 結合出力(FR-314: wt_frac(x)/格子(x)/転移点 x·V±σ の CSV)+ ヒステリシス(FR-315)
  └─> 最終選択(FinalSelectionEngine, M2)+ エスカレーション(FR-403: 経験推定モード発動を含む)
```

### 型/インターフェース定義(**実 API 署名を検証済み** — 2026-07-03 時点のソース)

M3 が依存・拡張する M0/M1/M2 の実インターフェース(すべて frozen dataclass / Protocol):

- **backends**(`backends/base.py`) — マルチスタート/吸収補正が回す最下層:
  - `RefinementBackend`(Protocol, `@runtime_checkable`): `name: str`, `refine(model: RefinementModel, *, max_cycles=20) -> RefinementResult`。
    `simulate(phases, two_theta) -> np.ndarray` は Protocol に無いが両実装が持つ(search 層が委譲利用)
  - `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)`。free_params は `"phase{i}.{suffix}"` 形式
  - `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params=frozenset())`
  - `param_name(phase_index, key) -> str` / `parse_param(name) -> (int, str)` ← **FR-317 の μt を free_param に足すならこの命名規約に載せる**
- **refinement**(`refinement/staged.py`) — マルチスタート(FR-230)の 1 本あたりの実行単位:
  - `StagedRefinementEngine(backend, store: SnapshotStore, ledger: Ledger, *, template=DEFAULT_STAGE_TEMPLATE, config=GuardConfig(), max_retries=3, worsen_tol=1e-9)`
  - `.run(phases, two_theta, intensity, *, weights=None) -> RefinementReport(final_phases, metrics, stage_outcomes, escalated, free_params=frozenset())`
  - `DEFAULT_STAGE_TEMPLATE`: scale_bg → lattice_zero → profile → texture → occupancy → coordinates → adp
    (**FR-317 の吸収補正段・restraint はこのテンプレートへ 1 段追加する形が自然**)
  - `refinement/guardrails.py`: `GuardConfig` / `check_guards`(発散/負占有率/格子暴走/負 ADP/相分率ゼロ張り付き検知)
- **evidence**(`evidence/{base,ic,ranking}.py`) — FR-313 判別/FR-316 分割スコアリングの評価軸:
  - `EvidenceBackend`(Protocol): `score(metrics: RefinementMetrics) -> EvidenceResult(backend, value, logz_err=None)`
  - `BICBackend`(name="bic", 既定)/ `AICBackend`。`rank(hypotheses, backend, *, temperature=1.0, close_threshold=10.0) -> tuple[RankedHypothesis, ...]`
  - `RankedHypothesis(hypothesis, evidence, probability, close_competitor)`。**`nested` backend は未実装(M5)** — FR-313 は bic までで確定
- **search**(`search/tree.py`, M1) — FR-313 の 2 仮説(単相/二相)生成・比較に再利用:
  - `HypothesisTreeSearch(backend, *, evidence=None, config=SearchConfig(), ledger=None, snapshots=None)`。`ledger/snapshots` 注入可
  - `.search(two_theta, intensity, candidates, *, weights=None) -> SearchResult`
  - `SearchResult(ranked, hypotheses, good_cluster_ids, alternatives, unmatched, final_reports, ledger, snapshots, warnings=())` + `.to_summary() -> dict`
  - `UnmatchedPeakReport(unmatched_observed, extra_calculated, unknown_phase_flag)`
- **sequential**(M2, `sequential/*.py`) — operando は SequentialEngine を軸に組む:
  - `SequentialEngine(backend, *, candidates=(), evidence=None, config=SequentialConfig(), ledger=None, snapshots=None)`
    `.run(series: FrameSeries, initial_phases) -> SequentialResult(trajectory, hypotheses, search_results, first_frame_report, ledger, snapshots, warnings)`
  - `FrameSeries(two_theta, intensities(2D), axis_values=(), axis_kind="index", channels: tuple[ExternalChannel,...]=())` + `.n_frames`(= `intensities.shape[0]`)
  - `SequentialConfig(orchestration="independent"|"native", inherit="phases"|"lattice_only", seq_max_cycles=10, first_frame_staged=True, changepoint=ChangepointConfig(), lifecycle=LifecycleConfig(), search=SearchConfig())`
    — `orchestration="native"`(GSAS-II ネイティブ sequential, FR-302)は**未実装 NotImplementedError**
  - **changepoint**(`sequential/changepoint.py`, FR-303): `detect_changepoint(rwp_history, lattice_history, new_unmatched, *, config=ChangepointConfig(window=5, z_threshold=5.0, min_new_peaks=1)) -> ChangepointSignal(frame_index, triggered, z_rwp, z_lattice, new_unmatched, reasons)`
    — **`min_new_peaks=1` は Issue #3 の較正対象**。FR-316 実装時に IC 分割へ再設計
  - **thermal**(`sequential/thermal.py`, FR-322/323): `fit_thermal_baseline(temperatures, values, *, degree=1, parameter="") -> ThermalBaseline(parameter, coefficients, residuals, outlier_frames)`;
    `estimate_transition(temperatures, fractions, *, phase_ref) -> TransitionEstimate(phase_ref, onset, midpoint, sigma, direction) | None`
    — **`estimate_transition` の onset(10% 交差)は Issue #4 の意味論バグ対象**(disappearing で onset>midpoint)
  - **trajectory**(`sequential/trajectory.py`, FR-306): `Trajectory(records: tuple[FrameRecord,...], lifecycles)` + `.to_csv(path)`;
    `FrameRecord(frame_index, axis_value, temperature, phases, rwp, chi2, changepoint, changepoint_reasons, refine_failed)`
- **selection**(M2, `selection/*.py`, FR-402/403): `FinalSelectionEngine(*, mode="agent"|"human", ledger=None, queue=None)` の `.decide/.accept/.revert/.set_mode`;
  `detect_escalations(result, *, staged_escalated=False, high_r_threshold=30.0) -> tuple[EscalationReason,...]`
  — **FR-403 のエスカレーション条件に「吸収補正の経験推定モード発動」が既に規定**。M3 の FR-317 経験推定はここに配線する
- **store**(`store/{ledger,snapshot,persistent,serialization}.py`):
  - インメモリ: `Ledger()`(`.append(kind, payload)` / `.verify()`、削除 API なし)/ `SnapshotStore(ledger=None)`(`.save/.load/.revert`)
  - 永続化(M2): `PersistentLedger(path)` / `PersistentSnapshotStore(path, ledger=...)`(JSONL 追記・再オープンで verify 再検証)
  - `phase_to_dict` / `phase_from_dict`(serialization.py。**M3 で CellConfig/echem/multistart を足すなら往復対称にシリアライズ拡張が要る**)
- **model**(`model/*.py`) — **spec §4 との差分が M3 の主要作業。次節の表を必読**
- **公開 API**(`src/tsumugin/__init__.py::__all__`, 現在 **52 件・アルファベット昇順**): `test_m1/m2_symbols_in_dunder_all_and_sorted` が昇順を固定。M3 追加シンボルもここへ

**参照元(実 API 確認元)**: `src/tsumugin/model/{project,phase,hypothesis,channel}.py`, `backends/base.py`,
`refinement/{staged,guardrails}.py`, `evidence/{base,ic,ranking}.py`, `search/tree.py`,
`sequential/{engine,changepoint,thermal,trajectory,series}.py`, `selection/{engine,review_queue}.py`,
`store/{ledger,snapshot,persistent,serialization}.py`, `__init__.py`

### ⚠️ spec §4 データモデルと現行実装の差分(M3 で埋める必要のある要素)
仕様 §4 のエンティティ定義に対し現行 dataclass は縮約版。**operando(FR-311/317)とマルチスタート(FR-232)に必須の未実装要素**:

| 仕様 §4 の要素 | 現行実装 | M3 で必要な FR | 対応方針(推奨) |
|---|---|---|---|
| `ExternalChannel.kind = echem(V,I,Q,x)` | `channel.py`:`ChannelKind=Literal["temperature","time","pressure","custom"]` で **echem を明示除外**(L21 コメント「echem は M3 スコープ外のため含めない」) | FR-311 電気化学同期 | `ChannelKind` に `"echem"` を追加。**ただし sync_map は `Mapping[int,float]` 単値** — echem は V/I/Q/x の 4 量。**量ごとに別 `ExternalChannel`(`label` で識別)を推奨** or 構造化値へ拡張。**非破壊で** |
| `Dataset.external_channels: [ExternalChannel]` | `project.py`:`Dataset(id, kind, frames=(), sequence_axis="none")` に **未定義**(現状チャネルは `FrameSeries.channels` 側に載る) | FR-311/321 | Dataset へ `external_channels: tuple[ExternalChannel,...]=()` を末尾・既定付き非破壊追加 |
| `Dataset.cell_config_ref: CellConfig \| null` | **未定義** | FR-317 吸収補正 | Dataset へ optional フィールド追加(下の CellConfig 新設が前提) |
| `CellConfig{geometry, layers[{role,material,thickness_mm,density}], beam{energy/wavelength,size}}` | **完全に未定義** | FR-317 | `model/cell_config.py` に frozen dataclass 群を新設(§4 の構造どおり)。§15-2 確定「層状=透過法のみ / v1 実効 μt 1 パラメータ + restraint」 |
| `RefinementMetrics.multistart{n, n_basins}` / `peak_match_score` / `unmatched_peaks` | `hypothesis.py`:`RefinementMetrics(rwp,gof,chi2,n_obs,n_params,evidence={})` のみ | FR-232 basin 報告 | `RefinementMetrics` へ multistart 情報を非破壊追加 or 別 dataclass(`MultiStartReport`)を Hypothesis に付与 |
| `sequence_axis="potential"/"capacity"` | `project.py` の `Dataset.sequence_axis` に**既に定義済**(potential/capacity 含む) | FR-311/314 電位・容量軸 | 追加不要(器は在る)。echem 値の同期のみ実装 |
| `PhaseInstance.microstructure/texture/coordinates` | 未定義(lattice/scale/wt_frac/occupancies/lifecycle のみ) | (精密化深化は主に M4/M5) | M3 では**吸収補正 μt を除き必須でない**。FR-317 の実効 μt は phase 属性でなくモデル/ヒストグラム属性として持つのが自然 |
| `Hypothesis.frame_range` / `PhaseInstance.lifecycle` | **実装済**(M2 で追加) | FR-316 区間仮説 | 再利用可。分割仮説は frame_range で表現できる |

## 関連実装

### M3 が土台にする M0/M1/M2 資産(再利用ポイント)
- **マルチスタート(FR-230)の 1 本 = `StagedRefinementEngine.run`** — 初期 phases を系統摂動して N 本回し、
  `RefinementReport.metrics`/`final_phases` を basin クラスタリングに集約(`refinement/staged.py`)
- **摂動対象パラメータ命名** — `backends/base.py::param_name(i,key)` / `parse_param` で相×パラメータを正準化(FR-231 の格子/scale/occupancy 摂動、FR-317 の μt free_param 追加)
- **判別 2 仮説の生成・比較(FR-313)** — `search/tree.py::HypothesisTreeSearch`(単相 vs 二相を候補集合として与え evidence 比較)。`ledger/snapshots` 注入で共有監査
- **区間分割の複合指標素材(FR-316)** — `sequential/changepoint.py::detect_changepoint`(オンライン検出)を**オフライン最適分割(PELT/binseg + BIC)へ一般化**。Issue #3 の較正もここで
- **温度軸転移(FR-323)→ FR-316 一般化** — `sequential/thermal.py::estimate_transition`(現状 onset/midpoint。Issue #4 を直しつつ FR-316 分割へ接続)
- **operando 逐次オーケストレーション** — `sequential/engine.py::SequentialEngine.run`(warm start + changepoint + 局所探索の枠をそのまま electrochemical 軸へ)
- **最終裁定 + エスカレーション(FR-313 競合/FR-317 経験推定)** — `selection/engine.py::FinalSelectionEngine` / `detect_escalations`(FR-403 に「経験推定モード発動」条件が既存)
- **結合出力 CSV(FR-314)** — `sequential/trajectory.py::Trajectory.to_csv` の列拡張(電位 V / 容量 Q / 組成 x / 転移点)
- **追記専用 store + 永続化** — `store/{ledger,snapshot,persistent}.py`(basin 昇格・判別・吸収補正も**削除/上書き API を作らず**追記 + revert)
- **GSAS-II 実バックエンド** — `backends/gsasii.py::GSASIIBackend`(FR-317 の透過吸収補正・μt 精密化は最終的に GSAS-II 側パラメータへ配線)

**参照元**: `src/tsumugin/{refinement/staged,backends/base,search/tree,sequential/{engine,changepoint,thermal,trajectory},selection/engine,store/persistent,backends/gsasii}.py`

### 参考パターン(M3 でも踏襲)
- **失敗は例外でなく chi2=inf の結果に変換**しガードレール/降格で処理(マルチスタートの発散本もこれで吸収)
- **降格のみ・候補除外しない**(Dara 教訓)。FR-232 の複数 basin は**除外せず別仮説へ昇格**(多峰性を隠さない)
- **全操作を理由付きで ledger 記録**(basin 昇格・判別採否・吸収補正モード・警告)
- **エスカレーションは処理をブロックしない**(FR-403: 暫定裁定 + 要確認フラグ)
- **決定論的順序**(ledger kind 順・canonical JSON ソート・ID 連番)で NFR-102。**マルチスタートは start ごと決定論シード + basin 安定ソート**が要
- **非有限を漏らさない**(`_finite_or_none` パターン、Issue #5 で共有化)

### 共通モジュール・ユーティリティ
- `backends/base.py::param_name` / `parse_param` — 相⇔パラメータ名の正準変換
- `store/ledger.py::_canonical_json` / `_compute_hash` — 決定論的ハッシュチェーン(永続化再利用)
- `refinement/guardrails.py::GuardConfig` / `check_guards` — 発散系の検知
- `sequential/changepoint.py::_robust_z`(中央値/MAD 修正 z, `_MODIFIED_Z_CONST=0.6745`)/ `thermal.py::_outlier_frames` — FR-316 分割でも同系統統計を使う
- **`_finite_or_none`(Issue #5 の統合対象)** — 現在 **3 系統に散在**: `search/tree.py`(L181 定義, webui/app.py が L27 で**私的横断 import**)/ `store/serialization.py`(L21 ローカル定義)/ `sequential/trajectory.py`(`_num_cell` が同思想)。
  **統合先はレイヤ最下層**(`store/` は最下層のため上位 `search/tree.py` を import 不可 = 逆依存)→ **`tsumugin/_json.py` 等ルート直下の基底モジュール**を新設し全層が下向き import する形が安全

### 依存関係・インポートパス
- 公開 import 例: `from tsumugin import SequentialEngine, FrameSeries, ExternalChannel, FinalSelectionEngine, StagedRefinementEngine, HypothesisTreeSearch, BICBackend, PersistentLedger`
- GSAS-II: `from GSASII import GSASIIscriptable`。ソース `C:\Users\tomoo\G2` + venv `gsas2-source.pth` + バイナリ `~/.GSASII/GSASII-bin/win_64_p3.12_n2.2`
- 依存導入は `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるので禁止**)。M3 で `xraylib` を足すなら **新規 optional extra**(例 `--extra operando`)にし未導入時は経験推定モードへ縮退

## 技術的制約

### パフォーマンス制約
- **NFR-103(努力目標)**: シーケンシャル非探索区間 ≤ 10 秒/フレーム。FR-234 のマルチスタート(N=8–16 本)は
  **判別/最終精密化に限定適用**(FR-233)しコスト集中。粗→細の 2 段(FR-316)で分割探索の計算量を抑える
- FR-234: Worker プール並列化。ただし**決定論(NFR-102)を壊さない**設計(順序安定化・start 別シード)が前提

### セキュリティ制約(= 非破壊性制約 P2 / NFR-101 / NFR-105)
- **破壊的操作(生データ削除・上書き・履歴改変)の API を実装しない**。永続化層でも Ledger/SnapshotStore に削除・上書き禁止
- **basin 昇格・判別採否・吸収補正モード切替・人間差し戻し**もすべて**追記 ledger 記録 + revert 可能**に保つ
- Review Queue Web UI に認証なし。既定 `127.0.0.1` バインド維持(`0.0.0.0` は解析データ全量の無認証公開)

### 互換性制約
- Python >= 3.12 固定。GSAS-II バージョン固定 + contract test(NFR-106)
- **公開 API の非破壊維持(REQ-404)**: `__all__` の既存 52 シンボルを壊さない。新規は末尾追加 + 昇順維持
- 新フィールドは**末尾・既定値付き**で frozen dataclass へ非破壊追加(M2 の `lifecycle`/`frame_range` 追加に倣う)

### データ制約
- chi2/rwp のセマンティクスはバックエンド間で統一(BIC/evidence 比較の一貫性)。精密化失敗は chi2=inf の結果に変換
- **echem 同期**: `sequence_axis="potential"/"capacity"` + `ExternalChannel(kind="echem")`。**sync_map 単値制約**により V/I/Q/x は
  量ごと別チャネル or 構造化が必要(§4 差分表)
- **吸収補正 μt**: 透過法のみ(§15-2)。CellConfig 由来値は restraint、実効 μt は精密化変数(v1 は 1 パラメータ)
- FR-314 結合出力・FR-324/325 の外部委譲出口は **parquet/CSV**

**参照元**: `CLAUDE.md`(実装上の不変条件), `docs/tsumugin_spec_v0.3.md`§3, §6, §7, §11, §14, §15

## 注意事項

### 開発時の注意点(M3 固有)
- **spec §4 差分を先に埋める**(上表): `CellConfig` 新設 / `ExternalChannel` に echem / `Dataset.external_channels`・`cell_config_ref` /
  `RefinementMetrics.multistart`。いずれも**非破壊追加**(末尾・既定付き)。シリアライズ(`phase_to_dict` 系)の往復対称も同時に拡張
- **FR-313 の `nested` 裁定は M5**。M3 は `bic` 一次判定 + マルチスタート(FR-233)までで確定させ、僅差競合は
  `FinalSelectionEngine`/`detect_escalations`(close_competitor)経由で**エスカレーション扱い**にする(M5 で nested 裁定に置換)
- **FR-316 は既存 changepoint の一般化**: オンライン `detect_changepoint` を**オフライン最適分割(PELT/binseg + BIC ペナルティ)**へ拡張。
  §15-1 確定「k を逐次追加し evidence 改善が閾値未満で打ち切り。ペナルティ較正値はベンチ §12-2 で確定」。**Issue #3(min_new_peaks 較正)を同時解消**
- **FR-317 経験推定モードは FR-403 エスカレーションに配線**(既に条件として規定済)。CellConfig 未提供時は警告 + 逆算 μt 提示
- **マルチスタート決定論(NFR-102)**: FR-234 の並列でも**start インデックス由来の決定論シード**とし、basin クラスタは**安定ソート**。
  ラテン超方格(FR-231 占有率摂動)も種固定でビット同一に
- **xraylib は optional**: 未導入環境では FR-317 を経験推定モードへ縮退させ、テストは gsas 同様マーカーで skip 可能に
- **`.mpr` パーサは重依存**: FR-311 は **CSV 汎用を第一級**にし `.mpr`/HZ は optional/後回しで良い(要件で切り分け)

### Issue 解消の実装ポイント(#3 / #4 / #5)
- **#3 changepoint 感度較正**(`sequential/changepoint.py`): `min_new_peaks=1` は単純カウントで実 GSAS-II ノイズ下で毎フレーム発火し
  探索連発の懸念。**発火頻度を実測較正 + 強度閾値 + 持続条件(連続 N フレーム)**を導入。FR-316 実装と併せて再設計するのが自然
- **#4 thermal onset 意味論**(`sequential/thermal.py` L204-206 / `tests/test_thermal.py`): `estimate_transition` は最初の交差を返すため
  減少シグモイド(disappearing)では 10% 交差(onset)が 50%(midpoint)より高温側になり `onset > midpoint`。
  **対応案: disappearing では 90% 交差を onset とする(遷移開始側に統一)or `onset` を `crossing_10pct` 等の中立名へ**。
  **disappearing の onset を検証するテストを追加**(現状未検証)
- **#5 finite_or_none 共有化**(`webui/app.py` L27 の私的横断 import ほか): `search/tree.py::_finite_or_none` を配信層が跨いで import。
  `store/serialization.py`・`sequential/trajectory.py` にも同思想の別実装。**挙動不変で単一情報源へ統合**。
  ただし**レイヤ逆依存に注意**(store は最下層)→ **ルート直下 `tsumugin/_json.py` 等の基底モジュール**へ置き全層が下向き import

### デプロイ・運用時の注意点
- GSAS-II 起動時の `~/.GSASII/config.ini` 読込警告(cp932)は無害(upstream 表示バグ)
- M3 で新規公開 API・依存(xraylib/echem パーサ)を足したら `docs/dev/context.md`(Tech Stack / 公開 API / スコープ)と `README.md` を更新

### セキュリティ/非破壊上の注意点
- 新規の basin 昇格・判別・吸収補正・裁定・モード切替でも**削除/上書き API を作らない**(P2 の構造的保証)。全て追記 + revert
- 吸収補正の経験推定モード発動・僅差判別は**理由付きで ledger 記録 + Review Queue 通知**(FR-403/FR-424)

### パフォーマンス上の注意点
- マルチスタート(FR-233 既定 = accepted 最終精密化 + FR-313 判別時のみ)で N 本コストを局所化
- FR-316 は粗い格子スキャン → 境界近傍細密化の 2 段で計算量を抑える(§7 FR-316)
- 吸収補正 μt と相分率・変位パラメータの**強い相関**(§14 リスク)→ 透過法限定 + CellConfig 由来 restraint + **相関行列の自動警告**

## Git情報

### 現在のブランチ
`milestone/m3-operando`(clean。`main` = M2 マージ済み `9475229` から分岐)

### 最近のコミット(抜粋)
```
9475229 Merge pull request #2 from tomooki/milestone/m2-sequential
ef300f1 fix: PR #2 レビュー指摘対応 (シリアライズ往復非対称の解消ほか)
c60453d M2 TASK-0022: 公開 API 統合 + E2E + ドキュメント (TDD, 19ケース green)
...(M2 TASK-0011〜0022 / M1 / M0)
```

### 開発状況
M0 + M1 + M2 完了・main にマージ済み。**430 passed / 3 skipped**(タスク提示)、GSAS-II 導入済み。
M3 ブランチを切った直後で、これから kairo-requirements → kairo-design → kairo-tasks → kairo-implement を回す。
未解決 Issue #3/#4/#5(いずれも PR #1/#2 レビューの LOW 指摘)を M3 スコープで併せて解消する。

## 収集したファイル一覧

### プロジェクト基本情報
- `CLAUDE.md`
- `README.md`
- `docs/dev/context.md`
- `pyproject.toml`
- (`AGENTS.md`, `docs/rule/`, `docs/rule/kairo/` は不在 — 規約は CLAUDE.md に集約)

### 仕様書(正)
- `docs/tsumugin_spec_v0.3.md`(FR/NFR の正。M3 = §6 FR-230, §7 FR-310/316/317, §4 データモデル, §13 M3 行, §14 リスク, §15 課題確定)

### 参考(M1/M2 の同種成果物)
- `docs/spec/m1-hypothesis-search/{note,requirements,user-stories,acceptance-criteria,prep,interview-record}.md`
- `docs/spec/m2-sequential/{note,requirements,user-stories,acceptance-criteria,prep,interview-record}.md`

### 未解決 Issue(M3 で解消)
- GitHub Issue #3(changepoint `min_new_peaks` 感度較正)/ #4(thermal `estimate_transition` onset 意味論)/ #5(`_finite_or_none` 共有化)

### 関連実装(M3 の土台となる M0/M1/M2 資産・実 API 確認済み)
- `src/tsumugin/__init__.py`(公開 API `__all__` 52 件)
- `src/tsumugin/model/{project,phase,hypothesis,channel}.py`(**§4 差分の埋め対象**)
- `src/tsumugin/backends/{base,simulated,gsasii}.py`
- `src/tsumugin/refinement/{staged,guardrails}.py`(マルチスタートの実行単位)
- `src/tsumugin/evidence/{base,ic,ranking}.py`(FR-313/316 スコアリング)
- `src/tsumugin/search/tree.py`(FR-313 の 2 仮説比較)
- `src/tsumugin/sequential/{engine,changepoint,thermal,trajectory,series,lifecycle}.py`(operando/FR-316 の基盤・Issue #3/#4 対象)
- `src/tsumugin/selection/{engine,review_queue}.py`(FR-313 競合/FR-317 経験推定のエスカレーション)
- `src/tsumugin/store/{ledger,snapshot,persistent,serialization}.py`(追記専用・Issue #5 対象)
- `src/tsumugin/webui/app.py`(Issue #5 の私的横断 import 箇所)

---

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
設計文書(`docs/design/m3-operando/*`)・M3 要件定義(`docs/spec/m3-operando/requirements.md` 等)は本ノートの後工程で生成されます。
