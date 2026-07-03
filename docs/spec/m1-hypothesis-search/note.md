# m1-hypothesis-search 開発コンテキストノート

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

**本ノートの対象マイルストーン = M1**:
> 多仮説木探索 (FR-110〜117) + Evidence Engine (bic 一次評価: FR-121 / FR-122) +
> .gpx 書き出し (FR-505) + Web UI 最小版

**参照元**: `README.md`, `CLAUDE.md`, `docs/tsumugin_spec_v0.3.md`(仕様の正)

## 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12
- **フレームワーク/ライブラリ**: numpy >= 1.26(コア)。GSAS-II は optional extra `gsas`(scipy / pycifrw / requests)
- **ランタイム**: CPython 3.12。Rietveld バックエンドは GSAS-II 2.0(`from GSASII import GSASIIscriptable`)
- **パッケージマネージャー**: uv 0.9.x(src layout + hatchling ビルド)
- **Web UI(M1 新規)**: 未選定 — 実装時に確定する(推奨: 軽量な Python 発オプション。仕様§10 FR-500 の HTML レポート出力と親和性を優先)

### アーキテクチャパターン
- **アーキテクチャスタイル**: レイヤ分離(Interfaces / Agent / Orchestrator / Workers / Data、仕様§3)。
  境界はすべて `typing.Protocol` で抽象化しバックエンド交換可能(設計原則 P7)
- **設計パターン**: frozen dataclass による不変値オブジェクト + `with_updates()` / `replace()` による非破壊更新。
  全状態遷移は追記専用 Ledger(ハッシュチェーン)+ Snapshot(revert 可能)に記録(P2)
- **ディレクトリ構造**:
  ```
  src/tsumugin/
  ├── model/       # Project/Dataset/Frame/HistogramRef/Hypothesis/PhaseInstance/LatticeParams/RefinementMetrics
  ├── backends/    # RefinementBackend(Protocol) + SimulatedBackend + GSASIIBackend
  ├── refinement/  # StagedRefinementEngine(FR-200) + guardrails(FR-210)
  ├── evidence/    # EvidenceBackend(Protocol) + BICBackend/AICBackend + ranking
  ├── store/       # Ledger(追記専用) + SnapshotStore(非破壊 revert)
  └── pipeline.py  # analyze_single_pattern(単一パターン自動多相精密化)
  tests/           # 実装ファイルと 1:1、GSAS-II 依存は @pytest.mark.gsas
  docs/dev/plans/  # dev/kairo 実装計画・タスク・レポート
  docs/spec/       # kairo 要件・設計・タスク(本ノートを含む)
  ```

**参照元**: `CLAUDE.md`(アーキテクチャ表), `docs/dev/context.md`, `docs/tsumugin_spec_v0.3.md`§3

## 開発ルール

### プロジェクト固有のルール(必須・違反禁止)
- **TDD 厳守**: Red(失敗テスト)→ Green(最小実装)→ Refactor。テストなしの実装コミット禁止
- **タスク毎コミット**: kairo/dev のタスク 1 件完了(テスト green)ごとに 1 コミット
- **ブランチ運用**: マイルストーン毎にブランチ。現在 `milestone/m1-hypothesis-search`。
  完了時に PR → `/pr-review-cycle`(HIGH 以上の指摘ゼロまで)→ マージはユーザー判断
- **モデル指定**: kairo/dev の全エージェント(サブエージェント含む)を Opus で実行する
- **成果物の保存先**: 要件定義・設計・タスク分割は `docs/` 配下

### コーディング規約
- **命名規則**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE
- **型チェック**: 型注釈必須(`any` 回避)。境界は `typing.Protocol`(`@runtime_checkable`)
- **コメント/docstring**: 日本語 docstring 可。FR/NFR 番号を docstring に紐づける慣習
- **フォーマット/Lint**: `uvx ruff check src tests`(line-length 100, target py312)
- **データモデリング**: frozen dataclass 基本。更新は新インスタンス生成 + Snapshot 追記のみ

### テスト要件
- **テストフレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`
- **テストコマンド**: `uv run pytest`(既定)/ `uv run pytest --cov=tsumugin`
- **カバレッジ**: M0 実績 95%(明示の最低値規定はないが高水準を維持)
- **マーカー**: `gsas`(GSAS-II 導入環境でのみ実行、未導入は自動 skip)。`uv run pytest -m gsas`
- **テストパターン**: 実装ファイルと 1:1 対応の `tests/test_*.py`。現状 70 passed

**参照元**: `CLAUDE.md`(開発ワークフロー/規約/不変条件), `docs/dev/context.md`, `pyproject.toml`
(注: `AGENTS.md`, `docs/rule/`, `docs/rule/kairo/` はいずれも未作成)

## 既存の要件定義

### 要件定義書
M1 専用の要件定義書(`docs/spec/m1-hypothesis-search-*.md`)は**未作成**(本ノートの後工程 kairo-requirements で作成する)。
正の要件は `docs/tsumugin_spec_v0.3.md` の FR/NFR 番号。M1 スコープに対応する主要 FR を以下に抜粋する。

**参照元**: `docs/tsumugin_spec_v0.3.md`§5〜§13(requirements/user-stories/acceptance-criteria は未生成)

### 主要な機能要件(M1 スコープ、仕様 FR 番号)
- **FR-110 単一パターン多仮説木探索**
  - FR-111: ノード = 相組合せの探索木。ピークマッチングスコアによる事前枝刈り
  - FR-112: 枝刈り閾値はスコア累積分布の変曲点で動的決定
  - FR-113: 各ノードで保守的設定の制約付き精密化(探索モード)
  - FR-114: 等構造相の Jaccard クラスタリング。FoM = 1/((1−fit)+ΔU) で代表選出、他相は代替解として保持
  - FR-115: R 改善閾値(既定 2%)による枝打ち切り。最大相数既定 5
  - FR-116: Jenks natural breaks による良好解クラスタ抽出 + 組成クラスタリング
  - FR-117: 未マッチ/extra ピークの構造化出力(未知相フラグ)
- **FR-120 Evidence Engine(M1 は bic 一次評価まで)**
  - FR-121: `bic`(既定)/ `aic` を残差から即時計算。木探索内ノード評価に使用(M0 で実装済み)
  - FR-122: **階層的裁定の 1 段目** — 木探索・枝刈りは `bic`、僅差競合(既定 ΔBIC < 10)を検出。
    `nested` 再裁定は M5(M1 では close_competitor フラグの提示まで)
  - FR-124: 仮説確率は softmax + 温度較正で出力(M0 で実装済み)
- **FR-505 .gpx 引き渡し保証**: 任意時点の状態を GSAS-II GUI で開ける `.gpx` として書き出し(M1 新規)
- **Web UI 最小版**: 仮説一覧・ランキング・evidence/確率・fit/残差の閲覧(仕様§10 FR-421〜424 の縮小版)

### 主要な非機能要件
- **NFR-101 / P2**: 破壊的操作の API 非実装。全出力追記型(削除・上書き API を作らない)
- **NFR-102**: 再現性 — 乱数種固定でビット同一。GSAS-II はノイズ付き Yobs でなく Ycalc を使う等
- **NFR-105**: ledger 追記専用 + ハッシュチェーン(`verify()` が常に True)
- **NFR-103**(参考・M1 では努力目標): 単一パターン(候補 300 相)中央値 ≤ 3 分(32 コア, bic 時)
- **NFR-106**: GSAS-II バージョン固定 + contract test
- **NFR-107**: σの由来(共分散/逐次相関/マルチスタート分散)をレポートに明示

## 既存の設計文書

### アーキテクチャ設計
`docs/design/` は未作成。設計の実体は M0 実装(`src/tsumugin/`)と `docs/dev/plans/m0-refinement-core/plan.md`。
M1 は M0 の 3 つの抽象境界(`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore`)を
共有インターフェースとして再利用する。

**参照元**: `docs/dev/plans/m0-refinement-core/plan.md`, `README.md`(アーキテクチャ表)

### データフロー(M0 実装済み: 単一パターン自動多相精密化)
```
Project(observed data + 初期 PhaseInstance 群)
  └─> StagedRefinementEngine
        stage ごと: SnapshotStore.save → Backend.refine → check_guards
                    → (違反なら revert+原因固定+retry / 3回で escalate、処理はブロックせず次段)
                    → Ledger.append(理由付き)
        └─> RefinementReport(final_phases, metrics 付き)
  └─> EvidenceEngine.score → rank([Hypothesis...]) → softmax 確率 + 僅差競合(close_competitor)フラグ
```
M1 追加: 上記の単一 `analyze_single_pattern` の前段に **Hypothesis Manager(木探索)** を挿入し、
候補相組合せを固定リストでなく探索木から動的に生成・枝刈りする。木のノード評価に既存 bic を使う。

**参照元**: `src/tsumugin/pipeline.py`, `docs/dev/plans/m0-refinement-core/plan.md`

### 型/インターフェース定義(TypeScript ではなく Python Protocol / dataclass)
M1 が依存・拡張する M0 の主要インターフェース:

- `RefinementBackend`(Protocol, `backends/base.py`): `name: str`, `refine(model: RefinementModel, *, max_cycles=20) -> RefinementResult`
  - `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)`。
    free_params は `"phase{i}.{suffix}"` 形式(`param_name` / `parse_param` ヘルパあり)
  - `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params)`
- `EvidenceBackend`(Protocol, `evidence/base.py`): `score(metrics: RefinementMetrics) -> EvidenceResult(backend, value, logz_err=None)`
  - `BICBackend`: value = chi2 + n_params·ln(n_obs);  `AICBackend`: value = chi2 + 2·n_params(小さいほど良い)
- `rank(hypotheses, backend, *, temperature=1.0, close_threshold=10.0) -> tuple[RankedHypothesis, ...]`
  - `RankedHypothesis(hypothesis, evidence, probability, close_competitor)`。probability = softmax(-value/2T)
- モデル(`model/`, すべて frozen dataclass):
  - `Hypothesis(id, phases, parent_id=None, metrics=None, status, accepted_by=None)` —
    `status: candidate|refined|accepted|rejected|superseded`。**`parent_id` は木探索の分岐用に既に用意済み**
  - `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence: Mapping[str,float])`
  - `PhaseInstance(phase_ref, lattice: LatticeParams, scale, wt_frac=None, occupancies)` + `with_updates(**changes)`
  - `LatticeParams(a,b,c,alpha=90,beta=90,gamma=90,sigma)` + `volume()`
  - `Project(id, datasets, final_selection_mode: agent|human)` / `Dataset` / `Frame` / `HistogramRef(probe, ...)`
- ストア(`store/`):
  - `Ledger`: `append(kind, payload) -> LedgerEntry` / `entries` / `verify() -> bool`。削除・改変 API なし
  - `SnapshotStore(ledger=None)`: `save(phases, *, label) -> Snapshot` / `load(id)` / `revert(id) -> phases` / `current_id`

**参照元**: `src/tsumugin/backends/base.py`, `evidence/base.py`, `evidence/ic.py`, `evidence/ranking.py`,
`model/hypothesis.py`, `model/phase.py`, `model/project.py`, `store/ledger.py`, `store/snapshot.py`

### データベース設計
DB スキーマ(SQLite/HDF5)は未実装。仕様§3 の Data Layer(Project Store = HDF5+SQLite)は M2 以降。
M1 はインメモリの Ledger/Snapshot を継続使用(永続化は範囲外)。

### API 仕様
REST / MCP は M2+ / M4(仕様 FR-512 / FR-513)。M1 の外部境界は Python API(`tsumugin.analyze_single_pattern` 等の
`src/tsumugin/__init__.py` 公開シンボル)+ 最小 Web UI + `.gpx` 書き出し(FR-505)。

## 関連実装

### 類似機能の実装例(M1 が土台にする M0 資産)
- **単一パターンのオーケストレーション** — `src/tsumugin/pipeline.py::analyze_single_pattern`
  (候補ごとに段階精密化 → evidence → rank。木探索版はこの構造を踏襲)
- **段階解放 + ガード + revert のループ** — `src/tsumugin/refinement/staged.py::StagedRefinementEngine.run`
  (探索モード精密化 FR-113 のベース。DEFAULT_STAGE_TEMPLATE で段階定義)
- **ノード評価と僅差検出** — `src/tsumugin/evidence/ranking.py::rank`(FR-122 の close_competitor 既に実装)
- **GSAS-II 実バックエンド** — `src/tsumugin/backends/gsasii.py`(scale=HAP 相分率 / lattice.*=Cell を refine、
  noise-free Ycalc を simulate。profile 以降は M2+)

**参照元**:
- `src/tsumugin/pipeline.py`
- `src/tsumugin/refinement/staged.py`
- `src/tsumugin/evidence/ranking.py`
- `src/tsumugin/backends/gsasii.py`, `src/tsumugin/backends/simulated.py`

### 参考パターン
- ガードは純粋関数 `check_guards(prev, cur, config) -> tuple[GuardViolation,...]`。例外を投げず結果で返し、
  ledger 記録/revert 判断は呼び出し側。**「失敗は例外でなく chi2=inf の結果に変換」の原則**を M1 の木探索でも踏襲
- 段階エンジンは escalate してもブロックせず次段へ進む(FR-403 の非ブロッキング設計)
- 決定論的順序(ガード kind 順、canonical JSON ソート)で再現性(NFR-102)を担保

### 共通モジュール・ユーティリティ
- `backends/base.py::param_name(i, key)` / `parse_param(name)` — 相インデックス⇔パラメータ名の正準変換
- `store/ledger.py::_canonical_json` / `_compute_hash` — 決定論的ハッシュチェーン
- `refinement/guardrails.py::GuardConfig` — 発散/負占有率/格子暴走/負 ADP/相分率ゼロ張り付きの閾値
- 公開 API は `src/tsumugin/__init__.py` の `__all__` に集約(M1 追加シンボルもここに公開)

### 依存関係・インポートパス
- 公開 import 例(README M0 使用例):
  `from tsumugin import PhaseInstance, LatticeParams, SimulatedBackend, analyze_single_pattern`
- GSAS-II: `from GSASII import GSASIIscriptable`(パッケージ形式)。ソースツリー `C:\Users\tomoo\G2` +
  venv の `gsas2-source.pth` + バイナリ `~/.GSASII/GSASII-bin/win_64_p3.12_n2.2`
- 依存導入は `uv sync --extra gsas`(**プレーン `uv sync` は gsas extra が外れるので禁止**)

## 技術的制約

### パフォーマンス制約
- 木探索は探索モード精密化(保守的・低コスト)で回し、ノード評価は `bic`(即時計算)に限定。
  高コストな nested は M1 非対象(仕様 FR-122 の 2 段目は M5)
- 参考目標 NFR-103: 単一パターン(候補 300 相)中央値 ≤ 3 分(32 コア)。M1 は正答性優先、並列化(Ray)は M3

### セキュリティ制約(= 非破壊性制約)
- **P2 / NFR-101**: 破壊的操作(生データ削除・上書き・履歴改変)の API をシステムに実装しない。
  Ledger/Snapshot に削除・上書きメソッドを追加してはならない。全状態変更は追記 + revert
- **NFR-105**: ledger は追記専用 + ハッシュチェーン。`verify()` が常に True であること

### 互換性制約
- Python >= 3.12 固定。GSAS-II はバージョン固定 + contract test(NFR-106)。`.gpx`(FR-505)は
  GSAS-II GUI で開ける形式を保証する必要がある(GSASIIscriptable のプロジェクト保存 API に準拠)

### データ制約
- chi2/rwp のセマンティクスはバックエンド間で統一(BIC 比較の一貫性)。
  精密化バックエンドの失敗は例外でなく chi2=inf の結果に変換し、ガードレールに処理させる
- **Dara 教訓**: ChemPlausibility スコアは降格のみ、候補除外はしない(evidence ランキングへの反映のみ)

**参照元**: `CLAUDE.md`(実装上の不変条件), `docs/tsumugin_spec_v0.3.md`§11, §14

## 注意事項

### 開発時の注意点
- 木探索(FR-110)は M0 の `analyze_single_pattern`(固定候補リスト)を置換せず**その前段**に位置づける。
  Hypothesis の `parent_id` フィールドが分岐用に既に用意されている点を活用する
- ピークマッチング(FR-111/112/117)は M0 に未実装 — 新規モジュール(例: `tsumugin.peakmatch`)が必要。
  `SimulatedBackend.simulate` / `GSASIIBackend.simulate`(Ycalc)が参照パターン生成に利用可能
- FoM = 1/((1−fit)+ΔU)、Jaccard クラスタリング(FR-114)、Jenks natural breaks(FR-116)、
  変曲点による動的閾値(FR-112)は新規アルゴリズム実装。乱数を使う場合は種固定で NFR-102 を守る
- `.gpx` 書き出し(FR-505)は GSAS-II 依存 — `@pytest.mark.gsas` でマークし未導入環境は skip 可能に

### デプロイ・運用時の注意点
- GSAS-II 起動時の `~/.GSASII/config.ini` 読込警告(cp932)は無害(upstream 表示バグ)
- Web UI 最小版は M1 新規スタック。実装時に選定し、`docs/dev/context.md` の Tech Stack を更新すること

### セキュリティ/非破壊上の注意点
- 新規に永続化やストア機能を足す場合も、削除・上書き API を作らない(P2 の構造的保証)
- ガード発動・仮説降格・枝刈りはすべて理由付きで ledger 記録(FR-214 / FR-424 遡及リンク)

### パフォーマンス上の注意点
- 木探索の枝刈りはコスト削減の要 — 事前ピークマッチング枝刈り(FR-111)で精密化回数を抑える
- 探索は `bic`(即時)で回し、重い評価は生存仮説の最終精密化に限定

## Git情報

### 現在のブランチ
`milestone/m1-hypothesis-search`(clean、`main` から分岐)

### 最近のコミット
```
e02275e M0 (PoC): 単一パターン自動多相精密化の中核を実装
99c510d 達成条件追記
b49ef59 Initialized
```

### 開発状況
M0 完了 + GSASIIBackend 実体化(M1 先行分)。70 tests passed / カバレッジ 95%。
M1 ブランチを切った直後で、これから kairo-requirements → kairo-design → kairo-tasks → kairo-implement を回す。

## 収集したファイル一覧

### プロジェクト基本情報
- `CLAUDE.md`
- `README.md`
- `docs/dev/context.md`
- `pyproject.toml`
- (`AGENTS.md` は不在)

### 追加ルール
- (`docs/rule/`, `docs/rule/kairo/` は不在 — 追加ルールは CLAUDE.md に集約)

### 仕様書(正)
- `docs/tsumugin_spec_v0.3.md`(FR/NFR の正。M1 = §5 FR-110〜124, §10 FR-505, §13 M1 行)

### 既存実装計画
- `docs/dev/plans/m0-refinement-core/plan.md`
- `docs/dev/plans/m0-refinement-core/tasks/001〜011-*.md`
- `docs/dev/plans/m0-refinement-core/reports/verification.md`

### 関連実装(M1 の土台となる M0 資産)
- `src/tsumugin/__init__.py`(公開 API)
- `src/tsumugin/pipeline.py`
- `src/tsumugin/model/{project,phase,hypothesis}.py`
- `src/tsumugin/backends/{base,simulated,gsasii}.py`
- `src/tsumugin/refinement/{staged,guardrails}.py`
- `src/tsumugin/evidence/{base,ic,ranking}.py`
- `src/tsumugin/store/{ledger,snapshot}.py`

---

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
設計文書(`docs/design/*`)・M1 要件定義(`docs/spec/m1-hypothesis-search-*.md`)は本ノートの後工程で生成されます。
