"""操作系ワークベンチの決定論シードデータ (`docs/design/gui-workbench/api-contract.md`)。

実解析セッション接続までは、FIT メトリクス・PARAMETERS 表・PHASE ID 候補・SEQUENCE 系列・
STRUCTURE サイト・AUTO transcript を決定論シード (デザインハンドオフ `handoff/README.md` の
プロトタイプ同値) としてバックエンドから配信する (v1 スコープ境界)。本モジュールは純 dict/list
のみを返す純関数群であり、numpy にも fastapi にも依存しない。

シードもバックエンド供給とする方針 (ADR-0001 規律 1): フロントにデータをハードコードさせず
`/api/viewmodel` の形を実データの契約として先に凍結する。実 API 差し替え時にフロントの view を
書き直さずに済む。

一部 (仮説の accept/revert 配線用の ``build_seed_search_result``) は ① エンジン実体
(``FinalSelectionEngine``) に本物の裁定を通すための最小 ``SearchResult`` を組み立てる
(v1 スコープ境界: 「仮説 accept・revert は① エンジン実体に配線する」)。
"""

from __future__ import annotations

from typing import Any

from ..evidence.base import EvidenceResult
from ..evidence.ranking import RankedHypothesis
from ..model import Hypothesis, LatticeParams, PhaseInstance, RefinementMetrics
from ..search.matcher import UnmatchedPeakReport
from ..search.peaks import Peak
from ..search.tree import SearchResult
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore

# ---------------------------------------------------------------------------
# /api/state
# ---------------------------------------------------------------------------


def seed_project() -> dict[str, Any]:
    """GET /api/state の ``project`` (ハンドオフ Context bar)。"""
    return {
        "name": "K2Mn[Fe(CN)6] operando",
        "dataset": "SR-XRD λ 0.79958 · 247 frames",
        "frame": "fr091",
        "echem": {"v": 3.94, "q_mah_g": 41.2, "x_echem": "0.71(2)"},
    }


def seed_status() -> dict[str, Any]:
    """GET /api/state の ``status`` (Status bar)。"""
    return {"backend_build": "tsumugin 0.3.0", "seed": 0, "mcp_tools": 36}


def seed_agent_status() -> dict[str, Any]:
    """GET /api/state の ``agent`` 基礎値 (idle は session が mode から算出する)。"""
    return {"tokens": 1240000, "wall_time_s": 1084}


# ---------------------------------------------------------------------------
# viewmodel: left rail
# ---------------------------------------------------------------------------


def seed_datasets() -> list[dict[str, Any]]:
    return [
        {"id": "sxrd", "name": "SR-XRD", "meta": "λ 0.79958 · 247 fr", "probe": "X", "active": True},
        {"id": "nd1", "name": "ND TOF bank 1", "meta": "low-angle bank", "probe": "N", "active": False},
        {"id": "nd2", "name": "ND TOF bank 3", "meta": "high-angle bank", "probe": "N", "active": False},
    ]


def seed_phases() -> list[dict[str, Any]]:
    return [
        {
            "id": "p1", "name": "cubic K2Mn[Fe(CN)6]", "swatch": "accent",
            "space_group": "Fm-3m", "mp_id": "mp-583814", "wt_frac": "62.1(4) %",
        },
        {
            "id": "p2", "name": "tetragonal K2Mn[Fe(CN)6]", "swatch": "neutral",
            "space_group": "P4/mnc", "mp_id": "mp-583815", "wt_frac": "29.4(6) %",
        },
        {
            "id": "p3", "name": "monoclinic K2Mn[Fe(CN)6]", "swatch": "neutral",
            "space_group": "P21/n", "mp_id": "mp-583816", "wt_frac": "8.5(9) %",
        },
    ]


def seed_channels() -> list[dict[str, Any]]:
    return [
        {"id": "echem", "label": "echem", "value": "V 3.94 · I −0.20 mA · Q 41.2"},
        {"id": "alkali", "label": "alkali budget x(t)", "value": "x_total 0.71(2) · FR-318"},
        {"id": "cellconfig", "label": "CellConfig μt", "value": "μt 0.842"},
    ]


def seed_snapshots() -> list[dict[str, Any]]:
    """このセッション以前から存在する既知スナップショットの表示シード (静的情報)。

    セッション自身が ``SnapshotStore.save`` で作る実スナップショットは別途 append される。
    """
    return [{"id": "S-0310", "note": "before stage 07"}]


# ---------------------------------------------------------------------------
# viewmodel: FIT
# ---------------------------------------------------------------------------


def seed_fit() -> dict[str, Any]:
    return {
        "metrics": [
            {"key": "rwp", "label": "Rwp", "value": "6.71%", "note": "vs manual 16.24%"},
            {"key": "gof", "label": "GOF", "value": "1.29", "note": ""},
            {"key": "chi2", "label": "χ²", "value": "3 118", "note": ""},
            {"key": "n_params", "label": "n_params", "value": "38", "note": ""},
            {"key": "delta", "label": "Δ vs manual", "value": "−9.53", "note": "pts"},
            {"key": "basins", "label": "basins", "value": "1 / 3", "note": "corroborated"},
        ],
        "histograms": [
            {"id": "sxrd", "label": "SR-XRD λ0.79958", "active": True},
            {"id": "nd1", "label": "ND TOF bank 1", "active": False},
            {"id": "nd2", "label": "ND TOF bank 3", "active": False},
        ],
        "limits_note": "two_theta_limits = [4.0, 38.0] · background 24 terms · Kα1 instprm",
        "phase_ticks": [
            "cubic K2Mn[Fe(CN)6]", "tetragonal K2Mn[Fe(CN)6]", "monoclinic K2Mn[Fe(CN)6]",
        ],
        "two_theta": {"min": 4.0, "max": 38.0},
        "history": [
            {"stage": "01 background", "rwp": 24.9, "delta_rwp": -41.2, "guard": "", "reverted": False},
            {"stage": "02 scale + cell", "rwp": 18.3, "delta_rwp": -6.6, "guard": "", "reverted": False},
            {"stage": "03 zero", "rwp": 16.1, "delta_rwp": -2.2, "guard": "", "reverted": False},
            {"stage": "04 profile U/V/W", "rwp": 11.4, "delta_rwp": -4.7, "guard": "", "reverted": False},
            {"stage": "05 profile X/Y/Zero", "rwp": 9.2, "delta_rwp": -2.2, "guard": "", "reverted": False},
            {"stage": "06 phase fractions", "rwp": 7.02, "delta_rwp": -0.31, "guard": "", "reverted": False},
            {
                "stage": "07 occupancies", "rwp": 7.44, "delta_rwp": 0.42,
                "guard": "revert: occ<0", "reverted": True,
            },
            {"stage": "08 size/microstrain", "rwp": 6.71, "delta_rwp": -0.73, "guard": "", "reverted": False},
        ],
        "validity": [
            {"check": "occupancy bounds", "status": "pass", "detail": "0 ≤ occ ≤ 1"},
            {"check": "Uiso", "status": "pass", "detail": "0.005–0.08 Å²"},
            {"check": "cell collapse", "status": "pass", "detail": "no axis < 1 Å"},
            {"check": "bond distance", "status": "pass", "detail": "Fe–C 1.90–1.96 Å"},
            {"check": "coordination", "status": "warn", "detail": "K1 coordination 8→7 near transition"},
        ],
    }


# ---------------------------------------------------------------------------
# viewmodel: PARAMETERS
# ---------------------------------------------------------------------------


def _row(field: str, value: str, esd: str = "", *, released: bool = False, locked: bool = False) -> dict[str, Any]:
    return {"field": field, "value": value, "esd": esd, "released": released, "locked": locked}


def _cw_parameters_for_histogram() -> dict[str, Any]:
    rows_radiation = [
        _row("wavelength λ / Å", "0.799580", "±0.000004", locked=True),
        _row("Kα2 / Kα1 ratio", "0.000", ""),
        _row("polarization", "0.980", ""),
    ]
    rows_background = [
        _row(f"coeff {i}", v, e, released=(i <= 4))
        for i, (v, e) in enumerate(
            [
                ("412.3", "±2.1"), ("-88.6", "±3.4"), ("21.9", "±2.8"), ("-6.2", "±1.9"),
                ("2.1", "±1.5"), ("-0.8", "±1.2"), ("0.3", "±0.9"), ("-0.1", "±0.7"),
            ],
            start=1,
        )
    ]
    rows_profile = [
        _row("U", "-1.960", "±0.040", released=True),
        _row("V", "-0.512", "±0.021", released=True),
        _row("W", "0.084", "±0.006", released=True),
        _row("X", "0.021", "±0.004", released=True),
        _row("Y", "0.045", "±0.005", released=True),
        _row("Z", "0.000", "", locked=True),
        _row("SH/L", "0.0021", "±0.0003", released=False),
        _row("Zero", "-0.0142", "±0.0008", released=True),
    ]
    rows_sample = [
        _row("scale (cubic)", "0.00412", "±0.00006", released=True),
        _row("sample displacement", "0.0031", "±0.0004", released=True),
        _row("absorption μt", "0.842", "±0.012", released=False),
        _row("preferred orientation", "1.000", "", locked=True),
    ]
    rows_micro = [
        _row("size (cubic)", "412 Å", "±18", released=True),
        _row("mustrain (cubic)", "0.031%", "±0.004", released=True),
        _row("LGmix", "0.70", "", locked=True),
    ]
    return {
        "released_count": sum(
            r["released"] for r in rows_background + rows_profile + rows_sample + rows_micro + rows_radiation
        ),
        "cards": [
            {
                "id": "radiation", "title": "RADIATION / WAVELENGTH", "note": "instprm",
                "dropdown": {
                    "label": "source", "value": "synchrotron X-ray",
                    "options": [
                        "synchrotron X-ray", "lab Cu Kα", "lab Mo Kα", "neutron CW", "neutron TOF",
                    ],
                },
                "rows": rows_radiation,
                "footer": "λ/cell is near-singular — keep λ fixed (SR_CeO2 file's 0.5 is unused).",
            },
            {
                "id": "background", "title": "BACKGROUND", "note": "24 terms",
                "dropdown": {
                    "label": "function", "value": "chebyshev",
                    "options": ["chebyshev", "cosine", "power series"],
                },
                "rows": rows_background,
                "footer": "8 of 24 coefficients shown.",
            },
            {
                "id": "profile", "title": "PROFILE", "note": "CW",
                "rows": rows_profile,
                "footer": "Lorentzian X,Y and Zero released in a separate stage from U,V,W (revert-guard isolated).",
            },
            {
                "id": "sample", "title": "SAMPLE & GEOMETRY", "note": "",
                "rows": rows_sample,
                "footer": "",
            },
            {
                "id": "micro", "title": "SIZE / MICROSTRAIN", "note": "per phase",
                "dropdown": {
                    "label": "model", "value": "isotropic",
                    "options": ["isotropic", "generalized"],
                },
                "rows": rows_micro,
                "footer": (
                    "Stage 08 reverts on cell collapse; low-resolution CW histograms are excluded "
                    "from size/microstrain release."
                ),
            },
        ],
    }


def _tof_parameters_for_histogram(bank_label: str) -> dict[str, Any]:
    rows_radiation = [
        _row("λ band", "0.5 – 3.2 Å", ""),
        _row("flight path", "40.020 m", "±0.002"),
        _row("bank 2θ", "90.02°", "±0.01"),
    ]
    rows_background = [
        _row(f"coeff {i}", v, e, released=(i <= 2))
        for i, (v, e) in enumerate([("108.4", "±4.1"), ("-22.6", "±3.0"), ("6.1", "±2.4"), ("-1.4", "±1.7")], start=1)
    ]
    rows_profile = [
        _row("difC", "16 372.1", "±0.8", released=True),
        _row("difA", "0.00", "", locked=True),
        _row("difB", "-1.42", "±0.09", released=False),
        _row("Zero", "-0.83", "±0.11", released=True),
        _row("alpha", "0.014", "±0.002", released=False),
        _row("beta-0", "0.0064", "±0.0006", released=False),
        _row("beta-1", "0.0102", "±0.0009", released=False),
        _row("sig-0", "0.0", "", locked=True),
        _row("sig-1", "12.4", "±0.6", released=True),
        _row("sig-2", "0.0", "", locked=True),
    ]
    rows_sample = [
        _row("scale (cubic)", "0.00189", "±0.00004", released=True),
        _row("absorption μt", "0.301", "±0.009", released=False),
    ]
    rows_micro = [
        _row("size (cubic)", "n/a", "", locked=True),
        _row("mustrain (cubic)", "n/a", "", locked=True),
    ]
    return {
        "released_count": sum(
            r["released"] for r in rows_background + rows_profile + rows_sample + rows_micro
        ),
        "cards": [
            {
                "id": "radiation", "title": "RADIATION / WAVELENGTH", "note": f"instprm · {bank_label}",
                "rows": rows_radiation,
                "footer": "TOF has no single λ — calibrate difC instead.",
            },
            {
                "id": "background", "title": "BACKGROUND", "note": "24 terms",
                "dropdown": {
                    "label": "function", "value": "chebyshev",
                    "options": ["chebyshev", "cosine", "power series"],
                },
                "rows": rows_background,
                "footer": "4 of 24 coefficients shown.",
            },
            {
                "id": "profile", "title": "PROFILE", "note": "TOF",
                "rows": rows_profile,
                "footer": "",
            },
            {
                "id": "sample", "title": "SAMPLE & GEOMETRY", "note": "",
                "rows": rows_sample,
                "footer": "",
            },
            {
                "id": "micro", "title": "SIZE / MICROSTRAIN", "note": "excluded (low resolution)",
                "rows": rows_micro,
                "footer": "Low-resolution CW/TOF histograms are excluded from size/microstrain release.",
            },
        ],
    }


def seed_parameters() -> dict[str, Any]:
    return {
        "sxrd": _cw_parameters_for_histogram(),
        "nd1": _tof_parameters_for_histogram("bank 1"),
        "nd2": _tof_parameters_for_histogram("bank 3"),
    }


# ---------------------------------------------------------------------------
# viewmodel: HYPOTHESES + 実裁定用 SearchResult
# ---------------------------------------------------------------------------


def seed_hypotheses_rows() -> list[dict[str, Any]]:
    return [
        {
            "rank": 1, "id": "H-014", "phases": "cubic + mono + tetra", "p": 0.62,
            "rwp": 6.71, "gof": 1.29, "bic": 39402, "close": True,
            "status": "provisional", "selected": True,
        },
        {
            "rank": 2, "id": "H-011", "phases": "cubic + tetra", "p": 0.33,
            "rwp": 8.04, "gof": 1.35, "bic": 41208, "close": True,
            "status": "provisional", "selected": False,
        },
        {
            "rank": 3, "id": "H-009", "phases": "cubic + mono", "p": 0.05,
            "rwp": 9.86, "gof": 1.51, "bic": 44120, "close": False,
            "status": "demoted · chem", "selected": False,
        },
    ]


def seed_hypotheses_diff() -> dict[str, Any]:
    return {
        "vs": "H-011",
        "rows": [
            {"field": "phases", "a": "cubic + mono + tetra", "b": "cubic + tetra", "changed": True},
            {"field": "rwp", "a": "6.71", "b": "8.04", "changed": True},
            {"field": "bic", "a": "39402", "b": "41208", "changed": True},
        ],
    }


def seed_hypotheses_evidence() -> list[list[str]]:
    return [
        ["evidence backend", "bic → nested"],
        ["ΔlogZ", "1.2 < 2.5 threshold"],
        ["n = 3 · basins = 1", "corroborated"],
        ["demote only", "never exclude"],
    ]


def _seed_phase(ref: str, a: float, b: float, c: float, *, beta: float = 90.0) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a=a, b=b, c=c, beta=beta))


def build_seed_search_result() -> SearchResult:
    """仮説 accept/revert を実エンジン (``FinalSelectionEngine``) に配線するための最小 ``SearchResult``。

    ``seed_hypotheses_rows`` の 3 件 (H-014/H-011/H-009) と id を揃え、rwp/gof/bic を一致させる。
    ledger/snapshots はこの結果専用の使い捨てで、セッション本体の ledger とは別物 (非破壊)。
    """
    phases_h014 = (
        _seed_phase("cubic", 10.394, 10.394, 10.394),
        _seed_phase("mono", 10.41, 10.28, 10.52, beta=90.4),
        _seed_phase("tetra", 10.35, 10.35, 10.60),
    )
    phases_h011 = (
        _seed_phase("cubic", 10.394, 10.394, 10.394),
        _seed_phase("tetra", 10.35, 10.35, 10.60),
    )
    phases_h009 = (
        _seed_phase("cubic", 10.394, 10.394, 10.394),
        _seed_phase("mono", 10.41, 10.28, 10.52, beta=90.4),
    )

    def _metrics(rwp: float, gof: float, bic: float, chi2: float, n_params: int) -> RefinementMetrics:
        return RefinementMetrics(
            rwp=rwp, gof=gof, chi2=chi2, n_obs=4200, n_params=n_params, evidence={"bic": bic},
        )

    h014 = Hypothesis(
        id="H-014", phases=phases_h014, metrics=_metrics(6.71, 1.29, 39402.0, 3118.0, 38), status="refined",
    )
    h011 = Hypothesis(
        id="H-011", phases=phases_h011, metrics=_metrics(8.04, 1.35, 41208.0, 3402.0, 30), status="refined",
    )
    h009 = Hypothesis(
        id="H-009", phases=phases_h009, metrics=_metrics(9.86, 1.51, 44120.0, 3811.0, 26), status="refined",
    )

    ranked = (
        RankedHypothesis(
            hypothesis=h014, evidence=EvidenceResult(backend="bic", value=39402.0),
            probability=0.62, close_competitor=True,
        ),
        RankedHypothesis(
            hypothesis=h011, evidence=EvidenceResult(backend="bic", value=41208.0),
            probability=0.33, close_competitor=True,
        ),
        RankedHypothesis(
            hypothesis=h009, evidence=EvidenceResult(backend="bic", value=44120.0),
            probability=0.05, close_competitor=False,
        ),
    )
    unmatched = UnmatchedPeakReport(
        unmatched_observed=(Peak(position=12.42, height=8.1), Peak(position=17.88, height=5.4)),
        extra_calculated=(),
        unknown_phase_flag=True,
    )
    led = Ledger()
    return SearchResult(
        ranked=ranked,
        hypotheses={h.hypothesis.id: h.hypothesis for h in ranked},
        good_cluster_ids=("H-014",),
        alternatives={},
        unmatched=unmatched,
        final_reports={},
        ledger=led,
        snapshots=SnapshotStore(ledger=led),
        warnings=(),
    )


# ---------------------------------------------------------------------------
# viewmodel: PHASE ID
# ---------------------------------------------------------------------------


def seed_phase_id() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "rank": 1, "formula": "KMnFe(CN)6", "source": "MP", "sg": "P21/n",
                "dara": 0.86, "mwmsx": "41/2/1/3", "strain": "0.4%",
                "chem_guard": "ok", "guard_fail": False,
            },
            {
                "rank": 2, "formula": "K2MnFe(CN)6", "source": "MP", "sg": "Fm-3m",
                "dara": 0.81, "mwmsx": "38/3/1/2", "strain": "0.6%",
                "chem_guard": "ok", "guard_fail": False,
            },
            {
                "rank": 3, "formula": "MnFe(CN)6", "source": "MP", "sg": "P4/mnc",
                "dara": 0.52, "mwmsx": "22/5/0/6", "strain": "1.9%",
                "chem_guard": "demoted", "guard_fail": True,
            },
            {
                "rank": 4, "formula": "NaMnFe(CN)6", "source": "MP", "sg": "Fm-3m",
                "dara": 0.31, "mwmsx": "18/9/0/11", "strain": "2.7%",
                "chem_guard": "K missing", "guard_fail": True,
            },
        ],
        "unexplained": [
            {"two_theta": 12.42, "sn": 8.1, "indexing": "unindexed"},
            {"two_theta": 17.88, "sn": 5.4, "indexing": "unindexed"},
        ],
        "completeness": {
            "is_complete": False,
            "notes": ["tetra fraction non-monotonic across fr088–fr101"],
            "flagged_frames": "fr088–fr101",
        },
    }


# ---------------------------------------------------------------------------
# viewmodel: SEQUENCE
# ---------------------------------------------------------------------------


def seed_sequence() -> dict[str, Any]:
    return {
        "charts": [
            {"id": "rwp", "title": "Rwp vs frame"},
            {"id": "lattice", "title": "lattice a/c vs frame"},
            {"id": "phase_fraction", "title": "phase fraction vs frame (x_echem overlay)"},
        ],
        "anchors": [
            {"id": "fr012", "crossover": False},
            {"id": "fr091", "crossover": True},
            {"id": "fr228", "crossover": False},
        ],
        "note": "crossover fr091 · total_bic minimum · x_XRD follows x_echem within esd",
        "segments": [
            {
                "segment": "fr061–fr091", "forward": "cubic+mono", "backward": "cubic+tetra",
                "rwp": "7.9 / 8.0", "total_bic": "41 208 / 39 402", "selected": "backward",
            },
        ],
    }


# ---------------------------------------------------------------------------
# viewmodel: STRUCTURE
# ---------------------------------------------------------------------------


def seed_structure_sites() -> list[dict[str, Any]]:
    def _site(
        sid: str, label: str, el: str, x: str, y: str, z: str, occ: str, uiso: str, note: str,
        *, lock: dict[str, bool], rel: dict[str, bool],
    ) -> dict[str, Any]:
        return {
            "id": sid, "label": label, "el": el, "x": x, "y": y, "z": z,
            "occ": occ, "uiso": uiso, "note": note, "lock": lock, "rel": rel,
        }

    fixed_lock = {"x": True, "y": True, "z": True}
    no_rel = {"x": False, "y": False, "z": False, "occ": False, "uiso": False}
    return [
        _site(
            "s1", "K1", "K", "0.2500", "0.2500", "0.2500", "0.71", "0.0450", "free_occupancy",
            lock=fixed_lock, rel={"x": False, "y": False, "z": False, "occ": True, "uiso": False},
        ),
        _site(
            "s2", "Mn1", "Mn", "0.0000", "0.0000", "0.0000", "1.00", "0.0120", "",
            lock=fixed_lock, rel=no_rel,
        ),
        _site(
            "s3", "Fe1", "Fe", "0.5000", "0.5000", "0.5000", "1.00", "0.0110", "",
            lock=fixed_lock, rel=no_rel,
        ),
        _site(
            "s4", "C1", "C", "0.2000", "0.0000", "0.0000", "1.00", "0.0180", "",
            lock={"x": False, "y": True, "z": True},
            rel={"x": True, "y": False, "z": False, "occ": False, "uiso": True},
        ),
        _site(
            "s5", "N1", "N", "0.3100", "0.0000", "0.0000", "1.00", "0.0200", "",
            lock={"x": False, "y": True, "z": True},
            rel={"x": True, "y": False, "z": False, "occ": False, "uiso": True},
        ),
        _site(
            "s6", "Ow1", "O", "0.5000", "0.2500", "0.0000", "0.174", "0.0500", "zeolitic water",
            lock=fixed_lock, rel={"x": False, "y": False, "z": False, "occ": True, "uiso": True},
        ),
        _site(
            "s7", "D1", "D", "0.5000", "0.2500", "0.0000", "0.174", "0.0500", "equiv → Ow1",
            lock=fixed_lock, rel=no_rel,
        ),
    ]


def seed_structure_constraints() -> list[dict[str, Any]]:
    return [
        {"kind": "EqnConstr", "text": "Σ occ(K1) · Z = x_total(t)", "ref": "FR-318"},
        {"kind": "EquivConstr", "text": "occ(D1) ≡ occ(Ow1)", "ref": ""},
        {"kind": "EquivConstr", "text": "Uiso(D1) ≡ Uiso(Ow1)", "ref": ""},
        {"kind": "parmMin/parmMax", "text": "0 ≤ occ ≤ 1", "ref": ""},
    ]


def seed_mem_peaks() -> list[dict[str, Any]]:
    return [{"position": "(0.5, 0.25, 0.0)", "density": "0.82 fm Å⁻³", "assign": "Ow?"}]


def seed_structure_base_phase() -> PhaseInstance:
    """STRUCTURE タブの初期モデル (``seed_structure_sites`` と occupancy が対応する単一相)。"""
    occupancies = {s["label"]: float(s["occ"]) for s in seed_structure_sites()}
    return PhaseInstance(
        phase_ref="cubic K2Mn[Fe(CN)6]",
        lattice=LatticeParams(a=10.394, b=10.394, c=10.394),
        scale=1.0,
        wt_frac=0.621,
        occupancies=occupancies,
    )


# ---------------------------------------------------------------------------
# viewmodel: STAGES (右ペイン MANUAL の Staged Release Recipe)
# ---------------------------------------------------------------------------


def seed_stages() -> list[dict[str, Any]]:
    return [
        {"nn": "01", "name": "background", "flags": "6→24 terms", "delta_rwp": "−41.2",
         "released": True, "gate": "bkg"},
        {"nn": "02", "name": "scale + cell", "flags": "scale, cell", "delta_rwp": "−6.6",
         "released": True, "gate": None},
        {"nn": "03", "name": "zero", "flags": "zero shift", "delta_rwp": "−2.2",
         "released": True, "gate": None},
        {"nn": "04", "name": "profile U/V/W", "flags": "U, V, W", "delta_rwp": "−4.7",
         "released": True, "gate": "profile"},
        {"nn": "05", "name": "profile X/Y/Zero", "flags": "X, Y, Zero", "delta_rwp": "−2.2",
         "released": True, "gate": "profile"},
        {"nn": "06", "name": "phase fractions", "flags": "scale per phase", "delta_rwp": "−0.31",
         "released": True, "gate": "sample"},
        {"nn": "07", "name": "occupancies", "flags": "K1, Ow1 occ", "delta_rwp": "+0.42 (reverted)",
         "released": False, "gate": "occ"},
        {"nn": "08", "name": "size/microstrain", "flags": "size + mustrain (high-res only)",
         "delta_rwp": "−0.73", "released": True, "gate": "micro"},
    ]


# ---------------------------------------------------------------------------
# review queue (4 seeded items — REQ-GUI-002 / FR-421/423)
# ---------------------------------------------------------------------------


def seed_review_items() -> list[dict[str, Any]]:
    """``ReviewQueue.add`` に渡す 4 項目 + 表示専用メタ (severity/title/ref)。

    ``ReviewItem`` (frozen) は severity/title/ref を持たないため、これらは表示専用メタとして
    ``WorkbenchSession`` 側で ``item_id`` に紐付けて別管理する (P2 の値オブジェクト自体は不変のまま)。
    """
    return [
        {
            "reason": "close_competitor", "hypothesis_id": "H-014", "frame_index": 91,
            "detail": "H-014 vs H-011 ΔlogZ below the 2.5 corroboration threshold.",
            "severity": "close", "title": "close competitor", "ref": "ΔlogZ 1.2",
        },
        {
            "reason": "unknown_phase", "hypothesis_id": None, "frame_index": 91,
            "detail": "Two observed peaks remain unindexed by the current phase set.",
            "severity": "unknown", "title": "unindexed peaks", "ref": "2θ 12.42, 17.88",
        },
        {
            "reason": "guard_escalated", "hypothesis_id": None, "frame_index": None,
            "detail": "Stage 07 occupancy release fired the physical-validity guard 3 consecutive times.",
            "severity": "guard", "title": "guard fired 3×", "ref": "3 consecutive",
        },
        {
            "reason": "incomparable_evidence", "hypothesis_id": None, "frame_index": 92,
            "detail": (
                "Coulometric feasibility gate rejected the two-phase solution at fr092 "
                "(x_XRD outside x_echem ± tolerance)."
            ),
            "severity": "echem", "title": "coulometric feasibility infeasible", "ref": "fr092",
        },
    ]


# ---------------------------------------------------------------------------
# transcript (AUTO の右ペイン — 6 種のメッセージ種を全て含む)
# ---------------------------------------------------------------------------


def seed_transcript() -> list[dict[str, Any]]:
    return [
        {
            "id": "t1", "kind": "user",
            "text": "Check whether the tetra fraction plateau near fr091 is real or a phase-set artifact.",
        },
        {
            "id": "t2", "kind": "agent",
            "text": "Running residual_report and check_phase_set on fr088–fr101 before touching PARAMETERS.",
        },
        {
            "id": "t3", "kind": "tool", "tool": "check_phase_set", "layer": "MCP ②", "secs": 1.8,
            "args": '{"anchor_table": {"fr088": ["cubic", "mono"], "fr101": ["cubic", "tetra"]}}',
            "ret": '{"is_complete": false, "notes": ["tetra fraction non-monotonic"], '
                   '"flagged_frames": "fr088–fr101"}',
        },
        {
            "id": "t4", "kind": "tool", "tool": "residual_report", "layer": "MCP ②", "secs": 0.9,
            "args": '{"frame": "fr091", "two_theta_limits": [4.0, 38.0]}',
            "ret": '{"unexplained": [{"two_theta": 12.42, "sn": 8.1}, {"two_theta": 17.88, "sn": 5.4}]}',
        },
        {
            "id": "t5", "kind": "tool", "tool": "identify_phases", "layer": "MCP ②", "secs": 3.4,
            "args": '{"elements": ["K", "Mn", "Fe", "C", "N"], "two_theta": [12.42, 17.88]}',
            "ret": '{"candidates": [{"formula": "KMnFe(CN)6", "dara": 0.86}]}',
        },
        {
            "id": "t6", "kind": "judgement", "text": "Rwp falls with every added phase; segment total_bic is the criterion.",
            "rows": [
                {"label": "cubic + tetragonal", "rwp": 8.04, "bic": 41208, "chosen": False},
                {"label": "cubic + mono + tetra", "rwp": 6.71, "bic": 39402, "chosen": True},
            ],
        },
        {
            "id": "t7", "kind": "approval", "action_id": "a1",
            "title": "Add tetragonal phase to fr088–fr101 (ModelAction)",
            "rationale": "check_phase_set flags non-monotonic tetra fraction; identify_phases confirms a matching candidate.",
            "action_json": '{"tool": "identify_and_add_phase", "frame_range": "fr088-fr101", "phase": "tetragonal"}',
            "state": "pending",
        },
        {
            "id": "t8", "kind": "escalation", "fr": "FR-403",
            "text": "close_competitor (ΔlogZ 1.2 < 2.5) — provisional ranking kept, review queue notified.",
        },
    ]
