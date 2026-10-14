"""P0 §1.1 のアームの組み立て (精密化は差し替え — GSAS を回さない)。"""

from __future__ import annotations

from types import SimpleNamespace

from tsumugin.autorietveld.model import RefinementStage
from tsumugin.prereg_eval.arms import (
    PERMUTATIONS,
    Runners,
    permute_stages,
    run_arms,
    stage_background,
    with_background,
)


def _stages(*labels, bkg=6):
    out = []
    for lab in labels:
        flags = {"scale": True, "background": {"coeffs": bkg}} if lab.startswith(("T0", "S0")) else {"x": lab}
        out.append(RefinementStage(lab, flags))
    return tuple(out)


TEMPLATE = _stages("T0 scale+background", "T1 lattice+offset", "T2 width-1", "TR lattice-retry",
                   "T5 coords", "T6 B", "T7 occupancy", "T8 pref", "T8R struct-retry", "T9 final", bkg=12)


# --- 段列の操作 ------------------------------------------------------------------------------


def test_background_is_read_and_replaced_without_touching_other_flags():
    assert stage_background(TEMPLATE) == 12
    swapped = with_background(TEMPLATE, 6)
    assert stage_background(swapped) == 6
    assert swapped[0].flags["scale"] is True and swapped[1:] == TEMPLATE[1:]


def test_registered_permutations():
    assert set(PERMUTATIONS) == {"swap_T1_T2", "swap_T5_T6", "T8_before_T5", "T7_before_T6"}
    lab = lambda st: [s.label.split()[0] for s in st]  # noqa: E731
    assert lab(permute_stages(TEMPLATE, "swap_T1_T2"))[:3] == ["T0", "T2", "T1"]
    assert lab(permute_stages(TEMPLATE, "swap_T5_T6"))[4:6] == ["T6", "T5"]
    assert lab(permute_stages(TEMPLATE, "T8_before_T5"))[4:8] == ["T8", "T5", "T6", "T7"]
    assert lab(permute_stages(TEMPLATE, "T7_before_T6"))[4:7] == ["T5", "T7", "T6"]


def test_permutation_needs_its_stages():
    no_pref = tuple(s for s in TEMPLATE if not s.label.startswith("T8 "))
    assert permute_stages(no_pref, "T8_before_T5") is None


# --- 実行 (差し替え) -------------------------------------------------------------------------


def _res(tag, gpx=""):
    return SimpleNamespace(tag=tag, gpx_path=gpx)


class Fake:
    def __init__(self, *, base_bkg=6, ab_bkg=6, template_fails=False):
        self.calls = []
        self.base_bkg, self.ab_bkg, self.template_fails = base_bkg, ab_bkg, template_fails

    def recipe(self, h, p, background_coeffs=None):
        return _stages("S0 scale", "S1 cell", bkg=background_coeffs or self.base_bkg)

    def single(self, h, p, *, recipe, **kw):
        self.calls.append(("single", tuple(s.label for s in recipe), stage_background(recipe), tuple(p)))
        return _res("single", gpx=f"{len(self.calls)}.gpx")

    def template_search(self, h, p, *, names, template_declarations, **kw):
        assert names == ("template",)
        if self.template_fails:
            return SimpleNamespace(selected=None, warnings=("nope",))
        cand = SimpleNamespace(stages=TEMPLATE, histograms=tuple(h), phases=("TPH",), derivation={"d": 1},
                               background_coeffs=12)
        return SimpleNamespace(selected=SimpleNamespace(candidate=cand, result=_res("T", "t.gpx")), warnings=())

    def confirm(self, h, p, *, candidates=None, **kw):
        self.calls.append(("confirm", candidates))
        stages = TEMPLATE if candidates == ("template",) else _stages("S0 scale", bkg=self.ab_bkg)
        cand = SimpleNamespace(stages=stages, histograms=tuple(h), phases=None, derivation=None)
        return SimpleNamespace(search=SimpleNamespace(selected=SimpleNamespace(candidate=cand)),
                               best=_res("AB", "ab.gpx"), multistart="MS", warnings=())

    def multistart(self, h, p, *, recipe, **kw):
        self.calls.append(("multistart", stage_background(recipe)))
        return SimpleNamespace(best=_res("ms", "ms.gpx"))

    def runners(self, posthoc=lambda path: 0.1):
        return Runners(single=self.single, template_search=self.template_search, confirm=self.confirm,
                       multistart=self.multistart, recipe=self.recipe, posthoc=posthoc)


def test_all_arms_run_and_background_matched_arms_reuse_when_equal():
    f = Fake(base_bkg=12, ab_bkg=12)
    arms = run_arms(("H",), ("P",), "DECL", runners=f.runners())
    assert set(arms) == {"B-single", "B-AB", "T-single", "T-AB", "T-single/bkg", "T-AB/bkg", "X-transplant",
                         *(f"T-perm:{p}" for p in PERMUTATIONS)}
    assert arms["T-single/bkg"].same_as == "T-single" and arms["T-AB/bkg"].same_as == "T-AB"
    assert arms["T-single/bkg"].posthoc_shift_esd == 0.1  # 同じ fit の事後検査の値を引き継ぐ
    assert not any(c[0] == "multistart" for c in f.calls)


def test_background_matched_arms_take_the_comparators_count():
    f = Fake(base_bkg=6, ab_bkg=18)
    arms = run_arms(("H",), ("P",), "DECL", runners=f.runners())
    assert arms["T-single/bkg"].background_coeffs == 6 and not arms["T-single/bkg"].same_as
    assert ("multistart", 18) in f.calls and arms["T-AB/bkg"].multistart is not None
    # テンプレートの段順と相の指定のまま、背景だけが変わる
    single_runs = [c for c in f.calls if c[0] == "single" and c[2] == 6 and c[1][0].startswith("T0")]
    assert single_runs and single_runs[0][3] == ("TPH",)


def test_transplant_keeps_the_current_stage_order_with_template_modelling():
    f = Fake()
    arms = run_arms(("H",), ("P",), "DECL", runners=f.runners())
    x = arms["X-transplant"]
    assert x.stage_labels == ("S0 scale", "S1 cell") and x.background_coeffs == 12 and x.phases == ("TPH",)


def test_template_failure_is_recorded_per_arm():
    f = Fake(template_fails=True)
    arms = run_arms(("H",), ("P",), "DECL", runners=f.runners())
    assert arms["T-single"].result is None and "template" in arms["T-single"].error
    assert arms["X-transplant"].result is None
    assert arms["B-single"].result is not None  # 基準経路は影響を受けない


def test_posthoc_failure_marks_the_arm():
    def boom(path):
        raise RuntimeError("refine failed")

    arms = run_arms(("H",), ("P",), "DECL", runners=Fake().runners(posthoc=boom))
    assert "posthoc" in arms["B-single"].error


def test_permutations_without_their_stages_are_not_run():
    f = Fake()
    arms = run_arms(("H",), ("P",), "DECL", runners=f.runners(), permutations=("swap_T1_T2",))
    assert arms["T-perm:swap_T1_T2"].stage_labels[1].startswith("T2")


def test_move_before_is_not_a_permutation_when_already_earlier():
    early = _stages("T0 scale+background", "T8 pref", "T5 coords", "T6 B")
    assert permute_stages(early, "T8_before_T5") is None
