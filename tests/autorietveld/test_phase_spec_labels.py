"""相の指定が名指す原子ラベルの検査 — **両エンジン共通** (`model.check_phase_spec_labels`)。

GSAS 経路 (`engine._phase_atom_info` / `_setup_constraints`) は相に無いラベルを
``if lab in label_to_idx`` で、異なる 2 原子に満たない組を ``len(idxs) < 2: continue`` で
**黙って飛ばしていた**。綴り違いの ``frozen_uiso_labels=["Ca1 "]`` は何も凍結せずに完走する
(= 呼べるが黙って間違う)。同じ `PhaseSpec` を TOPAS 経路は精密化の前に拒否していたので、
**同じ入力が片方のエンジンでだけ止まる**状態でもあった。

ここで固定するのは、エンジンを問わず意味を決められない指定だけ:

- 相に無い原子ラベル (前後の空白・大小の違いを含む)
- 相の中で 2 原子以上を指すラベル (GSAS は凍結・解放を先頭の原子に、拘束を末尾の原子に当てる)
- 異なる 2 原子に満たない組 (1 原子の組は何も拘束しない)

**1 原子を 2 つの占有率拘束に入れること**はここでは拒否しない — GSAS は両方の拘束を同時に
満たす (equivalence を constraint に変換して解く, 2026-10-09 に PbSO4 で実測)。張れないのは
TOPAS の INP (後に書いた方だけが効く) なので、3 原子以上の混合占有と同じく TOPAS 固有の規則。

numpy-only (GSAS 非依存)。
"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.autorietveld.model import (
    PHASE_SPEC_GROUP_FIELDS,
    PHASE_SPEC_LABEL_FIELDS,
    PhaseSpec,
    check_phase_spec_labels,
)
from tsumugin.errors import InvalidPhaseSpecError

_LABELS = ("Pb", "S", "O1", "O2", "O3")


def _spec(**kw) -> PhaseSpec:
    return PhaseSpec(structure_path="x.cif", phase_name="PbSO4", **kw)


# ---------------- 相に無いラベル ----------------


@pytest.mark.parametrize("field_name", PHASE_SPEC_LABEL_FIELDS)
def test_unknown_label_is_refused(field_name):
    """綴り違いは**凍結・解放したつもりで何も効かない** (GSAS は黙って飛ばしていた)。"""
    with pytest.raises(InvalidPhaseSpecError, match=rf"{field_name}.*Ox"):
        check_phase_spec_labels(_spec(**{field_name: ("O1", "Ox")}), _LABELS)


@pytest.mark.parametrize("field_name", PHASE_SPEC_GROUP_FIELDS)
def test_unknown_label_in_a_group_is_refused(field_name):
    with pytest.raises(InvalidPhaseSpecError, match=rf"{field_name}.*Ox"):
        check_phase_spec_labels(_spec(**{field_name: (("O1", "Ox"),)}), _LABELS)


def test_trailing_whitespace_is_not_the_same_label():
    """``"Pb "`` を ``"Pb"`` と読み替えない — 推測で埋めると、別の綴り違いで同じ穴が開く。
    エラー文は repr で出す (空白が見えないと③は直し方が分からない)。"""
    with pytest.raises(InvalidPhaseSpecError, match=r"'Pb '"):
        check_phase_spec_labels(_spec(frozen_uiso_labels=("Pb ",)), _LABELS)


def test_label_case_is_significant():
    with pytest.raises(InvalidPhaseSpecError, match="o1"):
        check_phase_spec_labels(_spec(frozen_coord_labels=("o1",)), _LABELS)


def test_refusal_names_the_phase_and_its_atoms():
    """③ が直せるように、相名と相の実際の原子ラベルを添える。"""
    with pytest.raises(InvalidPhaseSpecError) as excinfo:
        check_phase_spec_labels(_spec(free_occupancy_labels=("Ox",)), _LABELS)
    message = str(excinfo.value)
    assert "'PbSO4'" in message
    for label in _LABELS:
        assert label in message


def test_every_unknown_label_is_reported_at_once():
    """1 つ直して回し直すたびに次が見つかる、を避ける (精密化の前でも GSAS の読込は遅い)。"""
    spec = _spec(frozen_uiso_labels=("Ox",), position_equiv_groups=(("O1", "Oy"),))
    with pytest.raises(InvalidPhaseSpecError) as excinfo:
        check_phase_spec_labels(spec, _LABELS)
    assert "Ox" in str(excinfo.value) and "Oy" in str(excinfo.value)


# ---------------- 2 原子以上を指すラベル ----------------


def test_label_naming_two_atoms_is_refused_when_referenced():
    """GSAS の ``G2Phase.atom(label)`` は**先頭**の一致を、``_setup_constraints`` の
    ``label_to_idx`` は**末尾**の一致を使う。同じラベルの凍結と拘束が別の原子に当たる。"""
    with pytest.raises(InvalidPhaseSpecError, match="O1"):
        check_phase_spec_labels(
            _spec(frozen_coord_labels=("O1",)), ("Pb", "S", "O1", "O1", "O3")
        )


def test_duplicate_labels_that_no_field_names_are_left_to_the_engine():
    """名指していないラベルの重複は相の指定の問題ではない (TOPAS は構造の読込で別に拒否する)。"""
    check_phase_spec_labels(_spec(frozen_coord_labels=("Pb",)), ("Pb", "S", "O1", "O1"))


# ---------------- 組の形 ----------------


@pytest.mark.parametrize("field_name", PHASE_SPEC_GROUP_FIELDS)
def test_one_atom_group_is_refused(field_name):
    """1 原子の組は何も拘束しない (GSAS は ``len(idxs) < 2: continue`` で黙って飛ばしていた)。"""
    with pytest.raises(InvalidPhaseSpecError, match=rf"{field_name}.*O1"):
        check_phase_spec_labels(_spec(**{field_name: (("O1",),)}), _LABELS)


@pytest.mark.parametrize("field_name", PHASE_SPEC_GROUP_FIELDS)
def test_group_repeating_an_atom_is_refused(field_name):
    """``("O1", "O1")`` は 2 原子の組に見えて 1 原子しかない (混合占有なら O1 + O1 = 1)。"""
    with pytest.raises(InvalidPhaseSpecError, match=field_name):
        check_phase_spec_labels(_spec(**{field_name: (("O1", "O1"),)}), _LABELS)


def test_group_repeating_an_atom_among_others_is_refused():
    """``(親, 子, 親)`` は異なる 2 原子を含むが、同じ原子を 2 度数える (和の組なら 親 = 子 + 親)。"""
    with pytest.raises(InvalidPhaseSpecError, match="occupancy_sum_groups"):
        check_phase_spec_labels(_spec(occupancy_sum_groups=(("S", "O1", "S"),)), _LABELS)


def test_empty_group_is_refused():
    with pytest.raises(InvalidPhaseSpecError, match="mixed_occupancy_groups"):
        check_phase_spec_labels(_spec(mixed_occupancy_groups=((),)), _LABELS)


# ---------------- 通すもの (陽性対照) ----------------


def test_every_field_with_real_labels_passes():
    spec = _spec(
        mixed_occupancy_groups=(("O1", "O2"),),
        free_occupancy_labels=("Pb",),
        occupancy_equiv_groups=(("S", "O3"),),
        free_uiso_labels=("Pb", "S"),
        position_equiv_groups=(("O1", "O2"),),
        occupancy_sum_groups=(("Pb", "S"),),  # 親 = Σ子 — 3 原子以上も GSAS は張れる
        frozen_coord_labels=("O3",),
        frozen_uiso_labels=("S",),
    )
    check_phase_spec_labels(spec, _LABELS)


def test_default_spec_passes_even_for_a_phase_without_atoms():
    check_phase_spec_labels(_spec(), ())


@pytest.mark.parametrize("free_uiso_labels", [None, ()])
def test_unspecified_and_explicitly_empty_uiso_labels_pass(free_uiso_labels):
    check_phase_spec_labels(_spec(free_uiso_labels=free_uiso_labels), _LABELS)


def test_an_atom_in_two_occupancy_constraints_passes_the_shared_check():
    """GSAS は混合占有 (O1 + O2 = 1) と等値 (O1 = O3) を同時に満たす (実測: O1 = O3 = 0.579,
    O2 = 0.421)。拒否するのは TOPAS (`topas.structure._resolve_phase_spec`) だけ。"""
    spec = _spec(mixed_occupancy_groups=(("O1", "O2"),), occupancy_equiv_groups=(("O1", "O3"),))
    check_phase_spec_labels(spec, _LABELS)


# ---------------- 単一の真実源: ラベルを運ぶフィールドを漏らさない ----------------


def test_every_label_bearing_field_is_checked():
    """`PhaseSpec` に原子ラベル (の組) のフィールドを足したら、検査の対象に入れない限り落ちる。

    今回の欠陥は「エンジンが相に無いラベルを黙って飛ばす」型で、フィールドを足すたびに
    同じ穴が開く。型 (注釈) から引くので、手書きの一覧と照合するより先に古くならない。
    """
    by_annotation = {"tuple[str, ...]": "label", "tuple[str, ...] | None": "label",
                     "tuple[tuple[str, ...], ...]": "group"}
    expected: dict[str, set[str]] = {"label": set(), "group": set()}
    for f in dataclasses.fields(PhaseSpec):
        kind = by_annotation.get(str(f.type))  # model.py は postponed annotations (文字列)
        if kind is not None:
            expected[kind].add(f.name)
    assert expected["label"] == set(PHASE_SPEC_LABEL_FIELDS)
    assert expected["group"] == set(PHASE_SPEC_GROUP_FIELDS)
    assert expected["label"] and expected["group"], "注釈の読み取りが空振りしていない"


# ---------------- GSAS 経路の配線 (GSAS 無しで測る) ----------------


class _ReachedRefinementSetup(Exception):
    """検査を通り抜けて、精密化の準備 (参照格子の取得) まで進んだ印。"""


class _FakePhase:
    def __init__(self, labels):
        # GSAS の原子行: AtomPtrs = (cx, ct, cs, cia)、ラベルは row[ct - 1]。
        self.data = {
            "General": {"AtomPtrs": [3, 1, 7, 9]},
            "Atoms": [[label, "O", "", 0.0, 0.0, 0.0, 1.0] for label in labels],
        }
        self.name = "PbSO4"

    def get_cell(self):
        raise _ReachedRefinementSetup


class _FakeHist:
    def __init__(self):
        self.data = {"Sample Parameters": {}}


def _run_engine_with_fake_gsas(monkeypatch, spec: PhaseSpec, labels=_LABELS):
    from tsumugin.autorietveld import engine as eng
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation

    class _Project:
        def __init__(self, newgpx):
            pass

        def add_powder_histogram(self, *a, **k):
            return _FakeHist()

        def add_phase(self, *a, **k):
            return _FakePhase(labels)

    class _G2sc:
        G2Project = _Project

    monkeypatch.setattr(eng, "_g2sc", lambda: _G2sc)
    hist = HistogramSpec(
        data_path="d.fxye", instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )
    eng.run_auto_rietveld([hist], [spec])


def test_gsas_engine_refuses_an_unknown_label_before_refinement(monkeypatch):
    """GSAS が相を読んだ直後 (= ラベルが分かった時点) に止める。精密化の準備にも進まない。"""
    with pytest.raises(InvalidPhaseSpecError, match=r"'Pb '"):
        _run_engine_with_fake_gsas(monkeypatch, _spec(frozen_uiso_labels=("Pb ",)))


def test_gsas_engine_checks_against_the_labels_gsas_read(monkeypatch):
    """CIF の綴りではなく **GSAS の原子行**と突き合わせる (拘束が引き当てるのと同じもの)。"""
    with pytest.raises(InvalidPhaseSpecError, match="O1"):
        _run_engine_with_fake_gsas(
            monkeypatch, _spec(frozen_coord_labels=("O1",)), labels=("Pb", "S", "O_1")
        )


def test_gsas_engine_refuses_a_one_atom_group(monkeypatch):
    with pytest.raises(InvalidPhaseSpecError, match="mixed_occupancy_groups"):
        _run_engine_with_fake_gsas(monkeypatch, _spec(mixed_occupancy_groups=(("O1",),)))


def test_gsas_engine_lets_a_valid_spec_through(monkeypatch):
    """陽性対照: 正しいラベルなら検査を抜けて精密化の準備へ進む (検査が全部を止めていない)。
    GSAS が両方を満たせる占有率拘束の重複もここで止めない (TOPAS 固有の規則)。"""
    spec = _spec(
        frozen_uiso_labels=("Pb",),
        mixed_occupancy_groups=(("O1", "O2"),),
        occupancy_equiv_groups=(("O1", "O3"),),
    )
    with pytest.raises(_ReachedRefinementSetup):
        _run_engine_with_fake_gsas(monkeypatch, spec)
