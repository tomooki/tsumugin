"""fit-then-judge P1-1A タスク 2: 出自を決めるための観測 (GSAS 非依存の純写像)。

- `diagnostics.covariance_record_from_cov_data`: 最終の共分散から varyList・従属変数・強い相関の対
- `claim_variables.claim_variable_names`: 値のキー → それが依存する GSAS 変数名
"""

from __future__ import annotations

import numpy as np

from tsumugin.autorietveld.claim_variables import (
    HistogramVariables,
    PhaseVariables,
    claim_variable_names,
)
from tsumugin.autorietveld.diagnostics import covariance_record_from_cov_data


def test_covariance_record_lists_vary_dependent_and_strong_correlations():
    names = ["0::A0", "0::dAx:1", "0:0:Scale"]
    sig = [0.01, 0.002, 0.1]
    corr = np.array([[1.0, 0.95, 0.1], [0.95, 1.0, -0.2], [0.1, -0.2, 1.0]])
    cov = corr * np.outer(sig, sig)
    rec = covariance_record_from_cov_data({
        "varyList": names, "sig": sig, "covMatrix": cov,
        "depSigDict": {"0::dAy:1": (0.0, 0.002), "0::AUiso:2": (0.01, 0.001)},
    })
    assert rec.vary_list == tuple(names)
    assert rec.dependent == ("0::AUiso:2", "0::dAy:1")
    assert [(p.a, p.b) for p in rec.correlations] == [("0::A0", "0::dAx:1")]
    assert abs(rec.correlations[0].r - 0.95) < 1e-12


def test_covariance_record_without_covariance_is_none_not_empty():
    """共分散が無い (精密化していない・失敗) のを「何も解放しなかった」と答えない。"""
    assert covariance_record_from_cov_data({}) is None
    assert covariance_record_from_cov_data({"varyList": None}) is None


def test_covariance_record_with_an_empty_vary_list_is_an_empty_record():
    rec = covariance_record_from_cov_data({"varyList": [], "sig": [], "covMatrix": None})
    assert rec is not None and rec.vary_list == () and rec.correlations == ()


def _phase(**kw):
    base = dict(name="P", pid=0, labels=("Pb", "O1"))
    base.update(kw)
    return PhaseVariables(**base)


def test_claim_keys_use_the_agreement_vocabulary_and_gsas_names():
    got = claim_variable_names(
        [_phase()], [HistogramVariables(index=0, hid=0, profile_keys=("U", "W"))],
    )
    assert got["cell:P.a"] == tuple(f"0::A{i}" for i in range(6))
    assert got["coord:P.O1.y"] == ("0::dAy:1",)
    assert got["uiso:P.Pb"] == ("0::AUiso:0",)
    assert got["occupancy:P.O1"] == ("0::Afrac:1",)
    assert got["microstructure:P.hist0.size"] == ("0:0:Size;i",)
    assert got["microstructure:P.hist0.mustrain"] == ("0:0:Mustrain;i",)
    assert got["profile:hist0.U"] == (":0:U",)
    assert got["weight_fraction:P.wt"] == ("0:0:Scale",)


def test_weight_fraction_depends_on_every_phase_scale():
    """質量分率は全相のスケールの比で決まる — 他相のスケールが動いても変わる。"""
    got = claim_variable_names(
        [_phase(), _phase(name="Q", pid=1, labels=("C",))],
        [HistogramVariables(index=0, hid=0, profile_keys=())],
    )
    assert set(got["weight_fraction:P.wt"]) == {"0:0:Scale", "1:0:Scale"}


def test_histogram_ids_are_gsas_ids_not_positions():
    """GSAS の変数名はヒストグラムの id で、列挙の位置ではない (`_profile_esd_map` と同じ罠)。"""
    got = claim_variable_names(
        [_phase()], [HistogramVariables(index=0, hid=3, profile_keys=("U",))],
    )
    assert got["profile:hist0.U"] == (":3:U",)
    assert got["microstructure:P.hist0.size"] == ("0:3:Size;i",)
