"""TASK-0040 joint/contrast の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/joint/contrast.py``:
    - ``NEUTRON_B_TABLE: Mapping[str, float]`` — 元素→中性子コヒーレント散乱長 b [fm]
    - ``XRAY_Z_TABLE: Mapping[str, int]`` — 元素→原子番号 Z (X 線散乱因子近似)
    - ``OccupancyReleaseRecommendation`` frozen dataclass
    - ``ContrastConfig`` frozen dataclass (contrast_threshold=0.15 + site_elements)
    - ``recommend_occupancy_release(phases, model, *, config, ledger=None) -> tuple[...]``
- ``src/tsumugin/joint/__init__.py``: 上記シンボルの re-export (__all__ 昇順)

契約は ``docs/design/m4-joint-mcp/interfaces.py`` の joint/contrast 節に依拠。
完了条件 7 項目 (TC-404-01〜06 / REQ-402/403) に 1:1 対応する。

【設計判断 (PhaseInstance のサイト表現)】:
``PhaseInstance.occupancies`` は ``Mapping[str, float]`` (site→占有率スカラ) で、
混合サイトの占有元素対 (A,B) を表現できない。既存モデルを壊さず契約
(``elements: tuple[str, str]``) を満たすため、site→(elemA, elemB) は
``ContrastConfig.site_elements`` で供給する。相 (model.phases) は phase_index 反復と
joint 条件判定 (ヒスト数・probe 種別) に用いる。
"""

from __future__ import annotations

import numpy as np

from tsumugin.joint import (
    NEUTRON_B_TABLE,
    XRAY_Z_TABLE,
    ContrastConfig,
    JointHistogram,
    JointRefinementModel,
    OccupancyReleaseRecommendation,
    recommend_occupancy_release,
)
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.store.ledger import Ledger

# ---------------------------------------------------------------------------
# ヘルパ
# ---------------------------------------------------------------------------


def _phase(ref: str = "P", occ: dict[str, float] | None = None) -> PhaseInstance:
    return PhaseInstance(
        phase_ref=ref,
        lattice=LatticeParams(5.0, 5.0, 5.0),
        occupancies=occ or {},
    )


def _hist(probe: str) -> JointHistogram:
    grid = np.arange(15.0, 80.0, 0.5)
    return JointHistogram(two_theta=grid, intensity=np.ones_like(grid), probe=probe)


def _joint_model(probes: tuple[str, ...], phases: tuple[PhaseInstance, ...]) -> JointRefinementModel:
    return JointRefinementModel(
        phases=phases,
        histograms=tuple(_hist(p) for p in probes),
    )


# ---------------------------------------------------------------------------
# TC-404-01: |f_norm - b_norm| > 閾値のサイト検出 (b 静的テーブル参照)
# ---------------------------------------------------------------------------


def test_high_contrast_site_detected():
    # Ni/Fe: Z=28/26 (X 線類似) だが b=10.3/9.45 fm。ここでは Mn を使い中性子で大差を作る。
    # Fe(Z=26, b=9.45) / Mn(Z=25, b=-3.73): X 線ほぼ同一・中性子で符号違い → 高コントラスト。
    phase = _phase(occ={"M": 1.0})
    model = _joint_model(("xray", "neutron_cw"), (phase,))
    config = ContrastConfig(site_elements={"M": ("Fe", "Mn")})

    recs = recommend_occupancy_release((phase,), model, config=config)

    assert len(recs) == 1
    rec = recs[0]
    assert isinstance(rec, OccupancyReleaseRecommendation)
    assert rec.phase_index == 0
    assert rec.site == "M"
    assert rec.elements == ("Fe", "Mn")  # 記号昇順
    # 手計算で contrast を再現し、テーブル参照を検証する。
    z_fe, z_mn = XRAY_Z_TABLE["Fe"], XRAY_Z_TABLE["Mn"]
    b_fe, b_mn = NEUTRON_B_TABLE["Fe"], NEUTRON_B_TABLE["Mn"]
    f_norm = z_fe / (z_fe + z_mn)
    b_norm = b_fe / (abs(b_fe) + abs(b_mn))
    expected = abs(f_norm - b_norm)
    assert rec.contrast == expected
    assert expected >= config.contrast_threshold


# ---------------------------------------------------------------------------
# TC-404-02: joint (ヒスト≥2 かつ probe種≥2) のときのみ提案
# ---------------------------------------------------------------------------


def test_recommend_only_when_joint():
    phase = _phase(occ={"M": 1.0})
    config = ContrastConfig(site_elements={"M": ("Fe", "Mn")})

    # 2 ヒストだが両方 xray (probe 種 1) → 空
    same_probe = _joint_model(("xray", "xray"), (phase,))
    assert recommend_occupancy_release((phase,), same_probe, config=config) == ()

    # 2 ヒスト + probe 種 2 → 提案
    joint = _joint_model(("xray", "neutron_cw"), (phase,))
    assert len(recommend_occupancy_release((phase,), joint, config=config)) == 1


# ---------------------------------------------------------------------------
# TC-404-03 / EDGE-004: 単一ヒストで空
# ---------------------------------------------------------------------------


def test_single_histogram_empty():
    phase = _phase(occ={"M": 1.0})
    config = ContrastConfig(site_elements={"M": ("Fe", "Mn")})
    single = _joint_model(("xray",), (phase,))
    assert recommend_occupancy_release((phase,), single, config=config) == ()


# ---------------------------------------------------------------------------
# TC-404-04 / EDGE-003: 全サイト閾値未満で空・無警告
# ---------------------------------------------------------------------------


def test_low_contrast_all_below_threshold_empty():
    # Co(Z=27, b=2.49) / Ni(Z=28, b=10.3): X 線ほぼ同一。ここでは高い閾値で全滅させる。
    phase = _phase(occ={"M": 1.0})
    model = _joint_model(("xray", "neutron_cw"), (phase,))
    config = ContrastConfig(site_elements={"M": ("Fe", "Mn")}, contrast_threshold=0.99)
    assert recommend_occupancy_release((phase,), model, config=config) == ()


# ---------------------------------------------------------------------------
# TC-404-05 / REQ-012: ledger 記録 + verify() True
# ---------------------------------------------------------------------------


def test_recommendation_recorded_in_ledger():
    phase = _phase(occ={"M": 1.0})
    model = _joint_model(("xray", "neutron_cw"), (phase,))
    config = ContrastConfig(site_elements={"M": ("Fe", "Mn")})
    ledger = Ledger()

    recs = recommend_occupancy_release((phase,), model, config=config, ledger=ledger)

    assert len(recs) == 1
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert "contrast_occupancy_recommend" in kinds
    entry = next(e for e in ledger.entries if e.kind == "contrast_occupancy_recommend")
    assert entry.payload["phase_index"] == 0
    assert entry.payload["site"] == "M"
    assert list(entry.payload["elements"]) == ["Fe", "Mn"]
    assert "rationale" in entry.payload
    assert entry.payload["rationale"]  # 非空
    # 閾値未満なら記録も 0 件のまま verify() True。
    empty_ledger = Ledger()
    low = ContrastConfig(site_elements={"M": ("Fe", "Mn")}, contrast_threshold=0.99)
    recommend_occupancy_release((phase,), model, config=low, ledger=empty_ledger)
    assert empty_ledger.verify() is True
    assert all(e.kind != "contrast_occupancy_recommend" for e in empty_ledger.entries)


# ---------------------------------------------------------------------------
# TC-404-06 / REQ-011: 提案のみ・phases 不変 (自動解放しない)
# ---------------------------------------------------------------------------


def test_recommendation_does_not_mutate_phases():
    phase = _phase(occ={"M": 1.0})
    phases = (phase,)
    model = _joint_model(("xray", "neutron_cw"), phases)
    config = ContrastConfig(site_elements={"M": ("Fe", "Mn")})

    recs = recommend_occupancy_release(phases, model, config=config)

    assert len(recs) == 1
    # phases タプル・相・占有率は一切書き換わらない (自動解放しない)。
    assert phases[0] is phase
    assert phase.occupancies == {"M": 1.0}
    # param_name は解放候補名を「提案」するのみ。
    assert recs[0].param_name == "global.occ.M"


# ---------------------------------------------------------------------------
# REQ-402: 決定論 (元素昇順・サイトキー昇順) + ビット同一
# ---------------------------------------------------------------------------


def test_deterministic_element_and_site_order():
    # 元素を降順で渡しても (A,B) は記号昇順へ正規化される。
    phase = _phase(occ={"M": 1.0})
    model = _joint_model(("xray", "neutron_cw"), (phase,))
    config = ContrastConfig(site_elements={"M": ("Mn", "Fe")})  # 逆順入力

    recs = recommend_occupancy_release((phase,), model, config=config)
    assert recs[0].elements == ("Fe", "Mn")


def test_deterministic_multiple_sites_sorted():
    # 複数サイトは占有率キー昇順で評価・列挙される。
    phase = _phase(occ={"B": 1.0, "A": 1.0})
    model = _joint_model(("xray", "neutron_cw"), (phase,))
    config = ContrastConfig(
        site_elements={"A": ("Fe", "Mn"), "B": ("Fe", "Mn")},
    )
    recs = recommend_occupancy_release((phase,), model, config=config)
    assert [r.site for r in recs] == ["A", "B"]  # サイトキー昇順


def test_bitwise_identical_across_runs():
    phase = _phase(occ={"M": 1.0})
    model = _joint_model(("xray", "neutron_cw"), (phase,))
    config = ContrastConfig(site_elements={"M": ("Fe", "Mn")})

    r1 = recommend_occupancy_release((phase,), model, config=config)
    r2 = recommend_occupancy_release((phase,), model, config=config)
    assert r1 == r2


def test_core_imports_numpy_only():
    # コアモジュールが numpy 以外の重依存を import しないことを確認 (REQ-403)。
    import ast
    import pathlib

    src = pathlib.Path("src/tsumugin/joint/contrast.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imported_roots.add(node.module.split(".")[0])
    forbidden = {"xraylib", "scipy", "pandas"}
    assert not (imported_roots & forbidden)


# ---------------------------------------------------------------------------
# F8: 散乱長/Z テーブルのキー乖離を固定する回帰テスト
# ---------------------------------------------------------------------------


def test_neutron_b_and_xray_z_tables_have_identical_keys():
    # 【F8】: _contrast は両テーブルを参照する。キー集合が一致していることを不変条件として固定
    #   (片方のみ収録の元素があると _both_tables_have で片側 skip され契約が乖離するため)。
    assert set(NEUTRON_B_TABLE.keys()) == set(XRAY_Z_TABLE.keys())


def test_recommend_skips_site_when_element_missing_from_a_table():
    # 【F8】: 片方のテーブルにしか無い元素対のサイトは KeyError を出さず skip される。
    #   XRAY_Z_TABLE には有るが NEUTRON_B_TABLE には無い擬似元素を site_elements に与える。
    from tsumugin.joint import contrast as contrast_mod

    # 実在キー "Fe" と、Z にだけ存在させた擬似元素 "Xx" の対を作る。
    original_z = dict(XRAY_Z_TABLE)
    patched_z = dict(original_z)
    patched_z["Xx"] = 99  # b テーブルには追加しない → 片側欠損
    contrast_mod.XRAY_Z_TABLE = patched_z  # type: ignore[assignment]
    try:
        phase = _phase(occ={"M": 1.0})
        model = _joint_model(("xray", "neutron_cw"), (phase,))
        config = ContrastConfig(site_elements={"M": ("Fe", "Xx")})
        # KeyError を送出せず空推奨 (当該サイト skip) になること。
        recs = recommend_occupancy_release((phase,), model, config=config)
        assert recs == ()
    finally:
        contrast_mod.XRAY_Z_TABLE = original_z  # type: ignore[assignment]
