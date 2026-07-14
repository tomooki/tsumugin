from __future__ import annotations

import dataclasses
import math

import pytest
from dataclasses import FrozenInstanceError

from tsumugin.errors import TsumuginError, GuardrailError, EscalationRequired
from tsumugin.model import (
    Dataset,
    Frame,
    HistogramRef,
    Hypothesis,
    LatticeParams,
    PhaseInstance,
    PhaseRef,
    Project,
    RefinementMetrics,
    TofBankParams,
)


def test_cubic_volume():
    lat = LatticeParams(a=5.0, b=5.0, c=5.0)
    assert lat.volume() == pytest.approx(125.0)


def test_lattice_sigma_source_defaults_empty_and_with_updates_compatible():
    # 【テスト目的】: LatticeParams.sigma_source が既定 "" で、with_updates 相当 (dataclasses.replace)
    #   と互換に更新できることを確認 (Issue #66 / FR-306 / NFR-107)。
    lat = LatticeParams(a=5.0, b=5.0, c=5.0)
    assert lat.sigma_source == ""  # 【確認内容】: 未提供は空文字既定 🔵
    updated = dataclasses.replace(lat, sigma={"a": 0.01}, sigma_source="covariance")
    assert updated.sigma_source == "covariance"  # 【確認内容】: 非破壊更新で由来を設定できる 🔵
    assert lat.sigma_source == ""  # 【確認内容】: 元インスタンスは不変 (P2) 🔵


def test_triclinic_volume_matches_general_formula():
    a, b, c = 4.0, 5.0, 6.0
    alpha, beta, gamma = 80.0, 85.0, 95.0
    lat = LatticeParams(a=a, b=b, c=c, alpha=alpha, beta=beta, gamma=gamma)
    ca, cb, cg = (math.cos(math.radians(x)) for x in (alpha, beta, gamma))
    expected = a * b * c * math.sqrt(
        1 - ca**2 - cb**2 - cg**2 + 2 * ca * cb * cg
    )
    assert lat.volume() == pytest.approx(expected)


def test_phase_with_updates_is_nondestructive():
    p = PhaseInstance(phase_ref="Fe2O3", lattice=LatticeParams(5, 5, 5), scale=1.0)
    p2 = p.with_updates(scale=2.0)
    assert p2.scale == 2.0
    assert p.scale == 1.0  # original unchanged (P2)
    assert p2.phase_ref == "Fe2O3"


def test_frozen_assignment_raises():
    p = PhaseInstance(phase_ref="x", lattice=LatticeParams(5, 5, 5), scale=1.0)
    with pytest.raises(FrozenInstanceError):
        p.scale = 3.0  # type: ignore[misc]


def test_defaults():
    h = Hypothesis(id="h1", phases=())
    assert h.status == "candidate"
    proj = Project(id="p1")
    assert proj.final_selection_mode == "agent"


def test_exception_hierarchy():
    assert issubclass(GuardrailError, TsumuginError)
    assert issubclass(EscalationRequired, TsumuginError)


def test_metrics_and_containers_construct():
    m = RefinementMetrics(rwp=5.0, gof=1.2, chi2=100.0, n_obs=1000, n_params=5)
    assert m.evidence == {}
    hist = HistogramRef(probe="xray", data_ref="d.xy")
    frame = Frame(id="f0", index=0, histograms=(hist,))
    ds = Dataset(id="ds0", kind="single", frames=(frame,))
    proj = Project(id="p", datasets=(ds,))
    assert proj.datasets[0].frames[0].histograms[0].probe == "xray"


# ---------------------------------------------------------------------------
# TASK-0036: TofBankParams + HistogramRef.bank_params (M4 joint / FR-241)
# ---------------------------------------------------------------------------


def test_neutron_probes_coexist_with_xray():
    # 【TC-401-01】: probe="neutron_cw"/"neutron_tof" が生成でき既存 xray と共存する 🔵
    xray = HistogramRef(probe="xray", data_ref="x.xy")
    cw = HistogramRef(probe="neutron_cw", data_ref="cw.dat")
    tof = HistogramRef(probe="neutron_tof", data_ref="tof.dat")
    assert xray.probe == "xray"
    assert cw.probe == "neutron_cw"
    assert tof.probe == "neutron_tof"


def test_tof_bank_params_frozen_and_defaults():
    # 【TC-401-02】: TofBankParams(difc/difa/zero) が frozen dataclass で生成でき既定 difa=0.0/zero=0.0 🔵
    p = TofBankParams(difc=5000.0)
    assert p.difc == 5000.0
    assert p.difa == 0.0
    assert p.zero == 0.0
    full = TofBankParams(difc=5000.0, difa=1.5, zero=-3.0)
    assert (full.difc, full.difa, full.zero) == (5000.0, 1.5, -3.0)
    with pytest.raises(FrozenInstanceError):
        p.difc = 1.0  # type: ignore[misc]


def test_histogram_ref_bank_params_default_none_nondestructive():
    # 【TC-401-02】: bank_params が末尾・既定 None で非破壊追加され既存フィールドが不変 (後方互換) 🔵
    # 【後方互換】: 既存の位置引数呼び出しは不変 (probe/data_ref/instprm_ref/bank_id)
    h = HistogramRef(probe="xray", data_ref="x.xy")
    assert h.bank_params is None
    assert h.instprm_ref is None
    assert h.bank_id is None
    bp = TofBankParams(difc=5000.0)
    h2 = HistogramRef(
        probe="neutron_tof", data_ref="tof.dat", instprm_ref="i.prm", bank_id=1, bank_params=bp
    )
    assert h2.bank_params is bp
    assert h2.bank_id == 1


def test_frame_holds_xray_and_multi_bank_neutron_histograms():
    # 【TC-401-03】: 1 Frame に X線 + 中性子 (+複数バンク) の複数 HistogramRef を保持できる 🔵
    hists = (
        HistogramRef(probe="xray", data_ref="x.xy"),
        HistogramRef(probe="neutron_cw", data_ref="cw.dat"),
        HistogramRef(
            probe="neutron_tof",
            data_ref="tof.dat",
            bank_id=1,
            bank_params=TofBankParams(difc=5000.0),
        ),
        HistogramRef(
            probe="neutron_tof",
            data_ref="tof.dat",
            bank_id=2,
            bank_params=TofBankParams(difc=7000.0, difa=2.0, zero=-1.0),
        ),
    )
    frame = Frame(id="f0", index=0, histograms=hists)
    probes = [h.probe for h in frame.histograms]
    assert probes == ["xray", "neutron_cw", "neutron_tof", "neutron_tof"]
    banks = [h.bank_id for h in frame.histograms if h.probe == "neutron_tof"]
    assert banks == [1, 2]


# ---------------------------------------------------------------------------
# TASK-0037: PhaseRef (相 ID + 組成/元素系ヒント) + 疎結合橋渡し (M4 joint / REQ-020)
# ---------------------------------------------------------------------------


def test_phase_ref_construct_and_defaults():
    # 【TC-406-07】: PhaseRef(id/formula/element_system) が生成でき既定 formula=None/element_system=() 🔵
    ref = PhaseRef(id="LiFePO4")
    assert ref.id == "LiFePO4"
    assert ref.formula is None
    assert ref.element_system == ()
    full = PhaseRef(id="LiFePO4", formula="LiFePO4", element_system=("Fe", "Li", "O", "P"))
    assert full.formula == "LiFePO4"
    assert full.element_system == ("Fe", "Li", "O", "P")


def test_phase_ref_frozen():
    # 【TC-406-07】: PhaseRef は frozen dataclass で属性再代入不可 🔵
    ref = PhaseRef(id="Fe2O3")
    with pytest.raises(FrozenInstanceError):
        ref.id = "Fe3O4"  # type: ignore[misc]


def test_phase_ref_id_matches_phase_instance_phase_ref():
    # 【TC-406-07】: PhaseRef.id を PhaseInstance.phase_ref と一致させ id 整合できる 🔵 REQ-020
    inst = PhaseInstance(phase_ref="Fe2O3", lattice=LatticeParams(5, 5, 5))
    ref = PhaseRef(id=inst.phase_ref, formula="Fe2O3")
    assert ref.id == inst.phase_ref


def test_phase_ref_from_phase_ref_bridges_str():
    # 【REQ-020】: from_phase_ref(str, ...) が既存 str phase_ref から PhaseRef を橋渡し生成する 🔵
    inst = PhaseInstance(phase_ref="LiFePO4", lattice=LatticeParams(5, 5, 5))
    ref = PhaseRef.from_phase_ref(inst.phase_ref)
    assert isinstance(ref, PhaseRef)
    assert ref.id == "LiFePO4"
    assert ref.formula is None
    assert ref.element_system == ()
    enriched = PhaseRef.from_phase_ref(
        inst.phase_ref, formula="LiFePO4", element_system=("Fe", "Li", "O", "P")
    )
    assert enriched.id == "LiFePO4"
    assert enriched.formula == "LiFePO4"
    assert enriched.element_system == ("Fe", "Li", "O", "P")


def test_phase_instance_has_no_phase_ref_object_field():
    # 【TC-406-07 / D6】: PhaseInstance は疎結合。phase_ref は str のまま、PhaseRef フィールドを持たない 🔵
    inst = PhaseInstance(phase_ref="Fe2O3", lattice=LatticeParams(5, 5, 5))
    assert isinstance(inst.phase_ref, str)
    field_names = {f.name for f in dataclasses.fields(inst)}
    assert "phase_ref" in field_names
    # PhaseRef 型のフィールドが PhaseInstance に混入していないこと (疎結合の別値オブジェクト)
    assert not any(isinstance(getattr(inst, name), PhaseRef) for name in field_names)


# ---------------------------------------------------------------------------
# TASK-0037: MCPUnavailableError / MEMUnavailableError (TsumuginError 派生)
# ---------------------------------------------------------------------------


def test_mcp_unavailable_error_hierarchy_and_raise():
    # 【TC-407-07】: MCPUnavailableError が TsumuginError 派生で raise/except できる 🔵 REQ-102
    from tsumugin.errors import MCPUnavailableError

    assert issubclass(MCPUnavailableError, TsumuginError)
    with pytest.raises(TsumuginError):
        raise MCPUnavailableError("mcp extra 未導入")
    with pytest.raises(MCPUnavailableError):
        raise MCPUnavailableError("mcp extra 未導入")


def test_mem_unavailable_error_hierarchy_and_raise():
    # 【TC-407-08】: MEMUnavailableError が TsumuginError 派生で raise/except できる 🔵 REQ-101
    from tsumugin.errors import MEMUnavailableError

    assert issubclass(MEMUnavailableError, TsumuginError)
    with pytest.raises(TsumuginError):
        raise MEMUnavailableError("MEM は M5 で提供予定")
    with pytest.raises(MEMUnavailableError):
        raise MEMUnavailableError("MEM は M5 で提供予定")
