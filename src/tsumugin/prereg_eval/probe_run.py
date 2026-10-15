"""P0 §5: 反証プローブを保存した gpx に当てる (GSAS は遅延 import)。

保存した最終 gpx の**写し**を開き、既定が止めていた母数のフラグを足して精密化し直す (保存した成果物は書き換えない)。
小さい模型 = 元の fit、大きい模型 = 足した fit。判定量は Hamilton の ``Δχ²/GOF²_big``、k = 増えた変数の数、
λ は大きい模型の共分散のうち増えた変数の部分 Σ₂₂ と、登録した効果量 Δ (`probes`) から。

Δ は GSAS の変数の単位に写す: ゼロ点は度、座標 ``dAx`` は分率 (軸の長さで割る)、Uiso は Å²。格子は逆格子計量テンソルの
項 ``A0..A5`` で精密化されるので、独立な格子定数ごとの 0.5% を ``A`` の変化に直し (ヤコビアンの列)、軸ごとの符号の
組み合わせのうち λ が最小のものを採る。
"""

from __future__ import annotations

import itertools
import math
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .probes import PROBES, classify, delta_uiso, delta_zero, power

__all__ = ["ProbeOutcome", "run_probe"]

_CELL_FRAC = 0.005
_COORD_ANG = 0.02


@dataclass(frozen=True)
class ProbeOutcome:
    probe_id: str
    phase: str | None
    k: int
    statistic: float | None
    gof2: float | None
    lam: float | None
    power: float | None
    alpha: float
    outcome: str
    chi2_small: float | None = None
    chi2_big: float | None = None


def _chi2(gpx) -> tuple[float | None, float | None, list[str]]:
    cov = gpx.data["Covariance"]["data"]
    rv = cov.get("Rvals", {}) or {}
    names = list(cov.get("varyList", []) or [])
    try:
        gof = float(rv["GOF"])
        n_obs = int(rv["Nobs"])
    except (KeyError, TypeError, ValueError):
        return None, None, names
    if not math.isfinite(gof) or n_obs - len(names) <= 0:
        return None, None, names
    return gof**2 * (n_obs - len(names)), gof**2, names


def _phase(gpx, name: str):
    for ph in gpx.phases():
        if ph.name == name:
            return ph
    raise KeyError(f"相 {name!r} が gpx に無い")


def _add_atom_flag(ph, flag: str) -> None:
    general = ph.data["General"]
    _cx, ct, _cs, _cia = general["AtomPtrs"]
    for row in ph.data["Atoms"]:
        flags = str(row[ct + 1])
        if flag not in flags:
            row[ct + 1] = flags + flag


def _ungroup_uiso(gpx, ph) -> int:
    """対象相の Uiso の等値拘束を外す (共位置の原子 = 混合占有の席どうしの拘束は残す — 同じ席の Uiso は物理)。外した数。

    拘束の変数は `G2VarObj` で、相と原子はランダム ID で指す (読み込んだだけの gpx では名前が ``?::AUiso:?`` のまま) —
    engine の `_coord_constrained_axes` と同じく ``var.phase`` / ``var.atom`` / ``var.name`` で照合する。
    """
    phase_rid = ph.data["ranId"]
    general = ph.data["General"]
    cx, _ct, _cs, cia = (int(v) for v in general["AtomPtrs"])
    pos = {row[cia + 8]: tuple(round(float(v), 6) for v in row[cx:cx + 3]) for row in ph.data["Atoms"]}
    kept, removed = [], 0
    for con in gpx.data["Constraints"]["data"].get("Phase", []):
        kind = con[-1] if con and isinstance(con[-1], str) else ""
        terms = [t[1] for t in con if isinstance(t, (list, tuple)) and len(t) >= 2]
        uiso_atoms = [
            getattr(v, "atom", None) for v in terms
            if getattr(v, "phase", None) == phase_rid and str(getattr(v, "name", "")) == "AUiso"
        ]
        if kind == "e" and terms and len(uiso_atoms) == len(terms):
            if len({pos.get(a) for a in uiso_atoms}) > 1:  # 位置の違う原子をまとめた組 = テンプレートの選択
                removed += 1
                continue
        kept.append(con)
    gpx.data["Constraints"]["data"]["Phase"] = kept
    return removed


def _release(gpx, probe_id: str, phase: str | None) -> None:
    if probe_id == "zero_fixed":
        for h in gpx.histograms():
            h.set_refinements({"Instrument Parameters": ["Zero"]})
    elif probe_id == "minor_cell_frozen":
        _phase(gpx, phase).set_refinements({"Cell": True})  # type: ignore[arg-type]
    elif probe_id == "minor_coords_frozen":
        _add_atom_flag(_phase(gpx, phase), "X")  # type: ignore[arg-type]
    elif probe_id == "minor_uiso_frozen":
        _add_atom_flag(_phase(gpx, phase), "U")  # type: ignore[arg-type]
    elif probe_id == "uiso_grouping":
        ph = _phase(gpx, phase)  # type: ignore[arg-type]
        if _ungroup_uiso(gpx, ph) == 0:
            raise ValueError("no Uiso grouping to undo")
        _add_atom_flag(ph, "U")
    else:
        raise ValueError(f"実行できないプローブ: {probe_id!r}")


def _delta_columns(gpx, added: list[str], probe_id: str, phase: str | None) -> list[np.ndarray] | None:
    """Δ を「符号を独立に選べる列」の並びで返す (列の符号付き和が Δ)。写せなければ None。"""
    if probe_id == "zero_fixed":
        return [np.array([delta_zero()[0] if n.endswith(":Zero") else 0.0 for n in added])]
    ph = _phase(gpx, phase)  # type: ignore[arg-type]
    if probe_id in ("minor_coords_frozen", "minor_uiso_frozen", "uiso_grouping"):
        cell = ph.data["General"]["Cell"][1:4]
        cols = []
        for i, n in enumerate(added):
            v = np.zeros(len(added))
            if probe_id == "minor_coords_frozen" and ":dA" in n:
                axis = "xyz".index(n.split(":dA")[1][0])
                v[i] = _COORD_ANG / float(cell[axis])
            elif probe_id in ("minor_uiso_frozen", "uiso_grouping") and ":AUiso:" in n:
                v[i] = delta_uiso(1)[0]
            else:
                return None
            cols.append(v)
        return cols
    if probe_id == "minor_cell_frozen":
        from GSASII import GSASIIlattice as G2lat

        cell = [float(x) for x in ph.data["General"]["Cell"][1:7]]
        a0 = np.asarray(G2lat.cell2A(cell))
        idx = [int(n.split("::A")[1]) for n in added if "::A" in n]
        if len(idx) != len(added):
            return None
        cols = []
        for axis in range(3):  # a, b, c (角度は直方以外で足す — 下)
            c2 = list(cell)
            c2[axis] *= 1.0 + _CELL_FRAC
            col = (np.asarray(G2lat.cell2A(c2)) - a0)[idx]
            if np.any(np.abs(col) > 0):
                cols.append(col)
        return cols
    return None


def _min_lambda(cols: list[np.ndarray], cov22: np.ndarray) -> float:
    best = math.inf
    for signs in itertools.product((1.0, -1.0), repeat=max(len(cols) - 1, 0)):
        v = cols[0] + sum(s * c for s, c in zip(signs, cols[1:]))
        best = min(best, float(v @ np.linalg.solve(cov22, v)))
    return best


def run_probe(
    gpx_path: str, probe_id: str, *, phase: str | None = None, alpha: float = 0.01, max_cyc: int = 12
) -> ProbeOutcome:
    """保存した gpx に反証プローブを 1 つ当てる。失敗は ``unevaluated(<理由>)`` に畳む (例外にしない)。"""
    if probe_id not in PROBES:
        raise ValueError(f"未登録のプローブ: {probe_id!r}")

    def fail(reason: str) -> ProbeOutcome:
        return ProbeOutcome(probe_id, phase, 0, None, None, None, None, alpha, f"unevaluated({reason})")

    try:
        from ..autorietveld.engine import _g2sc, _refine_once
    except Exception as exc:  # noqa: BLE001
        return fail(f"gsas unavailable: {type(exc).__name__}")
    g2sc = _g2sc()
    with tempfile.TemporaryDirectory(prefix="tsumugin-falsify-") as tmp:
        copy = Path(tmp) / "falsify.gpx"
        shutil.copyfile(gpx_path, copy)
        gpx = g2sc.G2Project(gpxfile=str(copy))
        chi2_small, _, vary_small = _chi2(gpx)
        if chi2_small is None:
            return fail("no covariance in the saved fit")
        try:
            _release(gpx, probe_id, phase)
            gpx.data["Controls"]["data"]["max cyc"] = int(max_cyc)
            _refine_once(gpx)
        except Exception as exc:  # noqa: BLE001 — 反証の fit の失敗は unevaluated (P0 §5.3)
            return fail(f"{type(exc).__name__}: {exc}"[:200])
        chi2_big, gof2_big, vary_big = _chi2(gpx)
        if chi2_big is None or gof2_big is None:
            return fail("non-finite fit")
        added = [n for n in vary_big if n not in set(vary_small)]
        if not added:
            return fail("no parameter was added")
        cov = np.asarray(gpx.data["Covariance"]["data"].get("covMatrix"), dtype=float)
        idx = [vary_big.index(n) for n in added]
        if cov.ndim != 2 or cov.shape[0] != len(vary_big):
            return fail("covariance shape")
        cov22 = cov[np.ix_(idx, idx)]
        cols = _delta_columns(gpx, added, probe_id, phase)
        if not cols:
            return fail("cannot map the effect size to the added variables")
        try:
            lam = _min_lambda(cols, cov22)
        except np.linalg.LinAlgError:
            return fail("singular covariance")
    k = len(added)
    statistic = (chi2_small - chi2_big) / gof2_big
    pw = power(lam, k=k, alpha=alpha) if math.isfinite(lam) else None
    return ProbeOutcome(probe_id, phase, k, statistic, gof2_big, lam, pw, alpha,
                        classify(statistic=statistic, lam=lam, k=k, alpha=alpha),
                        chi2_small=chi2_small, chi2_big=chi2_big)
