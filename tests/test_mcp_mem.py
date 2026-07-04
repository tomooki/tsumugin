"""TASK-0057 mcp/mem.py 実体化 (run_mem_boundary MEMBackend 委譲) の TDD テスト。

対象実装:
- ``src/tsumugin/mcp/mem.py``: ``run_mem_boundary`` を M4 プレースホルダ境界から MEMBackend 委譲へ実体化
- ``src/tsumugin/mcp/tools.py``: ``AnalysisSession`` に ``verification`` フィールドを末尾・既定 None で追加

AC (完了条件 / TC-511-01〜04) に 1:1 対応:
  - TC-511-01: MEMBackend 委譲接続 + M4 placeholder スキーマ整合 (REQ-033)
  - TC-511-02: 破壊操作なし (子スナップショット追記のみ・削除/上書きなし, REQ-034/P2)
  - TC-511-03: MEMUnavailableError → error dict 変換・非クラッシュ (REQ-104/EDGE-006)
  - TC-511-04: MEM 結果を素の型 dict で返す (finite_or_none 純化・json.dumps allow_nan=False 安全, EDGE-013)

本層は MCP SDK を一切 import しない。テストも SDK 非依存で通常 pytest として動く。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from tsumugin.backends.base import RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.errors import MEMUnavailableError
from tsumugin.evidence.ic import BICBackend
from tsumugin.joint.model import JointRefinementResult, PerHistogramMetrics
from tsumugin.joint.verification import JointVerificationResult
from tsumugin.mem.base import (
    BondPathDensity,
    DensityCrossSection,
    MEMDensityMap,
    MEMResult,
)
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance, RefinementMetrics
from tsumugin.model.project import Dataset, Frame, HistogramRef, Project
from tsumugin.selection import FinalSelectionEngine
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

from tsumugin.mcp import mem as mem_module
from tsumugin.mcp.tools import AnalysisSession, run_mem


# ---------------------------------------------------------------------------
# テストダブルヘルパ
# ---------------------------------------------------------------------------


def _phase(a: float = 4.0, ref: str = "H1") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=1.0)


def _metrics(rwp: float = 5.0) -> RefinementMetrics:
    return RefinementMetrics(
        rwp=rwp, gof=1.0, chi2=1.0, n_obs=100, n_params=5, evidence={"bic": rwp}
    )


def _joint_result(ref: str = "H1") -> JointRefinementResult:
    aggregate = RefinementResult(
        phases=(_phase(ref=ref),),
        chi2=1.0,
        rwp=5.0,
        n_obs=100,
        n_params=5,
        converged=True,
        n_cycles=3,
    )
    per = (
        PerHistogramMetrics(
            hist_index=0, probe="xray", rwp=5.0, chi2=1.0, scale=1.0, sigma_source="covariance"
        ),
    )
    return JointRefinementResult(aggregate=aggregate, per_histogram=per)


def _verification(hyp_id: str = "H1") -> JointVerificationResult:
    hyp = Hypothesis(
        id=hyp_id, phases=(_phase(ref=hyp_id),), metrics=_metrics(), status="refined"
    )
    return JointVerificationResult(
        verified=(hyp,),
        joint_results={hyp_id: _joint_result(ref=hyp_id)},
        recommendations={hyp_id: ()},
        warnings=(),
    )


def _project_with_frame() -> Project:
    frame = Frame(
        id="f0",
        index=0,
        histograms=(HistogramRef(probe="xray", data_ref="d0"),),
    )
    dataset = Dataset(id="ds0", kind="single", frames=(frame,))
    return Project(id="proj-0", datasets=(dataset,))


def _session(
    *,
    mode: str = "agent",
    verification: JointVerificationResult | None = None,
    project: Project | None = None,
) -> AnalysisSession:
    ledger = Ledger()
    selection = FinalSelectionEngine(mode=mode, ledger=ledger)
    return AnalysisSession(
        project=project if project is not None else _project_with_frame(),
        backend=SimulatedBackend(),
        selection=selection,
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
        evidence=BICBackend(),
        verification=verification,
    )


class _StubMEMBackend:
    """MEMResult を返す MEMBackend スタブ。"""

    name = "stub"

    def __init__(self, result: MEMResult) -> None:
        self._result = result
        self.calls: list[object] = []

    def run(self, mem_input: object) -> MEMResult:
        self.calls.append(mem_input)
        return self._result


class _UnavailableMEMBackend:
    """run で MEMUnavailableError を送出する MEMBackend スタブ (未導入経路)。"""

    name = "unavailable"

    def run(self, mem_input: object) -> MEMResult:
        raise MEMUnavailableError("外部 MEM ソルバ未検出")


def _mem_result(*, min_density: float = 0.1, max_density: float = 9.9) -> MEMResult:
    return MEMResult(
        density_map=MEMDensityMap(
            path="/tmp/density.grd",
            density_kind="electron",
            grid_shape=(64, 64, 64),
            min_density=min_density,
            max_density=max_density,
        ),
        cross_sections=(
            DensityCrossSection(
                label="Na-Na",
                dimension=1,
                coordinates=np.array([0.0, 0.5, 1.0]),
                values=np.array([1.0, 2.0, 3.0]),
            ),
        ),
        bond_paths=(
            BondPathDensity(
                start_site="Na1", end_site="Na2", min_density=0.05, path_length=3.2
            ),
        ),
        r_factor=0.03,
        converged=True,
        warnings=("適用ガード: 低角反射不足",),
    )


# ===========================================================================
# 後方互換 (REQ-033): placeholder=True は M4 dict、mem_backend=None は MEMUnavailableError
# ===========================================================================


def test_placeholder_returns_m4_dict_unchanged():
    # 【テスト目的】: placeholder=True が M4 契約 dict を返す (後方互換不変)
    session = _session()
    result = mem_module.run_mem_boundary(session, placeholder=True)
    assert result == {"status": "not_implemented", "milestone": "M5", "tool": "run_mem"}


def test_default_without_backend_raises_mem_unavailable():
    # 【テスト目的】: mem_backend=None かつ placeholder=False は MEMUnavailableError (M4 既定不変)
    session = _session()
    with pytest.raises(MEMUnavailableError):
        mem_module.run_mem_boundary(session)


def test_run_mem_tool_default_still_raises():
    # 【テスト目的】: run_mem ツール経由でも既定は MEMUnavailableError (既存挙動不変)
    session = _session()
    with pytest.raises(MEMUnavailableError):
        run_mem(session)


# ===========================================================================
# TC-511-01: MEMBackend 委譲 — 素の型 dict で密度マップ・断面・ボンド経路・警告を返す
# ===========================================================================


def test_mem_backend_delegation_returns_plain_dict():
    # 【テスト目的】: mem_backend 供給時は build_mem_input→run で素の型 dict を返す
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=_verification("H1"))
    resp = mem_module.run_mem_boundary(session, mem_backend=backend, hypothesis_id="H1")

    assert resp["status"] == "ok"
    assert resp["hypothesis_id"] == "H1"
    assert resp["density_map"]["path"] == "/tmp/density.grd"
    assert resp["density_map"]["density_kind"] == "electron"
    assert resp["density_map"]["min_density"] == pytest.approx(0.1)
    assert resp["density_map"]["max_density"] == pytest.approx(9.9)
    assert resp["density_map"]["grid_shape"] == [64, 64, 64]
    assert resp["cross_sections"] == ["Na-Na"]
    assert resp["bond_paths"][0]["start_site"] == "Na1"
    assert resp["bond_paths"][0]["end_site"] == "Na2"
    assert resp["bond_paths"][0]["min_density"] == pytest.approx(0.05)
    assert resp["bond_paths"][0]["path_length"] == pytest.approx(3.2)
    assert resp["r_factor"] == pytest.approx(0.03)
    assert resp["converged"] is True
    assert resp["warnings"] == ["適用ガード: 低角反射不足"]
    # build_mem_input で MEMInput が組まれ backend.run へ渡っている
    assert len(backend.calls) == 1


def test_mem_backend_delegation_defaults_to_first_verified():
    # 【テスト目的】: hypothesis_id 未指定なら verified 先頭を対象にする
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=_verification("H1"))
    resp = mem_module.run_mem_boundary(session, mem_backend=backend)
    assert resp["status"] == "ok"
    assert resp["hypothesis_id"] == "H1"


def test_run_mem_tool_passes_backend_through_params():
    # 【テスト目的】: run_mem(session, **params) が mem_backend を透過して委譲する
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=_verification("H1"))
    resp = run_mem(session, mem_backend=backend, hypothesis_id="H1")
    assert resp["status"] == "ok"
    assert resp["hypothesis_id"] == "H1"


# ===========================================================================
# TC-511-04: JSON 安全 — 非有限値は finite_or_none で None 化し json.dumps(allow_nan=False) 安全
# ===========================================================================


def test_non_finite_densities_are_nulled_and_json_safe():
    # 【テスト目的】: min_density=inf / r_factor=nan 等を含んでも finite_or_none で None 化される
    result = MEMResult(
        density_map=MEMDensityMap(
            path="/tmp/d.grd",
            density_kind="nuclear",
            grid_shape=(32, 32, 32),
            min_density=math.inf,
            max_density=math.nan,
        ),
        bond_paths=(
            BondPathDensity(
                start_site="K1", end_site="K2", min_density=-math.inf, path_length=math.nan
            ),
        ),
        r_factor=math.nan,
        converged=False,
        warnings=("非収束",),
    )
    backend = _StubMEMBackend(result)
    session = _session(verification=_verification("H1"))
    resp = mem_module.run_mem_boundary(session, mem_backend=backend, hypothesis_id="H1")

    assert resp["density_map"]["min_density"] is None
    assert resp["density_map"]["max_density"] is None
    assert resp["bond_paths"][0]["min_density"] is None
    assert resp["bond_paths"][0]["path_length"] is None
    assert resp["r_factor"] is None
    # json.dumps(allow_nan=False) がクラッシュしない
    json.dumps(resp, allow_nan=False)


# ===========================================================================
# TC-511-03: 未導入変換 — run が MEMUnavailableError を投げると error dict へ変換
# ===========================================================================


def test_unavailable_backend_converts_to_error_dict():
    # 【テスト目的】: mem_backend.run が MEMUnavailableError を投げたら error dict へ変換 (非クラッシュ)
    backend = _UnavailableMEMBackend()
    session = _session(verification=_verification("H1"))
    resp = mem_module.run_mem_boundary(session, mem_backend=backend, hypothesis_id="H1")
    assert resp == {"status": "error", "error": "mem_unavailable"}
    json.dumps(resp, allow_nan=False)


# ===========================================================================
# 縮退 — verification 不在・未知 hypothesis_id は素直な error dict (非クラッシュ)
# ===========================================================================


def test_no_verification_returns_error_dict():
    # 【テスト目的】: verification が None かつ mem_backend 供給の縮退は error dict
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=None)
    resp = mem_module.run_mem_boundary(session, mem_backend=backend, hypothesis_id="H1")
    assert resp == {"status": "error", "error": "no_verification"}


def test_unknown_hypothesis_id_returns_error_dict():
    # 【テスト目的】: 未知 hypothesis_id は error dict へ変換
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=_verification("H1"))
    resp = mem_module.run_mem_boundary(session, mem_backend=backend, hypothesis_id="UNKNOWN")
    assert resp == {"status": "error", "error": "unknown_hypothesis"}


# ===========================================================================
# TC-511-02: 破壊操作なし — ledger.verify() True・件数不変・削除/上書きなし
# ===========================================================================


def test_non_numeric_hist_index_does_not_crash():
    # LOW-6: hist_index="foo" (非数値) で素の ValueError クラッシュせず既定 (0) 縮退で ok を返す
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=_verification("H1"))
    resp = mem_module.run_mem_boundary(
        session, mem_backend=backend, hypothesis_id="H1", hist_index="foo"
    )
    # 縮退して正常応答 (他の error dict 経路と非対称なクラッシュを起こさない)。
    assert resp["status"] == "ok"
    assert resp["hypothesis_id"] == "H1"
    json.dumps(resp, allow_nan=False)


def test_non_numeric_hist_index_none_does_not_crash():
    # LOW-6: hist_index=None も既定 0 へ縮退 (int(None) の TypeError を捕捉)
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=_verification("H1"))
    resp = mem_module.run_mem_boundary(
        session, mem_backend=backend, hypothesis_id="H1", hist_index=None
    )
    assert resp["status"] == "ok"


def test_mem_run_is_non_destructive():
    # 【テスト目的】: run_mem 前後で ledger 件数不変・verify() True (子スナップショット追記のみ許容)
    backend = _StubMEMBackend(_mem_result())
    session = _session(verification=_verification("H1"))
    n_before = len(session.ledger.entries)
    mem_module.run_mem_boundary(session, mem_backend=backend, hypothesis_id="H1")
    # 破壊的追記なし (件数不変) かつ ハッシュチェーン整合
    assert len(session.ledger.entries) == n_before
    assert session.ledger.verify() is True


def test_mem_source_has_no_destructive_calls():
    # 【テスト目的】: mem.py 実装が破壊系メソッドを呼ばない (走査)
    import inspect

    source = inspect.getsource(mem_module)
    for pattern in (".delete(", ".remove(", ".overwrite(", ".pop(", ".truncate(", ".clear("):
        assert pattern not in source, pattern
