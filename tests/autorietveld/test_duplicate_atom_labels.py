"""相の中で原子ラベルが重複する構造は GSAS 経路で精密化の前に拒否する (GSAS 非依存で測る)。

GSAS-II の CIF インポータは重複した ``_atom_site_label`` を別原子として残す (警告
``note: repeated atom label`` を出すだけ)。ところが原子ごとの精密化フラグは
``G2Phase.set_refinements({"Atoms": {label: "XU"}})`` で付け、GSAS はラベルを
``G2Phase.atom(label)`` = **先頭**の一致で引き当てる。2026-10-09 に PbSO4 (O2 を ``O1`` へ
改名) で実測した結果:

- 2 番目の ``O1`` は既定レシピを最後まで回しても**フラグ空・座標と Uiso が CIF の出発値のまま**
- それでも完走し validity は合格、Rwp は 11.0191% (正しいラベルで 11.0181%) — **Rwp では見えない**
- 報告の ``atom_uiso["O1"]`` は **0.01 = 精密化されていない方の値** (ラベルキーの写像は末尾が勝つ)

つまりフラグは先頭に、拘束 (`_setup_constraints` の ``label_to_idx``) と結果の写像は末尾に
当たる。添字で引き当て直しても、結果・相の指定・初期占有率・拘束がすべてラベルキーなので
「精密化は正しいが報告が潰れる」に移るだけ — ラベルの一意性はラベルキー契約全体の前提で
あり、TOPAS 経路 (`topas.structure.structure_to_topas_phase`) と同じく入口で止める。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.errors import DuplicateAtomLabelError, TsumuginError


class _ReachedRefinementSetup(Exception):
    """検査を通り抜けて、精密化の準備 (参照格子の取得) まで進んだ印。"""


class _FakePhase:
    def __init__(self, labels, name="PbSO4"):
        # GSAS の原子行: AtomPtrs = (cx, ct, cs, cia)、ラベルは row[ct - 1]、座標は row[cx:cx+3]。
        self.data = {
            "General": {"AtomPtrs": [3, 1, 7, 9]},
            "Atoms": [
                [label, "O", "", 0.1 * i, 0.25, 0.5, 1.0] for i, label in enumerate(labels)
            ],
        }
        self.name = name

    def get_cell(self):
        raise _ReachedRefinementSetup


class _FakeHist:
    def __init__(self):
        self.data = {"Sample Parameters": {}}


def _hist() -> HistogramSpec:
    return HistogramSpec(
        data_path="d.xra", instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )


def _run_engine_with_fake_gsas(monkeypatch, phases_labels):
    """``phases_labels``: 相名 → GSAS が読んだ (ことにする) 原子ラベル列。"""
    from tsumugin.autorietveld import engine as eng

    added: list[str] = []

    class _Project:
        def __init__(self, newgpx):
            pass

        def add_powder_histogram(self, *a, **k):
            return _FakeHist()

        def add_phase(self, path, phasename, **k):
            added.append(phasename)
            return _FakePhase(phases_labels[phasename], name=phasename)

    class _G2sc:
        G2Project = _Project

    monkeypatch.setattr(eng, "_g2sc", lambda: _G2sc)
    specs = [PhaseSpec(structure_path=f"{n}.cif", phase_name=n) for n in phases_labels]
    eng.run_auto_rietveld([_hist()], specs, save_gpx=False)
    return added


def test_duplicate_label_is_refused_before_refinement(monkeypatch):
    """★相の指定が何も名指していなくても止める — 既定レシピの coords/uiso 段は**全原子**を
    ラベルで解放するので、名指しの有無に関係なく 2 番目の原子が黙って凍結される。"""
    with pytest.raises(DuplicateAtomLabelError, match="O1"):
        _run_engine_with_fake_gsas(monkeypatch, {"PbSO4": ("Pb", "S", "O1", "O1", "O3")})


def test_refusal_names_phase_and_the_rows_that_collide(monkeypatch):
    """③ が CIF のどの行を直すか分かるように、相名と衝突した行 (1 始まり) を添える。"""
    with pytest.raises(DuplicateAtomLabelError) as excinfo:
        _run_engine_with_fake_gsas(monkeypatch, {"PbSO4": ("Pb", "S", "O1", "O1", "O3")})
    message = str(excinfo.value)
    assert "'PbSO4'" in message
    assert "{'O1': [3, 4]}" in message, message


def test_every_duplicated_label_is_reported_at_once(monkeypatch):
    """1 つ直して回し直すたびに次が見つかる、を避ける。"""
    with pytest.raises(DuplicateAtomLabelError) as excinfo:
        _run_engine_with_fake_gsas(monkeypatch, {"X": ("S", "O", "S", "O", "Pb")})
    message = str(excinfo.value)
    assert "'S'" in message and "'O'" in message, message
    assert "'Pb'" not in message, "重複していないラベルまで並べない"


def test_every_phase_is_checked_not_only_the_first(monkeypatch):
    """多相: 2 相目の重複も止める (先頭相だけ見て抜けない)。"""
    with pytest.raises(DuplicateAtomLabelError, match="'minor'"):
        _run_engine_with_fake_gsas(
            monkeypatch, {"major": ("Pb", "S", "O1"), "minor": ("Ca", "O", "O")}
        )


def test_whitespace_and_case_variants_are_distinct_labels(monkeypatch):
    """陽性対照: GSAS は ``G2Phase.atom`` で**完全一致**を引くので ``O1``/``o1``/``O1 `` は
    別原子として正しく引き当たる — 推測で同一視して正しい構造を拒否しない。"""
    with pytest.raises(_ReachedRefinementSetup):
        _run_engine_with_fake_gsas(monkeypatch, {"PbSO4": ("Pb", "S", "O1", "o1", "O1 ")})


def test_unique_labels_reach_refinement(monkeypatch):
    """陽性対照: 一意なら検査を抜けて精密化の準備へ進む (検査が全部を止めていない)。"""
    with pytest.raises(_ReachedRefinementSetup):
        _run_engine_with_fake_gsas(monkeypatch, {"PbSO4": ("Pb", "S", "O1", "O2", "O3")})


def test_error_is_a_domain_input_error():
    """② の縮退はドメインエラーを捕まえ、既存の入力検証は ``ValueError`` で捕まえる。"""
    assert issubclass(DuplicateAtomLabelError, TsumuginError)
    assert issubclass(DuplicateAtomLabelError, ValueError)


# ---------------- ② は例外を送出しない ----------------


def _refusing_runner(_inp):
    raise DuplicateAtomLabelError("相 'PbSO4': 原子ラベルが重複しています: {'O1': [3, 4]}")


def test_layer_two_degrades_the_refusal_to_an_error_dict():
    """engine が精密化の途中 (相を読んだ直後) で送出するので、入力解析の ``try`` では捕まらない。
    ② は ``{"error","error_type"}`` を返す (③ は LLM なので例外は回復不能)。"""
    from tsumugin.mcp import rietveld_tools

    hist = _hist().to_dict()
    phase = PhaseSpec(structure_path="a.cif", phase_name="PbSO4").to_dict()
    for tool, args in (
        (rietveld_tools.auto_rietveld, ([hist], [phase])),
        (rietveld_tools.refine_with_revisions, ([hist], [phase], [])),
    ):
        out = tool(*args, runner=_refusing_runner)
        assert out.get("error_type") == "DuplicateAtomLabelError", (tool.__name__, out)
        assert "O1" in out["error"]


def test_degrade_decorator_passes_other_errors_through():
    """対照: 縮退の対象を広げすぎない (論理バグを「入力の誤り」に見せない)。"""
    from tsumugin.mcp._degrade import degrade_oserror

    @degrade_oserror
    def _bug() -> dict:
        raise KeyError("bug")

    with pytest.raises(KeyError):
        _bug()


# ---------------- ファンアウトは入力の誤りを候補の失敗に畳まない ----------------


def test_recipe_search_reraises_instead_of_failing_every_candidate():
    """どの候補でも同じになる入力の誤りを候補の失敗に畳むと「立つ手順が無い」と読まれる。"""
    from tsumugin.autorietveld.search import run_recipe_search

    phase = PhaseSpec(structure_path="a.cif", phase_name="PbSO4")
    with pytest.raises(DuplicateAtomLabelError, match="O1"):
        run_recipe_search(
            [_hist()], [phase], names=("default",),
            runner=lambda cand: _refusing_runner(cand), save_gpx=False,
        )


def test_multistart_reraises_instead_of_counting_divergence(monkeypatch):
    """開始点の失敗に畳むと「初期値で解が割れた」と読まれ、③ はラベルでなく構造を疑う。"""
    from tsumugin.autorietveld import engine
    from tsumugin.autorietveld import multistart as ms
    from tsumugin.multistart.perturb import MultistartConfig

    def _refuse(*a, **k):
        _refusing_runner(None)

    monkeypatch.setattr(engine, "run_auto_rietveld", _refuse)
    phase = PhaseSpec(structure_path="a.cif", phase_name="PbSO4")
    with pytest.raises(DuplicateAtomLabelError, match="O1"):
        ms.run_multistart_rietveld(
            [_hist()], [phase], config=MultistartConfig(n_starts=2), jobs=1, save_gpx=False,
        )


# ---------------- ③ の手順書が error_type を名指す ----------------


@pytest.mark.parametrize(
    "doc",
    [
        "plugins/tsumugin/skills/analyze/SKILL.md",
        "plugins/tsumugin/skills/mem-model-fix/SKILL.md",
        "docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md",
    ],
)
def test_layer_three_is_told_what_the_refusal_means(doc):
    """③ は ``error_type`` しか手掛かりが無い。手順書が実装のクラス名で名指していないと、
    改名や削除で「何を直せばよいか」の指示が黙って死ぬ。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    text = (root / doc).read_text(encoding="utf-8")
    assert DuplicateAtomLabelError.__name__ in text, doc
