# m5-nested-mem-oed 開発コンテキストノート

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

**本ノートの対象マイルストーン = M5**(仕様 §13 の行:
「**nested sampling 裁定** + **MEM(Dysnomia 連携)** + **OED 提案** + **較正済み確率** + ベンチ公開」):
> (A) nested sampling 裁定 **FR-121/122/124/125** (+ Laplace evidence **FR-121**) /
> (B) MEMBackend **FR-600〜606** (Dysnomia 連携) / (C) OED / 測定フィードバック **FR-430/431/432** /
> (D) 較正済み確率 (reliability diagram / ECE) **FR-124 / §12-5**。

**スコープ外(M-later)**: ab initio 構造決定・PDF/磁気/2D 方位解析(§1.2 非スコープ)・
MEM-Rietveld 反復の条件付き auto 運転本実装(v1 既定オフ)・PyBOED 獲得関数による次測定「実行」
(v1 は提案生成のみ)・較正ベンチの公開運用(実装までが M5、公開基盤は M-later)。

**参照元**: `CLAUDE.md`, `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`(仕様の正)、
直前 MS 成果物 `docs/spec/m4-joint-mcp/*`

## 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12(uv 管理, src layout + hatchling ビルド)
- **数値**: numpy >= 1.26(コア)。**コア import は numpy のみ**(nested/mem/oed は optional extra)
- **ランタイム**: CPython 3.12。Rietveld バックエンド = GSAS-II 2.0(`from GSASII import GSASIIscriptable`)
- **Web UI(M1 導入済)**: FastAPI + uvicorn(optional extra `web`、read-only)
- **MCP Server(M4 導入済)**: 公式 MCP Python SDK(optional extra `mcp`)。SDK 非依存のツール実処理層
  (`mcp.tools`)+ SDK 依存アダプタ(`mcp.server`)の 2 層分離。`run_mem` 委譲境界(`mcp.mem`)は M5 で実体化
- **永続化(M2 導入済)**: JSONL 追記(`PersistentLedger` / `PersistentSnapshotStore`)。追記専用 +
  ハッシュチェーン + 非破壊 revert

### M5 新規で検討が要る外部依存(未導入・すべて optional extra)
- **nested sampling(FR-121/122)**: `dynesty` / `ultranest`。
  `[project.optional-dependencies] nested = ["dynesty>=2.1"]`(or ultranest)を追加し
  `uv sync --extra nested` で導入。**未導入環境では nested 実行 API のみ `NestedUnavailableError`**
  (`MCPUnavailableError` / `WebUIUnavailableError` と対称)で縮退。evidence 計算(bic/aic/laplace)と
  コア import は SDK 非依存で動作。
- **MEM(FR-600〜606)**: `Dysnomia`(外部バイナリ・PyPI 非公開)。GSAS-II と同様に**バイナリ導入 +
  ラッパ**。`mem = [...]`(ラッパが必要とする Python 依存があれば列挙。Dysnomia 本体は README 手順で導入)を
  optional extra とし、**未導入時は `MEMUnavailableError`**(M4 で errors.py に定義済)へ縮退。
- **OED(FR-430/431/432)**: `PyBOED`(獲得関数)。`oed = ["pyboed>=..."]` を optional extra とし、
  **v1 は提案生成のみ**(PyBOED 未導入でも提案生成は動作)。獲得関数接続 API のみ `OEDUnavailableError`。
- **バージョン固定 + contract test(NFR-106)**: Dysnomia / dynesty / ultranest / PyBOED は GSAS-II と
  同様にバージョン固定。外部バイナリ(Dysnomia)は入出力ファイル契約を固定した contract test を用意。

### アーキテクチャパターン
- **スタイル**: レイヤ分離(Interfaces / Agent / Orchestrator / Workers / Data、仕様 §3)。境界はすべて
  `typing.Protocol` で抽象化しバックエンド交換可能(P7)
- **設計パターン**: frozen dataclass の不変値オブジェクト + `with_updates()` / `dataclasses.replace()` に
  よる非破壊更新。全状態遷移は追記専用 Ledger(ハッシュチェーン)+ SnapshotStore(revert 可能)に記録
  (P2 / NFR-101 / NFR-105)
- **ディレクトリ構造(M4 まで実装済み・M5 が土台にする範囲)**:
  ```
  src/tsumugin/
  ├── model/       # project.py(Probe/HistogramRef/Frame), phase.py, hypothesis.py(RefinementMetrics),
  │                #   channel.py, cell.py, tof.py(TofBankParams) ← M4
  ├── backends/    # base.py(RefinementBackend/RefinementModel/RefinementResult/param_name/parse_param)
  │                #   + simulated.py + gsasii.py
  ├── refinement/  # staged.py + guardrails.py
  ├── evidence/    # base.py(EvidenceBackend Protocol/EvidenceResult{value,logz_err}) + ic.py(BIC/AIC)
  │                #   + ranking.py(rank: softmax+温度較正/close_competitor) ← M5 が laplace/nested を足す主対象
  ├── joint/       # model.py(JointHistogram/JointRefinementModel/JointRefinementResult) + engine + weights
  │                #   + contrast + verification.py(verify_survivors) ← M5 MEM の入力元
  ├── chem/        # base.py(ChemPlausibility Protocol) + rules + compose + ranking ← 降格のみ思想の手本
  ├── mcp/         # tools.py(8 ツール実処理/AnalysisSession) + server.py(SDK アダプタ)
  │                #   + mem.py(run_mem_boundary) ← M5 で MEMBackend へ実体化する境界
  ├── multistart/  # M3(FR-230)。nested 前段の basin/摂動
  ├── operando/    # M3(FR-311/313/316/317)
  ├── sequential/  # engine/changepoint/lifecycle/thermal/trajectory ← MEM スポット解析のフレーム指定元
  ├── selection/   # engine(FinalSelectionEngine.accept/revert/decide/set_mode) — final_selection_mode
  ├── search/      # tree.py(HypothesisTreeSearch) — bic 探索(nested 化しない)
  ├── export/      # gpx.py(export_gpx)
  ├── store/       # ledger.py + snapshot.py + persistent.py + serialization.py ← MEM 子スナップショット追記
  ├── errors.py    # MEMUnavailableError(M4 定義済)・MCPUnavailableError 等 ← nested/oed 例外を足す
  └── pipeline.py  # analyze_single_pattern
  tests/           # 実装ファイルと 1:1、外部依存は @pytest.mark.{nested,mem,oed} 相当で分離
  docs/spec/       # kairo 要件・設計・タスク(本ノートを含む)
  ```
  **M5 が新設する見込みの層**:
  - `evidence/laplace.py`(`LaplaceBackend`)/ `evidence/nested.py`(`NestedBackend` + 遅延 import)/
    `evidence/adjudication.py`(階層的裁定 = bic 一次 + 競合のみ nested)/ `evidence/calibration.py`
    (reliability diagram / ECE)
  - `mem/`(`MEMBackend` Protocol / `DysnomiaBackend` 遅延 import ラッパ / F_obs 抽出・入力生成 /
    MEM-Rietveld 反復 / 出力(.grd/断面/最小密度)/ 適用ガード)
  - `oed/`(判別測定提案 JSON スキーマ生成 / PyBOED 獲得関数接続境界)
  - `errors.py` 拡張(`NestedUnavailableError` / `OEDUnavailableError`)
  - `mcp/mem.py` 実体化(`run_mem_boundary` を MEMBackend 委譲へ差し替え・M4 placeholder 契約維持)

**参照元**: `CLAUDE.md`, `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`§5(FR-121系)/§8(FR-430系)/
§9(FR-600系)/§11(NFR)/§12-5(較正ベンチ)

## 開発ルール

### プロジェクト固有のルール(必須・違反禁止)
- **TDD 厳守**: Red(失敗テスト)→ Green(最小実装)→ Refactor。テストなしの実装コミット禁止
- **タスク毎コミット**: タスク 1 件完了(テスト green)ごとに 1 コミット
- **ブランチ運用**: マイルストーン毎にブランチ。M5 は `milestone/m5-nested-mem-oed`。完了時に PR →
  `/code-review`(HIGH 以上に限らず MEDIUM/LOW も修正、新規指摘が出なくなるまでループ)→ マージはユーザー判断
- **モデル指定**: kairo/dev の全エージェント(サブエージェント含む)を **Opus** で実行する
- **成果物の保存先**: 要件定義・設計・タスク分割は `docs/` 配下

### コーディング規約
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE
- **型チェック**: 型注釈必須(`any` 回避)。境界は `typing.Protocol`(`@runtime_checkable`)
- **コメント/docstring**: 日本語 docstring 可。FR/NFR/REQ 番号を docstring に紐づける慣習(信頼性レベル 🔵🟡🔴 表記)
- **フォーマット/Lint**: `uvx ruff check src tests`(line-length 100, target py312)
- **データモデリング**: frozen dataclass 基本。更新は新インスタンス生成 + Snapshot 追記のみ。
  **新フィールドは末尾・既定値付きで非破壊追加**(REQ-404)

### テスト要件
- **フレームワーク**: pytest >= 8 + pytest-cov(+ httpx, dev グループ)
- **コマンド**: `uv run pytest`(既定)/ `uv run pytest --cov=tsumugin` / `uv run pytest -m gsas`
- **依存導入**: `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるため禁止**)。
  M5 で `--extra nested` / `--extra mem` / `--extra oed` を新設(未導入環境では該当実行 API を friendly
  error に縮退・境界/入力生成/提案/較正は SDK/バイナリ非依存で網羅)
- **マーカー**: `gsas`(既存)に加え、M5 で `nested` / `mem` / `oed` の optional マーカーを追加検討
  (`@pytest.mark.mcp` の前例踏襲)。**境界・入力生成・提案スキーマ・較正評価は外部依存なしで通常テスト網羅**

**参照元**: `CLAUDE.md`, `docs/dev/context.md`, `pyproject.toml`

## 既存の要件定義

### 要件定義書
M5 専用の要件定義書は `docs/spec/m5-nested-mem-oed/requirements.md`。正の要件は
`docs/tsumugin_spec_v0.3.md` の FR/NFR 番号。M5 スコープに対応する主要 FR:

- **FR-120 Evidence Engine(多バックエンド)** §5
  - FR-121: `laplace`(Hessian 由来 Laplace 近似・中コスト)/ `nested`(dynesty/UltraNest・logZ±誤差・高コスト)
  - FR-122: **階層的裁定** — 木探索は bic、生存上位仮説で evidence 差 < 閾値(既定 ΔBIC<10)の競合のみ
    nested 再裁定の 2 段構え。フル nested も設定で可能
  - FR-123: ノイズ標準偏差の明示推定(EM 反復)と尤度反映(既存 σ 由来明示と接続)
  - FR-124: 確率は softmax + 温度較正。backend 間で確率の意味が異なる(BIC 近似 vs logZ)をレポート明記
  - FR-125: `nested` 事前分布は精密化 restraint から自動構成・手動上書き可
- **FR-430 OED / 測定フィードバック** §8
  - FR-431: 僅差競合時の判別測定提案(高統計再測定・追加温度点・joint 用中性子測定・組成分析)を情報利得順で
    提案する JSON スキーマ
  - FR-432: PyBOED 獲得関数への接続。**v1 は提案生成のみ**
- **FR-600 MEMBackend** §9
  - FR-601: 精密化済み仮説から F_obs(位相はモデル由来)抽出 → MEM 入力自動生成。X線→電子密度・中性子→核密度
  - FR-602: `MEMBackend` 抽象 IF。v1 実装は Dysnomia 連携(外部バイナリラッパ)。将来ソルバも同一 IF
  - FR-603: MEM-Rietveld 反復(MPF 型)。**既定オフ**・最大反復数/収束判定・**各サイクルは子スナップショット**
  - FR-604: 出力 — 密度マップ(VESTA 互換 .grd)・1D/2D 断面・ボンド経路最小密度
  - FR-605: 適用ガード — joint 済み単相/主相支配を推奨。多相/低統計は**信頼性警告(除外はしない)**
  - FR-606: シーケンシャルの指定フレームへのスポット解析

### 主要な非機能要件
- **NFR-101 / P2**: 破壊的操作の API 非実装。nested 裁定・MEM 反復・OED 提案・較正評価も**全て追記 + revert**
- **NFR-102**: 再現性 — 乱数種固定でビット同一。**nested はサンプラー種固定 + logZ 誤差併記**
- **NFR-103**: 性能 — **nested 裁定は 1 仮説 ≤ 30 分目標・超過時は打ち切り + Laplace 代替 + 警告**
- **NFR-105**: ledger 追記専用 + ハッシュチェーン(`verify()` 常時 True)
- **NFR-106**: GSAS-II / Dysnomia バージョン固定 + contract test
- **NFR-107**: σ の由来(共分散 / 逐次相関 / マルチスタート分散)をレポート明示

## 既存の設計文書

### データフロー(M5 が新設する層のイメージ)
```
[nested 裁定(FR-121/122/124/125)]
  木探索(bic, HypothesisTreeSearch 不変) → 生存仮説 rank(softmax+温度較正, close_competitor)
    └─ 僅差競合 (ΔBIC<10) のみ → nested 再裁定 (dynesty/ultranest, 事前分布=restraint 自動構成)
         → logZ±誤差 (EvidenceResult.value=-logZ, logz_err) → 確率再計算
         └─ 30 分超過 → 打ち切り + Laplace 代替 + 警告 (NFR-103)
    └─ フル nested 運転設定なら全生存仮説を nested 裁定
  較正評価(reliability diagram / ECE, bic と nested 別系列)

[MEM(FR-600〜606)]
  joint 検証済み仮説(JointVerificationResult) → F_obs 抽出(位相=モデル由来)
    → 適用ガード判定(joint 済み単相/主相支配? 多相/低統計は警告のみ・除外しない)
    → MEM 入力自動生成(X線=電子密度 / 中性子=核密度) → MEMBackend(DysnomiaBackend, 遅延 import)
         └─ 未導入 → MEMUnavailableError
    → 出力(.grd / 1D-2D 断面 / ボンド経路最小密度)
    └─ (既定オフ)MEM-Rietveld 反復: MEM 密度→F_calc 更新→再精密化, 各サイクル=子スナップショット追記
  MCP: mcp/mem.py::run_mem_boundary → MEMBackend 委譲(M4 placeholder 契約と整合)

[OED(FR-430/431/432)]
  僅差競合検出(rank.close_competitor / ΔlogZ<閾値)
    → 判別測定提案(高統計再測定/追加温度点/中性子測定/組成分析)を情報利得順 JSON 生成
    → ledger 追記のみ(非破壊・状態変更なし)
    └─ PyBOED 獲得関数接続は境界のみ(未導入 → OEDUnavailableError, v1 は提案生成のみ)
```

### 型/インターフェース定義(**実 API 署名を確認済** — 2026-07-04 時点のソース)

M5 が依存・拡張する M0〜M4 の実インターフェース(すべて frozen dataclass / Protocol):

- **evidence/base.py** — nested/laplace の実装対象:
  - `EvidenceResult(backend: str, value: float, logz_err: float | None = None)`
    (**logz_err は nested 用に M0 で既に定義済**・小さいほど良い規約)
  - `EvidenceBackend` Protocol: `name: str` + `score(metrics: RefinementMetrics) -> EvidenceResult`
- **evidence/ic.py** — 符号規約・フォールバックの手本:
  - `BICBackend`(既定)/ `AICBackend`。`value = chi2 + n_params*ln(n)`。Laplace は BIC フォールバック先
- **evidence/ranking.py** — 階層的裁定・確率較正・OED 発動の接続点:
  - `rank(hypotheses, backend, *, temperature=1.0, close_threshold=10.0) -> tuple[RankedHypothesis,...]`。
    `RankedHypothesis(hypothesis, evidence, probability, close_competitor)`。
    **close_competitor(ΔBIC<10)を nested 再裁定対象・OED 発動条件に再利用**。softmax(-value/2T) は
    温度較正の実体
- **joint/verification.py** — MEM の入力元:
  - `verify_survivors(...) -> JointVerificationResult(verified, joint_results, recommendations, warnings)`。
    `joint_results: Mapping[str, JointRefinementResult]`(集約 + ヒスト別)から F_obs 抽出
  - `JointRefinementResult(aggregate: RefinementResult, per_histogram, warnings)`、
    `JointHistogram(two_theta, intensity, probe, ...)`(probe で MEM 密度種別を分岐)
- **mcp/mem.py** — M5 で実体化する境界(**現状は M4 プレースホルダ**):
  - `run_mem_boundary(session, *, placeholder=False, **params) -> dict`。
    既定 `MEMUnavailableError` 送出 / `placeholder=True` で `{"status":"not_implemented","milestone":"M5",
    "tool":"run_mem"}`。**M5 は placeholder=False 経路を MEMBackend 委譲へ差し替え、スキーマ将来互換を維持**
- **mcp/tools.py** — MCP 8 ツール:
  - `run_mem(session, **params) -> dict` は `_mem.run_mem_boundary` へ委譲(SDK 非依存)。素の型 dict のみ返す
- **errors.py** — 例外階層(**M4 で MEMUnavailableError 定義済**):
  - `MEMUnavailableError`(FR-601〜606, M5 で実処理接続)/ `MCPUnavailableError` / `WebUIUnavailableError`
    (「available + 専用例外」パターン)。**M5 で `NestedUnavailableError` / `OEDUnavailableError` を同型追加**
- **selection/engine.py** — final_selection_mode の単一経路:
  - `FinalSelectionEngine(*, mode, ledger, queue).accept/.revert/.decide/.set_mode`。
    **human モードでは nested/OED/MEM は推奨提示に留める**
- **store**(`store/*.py`): `Ledger()`(`.append(kind, payload)`/`.verify()`)/ `SnapshotStore`(**MEM 子
  スナップショット追記先・追記型**)/ 永続化。全 M5 操作も同一 ledger に理由付き追記(NFR-105)
- **公開 API**(`src/tsumugin/__init__.py::__all__`, 昇順固定・test で検証): M5 追加シンボルも末尾追加 + 昇順維持

**参照元(実 API 確認元)**: `src/tsumugin/evidence/{base,ic,ranking}.py`, `joint/{model,verification}.py`,
`mcp/{tools,mem}.py`, `errors.py`, `selection/engine.py`, `backends/base.py`, `store/*.py`, `__init__.py`

### ⚠️ spec §4/§9 データモデルと現行実装の差分(M5 で埋める必要のある要素)

| 仕様 FR の要素 | 現行実装 | M5 で必要な FR | 対応方針(推奨) |
|---|---|---|---|
| `laplace` evidence | `evidence/ic.py` は bic/aic のみ | FR-121 | `evidence/laplace.py`:`LaplaceBackend`(Hessian 近似・BIC フォールバック) |
| `nested` evidence | 未実装。`EvidenceResult.logz_err` の器はあり | FR-121/125 | `evidence/nested.py`:`NestedBackend`(遅延 import・restraint 事前分布・logZ±誤差) |
| 階層的裁定(bic 一次 + 競合のみ nested) | `rank.close_competitor` はあるが再裁定配線なし | FR-122 | `evidence/adjudication.py`:close_competitor 群のみ nested 再裁定・フル nested 設定 |
| 確率較正(reliability/ECE) | `rank` に softmax+温度はあるが較正評価なし | FR-124/§12-5 | `evidence/calibration.py`:reliability diagram / ECE(bic と nested 別系列) |
| `MEMBackend` Protocol / Dysnomia 連携 | **未実装**(`run_mem` は placeholder 境界のみ) | FR-600〜606 | `mem/` 新設:Protocol + DysnomiaBackend(遅延 import)+ 入力生成 + 反復 + 出力 + ガード |
| MEM 入力(F_obs 抽出) | joint 結果(`JointRefinementResult`)はあるが F_obs 抽出なし | FR-601 | joint 集約から F_obs(位相=モデル由来)抽出・probe で密度種別分岐 |
| MEM 子スナップショット反復 | `SnapshotStore` はあるが MEM 反復なし | FR-603 | 既定オフの MPF 反復・各サイクル子スナップショット追記(非破壊) |
| OED 提案 JSON | **未実装** | FR-431/432 | `oed/` 新設:判別測定提案 JSON(情報利得順)+ PyBOED 境界(v1 提案のみ) |
| `NestedUnavailableError` / `OEDUnavailableError` | 未定義(`MEMUnavailableError` は定義済) | FR-121/432 | `errors.py` に「available + 専用例外」で同型追加 |
| `run_mem` 実体化 | `mcp/mem.py` は placeholder | FR-513/FR-600系 | placeholder=False 経路を MEMBackend 委譲へ差し替え・M4 契約維持 |

## 関連実装

### M5 が土台にする M0〜M4 資産(再利用ポイント)
- **nested 再裁定の入口 = `evidence/ranking.py::rank` の `close_competitor`** — ΔBIC<10 の僅差競合群のみ
  nested へ回す(木探索 `search/tree.py` は bic 固定・不変)
- **nested/laplace の value 符号規約 = `evidence/ic.py`(小さいほど良い)** に統一。`EvidenceResult.logz_err`
  (M0 定義済)に nested 誤差を格納
- **MEM の入力元 = `joint/verification.py::verify_survivors` の `JointRefinementResult`** — joint 済み仮説の
  F_obs(位相=モデル由来)を抽出。probe(`JointHistogram.probe`)で電子密度/核密度を分岐
- **MEM 子スナップショット = `store/snapshot.py::SnapshotStore`(追記型)** — MPF 反復の各サイクルを子として
  追記。削除/上書き API を作らない(P2)
- **run_mem 実体化 = `mcp/mem.py::run_mem_boundary`(M4 プレースホルダ)** — placeholder=False 経路を
  MEMBackend 委譲へ。M4 の placeholder=True dict スキーマは後方互換維持
- **OED / nested の human モード整合 = `selection/engine.py::FinalSelectionEngine`** — human モードでは
  推奨提示に留める
- **例外の縮退パターン = `errors.py::MEMUnavailableError`(M4 定義済)** — nested/oed も「available + 専用
  例外」で同型追加

### 参考パターン(M5 でも踏襲)
- **失敗は例外でなく chi2=inf / 縮退値に変換**しガードレール処理(nested 打ち切りは Laplace 代替へ縮退・例外化しない)
- **降格/警告のみ・除外しない**(Dara 教訓)。**MEM 適用ガードは信頼性警告のみで仮説除外しない**(FR-412 と同型)
- **全操作を理由付きで ledger 記録**(nested 裁定の振り分け・MEM 反復サイクル・OED 提案・較正結果)
- **エスカレーションは処理をブロックしない**(FR-403)。human モードでも情報提示は継続
- **決定論的順序**(ledger kind 順・canonical JSON ソート・反射順・提案順・ビン順)で NFR-102。
  **nested のみサンプラ種固定 + logZ±誤差**で再現性(確率的性質を誤差で明示)
- **境界は Protocol**(MEMBackend / EvidenceBackend / ChemPlausibility と同型)。外部(Dysnomia/dynesty/
  PyBOED)は遅延 import + 未導入時 friendly error

### 共通モジュール・ユーティリティ
- `evidence/ranking.py::rank`(close_competitor = nested 再裁定 + OED 発動の単一情報源)
- `store/ledger.py::_canonical_json` / `_compute_hash`(決定論ハッシュチェーン。M5 操作記録でも再利用)
- `_json.py::finite_or_none`(nested logZ・MEM 密度統計・OED 情報利得の非有限を漏らさない・MCP 応答安全化)
- `backends/base.py::param_name` / `parse_param`(`"global.{key}"` 対応済 — nested 事前分布パラメータ命名)

### 依存関係・インポートパス
- 公開 import 例: `from tsumugin import rank, verify_survivors, FinalSelectionEngine`
- nested SDK: `import dynesty`(or `ultranest`)(optional extra `nested`。未導入時 `NestedUnavailableError`)
- MEM: Dysnomia バイナリ + ラッパ(optional extra `mem`。未導入時 `MEMUnavailableError`)
- OED: `import pyboed`(optional extra `oed`。未導入時 `OEDUnavailableError`・v1 提案生成は非依存)
- 依存導入は `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるので禁止**)。M5 で
  `--extra nested` / `--extra mem` / `--extra oed` を新設。**境界/入力生成/提案/較正は外部依存なしで網羅**

## 技術的制約

### パフォーマンス制約
- **NFR-103 nested 時間上限**: nested 裁定は 1 仮説 ≤ 30 分目標。超過時は打ち切り + Laplace 代替 + 警告
- **FR-122 コスト抑制**: 木探索は bic 固定。nested は**僅差競合のみに限定適用**(フル nested は明示設定)
- **FR-606 MEM スポット**: MEM は指定フレームのスポット解析。全フレーム自動反復を既定にしない
- M5 テストは合成データ + モック外部依存で CI 実用時間内に収める。実サンプラ/実バイナリは `@pytest.mark` 分離

### セキュリティ制約(= 非破壊性制約 P2 / NFR-101 / NFR-105)
- **破壊的操作(生データ削除・上書き・履歴改変)の API を実装しない**。**MEM 反復・OED 提案・nested 裁定にも
  破壊的操作を作らない**(MEM 反復は子スナップショット追記のみ・revert 可能)
- **全操作を追記 ledger 記録 + revert 可能**に保つ(nested 振り分け・MEM サイクル・OED 提案・較正結果)
- 外部バイナリ(Dysnomia)の入出力ファイルは一時領域に自動生成・回収。生データ改変はしない

### 互換性制約
- Python >= 3.12 固定。GSAS-II / Dysnomia / dynesty / ultranest / PyBOED バージョン固定 + contract test(NFR-106)
- **公開 API の非破壊維持(REQ-404)**: `__all__` の既存シンボルを壊さない。新規は末尾追加 + 昇順維持
- 新フィールド/新例外は**末尾・既定値付き / 同型追加**で非破壊(M4 の TofBankParams/MEMUnavailableError に倣う)
- **M4 の run_mem placeholder 契約(`placeholder=True` dict スキーマ)を後方互換維持**

### データ制約
- **evidence value はバックエンド間で符号規約統一(小さいほど良い)**。nested は `-logZ` 相当 + `logz_err`
- **nested はサンプラ種固定でも logZ は確率的** → ビット同一でなく logZ±誤差で再現性を保証(NFR-102 の nested 例外)
- **MEM 適用ガードは警告のみ**(候補除外禁止・Dara 教訓)
- **中性子散乱長 / X線散乱因子**は M4 の軽量静的テーブルを再利用(MEM 密度種別分岐に活用・重依存不可)

**参照元**: `CLAUDE.md`(実装上の不変条件), `docs/tsumugin_spec_v0.3.md`§5, §8, §9, §11, §12, §14, §15

## 注意事項

### 開発時の注意点(M5 固有)
- **既存の器を最大活用**: `EvidenceResult.logz_err`・`rank.close_competitor`・`JointRefinementResult`・
  `SnapshotStore`・`mcp/mem.py::run_mem_boundary`・`MEMUnavailableError` は**既に導入済**。
  M5 は**中身(nested/laplace 実装・MEM 実処理・OED 提案・較正評価)**を足すのが主
- **nested は 2 段構えで接続**(FR-122): 木探索/rank は変更最小。nested は rank の close_competitor 群に
  差し込む上段として実装。**探索段を nested 化しない**
- **nested の再現性は logZ±誤差**(NFR-102 の例外): サンプラ種固定でもビット同一は保証できないため、
  `logz_err` を必ず併記し、テストは「誤差範囲内で一致」を検証する
- **nested の暴走防止**(NFR-103): 30 分上限 + 打ち切り + Laplace 代替を**例外でなく縮退**で実装。
  Laplace を M5 で先に実装しておくこと(nested の代替先として必須)
- **MEM 適用ガード = 警告のみ・除外しない**(Dara 教訓・FR-412 と同型の最重要不変条件)。多相/低統計でも
  MEM 実行は継続。テストで「ガード発動時も仮説除外なし」を固定
- **MEM 反復は既定オフ + 子スナップショット**(FR-603/§15-3): MPF 反復を回すなら各サイクルを子スナップ
  ショットに追記。**親仮説・joint 結果は不変**。削除/上書き API を作らない(P2)
- **run_mem 実体化は M4 契約維持**: `mcp/mem.py` の placeholder=False 経路のみ差し替え。placeholder=True の
  dict スキーマは後方互換維持。MEMBackend 未導入時は `MEMUnavailableError` を MCP エラー dict へ変換
- **OED は v1 提案生成のみ**(FR-432): PyBOED 獲得関数接続は境界のみ。提案は非破壊(ledger 追記のみ)。
  僅差競合(close_competitor)を発動条件に再利用
- **外部依存は全て optional extra**: nested/mem/oed。SDK 非依存の「境界・入力生成・提案スキーマ・較正評価」を
  通常テストで網羅。実サンプラ/実バイナリは `@pytest.mark.{nested,mem,oed}` で分離

### Issue / 技術負債
- §15-5「nested 事前分布自動構成は M5 で失敗モード検証の上で確定(実装時確定)」— M5 の実装時課題
- nested 閾値(ΔBIC 再裁定閾値・温度較正値)は較正ベンチ(§12-5)で数値較正。M5 はテストで既定値を凍結
- Dysnomia 入出力ファイル契約は実バイナリで contract test 確立時に固定(NFR-106)
- M5 固有の新規 Issue は PR レビュー(`/code-review`)で洗い出す

### デプロイ・運用時の注意点
- GSAS-II 起動時の `~/.GSASII/config.ini` 読込警告(cp932)は無害(upstream 表示バグ)
- M5 で新規公開 API・依存(nested/mem/oed extra)を足したら `docs/dev/context.md`・`README.md` を更新
- nested/MEM/OED の起動手順・外部依存導入(Dysnomia バイナリ・dynesty/ultranest/pyboed)を README に追記

### セキュリティ/非破壊上の注意点
- 新規の nested 裁定・MEM 反復・OED 提案・較正評価でも**削除/上書き API を作らない**(P2 構造保証)。全て追記 + revert
- MEM 反復は子スナップショット追記(破壊でない)。外部バイナリ入出力は一時領域・生データ改変なし

### パフォーマンス上の注意点
- nested は 30 分上限 + 僅差競合限定で暴走防止。フル nested は明示設定時のみ
- MEM は指定フレームのスポット解析。全フレーム自動反復を既定にしない(FR-606)
- 較正評価・OED 提案は軽量(算術 + JSON 生成)。決定論順序を守ればコスト無視できる

## Git情報

### 現在のブランチ
`milestone/m5-nested-mem-oed`(M4 マージ済み `main` から分岐予定)

### 最近のコミット(抜粋)
```
c627f90 Merge pull request #8 from tomooki/milestone/m4-joint-mcp
81eee98 fix(m4): 再レビュー指摘 — submit(single) の NaN 確率も有限化 (F1 残存)
d9ebcdd feat(m4): TASK-0046 公開 API 統合 + M4 E2E + ドキュメント
...(M4 joint/MCP / M3 operando / M2 / M1 / M0)
```

### 開発状況
M0 + M1 + M2 + M3 + M4 完了・main にマージ済み。803 tests green / 5 skipped / cov 96%。GSAS-II 導入済み。
M5 ブランチを切る段階で、これから kairo-requirements → kairo-design → kairo-tasks → kairo-implement を回す。

## 収集したファイル一覧

### プロジェクト基本情報
- `CLAUDE.md` / `README.md` / `docs/dev/context.md` / `pyproject.toml`

### 仕様書(正)
- `docs/tsumugin_spec_v0.3.md`(M5 = §5 FR-121系, §8 FR-430系, §9 FR-600系, §11 NFR, §12-5 較正ベンチ,
  §13 M5 行, §15 課題確定状況)

### 参考(M1〜M4 の同種成果物)
- `docs/spec/{m1-hypothesis-search,m2-sequential,m3-operando,m4-joint-mcp}/{note,requirements,user-stories,acceptance-criteria,prep,interview-record}.md`

### 関連実装(M5 の土台となる M0〜M4 資産・実 API 確認済み)
- `src/tsumugin/evidence/{base,ic,ranking}.py`(**laplace/nested/階層裁定/較正の主対象**)
- `src/tsumugin/joint/{model,verification}.py`(**MEM 入力元**)
- `src/tsumugin/mcp/{tools,mem}.py`(**run_mem 実体化の境界**)
- `src/tsumugin/errors.py`(**MEMUnavailableError 定義済・nested/oed 例外を足す**)
- `src/tsumugin/selection/engine.py`(final_selection_mode の human モード整合)
- `src/tsumugin/store/{ledger,snapshot,persistent,serialization}.py`(**MEM 子スナップショット追記・非破壊**)
- `src/tsumugin/{backends/base,search/tree}.py`(bic 探索・param 命名)

---

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
設計文書(`docs/design/m5-nested-mem-oed/*`)・M5 タスク分割は本ノートの後工程で生成されます。
