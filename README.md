# Tsumugin

多仮説・全自動 Rietveld 解析プラットフォーム。粉末回折(X線・中性子)の相同定・
多相 Rietveld 精密化・時系列解析を、AI エージェントと人間の介入点を明示的に設計した上で
自動化することを目指す。設計思想は [docs/tsumugin_spec_v0.3.md](docs/tsumugin_spec_v0.3.md) を参照。

> **状態**: M0 (PoC) + M1 (多仮説木探索) 実装済み。単一パターン自動多相精密化の中核
> (段階的パラメータ解放・ガードレール・Evidence Engine・追記専用 Ledger/Snapshot) に加え、
> 候補相集合からの多仮説木探索 (`tsumugin.search`)・`.gpx` 書き出し (`tsumugin.export`)・
> read-only Web UI (`tsumugin.webui`) が、`SimulatedBackend` (GSAS-II 不要) と
> `GSASIIBackend` (実 Rietveld) の両方で動作する。

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

## アーキテクチャ (M0 + M1 実装済み範囲)

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

実装計画は [docs/dev/plans/m0-refinement-core/](docs/dev/plans/m0-refinement-core/) を参照。
