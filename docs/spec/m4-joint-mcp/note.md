# m4-joint-mcp 開発コンテキストノート

## 作成日時
2026-07-04

## プロジェクト概要

### プロジェクト名
Tsumugin — 多仮説・全自動 Rietveld 解析プラットフォーム

### プロジェクトの目的
粉末回折(X線・中性子)の相同定・多相 Rietveld 精密化・時系列(operando / in situ 高温)解析を、
**AI エージェントと人間の介入点を明示的に設計した上で**全自動化する。Dara の中核思想
(多仮説主義 / 精密化の前倒し / null hypothesis testing / 解釈可能性)を継承し、精密解析・
operando・高温・joint・MEM へ拡張する。バックエンドは GSAS-II (`GSASIIscriptable`、導入済み)。

**本ノートの対象マイルストーン = M4**(仕様 §13 の行:
「中性子・joint精密化 **FR-240系** + ChemPlausibility IF **FR-412** + MCP Server **FR-513**」):
> (1) 中性子 CW/TOF マルチヒストグラム取り込み **FR-241**/ (2) joint 精密化(構造共有・ヒスト独立)**FR-242**/
> (3) ヒストグラム重み **FR-243** / (4) X線/中性子コントラスト占有率解放推奨 **FR-244** /
> (5) 探索はプライマリ・検証を joint **FR-245** / (6) ChemPlausibility プラグイン境界 **FR-412** /
> (7) MCP Server 8 ツール **FR-513**。

**スコープ外(M5 以降)**: nested sampling 裁定(FR-122)・MEM 本体(Dysnomia, FR-600系)・OED 提案本体
(FR-430系)・較正済み確率(reliability diagram / ECE)。
- **FR-513 の `run_mem` ツールは MCP 境界のみ M4 スコープ**。MEM バックエンド(FR-601〜606)は M5。
  M4 では `run_mem` を**薄い委譲/スタブ境界**(未実装バックエンドへは `NotImplementedError` 相当の明示エラー or
  プレースホルダ応答)に留める。この境界を要件で明記する。
- **FR-244 のコントラスト判定は「推奨のみ」**。実際の中性子散乱長テーブル(元素 → b)を同梱するかは
  最小同梱で足り、**判定ロジック(X線 f と中性子 b の差が閾値以上のサイトを検出)**が主。占有率解放の
  自動適用はせず、戦略への追加提案(降格でなく昇格側の提案)に留める。
- **FR-412 ChemPlausibility は Protocol 境界 + v1 最小ルールモジュールのみ**。reaction network / 熱力学 /
  合成可能性 / LLM 判断の外部モジュールは本 IF に準拠して**将来接続する想定**(M4 では接続点のみ)。

**参照元**: `README.md`, `CLAUDE.md`, `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`(仕様の正)、
直前 MS 成果物 `docs/spec/m3-operando/*`

## 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12(uv 管理, src layout + hatchling ビルド)
- **数値**: numpy >= 1.26(コア)。GSAS-II は optional extra `gsas`(scipy / pycifrw / requests、導入済み)
- **ランタイム**: CPython 3.12。Rietveld バックエンド = GSAS-II 2.0(`from GSASII import GSASIIscriptable`)。
  **joint 精密化(FR-242)は GSAS-II ネイティブのマルチヒストグラム機能を利用**(構造共有・ヒスト独立 scale/背景/プロファイル)
- **Web UI(M1 導入済)**: FastAPI + uvicorn(optional extra `web`、read-only)。M2 で Review Queue 最小版を追加済
- **永続化(M2 導入済)**: JSONL 追記(`PersistentLedger` / `PersistentSnapshotStore`)。追記専用 + ハッシュチェーン + 非破壊 revert

### M4 新規で検討が要る外部依存(未導入)
- **MCP Server(FR-513)**: 公式 Python SDK は PyPI パッケージ `mcp`(`from mcp.server import Server` 等)。
  **GSAS-II / xraylib と同じ optional extra 方式**で足すのが安全:
  `[project.optional-dependencies] mcp = ["mcp>=1.0"]` を追加し、`uv sync --extra mcp` で導入。
  **未導入環境では MCP サーバ起動 API のみ `ImportError` フレンドリなガード**(`MCPUnavailableError` 相当)で縮退し、
  コア解析ロジック(ツールが委譲する `submit_analysis` 等の実処理)は **SDK 非依存のプレーン関数**として実装しテスト可能にする。
  → MCP 層は「SDK 依存の薄いアダプタ」+「SDK 非依存のツール実処理関数」の 2 層に分離する(テスト容易性・NFR-102)。
- **中性子散乱長(FR-241/244)**: 元素 → 中性子コヒーレント散乱長 b(fm)の小テーブル。
  **軽量な静的テーブルを同梱**(xraylib 相当の重依存は不要 — b は元素/同位体で概ね定数)。
  X線散乱因子 f はプライマリヒストグラムの Z 近似で足り、**コントラスト = |f_norm − b_norm| が閾値超のサイトを検出**するに留める。
- **instprm 管理(FR-241)**: TOF マルチバンクは**バンクごとの instprm 参照 + DIFC 系パラメータ**を管理する。
  既存 `HistogramRef(probe, data_ref, instprm_ref, bank_id)`(project.py, M1 で器は導入済)を活用し、
  **バンク別 DIFC/DIFA/ZERO を保持する `TofBankParams` 相当の値オブジェクトを新設**する(非破壊追加)。

### アーキテクチャパターン
- **スタイル**: レイヤ分離(Interfaces / Agent / Orchestrator / Workers / Data、仕様 §3)。境界はすべて
  `typing.Protocol` で抽象化しバックエンド交換可能(P7)
- **設計パターン**: frozen dataclass の不変値オブジェクト + `with_updates()` / `dataclasses.replace()` による非破壊更新。
  全状態遷移は追記専用 Ledger(ハッシュチェーン)+ SnapshotStore(revert 可能)に記録(P2 / NFR-101 / NFR-105)
- **ディレクトリ構造(M3 まで実装済み・M4 が土台にする範囲)**:
  ```
  src/tsumugin/
  ├── model/       # project.py(Project/Dataset/Frame/HistogramRef/Probe), phase.py, hypothesis.py(RefinementMetrics),
  │                #   channel.py(ExternalChannel), cell.py(CellConfig/MuCalculator) ← M3 で追加
  ├── backends/    # base.py(RefinementBackend Protocol/RefinementModel/RefinementResult/param_name/parse_param)
  │                #   + simulated.py + gsasii.py ← joint 精密化(FR-242)の拡張対象
  ├── refinement/  # staged.py(StagedRefinementEngine) + guardrails.py
  ├── evidence/    # base.py + ic.py(BICBackend/AICBackend) + ranking.py(rank)
  ├── multistart/  # M3(FR-230)。joint 検証精密化のマルチスタートに再利用可
  ├── operando/    # M3(FR-311/313/316/317)
  ├── absorption/  # M3(FR-317 透過吸収)。中性子吸収は同一 IF で切替(FR-317 末項)
  ├── store/       # ledger.py + snapshot.py + persistent.py + serialization.py
  ├── search/      # tree.py(HypothesisTreeSearch) — M1。FR-245 プライマリ探索に再利用
  ├── export/      # gpx.py(export_gpx) — M1。MCP export_gpx が委譲
  ├── webui/       # app.py(read-only FastAPI + Review Queue) — M1/M2
  ├── sequential/  # engine/changepoint/lifecycle/thermal/trajectory/series — M2/M3。MCP get_trajectory が委譲
  ├── selection/   # engine(FinalSelectionEngine.accept/revert/decide/set_mode) — M2。MCP accept/revert が委譲
  └── pipeline.py  # analyze_single_pattern — M0。MCP submit_analysis が委譲
  tests/           # 実装ファイルと 1:1、GSAS-II 依存は @pytest.mark.gsas
  docs/spec/       # kairo 要件・設計・タスク(本ノートを含む)
  ```
  **M4 が新設する見込みの層**:
  - `joint/`(マルチヒストグラム joint 精密化オーケストレーション / `JointRefinementModel` / ヒスト重み / コントラスト判定)
  - `chem/`(`ChemPlausibility` Protocol / `PlausibilityResult` / `SynthesisContext` / 最小ルールモジュール / 重み付き幾何平均合成)
  - `mcp/`(MCP Server アダプタ + SDK 非依存ツール実処理関数群 + `run_mem` 委譲境界)
  - `model/` 拡張(`TofBankParams` 系 / `PhaseRef`(FR-412 引数))

**参照元**: `CLAUDE.md`, `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`§6(FR-240)/§8(FR-412)/§10(FR-513)

## 開発ルール

### プロジェクト固有のルール(必須・違反禁止)
- **TDD 厳守**: Red(失敗テスト)→ Green(最小実装)→ Refactor。テストなしの実装コミット禁止
- **タスク毎コミット**: タスク 1 件完了(テスト green)ごとに 1 コミット。**git commit はユーザー判断(本セッションでは commit 禁止)**
- **ブランチ運用**: マイルストーン毎にブランチ。M4 は `milestone/m4-joint-mcp`。完了時に PR → `/code-review`
  (HIGH 以上に限らず MEDIUM/LOW も修正、新規指摘が出なくなるまでループ)→ マージはユーザー判断
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
- **依存導入**: `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるため禁止**)。Web は `--extra web`、
  MCP は M4 で `--extra mcp` を新設(未導入環境では MCP 起動 API を skip / friendly error に縮退)
- **現状ベースライン(M3 完了時点・タスク提示)**: **全 green**(GSAS-II 導入済み。未導入環境用 gsas マーカー分は自動 skip)
- **マーカー**: `gsas`(GSAS-II 導入環境でのみ実行)。M4 で `mcp` SDK 依存テストが入るなら**同種の optional マーカー**(例 `@pytest.mark.mcp`)を検討。
  ただし**ツール実処理関数は SDK 非依存**にして通常テストで網羅する

**参照元**: `CLAUDE.md`, `docs/dev/context.md`, `pyproject.toml`

## 既存の要件定義

### 要件定義書
M4 専用の要件定義書(`docs/spec/m4-joint-mcp/requirements.md` 等)は本ノートの後工程 kairo-requirements で作成する。
正の要件は `docs/tsumugin_spec_v0.3.md` の FR/NFR 番号。M4 スコープに対応する主要 FR を以下に抜粋する。

**参照元**: `docs/tsumugin_spec_v0.3.md`§6(FR-240), §8(FR-412), §10(FR-513), §4(データモデル), §13(M4 行), §11(NFR)

### 主要な機能要件(M4 スコープ、仕様 FR 番号)
- **FR-240 中性子・マルチヒストグラム対応**(§6, v0.2 新設)
  - FR-241: 中性子 CW / TOF(マルチバンク)ヒストグラムの取り込み。TOF はバンクごとの instprm・DIFC 系パラメータ管理
  - FR-242: **joint 精密化** — 同一構造モデルに X線+中性子/複数バンク/複数温度点を同時フィット。
    ヒストごとの scale/背景/プロファイルは独立、構造パラメータは共有(**GSAS-II ネイティブ機能を利用**)
  - FR-243: ヒストごとの重み(統計・信頼度)設定可。既定は統計重み
  - FR-244: X線/中性子コントラストを利用した占有率解放の**推奨判定** — 散乱コントラストが十分なサイトを自動検出し、
    joint データがある場合のみ当該占有率の解放を戦略に追加
  - FR-245: 木探索(FR-110)は**プライマリヒストグラムで実行**し、**生存仮説の検証精密化を joint で行う**(探索コスト抑制)
- **FR-412 ChemPlausibility インターフェース**(§8, v0.2 改定)
  - Protocol 境界: `score(phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult`。
    `PlausibilityResult = {score: float[0,1], rationale: str, source: str}`
  - `SynthesisContext`: 元素系 / 前駆体 / 雰囲気 / 温度履歴 / 電気化学窓
  - v1 同梱は最小ルールモジュールのみ(例: 大気下での単体アルカリ金属の降格)
  - 複数モジュールのスコア合成規則 = **重み付き幾何平均(既定)**
  - **スコアは降格のみに使い候補除外は行わない**(Dara 教訓・最重要不変条件)
- **FR-513 MCP Server**(§10)
  - ツール: `submit_analysis`, `list_hypotheses`, `compare_hypotheses`, `accept_hypothesis`, `revert`,
    `get_trajectory`, `export_gpx`, `run_mem`
  - `final_selection_mode`(agent/human, FR-402)は MCP 経由でも同一適用
  - **非破壊性 P2**: revert は追記型スナップショット revert であり破壊的削除ではない。破壊的操作は MCP ツールにも存在しない
  - `run_mem` は MEM(FR-600系)であり **M5 スコープ**。M4 は薄い委譲/スタブ境界に留める

### 主要な非機能要件
- **NFR-101 / P2**: 破壊的操作の API 非実装。joint 精密化・コントラスト提案・ChemPlausibility 降格・MCP 経由操作も**全て追記 + revert**
- **NFR-102**: 再現性 — **乱数種固定でビット同一**。joint のヒスト順序・コントラスト判定・スコア合成も決定論的順序で
- **NFR-105**: ledger 追記専用 + ハッシュチェーン(`verify()` 常時 True)。MCP 経由の全操作も ledger 記録
- **NFR-107**: σの由来(共分散 / 逐次相関 / マルチスタート分散)をレポートに明示。joint はヒスト重みの由来も明示

## 既存の設計文書

### アーキテクチャ設計
`docs/design/m4-joint-mcp/` は kairo-design で生成予定。M4 は M0〜M3 の抽象境界
(`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore` / `HypothesisTreeSearch` /
`SequentialEngine` / `FinalSelectionEngine` / `analyze_single_pattern` / `export_gpx`)を
共有インターフェースとして再利用し、その上に **joint 精密化層・ChemPlausibility 層・MCP Server 層**を新設する。

### データフロー(M4 が新設する層のイメージ)
```
Project(datasets=[Dataset(frames=[Frame(histograms=[HistogramRef(probe="xray"/"neutron_cw"/"neutron_tof",
        instprm_ref=..., bank_id=...)])])])
  └─> 木探索(FR-245: HypothesisTreeSearch をプライマリヒストグラムで実行 → 生存仮説)
  └─> joint 検証精密化(FR-242: JointRefinementModel = 構造共有 + ヒスト独立 scale/bg/profile
        → GSASIIBackend のマルチヒストグラム経路 / SimulatedBackend の加算 χ² 経路)
        └─> ヒスト重み(FR-243: 既定 統計重み。経験重みはオプション)
        └─> コントラスト占有率解放推奨(FR-244: |f_norm − b_norm| > 閾値のサイト検出 → 戦略へ追加提案)
  └─> ChemPlausibility(FR-412: score(PhaseRef, SynthesisContext) → PlausibilityResult
        複数モジュール合成 = 重み付き幾何平均。降格のみ・除外しない → rank の順位を軽く下げる)
  └─> 最終選択(FinalSelectionEngine, M2)+ エスカレーション

MCP Server(FR-513, mcp/ 層):
  submit_analysis ─委譲→ pipeline.analyze_single_pattern / joint オーケストレーション
  list_hypotheses / compare_hypotheses ─委譲→ SearchResult / rank
  accept_hypothesis / revert ─委譲→ FinalSelectionEngine.accept / .revert (追記型・P2)
  get_trajectory ─委譲→ Trajectory.to_csv / dict
  export_gpx ─委譲→ export.gpx.export_gpx
  run_mem ─委譲→ MEMBackend(M5 未実装)→ NotImplemented 相当の明示エラー(M4 は境界のみ)
```

### 型/インターフェース定義(**実 API 署名を検証済み** — 2026-07-04 時点のソース)

M4 が依存・拡張する M0〜M3 の実インターフェース(すべて frozen dataclass / Protocol):

- **model/project.py** — マルチヒストグラムの器は**既に導入済み**(M4 は中身を使う):
  - `Probe = Literal["xray", "neutron_cw", "neutron_tof"]`(**中性子 3 種は定義済**)
  - `HistogramRef(probe, data_ref, instprm_ref=None, bank_id=None)`(**instprm/bank の器あり**。FR-241 は DIFC 系を足す)
  - `Frame(id, index, histograms: tuple[HistogramRef,...]=(), axis_value=None)`(**複数ヒストの器あり**)
  - `Dataset(id, kind, frames=(), sequence_axis="none")` / `Project(id, datasets=(), final_selection_mode="agent")`
- **backends/base.py** — joint 精密化(FR-242)の拡張点:
  - `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)` は**単一ヒスト前提**。
    M4 は **joint 用のマルチヒスト入力(`JointRefinementModel` 相当: ヒストごとの (two_theta, intensity, weights) 群 +
    ヒスト独立 free_params + 共有構造 free_params)**を新設。`RefinementResult.globals`/`warnings` は M3 で導入済(再利用)
  - `param_name(i,key)` / `parse_param` は `"global.{key}"` を既にサポート(コントラスト由来の占有率解放命名に活用)
- **evidence/{ic,ranking}.py** — joint 後の仮説比較・ChemPlausibility 降格の適用点:
  - `BICBackend`(既定)/ `rank(hypotheses, backend, *, temperature=1.0, close_threshold=10.0)`。
    **ChemPlausibility の降格は rank 前段のスコア調整 or rank 後の順位補正として配線**(除外しない)
- **search/tree.py**(M1) — FR-245 プライマリ探索の実体:
  - `HypothesisTreeSearch(...).search(two_theta, intensity, candidates, *, weights=None) -> SearchResult`
  - `SearchResult(ranked, hypotheses, ..., ledger, snapshots, warnings)` + `.to_summary() -> dict`(MCP list/compare が利用)
- **sequential/trajectory.py**(M2/M3) — MCP `get_trajectory` の委譲先:
  - `Trajectory(records, lifecycles).to_csv(path)` / `FrameRecord(...)`
- **selection/engine.py**(M2) — MCP `accept_hypothesis` / `revert` の委譲先(**そのまま P2 準拠**):
  - `FinalSelectionEngine(*, mode="agent"|"human", ledger=None, queue=None)` の
    `.decide(result, *, frame_index=None)` / `.accept(result, hypothesis_id, *, by)` /
    `.revert(hypothesis_id, *, note="")`(**superseded 化で削除しない**)/ `.set_mode(mode)`。
    **MCP の final_selection_mode 適用はこの set_mode/mode を経由**(FR-402 同一適用)
- **export/gpx.py**(M1) — MCP `export_gpx` の委譲先:
  - `export_gpx(path, phases, two_theta, intensity, *, weights=None, wavelength=...) -> str`(GSAS-II 未導入は `GSASUnavailableError`)
- **pipeline.py**(M0) — MCP `submit_analysis` の委譲先:
  - `analyze_single_pattern(...) -> AnalysisResult`
- **store**(`store/*.py`): `Ledger()`(`.append(kind, payload)`/`.verify()`)/ `SnapshotStore` / 永続化。
  **MCP 経由の全操作も同一 ledger に理由付き追記**(NFR-105)。`phase_to_dict`/`phase_from_dict` は
  **joint/コントラスト/ChemPlausibility の新フィールドを足すなら往復対称に拡張**
- **model/cell.py**(M3) — FR-317 末項「中性子吸収/多重散乱補正を同一 IF で切替」の接続点(M4 では最小)
- **公開 API**(`src/tsumugin/__init__.py::__all__`, 現在 **昇順固定・test で検証**): M4 追加シンボルもここへ末尾追加 + 昇順維持

**参照元(実 API 確認元)**: `src/tsumugin/model/{project,phase,hypothesis,channel,cell}.py`, `backends/{base,gsasii}.py`,
`evidence/{ic,ranking}.py`, `search/tree.py`, `sequential/trajectory.py`, `selection/engine.py`,
`export/gpx.py`, `pipeline.py`, `store/*.py`, `__init__.py`

### ⚠️ spec §4 データモデルと現行実装の差分(M4 で埋める必要のある要素)

| 仕様 §4 / FR の要素 | 現行実装 | M4 で必要な FR | 対応方針(推奨) |
|---|---|---|---|
| `HistogramRef` の TOF バンク DIFC/DIFA/ZERO | `project.py`:`HistogramRef(probe, data_ref, instprm_ref, bank_id)` に **DIFC 系未定義** | FR-241 TOF マルチバンク | `TofBankParams(difc, difa=0.0, zero=0.0)` 相当を新設し `HistogramRef` に optional フィールド末尾追加(非破壊) |
| joint 用マルチヒスト入力(構造共有 + ヒスト独立) | `backends/base.py`:`RefinementModel` は**単一ヒスト前提** | FR-242 joint 精密化 | `JointRefinementModel`(ヒストごと (2θ,I,w) 群 + shared/per-hist free_params)を新設。SimulatedBackend は χ² 加算で検証 |
| ヒストグラム重み | 単一 `weights` のみ | FR-243 | joint 入力にヒストごと weight スカラ(既定 統計)を持たせる |
| 中性子散乱長 b テーブル / コントラスト判定 | **未定義** | FR-244 | `chem`/`joint` に軽量 b テーブル(元素→fm)+ `recommend_occupancy_release`(|f−b| 閾値検出)を新設 |
| `PhaseRef`(FR-412 引数) | `PhaseInstance.phase_ref: str` はあるが `PhaseRef` 型は未定義 | FR-412 | 軽量 `PhaseRef`(相 ID + 組成/元素系のヒント)を新設 or 既存 str + context で代替(設計裁量) |
| `SynthesisContext` / `PlausibilityResult` / `ChemPlausibility` Protocol | **未定義** | FR-412 | `chem/` に frozen dataclass + Protocol を新設。v1 最小ルール 1 モジュール + 重み付き幾何平均合成 |
| MCP ツール群 | **未定義** | FR-513 | `mcp/` に SDK 非依存ツール実処理関数 + SDK アダプタ + `run_mem` スタブ境界を新設 |

## 関連実装

### M4 が土台にする M0〜M3 資産(再利用ポイント)
- **joint 検証精密化(FR-242/245)の探索段 = `search/tree.py::HypothesisTreeSearch`** — プライマリヒストグラムで探索し
  生存仮説のみ joint 精密化へ。**joint 段は `GSASIIBackend` のマルチヒストグラム経路 or `SimulatedBackend` の χ² 加算**で実装
- **joint 後の仮説比較 = `evidence/ranking.py::rank`** — joint 精密化済み仮説を bic で比較。**ChemPlausibility 降格を順位補正として配線**
- **MCP submit_analysis = `pipeline.py::analyze_single_pattern`**(単一)+ joint オーケストレーション(マルチヒスト)
- **MCP accept/revert = `selection/engine.py::FinalSelectionEngine.accept/.revert`** — **既に P2 準拠(revert=superseded 化)**。そのまま委譲
- **MCP get_trajectory = `sequential/trajectory.py::Trajectory.to_csv`** / **export_gpx = `export/gpx.py::export_gpx`**
- **追記専用 store + 永続化 = `store/*.py`** — joint 昇格・コントラスト提案・ChemPlausibility 降格・MCP 操作も**削除/上書き API を作らず**追記 + revert
- **GSAS-II 実バックエンド = `backends/gsasii.py::GSASIIBackend`** — FR-242 の joint は最終的に GSAS-II のマルチヒストグラム精密化へ配線

**参照元**: `src/tsumugin/{search/tree,evidence/ranking,pipeline,selection/engine,sequential/trajectory,export/gpx,store/*,backends/gsasii}.py`

### 参考パターン(M4 でも踏襲)
- **失敗は例外でなく chi2=inf の結果に変換**しガードレール/降格で処理(joint の 1 ヒスト精密化失敗も吸収)
- **降格のみ・候補除外しない**(Dara 教訓)。**ChemPlausibility は最重要適用点** — スコアで rank 順位を下げるのみ、rejected 化・除外はしない
- **全操作を理由付きで ledger 記録**(joint 昇格・コントラスト提案・降格スコア・MCP 経由の accept/revert/mode 切替)
- **エスカレーションは処理をブロックしない**(FR-403)。MCP 経由でも `final_selection_mode` を同一適用
- **決定論的順序**(ledger kind 順・canonical JSON ソート・ヒスト順・元素順)で NFR-102
- **境界は Protocol**(ChemPlausibility / MuCalculator / RefinementBackend と同型)。外部モジュール(LLM/熱力学)は IF 準拠で後付け

### 共通モジュール・ユーティリティ
- `backends/base.py::param_name` / `parse_param`(`"global.{key}"` 対応済 — コントラスト由来占有率解放の命名に活用)
- `store/ledger.py::_canonical_json` / `_compute_hash`(決定論的ハッシュチェーン。MCP 操作記録でも再利用)
- `_json.py::finite_or_none`(M3 Issue #5 で統合済 — MCP のシリアライズ応答でも非有限を漏らさない)
- `evidence/ranking.py::rank`(ChemPlausibility 降格の適用点)

### 依存関係・インポートパス
- 公開 import 例: `from tsumugin import HypothesisTreeSearch, FinalSelectionEngine, export_gpx, Trajectory, analyze_single_pattern`
- MCP SDK: `from mcp.server import Server`(optional extra `mcp`。未導入時は起動 API のみ friendly error に縮退)
- 依存導入は `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるので禁止**)。M4 で MCP を足すなら
  **新規 optional extra `--extra mcp`**。**ツール実処理関数は SDK 非依存**にして通常テストで網羅する

## 技術的制約

### パフォーマンス制約
- **FR-245 探索コスト抑制**: 木探索はプライマリヒストグラムのみ。joint は**生存仮説の検証精密化に限定適用**しコスト集中を避ける
- **NFR-103**: joint 精密化はヒスト数に比例。M4 テストは合成データ(2 ヒスト程度)で CI 実用時間内に収める

### セキュリティ制約(= 非破壊性制約 P2 / NFR-101 / NFR-105)
- **破壊的操作(生データ削除・上書き・履歴改変)の API を実装しない**。**MCP ツールにも破壊的操作を作らない**(revert=superseded 化のみ)
- **joint 昇格・コントラスト提案・ChemPlausibility 降格・MCP 経由の accept/revert/mode 切替**もすべて**追記 ledger 記録 + revert 可能**に保つ
- **MCP Server のバインド**: 既定はローカル(stdio トランスポート or `127.0.0.1`)。ネットワーク公開は解析データ全量の無認証公開になるため既定で避ける
- Review Queue Web UI に認証なし。既定 `127.0.0.1` バインド維持

### 互換性制約
- Python >= 3.12 固定。GSAS-II バージョン固定 + contract test(NFR-106)。**MCP SDK もバージョン固定**(optional extra 内で範囲指定)
- **公開 API の非破壊維持(REQ-404)**: `__all__` の既存シンボルを壊さない。新規は末尾追加 + 昇順維持
- 新フィールドは**末尾・既定値付き**で frozen dataclass へ非破壊追加(M2/M3 の `lifecycle`/`multistart`/`globals` 追加に倣う)

### データ制約
- chi2/rwp のセマンティクスはバックエンド間で統一(BIC/evidence 比較の一貫性)。joint はヒスト χ² の合算セマンティクスを統一
- **中性子散乱長 b は同位体で変わりうる**が v1 は元素代表値の静的テーブルで足る(FR-244 は推奨判定のみ)
- **ChemPlausibility スコアは [0,1]**。合成は重み付き幾何平均。**降格のみ**(候補除外禁止)

**参照元**: `CLAUDE.md`(実装上の不変条件), `docs/tsumugin_spec_v0.3.md`§3, §6, §8, §10, §11, §14

## 注意事項

### 開発時の注意点(M4 固有)
- **既存の器を最大活用**: `Probe`(中性子 3 種)・`HistogramRef`(instprm/bank)・`Frame.histograms`(複数)は**既に導入済**。
  M4 は**中身(DIFC 系・joint オーケストレーション・コントラスト判定)**を足すのが主で、器の破壊的変更は不要
- **joint は「検証精密化」段で接続**(FR-245): 木探索/operando/sequential など既存機能は**変更最小**。joint は探索後段に差し込む
- **`run_mem` は MEM 本体でなく境界のみ**(M5 委譲): MCP ツールとして受け口は作るが、内部は `MEMBackend` 未実装 →
  `NotImplementedError` 相当の明示エラー or 「M5 で提供予定」プレースホルダ応答。**破壊的でないこと・スキーマは将来と互換**を要件で明記
- **ChemPlausibility の最重要不変条件 = 降格のみ・除外しない**(Dara 教訓)。スコアで rank 順位を軽く下げるに留め、
  rejected 化や候補集合からの除去は**実装しない**。テストで「低スコア相が rank から消えない」ことを固定
- **MCP SDK は optional extra**: SDK 非依存の「ツール実処理関数」と SDK 依存の「アダプタ」を分離。
  未導入環境ではアダプタ起動のみ friendly error、実処理関数は通常テストで網羅。**NFR-102 のため MCP 経由でも決定論**
- **final_selection_mode は MCP でも同一適用**(FR-402/513): `accept_hypothesis` は現在モードに従い、
  `human` モードでは agent が勝手に accepted 化しない。mode 切替も ledger 記録

### Issue / 技術負債
- M3 完了時点で未解決の LOW 指摘があれば M4 スコープで併せて解消候補とする(M3 の #3/#4/#5 は M3 で解消済み想定)。
  M4 固有の新規 Issue は PR レビュー(`/code-review`)で洗い出す

### デプロイ・運用時の注意点
- GSAS-II 起動時の `~/.GSASII/config.ini` 読込警告(cp932)は無害(upstream 表示バグ)
- M4 で新規公開 API・依存(`mcp` SDK)を足したら `docs/dev/context.md`(Tech Stack / 公開 API / スコープ)と `README.md` を更新
- MCP Server の起動手順・ツール一覧・`final_selection_mode` の扱いを README に追記

### セキュリティ/非破壊上の注意点
- 新規の joint 昇格・コントラスト提案・降格・MCP 操作でも**削除/上書き API を作らない**(P2 の構造的保証)。全て追記 + revert
- MCP `revert` は superseded 化(削除でない)。破壊的操作は MCP ツールに存在させない
- MCP Server は既定ローカルバインド。ネットワーク公開時の認証は M4 スコープ外(要件で明記し既定安全側に倒す)

### パフォーマンス上の注意点
- joint はヒスト数に比例するコスト増 → **FR-245 で生存仮説のみに限定適用**
- コントラスト判定・スコア合成は軽量(静的テーブル参照 + 算術)。決定論順序を守ればコスト無視できる

## Git情報

### 現在のブランチ
`milestone/m4-joint-mcp`(M3 マージ済み `main` から分岐予定)

### 最近のコミット(抜粋)
```
bfce209 docs: GUI/フロントエンド技術選定を ADR-0001 として確定 (#7)
4497ed9 Merge pull request #6 from tomooki/milestone/m3-operando
508b74a refactor(operando): 残 MEDIUM/LOW 対応 — bic 式を BICBackend へ単一情報源化 + to_csv 二重ソート解消
...(M3 operando / M2 / M1 / M0)
```

### 開発状況
M0 + M1 + M2 + M3 完了・main にマージ済み。GSAS-II 導入済み。
M4 ブランチを切る段階で、これから kairo-requirements → kairo-design → kairo-tasks → kairo-implement を回す。

## 収集したファイル一覧

### プロジェクト基本情報
- `CLAUDE.md` / `README.md` / `docs/dev/context.md` / `pyproject.toml`
- (`AGENTS.md`, `docs/rule/` は不在 — 規約は CLAUDE.md に集約)

### 仕様書(正)
- `docs/tsumugin_spec_v0.3.md`(FR/NFR の正。M4 = §6 FR-240, §8 FR-412, §10 FR-513, §4 データモデル, §13 M4 行, §11 NFR)

### 参考(M1/M2/M3 の同種成果物)
- `docs/spec/{m1-hypothesis-search,m2-sequential,m3-operando}/{note,requirements,user-stories,acceptance-criteria,prep,interview-record}.md`

### 関連実装(M4 の土台となる M0〜M3 資産・実 API 確認済み)
- `src/tsumugin/__init__.py`(公開 API `__all__`)
- `src/tsumugin/model/{project,phase,hypothesis,channel,cell}.py`(**§4 差分の埋め対象**: TofBankParams / PhaseRef / SynthesisContext)
- `src/tsumugin/backends/{base,simulated,gsasii}.py`(joint 精密化 FR-242 の拡張点)
- `src/tsumugin/evidence/{ic,ranking}.py`(ChemPlausibility 降格・joint 後比較の適用点)
- `src/tsumugin/search/tree.py`(FR-245 プライマリ探索)
- `src/tsumugin/selection/engine.py`(MCP accept/revert の委譲先・P2 準拠)
- `src/tsumugin/sequential/trajectory.py`(MCP get_trajectory の委譲先)
- `src/tsumugin/export/gpx.py`(MCP export_gpx の委譲先)
- `src/tsumugin/pipeline.py`(MCP submit_analysis の委譲先)
- `src/tsumugin/store/{ledger,snapshot,persistent,serialization}.py`(追記専用・MCP 操作記録)

---

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
設計文書(`docs/design/m4-joint-mcp/*`)・M4 要件定義は本ノートの後工程で生成されます。
