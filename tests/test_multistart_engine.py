"""TASK-0028 multistart/basin + MultistartEngine (FR-230/232 / 設計 D2/D3) の失敗テスト (TDD Red)。

対象実装 (**未実装**):
- ``src/tsumugin/multistart/basin.py``: ``BasinInfo`` (frozen dataclass) /
  ``cluster_basins(results, *, basin_rel_tol)`` (収束解を正規化パラメータ距離で union-find
  クラスタし、代表 = chi2 最小解・evidence 昇順の ``tuple[BasinInfo, ...]`` を返す純関数)。
- ``src/tsumugin/multistart/engine.py``: ``MultistartResult`` (frozen dataclass) /
  ``MultistartEngine(backend, *, config, ledger).run(phases, two_theta, intensity, *,
  free_suffixes, weights)`` (generate_starts → 各 start の direct refine → 発散除外 →
  basin クラスタ → 複数 basin 昇格 → MultistartResult)。

契約は ``docs/design/m3-operando/interfaces.py`` L143-191 に確定。18 件 (basin 正常/境界 6 +
engine 正常/異常/境界 12) はテストケース定義 (multistart-basin-engine-testcases.md) に 1:1 対応する。

テストダブル ``InitialValueFakeBackend`` は初期値 (model.phases[0].lattice.a) 依存で収束解を決める
決定論スタブ (単峰/双峰/発散)。``RefinementBackend`` Protocol (name + refine) のみ満たし GSAS-II 非依存。

対象 2 モジュール未実装のため import が collection 時に失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, RefinementResult
from tsumugin.evidence.ic import BICBackend
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance, RefinementMetrics
from tsumugin.multistart import MultistartConfig
from tsumugin.store.ledger import Ledger

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定 (Red)。
from tsumugin.multistart.basin import BasinInfo, cluster_basins
from tsumugin.multistart.engine import MultistartEngine, MultistartResult

# ---------------------------------------------------------------------------
# 共通テストデータ・ヘルパ (モジュールレベルで一度だけ構築し不変共有する)
# ---------------------------------------------------------------------------

# 【観測グリッド】: fake backend は intensity.size (=n_obs) しか参照しないため小グリッドで十分。
#   実行時間を抑えるため 64 点に縮める (basin/engine の判定は初期値と収束解に依存し波形非依存)。🔵
GRID = np.linspace(10.0, 40.0, 64)
INTENSITY = np.ones(64, dtype=float)

# 【free_params 期待集合】: free_suffixes 既定 × 単相 (phase0) で構築される解放パラメータ名。🔵
_FREE_1PHASE = {"phase0.scale", "phase0.lattice.a", "phase0.lattice.b", "phase0.lattice.c"}


def _phase(ref: str = "A", a: float = 5.5, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンスを組む (a=b=c を変えるとパラメータ距離が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


# 【エンジン入力の基準相】: base a=5.5。双峰スタブは split=5.5 で摂動列を 2 吸引域へ分ける。🔵
PHASES = (_phase("A", 5.5),)


def _result(
    a: float,
    chi2: float,
    *,
    b: float | None = None,
    c: float | None = None,
    scale: float = 1.0,
    n_obs: int = 100,
    n_params: int = 4,
    ref: str = "A",
) -> RefinementResult:
    """basin クラスタ直接テスト用の収束解を組む (b/c 既定は a と同値)。"""
    bb = a if b is None else b
    cc = a if c is None else c
    phases = (PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, bb, cc), scale=scale),)
    return RefinementResult(
        phases=phases,
        chi2=chi2,
        rwp=0.0,
        n_obs=n_obs,
        n_params=n_params,
        converged=math.isfinite(chi2),
        n_cycles=1,
        free_params=frozenset(_FREE_1PHASE),
    )


def _bic(chi2: float, n_obs: int = 100, n_params: int = 4) -> float:
    """BICBackend による evidence 期待値 (BIC = chi2 + n_params·ln(max(n_obs,1)))。"""
    metrics = RefinementMetrics(rwp=0.0, gof=0.0, chi2=chi2, n_obs=n_obs, n_params=n_params)
    return BICBackend().score(metrics).value


# ---------------------------------------------------------------------------
# テストダブル (初期値依存の収束解 / 発散注入 / direct refine 呼び出し記録)
# ---------------------------------------------------------------------------


class InitialValueFakeBackend:
    """初期値 (model.phases[0].lattice.a) 依存で収束解を決める決定論スタブ (双峰テストの要)。

    - mode="unimodal": 任意初期値 → 収束 a=5.0 / chi2=8.0 (全 start 同一 basin)。
    - mode="bimodal": 初期 a<split → 収束 a=5.0 / chi2=8.0、a>=split → 収束 a=6.0 / chi2=12.0。
      収束 phases は吸引域ごとに固定 (a/b/c/scale 同値) にし、同一 basin の正規化距離を 0 に畳む。
    - 発散: diverge_all=True か、呼び出し順 (=start index) が diverge_starts の start は chi2=inf。
      engine は各 start を 0..N-1 順に direct refine するため呼び出し順が start index に一致する
      (この契約は TC-E05 で検証)。
    """

    name = "ivfake"

    def __init__(
        self,
        *,
        mode: str = "unimodal",
        split: float = 5.5,
        diverge_starts: frozenset[int] = frozenset(),
        diverge_all: bool = False,
    ) -> None:
        self.mode = mode
        self.split = float(split)
        self.diverge_starts = frozenset(diverge_starts)
        self.diverge_all = diverge_all
        # 【呼び出し記録】: direct refine の (free_params, max_cycles, a_init) を start 順に保存。
        self.calls: list[dict] = []

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        a_init = float(model.phases[0].lattice.a)
        start_index = len(self.calls)  # 呼び出し順 = start index (engine は 0..N-1 順に direct 呼び)
        self.calls.append(
            {
                "free_params": frozenset(model.free_params),
                "max_cycles": max_cycles,
                "a_init": a_init,
            }
        )
        n_obs = int(np.asarray(model.intensity).size)
        n_params = len(model.free_params)
        # 【発散注入】: 全滅 or 指定 start は chi2=inf 結果へ (例外化しない / CLAUDE.md 不変条件)。
        if self.diverge_all or start_index in self.diverge_starts:
            return self._make(model.phases, float("inf"), n_obs, n_params, snap_a=None)
        # 【吸引域決定】: 双峰は初期 a と split の大小で 2 解へ、単峰は常に 1 解へ写像。
        if self.mode == "bimodal" and a_init >= self.split:
            conv_a, chi2 = 6.0, 12.0
        else:
            conv_a, chi2 = 5.0, 8.0
        return self._make(model.phases, chi2, n_obs, n_params, snap_a=conv_a)

    def _make(
        self,
        phases: tuple[PhaseInstance, ...],
        chi2: float,
        n_obs: int,
        n_params: int,
        *,
        snap_a: float | None,
    ) -> RefinementResult:
        if snap_a is None:
            snapped = phases  # 【発散】: basin 対象外なので入力保持で可
        else:
            # 【吸引域スナップ】: 収束 phases を吸引域固定値へ (同一 basin の距離を 0 に畳む)。
            snapped = tuple(
                p.with_updates(lattice=LatticeParams(snap_a, snap_a, snap_a), scale=1.0)
                for p in phases
            )
        return RefinementResult(
            phases=snapped,
            chi2=chi2,
            rwp=0.0,
            n_obs=n_obs,
            n_params=n_params,
            converged=math.isfinite(chi2),
            n_cycles=1,
            free_params=frozenset(_FREE_1PHASE),
        )


def _member_union(result: MultistartResult) -> set[int]:
    """全 basin の member_starts の和集合 (発散除外の検証に使う)。"""
    union: set[int] = set()
    for basin in result.basins:
        union.update(basin.member_starts)
    return union


# ---------------------------------------------------------------------------
# 1. basin クラスタ (basin.py) — 正常系・境界値
# ---------------------------------------------------------------------------


def test_basin_all_close_forms_single_basin():
    # 【テスト目的】: 全対の正規化距離が tol 未満の収束解群が 1 basin に畳まれる (TC-B01 / TC-201-02 basin 層)
    # 【テスト内容】: cluster_basins に近接 8 解を渡し、単一 basin・全 member 昇順・代表 chi2 最小を確認
    # 【期待される動作】: len==1、member_starts==(0..7)、representative=chi2 最小解、evidence=bic(8.0)
    # 🔵 信頼性レベル: D3 (相対距離 < tol の union-find) / REQ-002 に直接依拠

    # 【テストデータ準備】: a を基準 ±0.07% 以内に収め (全対で tol=1% 未満)、chi2 は 8..15 でばらつかせる
    # 【初期条件設定】: 単峰 = 全 start が同一 basin へ収束した状況の直接表現 (代表は chi2 最小の index0)
    results = [_result(5.0 + 0.0005 * i, 8.0 + i) for i in range(8)]

    # 【実際の処理実行】: 正規化パラメータ距離 → union-find → 代表選出 → evidence 昇順ソート
    basins = cluster_basins(results, basin_rel_tol=1e-2)

    # 【結果検証】: 単一 basin に全 start が入り、代表と evidence が正しいこと
    assert len(basins) == 1  # 【確認内容】: 近接 8 解が 1 basin に畳まれる 🔵
    assert basins[0].member_starts == (0, 1, 2, 3, 4, 5, 6, 7)  # 【確認内容】: 全 start が昇順で所属 🔵
    assert basins[0].representative == results[0]  # 【確認内容】: 代表 = chi2 最小 (index0) 解 🔵
    assert basins[0].chi2 == 8.0  # 【確認内容】: basin の chi2 は代表の chi2 🔵
    assert basins[0].evidence == pytest.approx(_bic(8.0))  # 【確認内容】: evidence = BICBackend 値 🔵


def test_basin_two_groups_two_basins_evidence_ascending():
    # 【テスト目的】: 群内近接・群間 tol 超の 2 群が 2 basin に分かれ evidence 昇順に並ぶ (TC-B02 / TC-201-03)
    # 【テスト内容】: a≈5.0 群 (chi2≈8) と a≈6.0 群 (chi2≈12) を cluster_basins へ渡す
    # 【期待される動作】: len==2、basins[0]=低 evidence 群 (chi2=8)、basins[1]=(chi2=12)、member 群分割
    # 🔵 信頼性レベル: D3 / REQ-002 (basin 数・chi2・evidence・代表報告) に直接依拠

    # 【テストデータ準備】: index0-3 が a≈5.0 群 (chi2 8..11)、index4-7 が a≈6.0 群 (chi2 12..15)
    # 【初期条件設定】: 群間 |5-6|/5=20% は tol 超で必ず分離、群内は 0.06% 以内で必ず結合
    group1 = [_result(5.0 + 0.001 * i, 8.0 + i) for i in range(4)]
    group2 = [_result(6.0 + 0.001 * i, 12.0 + i) for i in range(4)]
    results = group1 + group2

    # 【実際の処理実行】: 2 群への union-find 分割 → 各群代表 → evidence 昇順ソート
    basins = cluster_basins(results, basin_rel_tol=1e-2)

    # 【結果検証】: 2 basin・evidence 昇順・群分割・chi2 報告
    assert len(basins) == 2  # 【確認内容】: 2 群が 2 basin に分離 🔵
    assert basins[0].evidence <= basins[1].evidence  # 【確認内容】: evidence 昇順ソート 🔵
    assert basins[0].chi2 == 8.0  # 【確認内容】: 低 evidence basin の代表 chi2 🔵
    assert basins[1].chi2 == 12.0  # 【確認内容】: 高 evidence basin の代表 chi2 🔵
    assert basins[0].member_starts == (0, 1, 2, 3)  # 【確認内容】: a≈5.0 群の start index 昇順 🔵
    assert basins[1].member_starts == (4, 5, 6, 7)  # 【確認内容】: a≈6.0 群の start index 昇順 🔵


def test_basin_representative_is_min_chi2_tie_lowest_index():
    # 【テスト目的】: basin 代表が chi2 最小、同点は start index 小優先で決定論になる (TC-B03)
    # 【テスト内容】: 同一 basin 3 解 chi2=[10,8,8] を渡し index1 が代表になることを確認
    # 【期待される動作】: representative == results[1] (chi2 同点は index 小)、member_starts==(0,1,2)
    # 🔵 信頼性レベル: D3 (代表は chi2 最小) / clustering の同点 index 小優先パターンに依拠

    # 【テストデータ準備】: a は近接 (0.04% 以内で 1 basin)、chi2=[10,8,8] で index1/2 が同点最小
    # 【初期条件設定】: index1 と index2 を a で区別し representative == results[1] を一意判定可能に
    results = [_result(5.0, 10.0), _result(5.001, 8.0), _result(5.002, 8.0)]

    # 【実際の処理実行】: 単一 basin 内で代表選出 (chi2 最小 + 同点 index 小)
    basins = cluster_basins(results, basin_rel_tol=1e-2)

    # 【結果検証】: 代表選出の決定論
    assert len(basins) == 1  # 【確認内容】: 近接 3 解は 1 basin 🔵
    assert basins[0].member_starts == (0, 1, 2)  # 【確認内容】: 全 start が昇順で所属 🔵
    assert basins[0].representative == results[1]  # 【確認内容】: 同点最小は index 小の index1 🔵
    assert basins[0].chi2 == 8.0  # 【確認内容】: 代表の chi2 は 8.0 🔵


def test_basin_rel_tol_boundary_strict_less_than():
    # 【テスト目的】: basin_rel_tol は strict `<` で分離判定する (境界=tol は別 basin) (TC-BV01)
    # 【テスト内容】: 正規化距離が代表基準で 0.01 の 2 解に対し tol を直上/ちょうど/直下で切り替える
    # 【期待される動作】: 距離 < tol → 1 basin、距離 == tol → 2 basin、距離 > tol → 2 basin
    # 🔵 信頼性レベル: D3 (相対距離 < tol) の strict 不等号を検証 (= tol は別 basin の自然な帰結)

    # 【テストデータ準備】: a のみ差 (b/c/scale 同値) で L2/L∞ 差を排除。代表 (chi2 最小) 基準の距離を固定
    # 【初期条件設定】: |5.05-5.0|/5.0 = 0.01。tol を 0.0101/0.01/0.0099 と変えて strict `<` を検証
    rep = _result(5.0, 8.0, b=5.0, c=5.0)  # chi2 最小 → 代表 (正規化距離の基準)
    other = _result(5.05, 9.0, b=5.0, c=5.0)  # 代表基準の正規化距離 0.01
    results = [rep, other]

    # 【実際の処理実行 & 結果検証】: 同一ペアに対し tol を変え basin 数の切り替わりを確認
    assert len(cluster_basins(results, basin_rel_tol=0.0101)) == 1  # 距離 < tol → 結合 🔵
    assert len(cluster_basins(results, basin_rel_tol=0.01)) == 2  # 距離 == tol → 分離 (strict) 🔵
    assert len(cluster_basins(results, basin_rel_tol=0.0099)) == 2  # 距離 > tol → 分離 🔵


def test_basin_empty_input_returns_empty():
    # 【テスト目的】: 収束解 0 件 (全滅後など) の入力が空タプルへ縮退する (TC-BV03)
    # 【テスト内容】: cluster_basins([], ...) が例外を投げず () を返すことを確認
    # 【期待される動作】: 戻り値 == () (clustering.py の空入力縮退パターンに整合)
    # 🔵 信頼性レベル: clustering.py 空入力縮退 / M0 規約に依拠

    # 【実際の処理実行】: 空 Sequence を渡す
    basins = cluster_basins([], basin_rel_tol=1e-2)

    # 【結果検証】: 空入力の非例外化
    assert basins == ()  # 【確認内容】: 空入力は空タプルへ縮退し例外化しない 🔵


def test_basin_single_result_forms_single_basin():
    # 【テスト目的】: 収束解が 1 件のとき単一要素 basin を成す (TC-BV04)
    # 【テスト内容】: cluster_basins に 1 解を渡し member_starts 単一・代表・evidence を確認
    # 【期待される動作】: len==1、member_starts==(0,)、representative=その解、evidence=bic
    # 🔵 信頼性レベル: D3 / clustering 単一要素クラスタ挙動に依拠

    # 【テストデータ準備】: 収束解 1 件 (発散除外後 1 本残に相当)
    only = _result(5.0, 9.0)

    # 【実際の処理実行】: 1 要素の basin 集約 (0 除算・空回避)
    basins = cluster_basins([only], basin_rel_tol=1e-2)

    # 【結果検証】: 単一要素 basin の member_starts・代表・evidence
    assert len(basins) == 1  # 【確認内容】: 1 解は 1 basin 🔵
    assert basins[0].member_starts == (0,)  # 【確認内容】: 単一 start が所属 🔵
    assert basins[0].representative == only  # 【確認内容】: 代表はその解自身 🔵
    assert basins[0].evidence == pytest.approx(_bic(9.0))  # 【確認内容】: evidence = bic 🔵


# ---------------------------------------------------------------------------
# 2. MultistartEngine (engine.py) — 正常系
# ---------------------------------------------------------------------------


def test_engine_unimodal_single_basin_corroborated():
    # 【テスト目的】: 単峰スタブで全 start が 1 basin へ収束し「大域最適の傍証あり」を返す (TC-E01 / TC-201-02)
    # 【テスト内容】: MultistartEngine.run のフルパイプライン (generate_starts→direct refine→basin)
    # 【期待される動作】: len(basins)==1、is_global_corroborated is True、promoted==()、n_diverged==0
    # 🔵 信頼性レベル: TC-201-02 / EDGE-001 / REQ-003 に直接依拠

    # 【テストデータ準備】: 単峰スタブ (任意初期値 → 同一収束解)、n_starts=8
    backend = InitialValueFakeBackend(mode="unimodal")
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8))

    # 【実際の処理実行】: 8 本を direct refine → 単一 basin へクラスタ
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 単一 basin 判定と傍証フラグ
    assert result.n_starts == 8  # 【確認内容】: 実行 start 総数 = config.n_starts 🔵
    assert result.n_diverged == 0  # 【確認内容】: 発散なし 🔵
    assert len(result.basins) == 1  # 【確認内容】: 全 start が単一 basin 🔵
    assert result.basins[0].member_starts == (0, 1, 2, 3, 4, 5, 6, 7)  # 【確認内容】: 全 8 start 所属 🔵
    assert result.is_global_corroborated is True  # 【確認内容】: n_basins==1 で傍証あり 🔵
    assert result.promoted == ()  # 【確認内容】: 単一 basin では昇格なし 🔵


def test_engine_bimodal_two_basins_reports_chi2_evidence():
    # 【テスト目的】: 双峰スタブで n_basins==2 となり両 basin の chi2/evidence を報告する (TC-E02 / TC-201-03)
    # 【テスト内容】: 初期値依存で 2 解へ収束する双峰問題に対する run のフルパイプライン
    # 【期待される動作】: len(basins)==2、evidence 昇順、chi2=8/12、member 和集合=全 start (発散なし)
    # 🔵 信頼性レベル: 受け入れ基準 TC-201-03 に直接依拠

    # 【テストデータ準備】: a<split→chi2=8, a>=split→chi2=12 の 2 吸引域スタブ (split=5.5)
    # 【初期条件設定】: n_starts=8、摂動列が split をまたいで各吸引域へ入る
    backend = InitialValueFakeBackend(mode="bimodal", split=5.5)
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8))

    # 【実際の処理実行】: generate_starts → 各 direct refine → 発散除外 → basin クラスタ
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: basin 数・evidence 昇順・chi2 報告・発散なし
    assert len(result.basins) == 2  # 【確認内容】: 双峰が 2 basin に分離 🔵
    assert result.basins[0].chi2 == 8.0  # 【確認内容】: 低 evidence basin の chi2 🔵
    assert result.basins[1].chi2 == 12.0  # 【確認内容】: 高 evidence basin の chi2 🔵
    assert result.basins[0].evidence < result.basins[1].evidence  # 【確認内容】: evidence 昇順 🔵
    assert result.n_diverged == 0  # 【確認内容】: 発散なし 🔵
    assert _member_union(result) == set(range(8))  # 【確認内容】: member 和集合 = 全 start 🔵
    assert result.is_global_corroborated is False  # 【確認内容】: n_basins>1 は傍証なし 🔵


def test_engine_multiple_basins_promote_hypotheses_rankable():
    # 【テスト目的】: 複数 basin が Hypothesis へ昇格され evidence で rank 可能 (TC-E03 / TC-201-04 / FR-232)
    # 【テスト内容】: 双峰 run の promoted が各 basin 代表 phases を持ち basins と同順で並ぶことを確認
    # 【期待される動作】: len(promoted)==2、各 phases が該当 basin 代表と一致、metrics.multistart 非 None
    # 🔵 信頼性レベル: TC-201-04 / FR-232 / REQ-003 に直接依拠

    # 【テストデータ準備】: TC-E02 と同じ双峰構成
    backend = InitialValueFakeBackend(mode="bimodal", split=5.5)
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8))

    # 【実際の処理実行】: 複数 basin → 各 basin を Hypothesis へ昇格
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 昇格仮説の生成・順序・phases 対応・rank 可能性
    assert len(result.promoted) == 2  # 【確認内容】: 2 basin が 2 仮説へ昇格 🔵
    assert isinstance(result.promoted[0], Hypothesis)  # 【確認内容】: 昇格物は Hypothesis 🔵
    assert result.promoted[0].phases == result.basins[0].representative.phases  # basin0 代表 phases 🔵
    assert result.promoted[1].phases == result.basins[1].representative.phases  # basin1 代表 phases 🔵
    assert result.promoted[0].metrics is not None  # 【確認内容】: metrics が付与される 🔵
    assert result.promoted[0].metrics.multistart is not None  # 【確認内容】: multistart 記録が非 None 🔵


def test_engine_records_metrics_multistart():
    # 【テスト目的】: 昇格仮説の metrics.multistart に {n,n_basins,n_diverged} が記録される (TC-E04 / TC-201-06)
    # 【テスト内容】: 双峰 (発散なし) run の各昇格仮説 metrics.multistart を検証
    # 【期待される動作】: metrics.multistart == {"n":8, "n_basins":2, "n_diverged":0}
    # 🔵 信頼性レベル: TC-201-06 / REQ-006 (RefinementMetrics.multistart) に直接依拠

    # 【テストデータ準備】: TC-E02 の双峰構成 (発散なし)
    backend = InitialValueFakeBackend(mode="bimodal", split=5.5)
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8))

    # 【実際の処理実行】: 昇格時に metrics.multistart を付与
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 記録キー・値の完全一致
    expected = {"n": 8, "n_basins": 2, "n_diverged": 0}
    assert dict(result.promoted[0].metrics.multistart) == expected  # 【確認内容】: 仮説0 の記録 🔵
    assert dict(result.promoted[1].metrics.multistart) == expected  # 【確認内容】: 仮説1 の記録 🔵


def test_engine_calls_direct_refine_n_times():
    # 【テスト目的】: run が各 start に direct refine を N 回・max_cycles=ms_max_cycles で呼ぶ (TC-E05 / D2)
    # 【テスト内容】: 呼び出し記録スタブで refine 回数・max_cycles・free_params 構築を観測
    # 【期待される動作】: len(calls)==8、全 max_cycles==15、各 free_params が free_suffixes×相数で構成
    # 🔵 信頼性レベル: D2 / interfaces.py run シグネチャ (free_suffixes) / REQ-005 に依拠

    # 【テストデータ準備】: 単峰スタブ (呼び出し記録内蔵)、n_starts=8, ms_max_cycles=15
    backend = InitialValueFakeBackend(mode="unimodal")
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8, ms_max_cycles=15))

    # 【実際の処理実行】: direct refine を start ごとに 1 回だけ呼ぶ
    engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 呼び出し回数・max_cycles 伝播・free_params 構築
    assert len(backend.calls) == 8  # 【確認内容】: N=8 start に direct 1 回ずつ 🔵
    assert all(call["max_cycles"] == 15 for call in backend.calls)  # 【確認内容】: ms_max_cycles 伝播 🔵
    assert all(call["free_params"] == _FREE_1PHASE for call in backend.calls)  # free_suffixes×相数 🔵


def test_engine_ledger_records_and_verifies():
    # 【テスト目的】: ledger 提供時に各操作を追記し実行後も verify()==True である (TC-E06 / NFR-105)
    # 【テスト内容】: Ledger を渡した双峰 run 後にエントリ非空・kind 前置・ハッシュチェーン整合を確認
    # 【期待される動作】: len(entries)>0、全 kind が "multistart." で始まる、verify() is True
    # 🔵 信頼性レベル: NFR-105 / タスク本文「全操作 ledger 記録」に依拠

    # 【テストデータ準備】: Ledger を渡した engine、双峰構成
    ledger = Ledger()
    backend = InitialValueFakeBackend(mode="bimodal", split=5.5)
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8), ledger=ledger)

    # 【実際の処理実行】: 各操作を append で追記
    engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 追記専用・ハッシュチェーン整合
    assert len(ledger.entries) > 0  # 【確認内容】: 操作が記録される 🔵
    assert all(e.kind.startswith("multistart.") for e in ledger.entries)  # kind は multistart.* 🔵
    assert ledger.verify() is True  # 【確認内容】: 記録後もチェーン整合 🔵


def test_engine_deterministic_bitwise_identical():
    # 【テスト目的】: 同一入力で run を 2 回実行すると MultistartResult がビット同一になる (TC-E07 / NFR-102)
    # 【テスト内容】: 双峰構成を新規 engine で 2 回実行し結果の == 一致を確認
    # 【期待される動作】: result_a == result_b (basins/member_starts/promoted/n_diverged すべて一致)
    # 🔵 信頼性レベル: NFR-102 / REQ-402 / 完了条件「決定論 (2 回でビット同一)」に直接依拠

    # 【テストデータ準備】: 各回とも新規 backend/engine (同一入力・同一 config)
    engine_a = MultistartEngine(
        InitialValueFakeBackend(mode="bimodal", split=5.5), config=MultistartConfig(n_starts=8)
    )
    engine_b = MultistartEngine(
        InitialValueFakeBackend(mode="bimodal", split=5.5), config=MultistartConfig(n_starts=8)
    )

    # 【実際の処理実行】: 2 回実行
    result_a = engine_a.run(PHASES, GRID, INTENSITY)
    result_b = engine_b.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: union-find・代表選出・basins/promoted ソートの決定論
    assert result_a == result_b  # 【確認内容】: 2 回実行でビット同一 (id も決定論) 🔵
    assert result_a.basins == result_b.basins  # 【確認内容】: basins が完全一致 🔵
    assert result_a.promoted == result_b.promoted  # 【確認内容】: promoted が完全一致 🔵


# ---------------------------------------------------------------------------
# 3. MultistartEngine (engine.py) — 異常系 (発散・全滅)
# ---------------------------------------------------------------------------


def test_engine_diverged_starts_excluded_and_counted():
    # 【テスト目的】: 一部 start が発散したとき basin から除外し n_diverged にカウントする (TC-A01 / TC-201-05)
    # 【テスト内容】: 2 本を chi2=inf で返す双峰スタブで run し除外・カウント・非例外化を確認
    # 【期待される動作】: n_diverged==2、member 和集合が発散 2 本を除く 6 本、n_starts==8、例外なし
    # 🟡 信頼性レベル: REQ-102 / TC-201-05 に依拠 (発散本数はテスト設計の妥当推測)

    # 【テストデータ準備】: start index 2 と 5 に chi2=inf を返させる (各吸引域から 1 本ずつ除外)
    # 【初期条件設定】: n_starts=8。発散を例外化せず縮退処理する契約を検証
    backend = InitialValueFakeBackend(mode="bimodal", split=5.5, diverge_starts=frozenset({2, 5}))
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8))

    # 【実際の処理実行】: 発散 start を除外し残りを basin クラスタ
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 発散判定・除外・カウント・非例外化
    assert result.n_starts == 8  # 【確認内容】: 実行 start 総数は不変 🟡
    assert result.n_diverged == 2  # 【確認内容】: 発散 2 本をカウント 🟡
    union = _member_union(result)
    assert len(union) == 6  # 【確認内容】: 収束 6 本が basin に残る 🟡
    assert 2 not in union and 5 not in union  # 【確認内容】: 発散 start は basin に含まれない 🟡


def test_engine_all_diverged_warns_empty_basins():
    # 【テスト目的】: 全 start 発散時に警告 + 空 basins + 元仮説維持へ縮退する (TC-A02 / EDGE-002)
    # 【テスト内容】: 全 start に chi2=inf を返すスタブで run し縮退値・警告・非例外化を確認
    # 【期待される動作】: basins==()、n_diverged==8、warnings 非空、is_global_corroborated False、promoted==()
    # 🟡 信頼性レベル: EDGE-002 / TC-201-05 / REQ-102 に依拠 (警告文言は実装裁量)

    # 【テストデータ準備】: 全 start 発散スタブ、n_starts=8、ledger も渡し verify 維持を確認
    ledger = Ledger()
    backend = InitialValueFakeBackend(mode="unimodal", diverge_all=True)
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=8), ledger=ledger)

    # 【実際の処理実行】: 全滅を例外化せず縮退値を返す
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 全滅縮退・警告・元仮説維持・非例外化
    assert result.basins == ()  # 【確認内容】: basin なし (空タプル) 🟡
    assert result.n_diverged == 8  # 【確認内容】: 全 8 本が発散 🟡
    assert result.warnings != ()  # 【確認内容】: 全滅を示す警告が付く 🟡
    assert result.is_global_corroborated is False  # 【確認内容】: 傍証なし 🟡
    assert result.promoted == ()  # 【確認内容】: 昇格なし (元仮説維持) 🟡
    assert ledger.verify() is True  # 【確認内容】: 全滅時も ledger チェーン整合 🔵


# ---------------------------------------------------------------------------
# 4. MultistartEngine / BasinInfo — 境界値
# ---------------------------------------------------------------------------


def test_engine_n_equals_one_degenerate_single_basin():
    # 【テスト目的】: n_starts==1 (摂動なし 1 本) でエンジンが成立し basin=1 になる (TC-BV02 / TC-201-07)
    # 【テスト内容】: 単一 start 構成で run し 0 除算回避・単一 basin 判定を確認
    # 【期待される動作】: n_starts==1、len(basins)==1、is_global_corroborated True、n_diverged==0、promoted==()
    # 🟡 信頼性レベル: EDGE-101 / TC-201-07 に依拠 (N=1 エンジン挙動は妥当推測)

    # 【テストデータ準備】: n_starts=1 (基準 1 組のみ)、単峰スタブ
    backend = InitialValueFakeBackend(mode="unimodal")
    engine = MultistartEngine(backend, config=MultistartConfig(n_starts=1))

    # 【実際の処理実行】: 1 start の basin 集約 (正規化距離計算の 0 除算回避)
    result = engine.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: 1 本での単一 basin 判定
    assert result.n_starts == 1  # 【確認内容】: start 総数 1 🟡
    assert len(result.basins) == 1  # 【確認内容】: 単一 basin 🟡
    assert result.basins[0].member_starts == (0,)  # 【確認内容】: 基準 start のみ所属 🟡
    assert result.is_global_corroborated is True  # 【確認内容】: n_basins==1 で傍証あり 🟡
    assert result.n_diverged == 0  # 【確認内容】: 発散なし 🟡
    assert result.promoted == ()  # 【確認内容】: 単一 basin では昇格なし 🟡


def test_engine_works_without_ledger():
    # 【テスト目的】: ledger 未提供 (既定 None) でもエンジンが完全に動作する (TC-BV05)
    # 【テスト内容】: ledger あり/なしの双峰 run が同一 basins/promoted を返すことを確認
    # 【期待される動作】: ledger=None でも TC-E02 と同一内容、例外なし
    # 🔵 信頼性レベル: interfaces.py `ledger: Ledger | None = None` 既定に依拠

    # 【テストデータ準備】: ledger なし engine と ledger あり engine (それぞれ新規 backend)
    engine_none = MultistartEngine(
        InitialValueFakeBackend(mode="bimodal", split=5.5), config=MultistartConfig(n_starts=8)
    )
    engine_ledger = MultistartEngine(
        InitialValueFakeBackend(mode="bimodal", split=5.5),
        config=MultistartConfig(n_starts=8),
        ledger=Ledger(),
    )

    # 【実際の処理実行】: ledger 有無で 2 回実行
    result_none = engine_none.run(PHASES, GRID, INTENSITY)
    result_ledger = engine_ledger.run(PHASES, GRID, INTENSITY)

    # 【結果検証】: ledger 非依存 (結果の同一性)
    assert len(result_none.basins) == 2  # 【確認内容】: ledger なしでも双峰を検出 🔵
    assert result_none.basins == result_ledger.basins  # 【確認内容】: basins は ledger 有無で不変 🔵
    assert result_none.promoted == result_ledger.promoted  # 【確認内容】: promoted も不変 🔵


def test_basininfo_and_result_are_frozen():
    # 【テスト目的】: BasinInfo / MultistartResult が frozen (不変値オブジェクト) である (TC-BV06)
    # 【テスト内容】: 各フィールドへの再代入で FrozenInstanceError が送出されることを確認
    # 【期待される動作】: 属性代入で dataclasses.FrozenInstanceError
    # 🔵 信頼性レベル: CLAUDE.md 規約 (frozen dataclass) / interfaces.py @dataclass(frozen=True) に依拠

    # 【テストデータ準備】: 最小の BasinInfo / MultistartResult を構築
    basin = BasinInfo(representative=_result(5.0, 8.0), member_starts=(0,), chi2=8.0, evidence=1.0)
    result = MultistartResult(
        basins=(basin,),
        n_starts=1,
        n_diverged=0,
        promoted=(),
        is_global_corroborated=True,
    )

    # 【結果検証】: frozen 属性への再代入が拒否される
    with pytest.raises(FrozenInstanceError):
        basin.chi2 = 9.0  # 【確認内容】: BasinInfo は不変 🔵
    with pytest.raises(FrozenInstanceError):
        result.n_starts = 2  # 【確認内容】: MultistartResult は不変 🔵
