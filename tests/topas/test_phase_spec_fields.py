"""TOPAS 経路が `PhaseSpec` の相の指定を**黙って無視しない**こと。

以前の TOPAS バックエンドは `refine_cell` / `frozen_coord_labels` / `free_uiso_labels` /
`frozen_uiso_labels` / `occupancy_equiv_groups` / `position_equiv_groups` を一度も参照せず、
`backend="topas"` で渡すと**何もせずに完走していた** (#47 の副相格子凍結も #209 の幽霊相対策の
Uiso 凍結も効かない)。`occupancy_sum_groups` は参照されていたが **GSAS と別の意味**
(「親 = Σ子」ではなく混合占有の「和 = 1」) で張られていた。

ここでは各フィールドを **GSAS 経路と同じ意味で INP に写す**こと、意味を決められない指定は
`InvalidPhaseSpecError` で**精密化の前に**止めることを固定する。実 tc.exe が INP を受理して
その通りに精密化することは末尾の `@pytest.mark.topas` で見る。
"""

from __future__ import annotations

import math
import re
from dataclasses import fields
from pathlib import Path

import pytest

from tsumugin.autorietveld.cif_normalize import Atom, Structure
from tsumugin.autorietveld.model import (
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
)
from tsumugin.errors import InvalidPhaseSpecError
from tsumugin.topas.flags import apply_stage
from tsumugin.topas.inp import TopasDocument, TopasHistogram, TopasPhase
from tsumugin.topas.structure import PHASE_SPEC_FIELDS, structure_to_topas_phase

#: Pnma の一般位置の一部 (鏡面 y=1/4 を作るのに足りる)。`free_coord_axes` の判定に要る。
_SYMOPS = ("x,y,z", "x,1/2-y,z", "-x,-y,-z", "-x,1/2+y,-z")


def _structure(*atoms: Atom) -> Structure:
    return Structure(
        a=8.48, b=5.40, c=6.96, alpha=90.0, beta=90.0, gamma=90.0,
        spacegroup_hm="P n m a", it_number=62,
        atoms=atoms or (
            Atom("Pb", "Pb", 0.188, 0.25, 0.167, 1.0, 0.010),  # 鏡面上: x,z だけ自由
            Atom("S", "S", 0.063, 0.25, 0.686, 1.0, 0.010),
            Atom("O1", "O", 0.095, 0.026, 0.806, 1.0, 0.010),  # 一般位置: x,y,z 自由
            Atom("O2", "O", 0.181, 0.25, 0.543, 1.0, 0.010),
        ),
        symops=_SYMOPS,
    )


def _phase(spec_kw: "dict | None" = None, *, structure: "Structure | None" = None,
           name: str = "P"):
    spec = PhaseSpec(structure_path="x.cif", phase_name=name, **(spec_kw or {}))
    return structure_to_topas_phase(structure or _structure(), name, spec=spec)


def _doc(*phases, histograms: int = 1) -> TopasDocument:
    return TopasDocument(
        histograms=tuple(TopasHistogram(data_path=f"d{i}.xye") for i in range(histograms)),
        phases=tuple(phases),
        results_path="results.txt",
    )


def _stage(doc: TopasDocument, **flags) -> TopasDocument:
    return apply_stage(doc, RefinementStage(label="S", flags=flags))


def _site(phase, label):
    return next(s for s in phase.sites if s.label == label)


# ---------------- refine_cell (#47) ----------------


def test_refine_cell_false_keeps_that_phase_lattice_fixed_through_the_cell_stage():
    """副相の格子を凍結しても、**主相の格子は解放される** (#47: 巻き添えにしない)。"""
    main = _phase(name="main")
    minor = _phase({"refine_cell": False}, name="minor")
    out = _stage(_doc(main, minor), cell=True)
    assert any(p.refine for p in out.phases[0].cell.values())
    assert not any(p.refine for p in out.phases[1].cell.values())
    text = out.render()
    assert re.search(r"\n\s+a !minor_a 8\.48\n", text), "凍結した格子は `!` 付きで書かれる"
    assert re.search(r"\n\s+a main_a 8\.48\n", text)


def test_refine_cell_default_is_unchanged():
    out = _stage(_doc(_phase()), cell=True)
    assert all(out.phases[0].cell[k].refine for k in ("a", "b", "c"))


# ---------------- frozen_coord_labels ----------------


def test_frozen_coord_labels_are_not_released_by_the_coords_stage():
    out = _stage(_doc(_phase({"frozen_coord_labels": ("O1",)})), coords=True)
    phase = out.phases[0]
    o1 = _site(phase, "O1")
    assert not (o1.x.refine or o1.y.refine or o1.z.refine), "凍結した原子が解放された"
    pb = _site(phase, "Pb")
    assert pb.x.refine and pb.z.refine and not pb.y.refine, "凍結していない原子は従来どおり"


# ---------------- free_uiso_labels / frozen_uiso_labels (#189/#211) ----------------


@pytest.mark.parametrize(
    ("spec_kw", "released"),
    [
        ({}, {"Pb", "S", "O1", "O2"}),  # None = 未指定 → 全原子
        ({"free_uiso_labels": ()}, set()),  # () = 明示的に凍結 → 0 原子
        ({"free_uiso_labels": ("Pb", "O1")}, {"Pb", "O1"}),
        ({"frozen_uiso_labels": ("Pb",)}, {"S", "O1", "O2"}),
        # 両方に現れたら**凍結が勝つ** (GSAS `_resolve_uiso_targets` と同じ規約)
        ({"free_uiso_labels": ("Pb", "O1"), "frozen_uiso_labels": ("Pb",)}, {"O1"}),
    ],
)
def test_uiso_stage_releases_exactly_the_resolved_labels(spec_kw, released):
    out = _stage(_doc(_phase(spec_kw)), uiso=True)
    assert {s.label for s in out.phases[0].sites if s.beq.refine} == released


def test_empty_free_uiso_labels_is_not_read_as_unspecified():
    """**#189 の本体**: ``()`` を ``or`` で「未指定」に化けさせると、凍結したつもりで全原子が
    解放される。TOPAS 側も型 (None と ()) で区別していること。"""
    out = _stage(_doc(_phase({"free_uiso_labels": ()})), uiso=True)
    assert "beq !" in out.render()
    assert not any(s.beq.refine for s in out.phases[0].sites)


def _mixed_structure() -> Structure:
    return _structure(
        Atom("Fe1", "Fe", 0.0, 0.0, 0.0, 0.5, 0.010),
        Atom("Al1", "Al", 0.0, 0.0, 0.0, 0.5, 0.010),
        Atom("O1", "O", 0.095, 0.026, 0.806, 1.0, 0.010),
    )


def test_mixed_site_beq_group_follows_the_uiso_labels():
    """混合占有サイトの beq は**1 変数** (等値拘束)。組ごと凍結すれば共有 prm も固定のまま。"""
    frozen = _phase({"mixed_occupancy_groups": (("Fe1", "Al1"),),
                     "frozen_uiso_labels": ("Fe1", "Al1")}, structure=_mixed_structure())
    text = _stage(_doc(frozen), uiso=True).render()
    assert "prm !P_beq_g0 " in text, "凍結した組の共有 beq が解放された"
    released = _phase({"mixed_occupancy_groups": (("Fe1", "Al1"),)}, structure=_mixed_structure())
    assert "prm P_beq_g0 " in _stage(_doc(released), uiso=True).render()


def test_freezing_only_part_of_a_mixed_site_beq_is_refused():
    """組の一部だけ凍結は**意味が決まらない** (1 変数なので片方だけ動かせない)。黙ってどちらかに
    倒さず、精密化の前に止める。"""
    with pytest.raises(InvalidPhaseSpecError, match="Fe1"):
        _phase({"mixed_occupancy_groups": (("Fe1", "Al1"),), "free_uiso_labels": ("Fe1", "O1")},
               structure=_mixed_structure())


# ---------------- occupancy_equiv_groups ----------------


def test_occupancy_equiv_group_is_one_shared_occupancy():
    """組の全員が 1 変数。**[0,1] を張らない** — GSAS は等値・和の組に範囲拘束を張らない
    (`_update_atom_flags`) ので、張ると最適が 1 を超えるとき (= モデルの誤りの信号) に
    TOPAS だけが 1 に張り付き、エンジン間の照合が食い違う。"""
    phase = _phase({"occupancy_equiv_groups": (("O1", "O2"),)})
    text = _doc(phase).render()
    assert "prm !P_occeq_g0 1.0\n" in text
    assert text.count("occ O =P_occeq_g0;") == 2
    released = _stage(_doc(phase), occupancy=True).render()
    assert "prm P_occeq_g0 1.0\n" in released


# ---------------- occupancy_sum_groups: 親 = Σ子 (GSAS と同じ意味) ----------------


def test_occupancy_sum_group_makes_the_parent_the_sum_of_its_children():
    """GSAS は ``(親, 子1, 子2, …)`` に **Σ子 − 親 = 0** を張る (deuterium: D + H = 親水 O)。
    以前の TOPAS は混合占有と同じ「親 = x, 子 = 1-x」(和 = 1) を張っていた — 2 原子なら
    **親 + 子 = 1** で、GSAS の **親 = 子** とは別の構造になる。"""
    structure = _structure(
        Atom("Ow", "O", 0.3, 0.1, 0.2, 0.8, 0.010),
        Atom("D1", "H", 0.35, 0.12, 0.25, 0.5, 0.010),
        Atom("H1", "H", 0.35, 0.12, 0.25, 0.3, 0.010),
    )
    phase = _phase({"occupancy_sum_groups": (("Ow", "D1", "H1"),)}, structure=structure)
    text = _doc(phase).render()
    assert "prm !P_occsum_g0_1 0.5\n" in text  # [0,1] は張らない (GSAS と同じ)
    assert "prm !P_occsum_g0_2 0.3\n" in text
    assert "site Ow " in text and "occ O =P_occsum_g0_1 + P_occsum_g0_2;" in text
    assert "1-" not in text, "混合占有の「和 = 1」で張っている"
    released = _stage(_doc(phase), occupancy=True).render()
    assert "prm P_occsum_g0_1 " in released and "prm P_occsum_g0_2 " in released


def test_recipe_has_an_occupancy_stage_for_equiv_and_sum_groups():
    """拘束を張っても占有率段が無ければ**一度も解放されない** (GSAS 側 recipe と同じ条件)。"""
    from tsumugin.topas.recipe import build_topas_recipe

    hist = HistogramSpec(
        data_path="d.xye", instrument_path="i.prm", radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    for kw in ({"occupancy_equiv_groups": (("O1", "O2"),)},
               {"occupancy_sum_groups": (("Ow", "D1"),)}):
        stages = build_topas_recipe([hist], [PhaseSpec("x.cif", "P", **kw)])
        assert any("occupancy" in s.flags for s in stages), kw


# ---------------- 和の組の親を共有する (deuterium.place_hd_mix の形) ----------------

#: INP の占有率 prm 宣言 (``prm !P_occsum_g0_1 0.7``)。
_OCC_PRM = re.compile(r"^prm (!?)(\w+_occsum_\w+) (\S+)$", re.M)
#: site 行の占有率の式 (``site HO12 … occ H =a + b - c; beq …``)。
_SITE_OCC_EXPR = re.compile(r"^\s*site (\S+) .* occ \S+ =([^;]+);", re.M)


def _occupancy_plan(text: str) -> "tuple[dict[str, tuple[bool, float]], dict[str, str]]":
    """INP から (占有率の共有 prm → (解放か, 初期値), 原子 → 占有率の式) を読む。"""
    prms = {name: (bang == "", float(value)) for bang, name, value in _OCC_PRM.findall(text)}
    return prms, dict(_SITE_OCC_EXPR.findall(text))


_EXPR_TOKEN = re.compile(r"\s*(\w+|[-+()])")


def _evaluate(expr: str, values: "dict[str, float]") -> float:
    """占有率の式 (prm 名と ``+ - ( )`` だけ) を評価する。知らない字面は落とす。"""
    tokens = _EXPR_TOKEN.findall(expr)
    assert "".join(tokens) == expr.replace(" ", ""), f"読めない字面: {expr!r}"
    pos = 0

    def operand() -> float:
        nonlocal pos
        token = tokens[pos]
        pos += 1
        if token != "(":
            return values[token]
        inner = chain()
        assert tokens[pos] == ")", expr
        pos += 1
        return inner

    def chain() -> float:
        nonlocal pos
        total = operand()
        while pos < len(tokens) and tokens[pos] in ("+", "-"):
            sign = tokens[pos]
            pos += 1
            total = total + operand() if sign == "+" else total - operand()
        return total

    result = chain()
    assert pos == len(tokens), f"読み残し: {expr!r}"
    return result


def _gsas_degrees_of_freedom(groups: "tuple[tuple[str, ...], ...]") -> int:
    """GSAS の自由度 = 組に現れる変数の数 − 拘束行列の階数。

    `engine._setup_constraints` は組ごとに ``Σ子 − 親 = 0`` を 1 本張る (係数 1…1, −1)。
    """
    import numpy as np

    labels = sorted({label for group in groups for label in group})
    rows = []
    for group in groups:
        row = [0.0] * len(labels)
        for child in group[1:]:
            row[labels.index(child)] += 1.0
        row[labels.index(group[0])] -= 1.0
        rows.append(row)
    return len(labels) - int(np.linalg.matrix_rank(np.array(rows)))


def _shared_parent_structure() -> Structure:
    """和の組の形を試すための原子 (全員一般位置。値に物理的な意味は無い)。"""
    atoms = [Atom("Ow", "O", 0.30, 0.10, 0.20, 0.9, 0.010),
             Atom("Ox", "O", 0.40, 0.05, 0.60, 0.8, 0.010)]
    for i, label in enumerate(("D1", "H1", "D2", "H2", "D3", "H3", "D4", "H4", "T2")):
        element = "D" if label.startswith("D") else "H"
        atoms.append(Atom(label, element, 0.31 + 0.01 * i, 0.11, 0.22, 0.3, 0.010))
    return _structure(*atoms)


_SUM_SHAPES = {
    # deuterium.place_hd_mix: 親水 O が (O, D1, H1), (O, D2, H2) の 2 組の親になる
    "place_hd_mix": (("Ow", "D1", "H1"), ("Ow", "D2", "H2")),
    "three_groups": (("Ow", "D1", "H1"), ("Ow", "D2", "H2"), ("Ow", "D3", "H3")),
    "later_group_has_one_child": (("Ow", "D1", "H1"), ("Ow", "D2")),
    "first_group_has_one_child": (("Ow", "D1"), ("Ow", "D2", "H2")),
    "later_group_has_three_children": (("Ow", "D1", "H1"), ("Ow", "D2", "H2", "T2")),
    "two_parents_interleaved": (
        ("Ow", "D1", "H1"), ("Ox", "D3", "H3"), ("Ow", "D2", "H2"), ("Ox", "D4", "H4"),
    ),
    "single_group": (("Ow", "D1", "H1"),),
}


@pytest.mark.parametrize("groups", list(_SUM_SHAPES.values()), ids=list(_SUM_SHAPES))
def test_sum_groups_keep_the_gsas_degrees_of_freedom(groups):
    """**自由度が GSAS と同じ** (変数 − 拘束) で、**解放した prm がどんな値でも全ての和が成り立つ**。

    INP は原子ごとに占有率を 1 つの式で書くので、親を共有する 2 つ目の組で親をもう一度
    「Σ子」と書くと**後に書いた方だけが効き、先の組の和が黙って外れる**。最初の組で 親 = Σ子、
    後の組は最後の子を ``親の式 − 他の子`` にする。自由度を数えるだけだと「拘束を 1 本落とした」
    ことは見えても「足りない自由度」と「余った自由度」を取り違えうるので、解放した prm の各方向に
    動かした占有率の階数と、和の恒等的な成立の両方を見る。
    """
    import numpy as np

    phase = _phase({"occupancy_sum_groups": groups}, structure=_shared_parent_structure())
    text = _stage(_doc(phase), occupancy=True).render()
    prms, exprs = _occupancy_plan(text)
    members = sorted({label for group in groups for label in group})
    assert set(members) <= set(exprs), f"式で書かれていない原子: {set(members) - set(exprs)}"
    free = sorted(name for name, (released, _) in prms.items() if released)
    assert len(free) == len(prms), "占有率段で解放されていない和の prm がある"
    assert len(free) == _gsas_degrees_of_freedom(groups)

    # 解放した prm 1 本ずつの方向 → 原子の占有率 (式は線形・定数項なし)。
    jacobian = np.array([
        [_evaluate(exprs[m], {n: float(n == name) for n in prms}) for m in members]
        for name in free
    ])
    assert np.linalg.matrix_rank(jacobian) == len(free), "解放した prm が互いに独立でない"

    rng = np.random.default_rng(0)
    for _ in range(5):
        values = {name: float(rng.uniform(-1.0, 2.0)) for name in prms}
        occ = {m: _evaluate(exprs[m], values) for m in members}
        for group in groups:
            assert occ[group[0]] == pytest.approx(sum(occ[c] for c in group[1:]), abs=1e-12), (
                f"{group}: 親 = Σ子 が成り立たない"
            )


def _hd_mix_phase(synthetic_cif: Path, tmp_path: Path, *, name: str = "P") -> "TopasPhase":
    """合成 CIF の O1 に `place_hd_mix` で D/H 対を 2 組置いた相 (返された組をそのまま渡す)。"""
    from tsumugin.autorietveld.cif_normalize import read_structure_cif
    from tsumugin.autorietveld.deuterium import place_hd_mix

    out, pos_equiv, occ_sum = place_hd_mix(
        synthetic_cif, ["O1"], tmp_path / "hd.cif", deuteration=0.7, phase_name=name
    )
    assert occ_sum == (("O1", "DO11", "HO11"), ("O1", "DO12", "HO12"))
    spec = PhaseSpec(str(out), name, position_equiv_groups=pos_equiv, occupancy_sum_groups=occ_sum)
    return structure_to_topas_phase(read_structure_cif(out), name, spec=spec)


def _site_line(text: str, label: str) -> str:
    return next(line for line in text.splitlines() if line.strip().startswith(f"site {label} "))


def test_place_hd_mix_groups_render_both_sums(synthetic_cif, tmp_path):
    """`place_hd_mix` が返す組を**そのまま**渡したときの INP。以前は「1 原子が 2 つの占有率拘束に
    入っている」として精密化の前に拒否していた (GSAS は両方の和を同時に満たす)。"""
    phase = _hd_mix_phase(synthetic_cif, tmp_path)
    text = _doc(phase).render()
    assert re.search(r"^prm !P_occsum_g0_1 0\.7$", text, re.M)
    assert re.search(r"^prm !P_occsum_g0_2 0\.3", text, re.M)
    assert re.search(r"^prm !P_occsum_g1_1 0\.7$", text, re.M)
    assert "P_occsum_g1_2" not in text, "後の組の最後の子は prm でなく式"
    assert "occ O =P_occsum_g0_1 + P_occsum_g0_2;" in _site_line(text, "O1")
    assert "occ D =P_occsum_g0_1;" in _site_line(text, "DO11")
    assert "occ H =P_occsum_g0_2;" in _site_line(text, "HO11")
    assert "occ D =P_occsum_g1_1;" in _site_line(text, "DO12")
    assert "occ H =P_occsum_g0_1 + P_occsum_g0_2 - P_occsum_g1_1;" in _site_line(text, "HO12")
    # [0,1] は張らない (GSAS も和の組に張らない)。
    assert not re.search(r"^prm \S*occsum.*\bmin\b", text, re.M)


def test_place_hd_mix_groups_publish_every_member_once(synthetic_cif, tmp_path):
    """占有率段では和の組の**全員**の占有率を出版する — 式で書いた子 (HO12) も esd 付きで出る。"""
    text = _stage(_doc(_hd_mix_phase(synthetic_cif, tmp_path)), occupancy=True).render()
    expected = {
        "O1": "P_occsum_g0_1 + P_occsum_g0_2",
        "DO11": "P_occsum_g0_1",
        "HO11": "P_occsum_g0_2",
        "DO12": "P_occsum_g1_1",
        "HO12": "P_occsum_g0_1 + P_occsum_g0_2 - P_occsum_g1_1",
    }
    for label, expr in expected.items():
        assert text.count(f'"occ\\tP\\t{label}\\t') == 1, f"{label} の出版値が 1 回でない"
        assert f'Out({expr}, "occ\\tP\\t{label}\\t' in text


def test_joint_place_hd_mix_groups_are_not_hoisted_per_atom(synthetic_cif, tmp_path):
    """joint は構造を共有 prm へ持ち上げる。和の組の原子を**個別にも**持ち上げると、どこからも
    参照されない占有率 prm が宣言される (解放されれば結果に効かない精密化対象)。各 xdd は
    同じ式を参照し、出版値は先頭の xdd で 1 回だけ。"""
    text = _stage(_doc(_hd_mix_phase(synthetic_cif, tmp_path), histograms=2),
                  occupancy=True).render()
    for label in ("O1", "DO11", "HO11", "DO12", "HO12"):
        assert f"prm P_{label}_occ" not in text and f"prm !P_{label}_occ" not in text, label
    assert text.count("prm P_occsum_g1_1 ") == 1
    blocks = text.split("xdd ")[1:]
    assert len(blocks) == 2
    for block in blocks:
        assert "occ H =P_occsum_g0_1 + P_occsum_g0_2 - P_occsum_g1_1;" in _site_line(block, "HO12")
    assert text.count('"occ\\tP\\tHO12\\t') == 1
    assert '"occ\\tP\\tHO12\\t' in blocks[0]


@pytest.mark.parametrize(
    ("spec_kw", "label"),
    [
        # 同じ原子が 2 つの組の子になる
        ({"occupancy_sum_groups": (("Ow", "D1", "H1"), ("Ox", "D1", "H2"))}, "D1"),
        # ある組の子が別の組の親になる (入れ子)
        ({"occupancy_sum_groups": (("Ow", "D1", "H1"), ("D1", "D2", "H2"))}, "D1"),
        # 和の組の親が等値の組にも入る
        ({"occupancy_sum_groups": (("Ow", "D1", "H1"), ("Ow", "D2", "H2")),
          "occupancy_equiv_groups": (("Ow", "Ox"),)}, "Ow"),
        # 和の組の親が混合占有の組にも入る
        ({"occupancy_sum_groups": (("Ow", "D1", "H1"),),
          "mixed_occupancy_groups": (("Ow", "Ox"),)}, "Ow"),
    ],
    ids=["child_twice", "child_is_a_parent", "parent_also_equiv", "parent_also_mixed"],
)
def test_other_occupancy_overlaps_are_still_refused(spec_kw, label):
    """張れるのは**和の組の親を共有する**形だけ。それ以外の重なりは INP で 1 つの式に
    まとめられない (後に書いた方だけが効く) ので、精密化の前に止める。

    案内は「GSAS で回せ」— 重なりは GSAS では正しい入力でありうる (全拘束を同時に満たす)。
    「1 つの拘束にまとめろ」と案内すると、別のモデルへ書き換えさせることになる。"""
    with pytest.raises(InvalidPhaseSpecError, match=label) as info:
        _phase(spec_kw, structure=_shared_parent_structure())
    message = str(info.value)
    assert "親" in message, "張れる形 (和の組の親の共有) をエラー文が案内していない"
    assert "gsasii" in message, "GSAS では正しいモデルなのに GSAS を案内していない"
    assert "まとめ" not in message, "GSAS では正しいモデルを「まとめろ」と案内している"


def test_inp_builder_refuses_to_write_an_occupancy_twice():
    """`structure_to_topas_phase` を経ずに `TopasPhase` を組む呼び手にも、**1 原子の占有率を
    2 つの式で書く** INP (後に書いた方だけが効く) を黙って書かない。"""
    phase = _phase().with_updates(
        occupancy_equiv_groups=(("O1", "O2"),), occupancy_parent_sum_groups=(("S", "O1"),)
    )
    with pytest.raises(ValueError, match="O1"):
        _doc(phase).render()


def test_inp_builder_refuses_a_sum_group_without_children():
    """子の無い組は親が空の式 (``=;``) になり、tc.exe が拒否する INP になる。"""
    phase = _phase().with_updates(occupancy_parent_sum_groups=(("S",),))
    with pytest.raises(ValueError, match="子"):
        _doc(phase).render()


def test_spec_the_inp_builder_cannot_write_is_refused_before_refinement(monkeypatch):
    """`_resolve_phase_spec` の規則と INP の書き手 (`_group_prm_plan`) がずれても、精密化の前に
    `InvalidPhaseSpecError` で止まる。段の中で止まると rwp=inf → revert に吸われ、全段 revert の
    まま完走する。"""
    from tsumugin.topas import structure as topas_structure

    def cannot_write(phases):
        raise ValueError("書けない拘束 (テスト用)")

    monkeypatch.setattr(topas_structure, "_group_prm_plan", cannot_write)
    with pytest.raises(InvalidPhaseSpecError, match="書けない拘束"):
        _phase({"occupancy_equiv_groups": (("O1", "O2"),)})
    # 相の指定が無い (spec=None) 呼び手は従来どおり検めない。
    structure_to_topas_phase(_structure(), "P")


# ---------------- position_equiv_groups / 混合占有サイトの共位置 ----------------


def _co_located() -> Structure:
    return _structure(
        Atom("D1", "H", 0.35, 0.12, 0.25, 0.5, 0.010),
        Atom("H1", "H", 0.35, 0.12, 0.25, 0.5, 0.010),
        Atom("O1", "O", 0.095, 0.026, 0.806, 1.0, 0.010),
    )


def test_position_equiv_group_moves_its_atoms_together():
    """GSAS は座標の**シフト** (dAx/dAy/dAz) を等値拘束する。共位置の対は 1 組の座標を共有する。"""
    phase = _phase({"position_equiv_groups": (("D1", "H1"),)}, structure=_co_located())
    text = _stage(_doc(phase), coords=True).render()
    for axis in "xyz":
        assert f"prm P_pos_g0_{axis} " in text, f"{axis} の共有座標が解放されていない"
        assert text.count(f"{axis} =P_pos_g0_{axis};") == 2


def test_position_equiv_group_keeps_the_initial_offset():
    """シフトの等値なので、離れた原子は**初期の相対位置を保って**一緒に動く。"""
    structure = _structure(
        Atom("O1", "O", 0.10, 0.03, 0.80, 1.0, 0.010),
        Atom("O3", "O", 0.20, 0.05, 0.70, 1.0, 0.010),
    )
    phase = _phase({"position_equiv_groups": (("O1", "O3"),)}, structure=structure)
    text = _doc(phase).render()
    assert "x =P_pos_g0_x + 0.1;" in text
    assert "z =P_pos_g0_z - 0.1;" in text


def test_mixed_site_atoms_share_their_position_like_gsas():
    """GSAS は混合占有の組に**座標の等値**も張る (`_equiv_positions`)。TOPAS で張らないと
    座標段で同じサイトの 2 原子が別々に動ける。"""
    structure = _structure(
        Atom("Fe1", "Fe", 0.3, 0.1, 0.2, 0.5, 0.010),
        Atom("Al1", "Al", 0.3, 0.1, 0.2, 0.5, 0.010),
    )
    phase = _phase({"mixed_occupancy_groups": (("Fe1", "Al1"),)}, structure=structure)
    text = _stage(_doc(phase), coords=True).render()
    assert text.count("x =P_pos_g0_x;") == 2


def test_joint_does_not_hoist_the_tied_coordinates_separately():
    """joint は構造を共有 prm へ持ち上げる。結束した座標を個別に持ち上げると、**使われない
    解放パラメータ**が宣言されて結束が二重化する。"""
    phase = _phase({"position_equiv_groups": (("D1", "H1"),)}, structure=_co_located())
    text = _stage(_doc(phase, histograms=2), coords=True).render()
    assert "prm P_D1_x" not in text and "prm P_H1_x" not in text
    assert "prm P_pos_g0_x " in text
    assert "prm P_O1_x " in text  # 結束していない原子は従来どおり持ち上げる


def test_tie_group_with_different_site_symmetry_is_refused():
    """鏡面上の原子と一般位置の原子を結束すると、鏡面上の原子が特殊位置から外れる。"""
    structure = _structure(
        Atom("Pb", "Pb", 0.188, 0.25, 0.167, 1.0, 0.010),
        Atom("O1", "O", 0.095, 0.026, 0.806, 1.0, 0.010),
    )
    with pytest.raises(InvalidPhaseSpecError, match="サイト対称"):
        _phase({"position_equiv_groups": (("Pb", "O1"),)}, structure=structure)


def test_freezing_only_part_of_a_tie_group_is_refused():
    with pytest.raises(InvalidPhaseSpecError, match="H1"):
        _phase({"position_equiv_groups": (("D1", "H1"),), "frozen_coord_labels": ("H1",)},
               structure=_co_located())


def test_freezing_a_whole_tie_group_keeps_its_shared_coordinates_fixed():
    phase = _phase({"position_equiv_groups": (("D1", "H1"),),
                    "frozen_coord_labels": ("D1", "H1")}, structure=_co_located())
    text = _stage(_doc(phase), coords=True).render()
    assert "prm !P_pos_g0_x " in text


def test_small_tie_offsets_are_written_in_fixed_point():
    """``repr`` は小さな値を ``5e-05`` と指数表記にする。TOPAS の式で通ると実測した形
    (固定小数) に揃える。"""
    structure = _structure(
        Atom("O1", "O", 0.10, 0.03, 0.80, 1.0, 0.010),
        Atom("O3", "O", 0.10005, 0.03, 0.80, 1.0, 0.010),
    )
    phase = _phase({"position_equiv_groups": (("O1", "O3"),)}, structure=structure)
    text = _doc(phase).render()
    assert "x =P_pos_g0_x + 0.00005;" in text
    site_line = next(line for line in text.splitlines() if "site O3 " in line)
    assert "e-" not in site_line, f"式に指数表記が出た: {site_line}"


def test_joint_tied_members_reference_the_group_prm_in_every_histogram():
    """joint では各 xdd の str ブロックが同じ共有 prm を参照し、出版値は先頭の xdd で 1 回だけ。"""
    structure = _structure(
        Atom("O1", "O", 0.10, 0.03, 0.80, 1.0, 0.010),
        Atom("O3", "O", 0.20, 0.05, 0.70, 1.0, 0.010),
    )
    phase = _phase({"position_equiv_groups": (("O1", "O3"),)}, structure=structure)
    text = _stage(_doc(phase, histograms=2), coords=True).render()
    assert text.count("prm P_pos_g0_x ") == 1, "共有 prm の宣言は 1 回"
    blocks = text.split("xdd ")[1:]
    assert len(blocks) == 2
    for block in blocks:
        assert "site O1 x =P_pos_g0_x;" in block
        assert "site O3 x =P_pos_g0_x + 0.1;" in block
    assert text.count('"coord\\tP\\tO3\\tx') == 1, "出版値は先頭の xdd で 1 回だけ"
    assert "Out(P_pos_g0_x + 0.1," in blocks[0]


# ---------------- 意味を決められない指定は精密化の前に止める ----------------


@pytest.mark.parametrize(
    "field_name",
    ["frozen_coord_labels", "free_uiso_labels", "frozen_uiso_labels", "free_occupancy_labels"],
)
def test_unknown_label_is_refused(field_name):
    """綴り違いのラベルは**凍結したつもりで凍結されない** (無言 no-op)。"""
    with pytest.raises(InvalidPhaseSpecError, match="Ox"):
        _phase({field_name: ("Ox",)})


@pytest.mark.parametrize(
    "field_name",
    ["mixed_occupancy_groups", "occupancy_equiv_groups", "occupancy_sum_groups",
     "position_equiv_groups"],
)
def test_unknown_label_in_a_group_is_refused(field_name):
    with pytest.raises(InvalidPhaseSpecError, match="Ox"):
        _phase({field_name: (("O1", "Ox"),)})


def test_three_way_mixed_site_is_refused():
    """TOPAS 経路の混合占有は ``x`` / ``1-x`` の 2 原子形。3 原子に同じ形を当てると
    ``x, 1-x, 1-x`` で**和が 2-x** になる (以前は黙ってそうしていた)。"""
    structure = _structure(
        Atom("Fe1", "Fe", 0.0, 0.0, 0.0, 0.4, 0.010),
        Atom("Al1", "Al", 0.0, 0.0, 0.0, 0.3, 0.010),
        Atom("Ga1", "Ga", 0.0, 0.0, 0.0, 0.3, 0.010),
    )
    with pytest.raises(InvalidPhaseSpecError, match="2 原子"):
        _phase({"mixed_occupancy_groups": (("Fe1", "Al1", "Ga1"),)}, structure=structure)


def test_atom_in_two_occupancy_constraints_is_refused():
    """1 原子の占有率を 2 つの拘束で書くと、INP では**後に書いた方だけが効く**
    (張れる例外は和の組の親の共有だけ — `test_other_occupancy_overlaps_are_still_refused`)。"""
    with pytest.raises(InvalidPhaseSpecError, match="O1"):
        _phase({"occupancy_equiv_groups": (("O1", "O2"),),
                "occupancy_sum_groups": (("S", "O1"),)})


def test_hd_mix_parent_in_two_sum_groups_is_written_by_topas():
    """D/H 混合 (`deuterium.place_hd_mix`) は親水 O を 2 つの和の組に入れる — **GSAS では正しい
    入力**で、GSAS は両方の拘束を同時に満たす。以前の TOPAS 経路はこの形を止めて GSAS へ案内して
    いたが、今は同じ自由度で張る (親の式は最初の組、後の組は最後の子が「親 − 他の子」)。
    D/H 対の共位置の結束 (`position_equiv_groups`) と同時に渡しても止まらない。"""
    structure = _structure(
        Atom("Ow", "O", 0.30, 0.10, 0.20, 0.8, 0.010),
        Atom("DOw1", "H", 0.35, 0.12, 0.25, 0.6, 0.020),
        Atom("HOw1", "H", 0.35, 0.12, 0.25, 0.2, 0.020),
        Atom("DOw2", "H", 0.25, 0.12, 0.25, 0.6, 0.020),
        Atom("HOw2", "H", 0.25, 0.12, 0.25, 0.2, 0.020),
    )
    phase = _phase({"occupancy_sum_groups": (("Ow", "DOw1", "HOw1"), ("Ow", "DOw2", "HOw2")),
                    "position_equiv_groups": (("DOw1", "HOw1"), ("DOw2", "HOw2"))},
                   structure=structure)
    text = _doc(phase).render()
    assert "occ O =P_occsum_g0_1 + P_occsum_g0_2;" in _site_line(text, "Ow")
    assert "occ H =P_occsum_g0_1 + P_occsum_g0_2 - P_occsum_g1_1;" in _site_line(text, "HOw2")


# ---------------- 単一の真実源: 全フィールドを分類する ----------------


def test_every_phase_spec_field_is_classified_for_topas():
    """**PhaseSpec にフィールドを足したら、TOPAS がそれをどう扱うかを決めない限り落ちる**。

    今回の不具合は「GSAS 経路に足したフィールドを TOPAS が知らないまま黙って完走する」型で、
    個別に直しても次のフィールドで再発する。分類は `honored` (GSAS と同じ意味で効く) /
    `refused` (渡すと `InvalidPhaseSpecError`) / `unused` (どのバックエンドも読まない) の 3 つ。
    """
    declared = {f.name for f in fields(PhaseSpec)}
    assert set(PHASE_SPEC_FIELDS) == declared, (
        f"未分類: {sorted(declared - set(PHASE_SPEC_FIELDS))} / "
        f"存在しない: {sorted(set(PHASE_SPEC_FIELDS) - declared)}"
    )
    for name, (kind, _note) in PHASE_SPEC_FIELDS.items():
        assert kind in {"honored", "refused", "unused"}, name


def test_a_refused_field_stops_the_run_before_refinement(monkeypatch):
    """`refused` に分類したフィールドは、既定値でなければ精密化の前に止まる。"""
    from tsumugin.topas import structure as topas_structure

    table = dict(topas_structure.PHASE_SPEC_FIELDS)
    table["refine_cell"] = ("refused", "テスト用に拒否へ倒す")
    monkeypatch.setattr(topas_structure, "PHASE_SPEC_FIELDS", table)
    with pytest.raises(InvalidPhaseSpecError, match="refine_cell"):
        _phase({"refine_cell": False})
    _phase()  # 既定値なら通る


def test_non_cif_format_is_refused_before_the_structure_is_read(monkeypatch):
    """TOPAS 経路は CIF しか読まない。``format_hint="EXP"`` を渡すと、以前は .EXP を CIF として
    読みに行って構文エラー (② の境界を越える ValueError) になっていた。読む前に理由付きで止める。"""
    from tsumugin.topas import engine as eng

    monkeypatch.setattr(eng, "run_tc", lambda *a, **k: pytest.fail("tc.exe を起動した"))
    with pytest.raises(InvalidPhaseSpecError, match="format_hint"):
        eng.run_topas_rietveld(
            [], [PhaseSpec("no/such/file.EXP", "P", format_hint="EXP")], save_gpx=False
        )
    _phase({"format_hint": "cif"})  # 大小は意味を持たない


def test_carrying_a_refined_value_does_not_rewrite_the_tie_expressions():
    """持ち越し (#218) は「名前 + 空白 + 数値」を宣言とみなして値を差し替える。結束の式を
    ``name -0.1`` と書くと**宣言と誤認されて式が壊れる**ので、演算子と数値の間を空ける。"""
    structure = _structure(
        Atom("O1", "O", 0.10, 0.03, 0.80, 1.0, 0.010),
        Atom("O3", "O", 0.20, 0.05, 0.70, 1.0, 0.010),
    )
    phase = _phase({"position_equiv_groups": (("O1", "O3"),)}, structure=structure)
    doc = _doc(phase).with_updates(carried_values={"P_pos_g0_z": 0.5})
    text, unplaced = doc.render_with_report()
    assert "prm !P_pos_g0_z 0.5\n" in text
    assert "z =P_pos_g0_z - 0.1;" in text
    assert unplaced == ()


def test_temperature_is_classified_as_unused_by_every_backend():
    """相の ``temperature`` は GSAS 経路も読まない (温度差の判定は ``HistogramSpec.temperature``)。
    TOPAS だけで拒否すると、同じ入力が片方のエンジンでだけ止まる。"""
    assert PHASE_SPEC_FIELDS["temperature"][0] == "unused"
    _phase({"temperature": 10.0})


# ---------------- engine: 凍結した格子の esd を捏造しない ----------------


def test_frozen_cell_reports_no_esd_instead_of_zero(monkeypatch, synthetic_cif, synthetic_data):
    """凍結した格子に TOPAS は esd 0 を書くが、それは「精密化して 0 に決まった」ではない。
    GSAS 経路と同じく **None × 6** にする (`model.CellEsd` の 3 状態の規律)。"""
    from tsumugin.topas import engine as eng

    class _Run:
        out_text = "r_wp 10.0 gof 1.5\np0 1.0`_0.01\n"
        results_text = (
            "r_wp\t10.0\ngof\t1.5\nwt_frac\tmain\t60.0\t1.0\nwt_frac\tminor\t40.0\t1.0\n"
            "cell\tmain\ta\t8.47\t0.001\ncell\tminor\ta\t8.48\t0.0\n"
        )
        stdout = ""

    monkeypatch.setattr(eng, "run_tc", lambda *a, **k: _Run())
    hist = HistogramSpec(
        data_path=str(synthetic_data[0]), instrument_path=str(synthetic_data[1]),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    result = eng.run_topas_rietveld(
        [hist],
        [PhaseSpec(str(synthetic_cif), "main"),
         PhaseSpec(str(synthetic_cif), "minor", refine_cell=False)],
        recipe=(RefinementStage("S2 cell", {"cell": True}),),
        save_gpx=False,
    )
    assert result.cell_esd["minor"] == (None,) * 6
    assert result.cell_esd["main"][0] == pytest.approx(0.001)


def test_uiso_stage_with_every_phase_frozen_is_marked_as_intentional(
    monkeypatch, synthetic_cif, synthetic_data
):
    """全相で Uiso を凍結した uiso 段は**原理的に**何も解放しない。GSAS 経路 (#211) と同じく
    意図的な凍結であることを台帳に残し、真の無言失敗と区別できるようにする。"""
    from tsumugin.store import Ledger
    from tsumugin.topas import engine as eng

    class _Run:
        out_text = "r_wp 10.0 gof 1.5\np0 1.0`_0.01\n"
        results_text = "r_wp\t10.0\ngof\t1.5\nwt_frac\tP\t100.0\t0.0\n"
        stdout = ""

    monkeypatch.setattr(eng, "run_tc", lambda *a, **k: _Run())
    hist = HistogramSpec(
        data_path=str(synthetic_data[0]), instrument_path=str(synthetic_data[1]),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    ledger = Ledger()
    result = eng.run_topas_rietveld(
        [hist], [PhaseSpec(str(synthetic_cif), "P", free_uiso_labels=())],
        recipe=(RefinementStage("S0", {"scale": True}), RefinementStage("S6 uiso", {"uiso": True})),
        ledger=ledger, save_gpx=False,
    )
    stages = [e for e in ledger.entries if e.kind == "m12_topas_stage"]
    assert [e.payload["uiso_frozen_all"] for e in stages] == [False, True]
    # ③ の手順書は「凍結できたかは uiso 段の note の `uiso_frozen_all` で確かめる」と指示している
    # (GSAS 経路と同じ印)。TOPAS だけ出さないと、凍結が効いたのか無言失敗かを ③ が区別できない。
    assert "uiso_frozen_all" in result.stage_results[1].note
    assert "uiso_frozen_all" not in result.stage_results[0].note


def test_uiso_marker_follows_the_key_like_gsas(monkeypatch, synthetic_cif, synthetic_data):
    """GSAS は段に ``uiso`` の**キーがあるか**で印を付ける。値の真偽で見ると ``{"uiso": 0}``
    (ランク付きの段) で両エンジンの印が食い違う。"""
    from tsumugin.topas import engine as eng

    class _Run:
        out_text = "r_wp 10.0 gof 1.5\np0 1.0`_0.01\n"
        results_text = "r_wp\t10.0\ngof\t1.5\nwt_frac\tP\t100.0\t0.0\n"
        stdout = ""

    monkeypatch.setattr(eng, "run_tc", lambda *a, **k: _Run())
    hist = HistogramSpec(
        data_path=str(synthetic_data[0]), instrument_path=str(synthetic_data[1]),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    result = eng.run_topas_rietveld(
        [hist], [PhaseSpec(str(synthetic_cif), "P", free_uiso_labels=())],
        recipe=(RefinementStage("S6 uiso", {"uiso": 0}),), save_gpx=False,
    )
    assert "uiso_frozen_all" in result.stage_results[0].note


# ---------------- ②: 精密化の前の拒否は error dict に縮退する ----------------


def test_layer_two_degrades_the_refusal_to_an_error_dict(monkeypatch, synthetic_cif, synthetic_data):
    """③ は LLM なので例外は回復不能。TOPAS の入口で止めた相仕様の誤りも
    ``{"error","error_type"}`` で返る (tc.exe は一度も起動しない)。"""
    from tsumugin.mcp import rietveld_tools
    from tsumugin.topas import engine as eng

    def boom(*a, **k):  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("相仕様の誤りなのに tc.exe を起動した")

    monkeypatch.setattr(eng, "run_tc", boom)
    hist = HistogramSpec(
        data_path=str(synthetic_data[0]), instrument_path=str(synthetic_data[1]),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    ).to_dict()
    phase = PhaseSpec(str(synthetic_cif), "PbSO4", frozen_coord_labels=("Ox",)).to_dict()
    # **JSON 引数だけ**で TOPAS 経路に入る (runner を注入しない = ③ が実際に通る経路)。
    for tool, args in (
        (rietveld_tools.auto_rietveld, ([hist], [phase])),
        (rietveld_tools.refine_with_revisions, ([hist], [phase], [])),
    ):
        out = tool(*args, backend="topas", save_gpx=False)
        assert out.get("error_type") == "InvalidPhaseSpecError", (tool.__name__, out)
        assert "Ox" in out["error"]


def test_layer_two_degrades_unreadable_topas_input(monkeypatch, synthetic_cif, synthetic_data):
    """INP を組めない入力 (ここでは波長の無い装置ファイル) も error dict で返る。組み立て側は
    ``ValueError`` で知らせるが、② はドメインエラーしか縮退しないので包まないと境界を越える
    (CLAUDE.md「② ツールは例外を送出しない」)。"""
    from tsumugin.mcp import rietveld_tools
    from tsumugin.topas import engine as eng

    monkeypatch.setattr(eng, "run_tc", lambda *a, **k: pytest.fail("tc.exe を起動した"))
    hist = HistogramSpec(
        data_path=str(synthetic_data[0]), instrument_path=str(synthetic_data[0]),  # 波長が無い
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    ).to_dict()
    out = rietveld_tools.auto_rietveld(
        [hist], [PhaseSpec(str(synthetic_cif), "PbSO4").to_dict()], backend="topas",
        save_gpx=False,
    )
    assert out.get("error_type") == "TopasInputError", out
    assert "波長" in out["error"]


def test_layer_two_accepts_shared_parent_sum_groups_as_json(
    monkeypatch, synthetic_cif, synthetic_data, tmp_path
):
    """③ が実際に通る経路 (② に **JSON 引数だけ**を渡す) で、和の組の親の共有が止まらずに
    INP まで届く — ① が受理しても ② の変換で落ちれば ③ にとっては「無い」のと同じ。"""
    import json

    from tsumugin.autorietveld.deuterium import place_hd_mix
    from tsumugin.mcp import rietveld_tools
    from tsumugin.topas import engine as eng

    cif, pos_equiv, occ_sum = place_hd_mix(
        synthetic_cif, ["O1"], tmp_path / "hd.cif", deuteration=0.7, phase_name="P"
    )
    inputs: list[str] = []

    class _Run:
        out_text = "r_wp 10.0 gof 1.5\np0 1.0`_0.01\n"
        results_text = "r_wp\t10.0\ngof\t1.5\nwt_frac\tP\t100.0\t0.0\n"
        stdout = ""

    def fake_run(inp_text, **kw):
        inputs.append(inp_text)
        return _Run()

    monkeypatch.setattr(eng, "run_tc", fake_run)
    hist = HistogramSpec(
        data_path=str(synthetic_data[0]), instrument_path=str(synthetic_data[1]),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    ).to_dict()
    phase = PhaseSpec(str(cif), "P", position_equiv_groups=pos_equiv,
                      occupancy_sum_groups=occ_sum).to_dict()
    out = rietveld_tools.auto_rietveld(
        *json.loads(json.dumps([[hist], [phase]])), backend="topas", save_gpx=False
    )
    assert "error" not in out, out
    assert any("occ H =P_occsum_g0_1 + P_occsum_g0_2 - P_occsum_g1_1;" in text for text in inputs)


def test_layer_two_does_not_swallow_logic_bugs():
    """縮退するのは Tsumugin の**ドメインエラーだけ**。論理バグまで error dict にすると、
    不具合が「入力の誤り」に見えて握り潰される (縮退対象を広げすぎない対照)。"""
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    def buggy(inp):
        raise ZeroDivisionError("bug")

    with pytest.raises(ZeroDivisionError):
        auto_rietveld([], [], runner=buggy)


# ---------------- 実 tc.exe ----------------

_DATA = Path("docs/benchmark/testdata")
_PBSO4 = (_DATA / "PbSO4-Wyckoff.cif", _DATA / "PBSO4.XRA", _DATA / "INST_XRY.PRM")
_real_pbso4 = pytest.mark.skipif(
    not all(p.is_file() for p in _PBSO4), reason="PbSO4 実データが無い (gitignore 対象)"
)


def _pbso4_hist() -> HistogramSpec:
    return HistogramSpec(
        data_path=str(_PBSO4[1]), instrument_path=str(_PBSO4[2]),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="GSAS",
        two_theta_limits=(20.0, 90.0),
    )


@pytest.mark.topas
@_real_pbso4
def test_real_tc_honours_the_freezes(tmp_path):
    """実 tc.exe で: 格子・Pb 座標・Pb 以外の Uiso が**最後まで CIF 値のまま**で、Pb の Uiso と
    他原子の座標は動く (凍結が効いていて、かつ全部が凍結されてはいない)。"""
    from tsumugin.autorietveld.cif_normalize import read_structure_cif

    from .test_engine import _assert_n_params_is_topas_own_count
    from tsumugin.topas import engine as eng

    cif = read_structure_cif(str(_PBSO4[0]))
    result = eng.run_topas_rietveld(
        [_pbso4_hist()],
        [PhaseSpec(str(_PBSO4[0]), "PbSO4", refine_cell=False,
                   frozen_coord_labels=("Pb",), free_uiso_labels=("Pb",))],
        keep_project=str(tmp_path / "proj"),
    )
    assert math.isfinite(result.final_rwp)
    assert result.refined_cells["PbSO4"][:3] == pytest.approx((cif.a, cif.b, cif.c), abs=1e-9)
    assert result.cell_esd["PbSO4"] == (None,) * 6
    assert "Pb" not in result.atom_coords["PbSO4"], "凍結した座標が出版値として出た"
    assert {"S", "O1", "O2", "O3"} <= set(result.atom_coords["PbSO4"])
    assert set(result.atom_uiso["PbSO4"]) == {"Pb"}
    inp = (tmp_path / "proj" / f"stage{len(result.stage_results) - 1}.inp").read_text("utf-8")
    assert re.search(r"\ba !PbSO4_a ", inp)
    _assert_n_params_is_topas_own_count(result)


_T4 = _DATA / "m7" / "tofcw"


@pytest.mark.topas
@pytest.mark.skipif(
    not all((_T4 / name).is_file() for name in
            ("11BM_NAC.fxye", "PG3_22048.gsa", "PG3_22049.gsa", "NAC.cif", "CaF2.cif")),
    reason="M7 実データが無い (gitignore 対象)",
)
def test_real_t4_freezing_the_minor_phase_adp_clears_the_negative_uiso():
    """**実データでの受け入れ**: T4 (NAC + 少数相 CaF2 ~1 wt%) の既知の赤旗は CaF2 の
    Uiso < 0 (`test_engine.py` の T4 ベンチが「既知の状態」として固定)。③ の手順書が指示する
    「多相なら少数相の ADP を凍結する」(``free_uiso_labels=[]``) は、以前の TOPAS 経路では
    **黙って無視されて赤旗が残った**。凍結が効けば Uiso 検査は CaF2 で落ちようがない。

    実測 (2026-10-09, 背景 6 項): 既定 32.95% / validity 不合格 (Ca Uiso −0.011) → 凍結
    21.84% / 合格。⚠ **Rwp の差の大半は凍結の効果ではない** — S9 size_strain が既定の軌跡では
    revert、凍結の軌跡では受理された (CS_L は上限 10000 に張り付き) ことによる。ここで固定する
    のは「凍結が効いて Uiso 検査が通る」ことだけで、Rwp は既定と同じ上限で悪化だけを見る。
    """
    from .test_engine import _T4_RWP_CEILING, _t4_histograms

    from tsumugin.topas import engine as eng

    result = eng.run_topas_rietveld(
        _t4_histograms(_T4),
        [PhaseSpec(str(_T4 / "NAC.cif"), "NAC"),
         PhaseSpec(str(_T4 / "CaF2.cif"), "CaF2", free_uiso_labels=())],
        max_cyc=10, save_gpx=False,
    )
    assert "CaF2" not in result.atom_uiso, "凍結した少数相の Uiso が精密化された"
    assert result.validity.passed, [c for c in result.validity.checks if not c[1]]
    assert result.final_rwp < _T4_RWP_CEILING


@pytest.mark.topas
@_real_pbso4
def test_real_tc_honours_the_constraint_groups(tmp_path):
    """実 tc.exe が結束・等値・和の INP を受理し、**その通りの関係**を保って精密化すること。

    PbSO4 に物理的な意味の無い組を張った**機構の試験**である (値の妥当性は見ない):
    O1 と O2 は同じ鏡面上 (x,1/4,z) なのでシフトを結束でき、占有率は O1=O2 の等値と
    「S = O3」の和 (子 1 つ) を張る。
    """
    from tsumugin.autorietveld.cif_normalize import read_structure_cif

    from .test_engine import _assert_n_params_is_topas_own_count
    from tsumugin.topas import engine as eng

    cif = {a.label: a for a in read_structure_cif(str(_PBSO4[0])).atoms}
    result = eng.run_topas_rietveld(
        [_pbso4_hist()],
        [PhaseSpec(str(_PBSO4[0]), "PbSO4",
                   position_equiv_groups=(("O1", "O2"),),
                   occupancy_equiv_groups=(("O1", "O2"),),
                   occupancy_sum_groups=(("S", "O3"),))],
        keep_project=str(tmp_path / "proj"),
    )
    assert math.isfinite(result.final_rwp)
    coords = result.atom_coords["PbSO4"]
    assert {"O1", "O2"} <= set(coords), "結束した座標の出版値が欠けた"
    for i in (0, 2):  # x, z (y は鏡面で固定)
        initial = cif["O1"].x - cif["O2"].x if i == 0 else cif["O1"].z - cif["O2"].z
        assert coords["O1"][i] - coords["O2"][i] == pytest.approx(initial, abs=1e-6)
    assert coords["O1"][0] != pytest.approx(cif["O1"].x, abs=1e-6), "座標が動いていない"
    occ = result.atom_occupancy["PbSO4"]
    assert occ["O1"] == pytest.approx(occ["O2"], abs=1e-9)
    assert occ["S"] == pytest.approx(occ["O3"], abs=1e-6)
    _assert_n_params_is_topas_own_count(result)


_CWCOMBINED = _DATA / "m7" / "cwcombined"
_real_pbso4_joint = pytest.mark.skipif(
    not all(p.is_file() for p in (
        _PBSO4[0], _CWCOMBINED / "PBSO4.XRA", _CWCOMBINED / "INST_XRY.PRM",
        _CWCOMBINED / "PBSO4.CWN", _CWCOMBINED / "inst_d1a.prm",
    )),
    reason="PbSO4 X 線 + CW 中性子の実データが無い (gitignore 対象)",
)


@pytest.mark.topas
@_real_pbso4_joint
def test_real_tc_holds_both_sums_of_a_shared_parent(tmp_path):
    """実 tc.exe で `deuterium.place_hd_mix` の形 (親水 O が 2 つの和の組の親) を精密化し、
    **両方の和が精密化の後も成り立つ**こと。

    PbSO4 の O1 に D/H 対を 2 組置いた**機構の試験**である (PbSO4 に水素は無く、値の妥当性は
    見ない)。X 線では D と H の散乱因子が同じで D:H の比が決まらないので、散乱長の符号が逆の
    CW 中性子と joint で回す — joint の持ち上げ (`_shared_prm_plan`) も実 tc.exe で通る。
    自由度は GSAS と同じ 5 原子 − 2 拘束 = 3 で、占有率段が足した母数で数える。
    """
    from tsumugin.autorietveld.deuterium import place_hd_mix

    from .test_engine import _assert_n_params_is_topas_own_count
    from tsumugin.topas import engine as eng

    cif, pos_equiv, occ_sum = place_hd_mix(
        _PBSO4[0], ["O1"], tmp_path / "hd.cif", deuteration=0.7, phase_name="PbSO4"
    )
    members = ("O1", "DO11", "HO11", "DO12", "HO12")
    assert occ_sum == ((members[0], *members[1:3]), (members[0], *members[3:]))
    project = tmp_path / "proj"
    result = eng.run_topas_rietveld(
        [
            HistogramSpec(
                data_path=str(_CWCOMBINED / "PBSO4.XRA"),
                instrument_path=str(_CWCOMBINED / "INST_XRY.PRM"),
                radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
            ),
            HistogramSpec(
                data_path=str(_CWCOMBINED / "PBSO4.CWN"),
                instrument_path=str(_CWCOMBINED / "inst_d1a.prm"),
                radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
            ),
        ],
        [PhaseSpec(str(cif), "PbSO4", position_equiv_groups=pos_equiv,
                   occupancy_sum_groups=occ_sum)],
        recipe=(
            RefinementStage("S0", {"scale": True, "background": {"coeffs": 6}}),
            RefinementStage("S1 occupancy", {"occupancy": True}),
            # 占有率段の後にもう 1 段 — 後の組の prm (occsum_g1_1) が名前で持ち越され (#218)、
            # 式で書いた子 (HO12) が持ち越しの置換で壊れないことを実 tc.exe で見る。
            RefinementStage("S2 cell", {"cell": True}),
        ),
        # 機構の試験: O は本来満占有なので H/D を足すと Rwp が悪化しうる — 悪化判定で
        # revert させず、拘束の解そのものを読む。
        worsen_eps=1e9,
        keep_project=str(project),
    )
    base, occ_stage, cell_stage = result.stage_results
    for stage in (occ_stage, cell_stage):
        assert math.isfinite(stage.rwp) and not stage.reverted, stage.note
    carried = re.search(
        r"^prm PbSO4_occsum_g1_1 (\S+)$", (project / "stage2.inp").read_text("utf-8"), re.M
    )
    refined = re.search(
        r"^prm PbSO4_occsum_g1_1 +(\S+?)`", (project / "stage1.out").read_text("utf-8"), re.M
    )
    assert carried and refined, "後の組の prm が段の間で見つからない"
    assert float(carried.group(1)) == pytest.approx(float(refined.group(1)), abs=1e-6), (
        "後の組の prm が持ち越されていない (出発値から解き直している)"
    )
    assert "occ H =PbSO4_occsum_g0_1 + PbSO4_occsum_g0_2 - PbSO4_occsum_g1_1;" in (
        project / "stage2.inp"
    ).read_text("utf-8"), "持ち越しの置換が式で書いた子を壊した"
    occ = result.atom_occupancy["PbSO4"]
    assert set(members) <= set(occ), f"和の組の出版値が欠けた: {sorted(occ)}"
    assert occ["DO12"] != pytest.approx(0.7, abs=1e-4), "占有率が動いていない (拘束の試験にならない)"
    # Out は %.8f なので丸めは 1.5e-8 以内。
    assert occ["O1"] == pytest.approx(occ["DO11"] + occ["HO11"], abs=1e-6)
    assert occ["O1"] == pytest.approx(occ["DO12"] + occ["HO12"], abs=1e-6)
    assert occ_stage.n_params - base.n_params == 3, "占有率の自由度が GSAS (5 − 2) と違う"
    _assert_n_params_is_topas_own_count(result)
    inp = (project / "stage1.inp").read_text("utf-8")
    assert not re.search(r"^prm !?PbSO4_(?:O1|DO1\d|HO1\d)_occ\b", inp, re.M), (
        "joint で和の組の原子が個別にも持ち上げられた"
    )
