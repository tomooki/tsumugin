# Tsumugin

多仮説・全自動 Rietveld 解析プラットフォーム。粉末回折(X線・中性子)の相同定・
多相 Rietveld 精密化・時系列解析を、AI エージェントと人間の介入点を明示的に設計した上で
自動化することを目指す。設計思想は [docs/tsumugin_spec_v0.3.md](docs/tsumugin_spec_v0.3.md) を参照。

> **状態**: M0 (PoC) + M1 (多仮説木探索) + M2 (シーケンシャル解析) 実装済み。単一パターン
> 自動多相精密化の中核 (段階的パラメータ解放・ガードレール・Evidence Engine・追記専用
> Ledger/Snapshot)、候補相集合からの多仮説木探索 (`tsumugin.search`)・`.gpx` 書き出し
> (`tsumugin.export`)・read-only Web UI (`tsumugin.webui`) に加え、時系列フレーム列の逐次
> 精密化 (`tsumugin.sequential`: changepoint 検出・lifecycle・転移温度・trajectory/CSV)・
> agent/human 2 モードの最終選択 (`tsumugin.selection`)・JSONL 永続化
> (`tsumugin.store` の `PersistentLedger`/`PersistentSnapshotStore`) が、`SimulatedBackend`
> (GSAS-II 不要) と `GSASIIBackend` (実 Rietveld) の両方で動作する。

## セットアップ

```bash
uv sync          # 依存 (numpy) と dev グループ (pytest) を導入
uv run pytest    # 全テスト実行 (GSAS-II 未導入なら gsas テストは自動 skip)
```

### GSAS-II バックエンドの導入 (任意)

GSAS-II は PyPI 非公開で、Windows では pip ビルドが非推奨 (Fortran コンパイラ必要) のため、
ソースツリー + ビルド済みバイナリ方式で導入する:

```bash
# 1. ソースを取得
git clone --depth 1 https://github.com/AdvancedPhotonSource/GSAS-II.git ~/G2

# 2. ランタイム依存 (scipy, pycifrw, requests) を導入
uv sync --extra gsas

# 3. venv からソースツリーを import 可能にする (.pth)
#    <venv>/Lib/site-packages/gsas2-source.pth に ~/G2 の絶対パスを 1 行書く

# 4. コンパイル済みバイナリを ~/.GSASII/GSASII-bin に取得
uv run python -c "import os; from GSASII import GSASIIpath as p; p.InstallGitBinary(p.getGitBinaryLoc(), os.path.expanduser('~/.GSASII/GSASII-bin'), nameByVersion=True)"

# 5. 検証 (contract tests が実行される)
uv run pytest -m gsas
```

### Web UI (M1 最小版, 任意)

仮説一覧・ランキング閲覧用の read-only Web UI (FastAPI + uvicorn) は optional extra `web` で導入する:

```bash
uv sync --extra gsas --extra web   # gsas を必ず併用 (プレーン uv sync は gsas 依存が外れる)
```

> **注意**: Web UI に認証はない。既定の `127.0.0.1` バインドのままローカル閲覧専用で使うこと。
> `serve(host="0.0.0.0")` 等に変更すると解析データ全量が同一ネットワークへ無認証で公開される。

## 使い方 (M0)

```python
import numpy as np
from tsumugin import PhaseInstance, LatticeParams, SimulatedBackend, analyze_single_pattern

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 80.0, 0.02)

# 観測パターン (ここでは合成データを生成)
truth = (PhaseInstance("PhaseA", LatticeParams(5.0, 5.0, 5.0), scale=2.0),)
intensity = backend.simulate(truth, two_theta)

# 2 つの候補相組合せをランキング
candidates = [
    (PhaseInstance("PhaseA", LatticeParams(5.02, 5.0, 5.0), scale=1.0),),  # 正しい構造
    (PhaseInstance("PhaseX", LatticeParams(6.0, 6.0, 6.0), scale=1.0),),   # 誤った構造
]
result = analyze_single_pattern(two_theta, intensity, candidates, backend=backend)

for r in result.ranked:
    print(f"{r.hypothesis.id}: P={r.probability:.3f} "
          f"evidence({r.evidence.backend})={r.evidence.value:.2f} "
          f"Rwp={r.hypothesis.metrics.rwp:.3f}")

# 全過程は追記専用 Ledger に記録され、検証・revert 可能 (非破壊性 P2)
assert result.ledger.verify()
```

## 使い方 (M1): 多仮説木探索

候補相の集合から best-first 木探索で複数仮説を展開・精密化し、Evidence (BIC) で
ランキングした結果を JSON 化可能な summary として取り出す:

```python
import numpy as np
from tsumugin import HypothesisTreeSearch, SimulatedBackend, PhaseInstance, LatticeParams

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 60.0, 0.02)

# 既知の 2 相 (立方 A/B) を重ねた合成観測パターン
candidates = [
    PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0)),
    PhaseInstance(phase_ref="B", lattice=LatticeParams(6.0, 6.0, 6.0)),
]
intensity = backend.simulate(candidates, two_theta)

# 多仮説木探索 → ランキング → summary (/api/result 準拠の純 dict, json.dumps 可)
result = HypothesisTreeSearch(backend).search(two_theta, intensity, candidates)
summary = result.to_summary()

best = summary["ranked"][0]
print("best phases:", sorted(p["phase_ref"] for p in best["phases"]))  # -> ['A', 'B']
assert result.ledger.verify()  # 全操作は追記専用 Ledger に記録 (非破壊性 P2)
```

`export_gpx(path, phases, two_theta, intensity)` で任意時点の相集合を GSAS-II GUI で
再オープン可能な `.gpx` へ書き出せる (GSAS-II 導入時)。

## 使い方 (M2): シーケンシャル解析

昇温などで時間発展する回折フレーム列を `FrameSeries` にまとめ、`SequentialEngine` で逐次
精密化する。frame0 は staged 精密化で確立、以降は直近成功フレームからの warm start + direct
refine で軽量に処理し、`detect_changepoint` (複合指標ロバスト z) が発火したフレームでのみ
局所木探索を起動して新相を採択する。lifecycle・転移温度・CSV まで一気通貫で得られる:

```python
import numpy as np
from tsumugin import (
    SequentialEngine, FrameSeries, ExternalChannel,
    SimulatedBackend, PhaseInstance, LatticeParams,
)

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 60.0, 0.02)

# 昇温で格子が膨張しつつ frame 8 以降で新相 B が出現する合成フレーム列を組む
rows, temps = [], []
for i in range(12):
    a = 5.0 + 0.01 * i  # 熱膨張する主相 A の格子定数
    phases = [PhaseInstance("A", LatticeParams(a, a, a))]
    if i >= 8:
        phases.append(PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0)))  # 転移で新相 B
    rows.append(backend.simulate(phases, two_theta))
    temps.append(300.0 + 5.0 * i)
series = FrameSeries(
    two_theta, np.asarray(rows, dtype=float),
    axis_values=tuple(temps), axis_kind="temperature",
    channels=(ExternalChannel("temperature", {i: t for i, t in enumerate(temps)}),),
)

# 逐次精密化 → changepoint 発火時のみ局所探索で新相 B を採択 → trajectory 組立
engine = SequentialEngine(backend, candidates=[PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0))])
result = engine.run(series, [PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0))])

result.trajectory.to_csv("traj.csv")                       # 相分率・格子・Rwp の時系列を CSV 出力
print("phases seen:", sorted(result.trajectory.lifecycles))  # -> ['A', 'B']
assert result.ledger.verify()                              # 全操作は追記専用 Ledger に記録 (P2)
```

`PersistentLedger(path)` / `PersistentSnapshotStore(path, ledger=...)` を注入すると全操作が
JSONL に追記され、別プロセスで再オープンしても `verify()` でハッシュチェーンの改竄を検知できる。
`estimate_transition(temperatures, fractions, phase_ref="B")` で相分率シグモイドから転移温度
(onset/midpoint) を推定でき、`FinalSelectionEngine(mode="agent")` で局所探索結果に自動裁定
(または Review Queue へのエスカレーション) を適用できる。

## アーキテクチャ (M0 + M1 + M2 実装済み範囲)

| モジュール | 役割 | 主な仕様 FR |
|-----------|------|------------|
| `tsumugin.model` | Project/Dataset/Frame/Hypothesis/PhaseInstance | §4 |
| `tsumugin.backends` | RefinementBackend 抽象 + Simulated + GSASII(薄いラッパ) | P7, §3.1 |
| `tsumugin.refinement` | 段階的パラメータ解放 + ガードレール | FR-200, FR-210 |
| `tsumugin.evidence` | Evidence Engine (bic/aic + softmax 確率) | FR-120 |
| `tsumugin.store` | 追記専用 Ledger + Snapshot (非破壊・revert) | P2, NFR-101/105 |
| `tsumugin.pipeline` | 単一パターン自動多相精密化 | M0 |
| `tsumugin.search` | ピーク検出→マッチ→クラスタリング→枝刈り→多仮説木探索 | FR-110〜117 |
| `tsumugin.export` | 相集合 + 観測を再オープン可能な `.gpx` へ書き出し | FR-505 |
| `tsumugin.webui` | 仮説一覧・ランキング閲覧の read-only Web UI (optional `web`) | FR-421〜424 |
| `tsumugin.sequential` | フレーム列逐次精密化 + changepoint + lifecycle + 転移温度 + trajectory/CSV | REQ-001〜008 |
| `tsumugin.selection` | 最終選択エンジン (agent/human 2 モード) + エスカレーション + Review Queue | REQ-013〜015 |
| `tsumugin.store` (persistent) | JSONL 永続化 Ledger / Snapshot (追記専用・再オープン改竄検知) | REQ-010〜012, NFR-105 |

実装計画は [docs/dev/plans/m0-refinement-core/](docs/dev/plans/m0-refinement-core/) を参照。
