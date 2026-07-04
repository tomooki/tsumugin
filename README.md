# Tsumugin

多仮説・全自動 Rietveld 解析プラットフォーム。粉末回折(X線・中性子)の相同定・
多相 Rietveld 精密化・時系列解析を、AI エージェントと人間の介入点を明示的に設計した上で
自動化することを目指す。設計思想は [docs/tsumugin_spec_v0.3.md](docs/tsumugin_spec_v0.3.md) を参照。

> **状態**: M0 (PoC) + M1 (多仮説木探索) + M2 (シーケンシャル解析) + M3 (operando 解析)
> + M4 (中性子 joint / ChemPlausibility / MCP) + M5 (nested 裁定 / MEM / OED) 実装済み。
> 単一パターン自動多相精密化の中核 (段階的パラメータ解放・ガードレール・Evidence Engine・追記専用
> Ledger/Snapshot)、候補相集合からの多仮説木探索 (`tsumugin.search`)・`.gpx` 書き出し
> (`tsumugin.export`)・read-only Web UI (`tsumugin.webui`) に加え、時系列フレーム列の逐次
> 精密化 (`tsumugin.sequential`: changepoint 検出・lifecycle・転移温度・trajectory/CSV)・
> agent/human 2 モードの最終選択 (`tsumugin.selection`)・JSONL 永続化
> (`tsumugin.store` の `PersistentLedger`/`PersistentSnapshotStore`) が、`SimulatedBackend`
> (GSAS-II 不要) と `GSASIIBackend` (実 Rietveld) の両方で動作する。M3 では電池 operando 向けに
> echem 同期 (`tsumugin.operando`)・マルチスタート大域最適化 (`tsumugin.multistart`)・
> 固溶体/二相判別・IC 区間分割・セル固定相/吸収補正 (`tsumugin.absorption`) を追加した。M4 では
> X 線 + 中性子のマルチヒストグラム joint 検証精密化 (`tsumugin.joint`)・化学的妥当性による
> 降格 (`tsumugin.chem`, 候補除外はしない)・AI エージェント連携用の MCP サーバ (`tsumugin.mcp`,
> SDK 非依存の 8 ツール実処理層 + 遅延 import アダプタ) を追加した。M5 では僅差競合のみを nested
> sampling で再裁定する 2 段構え裁定 + 確率較正 (`tsumugin.nested`)・MEM (最大エントロピー法) 密度
> 解析と MEM-Rietveld 反復 (`tsumugin.mem`)・僅差競合の判別測定を情報利得順に提案する最適実験計画
> (`tsumugin.oed`, 非破壊・提案のみ) を追加した。nested/MEM/OED の実バックエンド (dynesty /
> Dysnomia / pyboed) は遅延 import に隔離され、コア import は numpy のみを維持する。

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

## 使い方 (M3): operando 解析

電池 operando 測定の一気通貫。充放電 (echem) CSV を frame 同期して組成 x へ換算し
(`read_echem_csv`)、セル集電体などのプリセット固定相 (`CELL_PHASE_PRESETS`) を scale のみ解放で
常駐させたまま逐次精密化し、Evidence (BIC) の区間分割 (`segment_series`) で反応区間へ切り分け、
各区間を端点マルチスタート込みで固溶体 / 二相反応に判別 (`discriminate_interval`) する。最後に
相分率・格子の trajectory と echem (V/組成 x) を frame_index で外部結合した CSV を書き出す
(`combined_csv`)。全操作は 1 本の共有 Ledger に集約され `verify()` できる:

```python
import numpy as np
from tsumugin import (
    SimulatedBackend, PhaseInstance, LatticeParams, FrameSeries, Ledger,
    SequentialEngine, CELL_PHASE_PRESETS, DiscriminationConfig, MultistartConfig,
    segment_series, discriminate_interval, read_echem_csv, combined_csv,
)

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 60.0, 0.05)
n_frames = 6

# 端成分 α/β の scale を漸移させた二相反応系列に Al 集電体 (固定相) を重畳
al = CELL_PHASE_PRESETS["Al"].phase.with_updates(scale=0.7)
rows = []
for i in range(n_frames):
    t = i / (n_frames - 1)
    phases = []
    if 1.0 - t > 0.0:
        phases.append(PhaseInstance("alpha", LatticeParams(5.0, 5.0, 5.0), scale=1.0 - t))
    if t > 0.0:
        phases.append(PhaseInstance("beta", LatticeParams(5.06, 5.06, 5.06), scale=t))
    phases.append(al)
    rows.append(backend.simulate(phases, two_theta))
series = FrameSeries(two_theta, np.asarray(rows, dtype=float))

fixed = CELL_PHASE_PRESETS["Al"]                       # セル固定相 (scale のみ解放)
initial = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
ledger = Ledger()                                      # segment/discriminate を 1 本のチェーンへ集約

# 固定相込み IC 区間分割 → 区間ごとに固溶体/二相を判別 (端点マルチスタート)
seg = segment_series(backend, series, initial, fixed_phases=(fixed,), ledger=ledger)
disc = discriminate_interval(
    backend, series, (0, n_frames - 1), initial,
    config=DiscriminationConfig(multistart=MultistartConfig(n_starts=2)),
    fixed_phases=(fixed,), ledger=ledger,
)
print("segments:", seg.n_segments, "/ verdict:", disc.verdict)  # verdict ∈ {solid_solution, two_phase, undecided}

# echem CSV を frame 同期 (容量 Q → 組成 x = 0.1·Q) して trajectory と結合出力
echem = read_echem_csv(
    "echem.csv",
    column_map={"frame": "frame", "voltage": "voltage", "capacity": "capacity"},
    capacity_to_x=(0.1, 0.0),
)
trajectory = SequentialEngine(backend).run(series, [initial[0], al]).trajectory
written = combined_csv(trajectory, echem, "combined.csv")  # wt_frac/格子 + V/組成 x を frame で外部結合
assert ledger.verify()                                     # 全操作は追記専用 Ledger に記録 (P2/NFR-105)
```

判別が僅差または両仮説とも高 R のときは自動確定せず `verdict="undecided"` で
`ReviewQueue` へエスカレーションする (誤自動確定の回避)。`MultistartEngine(backend,
config=MultistartConfig(n_starts=N)).run(...)` は摂動 start を direct refine → 発散除外 →
basin クラスタで大域最適を裏取りし、`AbsorptionConfig` / `transmission_factor` は透過配置の
吸収補正 (A = exp(-μt/cosθ)) を与える。

## 使い方 (M4): 中性子 joint / ChemPlausibility / MCP

プライマリ探索 (`HypothesisTreeSearch`) は不変のまま、その生存仮説 (良好解) のみを X 線 +
中性子の複数ヒストグラムで joint 検証精密化する (`verify_survivors`)。探索段そのものは joint 化
しない (再実行しない)。続けて化学的妥当性 (`ChemPlausibility`, v1 は大気下の単体アルカリ金属を
降格する `AlkaliMetalInAirRule`) で確率を **降格** する — スコアは降格のみに使い、低スコアでも
候補を除外・削除はしない (`rank_with_plausibility`, Dara 教訓)。全操作は 1 本の Ledger に集約:

```python
import numpy as np
from tsumugin import (
    SimulatedBackend, PhaseInstance, LatticeParams, Ledger,
    HypothesisTreeSearch, JointHistogram, verify_survivors,
    BICBackend, AlkaliMetalInAirRule, SynthesisContext, rank_with_plausibility,
)
from tsumugin.search.clustering import PhaseCandidate

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 60.0, 0.05)
true_phase = PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0))
observed = backend.simulate((true_phase,), two_theta)

# プライマリ探索 (探索段は不変) → 生存仮説を得る
ledger = Ledger()
search = HypothesisTreeSearch(backend, ledger=ledger)
result = search.search(two_theta, observed, [
    PhaseCandidate(phase=true_phase),
    PhaseCandidate(phase=PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0))),
])

# 生存仮説を X 線 + 中性子の 2 ヒストで joint 検証 (マルチヒストグラム)
histograms = (
    JointHistogram(two_theta=two_theta, intensity=observed, probe="xray"),
    JointHistogram(two_theta=two_theta, intensity=observed, probe="neutron_cw"),
)
verification = verify_survivors(backend, result, histograms, evidence=BICBackend(), ledger=ledger)

# ChemPlausibility で化学的に非妥当な相を降格 (除外はしない・件数不変)
ranked = rank_with_plausibility(
    verification.verified, BICBackend(),
    modules=(AlkaliMetalInAirRule(),), context=SynthesisContext(atmosphere="air"),
    ledger=ledger,
)
print("verified:", [h.id for h in verification.verified], "/ ranked:", [r.hypothesis.id for r in ranked])
assert ledger.verify()  # joint 昇格・降格を通しても追記専用 Ledger は無傷 (P2/NFR-105)
```

AI エージェント連携は MCP サーバ (`tsumugin.mcp`) が担う。`AnalysisSession` facade に
project/backend/selection/ledger 等を束ね、submit / list / compare / accept / revert /
get_trajectory / export_gpx / run_mem の 8 ツール (SDK 非依存の実処理層) を委譲する。応答は
すべて素の型 dict で、`accept`/`revert` は最終選択モード (agent/human) を同一適用し、`revert`
は削除でなく superseded 化 (追記型) に留まる:

```python
from tsumugin import (
    AnalysisSession, FinalSelectionEngine, Ledger, SnapshotStore, Project, BICBackend,
    SimulatedBackend, create_mcp_server,
)
from tsumugin.mcp.tools import list_hypotheses, accept_hypothesis, revert

ledger = Ledger()
session = AnalysisSession(
    project=Project(id="demo"), backend=SimulatedBackend(),
    selection=FinalSelectionEngine(mode="agent", ledger=ledger),
    ledger=ledger, snapshots=SnapshotStore(ledger=ledger),
    evidence=BICBackend(), search_result=result,  # 上の探索結果を渡す
)
accept_hypothesis(session, result.good_cluster_ids[0], by="agent", reason="best fit")
revert(session, result.good_cluster_ids[0], note="rollback")   # 破壊的削除でなく superseded 化
assert session.ledger.verify()

# MCP サーバの構築は create_mcp_server(session)。mcp SDK は関数呼び出し時に遅延 import される
# (コア import は numpy のみ)。SDK 未導入なら MCPUnavailableError で導入手順を案内する。
```

`create_mcp_server` はトップレベルから import 可能だが、`import tsumugin` 自体は mcp SDK を
一切引き込まない (コア import は numpy のみ / REQ-403)。SDK は `create_mcp_server(session)` /
`serve_stdio(session)` の **呼び出し時点** でのみ遅延 import され、未導入なら
`MCPUnavailableError` に縮退する (`WebUIUnavailableError` と対称)。

## 使い方 (M5): nested 裁定 / MEM 解析 / OED 提案

木探索は bic のまま維持し、その残った **僅差競合** (ΔBIC < 10) のみを nested sampling で
再裁定する 2 段構え裁定 (`arbitrate`)。裁定後の確率は backend 別に較正できる
(`calibrate_by_backend`: ECE / reliability diagram)。nested の実サンプラ (`dynesty`) 未導入時は
`NestedUnavailableError` を経て Laplace evidence へ縮退する (較正・裁定はコア numpy のみで動作):

```python
import numpy as np
from tsumugin import (
    Hypothesis, RefinementMetrics, EvidenceProblem, PriorSpec, Ledger,
    NestedBackend, CalibrationSample, arbitrate, calibrate_by_backend,
)

def hyp(hid, chi2):
    m = RefinementMetrics(rwp=5.0, gof=1.2, chi2=chi2, n_obs=1000, n_params=8)
    return Hypothesis(id=hid, phases=(), metrics=m)

def problem():
    priors = (
        PriorSpec(param_name="phase0.lattice.a", kind="uniform", low=4.0, high=6.0),
        PriorSpec(param_name="phase0.occ.site", kind="uniform", low=0.0, high=1.0),
    )
    m = RefinementMetrics(rwp=5.0, gof=1.2, chi2=100.0, n_obs=1000, n_params=8)
    return EvidenceProblem(
        metrics=m, priors=priors,
        log_likelihood=lambda t: float(-0.5 * np.sum((np.asarray(t) - [5.0, 0.5]) ** 2)),
    )

ledger = Ledger()
hyps = (hyp("h1", 100.0), hyp("h2", 103.0), hyp("h3", 200.0))  # h1/h2 は僅差競合
problems = {h.id: problem() for h in hyps}

# 僅差競合 (ΔBIC<10) のみ nested で再裁定する (未導入は Laplace 縮退)
result = arbitrate(hyps, problems=problems, nested=NestedBackend(), ledger=ledger)
print("nested 再裁定対象:", result.nested_ids)  # ('h1', 'h2')

# 裁定後の確率を backend 別に較正 (ECE / reliability diagram)
samples = [
    CalibrationSample(a.ranked.probability, a.ranked.hypothesis.id == "h1", backend="nested")
    for a in result.arbitrated
]
reports = calibrate_by_backend(samples)
assert ledger.verify()  # 裁定を通しても追記専用 Ledger は無傷 (P2/NFR-105)
```

joint 検証済みの精密化解から MEM (最大エントロピー法) 入力を決定論的に生成し
(`build_mem_input`: probe に応じ X 線→電子密度 / 中性子→核密度)、MEM-Rietveld 反復
(`run_mem_rietveld`, 既定オフ) を回す。有効時は各サイクルを **子スナップショット** として追記する
(親の相/joint 結果は不変・P2)。`MEMBackend` は交換可能な Protocol 境界で、v1 実体は外部バイナリ
ラッパ `DysnomiaBackend`:

```python
import numpy as np
from tsumugin import (
    SimulatedBackend, PhaseInstance, LatticeParams, JointHistogram, Ledger, SnapshotStore,
    MEMDensityMap, MEMResult, MEMRietveldConfig, build_mem_input, run_mem_rietveld,
)
from tsumugin.joint.engine import refine_joint_detailed
from tsumugin.joint.model import JointRefinementModel

backend = SimulatedBackend(peak_fwhm=0.2)
two_theta = np.arange(15.0, 40.0, 0.05)
phases = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
y = backend.simulate(phases, two_theta)
joint_result = refine_joint_detailed(backend, JointRefinementModel(
    phases=phases,
    histograms=(JointHistogram(two_theta=two_theta, intensity=y, probe="xray"),),
    shared_free_params=frozenset({"phase0.scale"}),
))

# 精密化済み joint 結果から MEM 入力を生成 (probe に応じ電子/核密度を選択)
mem_input = build_mem_input(joint_result, "xray", grid_shape=(32, 32, 32))
print("密度種別:", mem_input.density_kind)  # electron

# MEMBackend は Protocol 境界 (v1 実体は DysnomiaBackend)。ここではデモ用の最小モック
class DemoMEM:
    name = "demo"
    def run(self, mi):
        dm = MEMDensityMap(path="demo.grd", density_kind=mi.density_kind,
                           grid_shape=mi.grid_shape, min_density=0.0, max_density=10.0)
        return MEMResult(density_map=dm, r_factor=0.1)

# MEM-Rietveld 反復 (既定オフ)。有効時は各サイクルを子スナップショットとして追記 (親不変)
snaps, mledger = SnapshotStore(), Ledger()
mem_res = run_mem_rietveld(
    backend, DemoMEM(), joint_result, phases, "xray",
    config=MEMRietveldConfig(enabled=True, max_iter=2), snapshots=snaps, ledger=mledger,
)
print("停止理由:", mem_res.stop_reason, "/ サイクル数:", len(mem_res.cycles))
assert mledger.verify()
```

裁定後も残った僅差競合は、それを判別するための **追加測定** を情報利得順に提案できる
(`propose_measurements`: 高統計再測定 / 中性子 joint / 組成分析 / 追加温度点)。提案は **非破壊**
で、仮説を accepted/rejected 化せず・データを改変せず、ledger には追記記録するのみ (提案のみ)。
僅差競合が無ければ空提案 (状態変更なし)。PyBOED 獲得関数による高度な情報利得評価は `acquire` の
遅延 import 境界に隔離され、v1 の提案生成はコアのみで動作する:

```python
from tsumugin import BICBackend, Ledger, rank, propose_measurements
from tsumugin.oed import proposals_to_json

ledger = Ledger()
ranked = rank(hyps, BICBackend())  # 僅差競合フラグ付きランキング (上の hyps を再利用)

# 僅差競合があるときのみ判別測定を情報利得順に提案する (非破壊・提案のみ)
proposals = propose_measurements(ranked, ledger=ledger)
for row in proposals_to_json(proposals):
    print(f"{row['kind']}: gain={row['estimated_information_gain']:.3f}")
assert ledger.verify()  # 提案は accepted/rejected 化せず ledger 追記のみ (P2)
```

nested/mem/oed の実バックエンド (dynesty / Dysnomia / pyboed) はいずれも各境界の遅延 import に
隔離されており、`import tsumugin` はコア (numpy のみ) を維持する。`arbitrate` / `build_mem_input` /
`propose_measurements` はトップレベルから import できるが、実サンプラ・実バイナリ・pyboed を
一切引き込まない (REQ-403)。

## アーキテクチャ (M0 + M1 + M2 + M3 + M4 + M5 実装済み範囲)

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
| `tsumugin.multistart` | 摂動マルチスタート大域最適化 (basin クラスタ・発散除外・大域裏取り) | FR-230〜231 |
| `tsumugin.operando` | echem 同期 + セル固定相 + IC 区間分割 + 固溶体/二相判別 + 結合出力/ヒステリシス | FR-311〜316 |
| `tsumugin.absorption` | 透過配置の吸収補正 (A = exp(-μt/cosθ)) + `CellConfig` 連携 | REQ-016 |
| `tsumugin.joint` | X 線+中性子マルチヒストグラム joint 精密化 + 生存仮説の joint 検証 + コントラスト占有率解放推奨 | FR-240〜245 |
| `tsumugin.chem` | ChemPlausibility 境界 (降格のみ・除外しない) + v1 ルール + スコア合成 + rank 配線 | FR-412 |
| `tsumugin.mcp` | AI エージェント連携 MCP サーバ (SDK 非依存の 8 ツール実処理層 + 遅延 import アダプタ) | FR-420 |
| `tsumugin.nested` | nested sampling 再裁定 (bic 一次 + 僅差競合のみ再裁定) + Laplace evidence + 事前分布 + 確率較正 | FR-500〜510 |
| `tsumugin.mem` | MEM (最大エントロピー法) ソルバ境界 (`MEMBackend`) + 適用ガード + 密度出力 + MEM-Rietveld 反復 (子スナップショット) | FR-601〜606 |
| `tsumugin.oed` | 最適実験計画 (僅差競合の判別測定を情報利得順に提案・非破壊) + PyBOED 獲得関数の遅延 import 境界 | FR-700〜704 |

実装計画は [docs/dev/plans/m0-refinement-core/](docs/dev/plans/m0-refinement-core/) を参照。
